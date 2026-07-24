#!/usr/bin/env python3
"""Audit e621 character series against an official daily database export.

The audit is deliberately read-only with respect to the character catalogue.
It resolves active aliases and active tag implications offline, then writes:

* a compact, tracked evidence file for unambiguous character-to-copyright links;
* a full generated JSON report; and
* a generated CSV review queue prioritized by the evidence still required.

Source prompts are never parsed beyond their stored SHA-256 digest and are never
rewritten. The evidence file includes that digest so the v2 builder can reject
stale assignments if a source prompt changes later.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEFAULT_CATALOG = DATA_DIR / "catalog" / "characters-v2.db"
DEFAULT_EXPORT_ROOT = DATA_DIR / "generated" / "e621_export"
DEFAULT_EVIDENCE = DATA_DIR / "e621_series_implications.json"
DEFAULT_REPORT = DATA_DIR / "generated" / "e621_series_audit.json"
DEFAULT_REVIEW_CSV = DATA_DIR / "generated" / "e621_series_review.csv"

EVIDENCE_SCHEMA_VERSION = 1
E621_CATEGORY_NAMES = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "species",
    6: "invalid",
    7: "meta",
    8: "lore",
}
REQUIRED_EXPORTS = (
    "tags.csv.gz",
    "tag_aliases.csv.gz",
    "tag_implications.csv.gz",
    "wiki_pages.csv.gz",
)
REVIEW_FIELDS = (
    "priority",
    "audit_status",
    "source_record_id",
    "legacy_id",
    "source_name_raw",
    "source_tag_raw",
    "resolved_tag",
    "tag_category",
    "post_count",
    "wiki_available",
    "current_series_raw",
    "copyright_candidates",
    "selected_copyright",
    "implication_depth",
    "implication_path",
    "catalog_series_match",
    "recommended_next_step",
    "prompt_sha256",
)


class E621AuditError(RuntimeError):
    """Raised when local inputs cannot produce trustworthy audit evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_e621_tag(value: str | None) -> str:
    """Normalize a copied tag for e621 matching without changing source text."""
    text = (value or "").replace("\\(", "(").replace("\\)", ")").strip().casefold()
    return re.sub(r"\s+", "_", text)


def normalize_catalog_text(value: str | None) -> str:
    """Match the catalogue builder's normalized space-separated key."""
    return normalize_e621_tag(value).replace("_", " ")


def _read_gzip_dicts(
    path: Path,
    required_fields: Iterable[str],
) -> Iterable[dict[str, str]]:
    if not path.exists():
        raise E621AuditError(f"Required e621 export not found: {path}")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required_fields).difference(reader.fieldnames or [])
        if missing:
            raise E621AuditError(f"{path.name} is missing columns: {sorted(missing)}")
        yield from reader


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def find_latest_export(export_root: Path) -> Path:
    """Return the latest complete YYYY-MM-DD export directory."""
    if not export_root.exists():
        raise E621AuditError(f"e621 export root not found: {export_root}")
    candidates = sorted(
        path
        for path in export_root.iterdir()
        if path.is_dir() and all((path / name).exists() for name in REQUIRED_EXPORTS)
    )
    if not candidates:
        raise E621AuditError(f"No complete e621 export found under {export_root}")
    return candidates[-1]


class E621ExportIndex:
    """Memory-conscious index over the metadata subset of an e621 export."""

    def __init__(
        self,
        *,
        tags: dict[str, tuple[int, int]],
        aliases: dict[str, str],
        implications: dict[str, set[str]],
        wiki_titles: set[str],
    ) -> None:
        self.tags = tags
        self.aliases = aliases
        self.implications = implications
        self.wiki_titles = wiki_titles

    def resolve_alias(self, tag: str) -> tuple[str, list[str]]:
        current = normalize_e621_tag(tag)
        chain = [current]
        seen: set[str] = set()
        while current in self.aliases:
            if current in seen:
                raise E621AuditError(f"Active e621 alias cycle detected at {current}")
            seen.add(current)
            current = self.aliases[current]
            chain.append(current)
        return current, chain

    @lru_cache(maxsize=None)
    def closure(self, tag: str) -> frozenset[str]:
        resolved, _ = self.resolve_alias(tag)
        seen = {resolved}
        pending = [resolved]
        while pending:
            current = pending.pop()
            for raw_next in self.implications.get(current, set()):
                next_tag, _ = self.resolve_alias(raw_next)
                if next_tag not in seen:
                    seen.add(next_tag)
                    pending.append(next_tag)
        return frozenset(seen)

    def shortest_path(self, start: str, target: str) -> list[str]:
        start, _ = self.resolve_alias(start)
        target, _ = self.resolve_alias(target)
        pending: deque[tuple[str, list[str]]] = deque([(start, [start])])
        seen = {start}
        while pending:
            current, path = pending.popleft()
            if current == target:
                return path
            for raw_next in sorted(self.implications.get(current, set())):
                next_tag, _ = self.resolve_alias(raw_next)
                if next_tag not in seen:
                    seen.add(next_tag)
                    pending.append((next_tag, [*path, next_tag]))
        return []

    def most_specific_copyrights(self, tag: str) -> set[str]:
        """Discard broader copyright ancestors reachable from a nearer copyright."""
        reachable = self.closure(tag)
        copyrights = {
            candidate
            for candidate in reachable
            if self.tags.get(candidate, (-1, 0))[0] == 3
        }
        broader: set[str] = set()
        for candidate in copyrights:
            broader.update((self.closure(candidate) - {candidate}) & copyrights)
        return copyrights - broader


def load_export_index(
    export_dir: Path,
    source_tags: Iterable[str] = (),
) -> E621ExportIndex:
    aliases = {
        normalize_e621_tag(row["antecedent_name"]): normalize_e621_tag(
            row["consequent_name"]
        )
        for row in _read_gzip_dicts(
            export_dir / "tag_aliases.csv.gz",
            {"antecedent_name", "consequent_name", "status"},
        )
        if row["status"] == "active"
    }

    raw_implications: list[tuple[str, str]] = []
    wanted_tags = (
        set(aliases)
        | set(aliases.values())
        | {normalize_e621_tag(tag) for tag in source_tags}
    )
    for row in _read_gzip_dicts(
        export_dir / "tag_implications.csv.gz",
        {"antecedent_name", "consequent_name", "status"},
    ):
        if row["status"] != "active":
            continue
        antecedent = normalize_e621_tag(row["antecedent_name"])
        consequent = normalize_e621_tag(row["consequent_name"])
        raw_implications.append((antecedent, consequent))
        wanted_tags.update((antecedent, consequent))

    tags: dict[str, tuple[int, int]] = {}
    for row in _read_gzip_dicts(
        export_dir / "tags.csv.gz",
        {"name", "category", "post_count"},
    ):
        name = normalize_e621_tag(row["name"])
        category = int(row["category"])
        if name in wanted_tags or category in {3, 4, 5, 6, 7, 8}:
            tags[name] = (category, int(row["post_count"]))

    temporary_index = E621ExportIndex(
        tags=tags,
        aliases=aliases,
        implications={},
        wiki_titles=set(),
    )
    implications: dict[str, set[str]] = defaultdict(set)
    for antecedent, consequent in raw_implications:
        resolved_antecedent, _ = temporary_index.resolve_alias(antecedent)
        resolved_consequent, _ = temporary_index.resolve_alias(consequent)
        if resolved_antecedent != resolved_consequent:
            implications[resolved_antecedent].add(resolved_consequent)

    wiki_titles = {
        normalize_e621_tag(row["title"])
        for row in _read_gzip_dicts(
            export_dir / "wiki_pages.csv.gz",
            {"title"},
        )
    }
    return E621ExportIndex(
        tags=tags,
        aliases=aliases,
        implications=dict(implications),
        wiki_titles=wiki_titles,
    )


def read_e621_records(catalog_path: Path) -> list[dict[str, Any]]:
    if not catalog_path.exists():
        raise E621AuditError(f"Character catalogue not found: {catalog_path}")
    uri = catalog_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id AS source_record_id, legacy_id, source_name_raw,
                   source_tag_raw, match_key, current_series_raw, prompt_sha256,
                   series_id, series_resolution
            FROM source_records
            WHERE source = 'e621'
            ORDER BY id
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise E621AuditError(f"Cannot read v2 source records: {catalog_path}") from exc
    finally:
        conn.close()
    return [dict(row) for row in rows]


def read_catalog_series(catalog_path: Path) -> tuple[set[str], dict[str, set[str]]]:
    uri = catalog_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        source_tags = {
            str(row[0])
            for row in conn.execute("SELECT source_copyright_tag FROM series")
        }
        aliases: dict[str, set[str]] = defaultdict(set)
        for source_tag, alias in conn.execute(
            """
            SELECT s.source_copyright_tag, a.alias
            FROM series s JOIN series_aliases a ON a.series_id = s.id
            """
        ):
            aliases[normalize_e621_tag(alias)].add(str(source_tag))
    finally:
        conn.close()
    return source_tags, dict(aliases)


def _catalog_series_match(
    copyright_tag: str,
    source_tags: set[str],
    aliases: dict[str, set[str]],
) -> tuple[str, str]:
    if copyright_tag in source_tags:
        return copyright_tag, "exact_source_tag"
    matches = aliases.get(normalize_e621_tag(copyright_tag), set())
    if len(matches) == 1:
        return next(iter(matches)), "unique_catalog_alias"
    return copyright_tag, "new_series_definition"


def _review_priority(status: str, post_count: int, wiki_available: bool) -> int:
    base = {
        "invalid_tag_category": 10,
        "alias_collision": 20,
        "multiple_specific_copyrights": 30,
        "wiki_review": 40,
        "post_api": 50,
        "manual_no_posts": 60,
        "already_resolved": 90,
        "evidence_assignment": 100,
    }[status]
    popularity_bonus = min(9, len(str(max(0, post_count))))
    wiki_bonus = 1 if wiki_available and status in {"wiki_review", "post_api"} else 0
    return base - popularity_bonus - wiki_bonus


def audit_catalog(
    catalog_path: Path,
    export_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    records = read_e621_records(catalog_path)
    index = load_export_index(
        export_dir,
        (record["source_tag_raw"] for record in records),
    )
    series_source_tags, series_aliases = read_catalog_series(catalog_path)

    resolved_counts: Counter[str] = Counter()
    resolved_by_record: dict[int, tuple[str, list[str]]] = {}
    for record in records:
        resolved = index.resolve_alias(record["source_tag_raw"])
        resolved_by_record[int(record["source_record_id"])] = resolved
        resolved_counts[resolved[0]] += 1

    assignments: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()

    for record in records:
        source_record_id = int(record["source_record_id"])
        resolved_tag, alias_chain = resolved_by_record[source_record_id]
        category, post_count = index.tags.get(resolved_tag, (-1, 0))
        category_name = E621_CATEGORY_NAMES.get(category, f"unknown:{category}")
        category_counts[category_name] += 1
        wiki_available = resolved_tag in index.wiki_titles
        specific_copyrights = sorted(index.most_specific_copyrights(resolved_tag))
        selected_copyright = ""
        implication_path: list[str] = []
        catalog_series_match = ""
        recommended_next_step = ""

        preserves_prior_evidence = (
            record["series_resolution"] == "e621_export_active_implication"
        )
        if record["series_id"] is not None and not preserves_prior_evidence:
            status = "already_resolved"
            recommended_next_step = "none"
        elif resolved_counts[resolved_tag] > 1:
            status = "alias_collision"
            recommended_next_step = "review identity or variation before assigning series"
        elif category != 4:
            status = "invalid_tag_category"
            recommended_next_step = "remove or reclassify the catalogue record"
        elif post_count <= 0:
            status = "manual_no_posts"
            recommended_next_step = "manual source review; no current e621 posts"
        elif len(specific_copyrights) == 1:
            status = "evidence_assignment"
            selected_copyright = specific_copyrights[0]
            implication_path = index.shortest_path(resolved_tag, selected_copyright)
            series_source_tag, match_type = _catalog_series_match(
                selected_copyright,
                series_source_tags,
                series_aliases,
            )
            catalog_series_match = f"{match_type}:{series_source_tag}"
            recommended_next_step = "apply official active implication"
            assignments.append(
                {
                    "source_record_id": source_record_id,
                    "legacy_id": record["legacy_id"],
                    "match_key": normalize_catalog_text(record["source_tag_raw"]),
                    "source_tag_raw": record["source_tag_raw"],
                    "resolved_tag": resolved_tag,
                    "alias_chain": alias_chain,
                    "character_post_count": post_count,
                    "copyright_tag": selected_copyright,
                    "series_source_tag": series_source_tag,
                    "catalog_match_type": match_type,
                    "implication_path": implication_path,
                    "implication_depth": max(0, len(implication_path) - 1),
                    "current_series_raw": record["current_series_raw"],
                    "prompt_sha256": record["prompt_sha256"],
                    "confidence": 1.0,
                }
            )
        elif len(specific_copyrights) > 1:
            status = "multiple_specific_copyrights"
            recommended_next_step = "review multiple official copyright implications"
        elif wiki_available:
            status = "wiki_review"
            recommended_next_step = "review local e621 wiki before using the posts API"
        else:
            status = "post_api"
            recommended_next_step = "query one categorized e621 post"

        status_counts[status] += 1
        resolution_counts[str(record["series_resolution"])] += 1
        review_rows.append(
            {
                "priority": _review_priority(status, post_count, wiki_available),
                "audit_status": status,
                "source_record_id": source_record_id,
                "legacy_id": record["legacy_id"],
                "source_name_raw": record["source_name_raw"],
                "source_tag_raw": record["source_tag_raw"],
                "resolved_tag": resolved_tag,
                "tag_category": category_name,
                "post_count": post_count,
                "wiki_available": int(wiki_available),
                "current_series_raw": record["current_series_raw"] or "",
                "copyright_candidates": "|".join(specific_copyrights),
                "selected_copyright": selected_copyright,
                "implication_depth": (
                    max(0, len(implication_path) - 1) if implication_path else ""
                ),
                "implication_path": " -> ".join(implication_path),
                "catalog_series_match": catalog_series_match,
                "recommended_next_step": recommended_next_step,
                "prompt_sha256": record["prompt_sha256"],
            }
        )

    assignments.sort(key=lambda row: (row["match_key"], row["source_record_id"]))
    review_rows.sort(
        key=lambda row: (
            int(row["priority"]),
            -int(row["post_count"]),
            str(row["resolved_tag"]),
        )
    )

    export_hashes = {
        name: sha256_file(export_dir / name)
        for name in REQUIRED_EXPORTS
    }
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "provider": "e621_db_export",
        "export_date": export_dir.name,
        "source_files": export_hashes,
        "selection_rule": (
            "Active alias resolves to one current category-4 character tag with "
            "posts, no alias collision, and exactly one most-specific category-3 "
            "copyright reachable through active implications."
        ),
        "assignments": assignments,
    }
    report = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "catalog": str(catalog_path.resolve()),
        "catalog_sha256": sha256_file(catalog_path),
        "export_directory": str(export_dir.resolve()),
        "export_date": export_dir.name,
        "source_files": export_hashes,
        "records": {
            "total": len(records),
            "by_existing_resolution": dict(sorted(resolution_counts.items())),
            "by_official_tag_category": dict(sorted(category_counts.items())),
            "by_audit_status": dict(sorted(status_counts.items())),
        },
        "evidence": {
            "assignments": len(assignments),
            "direct_implications": sum(
                row["implication_depth"] == 1 for row in assignments
            ),
            "transitive_implications": sum(
                row["implication_depth"] > 1 for row in assignments
            ),
            "existing_exact_series": sum(
                row["catalog_match_type"] == "exact_source_tag" for row in assignments
            ),
            "existing_alias_series": sum(
                row["catalog_match_type"] == "unique_catalog_alias" for row in assignments
            ),
            "new_series_definitions": len(
                {
                    row["series_source_tag"]
                    for row in assignments
                    if row["catalog_match_type"] == "new_series_definition"
                }
            ),
        },
        "api_queue": {
            "post_api_without_wiki": status_counts["post_api"],
            "wiki_first_without_implication": status_counts["wiki_review"],
            "manual_without_posts": status_counts["manual_no_posts"],
        },
    }
    return evidence, report, review_rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--export-dir",
        type=Path,
        help="Complete YYYY-MM-DD export directory; defaults to the latest local export.",
    )
    parser.add_argument("--export-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        export_dir = (
            args.export_dir.resolve()
            if args.export_dir is not None
            else find_latest_export(args.export_root.resolve())
        )
        evidence, report, review_rows = audit_catalog(
            args.catalog.resolve(),
            export_dir,
        )
        _write_json_atomic(args.evidence.resolve(), evidence)
        _write_json_atomic(args.report.resolve(), report)
        _write_csv_atomic(args.review_csv.resolve(), review_rows)
    except (E621AuditError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"e621 audit failed: {exc}", file=sys.stderr)
        return 1

    statuses = report["records"]["by_audit_status"]
    print(f"Evidence: {args.evidence.resolve()}")
    print(f"Report: {args.report.resolve()}")
    print(f"Review queue: {args.review_csv.resolve()}")
    print(
        "Official implication assignments: "
        f"{report['evidence']['assignments']:,}"
    )
    print(
        "Remaining evidence queues: "
        f"{statuses.get('wiki_review', 0):,} wiki-first, "
        f"{statuses.get('post_api', 0):,} post API, "
        f"{statuses.get('manual_no_posts', 0):,} without posts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
