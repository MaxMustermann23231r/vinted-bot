import discord
from discord.ext import commands
import json
import os
from pathlib import Path

# Load config
CONFIG_FILE = "config.json"

def load_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"token": "", "monitors": {}}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

config = load_config()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Load cogs
async def main():
    async with bot:
        await bot.load_extension("cogs.monitor")
        await bot.load_extension("cogs.settings")
        await bot.load_extension("cogs.help_cmd")
        token = config.get("token") or os.environ.get("DISCORD_TOKEN", "")
        if not token:
            print("❌ Kein Discord Token gefunden!")
            print("Bitte trage deinen Token in config.json ein: { \"token\": \"DEIN_TOKEN\" }")
            return
        await bot.start(token)

@bot.event
async def on_ready():
    print(f"✅ Bot ist online als {bot.user}")
    print(f"📋 {len(bot.guilds)} Server verbunden")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Vinted 👀 | !help"
    ))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
