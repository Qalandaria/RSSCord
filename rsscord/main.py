import logging
from pathlib import Path

from .commands import register_commands
from .config import load_settings
from .discord_bot import RSSCordBot
from . import resolver


def create_bot() -> RSSCordBot:
    settings = load_settings()
    bot = RSSCordBot(settings)
    register_commands(bot, settings)
    return bot


def main() -> None:
    bot = create_bot()
    if not bot.settings.bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required.")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.info(
        "RSSCord startup: entrypoint=%s resolver=%s cwd=%s",
        Path(__file__).resolve(),
        Path(resolver.__file__).resolve(),
        Path.cwd(),
    )
    bot.run(bot.settings.bot_token)
