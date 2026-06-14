#!/usr/bin/env python3
"""
Import the AnimaDex public catalogue into local SQLite databases.

The AnimaDex export token can be provided via:
  1) WebUI Settings > SD Character Finder > AnimaDex export token (recommended)
  2) --token command-line argument
  3) ANIMADEX_TOKEN environment variable

Usage:
    python scripts/import_anima.py
    python scripts/import_anima.py --token YOUR_TOKEN
    ANIMADEX_TOKEN=YOUR_TOKEN python scripts/import_anima.py

This downloads the character and artist CSVs from animadex.net and builds:
    data/anima_characters.db
    data/anima_artists.db

Images are NOT downloaded here. They are fetched on-demand by the UI from
https://blobs.animadex.net and cached locally under data/anima_covers/.

NOTE: AnimaDex export tokens are personal. Full catalogue downloads are limited
to 1x per 48h per token; delta updates and thumbnails are always allowed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

DEFAULT_SITE = "https://animadex.net"
USER_AGENT = "animadex-import/1"


def _get(url: str, headers: dict | None = None, timeout: int = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def fetch_manifest(site: str, token: str) -> dict:
    url = site.rstrip("/") + "/api/export/manifest"
    headers = {"X-Export-Token": token}
    status, body = _get(url, headers)
    data = json.loads(body.decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Manifest request failed: {data}")
    return data


def download_csv(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    status, body = _get(url)
    tmp.write_bytes(body)
    os.replace(tmp, dest)
    print(f"  Downloaded {dest.name}: {len(body):,} bytes")


def init_character_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character TEXT NOT NULL UNIQUE,
            copyright TEXT,
            name TEXT,
            trigger TEXT NOT NULL,
            core_tags TEXT,
            count INTEGER DEFAULT 0,
            url TEXT,
            imgname TEXT,
            thumbname TEXT,
            search_blob TEXT
        );
        CREATE INDEX idx_char_search ON characters(search_blob);
        CREATE INDEX idx_char_copyright ON characters(copyright);
        CREATE INDEX idx_char_count ON characters(count DESC);
        """
    )
    return conn


def init_artist_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL UNIQUE,
            name TEXT,
            trigger TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            url TEXT,
            score REAL,
            imgname TEXT,
            thumbname TEXT,
            search_blob TEXT
        );
        CREATE INDEX idx_artist_search ON artists(search_blob);
        CREATE INDEX idx_artist_count ON artists(count DESC);
        CREATE INDEX idx_artist_score ON artists(score DESC);
        """
    )
    return conn


def sanitize_filename(name: str) -> str:
    illegal = '<>:"/\\|?*'
    cleaned = "".join("_" if c in illegal else c for c in name)
    return cleaned.rstrip(" .") or "unnamed"


def titlecase(text: str) -> str:
    def _cap(word: str) -> str:
        for i, ch in enumerate(word):
            if ch.isalpha():
                return word[:i] + ch.upper() + word[i + 1 :]
        return word
    return " ".join(_cap(w) for w in text.split(" "))


def import_characters(conn: sqlite3.Connection, csv_path: Path) -> int:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            character = (row.get("character") or "").strip()
            copyright_ = (row.get("copyright") or "").strip()
            trigger = (row.get("trigger") or "").strip()
            core_tags = (row.get("core_tags") or "").strip()
            if not character:
                continue
            if ", " in trigger:
                nm, _ = trigger.split(", ", 1)
            else:
                nm = trigger
            name = titlecase(nm) if nm else titlecase(character.replace("_", " "))
            try:
                count = int(row.get("count") or 0)
            except ValueError:
                count = 0
            stem = sanitize_filename(trigger)
            search_blob = " ".join((character, copyright_, trigger, core_tags)).lower()
            rows.append(
                (
                    character,
                    copyright_,
                    name,
                    trigger,
                    core_tags,
                    count,
                    (row.get("url") or "").strip(),
                    stem + ".png",
                    stem + ".webp",
                    search_blob,
                )
            )
    conn.executemany(
        """
        INSERT INTO characters
        (character, copyright, name, trigger, core_tags, count, url, imgname, thumbname, search_blob)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def import_artists(conn: sqlite3.Connection, csv_path: Path) -> int:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            artist = (row.get("artist") or "").strip()
            trigger = (row.get("trigger") or "").strip() or artist.replace("_", " ")
            if not artist:
                continue
            name = titlecase(trigger)
            try:
                count = int(row.get("count") or 0)
            except ValueError:
                count = 0
            try:
                score = float(row.get("score") or 0.0)
            except ValueError:
                score = 0.0
            stem = sanitize_filename(trigger)
            search_blob = " ".join((artist, trigger)).lower()
            rows.append(
                (
                    artist,
                    name,
                    trigger,
                    count,
                    (row.get("url") or "").strip(),
                    score,
                    stem + ".png",
                    stem + ".webp",
                    search_blob,
                )
            )
    conn.executemany(
        """
        INSERT INTO artists
        (artist, name, trigger, count, url, score, imgname, thumbname, search_blob)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def _get_settings_token() -> tuple[str, str]:
    """Read AnimaDex token/site from the WebUI settings if available."""
    try:
        from modules import shared

        token = str(getattr(shared.opts, "sdcf_animadex_token", "") or "")
        site = str(getattr(shared.opts, "sdcf_animadex_site", DEFAULT_SITE) or DEFAULT_SITE)
        return token, site
    except Exception:
        return "", DEFAULT_SITE


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token", default=None, help="AnimaDex export token (overrides settings/env)")
    ap.add_argument("--site", default=None, help="AnimaDex site base URL (overrides settings)")
    args = ap.parse_args(argv)

    settings_token, settings_site = _get_settings_token()
    token = (args.token or os.environ.get("ANIMADEX_TOKEN") or settings_token or "").strip()
    site = (args.site or settings_site or DEFAULT_SITE).strip()

    if not token:
        ap.error(
            "AnimaDex export token is required.\n"
            "Set it in Settings > SD Character Finder > AnimaDex export token, "
            "or use --token / ANIMADEX_TOKEN env var.\n"
            "Note: full catalogue downloads are limited to 1x per 48h per token; "
            "delta updates and thumbnails are always allowed."
        )

    print(f"Contacting {site}...")
    manifest = fetch_manifest(site, token)
    print(f"Catalogue version: {manifest['version']}")
    print(f"R2 base: {manifest['r2_base']}")

    csv_dir = DATA_DIR / "anima_import"
    csv_dir.mkdir(parents=True, exist_ok=True)

    chars_csv = csv_dir / "characters.csv"
    artists_csv = csv_dir / "artists.csv"

    print("\nDownloading CSVs...")
    download_csv(manifest["csv"]["characters"], chars_csv)
    download_csv(manifest["csv"]["artists"], artists_csv)

    print("\nBuilding character database...")
    char_db_path = DATA_DIR / "anima_characters.db"
    char_conn = init_character_db(char_db_path)
    try:
        n_chars = import_characters(char_conn, chars_csv)
        print(f"  Imported {n_chars:,} characters")
    finally:
        char_conn.close()

    print("\nBuilding artist database...")
    artist_db_path = DATA_DIR / "anima_artists.db"
    artist_conn = init_artist_db(artist_db_path)
    try:
        n_artists = import_artists(artist_conn, artists_csv)
        print(f"  Imported {n_artists:,} artists")
    finally:
        artist_conn.close()

    print("\nDone.")
    print(f"  Character DB: {char_db_path}")
    print(f"  Artist DB: {artist_db_path}")
    print("\nImages are fetched on-demand by the UI.")


if __name__ == "__main__":
    main()
