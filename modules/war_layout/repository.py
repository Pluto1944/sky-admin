import sqlite3
import json
from datetime import datetime, timezone


SCHEMA = """
CREATE TABLE IF NOT EXISTS war_layout_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    author TEXT NOT NULL,
    layout_fingerprint TEXT NOT NULL UNIQUE,
    layout_url TEXT NOT NULL,
    image_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    draft_media_id TEXT,
    error_message TEXT,
    layout_urls_json TEXT,
    image_urls_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS war_layout_sync_state (
    author TEXT PRIMARY KEY,
    last_pull_time TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS war_layout_sync_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_pull_time TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS war_layout_sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL,
    posts INTEGER NOT NULL DEFAULT 0,
    layouts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL
)
"""


class WarLayoutRepository:
    """Persistence for war layouts using the caller-provided DB connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        cols = {row[1] for row in self.connection.execute("PRAGMA table_info(war_layout_items)")}
        if "layout_urls_json" not in cols:
            self.connection.execute("ALTER TABLE war_layout_items ADD COLUMN layout_urls_json TEXT")
        if "image_urls_json" not in cols:
            self.connection.execute("ALTER TABLE war_layout_items ADD COLUMN image_urls_json TEXT")
        self.connection.commit()

    def get_last_pull_time(self, author: str) -> datetime | None:
        row = self.connection.execute(
            "SELECT last_pull_time FROM war_layout_sync_state WHERE author = ?",
            (author,),
        ).fetchone()
        if not row:
            return None
        value = row[0]
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def get_global_last_pull_time(self) -> datetime | None:
        row = self.connection.execute(
            "SELECT last_pull_time FROM war_layout_sync_cursor WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except ValueError:
            return None

    def set_last_pull_time(self, author: str, timestamp: datetime) -> None:
        now = datetime.now(timezone.utc).isoformat()
        value = timestamp.astimezone(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO war_layout_sync_state (author, last_pull_time, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(author) DO UPDATE SET last_pull_time = excluded.last_pull_time,
                   updated_at = excluded.updated_at""",
            (author, value, now),
        )
        self.connection.commit()

    def record_sync(
        self,
        author: str,
        *,
        window_start: datetime,
        window_end: datetime,
        status: str,
        posts: int = 0,
        layouts: int = 0,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        start = window_start.astimezone(timezone.utc).isoformat()
        end = window_end.astimezone(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO war_layout_sync_history
               (author, window_start, window_end, status, posts, layouts, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (author, start, end, status, posts, layouts, error_message, now),
        )
        if status == "success":
            self.connection.execute(
                """INSERT INTO war_layout_sync_state (author, last_pull_time, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(author) DO UPDATE SET last_pull_time = excluded.last_pull_time,
                       updated_at = excluded.updated_at""",
                (author, end, now),
            )
        self.connection.commit()

    def record_global_sync(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        status: str,
        posts: int = 0,
        layouts: int = 0,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        start = window_start.astimezone(timezone.utc).isoformat()
        end = window_end.astimezone(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO war_layout_sync_history
               (author, window_start, window_end, status, posts, layouts, error_message, created_at)
               VALUES ('*', ?, ?, ?, ?, ?, ?, ?)""",
            (start, end, status, posts, layouts, error_message, now),
        )
        if status == "success":
            self.connection.execute(
                """INSERT INTO war_layout_sync_cursor (id, last_pull_time, updated_at)
                   VALUES (1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET last_pull_time = excluded.last_pull_time,
                       updated_at = excluded.updated_at""",
                (end, now),
            )
        self.connection.commit()

    def add_discovered(self, *, post_id: str, author: str, fingerprint: str, layout_url: str, image_url: str, layout_urls: tuple[str, ...] = (), image_urls: tuple[str, ...] = ()) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO war_layout_items
               (post_id, author, layout_fingerprint, layout_url, image_url, layout_urls_json, image_urls_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, author, fingerprint, layout_url, image_url, json.dumps(layout_urls or (layout_url,), ensure_ascii=False), json.dumps(image_urls or (image_url,), ensure_ascii=False), now, now),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def update_status(self, fingerprint: str, status: str, *, draft_media_id: str | None = None, error_message: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """UPDATE war_layout_items
               SET status = ?, draft_media_id = COALESCE(?, draft_media_id),
                   error_message = ?, updated_at = ?
               WHERE layout_fingerprint = ?""",
            (status, draft_media_id, error_message, now, fingerprint),
        )
        self.connection.commit()

    def get(self, fingerprint: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM war_layout_items WHERE layout_fingerprint = ?", (fingerprint,)
        ).fetchone()

    def list_pending(self, limit: int = 5) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM war_layout_items WHERE status IN ('discovered', 'failed') ORDER BY created_at, id LIMIT ?",
            (limit,),
        ).fetchall()
