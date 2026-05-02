"""SQLite index — track clipped articles in a local database.

Uses raw sqlite3 (no ORM, per project decision D006).  Auto-initializes
the schema on first use.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["ClipIndex"]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    title TEXT,
    source_type TEXT NOT NULL,
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    folder_path TEXT NOT NULL,
    markdown_path TEXT NOT NULL,
    image_count INTEGER DEFAULT 0,
    is_dynamic INTEGER DEFAULT 0,
    refresh_interval_days INTEGER DEFAULT 7,
    last_refreshed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_url ON clips(url);
CREATE INDEX IF NOT EXISTS idx_clips_source_type ON clips(source_type);
"""


class ClipIndex:
    """SQLite-backed index of clipped articles.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Parent directories are created
        automatically.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ── Connection management ────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Return an open connection, creating the DB schema if needed."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA_SQL)
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── CRUD ─────────────────────────────────────────────────────────

    def save_clip(self, clip_data: dict[str, Any]) -> int:
        """Insert a clip record and return its id.

        Parameters
        ----------
        clip_data:
            Dict with keys matching the clips table columns.
            ``created_at`` and ``updated_at`` are auto-populated if absent.

        Returns
        -------
        int
            The auto-generated row id.
        """
        conn = self._connect()
        now = datetime.now().isoformat()
        clip_data.setdefault("created_at", now)
        clip_data.setdefault("updated_at", now)

        # Ensure tags is stored as JSON string
        tags = clip_data.get("tags", [])
        if isinstance(tags, list):
            clip_data["tags"] = json.dumps(tags)

        columns = [
            "url", "title", "source_type", "category", "tags",
            "folder_path", "markdown_path", "image_count",
            "is_dynamic", "refresh_interval_days", "last_refreshed_at",
            "created_at", "updated_at",
        ]
        values = [clip_data.get(col, "") for col in columns]
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(columns)

        cursor = conn.execute(
            f"INSERT INTO clips ({col_names}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_clip(self, clip_id: int) -> dict[str, Any] | None:
        """Return a single clip record by id, or ``None`` if not found."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def query_clips(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query clips with optional filters and pagination.

        Supported filter keys: ``source_type``, ``is_dynamic``,
        ``category``, ``url``.

        Parameters
        ----------
        filters:
            Optional dict of column-value filters.
        limit:
            Maximum number of records to return.  ``None`` means no limit.
        offset:
            Number of records to skip.  ``None`` means no offset.

        Returns
        -------
        list[dict]
            Matching clip records, newest first.
        """
        conn = self._connect()
        clauses: list[str] = []
        params: list[Any] = []

        filters = filters or {}
        for key in ("source_type", "is_dynamic", "category", "url"):
            if key in filters:
                clauses.append(f"{key} = ?")
                params.append(filters[key])

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        # Pagination suffix (SQLite requires LIMIT before OFFSET)
        pagination = ""
        if limit is not None:
            pagination += " LIMIT ?"
            params.append(limit)
        elif offset is not None:
            # OFFSET requires LIMIT in SQLite; -1 = no limit
            pagination += " LIMIT -1"
        if offset is not None:
            pagination += " OFFSET ?"
            params.append(offset)

        rows = conn.execute(
            f"SELECT * FROM clips {where} ORDER BY id DESC{pagination}",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Tag / Search helpers ─────────────────────────────────────────

    def query_clips_by_tag(
        self,
        tag: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return clips whose tags JSON array contains *tag*.

        Uses SQLite JSON functions to query inside the stored JSON array.
        Falls back to a Python-side filter when json1 extension is absent.

        Parameters
        ----------
        tag:
            Tag string to match.
        limit:
            Maximum number of records to return.  ``None`` means no limit.
        offset:
            Number of records to skip.  ``None`` means no offset.
        """
        conn = self._connect()

        # Pagination suffix (SQLite requires LIMIT before OFFSET)
        pagination = ""
        params: list[Any] = [f'%"{tag}"%']
        if limit is not None:
            pagination += " LIMIT ?"
            params.append(limit)
        elif offset is not None:
            # OFFSET requires LIMIT in SQLite; -1 = no limit
            pagination += " LIMIT -1"
        if offset is not None:
            pagination += " OFFSET ?"
            params.append(offset)

        try:
            rows = conn.execute(
                f"SELECT * FROM clips WHERE tags LIKE ? ORDER BY id DESC{pagination}",
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback: filter in Python if JSON functions unavailable
            rows = conn.execute("SELECT * FROM clips ORDER BY id DESC").fetchall()
            filtered = []
            for r in rows:
                d = self._row_to_dict(r)
                if tag in d.get("tags", []):
                    filtered.append(d)
            # Apply pagination to filtered results
            start = offset or 0
            end = start + limit if limit is not None else len(filtered)
            return filtered[start:end]
        return [self._row_to_dict(r) for r in rows]

    def search_clips(self, keyword: str) -> list[dict[str, Any]]:
        """Search clips by keyword in title and url (case-insensitive LIKE)."""
        conn = self._connect()
        pattern = f"%{keyword}%"
        rows = conn.execute(
            "SELECT * FROM clips WHERE title LIKE ? OR url LIKE ? ORDER BY id DESC",
            (pattern, pattern),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_tags(self) -> list[dict[str, Any]]:
        """Return all unique tags with their usage counts.

        Scans every clip, deserialises the tags JSON, and aggregates counts.
        Returns a list of ``{"tag": str, "count": int}`` sorted by count descending.
        """
        conn = self._connect()
        rows = conn.execute("SELECT tags FROM clips").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            tags_raw = row["tags"]
            if isinstance(tags_raw, str):
                try:
                    tags_list = json.loads(tags_raw)
                except (json.JSONDecodeError, TypeError):
                    tags_list = []
            elif isinstance(tags_raw, list):
                tags_list = tags_raw
            else:
                tags_list = []
            for t in tags_list:
                if isinstance(t, str) and t:
                    counts[t] = counts.get(t, 0) + 1
        return [
            {"tag": tag, "count": cnt}
            for tag, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        ]

    def delete_clip(self, clip_id: int) -> bool:
        """Delete a clip record by id. Returns True if a row was deleted."""
        conn = self._connect()
        cursor = conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── Refresh helpers ─────────────────────────────────────────────

    def get_refreshable_clips(self) -> list[dict[str, Any]]:
        """Return clips that are dynamic (``is_dynamic=1``) and due for refresh.

        A clip is due when its ``last_refreshed_at`` is ``None`` or older
        than ``refresh_interval_days`` ago.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM clips WHERE is_dynamic = 1 ORDER BY id ASC"
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            d = self._row_to_dict(row)
            last = d.get("last_refreshed_at")
            interval = d.get("refresh_interval_days", 7)
            if self._is_expired(last, interval):
                results.append(d)
        return results

    @staticmethod
    def _is_expired(last_refreshed_at: str | None, interval_days: int | None) -> bool:
        """Return ``True`` when *last_refreshed_at* is empty or older than *interval_days*."""
        if not last_refreshed_at:
            return True
        interval_days = interval_days or 7
        try:
            last_dt = datetime.fromisoformat(last_refreshed_at)
        except (ValueError, TypeError):
            return True
        delta = (datetime.now() - last_dt).total_seconds() / 86400
        return delta >= interval_days

    def mark_refreshed(self, clip_id: int) -> bool:
        """Update ``last_refreshed_at`` on *clip_id* to the current time."""
        conn = self._connect()
        now = datetime.now().isoformat()
        cursor = conn.execute(
            "UPDATE clips SET last_refreshed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, clip_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # ── Update ───────────────────────────────────────────────────────

    def update_clip(self, clip_id: int, updates: dict[str, Any]) -> bool:
        """Update one or more columns on an existing clip record.

        Parameters
        ----------
        clip_id:
            The row id to update.
        updates:
            Column-value pairs to set.  ``tags`` as a list is serialised
            to JSON automatically.  ``updated_at`` is always refreshed.

        Returns
        -------
        bool
            ``True`` if a row was updated, ``False`` if *clip_id* not found.
        """
        conn = self._connect()

        # Serialise tags list → JSON string
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"])

        updates["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = list(updates.values()) + [clip_id]

        cursor = conn.execute(
            f"UPDATE clips SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return cursor.rowcount > 0

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a Row to a plain dict, deserialising JSON tags."""
        d = dict(row)
        # Deserialize tags JSON array
        tags_raw = d.get("tags", "[]")
        if isinstance(tags_raw, str):
            try:
                d["tags"] = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        return d
