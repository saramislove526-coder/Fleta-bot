import os
import asyncio
import logging
import signal
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables before importing config so config.py can read them
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
load_dotenv(dotenv_path=os.path.join(os.getcwd(), '.env'))
load_dotenv()

from config import COMMAND_PREFIX, DISCORD_GUILD_ID
from utils.sync import clear_obsolete_global, sync_guild

# ----------------------------------
# Logging
# ----------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
)

log = logging.getLogger("Bot")

# ----------------------------------
# Intents
# ----------------------------------

intents = discord.Intents.all()

# ----------------------------------
# Bot
# ----------------------------------

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    help_command=None,
    allowed_mentions=discord.AllowedMentions(
        everyone=False,
        roles=False,
        users=False,
        replied_user=False
    )
)

commands_synced = False

# ----------------------------------
# Events
# ----------------------------------

@bot.event
async def on_ready():
    global commands_synced
    print("-" * 50)
    print(f"Logged in as {bot.user}")
    print(f"ID : {bot.user.id}")
    print("-" * 50)

    if not commands_synced:
        try:
            if DISCORD_GUILD_ID:
                guild = bot.get_guild(DISCORD_GUILD_ID) or discord.Object(id=DISCORD_GUILD_ID)
                synced = await sync_guild(bot, guild)
                log.info("Synced %s slash commands to guild %s.", len(synced), DISCORD_GUILD_ID)
            elif bot.guilds:
                synced = []
                for guild in bot.guilds:
                    guild_synced = await sync_guild(bot, guild)
                    log.info("Synced %s slash commands to guild %s.", len(guild_synced), guild.id)
                    synced.extend(guild_synced)
            else:
                synced = await bot.tree.sync()
                log.info("Synced %s global slash commands.", len(synced))

            # Remove obsolete global registrations while preserving the current
            # in-memory commands needed for future guild syncs.
            await clear_obsolete_global(bot)
            commands_synced = True
        except Exception:
            log.exception("Failed to sync slash commands.")

# ----------------------------------
# Load Cogs
# ----------------------------------

COGS = (
    "cogs.ai",
    "cogs.character",
    "cogs.admin",
    "cogs.events",
    "cogs.alarms",
    "cogs.help",
)

async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info(f"Loaded {cog}")
        except Exception as e:
            log.exception(f"Failed to load {cog}: {e}")

# ----------------------------------
# Main
# ----------------------------------

async def main():
    async with bot:
        await load_cogs()

        token = os.getenv("DISCORD_BOT_TOKEN")

        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN not found.")

        # 호스팅 환경의 재시작/종료 신호(SIGTERM, Ctrl+C)에 깔끔하게 대응
        try:
            loop = asyncio.get_running_loop()
            for _sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(_sig, lambda: asyncio.ensure_future(bot.close()))
        except NotImplementedError:
            # Windows에서는 add_signal_handler 미지원 (KeyboardInterrupt가 별도 처리됨)
            pass

        await bot.start(token)

    if getattr(bot, "_restart_requested", False):
        os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])

if __name__ == "__main__":
    asyncio.run(main())
