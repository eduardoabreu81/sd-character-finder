#!/usr/bin/env python3
"""
Merge the AnimaDex catalogue into the main app databases.

This imports characters and artists from:
    data/anima_characters.db
    data/anima_artists.db

into the main app databases:
    data/characters.db
    data/artists.db

Rows are tagged with source='anima' so the UI can filter them alongside the
existing danbooru and e621 sources.

Usage:
    python scripts/import_anima_to_main_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

ANIMA_CHAR_DB = DATA_DIR / "anima_characters.db"
ANIMA_ARTIST_DB = DATA_DIR / "anima_artists.db"
MAIN_CHAR_DB = DATA_DIR / "characters.db"
MAIN_ARTIST_DB = DATA_DIR / "artists.db"

R2_BASE = "https://blobs.animadex.net"


def _r2_thumb_url(prefix: str, thumbname: str) -> str:
    """Build an R2 thumbnail URL preserving spaces/commas in the filename."""
    from urllib.parse import quote

    return f"{R2_BASE}/{prefix}/{quote(thumbname, safe='(),')}"


def _titlecase(text: str) -> str:
    """Lightweight title-caser that keeps existing uppercase letters."""

    def _cap(word: str) -> str:
        for i, ch in enumerate(word):
            if ch.isalpha():
                return word[:i] + ch.upper() + word[i + 1 :]
        return word

    return " ".join(_cap(w) for w in text.split(" "))


def _next_rank(conn: sqlite3.Connection, table: str) -> int:
    """Return the next free rank value for the given table."""
    row = conn.execute(f"SELECT MAX(rank) FROM {table}").fetchone()
    return (row[0] or 0) + 1


def import_characters() -> int:
    """Import Anima characters into the main characters.db."""
    if not ANIMA_CHAR_DB.exists():
        raise FileNotFoundError(f"Run scripts/import_anima.py first: {ANIMA_CHAR_DB}")

    anima = sqlite3.connect(ANIMA_CHAR_DB)
    anima.row_factory = sqlite3.Row

    main = sqlite3.connect(MAIN_CHAR_DB)
    main.row_factory = sqlite3.Row

    try:
        # Ensure source column exists (legacy DBs may lack it)
        main.execute("ALTER TABLE characters ADD COLUMN source TEXT DEFAULT 'danbooru'")
        main.commit()
    except sqlite3.OperationalError:
        pass

    try:
        next_rank = _next_rank(main, "characters")

        rows = anima.execute(
            "SELECT character, copyright, name, trigger, core_tags, count, thumbname "
            "FROM characters ORDER BY count DESC"
        ).fetchall()

        imported = 0
        for row in rows:
            trigger = (row["trigger"] or "").strip()
            core_tags = (row["core_tags"] or "").strip()
            copyright_ = (row["copyright"] or "").strip()

            # Build a single tags string matching the current app format:
            # trigger (character + series) followed by descriptive tags.
            tags = trigger
            if core_tags:
                tags = f"{tags}, {core_tags}" if tags else core_tags

            name = row["name"] or _titlecase(row["character"].replace("_", " "))
            series = copyright_
            image_url = _r2_thumb_url("Outputs/thumbs", row["thumbname"]) if row["thumbname"] else None

            main.execute(
                """
                INSERT INTO characters
                (name, series, tags, image_url, rank, danbooru_tag, source)
                VALUES (?, ?, ?, ?, ?, ?, 'anima')
                """,
                (name, series, tags, image_url, next_rank, trigger),
            )
            next_rank += 1
            imported += 1

        main.commit()
        return imported
    finally:
        anima.close()
        main.close()


def import_artists() -> int:
    """Import Anima artists into the main artists.db."""
    if not ANIMA_ARTIST_DB.exists():
        raise FileNotFoundError(f"Run scripts/import_anima.py first: {ANIMA_ARTIST_DB}")

    anima = sqlite3.connect(ANIMA_ARTIST_DB)
    anima.row_factory = sqlite3.Row

    main = sqlite3.connect(MAIN_ARTIST_DB)
    main.row_factory = sqlite3.Row

    try:
        next_rank = _next_rank(main, "artists")

        rows = anima.execute(
            "SELECT artist, name, trigger, count, thumbname FROM artists ORDER BY count DESC"
        ).fetchall()

        imported = 0
        for row in rows:
            trigger = (row["trigger"] or "").strip()
            artist_key = (row["artist"] or "").strip()

            # Anima artist triggers are used with a leading '@' in prompts.
            tag = f"@{trigger}" if not trigger.startswith("@") else trigger
            display_name = row["name"] or _titlecase(trigger)
            name = artist_key or trigger.replace(" ", "_")
            image_url_1 = _r2_thumb_url("ArtistOutputs/thumbs", row["thumbname"]) if row["thumbname"] else None
            ref_count = row["count"] or 0

            main.execute(
                """
                INSERT INTO artists
                (name, tag, display_name, image_url_1, image_url_2, ref_count, source, rank)
                VALUES (?, ?, ?, ?, NULL, ?, 'anima', ?)
                """,
                (name, tag, display_name, image_url_1, ref_count, next_rank),
            )
            next_rank += 1
            imported += 1

        main.commit()
        return imported
    finally:
        anima.close()
        main.close()


def main() -> int:
    print("Importing AnimaDex characters into main database...")
    n_chars = import_characters()
    print(f"  Imported {n_chars:,} characters")

    print("Importing AnimaDex artists into main database...")
    n_artists = import_artists()
    print(f"  Imported {n_artists:,} artists")

    print("\nDone.")
    print(f"  Main character DB: {MAIN_CHAR_DB}")
    print(f"  Main artist DB: {MAIN_ARTIST_DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
