"""
character_db.py — SQLite-backed character browser for the YAML Wildcard Creator.

Reads data/characters.db (populated by scripts/scrape_characters.py).
No external dependencies — uses stdlib sqlite3 only.

Usage:
    from wildcard_creator.character_db import get_character_db
    db = get_character_db()
    results = db.search("miku")
    char   = db.get("hatsune miku")
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "characters.db"


# ---------------------------------------------------------------------------
# CharacterDB
# ---------------------------------------------------------------------------

class CharacterDB:
    def __init__(self, db_path: Path = _DEFAULT_DB):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._migrate()
        return self._conn

    def _migrate(self) -> None:
        """Add new columns to existing DBs without breaking older installs."""
        try:
            self._conn.execute("ALTER TABLE characters ADD COLUMN danbooru_tag TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    def is_populated(self) -> bool:
        """Returns True if the DB file exists and has at least one row."""
        if not self._path.exists():
            return False
        try:
            row = self._get_conn().execute("SELECT 1 FROM characters LIMIT 1").fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"is_populated failed: {e}", exc_info=True)
            return False

    def count(self) -> int:
        try:
            row = self._get_conn().execute("SELECT COUNT(*) FROM characters").fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"count failed: {e}", exc_info=True)
            return 0

    def search(
        self,
        query: str,
        series_filter: Optional[str] = None,
        tag_status_filter: str = "All",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """
        Full-text search on name, tags and danbooru_tag.
        Optionally filter by exact series.
        Optionally filter by danbooru_tag status.
        Returns a tuple of (list of dicts, total match count).
        Dicts have keys: id, name, series, tags, image_url, rank.
        """
        query = (query or "").strip()
        normalized_series = (series_filter or "").strip()
        params: list = []
        clauses: list[str] = []

        if query:
            clauses.append("(name LIKE ? OR tags LIKE ? OR danbooru_tag LIKE ?)")
            like = f"%{query}%"
            params += [like, like, like]

        if normalized_series and normalized_series != "All":
            clauses.append("series = ? COLLATE NOCASE")
            params.append(normalized_series)

        if tag_status_filter == "Missing Danbooru Tag":
            clauses.append("(danbooru_tag IS NULL OR danbooru_tag = '')")
        elif tag_status_filter == "Has Danbooru Tag":
            clauses.append("(danbooru_tag IS NOT NULL AND danbooru_tag != '')")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        
        sql_count = f"SELECT COUNT(*) FROM characters {where}"
        
        sql = f"""
            SELECT id, name, series, tags, image_url, rank, danbooru_tag
            FROM characters
            {where}
            ORDER BY rank ASC
            LIMIT ? OFFSET ?
        """
        
        count_params = list(params)
        params.extend([limit, offset])

        try:
            total_count = self._get_conn().execute(sql_count, count_params).fetchone()[0]
            rows = self._get_conn().execute(sql, params).fetchall()
            return [dict(r) for r in rows], total_count
        except Exception as e:
            logger.error(f"search failed: query={query!r}, series={series_filter!r}, tag_status={tag_status_filter!r}, error={e}", exc_info=True)
            return [], 0

    def get(self, name: str) -> Optional[dict]:
        """Exact lookup by character name (case-insensitive)."""
        try:
            row = self._get_conn().execute(
                "SELECT id, name, series, tags, image_url, rank, danbooru_tag "
                "FROM characters WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name,),
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get failed: name={name!r}, error={e}", exc_info=True)
            return None

    def save_danbooru_tag(self, char_id: int, danbooru_tag: str) -> bool:
        """Persist the canonical Danbooru tag for a character (used by resolve script)."""
        try:
            self._get_conn().execute(
                "UPDATE characters SET danbooru_tag = ? WHERE id = ?",
                (danbooru_tag, char_id),
            )
            self._get_conn().commit()
            return True
        except Exception as e:
            logger.error(f"save_danbooru_tag failed: char_id={char_id}, tag={danbooru_tag!r}, error={e}", exc_info=True)
            return False

    def list_pending_danbooru(self, limit: int = 500) -> list[dict]:
        """List characters where danbooru_tag is still empty."""
        try:
            rows = self._get_conn().execute(
                "SELECT id, name, series FROM characters "
                "WHERE danbooru_tag IS NULL OR danbooru_tag = '' "
                "ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"list_pending_danbooru failed: limit={limit}, error={e}", exc_info=True)
            return []

    def pending_danbooru_count(self) -> int:
        """Count characters where danbooru_tag is still empty."""
        try:
            row = self._get_conn().execute(
                "SELECT COUNT(*) FROM characters WHERE danbooru_tag IS NULL OR danbooru_tag = ''"
            ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"pending_danbooru_count failed: error={e}", exc_info=True)
            return 0

    def list_series(self) -> list[tuple[str, int]]:
        """Returns list of (series, count) sorted by series name alphabetically."""
        try:
            rows = self._get_conn().execute(
                "SELECT series, COUNT(*) as cnt FROM characters "
                "WHERE series IS NOT NULL AND series != '' "
                "GROUP BY series "
                "ORDER BY series COLLATE NOCASE ASC"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            logger.error(f"list_series failed: error={e}", exc_info=True)
            return []

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_db_instance: Optional[CharacterDB] = None


def get_character_db() -> CharacterDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = CharacterDB()
    return _db_instance

# ---------------------------------------------------------------------------
# Auto-close on exit
# ---------------------------------------------------------------------------

import atexit

@atexit.register
def _close_db_on_exit() -> None:
    """Ensure the DB connection is closed when the process exits."""
    global _db_instance
    if _db_instance is not None:
        try:
            _db_instance.close()
        except Exception:
            pass  # Best effort

