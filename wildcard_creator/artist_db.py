"""
artist_db.py — SQLite-backed artist style reference browser.

Reads data/artists.db (populated by scripts/scrape_artists.py).
No external dependencies — uses stdlib sqlite3 only.

Usage:
    from wildcard_creator.artist_db import get_artist_db
    db = get_artist_db()
    results = db.search("hammer")
    artist = db.get_by_name("hammer_(sunset_beach)")
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "artists.db"


# ---------------------------------------------------------------------------
# ArtistDB
# ---------------------------------------------------------------------------

class ArtistDB:
    def __init__(self, db_path: Path = _DEFAULT_DB):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._write_lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # Prevents 'database disk image is malformed' on git pull updates by discarding orphaned WAL files
            try:
                wal = self._path.with_name(self._path.name + "-wal")
                shm = self._path.with_name(self._path.name + "-shm")
                if wal.exists():
                    wal.unlink()
                if shm.exists():
                    shm.unlink()
            except Exception:
                pass

            self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=15.0)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.execute("PRAGMA journal_mode=DELETE")
                self._conn.execute("PRAGMA busy_timeout=15000")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.OperationalError:
                pass
            self._migrate()
        return self._conn

    def _migrate(self) -> None:
        """Ensure schema exists (for fresh DBs)."""
        with self._write_lock:
            ddl = """
            CREATE TABLE IF NOT EXISTS artists (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                tag           TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                image_url_1   TEXT,
                image_url_2   TEXT,
                ref_count     INTEGER DEFAULT 0,
                source        TEXT DEFAULT 'danbooru',
                rank          INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_artist_name   ON artists(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_artist_tag    ON artists(tag COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_artist_source ON artists(source);
            CREATE INDEX IF NOT EXISTS idx_artist_rank   ON artists(rank);
            """
            self._conn.executescript(ddl)
            self._conn.commit()

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        source: str | None = None,
        limit: int = 24,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Search artists by name/tag with optional source filter."""
        conn = self._get_conn()
        params: list = []
        where_clauses = []

        if query and query.strip():
            terms = [t.strip() for t in query.strip().split() if t.strip()]
            if terms:
                term_conditions = []
                for term in terms:
                    term_conditions.append("(name LIKE ? OR tag LIKE ? OR display_name LIKE ?)")
                    like = f"%{term}%"
                    params.extend([like, like, like])
                where_clauses.append("(" + " AND ".join(term_conditions) + ")")

        if source and source != "all":
            where_clauses.append("source = ?")
            params.append(source)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        sql = f"SELECT * FROM artists {where_sql} ORDER BY rank ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def count(
        self,
        query: str = "",
        source: str | None = None,
    ) -> int:
        """Count total artists matching filters."""
        conn = self._get_conn()
        params: list = []
        where_clauses = []

        if query and query.strip():
            terms = [t.strip() for t in query.strip().split() if t.strip()]
            if terms:
                term_conditions = []
                for term in terms:
                    term_conditions.append("(name LIKE ? OR tag LIKE ? OR display_name LIKE ?)")
                    like = f"%{term}%"
                    params.extend([like, like, like])
                where_clauses.append("(" + " AND ".join(term_conditions) + ")")

        if source and source != "all":
            where_clauses.append("source = ?")
            params.append(source)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        sql = f"SELECT COUNT(*) FROM artists {where_sql}"

        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def get_by_id(self, artist_id: int) -> sqlite3.Row | None:
        """Get a single artist by ID."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,))
        return cursor.fetchone()

    def get_by_name(self, name: str) -> sqlite3.Row | None:
        """Get a single artist by exact name match."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM artists WHERE name = ? COLLATE NOCASE", (name,)
        )
        return cursor.fetchone()

    def list_sources(self) -> list[str]:
        """Return all distinct sources in the DB."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT DISTINCT source FROM artists ORDER BY source")
        return [row[0] for row in cursor.fetchall()]

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    def total_count(self) -> int:
        """Total number of artists in the DB."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM artists").fetchone()
        return row[0] if row else 0

    def count_unique(self) -> int:
        """Count distinct canonical artist entities across all sources.

        Deduplication strips a leading '@' and normalizes spaces so the same
        artist appearing in Danbooru and Anima counts once.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(tag, ''), NULLIF(name, ''), display_name) AS token FROM artists"
        ).fetchall()
        seen: set[str] = set()
        for (token,) in rows:
            if not token:
                continue
            key = token.strip().lower().lstrip("@")
            key = key.replace("_", " ")
            key = " ".join(key.split())
            if key:
                seen.add(key)
        return len(seen)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ARTIST_DB_INSTANCE: ArtistDB | None = None
_ARTIST_DB_LOCK = threading.Lock()


def get_artist_db() -> ArtistDB:
    global _ARTIST_DB_INSTANCE
    if _ARTIST_DB_INSTANCE is None:
        with _ARTIST_DB_LOCK:
            if _ARTIST_DB_INSTANCE is None:
                _ARTIST_DB_INSTANCE = ArtistDB()
    return _ARTIST_DB_INSTANCE
