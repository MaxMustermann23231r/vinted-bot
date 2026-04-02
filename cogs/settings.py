import discord
from discord.ext import commands
import json
from pathlib import Path

CONFIG_FILE = "config.json"

def load_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

class SettingsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Bot-Latenz prüfen"""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! `{latency}ms`")

    @commands.command(name="status")
    async def status(self, ctx):
        """Zeigt Bot-Status"""
        from cogs.monitor import load_monitors
        monitors = load_monitors()
        active_count = sum(1 for m in monitors.values() if m.get("active"))
        total_count = len(monitors)
        embed = discord.Embed(title="📊 Bot Status", color=0x09B1BA)
        embed.add_field(name="🤖 Bot", value=f"{self.bot.user}", inline=True)
        embed.add_field(name="⚡ Latenz", value=f"{round(self.bot.latency*1000)}ms", inline=True)
        embed.add_field(name="🌐 Server", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="📡 Monitore", value=f"{active_count} aktiv / {total_count} total", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SettingsCog(bot))
