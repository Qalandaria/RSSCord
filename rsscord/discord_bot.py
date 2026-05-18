import asyncio
import logging
from calendar import timegm
from typing import Any
from urllib.parse import urlparse

import discord
import feedparser
from discord.ext import commands, tasks

from .config import Settings
from .feed_utils import (
    derive_entry_description,
    derive_entry_thumbnail_url,
    derive_feed_description,
    is_short_entry,
    is_youtube_url,
)
from .resolver import FeedResolver
from .store import FeedStore


class RSSCordBot(commands.Bot):
    MAX_ANNOUNCED_ITEMS = 3

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=settings.command_prefix, intents=intents, help_command=None)
        self.settings = settings
        self.store = FeedStore(settings.database_path)
        self.resolver = FeedResolver()
        self.feed_poll_loop.change_interval(minutes=settings.poll_interval_minutes)

    async def setup_hook(self) -> None:
        await self.resolver.start()
        self.feed_poll_loop.start()

    async def close(self) -> None:
        self.feed_poll_loop.cancel()
        await self.resolver.close()
        await super().close()

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "n/a"))

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CheckFailure):
            await ctx.reply(str(error), mention_author=False)
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"Missing argument: `{error.param.name}`.", mention_author=False)
            return
        if isinstance(error, commands.BadArgument):
            await ctx.reply(f"Bad argument: {error}.", mention_author=False)
            return
        logging.exception("Unhandled command error", exc_info=error)
        await ctx.reply(f"Command failed: `{error}`", mention_author=False)

    def announcement_channel(self) -> discord.TextChannel | None:
        if not self.settings.announce_channel_id:
            return None
        channel = self.get_channel(self.settings.announce_channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    @tasks.loop(minutes=10)
    async def feed_poll_loop(self) -> None:
        print('Fetching all feeds...')
        await self.wait_until_ready()
        channel = self.announcement_channel()
        for feed in self.store.list_enabled_feeds():
            try:
                new_entries = await self.fetch_feed(feed)
            except Exception:
                logging.exception("Failed to process feed %s", feed.id)
                continue

            if not channel:
                continue

            visible_entries = [entry for entry in new_entries if self.should_show_entry(is_short_entry(entry))]
            for entry in self.select_entries_for_announcement(visible_entries):
                await self.send_entry(channel, entry, feed_title=feed.title, fallback_url=feed.resolved_url)

    @feed_poll_loop.before_loop
    async def before_feed_poll_loop(self) -> None:
        await self.wait_until_ready()

    async def fetch_feed(self, feed) -> list[dict]:
        parsed = await asyncio.to_thread(feedparser.parse, feed.resolved_url)
        if getattr(parsed, "bozo", False) and not parsed.entries and not parsed.feed.get("title"):
            bozo_exception = getattr(parsed, "bozo_exception", None)
            if bozo_exception:
                raise ValueError(f"Invalid feed: {bozo_exception}")

        feed_title = parsed.feed.get("title")
        feed_description = feed.description or derive_feed_description(parsed)
        if feed_title != feed.title or feed_description != feed.description:
            self.store.update_feed(
                feed.id,
                feed.source_url,
                feed.resolved_url,
                feed_title,
                feed_description,
            )

        new_entries: list[dict] = []
        for entry in parsed.entries:
            entry_key = self.entry_key(entry)
            published_at = (
                entry.get("published")
                or entry.get("updated")
                or entry.get("created")
            )
            inserted = self.store.upsert_entry(
                feed.id,
                entry_key,
                entry.get("title"),
                derive_entry_description(entry),
                derive_entry_thumbnail_url(entry),
                entry.get("link"),
                published_at,
                is_short=is_short_entry(entry),
            )
            if inserted:
                new_entries.append(entry)
        return new_entries

    @staticmethod
    def entry_key(entry: dict) -> str:
        for field in ("id", "guid", "link", "title"):
            value = entry.get(field)
            if value:
                return str(value)
        return repr(sorted(entry.items()))

    @classmethod
    def select_entries_for_announcement(cls, entries: list[dict]) -> list[dict]:
        if len(entries) <= cls.MAX_ANNOUNCED_ITEMS:
            return list(reversed(entries))

        ranked_entries = []
        has_popularity_signal = False
        for entry in entries:
            popularity = cls.entry_popularity(entry)
            if popularity > 0:
                has_popularity_signal = True
            ranked_entries.append((popularity, cls.entry_timestamp(entry), entry))

        if has_popularity_signal:
            ranked_entries.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return [entry for _, _, entry in ranked_entries[:cls.MAX_ANNOUNCED_ITEMS]]

        newest_first = sorted(ranked_entries, key=lambda item: item[1], reverse=True)
        selected = newest_first[:cls.MAX_ANNOUNCED_ITEMS]
        selected.sort(key=lambda item: item[1])
        return [entry for _, _, entry in selected]

    @staticmethod
    def entry_popularity(entry: dict) -> float:
        score = 0.0
        numeric_fields = (
            "popularity",
            "score",
            "rank",
            "rating",
            "views",
            "view_count",
            "viewCount",
            "likes",
            "like_count",
            "likeCount",
            "comments",
            "comment_count",
            "commentCount",
            "favorites",
            "favorite_count",
            "favoriteCount",
        )
        for field in numeric_fields:
            score += RSSCordBot.coerce_number(entry.get(field))

        media_stats = entry.get("media_statistics")
        if isinstance(media_stats, dict):
            for value in media_stats.values():
                score += RSSCordBot.coerce_number(value)

        return score

    @staticmethod
    def entry_timestamp(entry: dict) -> int:
        for field in ("published_parsed", "updated_parsed", "created_parsed"):
            value = entry.get(field)
            if value:
                try:
                    return int(timegm(value))
                except (OverflowError, TypeError, ValueError):
                    continue
        return 0

    @staticmethod
    def coerce_number(value: Any) -> float:
        if isinstance(value, bool) or value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def entry_value(entry: Any, key: str) -> Any:
        if isinstance(entry, dict):
            return entry.get(key)
        return getattr(entry, key, None)

    @classmethod
    def entry_link(cls, entry: Any, fallback_url: str | None = None) -> str | None:
        value = cls.entry_value(entry, "link")
        if value is None:
            value = cls.entry_value(entry, "entry_link")
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(fallback_url, str) and fallback_url.strip():
            return fallback_url.strip()
        return None

    @classmethod
    def entry_title(cls, entry: Any) -> str | None:
        value = cls.entry_value(entry, "title")
        if value is None:
            value = cls.entry_value(entry, "entry_title")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def entry_description(cls, entry: Any) -> str | None:
        if isinstance(entry, dict):
            return derive_entry_description(entry)
        value = cls.entry_value(entry, "entry_description")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def entry_thumbnail_url(cls, entry: Any) -> str | None:
        if isinstance(entry, dict):
            return derive_entry_thumbnail_url(entry)
        value = cls.entry_value(entry, "entry_thumbnail_url")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def entry_when(cls, entry: Any) -> str | None:
        value = cls.entry_value(entry, "published_at")
        if not value:
            value = cls.entry_value(entry, "seen_at")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def entry_feed_title(cls, entry: Any) -> str | None:
        value = cls.entry_value(entry, "feed_title")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def build_entry_embed(
        cls,
        feed_title: str | None,
        entry: Any,
        fallback_url: str | None,
    ) -> discord.Embed | None:
        link = cls.entry_link(entry, fallback_url)
        if not isinstance(link, str) or not link.strip():
            return None

        title = cls.entry_title(entry)
        if not isinstance(title, str) or not title.strip():
            hostname = urlparse(link).hostname
            title = feed_title or hostname or "Open item"

        description = cls.entry_description(entry)
        embed = discord.Embed(
            title=title.strip()[:256],
            url=link,
            description=description[:4096] if isinstance(description, str) else None,
        )
        if feed_title:
            embed.set_author(name=feed_title[:256])

        thumbnail_url = cls.entry_thumbnail_url(entry)
        if thumbnail_url:
            embed.set_image(url=thumbnail_url)
        when = cls.entry_when(entry)
        if when:
            embed.set_footer(text=when[:2048])
        return embed

    @classmethod
    def build_entry_text(
        cls,
        feed_title: str | None,
        entry: Any,
        fallback_url: str | None,
    ) -> str:
        title = cls.entry_title(entry) or "Untitled entry"
        link = cls.entry_link(entry, fallback_url)
        when = cls.entry_when(entry)
        lines = []
        if feed_title:
            lines.append(f"**{feed_title}**")
        lines.append(title)
        if when:
            lines.append(when)
        if link:
            lines.append(link)
        return "\n".join(lines)

    async def send_entry(
        self,
        destination: Any,
        entry: Any,
        feed_title: str | None = None,
        fallback_url: str | None = None,
    ) -> None:
        resolved_feed_title = feed_title or self.entry_feed_title(entry)
        link = self.entry_link(entry, fallback_url)
        if is_youtube_url(link):
            await destination.send(self.build_entry_text(resolved_feed_title, entry, fallback_url))
            return

        embed = self.build_entry_embed(resolved_feed_title, entry, fallback_url)
        if embed is not None:
            await destination.send(embed=embed)
            return
        await destination.send(self.build_entry_text(resolved_feed_title, entry, fallback_url))

    def shorts_enabled(self) -> bool:
        return self.store.get_bool_setting("shorts", default=False)

    def should_show_entry(self, is_short: bool) -> bool:
        return self.shorts_enabled() or not is_short
