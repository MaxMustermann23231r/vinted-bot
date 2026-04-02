import discord
from discord.ext import commands, tasks
import json
import asyncio
import time
import re
from pathlib import Path

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


async def vinted_search(domain, query="", brand_ids=None, price_from=None, price_to=None, size_ids=None, status_ids=None, catalog_ids=None):
    """Search using vinted-api-kit library"""
    try:
        from vinted import VintedClient
        base_domain = VINTED_DOMAINS.get(domain, "vinted.de")
        
        # Build URL with filters
        url = f"https://www.{base_domain}/catalog?"
        params = []
        if query:
            params.append(f"search_text={query.replace(' ', '+')}")
        for bid in (brand_ids or []):
            params.append(f"brand_ids[]={bid}")
        for sid in (size_ids or []):
            params.append(f"size_ids[]={sid}")
        for sid in (status_ids or []):
            params.append(f"status_ids[]={sid}")
        for cid in (catalog_ids or []):
            params.append(f"catalog_ids[]={cid}")
        if price_from is not None:
            params.append(f"price_from={price_from}")
        if price_to is not None:
            params.append(f"price_to={price_to}")
        
        url += "&".join(params)
        print(f"Searching: {url}")
        
        async with VintedClient(persist_cookies=True, cookies_dir=Path("./cookies"), storage_format="json") as client:
            items = await client.search_items(url=url, per_page=96)
            print(f"Found {len(items)} items")
            # Convert to dict format
            result = []
            for item in items:
                result.append({
                    "id": str(item.id),
                    "title": item.title,
                    "price": str(item.price),
                    "total_item_price": str(item.total_item_price) if hasattr(item, "total_item_price") else str(item.price),
                    "brand_title": item.brand_title if hasattr(item, "brand_title") else "",
                    "size_title": item.size_title if hasattr(item, "size_title") else "",
                    "url": item.url if hasattr(item, "url") else "",
                    "currency": item.currency if hasattr(item, "currency") else "EUR",
                    "photo_url": (item.photo.url if hasattr(item.photo, "url") else str(item.photo)) if hasattr(item, "photo") and item.photo else "",

                    "user": {
                        "login": item.user.login if hasattr(item, "user") and item.user else "?",
                        "id": str(item.user.id) if hasattr(item, "user") and item.user else ""
                    }
                })
            return result
    except Exception as e:
        print(f"vinted-api-kit error: {e}")
        return []


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
        items = await vinted_search(
            domain=domain, query=f.get("query", ""),
            brand_ids=f.get("brand_ids", []), price_from=f.get("price_from"),
            price_to=f.get("price_to"), size_ids=f.get("size_ids", []),
            status_ids=f.get("status_ids", []), catalog_ids=f.get("catalog_ids", []),
        )
        seen_ids = set(mon.get("seen_ids", []))
        new_items = []

        for i in items:
            item_id = str(i.get("id", ""))
            if item_id not in seen_ids:
                new_items.append(i)
            seen_ids.add(item_id)
        
        # Keep only last 5000 seen ids
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
        url = item.get("url", "")
        if not url:
            item_id = item.get("id", "")
            slug = re.sub(r"[^a-z0-9\-]", "", title.lower().replace(" ", "-"))[:40]
            url = f"https://www.{base}/items/{item_id}-{slug}"
        user = item.get("user", {})
        seller = user.get("login", "?")
        seller_id = user.get("id", "")
        currency = item.get("currency", "EUR")
        sym = {"EUR": "euro", "GBP": "GBP", "PLN": "PLN", "CZK": "CZK"}.get(currency, "euro")
        sym2 = {"EUR": "€", "GBP": "£", "PLN": "zł", "CZK": "Kč"}.get(currency, "€")

        embed = discord.Embed(title=f"🛍️ {title}", url=url, color=0x09B1BA)
        embed.add_field(name="💰 Preis", value=f"**{price} {sym2}** (gesamt: {total_price} {sym2})", inline=True)
        if brand:
            embed.add_field(name="🏷️ Marke", value=brand, inline=True)
        if size:
            embed.add_field(name="📏 Größe", value=size, inline=True)
        embed.add_field(name="👤 Verkäufer", value=f"[{seller}](https://www.{base}/members/{seller_id})" if seller_id else seller, inline=True)
        embed.add_field(name="🔗 Zum Artikel", value=f"[➜ Hier kaufen]({url})", inline=False)

        photo_url = item.get("photo_url", "")
        if photo_url:
            embed.set_image(url=photo_url)

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
        self.monitors[channel_id]["max_seen_id"] = 0
        save_monitors(self.monitors)
        embed = discord.Embed(title="✅ Monitor gestartet!", color=0x00C853)
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
            embed.add_field(name=f"{status} {mon.get('name','Monitor')}", value=f"Channel: {ch_name}\nSuche: `{mon.get('filters',{}).get('query','-')}`", inline=True)
        await ctx.send(embed=embed)

    def _ensure_monitor(self, channel_id):
        if channel_id not in self.monitors:
            self.monitors[channel_id] = {"name": "Monitor", "active": False, "seen_ids": [], "filters": {"domain": "de"}}


async def setup(bot):
    await bot.add_cog(MonitorCog(bot))
