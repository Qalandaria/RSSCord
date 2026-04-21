import sqlite3

from discord.ext import commands

from .auth import owner_only
from .config import Settings
from .discord_bot import RSSCordBot
from .feed_utils import (
    clean_url,
    derive_feed_description,
    format_bool,
    format_enabled_icon,
    is_short_entry,
    parse_feed_or_raise,
)


def register_commands(bot: RSSCordBot, settings: Settings) -> None:
    def shorts_enabled() -> bool:
        return bot.store.get_bool_setting("shorts", default=False)

    def compact_text(value: str | None, limit: int = 180) -> str | None:
        if not value:
            return None
        normalized = " ".join(str(value).split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3].rstrip()}..."

    def parse_bool_value(raw_value: str) -> bool | None:
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
        return None

    @bot.command(name="feeds")
    @owner_only(settings)
    async def feeds_command(ctx: commands.Context) -> None:
        feeds = bot.store.list_feeds()
        if not feeds:
            await ctx.reply("No feeds configured.", mention_author=False)
            return

        lines = ['```']
        for feed in feeds:
            label = feed.title or "Untitled feed"
            article_count = bot.store.count_entries(feed.id, include_shorts=shorts_enabled())
            lines.append(f"{feed.id}\t{format_enabled_icon(feed.enabled)} {label} ({article_count} items)")
        lines.append('```')
        await ctx.reply("\n".join(lines), mention_author=False)

    @bot.command(name="add")
    @owner_only(settings)
    async def add_command(ctx: commands.Context, url: str) -> None:
        source_url = clean_url(url)
        resolved = await bot.resolver.resolve(source_url)
        parsed = await parse_feed_or_raise(resolved.resolved_url)
        title = parsed.feed.get("title") or None
        description = resolved.description or derive_feed_description(parsed)
        try:
            feed = bot.store.add_feed(
                resolved.source_url,
                resolved.resolved_url,
                title,
                description,
            )
        except sqlite3.IntegrityError:
            await ctx.reply("That feed is already in the database.", mention_author=False)
            return

        await bot.fetch_feed(feed)
        await ctx.reply(
            f"Added feed `{feed.id}`: {title or 'Untitled feed'}\n{feed.resolved_url}",
            mention_author=False,
        )

    @bot.command(name="update")
    @owner_only(settings)
    async def update_command(ctx: commands.Context, feed_id: int, url: str) -> None:
        source_url = clean_url(url)
        resolved = await bot.resolver.resolve(source_url)
        parsed = await parse_feed_or_raise(resolved.resolved_url)
        title = parsed.feed.get("title") or None
        description = resolved.description or derive_feed_description(parsed)
        try:
            updated = bot.store.update_feed(
                feed_id,
                resolved.source_url,
                resolved.resolved_url,
                title,
                description,
            )
        except sqlite3.IntegrityError:
            await ctx.reply("Another feed already uses that resolved URL.", mention_author=False)
            return

        if updated is None:
            await ctx.reply("Feed not found.", mention_author=False)
            return

        await bot.fetch_feed(updated)
        await ctx.reply(
            f"Updated feed `{updated.id}` to {updated.title or 'Untitled feed'}\n{updated.resolved_url}",
            mention_author=False,
        )

    @bot.command(name="remove")
    @owner_only(settings)
    async def remove_command(ctx: commands.Context, feed_id: int) -> None:
        removed = bot.store.delete_feed(feed_id)
        if not removed:
            await ctx.reply("Feed not found.", mention_author=False)
            return
        await ctx.reply(f"Removed feed `{feed_id}`.", mention_author=False)

    @bot.command(name="toggle")
    @owner_only(settings)
    async def toggle_command(ctx: commands.Context, feed_id: int) -> None:
        feed = bot.store.toggle_feed(feed_id)
        if feed is None:
            await ctx.reply("Feed not found.", mention_author=False)
            return
        await ctx.reply(
            f"Feed `{feed.id}` is now {format_bool(feed.enabled)}.",
            mention_author=False,
        )

    @bot.command(name="refresh")
    @owner_only(settings)
    async def refresh_command(ctx: commands.Context, feed_id: int | None = None) -> None:
        if feed_id is not None:
            feed = bot.store.get_feed(feed_id)
            if feed is None:
                await ctx.reply("Feed not found.", mention_author=False)
                return
            new_entries = await bot.fetch_feed(feed)
            visible_new_entries = [
                entry for entry in new_entries
                if bot.should_show_entry(is_short_entry(entry))
            ]
            await ctx.reply(
                f"Fetched feed `{feed.id}` and found `{len(visible_new_entries)}` visible new entries.",
                mention_author=False,
            )
            return

        total_new = 0
        for feed in bot.store.list_enabled_feeds():
            total_new += len(
                [
                    entry for entry in await bot.fetch_feed(feed)
                    if bot.should_show_entry(is_short_entry(entry))
                ]
            )
        await ctx.reply(
            f"Fetched all enabled feeds and found `{total_new}` visible new entries.",
            mention_author=False,
        )

    @bot.command(name="get")
    @owner_only(settings)
    async def get_command(ctx: commands.Context, feed_id: int) -> None:
        feed = bot.store.get_feed(feed_id)
        if feed is None:
            await ctx.reply("Feed not found.", mention_author=False)
            return

        parsed = await parse_feed_or_raise(feed.resolved_url)
        description = feed.description or derive_feed_description(parsed) or "No description available."
        recent_entries = bot.store.recent_entries(feed.id, limit=3, include_shorts=shorts_enabled())

        lines = [
            f"**{parsed.feed.get('title') or feed.title or 'Untitled feed'}**",
            description,
        ]
        if recent_entries:
            for index, entry in enumerate(recent_entries, start=1):
                title = entry.entry_title or "Untitled article"
                when = entry.published_at or entry.seen_at
                if entry.entry_link:
                    lines.append(f"{index}. {title} ({when})\n{entry.entry_link}")
                else:
                    lines.append(f"{index}. {title} ({when})")
        else:
            lines.append("No visible articles yet.")

        await ctx.reply("\n\n".join(lines), mention_author=False)

    @bot.command(name="help")
    @owner_only(settings)
    async def help_command(ctx: commands.Context) -> None:
        prefix = settings.command_prefix
        lines = [
            f"`{prefix}feeds`",
            f"`{prefix}get <id>`",
            f"`{prefix}search <term> [term ...]`",
            f"`{prefix}add <url>`",
            f"`{prefix}set [shorts] [true|false]`",
            f"`{prefix}update <id> <url>`",
            f"`{prefix}remove <id>`",
            f"`{prefix}toggle <id>`",
            f"`{prefix}refresh [id]`",
        ]
        await ctx.reply("\n".join(lines), mention_author=False)

    @bot.command(name="set")
    @owner_only(settings)
    async def set_command(
        ctx: commands.Context,
        setting_name: str | None = None,
        setting_value: str | None = None,
    ) -> None:
        current_shorts = shorts_enabled()
        if setting_name is None:
            await ctx.reply(
                f"`shorts = {str(current_shorts).lower()}`",
                mention_author=False,
            )
            return

        if setting_name.lower() != "shorts":
            await ctx.reply("Unknown setting. Available settings: `shorts`.", mention_author=False)
            return

        if setting_value is None:
            await ctx.reply(
                f"`shorts = {str(current_shorts).lower()}`",
                mention_author=False,
            )
            return

        parsed_value = parse_bool_value(setting_value)
        if parsed_value is None:
            await ctx.reply("Value must be `true` or `false`.", mention_author=False)
            return

        bot.store.set_setting("shorts", str(parsed_value).lower())
        await ctx.reply(
            f"`shorts` is now `{str(parsed_value).lower()}`.",
            mention_author=False,
        )

    @bot.command(name="search")
    @owner_only(settings)
    async def search_command(ctx: commands.Context, *terms: str) -> None:
        if not terms:
            await ctx.reply("Usage: `%search <term> [term ...]`", mention_author=False)
            return

        results = bot.store.search_entries(
            list(terms),
            limit=3,
            include_shorts=shorts_enabled(),
        )
        if not results:
            await ctx.reply("No matching visible items found.", mention_author=False)
            return

        lines = []
        for index, result in enumerate(results, start=1):
            title = result.entry_title or "Untitled article"
            channel_name = result.feed_title or "Unknown channel"
            when = result.published_at or result.seen_at
            lines.append(f"{index}. **{title}**")
            lines.append(f"Channel: {channel_name}")
            lines.append(f"When: {when}")
            description = compact_text(result.entry_description)
            if description:
                lines.append(description)
            if result.entry_link:
                lines.append(result.entry_link)
            lines.append("")

        await ctx.reply("\n".join(lines[:-1]), mention_author=False)
