import discord
from discord.ext import commands, tasks
import json
import asyncio
import aiohttp
import time
import re
from pathlib import Path
from datetime import datetime, timezone

MONITORS_FILE = "monitors.json"

VINTED_DOMAINS = {
    "de": "vinted.de", "at": "vinted.at", "fr": "vinted.fr",
    "nl": "vinted.nl", "be": "vinted.be", "pl": "vinted.pl",
    "es": "vinted.es", "it": "vinted.it", "cz": "vinted.cz",
    "uk": "vinted.co.uk", "com": "vinted.com", "lt": "vinted.lt",
    "lu": "vinted.lu", "se": "vinted.se", "fi": "vinted.fi",
    "dk": "vinted.dk", "ro": "vinted.ro", "sk": "vinted.sk",
    "hu": "vinted.hu", "hr": "vinted.hr", "pt": "vinted.pt",
    "gr": "vinted.gr",
}

def load_monitors():
    if Path(MONITORS_FILE).exists():
        with open(MONITORS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_monitors(monitors):
    with open(MONITORS_FILE, "w") as f:
        json.dump(monitors, f, indent=2)

def time_ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"vor {seconds} Sekunden"
    elif seconds < 3600:
        return f"vor {seconds // 60} Minuten"
    elif seconds < 86400:
        return f"vor {seconds // 3600} Stunden"
    else:
        return f"vor {seconds // 86400} Tagen"

def resell_price(price_str):
    try:
        price = float(str(price_str).replace(",", "."))
        low = round(price * 1.3)
        high = round(price * 1.6)
        return f"~{low}€ – {high}€"
    except:
        return "?"

def parse_created_ts(val, now_ts):
    if val is None:
        return 0, "Unbekannt"
    try:
        if isinstance(val, str) and val:
            val = val.replace(" ", "T")
            if "+" not in val and "Z" not in val:
                val += "+00:00"
            dt = datetime.fromisoformat(val)
            ts = dt.timestamp()
            return ts, time_ago(now_ts - ts)
        elif isinstance(val, (int, float)):
            return float(val), time_ago(now_ts - float(val))
        elif hasattr(val, "timestamp"):
            ts = val.timestamp()
            return ts, time_ago(now_ts - ts)
    except Exception as e:
        print(f"parse_created_ts error: {e}")
    return 0, "Unbekannt"


class VintedSession:
    def __init__(self):
        self.session = None
        self.cookie_ts = {}

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_cookies(self, domain):
        now = time.time()
        if now - self.cookie_ts.get(domain, 0) < 600:
            return
        base = VINTED_DOMAINS.get(domain, "vinted.de")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            session = await self.get_session()
            async with session.get(f"https://www.{base}/", headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                self.cookie_ts[domain] = now
                print(f"Cookies refreshed for {domain}: {r.status}")
        except Exception as e:
            print(f"Cookie error: {e}")

    async def search(self, domain, query="", brand_ids=None, price_from=None,
                     price_to=None, size_ids=None, status_ids=None, catalog_ids=None):
        await self.get_cookies(domain)
        base = VINTED_DOMAINS.get(domain, "vinted.de")

        params = [
            ("search_text", query),
            ("order", "newest_first"),
            ("per_page", "96"),
            ("page", "1"),
            ("time", str(int(time.time()))),
        ]
        for bid in (brand_ids or []):
            params.append(("brand_ids[]", str(bid)))
        for sid in (size_ids or []):
            params.append(("size_ids[]", str(sid)))
        for sid in (status_ids or []):
            params.append(("status_ids[]", str(sid)))
        for cid in (catalog_ids or []):
            params.append(("catalog_ids[]", str(cid)))
        if price_from is not None:
            params.append(("price_from", str(price_from)))
        if price_to is not None:
            params.append(("price_to", str(price_to)))

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": f"https://www.{base}/catalog",
            "X-Requested-With": "XMLHttpRequest",
        }

        url = f"https://www.{base}/api/v2/catalog/items"
        try:
            session = await self.get_session()
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                print(f"Search [{domain}]: {r.status}")
                if r.status == 200:
                    data = await r.json()
                    items = data.get("items", [])
                    print(f"Items: {len(items)}")
                    return items
                elif r.status in (401, 403):
                    self.cookie_ts[domain] = 0
                    return []
                return []
        except Exception as e:
            print(f"Search error: {e}")
            return []


vinted = VintedSession()


class MonitorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitors = load_monitors()
        self.monitor_loop.start()

    def cog_unload(self):
        self.monitor_loop.cancel()

    @tasks.loop(seconds=3)
    async def monitor_loop(self):
        for channel_id, mon in list(self.monitors.items()):
            if not mon.get("active", False):
                continue
            try:
                await self._check_monitor(channel_id, mon)
            except Exception as e:
                print(f"Monitor error [{channel_id}]: {e}")

    @monitor_loop.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()
        print("Monitor loop gestartet!")

    async def _check_monitor(self, channel_id, mon):
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return
        f = mon.get("filters", {})
        domain = f.get("domain", "de")
        start_ts = float(mon.get("start_ts", time.time()))
        now_ts = time.time()

        raw_items = await vinted.search(
            domain=domain, query=f.get("query", ""),
            brand_ids=f.get("brand_ids", []), price_from=f.get("price_from"),
            price_to=f.get("price_to"), size_ids=f.get("size_ids", []),
            status_ids=f.get("status_ids", []), catalog_ids=f.get("catalog_ids", []),
        )

        seen_ids = set(mon.get("seen_ids", []))
        new_items = []

        for raw in raw_items:
            item_id = str(raw.get("id", ""))
            if not item_id or item_id in seen_ids:
                seen_ids.add(item_id)
                continue
            seen_ids.add(item_id)

            # Parse created_at
            # Print ALL keys of first item to find date field
            if len(seen_ids) <= 2:
                print(f"DEBUG ALL KEYS: {list(raw.keys())}")
                print(f"DEBUG FULL ITEM: {raw}")
            created_val = None
            for field in ["created_at_ts", "created_at", "updated_at_ts", "updated_at", "last_push_up_at", "photo"]:
                v = raw.get(field)
                if v is not None:
                    print(f"DEBUG field {field} = {str(v)[:80]}")
            created_val = raw.get("created_at_ts") or raw.get("created_at") or raw.get("updated_at_ts") or raw.get("updated_at")
            created_ts, created_str = parse_created_ts(created_val, now_ts)

            # Only show if created after monitor start
            if created_ts > 0 and created_ts < start_ts:
                continue

            # Build item dict
            user = raw.get("user", {}) or {}
            photo = raw.get("photo", {}) or {}
            photo_url = ""
            if isinstance(photo, dict):
                thumbs = photo.get("thumbnails", [])
                photo_url = thumbs[-1].get("url", "") if thumbs else photo.get("url", "")
            elif isinstance(photo, str):
                photo_url = photo

            new_items.append({
                "id": item_id,
                "title": raw.get("title", "Unbekannt"),
                "price": str(raw["price"]["amount"] if isinstance(raw.get("price"), dict) else raw.get("price", "?")),
                "total_item_price": str(raw["total_item_price"]["amount"] if isinstance(raw.get("total_item_price"), dict) else raw.get("total_item_price", raw.get("price", "?"))),
                "currency": str(raw["price"]["currency_code"] if isinstance(raw.get("price"), dict) else raw.get("currency", "EUR")),
                "brand_title": raw.get("brand_title", ""),
                "size_title": raw.get("size_title", ""),
                "status": raw.get("status", ""),
                "url": raw.get("url", ""),

                "photo_url": photo_url,
                "created_str": created_str,
                "user_login": user.get("login", "?"),
                "user_id": str(user.get("id", "")),
                "feedback_count": str(user.get("feedback_count", "") or ""),
            })

        mon["seen_ids"] = list(seen_ids)[-5000:]
        self.monitors[channel_id] = mon
        save_monitors(self.monitors)

        for item in new_items[:5]:
            embed = self._build_embed(item, domain)
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Send error: {e}")

    def _build_embed(self, item, domain):
        base = VINTED_DOMAINS.get(domain, "vinted.de")
        title = item.get("title", "Unbekannt")
        price = item.get("price", "?")
        total_price = item.get("total_item_price", price)
        brand = item.get("brand_title", "")
        size = item.get("size_title", "")
        condition = item.get("status", "")
        created_str = item.get("created_str", "Gerade eben")
        seller = item.get("user_login", "?")
        seller_id = item.get("user_id", "")
        feedback_count = item.get("feedback_count", "")
        url = item.get("url", "")
        if not url:
            item_id = item.get("id", "")
            slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:40]
            url = f"https://www.{base}/items/{item_id}-{slug}"

        sym = {"EUR": "€", "GBP": "£", "PLN": "zl", "CZK": "Kc"}.get(item.get("currency", "EUR"), "€")
        color_map = {"Neu": 0x00C853, "Sehr gut": 0x2196F3, "Gut": 0xFF9800,
                     "New": 0x00C853, "Very good": 0x2196F3, "Good": 0xFF9800}
        color = color_map.get(condition, 0x09B1BA)

        embed = discord.Embed(title=f"🛍️ {title}", url=url, color=color)
        embed.add_field(name="💰 Kaufpreis", value=f"**{price} {sym}**\n(+Versand: {total_price} {sym})", inline=True)
        embed.add_field(name="📈 Wiederverkauf", value=resell_price(price), inline=True)
        if brand:
            embed.add_field(name="🏷️ Marke", value=brand, inline=True)
        if size:
            embed.add_field(name="📏 Größe", value=size, inline=True)
        if condition:
            embed.add_field(name="✨ Zustand", value=condition, inline=True)
        embed.add_field(name="🕐 Hochgeladen", value=created_str, inline=True)

        seller_val = f"[{seller}](https://www.{base}/members/{seller_id})" if seller_id else seller
        if feedback_count:
            seller_val += f"\n⭐ {feedback_count} Bewertungen"
        embed.add_field(name="👤 Verkäufer", value=seller_val, inline=True)
        embed.add_field(name="🔗 Zum Artikel", value=f"[➜ Jetzt ansehen]({url})", inline=False)

        if item.get("photo_url"):
            embed.set_image(url=item["photo_url"])

        embed.set_footer(text=f"vinted.{domain} • {time.strftime('%H:%M:%S')}")
        return embed

    @commands.command(name="add")
    async def add_monitor(self, ctx, *, name: str = "Monitor"):
        channel_id = str(ctx.channel.id)
        if channel_id in self.monitors and self.monitors[channel_id].get("active"):
            await ctx.send("⚠️ Läuft bereits. Stoppe zuerst mit `!stop`.")
            return
        self.monitors[channel_id] = {"name": name, "active": False, "seen_ids": [], "filters": {"domain": "de"}}
        save_monitors(self.monitors)
        await ctx.send(f"✅ Monitor **{name}** erstellt!\n```\n!setdomain de\n!setquery <Begriff>\n!setbrand <Marke>\n!setprice <min> <max>\n!setsize <Größe>\n!start\n```")

    @commands.command(name="setquery")
    async def set_query(self, ctx, *, query: str):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        self.monitors[channel_id]["filters"]["query"] = query
        save_monitors(self.monitors)
        await ctx.send(f"✅ Suchbegriff: **{query}**")

    @commands.command(name="setbrand")
    async def set_brand(self, ctx, *, brand: str):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        brand_map = {
            "nike": 53, "adidas": 14, "zara": 2, "h&m": 6, "puma": 11,
            "gucci": 38, "louis vuitton": 46, "supreme": 225, "stone island": 308,
            "north face": 25, "levis": 62, "ralph lauren": 88,
            "tommy hilfiger": 68, "calvin klein": 78, "balenciaga": 82,
            "off-white": 428, "jordan": 14020, "new balance": 291,
            "converse": 257, "vans": 134, "champion": 109, "carhartt": 399,
            "stussy": 567, "moncler": 159, "burberry": 105,
            "versace": 100, "prada": 94, "chanel": 148, "dior": 142,
        }
        brands = [b.strip() for b in brand.split(",")]
        brand_ids = [brand_map[b.lower()] for b in brands if b.lower() in brand_map]
        self.monitors[channel_id]["filters"]["brand_ids"] = brand_ids
        self.monitors[channel_id]["filters"]["brand_names"] = brands
        save_monitors(self.monitors)
        await ctx.send(f"✅ Marke(n): **{', '.join(brands)}**")

    @commands.command(name="setprice")
    async def set_price(self, ctx, min_price: str = None, max_price: str = None):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        try:
            pmin = float(min_price) if min_price and min_price != "-" else None
            pmax = float(max_price) if max_price and max_price != "-" else None
        except ValueError:
            await ctx.send("❌ Beispiel: `!setprice 10 50`")
            return
        self.monitors[channel_id]["filters"]["price_from"] = pmin
        self.monitors[channel_id]["filters"]["price_to"] = pmax
        save_monitors(self.monitors)
        await ctx.send(f"✅ Preis: **{pmin or 0}€ – {pmax or chr(8734)}€**")

    @commands.command(name="setsize")
    async def set_size(self, ctx, *, size: str):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        size_map = {"xxs": 102, "xs": 103, "s": 104, "m": 1324, "l": 105, "xl": 106, "xxl": 1325,
                    "36": 1349, "37": 1350, "38": 1351, "39": 1352, "40": 1353,
                    "41": 1354, "42": 1355, "43": 1356, "44": 1357, "45": 1358}
        sizes = [s.strip() for s in size.split(",")]
        size_ids = [size_map[s.lower()] for s in sizes if s.lower() in size_map]
        self.monitors[channel_id]["filters"]["size_ids"] = size_ids
        self.monitors[channel_id]["filters"]["size_names"] = sizes
        save_monitors(self.monitors)
        await ctx.send(f"✅ Größe: **{', '.join(sizes)}**")

    @commands.command(name="setdomain")
    async def set_domain(self, ctx, domain: str = "de"):
        channel_id = str(ctx.channel.id)
        domain = domain.lower()
        if domain not in VINTED_DOMAINS:
            await ctx.send(f"❌ Verfügbar: `{', '.join(VINTED_DOMAINS.keys())}`")
            return
        self._ensure_monitor(channel_id)
        self.monitors[channel_id]["filters"]["domain"] = domain
        save_monitors(self.monitors)
        await ctx.send(f"✅ Domain: **vinted.{domain}**")

    @commands.command(name="setcondition")
    async def set_condition(self, ctx, *, condition: str):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        condition_map = {"new": [6], "neu": [6], "very_good": [3], "good": [4], "gut": [4], "satisfactory": [1]}
        cids = condition_map.get(condition.lower(), [])
        self.monitors[channel_id]["filters"]["status_ids"] = cids
        self.monitors[channel_id]["filters"]["condition_name"] = condition
        save_monitors(self.monitors)
        await ctx.send(f"✅ Zustand: **{condition}**")

    @commands.command(name="setcategory")
    async def set_category(self, ctx, *, category: str):
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        cat_map = {"men": [4], "herren": [4], "women": [1], "damen": [1], "kids": [306],
                   "shoes": [16], "schuhe": [16], "bags": [12], "sport": [76],
                   "electronics": [2485], "home": [1231], "beauty": [2350]}
        cid = cat_map.get(category.lower(), [])
        self.monitors[channel_id]["filters"]["catalog_ids"] = cid
        self.monitors[channel_id]["filters"]["category_name"] = category
        save_monitors(self.monitors)
        await ctx.send(f"✅ Kategorie: **{category}**")

    @commands.command(name="start")
    async def start_monitor(self, ctx):
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Erst `!add <n>` benutzen.")
            return
        f = self.monitors[channel_id].get("filters", {})
        if not f.get("query") and not f.get("brand_ids"):
            await ctx.send("⚠️ Setze mindestens: `!setquery <Begriff>`")
            return
        self.monitors[channel_id]["active"] = True
        self.monitors[channel_id]["seen_ids"] = []
        self.monitors[channel_id]["start_ts"] = time.time()
        save_monitors(self.monitors)
        embed = discord.Embed(title="✅ Monitor gestartet!", color=0x00C853,
                              description="Nur Artikel die **jetzt neu** eingestellt werden kommen rein!")
        embed.add_field(name="🌍 Domain", value=f"vinted.{f.get('domain','de')}", inline=True)
        if f.get("query"):
            embed.add_field(name="🔍 Suche", value=f["query"], inline=True)
        if f.get("brand_names"):
            embed.add_field(name="🏷️ Marke", value=", ".join(f["brand_names"]), inline=True)
        embed.set_footer(text="Prüft alle 3 Sekunden • !stop zum Stoppen")
        await ctx.send(embed=embed)

    @commands.command(name="stop")
    async def stop_monitor(self, ctx):
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Kein Monitor hier.")
            return
        self.monitors[channel_id]["active"] = False
        save_monitors(self.monitors)
        await ctx.send("🛑 Monitor gestoppt.")

    @commands.command(name="filters")
    async def show_filters(self, ctx):
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Kein Monitor. Nutze `!add <n>`.")
            return
        mon = self.monitors[channel_id]
        f = mon.get("filters", {})
        active = mon.get("active", False)
        embed = discord.Embed(title=f"📋 {mon.get('name','Monitor')}", color=0x09B1BA if active else 0x888888)
        embed.add_field(name="Status", value="🟢 Aktiv" if active else "🔴 Gestoppt", inline=True)
        embed.add_field(name="🌍 Domain", value=f"vinted.{f.get('domain','de')}", inline=True)
        if f.get("query"):
            embed.add_field(name="🔍 Suche", value=f["query"], inline=True)
        if f.get("brand_names"):
            embed.add_field(name="🏷️ Marke", value=", ".join(f["brand_names"]), inline=True)
        if f.get("size_names"):
            embed.add_field(name="📏 Größe", value=", ".join(f["size_names"]), inline=True)
        pmin, pmax = f.get("price_from"), f.get("price_to")
        if pmin is not None or pmax is not None:
            embed.add_field(name="💰 Preis", value=f"{pmin or 0}€ – {pmax or chr(8734)}€", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="reset")
    async def reset_monitor(self, ctx):
        channel_id = str(ctx.channel.id)
        if channel_id in self.monitors:
            name = self.monitors[channel_id].get("name", "Monitor")
            self.monitors[channel_id] = {"name": name, "active": False, "seen_ids": [], "filters": {"domain": "de"}}
            save_monitors(self.monitors)
        await ctx.send("🔄 Monitor zurückgesetzt.")

    @commands.command(name="monitors")
    async def list_monitors(self, ctx):
        guild_channels = [str(ch.id) for ch in ctx.guild.channels]
        active = [(cid, m) for cid, m in self.monitors.items() if cid in guild_channels]
        if not active:
            await ctx.send("📭 Keine Monitore auf diesem Server.")
            return
        embed = discord.Embed(title="📊 Alle Monitore", color=0x09B1BA)
        for cid, mon in active:
            ch = self.bot.get_channel(int(cid))
            ch_name = ch.mention if ch else f"#{cid}"
            status = "🟢" if mon.get("active") else "🔴"
            embed.add_field(name=f"{status} {mon.get('name','Monitor')}",
                            value=f"Channel: {ch_name}\nSuche: `{mon.get('filters',{}).get('query','-')}`", inline=True)
        await ctx.send(embed=embed)

    def _ensure_monitor(self, channel_id):
        if channel_id not in self.monitors:
            self.monitors[channel_id] = {"name": "Monitor", "active": False, "seen_ids": [], "filters": {"domain": "de"}}


async def setup(bot):
    await bot.add_cog(MonitorCog(bot))
