import discord
from discord.ext import commands

from .config import Settings


def user_tokens(user: discord.abc.User) -> set[str]:
    tokens = {str(user.id), user.name}
    display_name = getattr(user, "display_name", None)
    global_name = getattr(user, "global_name", None)
    if display_name:
        tokens.add(display_name)
    if global_name:
        tokens.add(global_name)
    return {token for token in tokens if token}


def is_authorized(user: discord.abc.User, settings: Settings) -> bool:
    return bool(user_tokens(user) & settings.allowed_users)


def owner_only(settings: Settings):
    async def predicate(ctx: commands.Context) -> bool:
        if is_authorized(ctx.author, settings):
            return True
        raise commands.CheckFailure("You are not allowed to use this bot.")

    return commands.check(predicate)
