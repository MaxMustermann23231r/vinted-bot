import discord
from discord.ext import commands

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Zeigt alle Befehle"""
        embed = discord.Embed(
            title="🛍️ Vinted Sniper Bot – Hilfe",
            description="Überwacht Vinted und benachrichtigt dich sofort bei neuen Artikeln!",
            color=0x09B1BA
        )

        embed.add_field(
            name="🚀 Schnellstart",
            value=(
                "```\n"
                "1. !add Mein Monitor\n"
                "2. !setdomain de\n"
                "3. !setquery Nike Air Max\n"
                "4. !setbrand Nike\n"
                "5. !setprice 10 80\n"
                "6. !setsize 42\n"
                "7. !start\n"
                "```"
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ Monitor-Steuerung",
            value=(
                "`!add <Name>` – Neuen Monitor erstellen\n"
                "`!start` – Monitor starten\n"
                "`!stop` – Monitor stoppen\n"
                "`!filters` – Aktuelle Filter anzeigen\n"
                "`!reset` – Filter zurücksetzen\n"
                "`!monitors` – Alle Monitore anzeigen"
            ),
            inline=False
        )

        embed.add_field(
            name="🔍 Filter-Befehle",
            value=(
                "`!setquery <Begriff>` – Suchbegriff\n"
                "`!setbrand <Marke>` – Marke (Nike, Adidas, Zara...)\n"
                "`!setprice <min> <max>` – Preisbereich\n"
                "`!setsize <Größe>` – Größe (S/M/L/38/39...)\n"
                "`!setcondition <Zustand>` – Zustand (new/very_good/good)\n"
                "`!setcategory <Kat>` – Kategorie (men/women/shoes...)\n"
                "`!setdomain <Land>` – Land (de/at/fr/uk/nl/pl...)"
            ),
            inline=False
        )

        embed.add_field(
            name="🌍 Verfügbare Länder",
            value="`de` `at` `fr` `nl` `be` `pl` `es` `it` `cz` `uk` `lt` `lu` `se` `fi` `dk` `ro` `sk` `hu` `hr` `pt` `gr` `com`",
            inline=False
        )

        embed.add_field(
            name="👗 Zustände",
            value="`new` (Neu) | `very_good` (Sehr gut) | `good` (Gut) | `satisfactory` (Befriedigend)",
            inline=False
        )

        embed.add_field(
            name="📂 Kategorien",
            value="`men` `women` `kids` `shoes` `bags` `accessories` `sport` `electronics` `home` `beauty` `books`",
            inline=False
        )

        embed.add_field(
            name="🛠️ Sonstiges",
            value="`!ping` – Latenz | `!status` – Bot-Status",
            inline=False
        )

        embed.set_footer(text="⏱️ Neue Artikel werden alle 30 Sek. geprüft")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
