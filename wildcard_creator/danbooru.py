"""
danbooru.py — Tag database backed by the Danbooru CSV dump and optional live API.

CSV columns expected (from danbooru tag dump):
  tag, category, post_count, aliases

category codes: 0=general, 1=artist, 3=copyright, 4=character, 5=meta

Usage:
  db = DanbooruDB()
  db.load_csv("/path/to/danbooru_tags.csv")          # full dump
  results = db.search("hair", min_post_count=1000)
  results = db.fetch_from_api("blue_hair", api_key="…", login="…")
"""

from __future__ import annotations

import csv
import fnmatch
import os
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DANBOORU_API_BASE = "https://danbooru.donmai.us"

CATEGORY_NAMES = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

# Categories we actually care about for wildcard generation
USEFUL_CATEGORIES = {0, 4}  # general + character tags


# ---------------------------------------------------------------------------
# DanbooruDB
# ---------------------------------------------------------------------------

class DanbooruDB:
    """
    In-memory tag database.
    Loaded from a local CSV dump for offline speed; can augment with live API.
    """

    def __init__(self) -> None:
        # tag → {post_count, category, aliases}
        self._tags: dict[str, dict] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_csv(self, csv_path: str | Path) -> int:
        """
        Load tags from a CSV file.
        Expected columns: tag, category, post_count[, aliases]
        Returns number of rows loaded.
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        count = 0
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Normalise column names (strip whitespace, lower)
            for row in reader:
                row = {k.strip().lower(): v.strip() for k, v in row.items()}
                tag = row.get("tag", row.get("name", ""))
                if not tag:
                    continue
                try:
                    post_count = int(row.get("post_count", "0"))
                    category = int(row.get("category", "0"))
                except ValueError:
                    post_count = 0
                    category = 0
                aliases_raw = row.get("aliases", row.get("tag_aliases", ""))
                aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
                self._tags[tag] = {
                    "tag": tag,
                    "post_count": post_count,
                    "category": category,
                    "category_name": CATEGORY_NAMES.get(category, "unknown"),
                    "aliases": aliases,
                }
                count += 1

        self._loaded = True
        return count

    def load_lightweight_csv(self) -> int:
        """
        Load the small curated CSV bundled with the extension.
        Located at <extension_root>/data/danbooru_tags.csv
        """
        here = Path(__file__).parent.parent
        csv_path = here / "data" / "danbooru_tags.csv"
        if not csv_path.exists():
            return 0
        return self.load_csv(csv_path)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        pattern: str,
        min_post_count: int = 500,
        max_results: int = 100,
        categories: Optional[set[int]] = None,
    ) -> list[dict]:
        """
        Search in-memory tags by glob pattern on the tag name.
        Returns list of tag dicts sorted by post_count descending.

        pattern examples: "blue_hair", "*hair*", "hair*"
        """
        if not self._loaded:
            self.load_lightweight_csv()

        if categories is None:
            categories = USEFUL_CATEGORIES

        pattern_lower = pattern.lower()
        results = []
        for tag, info in self._tags.items():
            if info["category"] not in categories:
                continue
            if info["post_count"] < min_post_count:
                continue
            if fnmatch.fnmatch(tag, pattern_lower) or pattern_lower in tag:
                results.append(info.copy())

        results.sort(key=lambda x: x["post_count"], reverse=True)
        return results[:max_results]

    def get_tag(self, tag_name: str) -> Optional[dict]:
        """Return info dict for a specific tag, or None if not found."""
        # Try exact match first
        info = self._tags.get(tag_name)
        if info:
            return info.copy()
        # Try alias lookup
        for info in self._tags.values():
            if tag_name in info["aliases"]:
                return info.copy()
        return None

    def tag_count(self) -> int:
        return len(self._tags)

    # ------------------------------------------------------------------
    # Live Danbooru API
    # ------------------------------------------------------------------

    def fetch_from_api(
        self,
        name_pattern: str,
        login: str,
        api_key: str,
        min_post_count: int = 500,
        max_results: int = 50,
        category: int = 0,
    ) -> list[dict]:
        """
        Fetch tags from the Danbooru API by name pattern.
        Results are also stored in the in-memory cache for reuse.
        """
        url = f"{DANBOORU_API_BASE}/tags.json"
        params = {
            "search[name_matches]": name_pattern,
            "search[category]": category,
            "search[post_count_gte]": min_post_count,
            "limit": max_results,
            "order": "count",
            "login": login,
            "api_key": api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            raw_tags = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Danbooru API error: {exc}") from exc

        results = []
        for t in raw_tags:
            tag = t.get("name", "")
            if not tag:
                continue
            info = {
                "tag": tag,
                "post_count": int(t.get("post_count", 0)),
                "category": int(t.get("category", 0)),
                "category_name": CATEGORY_NAMES.get(int(t.get("category", 0)), "unknown"),
                "aliases": [],
            }
            self._tags[tag] = info
            results.append(info.copy())

        return results

    def fetch_tag_group(
        self,
        group_name: str,
        login: str,
        api_key: str,
    ) -> list[str]:
        """
        Fetch a tag group wiki page from Danbooru.
        group_name example: 'hair_color', 'body_parts'
        Returns list of tag strings extracted from the wiki body.
        """
        url = f"{DANBOORU_API_BASE}/wiki_pages.json"
        params = {
            "search[title]": f"tag_group:{group_name}",
            "only": "body",
            "login": login,
            "api_key": api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            pages = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Danbooru tag group fetch error: {exc}") from exc

        if not pages:
            return []

        body = pages[0].get("body", "")
        # Extract tags from [[tag_name]] wiki links
        import re
        tags = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", body)
        return [t.replace(" ", "_").lower() for t in tags]


# ---------------------------------------------------------------------------
# Module-level singleton (lazy init)
# ---------------------------------------------------------------------------

_default_db: Optional[DanbooruDB] = None


def get_db() -> DanbooruDB:
    """Return the module-level shared DanbooruDB instance."""
    global _default_db
    if _default_db is None:
        _default_db = DanbooruDB()
        _default_db.load_lightweight_csv()
    return _default_db
