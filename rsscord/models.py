from dataclasses import dataclass


@dataclass(slots=True)
class FeedRecord:
    id: int
    source_url: str
    resolved_url: str
    title: str | None
    description: str | None
    enabled: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class EntryRecord:
    entry_title: str | None
    entry_description: str | None
    entry_link: str | None
    published_at: str | None
    seen_at: str
    is_short: int


@dataclass(slots=True)
class SearchResultRecord:
    feed_id: int
    feed_title: str | None
    entry_title: str | None
    entry_description: str | None
    entry_link: str | None
    published_at: str | None
    seen_at: str
    is_short: int
    score: int


@dataclass(slots=True)
class AppSettingRecord:
    key: str
    value: str


@dataclass(slots=True)
class ResolvedFeed:
    source_url: str
    resolved_url: str
    description: str | None = None
