"""
resolve_danbooru_tags.py — Add/update the `danbooru_tag` column in characters.db.

Approach (inspired by Danbooru Tags Sort Exporter):
  Instead of looking up tag names directly, we search POSTS with the character
  name and read `tag_string_character` from the results — exactly like the
  userscript reads tags already present on a post page.

  This works even when our DB name differs from the Danbooru tag because:
    • Danbooru resolves aliases automatically in post searches
    • "yor forger" → finds posts tagged "yor_briar" via the alias
    • "kaguya shinomiya" → finds posts tagged "shinomiya_kaguya" via alias

  Resolution order per character:
    1. Full name as post search query       ("hatsune_miku")
    2. Inverted name (Japanese order)       ("shinomiya_kaguya")
    3. Base name stripped of series suffix  ("black_swan" from "black swan (honkai)")
    4. Base name inverted                   ("swan_black" — rarely needed)

    The chosen tag must share ≥1 meaningful word with our DB name to avoid
    false positives.

  danbooru_tag is stored with SPACES (no underscores):
    "yor briar", "shinomiya kaguya", "emma (yakusoku no neverland)"

Usage:
    # Validate 10 names, no DB writes:
    python scripts/resolve_danbooru_tags.py --login USER --api-key KEY --sample 10 --dry-run

    # Phase 1: fill only direct CSV matches (no API calls):
    python scripts/resolve_danbooru_tags.py --csv PATH\\to\\tags.csv --csv-only --resume --limit 500 --summary-only

    # Phase 2: resolve only the remaining rows via API:
    python scripts/resolve_danbooru_tags.py --api-only --resume --limit 500 --summary-only

    # Process a deterministic batch of 500 rows:
    python scripts/resolve_danbooru_tags.py --csv PATH\\to\\tags.csv --limit 500 --offset 0 --resume --summary-only

    # Full run:
    python scripts/resolve_danbooru_tags.py --login USER --api-key KEY

    # Resume after interruption:
    python scripts/resolve_danbooru_tags.py --login USER --api-key KEY --resume
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import requests

# Force UTF-8 output — prevents cp1252 crash on Windows with Japanese chars
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH      = Path(__file__).parent.parent / "data" / "characters.db"
DANBOORU_API = "https://danbooru.donmai.us"

RATE_LIMIT_DELAY = 0.15  # auth: ~6 req/s
ANON_DELAY       = 1.1   # anon: ~1 req/s

_STOP_WORDS = {"the", "of", "a", "an", "in", "no", "to", "de", "la", "el", "wa", "ga"}


# ---------------------------------------------------------------------------
# CSV lookup
# ---------------------------------------------------------------------------

def load_csv(csv_path: Path) -> dict[str, str]:
    """Load a Danbooru tag dump CSV into a lowercase-query → raw_tag dict.

    Only character tags (category == 4) are kept.
    Expected CSV columns: tag_name, category, post_count[, aliases, ...]
    tag_name uses underscores (e.g. 'hatsune_miku').
    Aliases from the 4th column are also indexed to the canonical tag_name.
    """
    lookup: dict[str, str] = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            tag_name, category = row[0].strip(), row[1].strip()
            if category == "4":
                lookup[tag_name.lower()] = tag_name
                if len(row) >= 4 and row[3].strip():
                    for alias in row[3].split(","):
                        alias = alias.strip().lower()
                        if alias and alias not in lookup:
                            lookup[alias] = tag_name
    return lookup


def _csv_lookup(query: str, csv_data: dict[str, str]) -> str | None:
    """Exact lookup in pre-loaded CSV dict; returns raw_tag or None."""
    return csv_data.get(query.lower())


def _canonicalize_with_csv(raw_tag: str, csv_data: dict[str, str] | None) -> str:
    """Return canonical CSV tag_name for raw_tag (or empty string if missing).

    csv_data maps both canonical names and aliases to canonical tag_name.
    """
    if not csv_data:
        return ""
    return csv_data.get(raw_tag.lower(), "")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _get(endpoint: str, params: dict, login: str, api_key: str, delay: float):
    if login and api_key:
        params = {**params, "login": login, "api_key": api_key}
    r = requests.get(f"{DANBOORU_API}{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    time.sleep(delay)
    return r.json()


def _char_tags_from_posts(query: str, login: str, api_key: str, delay: float) -> Counter:
    """
    Search posts by query, collect character tags from tag_string_character.
    Danbooru resolves aliases in post searches, so 'yor_forger' returns posts
    tagged 'yor_briar'. Returns Counter of raw_tag → post_count.
    """
    data = _get(
        "/posts.json",
        {"tags": query, "limit": 50, "only": "tag_string_character"},
        login, api_key, delay,
    )
    counter: Counter = Counter()
    if not isinstance(data, list):
        return counter
    for post in data:
        for tag in post.get("tag_string_character", "").split():
            counter[tag] += 1
    return counter


def _resolve_copyright_alias(query: str, login: str, api_key: str, delay: float) -> str:
    """Resolve an English copyright name to Danbooru canonical tag if an alias exists.

    Example: the_promised_neverland -> yakusoku_no_neverland
    Returns the canonical raw tag, or the original query if no alias is found.
    """
    data = _get(
        "/tag_aliases.json",
        {"search[antecedent_name]": query},
        login,
        api_key,
        delay,
    )
    if isinstance(data, list) and data:
        consequent = data[0].get("consequent_name", "")
        if consequent:
            return consequent
    return query


def _search_character_tags(query: str, login: str, api_key: str, delay: float) -> list[dict]:
    """Search character tags directly as a last-resort fallback."""
    data = _get(
        "/tags.json",
        {
            "search[name_matches]": f"*{query}*",
            "search[category]": 4,
            "order": "count",
            "limit": 20,
        },
        login, api_key, delay,
    )
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Name utilities
# ---------------------------------------------------------------------------

def _meaningful_words(name: str) -> set[str]:
    clean = name.lower().replace("_", " ")
    clean = re.sub(r"[()\\]", " ", clean)
    return set(clean.split()) - _STOP_WORDS


def _normalize_db_name(name: str) -> str:
    """Convert DB display name into a Danbooru-friendly human name.

    The DB stores literal backslashes for escaped parentheses, e.g.
    "2b \\(nier:automata\\)". Danbooru expects normal parentheses in the
    human-readable form before we convert spaces to underscores.
    """
    return name.replace("\\(", "(").replace("\\)", ")").strip()


def _to_query(name: str) -> str:
    """Convert normalized human name to Danbooru query format."""
    return _normalize_db_name(name).replace(" ", "_").lower()


def _strip_series(name: str) -> str:
    """'black swan (honkai: star rail)' → 'black swan'"""
    return re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()


def _series_suffix(name: str) -> str:
    """Return trailing '(series)' text without parentheses, or empty string."""
    match = re.search(r"\(([^)]+)\)\s*$", name)
    return match.group(1).strip() if match else ""


def _invert(name: str) -> str:
    """'kaguya shinomiya' → 'shinomiya kaguya' (2-word, no parens only)"""
    parts = name.split()
    if len(parts) == 2 and "(" not in name:
        return f"{parts[1]} {parts[0]}"
    return ""


def _best_match(counter: Counter, orig_words: set[str]) -> str | None:
    """Most frequent tag that shares ≥1 meaningful word with the original name."""
    for raw_tag, _ in counter.most_common():
        if _meaningful_words(raw_tag) & orig_words:
            return raw_tag
    return None


def _best_tag_candidate(candidates: list[dict], orig_words: set[str], orig_series_words: set[str]) -> str | None:
    """Pick the best tag result with contextual validation.

    If the original name has a series suffix and the candidate also has one,
    require at least one overlapping series word. This blocks cases like
    'emma (the promised neverland)' matching an unrelated 'emma (...nikke)'.
    """
    scored: list[tuple[int, int, str]] = []
    for cand in candidates:
        raw_tag = cand.get("name", "")
        overlap = len(_meaningful_words(raw_tag) & orig_words)
        if overlap <= 0:
            continue
        cand_series_words = _meaningful_words(_series_suffix(raw_tag))
        if orig_series_words and cand_series_words and not (cand_series_words & orig_series_words):
            continue
        scored.append((overlap, int(cand.get("post_count", 0)), raw_tag))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][2]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def resolve_one(
    name: str,
    login: str,
    api_key: str,
    delay: float,
    csv_data: dict[str, str] | None = None,
    csv_only: bool = False,
    api_only: bool = False,
) -> tuple[str, str]:
    """Returns (danbooru_tag_with_spaces, strategy_label) or ('', 'not_found').

    If csv_data is provided (from load_csv()), it is checked first before any
    API call, dramatically reducing network requests for the bulk run.
    """
    normalized = _normalize_db_name(name)
    orig_words = _meaningful_words(normalized)
    orig_series_words = _meaningful_words(_series_suffix(normalized))
    base = _strip_series(normalized)
    base_words = _meaningful_words(base)
    inverted = _invert(base)
    base_inverted = _invert(base) if base != normalized else ""
    series_suffix = _series_suffix(normalized)

    basic_queries: list[tuple[str, str]] = [(_to_query(normalized), "full")]
    if inverted:
        basic_queries.append((_to_query(inverted), "inverted"))
    if base != normalized:
        basic_queries.append((_to_query(base), "base"))
        if base_inverted:
            basic_queries.append((_to_query(base_inverted), "base_inv"))

    # --- CSV pass on direct queries (no network) ---
    if csv_data and not api_only:
        for query, label in basic_queries:
            hit = _csv_lookup(query, csv_data)
            if hit:
                return hit.replace("_", " "), f"csv:{label}"

    if csv_only:
        return "", "not_found"

    series_queries: list[tuple[str, str]] = []
    if base != normalized and series_suffix:
        canonical_series = _resolve_copyright_alias(_to_query(series_suffix), login, api_key, delay)
        canonical_full = f"{_to_query(base)}_({canonical_series})"
        series_queries.append((canonical_full, "series_alias"))
        if base_inverted:
            canonical_inv = f"{_to_query(base_inverted)}_({canonical_series})"
            series_queries.append((canonical_inv, "series_alias_inv"))

    # --- CSV pass on alias-derived queries ---
    if csv_data and not api_only:
        for query, label in series_queries:
            hit = _csv_lookup(query, csv_data)
            if hit:
                return hit.replace("_", " "), f"csv:{label}"

    queries = basic_queries + series_queries

    # --- API pass (post search) ---
    for query, label in queries:
        counter = _char_tags_from_posts(query, login, api_key, delay)
        if not counter:
            continue
        best = _best_match(counter, orig_words)
        if best:
            canonical = _canonicalize_with_csv(best, csv_data)
            if csv_data and not canonical:
                continue
            final_tag = canonical or best
            return final_tag.replace("_", " "), label

    # --- API fallback (tag name search) ---
    for query, label in queries:
        if label in {"base", "base_inv"} and orig_series_words and len(base_words) < 2:
            continue
        candidates = _search_character_tags(query, login, api_key, delay)
        best = _best_tag_candidate(candidates, orig_words, orig_series_words)
        if best:
            canonical = _canonicalize_with_csv(best, csv_data)
            if csv_data and not canonical:
                continue
            final_tag = canonical or best
            return final_tag.replace("_", " "), f"tag_search:{label}"

    return "", "not_found"


def ensure_column(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
    if "danbooru_tag" not in cols:
        conn.execute("ALTER TABLE characters ADD COLUMN danbooru_tag TEXT")
        conn.commit()
        print("  Added column `danbooru_tag` to characters table.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login",   default="", help="Danbooru login (optional but recommended)")
    parser.add_argument("--api-key", default="", help="Danbooru API key")
    parser.add_argument("--csv",     default="", help="Path to Danbooru tag dump CSV (tag_name,category,...) for offline lookup")
    parser.add_argument("--sample",  type=int, default=0, help="Test N rows only (0 = full run)")
    parser.add_argument("--limit",   type=int, default=0, help="Process at most N rows after filters/resume are applied")
    parser.add_argument("--offset",  type=int, default=0, help="Skip the first N rows after filters/resume are applied")
    parser.add_argument("--resume",  action="store_true", help="Skip rows where danbooru_tag already set")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument("--summary-only", action="store_true", help="Suppress per-row output and print only the final summary")
    parser.add_argument("--csv-only", action="store_true", help="Use only direct CSV matches; make no API calls")
    parser.add_argument("--api-only", action="store_true", help="Skip CSV lookup and resolve only via API")
    args = parser.parse_args()

    if args.sample and (args.limit or args.offset):
        parser.error("--sample cannot be combined with --limit/--offset")
    if args.csv_only and args.api_only:
        parser.error("--csv-only and --api-only are mutually exclusive")
    if args.csv_only and not args.csv:
        parser.error("--csv-only requires --csv")
    if args.api_only and not args.csv:
        parser.error("--api-only requires --csv to canonicalize API results to CSV names")

    delay = RATE_LIMIT_DELAY if (args.login and args.api_key) else ANON_DELAY
    auth_mode = "authenticated" if (args.login and args.api_key) else "anonymous"
    print(f"Danbooru mode: {auth_mode}  (delay {delay}s/req)")

    csv_data: dict[str, str] | None = None
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"ERROR: CSV file not found: {csv_path}")
            sys.exit(1)
        print(f"Loading CSV from {csv_path} ...", end=" ", flush=True)
        csv_data = load_csv(csv_path)
        print(f"{len(csv_data):,} character tags loaded.")

    if args.csv_only:
        print("Resolver mode: CSV only")
    elif args.api_only:
        print("Resolver mode: API only")
    else:
        print("Resolver mode: CSV first, API fallback")

    conn = sqlite3.connect(str(DB_PATH))
    if not args.dry_run:
        ensure_column(conn)

    # Build query
    if args.resume:
        rows = conn.execute(
            "SELECT id, name FROM characters WHERE danbooru_tag IS NULL OR danbooru_tag = '' ORDER BY id ASC"
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, name FROM characters ORDER BY id ASC").fetchall()

    if args.sample:
        # Pick a varied sample: spread across the DB
        step = max(1, len(rows) // args.sample)
        rows = rows[::step][: args.sample]
        print(f"Testing {len(rows)} sample characters\n")
    else:
        if args.offset:
            rows = rows[args.offset :]
        if args.limit:
            rows = rows[: args.limit]
        print(f"Processing {len(rows):,} characters\n")

    stats = {"csv:full": 0, "csv:inverted": 0, "csv:base": 0, "csv:base_inv": 0, "csv:series_alias": 0, "full": 0, "inverted": 0, "base": 0, "base_inv": 0, "series_alias": 0, "series_alias_inv": 0, "tag_search:full": 0, "tag_search:inverted": 0, "tag_search:base": 0, "tag_search:base_inv": 0, "not_found": 0}
    updates: list[tuple[str, int]] = []

    if not args.summary_only:
        COL_W = 35
        print(f"{'Name in DB':<{COL_W}} {'Resolved tag':<{COL_W}} Strategy")
        print("-" * 90)

    for char_id, name in rows:
        try:
            resolved, strategy = resolve_one(
                name,
                args.login,
                args.api_key,
                delay,
                csv_data,
                csv_only=args.csv_only,
                api_only=args.api_only,
            )
        except requests.HTTPError as e:
            print(f"  HTTP error for {name!r}: {e}")
            if "429" in str(e):
                print("  Rate limited — waiting 30s...")
                time.sleep(30)
                resolved, strategy = resolve_one(
                    name,
                    args.login,
                    args.api_key,
                    delay,
                    csv_data,
                    csv_only=args.csv_only,
                    api_only=args.api_only,
                )
            else:
                resolved, strategy = "", "error"

        short_strategy = strategy.split("→")[0]
        stats[short_strategy] = stats.get(short_strategy, 0) + 1

        if not args.summary_only:
            changed = resolved and resolved.lower() != name.lower()
            marker = "  *" if changed else "   "
            print(f"{marker}{name:<{COL_W}} {resolved:<{COL_W}} [{strategy}]")

        if resolved and not args.dry_run:
            updates.append((resolved, char_id))

    print("\n--- Summary ---")
    csv_total = sum(v for k, v in stats.items() if k.startswith("csv:"))
    api_total = sum(v for k, v in stats.items() if not k.startswith("csv:") and k != "not_found")
    print(f"  csv hits  : {csv_total:>5,}  (no API call)")
    print(f"  api hits  : {api_total:>5,}")
    print(f"    full      : {stats.get('full', 0):>5,}")
    print(f"    inverted  : {stats.get('inverted', 0):>5,}")
    print(f"    base      : {stats.get('base', 0):>5,}")
    print(f"    base_inv  : {stats.get('base_inv', 0):>5,}")
    print(f"    series    : {stats.get('series_alias', 0):>5,}")
    print(f"    seriesinv : {stats.get('series_alias_inv', 0):>5,}")
    print(f"    tag full  : {stats.get('tag_search:full', 0):>5,}")
    print(f"    tag inv   : {stats.get('tag_search:inverted', 0):>5,}")
    print(f"    tag base  : {stats.get('tag_search:base', 0):>5,}")
    print(f"    tag b_inv : {stats.get('tag_search:base_inv', 0):>5,}")
    print(f"  not_found : {stats.get('not_found', 0):>5,}")
    print(f"  total     : {len(rows):>5,}")

    if args.dry_run:
        print("\n[dry-run] No DB writes.")
        return

    if updates:
        conn.executemany("UPDATE characters SET danbooru_tag = ? WHERE id = ?", updates)
        conn.commit()
        print(f"\n✅ Updated {len(updates):,} rows.")
    conn.close()


if __name__ == "__main__":
    main()
