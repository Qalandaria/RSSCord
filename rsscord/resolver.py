import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientSession, ClientTimeout

from .feed_utils import clean_url
from .models import ResolvedFeed


RESOLVER_USER_AGENT = "Wget/1.25.0"
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_CHANNEL_RE = re.compile(r"/channel/([A-Za-z0-9_-]{20,})")
YOUTUBE_CHANNEL_ID_RE = re.compile(
    r'"(?:channelId|externalId)"\s*:\s*"(?P<channel_id>UC[A-Za-z0-9_-]+)"'
)
YOUTUBE_BROWSE_ID_RE = re.compile(
    r'"browseId"\s*:\s*"(?P<channel_id>UC[A-Za-z0-9_-]+)"'
)
YOUTUBE_CANONICAL_RE = re.compile(
    r'<link[^>]+rel="canonical"[^>]+href="https?://(?:www\.)?youtube\.com/channel/(?P<channel_id>UC[A-Za-z0-9_-]+)"'
)
YOUTUBE_FEED_HINT_RE = re.compile(
    r"https?://www\.youtube\.com/feeds/videos\.xml\?channel_id=(?P<channel_id>UC[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


class YouTubePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.alternate_feed_url: str | None = None
        self.description: str | None = None
        self.canonical_channel_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs if value is not None}

        if tag.lower() == "link":
            rel_tokens = {
                token.strip().lower()
                for token in attributes.get("rel", "").split()
                if token.strip()
            }
            href = attributes.get("href")
            link_type = (attributes.get("type") or "").lower()
            if (
                href
                and "alternate" in rel_tokens
                and (
                    "application/atom+xml" in link_type
                    or "application/rss+xml" in link_type
                    or "/feeds/videos.xml?channel_id=" in href
                )
                and self.alternate_feed_url is None
            ):
                self.alternate_feed_url = unescape(href)
            if href and "canonical" in rel_tokens and "/channel/" in href and self.canonical_channel_url is None:
                self.canonical_channel_url = unescape(href)

        if tag.lower() == "meta":
            marker = (attributes.get("name") or attributes.get("rel") or "").lower()
            content = attributes.get("content")
            if marker == "description" and content and self.description is None:
                self.description = unescape(content).strip()


class FeedResolver:
    def __init__(self) -> None:
        self._session: ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                timeout=ClientTimeout(total=20),
                headers={"User-Agent": RESOLVER_USER_AGENT},
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def resolve(self, url: str) -> ResolvedFeed:
        if self._session is None:
            raise RuntimeError("FeedResolver session has not been started.")

        normalized = clean_url(url)
        parsed = urlparse(normalized)
        if parsed.netloc.lower() in YOUTUBE_HOSTS:
            return await self._resolve_youtube(normalized)
        return ResolvedFeed(source_url=normalized, resolved_url=normalized)

    async def _resolve_youtube(self, url: str) -> ResolvedFeed:
        parsed = urlparse(url)

        if parsed.path == "/feeds/videos.xml":
            return ResolvedFeed(source_url=url, resolved_url=url)

        direct_channel_match = YOUTUBE_CHANNEL_RE.search(parsed.path)
        if direct_channel_match:
            channel_id = direct_channel_match.group(1)
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=channel_id),
            )

        query = parse_qs(parsed.query)
        if "channel_id" in query and query["channel_id"]:
            channel_id = query["channel_id"][0]
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=channel_id),
            )

        assert self._session is not None
        async with self._session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            final_url = str(response.url)
            html = await response.text()

        parser = YouTubePageParser()
        parser.feed(html)
        description = parser.description or None

        if parser.alternate_feed_url:
            return ResolvedFeed(
                source_url=url,
                resolved_url=parser.alternate_feed_url,
                description=description,
            )

        feed_hint_match = YOUTUBE_FEED_HINT_RE.search(html)
        if feed_hint_match:
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=feed_hint_match.group("channel_id")),
                description=description,
            )

        browse_id_match = YOUTUBE_BROWSE_ID_RE.search(html)
        if browse_id_match:
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=browse_id_match.group("channel_id")),
                description=description,
            )

        final_match = YOUTUBE_CHANNEL_RE.search(urlparse(final_url).path)
        if final_match:
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=final_match.group(1)),
                description=description,
            )

        if parser.canonical_channel_url:
            canonical_match = YOUTUBE_CHANNEL_RE.search(urlparse(parser.canonical_channel_url).path)
            if canonical_match:
                return ResolvedFeed(
                    source_url=url,
                    resolved_url=YOUTUBE_FEED_URL.format(channel_id=canonical_match.group(1)),
                    description=description,
                )

        canonical_match = YOUTUBE_CANONICAL_RE.search(html)
        if canonical_match:
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=canonical_match.group("channel_id")),
                description=description,
            )

        channel_id_match = YOUTUBE_CHANNEL_ID_RE.search(html)
        if channel_id_match:
            return ResolvedFeed(
                source_url=url,
                resolved_url=YOUTUBE_FEED_URL.format(channel_id=channel_id_match.group("channel_id")),
                description=description,
            )

        raise ValueError("Could not determine the YouTube channel ID from that URL.")
