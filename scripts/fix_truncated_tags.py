"""
fix_truncated_tags.py — Fix truncated tags in data/characters.db.

Two cases:
  1. Tags ending with ',' → strip trailing comma (tag list was cut after a complete tag)
  2. Last tag not in Danbooru dictionary → complete via prefix match (tag was cut mid-word)
     - Partial >= 4 chars: complete with highest-count matching tag
     - Partial <  4 chars: remove (too ambiguous to guess reliably)

Usage:
    python scripts/fix_truncated_tags.py --csv path/to/danbooru_tags.csv
    python scripts/fix_truncated_tags.py --csv path/to/danbooru_tags.csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "characters.db"
MIN_PREFIX_LEN     = 3     # minimum chars to attempt prefix lookup
MIN_KEEP_LEN       = 3     # tags >= this many chars with no match are kept as-is
MIN_COMPLETE_COUNT = 500   # minimum post count for a completion to be trusted


def load_tags(csv_path: str) -> tuple[set[str], dict[str, int], dict[str, list[tuple[int, str]]]]:
    """Load tag dict and prefix map from Danbooru CSV.

    CSV columns: tag_name, category, count, aliases
    Tags are normalized: underscore → space, lowercase.
    """
    tag_count: dict[str, int] = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            name = row[0].strip().replace("_", " ").lower()
            count = int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 0
            tag_count[name] = count

    # prefix_map[prefix] = sorted list of (count, full_tag) descending
    prefix_map: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for tag, cnt in tag_count.items():
        for end in range(MIN_PREFIX_LEN, len(tag)):
            prefix_map[tag[:end]].append((cnt, tag))

    # Sort each bucket by count descending
    for key in prefix_map:
        prefix_map[key].sort(reverse=True)

    return set(tag_count.keys()), tag_count, prefix_map


def best_completion(partial: str, prefix_map: dict, tag_count: dict) -> str | None:
    """Return the best full tag for a partial string, or None if not confident.

    Strategy:
      1. Filter candidates with post count < MIN_COMPLETE_COUNT (too obscure to trust).
      2. Split remaining into word_boundary (next char is space/'(') and mid_word.
      3. Prefer word_boundary to avoid extending complete words incorrectly.
      4. Falls back to mid_word if no word_boundary candidates survive the filter.
    """
    if len(partial) < MIN_PREFIX_LEN:
        return None
    candidates = prefix_map.get(partial, [])
    if not candidates:
        return None

    word_boundary: list[tuple[int, str]] = []
    mid_word: list[tuple[int, str]] = []

    for cnt, tag in candidates:
        if tag_count.get(tag, 0) < MIN_COMPLETE_COUNT:
            continue  # skip obscure tags — likely wrong completion
        next_char = tag[len(partial)] if len(tag) > len(partial) else ""
        if next_char in (" ", "(", ")"):
            word_boundary.append((cnt, tag))
        else:
            mid_word.append((cnt, tag))

    # Prefer word_boundary (less ambiguous), fall back to mid_word
    preferred = word_boundary if word_boundary else mid_word
    if not preferred:
        return None
    return preferred[0][1]  # already sorted by count desc


def fix_tags(tags: str, valid_tags: set, prefix_map: dict, tag_count: dict) -> tuple[str, str]:
    """Fix a single tags string. Returns (fixed_tags, action)."""
    stripped = tags.rstrip()

    # Case 1: ends with comma → cut after complete tag, just strip comma
    if stripped.endswith(","):
        return stripped.rstrip(",").rstrip(), "strip_comma"

    # Case 2: check if last tag is valid
    parts = [p.strip() for p in stripped.split(",")]
    last = parts[-1].lower()

    if last in valid_tags:
        return tags, "ok"

    # Last tag is not valid → try to complete it
    completion = best_completion(last, prefix_map, tag_count)
    if completion:
        parts[-1] = completion
        return ", ".join(parts), f"completed:{last!r}->{completion!r}"
    else:
        # No completion found:
        # - Exists anywhere in valid_tags (even rare) → keep as-is
        # - Short fragments (< MIN_KEEP_LEN chars) that don't exist → remove
        # - Longer strings not in dict → keep as-is (likely valid but uncommon)
        if last in valid_tags or len(last) >= MIN_KEEP_LEN:
            return tags, "ok"
        fixed = ", ".join(parts[:-1])
        return fixed, f"removed:{last!r}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to danbooru tags CSV")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing to DB")
    args = parser.parse_args()

    print("Loading tags CSV...")
    valid_tags, tag_count, prefix_map = load_tags(args.csv)
    print(f"  {len(valid_tags):,} valid tags loaded")

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT id, name, tags FROM characters").fetchall()
    print(f"  {len(rows):,} characters in DB")

    stats = {"ok": 0, "strip_comma": 0, "completed": 0, "removed": 0}
    updates: list[tuple[str, int]] = []

    for char_id, name, tags in rows:
        if not tags:
            stats["ok"] += 1
            continue
        fixed, action = fix_tags(tags, valid_tags, prefix_map, tag_count)
        if action == "ok":
            stats["ok"] += 1
        elif action == "strip_comma":
            stats["strip_comma"] += 1
            updates.append((fixed, char_id))
        elif action.startswith("completed"):
            stats["completed"] += 1
            updates.append((fixed, char_id))
        elif action.startswith("removed"):
            stats["removed"] += 1
            updates.append((fixed, char_id))

    print(f"\nResults:")
    print(f"  Already OK:              {stats['ok']:>6,}")
    print(f"  Trailing comma stripped: {stats['strip_comma']:>6,}")
    print(f"  Last tag completed:      {stats['completed']:>6,}")
    print(f"  Last tag removed:        {stats['removed']:>6,}")
    print(f"  Total updates:           {len(updates):>6,}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        # Show sample completions
        print("\nSample completions (first 20 changes):")
        done = 0
        for char_id, name, tags in rows:
            if not tags:
                continue
            fixed, action = fix_tags(tags, valid_tags, prefix_map, tag_count)
            if action != "ok" and done < 20:
                print(f"  {name}")
                print(f"    action : {action}")
                print(f"    before : ...{tags[-80:]}")
                print(f"    after  : ...{fixed[-80:]}")
                done += 1
        return

    print("\nApplying updates...")
    conn.executemany("UPDATE characters SET tags = ? WHERE id = ?", updates)
    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
