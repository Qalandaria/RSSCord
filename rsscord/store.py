import sqlite3
from contextlib import closing
from pathlib import Path

from .feed_utils import utc_now
from .models import AppSettingRecord, EntryRecord, FeedRecord, SearchResultRecord


class FeedStore:
    DEFAULT_SETTINGS = {
        "shorts": "false",
    }

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL,
                    resolved_url TEXT NOT NULL UNIQUE,
                    title TEXT,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(feeds)").fetchall()
            }
            if "description" not in columns:
                connection.execute("ALTER TABLE feeds ADD COLUMN description TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feed_id INTEGER NOT NULL,
                    entry_key TEXT NOT NULL,
                    entry_title TEXT,
                    entry_link TEXT,
                    published_at TEXT,
                    seen_at TEXT NOT NULL,
                    UNIQUE(feed_id, entry_key),
                    FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
                )
                """
            )
            entry_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(entries)").fetchall()
            }
            if "entry_description" not in entry_columns:
                connection.execute("ALTER TABLE entries ADD COLUMN entry_description TEXT")
            if "is_short" not in entry_columns:
                connection.execute("ALTER TABLE entries ADD COLUMN is_short INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                """
                UPDATE entries
                SET is_short = 1
                WHERE lower(COALESCE(entry_link, '')) LIKE '%/shorts/%'
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO app_settings (key, value)
                VALUES (?, ?)
                """,
                self.DEFAULT_SETTINGS.items(),
            )
            connection.commit()

    def list_feeds(self) -> list[FeedRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, source_url, resolved_url, title, description, enabled, created_at, updated_at
                FROM feeds
                ORDER BY id ASC
                """
            ).fetchall()
        return [FeedRecord(**dict(row)) for row in rows]

    def count_entries(self, feed_id: int, include_shorts: bool = True) -> int:
        with closing(self._connect()) as connection:
            query = [
                "SELECT COUNT(*) AS total",
                "FROM entries",
                "WHERE feed_id = ?",
            ]
            if not include_shorts:
                query.append("AND is_short = 0")
            row = connection.execute("\n".join(query), (feed_id,)).fetchone()
        return int(row["total"]) if row else 0

    def recent_entries(self, feed_id: int, limit: int = 3, include_shorts: bool = True) -> list[EntryRecord]:
        with closing(self._connect()) as connection:
            query = [
                "SELECT entry_title, entry_description, entry_link, published_at, seen_at, is_short",
                "FROM entries",
                "WHERE feed_id = ?",
            ]
            params: list[object] = [feed_id]
            if not include_shorts:
                query.append("AND is_short = 0")
            query.extend(
                [
                    "ORDER BY",
                    "    CASE WHEN published_at IS NULL OR published_at = '' THEN 1 ELSE 0 END,",
                    "    published_at DESC,",
                    "    seen_at DESC",
                    "LIMIT ?",
                ]
            )
            params.append(limit)
            rows = connection.execute("\n".join(query), params).fetchall()
        return [EntryRecord(**dict(row)) for row in rows]

    def list_enabled_feeds(self) -> list[FeedRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, source_url, resolved_url, title, description, enabled, created_at, updated_at
                FROM feeds
                WHERE enabled = 1
                ORDER BY id ASC
                """
            ).fetchall()
        return [FeedRecord(**dict(row)) for row in rows]

    def get_feed(self, feed_id: int) -> FeedRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, source_url, resolved_url, title, description, enabled, created_at, updated_at
                FROM feeds
                WHERE id = ?
                """,
                (feed_id,),
            ).fetchone()
        return FeedRecord(**dict(row)) if row else None

    def add_feed(
        self,
        source_url: str,
        resolved_url: str,
        title: str | None,
        description: str | None,
    ) -> FeedRecord:
        now = utc_now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO feeds (source_url, resolved_url, title, description, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (source_url, resolved_url, title, description, now, now),
            )
            connection.commit()
            feed_id = cursor.lastrowid
        feed = self.get_feed(feed_id)
        if feed is None:
            raise RuntimeError("Failed to fetch newly created feed.")
        return feed

    def update_feed(
        self,
        feed_id: int,
        source_url: str,
        resolved_url: str,
        title: str | None,
        description: str | None,
    ) -> FeedRecord | None:
        now = utc_now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE feeds
                SET source_url = ?, resolved_url = ?, title = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (source_url, resolved_url, title, description, now, feed_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_feed(feed_id)

    def delete_feed(self, feed_id: int) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
            connection.commit()
            return cursor.rowcount > 0

    def toggle_feed(self, feed_id: int) -> FeedRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT enabled FROM feeds WHERE id = ?",
                (feed_id,),
            ).fetchone()
            if row is None:
                return None
            new_value = 0 if row["enabled"] else 1
            connection.execute(
                """
                UPDATE feeds
                SET enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_value, utc_now(), feed_id),
            )
            connection.commit()
        return self.get_feed(feed_id)

    def upsert_entry(
        self,
        feed_id: int,
        entry_key: str,
        entry_title: str | None,
        entry_description: str | None,
        entry_link: str | None,
        published_at: str | None,
        is_short: bool = False,
    ) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO entries (
                    feed_id,
                    entry_key,
                    entry_title,
                    entry_description,
                    entry_link,
                    published_at,
                    is_short,
                    seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_id,
                    entry_key,
                    entry_title,
                    entry_description,
                    entry_link,
                    published_at,
                    int(is_short),
                    utc_now(),
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def search_entries(
        self,
        terms: list[str],
        limit: int = 3,
        include_shorts: bool = True,
    ) -> list[SearchResultRecord]:
        cleaned_terms = [term.strip().lower() for term in terms if term.strip()]
        if not cleaned_terms:
            return []

        score_parts: list[str] = []
        term_params: list[object] = []
        for term in cleaned_terms:
            like_term = f"%{term}%"
            score_parts.extend(
                [
                    "CASE WHEN lower(COALESCE(e.entry_title, '')) LIKE ? THEN 6 ELSE 0 END",
                    "CASE WHEN lower(COALESCE(e.entry_description, '')) LIKE ? THEN 3 ELSE 0 END",
                    "CASE WHEN lower(COALESCE(f.title, '')) LIKE ? THEN 2 ELSE 0 END",
                ]
            )
            term_params.extend([like_term, like_term, like_term])

        score_expression = " + ".join(score_parts)
        query = [
            "SELECT",
            "    e.feed_id,",
            "    f.title AS feed_title,",
            "    e.entry_title,",
            "    e.entry_description,",
            "    e.entry_link,",
            "    e.published_at,",
            "    e.seen_at,",
            "    e.is_short,",
            f"    ({score_expression}) AS score",
            "FROM entries e",
            "JOIN feeds f ON f.id = e.feed_id",
            "WHERE 1 = 1",
        ]
        if not include_shorts:
            query.append("AND e.is_short = 0")
        query.append(f"AND ({score_expression}) > 0")
        query.extend(
            [
                "ORDER BY",
                "    score DESC,",
                "    CASE WHEN e.published_at IS NULL OR e.published_at = '' THEN 1 ELSE 0 END,",
                "    e.published_at DESC,",
                "    e.seen_at DESC",
                "LIMIT ?",
            ]
        )

        params = [*term_params, *term_params, limit]
        with closing(self._connect()) as connection:
            rows = connection.execute("\n".join(query), params).fetchall()
        return [SearchResultRecord(**dict(row)) for row in rows]

    def get_setting(self, key: str) -> AppSettingRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT key, value
                FROM app_settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        return AppSettingRecord(**dict(row)) if row else None

    def set_setting(self, key: str, value: str) -> AppSettingRecord:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            connection.commit()
        setting = self.get_setting(key)
        if setting is None:
            raise RuntimeError("Failed to fetch updated setting.")
        return setting

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        setting = self.get_setting(key)
        if setting is None:
            return default
        return setting.value.strip().lower() in {"1", "true", "yes", "on"}
