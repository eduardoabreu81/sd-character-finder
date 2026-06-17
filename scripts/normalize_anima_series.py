#!/usr/bin/env python3
"""
Normalize AnimaDex series/copyright names to match the title-case style used by
Danbooru entries in the main characters database.

The script preserves the original Anima triggers in the `tags` column (which is
what the model expects) and only rewrites the `series` display/filter column.

Usage:
    python scripts/normalize_anima_series.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "characters.db"


def _normalize_key(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("_", " ")
    s = s.replace("\\(", "(")
    s = s.replace("\\)", ")")
    s = re.sub(r"\s+", " ", s)
    return s


def _clean_anima_copyright(s: str) -> str:
    """Strip common Anima/Danbooru disambiguation suffixes."""
    s = s.strip().replace("_", " ")
    s = re.sub(r"\s*\(series\)\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(franchise\)\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(game\)\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _titlecase_keep_apostrophe(s: str) -> str:
    def _cap(word: str) -> str:
        for i, ch in enumerate(word):
            if ch.isalpha():
                return word[:i] + ch.upper() + word[i + 1 :]
        return word

    return " ".join(_cap(w) for w in s.split(" "))


def _build_mapping(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {original_anima_series: normalized_series}."""
    # Danbooru series lookup
    dan_series: dict[str, str] = {}
    cur = conn.execute(
        "SELECT DISTINCT series FROM characters WHERE source='danbooru' "
        "AND series IS NOT NULL AND series != ''"
    )
    for (series,) in cur.fetchall():
        dan_series[_normalize_key(series)] = series

    # Anima copyrights
    cur = conn.execute(
        "SELECT DISTINCT series FROM characters WHERE source='anima' "
        "AND series IS NOT NULL AND series != ''"
    )
    anima_series = {row[0] for row in cur.fetchall()}

    mapping: dict[str, str] = {}
    for original in anima_series:
        cleaned = _clean_anima_copyright(original)
        key = _normalize_key(cleaned)
        if key in dan_series:
            mapping[original] = dan_series[key]
        else:
            mapping[original] = _titlecase_keep_apostrophe(cleaned)

    return mapping


def main() -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    backup_path = DB_PATH.with_suffix(f".db.backup_series_norm")
    shutil.copy(DB_PATH, backup_path)
    print(f"Backup created: {backup_path}")

    with sqlite3.connect(DB_PATH) as conn:
        mapping = _build_mapping(conn)

        # Apply updates in batches via a temporary mapping table
        conn.execute("CREATE TEMP TABLE _series_map (old TEXT PRIMARY KEY, new TEXT)")
        conn.executemany(
            "INSERT INTO _series_map (old, new) VALUES (?, ?)",
            mapping.items(),
        )

        cur = conn.execute(
            "UPDATE characters SET series = (SELECT new FROM _series_map WHERE old = characters.series) "
            "WHERE source = 'anima' AND series IN (SELECT old FROM _series_map)"
        )
        updated = cur.rowcount
        conn.execute("DROP TABLE _series_map")
        conn.commit()

    print(f"Normalized {updated:,} Anima character series entries.")
    print(f"Distinct series remapped: {len(mapping):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
