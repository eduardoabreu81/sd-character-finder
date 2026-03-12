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

import sqlite3
from pathlib import Path
from typing import Optional

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
        return self._conn

    def is_populated(self) -> bool:
        """Returns True if the DB file exists and has at least one row."""
        if not self._path.exists():
            return False
        try:
            row = self._get_conn().execute("SELECT 1 FROM characters LIMIT 1").fetchone()
            return row is not None
        except Exception:
            return False

    def count(self) -> int:
        try:
            row = self._get_conn().execute("SELECT COUNT(*) FROM characters").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def search(
        self,
        query: str,
        series_filter: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Full-text search on name and tags.
        Optionally filter by exact series.
        Returns list of dicts with keys: id, name, series, tags, image_url, rank.
        """
        query = query.strip()
        params: list = []
        clauses: list[str] = []

        if query:
            clauses.append("(name LIKE ? OR tags LIKE ?)")
            like = f"%{query}%"
            params += [like, like]

        if series_filter and series_filter != "All":
            clauses.append("series = ?")
            params.append(series_filter)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT id, name, series, tags, image_url, rank
            FROM characters
            {where}
            ORDER BY rank ASC
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = self._get_conn().execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get(self, name: str) -> Optional[dict]:
        """Exact lookup by character name (case-insensitive)."""
        try:
            row = self._get_conn().execute(
                "SELECT id, name, series, tags, image_url, rank "
                "FROM characters WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name,),
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def list_series(self) -> list[tuple[str, int]]:
        """Returns list of (series, count) sorted by count descending."""
        try:
            rows = self._get_conn().execute(
                "SELECT series, COUNT(*) as cnt FROM characters "
                "WHERE series IS NOT NULL AND series != '' "
                "GROUP BY series ORDER BY cnt DESC"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception:
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
