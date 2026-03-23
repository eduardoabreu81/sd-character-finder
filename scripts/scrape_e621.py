"""
scrape_e621.py — Scraper for downloadmost.com/NoobAI-XL/e621-character/

Scrapes ~3,000 e621 characters (~125 pages) and saves to data/characters.db
(same unified DB as Danbooru, with source='e621').
Resumable: skips ranks already present for e621 source.

Usage:
    python scripts/scrape_e621.py              # full run (~125 pages, ~2 min)
    python scripts/scrape_e621.py --pages 3    # quick test (first 3 pages)
    python scripts/scrape_e621.py --resume     # skip already-scraped pages
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://www.downloadmost.com/NoobAI-XL/e621-character/"
CHARS_PER_PAGE = 24
TOTAL_PAGES = 125
RATE_LIMIT_SEC = 1.0
DB_PATH = Path(__file__).parent.parent / "data" / "characters.db"
SOURCE = "e621"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WildcardCreator/1.0; personal-use)",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

BASE_DDL = """
CREATE TABLE IF NOT EXISTS characters (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    series    TEXT,
    tags      TEXT NOT NULL,
    image_url TEXT,
    rank      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_name   ON characters(name   COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_series ON characters(series COLLATE NOCASE);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(BASE_DDL)
    # Migrate: add columns if not present (safe on any schema version)
    for ddl in [
        "ALTER TABLE characters ADD COLUMN danbooru_tag TEXT",
        "ALTER TABLE characters ADD COLUMN source TEXT DEFAULT 'danbooru'",
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    # Add index on source if missing
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON characters(source)")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Backfill NULLs
    conn.execute("UPDATE characters SET source = 'danbooru' WHERE source IS NULL")
    conn.commit()
    return conn


def last_e621_rank(conn: sqlite3.Connection) -> int:
    """Return the highest e621-specific rank already in the DB."""
    row = conn.execute(
        "SELECT MAX(rank) FROM characters WHERE source = ?", (SOURCE,)
    ).fetchone()
    return row[0] or 0


def e621_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM characters WHERE source = ?", (SOURCE,)
    ).fetchone()
    return row[0] or 0


def insert_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO characters (name, series, tags, image_url, rank, source) "
        "VALUES (:name, :series, :tags, :image_url, :rank, :source)",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Parsing  (same card structure as danbooru page)
# ---------------------------------------------------------------------------

def parse_page(html: str, page: int, rank_base: int) -> list[dict]:
    """Extract character records from one e621 listing page.

    Card structure is identical to the Danbooru page:
      <div class="card">
        <div class="card-header"><span>character name</span></div>
        <div class="text-center"><img src="..." alt="thumbnail"></div>
        <div class="card-body">
          <div>Prompt trigger:</div>
          <div class="alert alert-secondary">tag1, tag2, ...</div>
        </div>
      </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    rank_offset = (page - 1) * CHARS_PER_PAGE

    cards = soup.find_all("div", class_="card")
    for i, card in enumerate(cards):
        try:
            header = card.find("div", class_="card-header")
            if not header:
                continue
            span = header.find("span")
            name = span.get_text(strip=True) if span else header.get_text(strip=True)
            name = name.strip()
            if not name:
                continue

            img = card.find("img", alt="thumbnail")
            image_url = None
            if img:
                src = img.get("src", "")
                if src:
                    image_url = src if src.startswith("http") else BASE_URL.rstrip("/") + "/" + src.lstrip("/")

            tags_text = ""
            alert_div = card.find("div", class_="alert-secondary")
            if alert_div:
                tags_text = alert_div.get_text(separator=" ", strip=True)
                tags_text = " ".join(tags_text.split())

            series = None
            if tags_text:
                tag_list = [t.strip() for t in tags_text.split(",") if t.strip()]
                if tag_list and tag_list[0].lower() == name.lower():
                    tag_list = tag_list[1:]
                _skip = {"1girl", "1boy", "hair", "eyes", "long", "short", "solo"}
                for t in tag_list[:3]:
                    words = t.split()
                    if len(words) <= 4 and not any(skip in t for skip in _skip):
                        series = t
                        break

            records.append({
                "name": name,
                "series": series,
                "tags": tags_text,
                "image_url": image_url,
                "rank": rank_base + rank_offset + i + 1,
                "source": SOURCE,
            })
        except Exception:
            continue

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(pages: int, resume: bool) -> None:
    conn = open_db(DB_PATH)
    start_page = 1

    # Use a rank base offset above all existing Danbooru ranks to avoid conflicts
    danbooru_max = conn.execute("SELECT MAX(rank) FROM characters WHERE source != ?", (SOURCE,)).fetchone()[0] or 0
    rank_base = danbooru_max  # e621 ranks continue after Danbooru

    if resume:
        max_e621_rank = last_e621_rank(conn)
        if max_e621_rank:
            relative_rank = max_e621_rank - rank_base
            start_page = (relative_rank // CHARS_PER_PAGE) + 1
            print(f"Resuming from page {start_page} (last e621 rank: {max_e621_rank})")

    total_saved = e621_count(conn)
    end_page = min(start_page + pages - 1, TOTAL_PAGES) if pages else TOTAL_PAGES

    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(start_page, end_page + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [!] Page {page} failed: {exc} — skipping", file=sys.stderr)
            time.sleep(RATE_LIMIT_SEC * 2)
            continue

        records = parse_page(resp.text, page, rank_base)
        if records:
            insert_batch(conn, records)
            total_saved += len(records)

        if page % 20 == 0 or page == end_page:
            print(f"  Page {page}/{end_page} — {total_saved} e621 characters saved")

        if page < end_page:
            time.sleep(RATE_LIMIT_SEC)

    conn.close()
    print(f"\nDone. Total e621 characters in DB: {total_saved}")
    print(f"DB path: {DB_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape e621 character list into unified characters.db")
    parser.add_argument("--pages", type=int, default=0,
                        help="Number of pages to scrape (0 = all ~125)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip pages already in the DB")
    args = parser.parse_args()
    scrape(pages=args.pages, resume=args.resume)


if __name__ == "__main__":
    main()
