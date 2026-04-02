import discord
from discord.ext import commands
import os
import asyncio

# Token direkt aus Umgebungsvariable
TOKEN = os.environ.get("DISCORD_TOKEN", "")

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"✅ Bot ist online als {bot.user}")
    print(f"📋 {len(bot.guilds)} Server verbunden")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Vinted 👀 | !help"
    ))

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    print(f"Nachricht empfangen: {message.content} von {message.author}")
    await bot.process_commands(message)

async def main():
    async with bot:
        await bot.load_extension("cogs.monitor")
        await bot.load_extension("cogs.settings")
        await bot.load_extension("cogs.help_cmd")
        print(f"Token gefunden: {'Ja' if TOKEN else 'NEIN - FEHLER!'}")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
