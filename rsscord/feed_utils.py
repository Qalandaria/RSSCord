import asyncio
from datetime import datetime, timezone
from typing import Any

import feedparser


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_bool(enabled: int) -> str:
    return "enabled" if enabled else "disabled"


def format_enabled_icon(enabled: int) -> str:
    return "✅" if enabled else "❌"


def clean_url(url: str) -> str:
    return url.strip().strip("<>").strip()


async def parse_feed_or_raise(url: str) -> feedparser.FeedParserDict:
    parsed = await asyncio.to_thread(feedparser.parse, url)
    if not parsed.feed.get("title") and not parsed.entries:
        raise ValueError("The URL did not return a readable RSS/Atom feed.")
    return parsed


def derive_feed_description(parsed: feedparser.FeedParserDict) -> str | None:
    description = (
        parsed.feed.get("subtitle")
        or parsed.feed.get("description")
        or parsed.feed.get("summary")
    )
    if description:
        description = str(description).strip()
    return description or None


def derive_entry_description(entry: dict[str, Any]) -> str | None:
    description = (
        entry.get("summary")
        or entry.get("description")
        or entry.get("subtitle")
    )
    if not description:
        content = entry.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("value"):
                    description = item["value"]
                    break
    if description:
        description = str(description).strip()
    return description or None


def is_short_entry(entry: dict[str, Any]) -> bool:
    candidates = (
        entry.get("is_short"),
        entry.get("short"),
        entry.get("shorts"),
        entry.get("video_type"),
        entry.get("type"),
        entry.get("yt_video_type"),
    )
    for value in candidates:
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and "short" in value.strip().lower():
            return True

    media_player = entry.get("media_player")
    if isinstance(media_player, dict):
        if contains_shorts_path(media_player.get("url")):
            return True

    media_content = entry.get("media_content")
    if isinstance(media_content, list):
        for item in media_content:
            if isinstance(item, dict) and contains_shorts_path(item.get("url")):
                return True

    links = entry.get("links")
    if isinstance(links, list):
        for item in links:
            if isinstance(item, dict) and contains_shorts_path(item.get("href")):
                return True

    return contains_shorts_path(entry.get("link"))


def contains_shorts_path(value: Any) -> bool:
    return isinstance(value, str) and "/shorts/" in value.lower()
