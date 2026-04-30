"""
scrape_artists.py — One-time scraper for downloadmost.com/NoobAI-XL/danbooru-artist/

Scrapes ~6,000 artist style references and saves to data/artists.db (SQLite).
Resumable: skips pages already scraped by checking max rank in DB.

Each artist has two preview images:
  - preview1/<name>.jpg (Harry Potter style example)
  - preview2/<name>.jpg (Tifa Lockhart style example)

Usage:
    python scripts/scrape_artists.py              # full run (~251 pages, ~6k artists)
    python scripts/scrape_artists.py --pages 3    # quick test (first 3 pages)
    python scripts/scrape_artists.py --resume     # skip already-scraped pages
    python scripts/scrape_artists.py --source e621 # scrape e621 artists instead
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL_DANBOORU = "https://www.downloadmost.com/NoobAI-XL/danbooru-artist/"
BASE_URL_E621 = "https://www.downloadmost.com/NoobAI-XL/e621-artist/"
ARTISTS_PER_PAGE = 24
TOTAL_PAGES_DANBOORU = 251
TOTAL_PAGES_E621 = 0  # TODO: discover dynamically or set after first run
RATE_LIMIT_SEC = 1.0
DB_PATH = Path(__file__).parent.parent / "data" / "artists.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WildcardCreator/1.0; personal-use)",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS artists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    tag         TEXT NOT NULL,
    display_name TEXT NOT NULL,
    image_url_1 TEXT,
    image_url_2 TEXT,
    ref_count   INTEGER DEFAULT 0,
    source      TEXT DEFAULT 'danbooru',
    rank        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_artist_name   ON artists(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_artist_tag    ON artists(tag COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_artist_source ON artists(source);
CREATE INDEX IF NOT EXISTS idx_artist_rank   ON artists(rank);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(DDL)
    conn.commit()
    return conn


def last_rank(conn: sqlite3.Connection, source: str) -> int:
    row = conn.execute(
        "SELECT MAX(rank) FROM artists WHERE source = ?", (source,)
    ).fetchone()
    return row[0] or 0


def insert_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO artists (name, tag, display_name, image_url_1, image_url_2, ref_count, source, rank) "
        "VALUES (:name, :tag, :display_name, :image_url_1, :image_url_2, :ref_count, :source, :rank)",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _to_display_name(name: str) -> str:
    """Convert underscore tag to human-readable display name.
    
    'hammer_(sunset_beach)' -> 'hammer (sunset beach)'
    'ebifurya' -> 'ebifurya'
    """
    display = name.replace("_", " ")
    display = display.replace("\\(", "(").replace("\\)", ")")
    return display


def parse_page(html: str, page: int, base_url: str, source: str) -> list[dict]:
    """Extract artist records from one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    records = []
    rank_offset = (page - 1) * ARTISTS_PER_PAGE

    cards = soup.find_all("div", class_="card")
    for i, card in enumerate(cards):
        try:
            # Name — inside the card-header span
            name_span = card.find("span", class_="user-select-all")
            if not name_span:
                continue
            name = name_span.get_text(strip=True)
            if not name:
                continue

            # The name from the site is already in Danbooru tag format (underscores)
            tag = name
            display_name = _to_display_name(name)

            # Images — there are exactly 2 thumbnails per card
            imgs = card.find_all("img", alt="thumbnail")
            image_url_1 = None
            image_url_2 = None
            if len(imgs) >= 2:
                src1 = imgs[0].get("src", "")
                src2 = imgs[1].get("src", "")
                if src1:
                    image_url_1 = _abs_url(src1, base_url)
                if src2:
                    image_url_2 = _abs_url(src2, base_url)
            elif len(imgs) == 1:
                src1 = imgs[0].get("src", "")
                if src1:
                    image_url_1 = _abs_url(src1, base_url)

            # Reference count from card-body text
            ref_count = 0
            card_body = card.find("div", class_="card-body")
            if card_body:
                text = card_body.get_text(separator=" ", strip=True)
                m = re.search(r"Reference images:\s*(\d+)", text)
                if m:
                    ref_count = int(m.group(1))

            records.append({
                "name": name,
                "tag": tag,
                "display_name": display_name,
                "image_url_1": image_url_1,
                "image_url_2": image_url_2,
                "ref_count": ref_count,
                "source": source,
                "rank": rank_offset + i + 1,
            })
        except Exception:
            continue  # skip malformed cards silently

    return records


def _abs_url(src: str, base_url: str) -> str:
    """Convert relative URL to absolute."""
    if src.startswith("http"):
        return src
    base = base_url.rstrip("/")
    return base + "/" + src.lstrip("/")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_total_pages(base_url: str) -> int:
    """Binary search to find the last valid page (before wrap-around)."""
    session = requests.Session()
    session.headers.update(HEADERS)

    def _first_name(page: int) -> str:
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", class_="card")
        if not cards:
            return ""
        span = cards[0].find("span", class_="user-select-all")
        return span.get_text(strip=True) if span else ""

    first_page_name = _first_name(1)
    if not first_page_name:
        return 0

    # Exponential search for upper bound
    upper = 2
    while True:
        name = _first_name(upper)
        if name == first_page_name or not name:
            break
        upper *= 2
        time.sleep(RATE_LIMIT_SEC)

    # Binary search between upper//2 and upper
    low, high = upper // 2, upper
    last_valid = low
    while low <= high:
        mid = (low + high) // 2
        name = _first_name(mid)
        time.sleep(RATE_LIMIT_SEC)
        if name and name != first_page_name:
            last_valid = mid
            low = mid + 1
        else:
            high = mid - 1

    return last_valid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(pages: int, resume: bool, source: str) -> None:
    base_url = BASE_URL_E621 if source == "e621" else BASE_URL_DANBOORU

    # Discover total pages if not known
    total_pages = TOTAL_PAGES_E621 if source == "e621" else TOTAL_PAGES_DANBOORU
    if not total_pages:
        print(f"Discovering total pages for {source}...")
        total_pages = discover_total_pages(base_url)
        print(f"  Found {total_pages} pages (~{total_pages * ARTISTS_PER_PAGE} artists)")

    conn = open_db(DB_PATH)
    start_page = 1

    if resume:
        max_rank = last_rank(conn, source)
        if max_rank:
            start_page = (max_rank // ARTISTS_PER_PAGE) + 1
            print(f"Resuming from page {start_page} (last rank: {max_rank})")

    total_saved = last_rank(conn, source)
    end_page = min(start_page + pages - 1, total_pages) if pages else total_pages

    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(start_page, end_page + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [!] Page {page} failed: {exc} — skipping", file=sys.stderr)
            time.sleep(RATE_LIMIT_SEC * 2)
            continue

        records = parse_page(resp.text, page, base_url, source)
        if records:
            insert_batch(conn, records)
            total_saved += len(records)

        if page % 50 == 0 or page == end_page:
            print(f"  Page {page}/{end_page} — {total_saved} artists saved")

        if page < end_page:
            time.sleep(RATE_LIMIT_SEC)

    conn.close()
    print(f"\nDone. Total {source} artists in DB: {total_saved}")
    print(f"DB path: {DB_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape artist style references")
    parser.add_argument("--pages", type=int, default=0,
                        help="Number of pages to scrape (0 = all)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip pages already in the DB")
    parser.add_argument("--source", choices=["danbooru", "e621"], default="danbooru",
                        help="Which source to scrape (default: danbooru)")
    args = parser.parse_args()

    scrape(pages=args.pages, resume=args.resume, source=args.source)


if __name__ == "__main__":
    main()
