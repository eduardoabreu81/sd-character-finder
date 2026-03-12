"""
scrape_characters.py — One-time scraper for downloadmost.com/NoobAI-XL/danbooru-character/

Scrapes 20,016 characters (834 pages) and saves to data/characters.db (SQLite).
Resumable: skips pages already scraped by checking max rank in DB.

Usage:
    python scripts/scrape_characters.py              # full run (834 pages, ~14 min)
    python scripts/scrape_characters.py --pages 3    # quick test (first 3 pages)
    python scripts/scrape_characters.py --resume     # skip already-scraped pages
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

BASE_URL = "https://www.downloadmost.com/NoobAI-XL/danbooru-character/"
CHARS_PER_PAGE = 24          # site shows ~24 cards per page
TOTAL_PAGES = 834
RATE_LIMIT_SEC = 1.0         # seconds between requests (politeness)
DB_PATH = Path(__file__).parent.parent / "data" / "characters.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WildcardCreator/1.0; personal-use)",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS characters (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    series    TEXT,
    tags      TEXT NOT NULL,
    image_url TEXT,
    rank      INTEGER UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_name   ON characters(name   COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_series ON characters(series COLLATE NOCASE);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(DDL)
    conn.commit()
    return conn


def last_rank(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(rank) FROM characters").fetchone()
    return row[0] or 0


def insert_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO characters (name, series, tags, image_url, rank) "
        "VALUES (:name, :series, :tags, :image_url, :rank)",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_page(html: str, page: int) -> list[dict]:
    """Extract character records from one listing page.

    Card structure:
      <div class="card">
        <div class="card-header">
          <span ...>character name</span>
        </div>
        <div class="text-center">
          <img src="preview/<slug>.jpg" ...>
        </div>
        <div class="card-body">
          <div>Prompt tags:</div>
          <div class="alert alert-secondary">tag1, tag2, tag3, ...</div>
        </div>
      </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    rank_offset = (page - 1) * CHARS_PER_PAGE

    cards = soup.find_all("div", class_="card")
    for i, card in enumerate(cards):
        try:
            # Name — inside the card-header span
            header = card.find("div", class_="card-header")
            if not header:
                continue
            span = header.find("span")
            name = span.get_text(strip=True) if span else header.get_text(strip=True)
            name = name.strip()
            if not name:
                continue

            # Image URL — <img alt="thumbnail"> inside card
            img = card.find("img", alt="thumbnail")
            image_url = None
            if img:
                src = img.get("src", "")
                if src:
                    if src.startswith("http"):
                        image_url = src
                    else:
                        image_url = BASE_URL.rstrip("/") + "/" + src.lstrip("/")

            # Tags — div.alert-secondary inside card-body
            tags_text = ""
            alert_div = card.find("div", class_="alert-secondary")
            if alert_div:
                tags_text = alert_div.get_text(separator=" ", strip=True)
                tags_text = " ".join(tags_text.split())  # normalise whitespace

            # Series — typically the 2nd tag in the comma-separated list
            series = None
            if tags_text:
                tag_list = [t.strip() for t in tags_text.split(",") if t.strip()]
                # Remove the character name itself if it's the first tag
                if tag_list and tag_list[0].lower() == name.lower():
                    tag_list = tag_list[1:]
                # Series is first remaining tag that looks like a franchise
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
                "rank": rank_offset + i + 1,
            })
        except Exception:
            continue  # skip malformed cards silently

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(pages: int, resume: bool) -> None:
    conn = open_db(DB_PATH)
    start_page = 1

    if resume:
        max_rank = last_rank(conn)
        if max_rank:
            start_page = (max_rank // CHARS_PER_PAGE) + 1
            print(f"Resuming from page {start_page} (last rank: {max_rank})")

    total_saved = last_rank(conn)
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

        records = parse_page(resp.text, page)
        if records:
            insert_batch(conn, records)
            total_saved += len(records)

        if page % 50 == 0 or page == end_page:
            print(f"  Page {page}/{end_page} — {total_saved} characters saved")

        if page < end_page:
            time.sleep(RATE_LIMIT_SEC)

    conn.close()
    print(f"\nDone. Total characters in DB: {total_saved}")
    print(f"DB path: {DB_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape danbooru character list")
    parser.add_argument("--pages", type=int, default=0,
                        help="Number of pages to scrape (0 = all 834)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip pages already in the DB")
    args = parser.parse_args()

    scrape(pages=args.pages, resume=args.resume)


if __name__ == "__main__":
    main()
