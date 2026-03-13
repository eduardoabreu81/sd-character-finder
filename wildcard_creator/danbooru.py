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

    def fetch_character_post_tags(
        self,
        character_name: str,
        login: str = "",
        api_key: str = "",
        n_posts: int = 100,
        top_n: int = 40,
        min_freq: float = 0.10,
    ) -> list[dict]:
        """
        Fetch the most common tags associated with a character on Danbooru.

        Queries /posts.json with the character tag, collects all tags from the
        returned posts, counts frequency, and returns the top_n most common ones
        (excluding the character tag itself and meta/copyright tags).

        Args:
            character_name: Human-readable name, e.g. "hatsune miku" or "hatsune_miku".
            login/api_key:  Optional Danbooru credentials (anonymous works, lower rate limit).
            n_posts:        How many posts to sample (max 200 without auth, 1000 with).
            top_n:          Return at most this many tags.
            min_freq:       Minimum fraction of posts a tag must appear in to be included.

        Returns:
            List of dicts: {tag, count, frequency, category, category_name}
            sorted by count descending.
        """
        # Normalize name to Danbooru underscore format
        tag_query = character_name.strip().replace(" ", "_").lower()

        url = f"{DANBOORU_API_BASE}/posts.json"
        params: dict = {
            "tags": tag_query,
            "limit": min(n_posts, 200),
        }
        if login and api_key:
            params["login"] = login
            params["api_key"] = api_key

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            posts = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Danbooru posts fetch error: {exc}") from exc

        if not isinstance(posts, list) or not posts:
            return []

        # Count tag occurrences across all posts
        from collections import Counter
        counter: Counter = Counter()
        total_posts = len(posts)
        for post in posts:
            tag_string = post.get("tag_string", "")
            for t in tag_string.split():
                counter[t] += 1

        # Build result list — keep only physical description tags.
        # Skip: artists (1), meta (5), image-quality general tags, poses, actions, expressions.
        SKIP_CATEGORIES = {1, 5}  # artist, meta
        SKIP_GENERAL_TAGS = {
            # ── Image quality / source (category 0 but not character trait) ──
            "highres", "absurdres", "ultra-detailed", "commentary",
            "commentary request", "english commentary", "translation request",
            "translated", "paid reward available", "patreon reward",
            "official art", "scan", "censored", "uncensored",
            "jpeg artifacts", "watermark", "web address", "signature",
            # ── Poses / positions ──
            "standing", "sitting", "lying", "kneeling", "squatting", "crouching",
            "leaning forward", "leaning back", "on one knee", "all fours",
            "lying on back", "lying on side", "on stomach", "spread legs",
            "legs apart", "wariza", "seiza", "bent over", "arched back",
            "legs up", "legs together",
            # ── Actions ──
            "holding", "running", "walking", "jumping", "floating", "flying",
            "dancing", "fighting", "sleeping", "eating", "drinking", "reading",
            "pointing", "reaching", "stretching", "waving", "raising hand",
            "arms up", "arms behind back", "arms behind head", "hand on hip",
            "hand on own chest", "hands clasped", "hands on own hips",
            "hands on own thighs", "hands on own face",
            "hugging", "kissing", "carrying",
            # ── Expressions / emotions ──
            "smile", "smiling", "grin", "grinning", "laughing", "crying",
            "tears", "blush", "blushing", "open mouth", "closed mouth",
            "frown", "frowning", "pout", "pouting", "embarrassed", "surprised",
            "confused", "angry", "expressionless", "serious", "nervous",
            "seductive smile", "light smile", "closed eyes", "one eye closed",
            "wink",
            # ── Looking direction ──
            "looking at viewer", "looking back", "looking up", "looking down",
            "looking away", "looking to the side", "looking to the left",
            "looking to the right", "looking over shoulder", "eye contact",
            "staring", "pov",
            # ── Scene / background / framing ──
            "solo", "duo", "outdoors", "indoors", "simple background",
            "white background", "black background", "pink background",
            "gradient background", "upper body", "full body", "cowboy shot",
            "close-up", "portrait", "from below", "from above", "from behind",
            "from side", "dutch angle", "profile",
            # ── Count tags ──
            "1girl", "1boy", "2girls", "2boys", "3girls", "3boys",
            "multiple girls", "multiple boys", "no humans",
        }
        results = []
        for raw_tag, count in counter.most_common():
            if raw_tag == tag_query:
                continue
            freq = count / total_posts
            if freq < min_freq:
                break  # already sorted desc, can stop early
            human_tag = raw_tag.replace("_", " ")
            # Look up category — falls back to general(0) if unknown
            info = self._tags.get(human_tag) or self._tags.get(raw_tag)
            category = info["category"] if info else 0
            if category in SKIP_CATEGORIES:
                continue
            if human_tag in SKIP_GENERAL_TAGS:
                continue
            results.append({
                "tag": human_tag,
                "raw_tag": raw_tag,
                "count": count,
                "frequency": round(freq, 3),
                "category": category,
                "category_name": CATEGORY_NAMES.get(category, "general"),
            })
            if len(results) >= top_n:
                break

        return results

    def search_character_tags(
        self,
        query: str,
        login: str = "",
        api_key: str = "",
        limit: int = 10,
    ) -> list[dict]:
        """
        Search Danbooru for character tags matching a query string.
        Returns list of {tag, post_count} sorted by post_count desc.
        """
        url = f"{DANBOORU_API_BASE}/tags.json"
        params: dict = {
            "search[name_matches]": f"*{query.replace(' ', '_')}*",
            "search[category]": 4,  # character tags only
            "order": "count",
            "limit": limit,
        }
        if login and api_key:
            params["login"] = login
            params["api_key"] = api_key

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Danbooru tag search error: {exc}") from exc

        if not isinstance(raw, list):
            return []

        return [
            {
                "tag": t["name"].replace("_", " "),
                "raw_tag": t["name"],
                "post_count": int(t.get("post_count", 0)),
            }
            for t in raw
            if t.get("name")
        ]

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
