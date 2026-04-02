import discord
from discord.ext import commands, tasks
import json
import asyncio
import time
from pathlib import Path
from vinted_api import VintedAPI, build_item_url, VINTED_DOMAINS

MONITORS_FILE = "monitors.json"

def load_monitors():
    if Path(MONITORS_FILE).exists():
        with open(MONITORS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_monitors(monitors):
    with open(MONITORS_FILE, "w") as f:
        json.dump(monitors, f, indent=2)

# monitors[channel_id] = { "filters": {...}, "seen_ids": [...], "active": bool, "name": str }

class MonitorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitors = load_monitors()
        self.vinted_clients = {}  # domain -> VintedAPI
        self.monitor_loop.start()

    def cog_unload(self):
        self.monitor_loop.cancel()

    def get_client(self, domain: str) -> VintedAPI:
        if domain not in self.vinted_clients:
            self.vinted_clients[domain] = VintedAPI(domain)
        return self.vinted_clients[domain]

    @tasks.loop(seconds=30)
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

    async def _check_monitor(self, channel_id: str, mon: dict):
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return

        filters = mon.get("filters", {})
        domain = filters.get("domain", "de")
        client = self.get_client(domain)
        base_url = VINTED_DOMAINS.get(domain, VINTED_DOMAINS["de"])

        result = await client.search(
            query=filters.get("query", ""),
            brand_ids=filters.get("brand_ids", []),
            catalog_ids=filters.get("catalog_ids", []),
            size_ids=filters.get("size_ids", []),
            color_ids=filters.get("color_ids", []),
            price_from=filters.get("price_from"),
            price_to=filters.get("price_to"),
            order="newest_first",
            per_page=20,
        )

        if "error" in result:
            return

        items = result.get("items", [])
        seen_ids = set(mon.get("seen_ids", []))
        new_items = []

        for item in items:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_ids:
                new_items.append(item)
                seen_ids.add(item_id)

        # Keep seen_ids list manageable (last 500)
        mon["seen_ids"] = list(seen_ids)[-500:]
        self.monitors[channel_id] = mon
        save_monitors(self.monitors)

        # Send embeds for new items (max 5 at once to avoid spam)
        for item in new_items[:5]:
            embed = self._build_embed(item, base_url, filters.get("domain", "de"))
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(0.5)
            except discord.Forbidden:
                pass

    def _build_embed(self, item: dict, base_url: str, domain: str) -> discord.Embed:
        title = item.get("title", "Unbekannt")
        price = item.get("price", "?")
        total_price = item.get("total_item_price", price)
        brand = item.get("brand_title", "")
        size = item.get("size_title", "")
        condition = item.get("status", "")
        url = build_item_url(base_url, item)
        user = item.get("user", {})
        seller = user.get("login", "?")
        seller_id = user.get("id", "")
        seller_url = f"{base_url}/members/{seller_id}" if seller_id else ""

        # Photo
        photo_url = None
        photo = item.get("photo", {})
        if photo:
            photos = photo.get("thumbnails", [])
            if photos:
                photo_url = photos[-1].get("url")
            if not photo_url:
                photo_url = photo.get("url")

        currency_symbol = {"de": "€", "at": "€", "fr": "€", "uk": "£", "pl": "zł", "com": "$"}.get(domain, "€")

        embed = discord.Embed(
            title=f"🛍️ {title}",
            url=url,
            color=0x09B1BA,  # Vinted teal
        )
        embed.add_field(name="💰 Preis", value=f"**{price} {currency_symbol}** (inkl. {total_price} {currency_symbol})", inline=True)
        if brand:
            embed.add_field(name="🏷️ Marke", value=brand, inline=True)
        if size:
            embed.add_field(name="📏 Größe", value=size, inline=True)
        if condition:
            embed.add_field(name="✨ Zustand", value=condition, inline=True)
        embed.add_field(name="👤 Verkäufer", value=f"[{seller}]({seller_url})" if seller_url else seller, inline=True)

        if photo_url:
            embed.set_thumbnail(url=photo_url)

        embed.set_footer(text=f"Vinted.{domain} • {time.strftime('%H:%M:%S')}")
        return embed

    # ─── Commands ───────────────────────────────────────────────

    @commands.command(name="add")
    async def add_monitor(self, ctx, *, name: str = "Monitor"):
        """Startet die interaktive Einrichtung eines neuen Monitors"""
        channel_id = str(ctx.channel.id)
        if channel_id in self.monitors and self.monitors[channel_id].get("active"):
            await ctx.send("⚠️ In diesem Channel läuft bereits ein Monitor. Stoppe ihn zuerst mit `!stop`.")
            return

        await ctx.send(
            f"🔧 **Neuen Monitor einrichten: `{name}`**\n\n"
            "Benutze folgende Befehle um den Monitor zu konfigurieren:\n"
            "```\n"
            "!setquery <Suchbegriff>      → z.B. !setquery Nike Air Max\n"
            "!setbrand <Marke>            → z.B. !setbrand Nike\n"
            "!setprice <min> <max>        → z.B. !setprice 10 50\n"
            "!setsize <Größe>             → z.B. !setsize M\n"
            "!setdomain <Land>            → z.B. !setdomain de\n"
            "!setcondition <Zustand>      → z.B. !setcondition new\n"
            "!start                       → Monitor starten\n"
            "!filters                     → Aktuelle Filter anzeigen\n"
            "```"
        )

        self.monitors[channel_id] = {
            "name": name,
            "active": False,
            "seen_ids": [],
            "filters": {"domain": "de"}
        }
        save_monitors(self.monitors)

    @commands.command(name="setquery")
    async def set_query(self, ctx, *, query: str):
        """Setzt den Suchbegriff"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        self.monitors[channel_id]["filters"]["query"] = query
        save_monitors(self.monitors)
        await ctx.send(f"✅ Suchbegriff gesetzt: **{query}**")

    @commands.command(name="setbrand")
    async def set_brand(self, ctx, *, brand: str):
        """Setzt die Marke (Komma-getrennt für mehrere: Nike, Adidas)"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        # Known brand IDs mapping (common brands)
        brand_map = {
            "nike": 53, "adidas": 14, "zara": 2, "h&m": 6, "puma": 11,
            "gucci": 38, "louis vuitton": 46, "supreme": 225, "stone island": 308,
            "north face": 25, "levi's": 62, "levis": 62, "ralph lauren": 88,
            "tommy hilfiger": 68, "calvin klein": 78, "balenciaga": 82,
            "off-white": 428, "jordan": 14020, "new balance": 291,
            "converse": 257, "vans": 134, "champion": 109, "carhartt": 399,
            "stüssy": 567, "stussy": 567, "moncler": 159, "burberry": 105,
            "versace": 100, "prada": 94, "chanel": 148, "dior": 142,
        }
        brands = [b.strip() for b in brand.split(",")]
        brand_ids = []
        unknown = []
        for b in brands:
            bid = brand_map.get(b.lower())
            if bid:
                brand_ids.append(bid)
            else:
                unknown.append(b)

        self.monitors[channel_id]["filters"]["brand_ids"] = brand_ids
        self.monitors[channel_id]["filters"]["brand_names"] = brands
        save_monitors(self.monitors)

        msg = f"✅ Marke(n) gesetzt: **{', '.join(brands)}**"
        if unknown:
            msg += f"\n⚠️ Unbekannte Marken (keine ID gefunden): {', '.join(unknown)} — Suche läuft trotzdem per Suchbegriff."
        await ctx.send(msg)

    @commands.command(name="setprice")
    async def set_price(self, ctx, min_price: str = None, max_price: str = None):
        """Setzt den Preisbereich: !setprice 10 50"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        try:
            pmin = float(min_price) if min_price and min_price != "-" else None
            pmax = float(max_price) if max_price and max_price != "-" else None
        except ValueError:
            await ctx.send("❌ Ungültiger Preis. Beispiel: `!setprice 10 50`")
            return

        self.monitors[channel_id]["filters"]["price_from"] = pmin
        self.monitors[channel_id]["filters"]["price_to"] = pmax
        save_monitors(self.monitors)

        parts = []
        if pmin is not None:
            parts.append(f"Min: **{pmin}€**")
        if pmax is not None:
            parts.append(f"Max: **{pmax}€**")
        await ctx.send(f"✅ Preis gesetzt: {' | '.join(parts) if parts else 'Kein Limit'}")

    @commands.command(name="setsize")
    async def set_size(self, ctx, *, size: str):
        """Setzt die Größe (XS/S/M/L/XL/XXL oder Zahlen wie 38/39/40)"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        # Size ID mapping
        size_map = {
            "xxs": 102, "xs": 103, "s": 104, "m": 1324, "l": 105,
            "xl": 106, "xxl": 1325, "xxxl": 1483, "36": 1349, "37": 1350,
            "38": 1351, "39": 1352, "40": 1353, "41": 1354, "42": 1355,
            "43": 1356, "44": 1357, "45": 1358, "46": 1359, "one size": 596,
        }
        sizes = [s.strip() for s in size.split(",")]
        size_ids = []
        for s in sizes:
            sid = size_map.get(s.lower())
            if sid:
                size_ids.append(sid)

        self.monitors[channel_id]["filters"]["size_ids"] = size_ids
        self.monitors[channel_id]["filters"]["size_names"] = sizes
        save_monitors(self.monitors)
        await ctx.send(f"✅ Größe gesetzt: **{', '.join(sizes)}**")

    @commands.command(name="setdomain")
    async def set_domain(self, ctx, domain: str = "de"):
        """Setzt das Vinted-Land (de/at/fr/uk/nl/pl/es/it...)"""
        channel_id = str(ctx.channel.id)
        domain = domain.lower()
        if domain not in VINTED_DOMAINS:
            domains_list = ", ".join(VINTED_DOMAINS.keys())
            await ctx.send(f"❌ Ungültige Domain. Verfügbar: `{domains_list}`")
            return
        self._ensure_monitor(channel_id)
        self.monitors[channel_id]["filters"]["domain"] = domain
        save_monitors(self.monitors)
        await ctx.send(f"✅ Domain gesetzt: **vinted.{domain}**")

    @commands.command(name="setcondition")
    async def set_condition(self, ctx, *, condition: str):
        """Setzt den Zustand: new / very_good / good / satisfactory"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        condition_map = {
            "new": [6], "neu": [6],
            "very_good": [3], "sehr gut": [3], "sehrgut": [3],
            "good": [4], "gut": [4],
            "satisfactory": [1], "befriedigend": [1],
        }
        cids = condition_map.get(condition.lower(), [])
        self.monitors[channel_id]["filters"]["status_ids"] = cids
        self.monitors[channel_id]["filters"]["condition_name"] = condition
        save_monitors(self.monitors)
        await ctx.send(f"✅ Zustand gesetzt: **{condition}**")

    @commands.command(name="setcategory")
    async def set_category(self, ctx, *, category: str):
        """Setzt die Kategorie: men / women / kids / shoes / bags"""
        channel_id = str(ctx.channel.id)
        self._ensure_monitor(channel_id)
        cat_map = {
            "men": [4], "herren": [4],
            "women": [1], "damen": [1], "frauen": [1],
            "kids": [306], "kinder": [306],
            "shoes": [16], "schuhe": [16],
            "bags": [12], "taschen": [12],
            "accessories": [2], "accessoires": [2],
            "sport": [76], "electronics": [2485], "elektronik": [2485],
            "home": [1231], "wohnen": [1231],
            "beauty": [2350], "books": [1559], "bücher": [1559],
        }
        cid = cat_map.get(category.lower(), [])
        self.monitors[channel_id]["filters"]["catalog_ids"] = cid
        self.monitors[channel_id]["filters"]["category_name"] = category
        save_monitors(self.monitors)
        await ctx.send(f"✅ Kategorie gesetzt: **{category}**")

    @commands.command(name="setinterval")
    async def set_interval(self, ctx, seconds: int = 30):
        """Setzt das Check-Intervall in Sekunden (min 15)"""
        if seconds < 15:
            await ctx.send("⚠️ Mindestintervall ist 15 Sekunden.")
            seconds = 15
        # Note: changes global loop interval
        await ctx.send(f"⏱️ Intervall: **{seconds}s** (Neustart nötig für diese Änderung)")

    @commands.command(name="start")
    async def start_monitor(self, ctx):
        """Startet den Monitor in diesem Channel"""
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Kein Monitor konfiguriert. Benutze `!add <Name>` um einen einzurichten.")
            return

        filters = self.monitors[channel_id].get("filters", {})
        if not filters.get("query") and not filters.get("brand_ids") and not filters.get("catalog_ids"):
            await ctx.send("⚠️ Keine Filter gesetzt! Setze mindestens einen Suchbegriff mit `!setquery <Begriff>`.")
            return

        self.monitors[channel_id]["active"] = True
        self.monitors[channel_id]["seen_ids"] = []  # Reset on start
        save_monitors(self.monitors)

        name = self.monitors[channel_id].get("name", "Monitor")
        domain = filters.get("domain", "de")
        embed = discord.Embed(
            title=f"✅ Monitor gestartet: {name}",
            description=f"Ich überwache **vinted.{domain}** und sende neue Artikel hierher.",
            color=0x00C853
        )
        self._add_filter_fields(embed, filters)
        embed.set_footer(text="Stoppen mit !stop | Filter mit !filters")
        await ctx.send(embed=embed)

    @commands.command(name="stop")
    async def stop_monitor(self, ctx):
        """Stoppt den Monitor in diesem Channel"""
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Kein Monitor in diesem Channel.")
            return
        self.monitors[channel_id]["active"] = False
        save_monitors(self.monitors)
        await ctx.send("🛑 Monitor **gestoppt**.")

    @commands.command(name="filters")
    async def show_filters(self, ctx):
        """Zeigt die aktuellen Filter"""
        channel_id = str(ctx.channel.id)
        if channel_id not in self.monitors:
            await ctx.send("❌ Kein Monitor in diesem Channel. Nutze `!add <Name>`.")
            return
        mon = self.monitors[channel_id]
        filters = mon.get("filters", {})
        active = mon.get("active", False)

        embed = discord.Embed(
            title=f"📋 Filter: {mon.get('name', 'Monitor')}",
            color=0x09B1BA if active else 0x888888
        )
        embed.add_field(name="Status", value="🟢 Aktiv" if active else "🔴 Gestoppt", inline=True)
        self._add_filter_fields(embed, filters)
        await ctx.send(embed=embed)

    @commands.command(name="reset")
    async def reset_monitor(self, ctx):
        """Setzt alle Filter zurück"""
        channel_id = str(ctx.channel.id)
        if channel_id in self.monitors:
            name = self.monitors[channel_id].get("name", "Monitor")
            self.monitors[channel_id] = {
                "name": name,
                "active": False,
                "seen_ids": [],
                "filters": {"domain": "de"}
            }
            save_monitors(self.monitors)
        await ctx.send("🔄 Monitor zurückgesetzt.")

    @commands.command(name="monitors")
    async def list_monitors(self, ctx):
        """Zeigt alle aktiven Monitore auf diesem Server"""
        guild_channels = [str(ch.id) for ch in ctx.guild.channels]
        active = [(cid, m) for cid, m in self.monitors.items()
                  if cid in guild_channels]

        if not active:
            await ctx.send("📭 Keine Monitore auf diesem Server.")
            return

        embed = discord.Embed(title="📊 Alle Monitore", color=0x09B1BA)
        for cid, mon in active:
            channel = self.bot.get_channel(int(cid))
            ch_name = channel.mention if channel else f"#{cid}"
            status = "🟢" if mon.get("active") else "🔴"
            name = mon.get("name", "Monitor")
            query = mon.get("filters", {}).get("query", "-")
            embed.add_field(
                name=f"{status} {name}",
                value=f"Channel: {ch_name}\nSuche: `{query}`",
                inline=True
            )
        await ctx.send(embed=embed)

    # ─── Helpers ────────────────────────────────────────────────

    def _ensure_monitor(self, channel_id: str):
        if channel_id not in self.monitors:
            self.monitors[channel_id] = {
                "name": "Monitor",
                "active": False,
                "seen_ids": [],
                "filters": {"domain": "de"}
            }

    def _add_filter_fields(self, embed: discord.Embed, filters: dict):
        embed.add_field(name="🌍 Domain", value=f"vinted.{filters.get('domain', 'de')}", inline=True)
        if filters.get("query"):
            embed.add_field(name="🔍 Suche", value=filters["query"], inline=True)
        if filters.get("brand_names"):
            embed.add_field(name="🏷️ Marke", value=", ".join(filters["brand_names"]), inline=True)
        if filters.get("category_name"):
            embed.add_field(name="📂 Kategorie", value=filters["category_name"], inline=True)
        if filters.get("size_names"):
            embed.add_field(name="📏 Größe", value=", ".join(filters["size_names"]), inline=True)
        if filters.get("condition_name"):
            embed.add_field(name="✨ Zustand", value=filters["condition_name"], inline=True)
        pmin = filters.get("price_from")
        pmax = filters.get("price_to")
        if pmin is not None or pmax is not None:
            price_str = f"{pmin if pmin is not None else '0'}€ – {pmax if pmax is not None else '∞'}€"
            embed.add_field(name="💰 Preis", value=price_str, inline=True)


async def setup(bot):
    await bot.add_cog(MonitorCog(bot))
