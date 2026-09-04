import sqlite3
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class WarLayoutRepository:
    """Persistence for war layouts using the caller-provided DB connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute(SCHEMA)
        self.connection.commit()

    def add_discovered(self, *, post_id: str, author: str, fingerprint: str, layout_url: str, image_url: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO war_layout_items
               (post_id, author, layout_fingerprint, layout_url, image_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (post_id, author, fingerprint, layout_url, image_url, now, now),
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
