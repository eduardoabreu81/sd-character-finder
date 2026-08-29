#!/usr/bin/env python3
"""Cache official Danbooru aliases and produce offline catalogue suggestions.

The auditor is deliberately read-only with respect to ``characters_v2.db``.
Official aliases become review evidence in a separate SQLite database and CSV;
they never merge identities, change exclusivity, or rewrite provider prompts.

Usage:
    python scripts/audit_danbooru_aliases.py --fetch
    python scripts/audit_danbooru_aliases.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_character_catalog_v2 import normalize_text, sha256_file  # noqa: E402


DATA_DIR = REPO_ROOT / "data"
GENERATED_DIR = DATA_DIR / "generated"
DEFAULT_CATALOG = GENERATED_DIR / "characters_v2.db"
DEFAULT_LOCAL_TAGS = DATA_DIR / "danbooru_tags.csv"
DEFAULT_CACHE = GENERATED_DIR / "danbooru_tag_aliases.json"
DEFAULT_OUTPUT = GENERATED_DIR / "alias_suggestions.db"
DEFAULT_REPORT = GENERATED_DIR / "alias_suggestions_report.json"
DEFAULT_REVIEW_CSV = GENERATED_DIR / "alias_review_queue.csv"

DANBOORU_API = "https://danbooru.donmai.us"
CACHE_SCHEMA_VERSION = 1
AUDIT_SCHEMA_VERSION = 1
ALIAS_CATEGORIES = {3: "series", 4: "character"}


class AliasAuditError(RuntimeError):
    """Raised when alias inputs cannot produce a trustworthy offline audit."""


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def fetch_alias_cache(
    cache_path: Path,
    rate_limit: float = 1.0,
    login: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """Fetch active character/copyright aliases in cursor-paginated bulk pages."""
    try:
        import requests
    except ImportError as exc:
        raise AliasAuditError("The requests package is required for --fetch") from exc

    if rate_limit < 0:
        raise AliasAuditError("Rate limit must be zero or greater")
    if bool(login) != bool(api_key):
        raise AliasAuditError(
            "DANBOORU_LOGIN and DANBOORU_API_KEY must either both be set or both be absent"
        )

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "sd-character-finder-alias-audit/1.0 (offline catalogue builder)"}
    )
    aliases_by_id: dict[int, dict[str, Any]] = {}
    page_counts: dict[str, int] = {}

    for category, target_type in sorted(ALIAS_CATEGORIES.items()):
        cursor: int | None = None
        page_count = 0
        while True:
            params: dict[str, Any] = {
                "search[status]": "active",
                "search[antecedent_tag][category]": category,
                "limit": 1000,
                "only": "id,antecedent_name,consequent_name",
            }
            if cursor is not None:
                params["page"] = f"b{cursor}"
            if login and api_key:
                params["login"] = login
                params["api_key"] = api_key

            response = session.get(
                f"{DANBOORU_API}/tag_aliases.json",
                params=params,
                timeout=30,
            )
            if response.status_code == 429:
                retry_after = max(float(response.headers.get("Retry-After", "5")), 1.0)
                print(f"Rate limited; retrying {target_type} aliases in {retry_after:.1f}s")
                time.sleep(retry_after)
                continue
            try:
                response.raise_for_status()
                rows = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise AliasAuditError(
                    f"Danbooru alias request failed for category {category}"
                ) from exc
            if not isinstance(rows, list):
                raise AliasAuditError(f"Unexpected Danbooru response for category {category}")

            page_count += 1
            valid_ids: list[int] = []
            for row in rows:
                if not isinstance(row, dict):
                    raise AliasAuditError("Danbooru returned a non-object alias row")
                try:
                    alias_id = int(row["id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise AliasAuditError("Danbooru returned an alias without a valid ID") from exc
                antecedent = str(row.get("antecedent_name") or "").strip()
                consequent = str(row.get("consequent_name") or "").strip()
                if not antecedent or not consequent:
                    raise AliasAuditError(f"Danbooru alias {alias_id} has an empty endpoint")
                alias = {
                    "id": alias_id,
                    "category": category,
                    "target_type": target_type,
                    "antecedent_name": antecedent,
                    "consequent_name": consequent,
                    "status": "active",
                }
                existing = aliases_by_id.get(alias_id)
                if existing is not None and existing != alias:
                    raise AliasAuditError(f"Conflicting duplicate Danbooru alias ID {alias_id}")
                aliases_by_id[alias_id] = alias
                valid_ids.append(alias_id)

            print(
                f"Fetched {target_type} alias page {page_count}: "
                f"{len(rows):,} rows ({len(aliases_by_id):,} total unique)"
            )
            if len(rows) < 1000:
                break
            next_cursor = min(valid_ids)
            if cursor is not None and next_cursor >= cursor:
                raise AliasAuditError("Danbooru alias cursor did not advance")
            cursor = next_cursor
            if rate_limit:
                time.sleep(rate_limit)

        page_counts[target_type] = page_count

    cache = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "provider": "danbooru_public_api",
        "endpoint": f"{DANBOORU_API}/tag_aliases.json",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "authenticated": bool(login and api_key),
        "filters": {
            "status": "active",
            "categories": {str(key): value for key, value in ALIAS_CATEGORIES.items()},
        },
        "page_counts": page_counts,
        "aliases": sorted(
            aliases_by_id.values(),
            key=lambda row: (row["category"], -row["id"]),
        ),
    }
    atomic_write_json(cache_path, cache)
    return cache


def load_alias_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AliasAuditError(f"Alias cache not found: {path}; run with --fetch first")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AliasAuditError(f"Cannot read alias cache: {path}") from exc
    if not isinstance(cache, dict) or cache.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise AliasAuditError(f"Unsupported alias cache schema in {path}")
    aliases = cache.get("aliases")
    if not isinstance(aliases, list):
        raise AliasAuditError("Alias cache field 'aliases' must be a list")

    seen_ids: set[int] = set()
    for row in aliases:
        if not isinstance(row, dict):
            raise AliasAuditError("Alias cache contains a non-object row")
        try:
            alias_id = int(row["id"])
            category = int(row["category"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AliasAuditError("Alias cache row has invalid ID or category") from exc
        if alias_id in seen_ids:
            raise AliasAuditError(f"Alias cache contains duplicate ID {alias_id}")
        if category not in ALIAS_CATEGORIES:
            raise AliasAuditError(f"Alias {alias_id} uses unsupported category {category}")
        if row.get("target_type") != ALIAS_CATEGORIES[category]:
            raise AliasAuditError(f"Alias {alias_id} has a mismatched target type")
        if row.get("status") != "active":
            raise AliasAuditError(f"Alias {alias_id} is not active")
        if not str(row.get("antecedent_name") or "").strip():
            raise AliasAuditError(f"Alias {alias_id} has an empty antecedent")
        if not str(row.get("consequent_name") or "").strip():
            raise AliasAuditError(f"Alias {alias_id} has an empty consequent")
        seen_ids.add(alias_id)
    return cache


def audit_local_tag_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AliasAuditError(f"Local Danbooru tag CSV not found: {path}")
    counts: Counter[str] = Counter()
    rows_with_aliases = 0
    relevant_alias_rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            category = str(row.get("category") or "").strip()
            aliases = str(row.get("aliases") or row.get("tag_aliases") or "").strip()
            counts[category] += 1
            if aliases:
                rows_with_aliases += 1
                if category in {"3", "4"}:
                    relevant_alias_rows += 1
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": sum(counts.values()),
        "rows_by_category": dict(sorted(counts.items())),
        "rows_with_aliases": rows_with_aliases,
        "character_or_series_alias_rows": relevant_alias_rows,
        "usable_for_this_audit": relevant_alias_rows > 0,
    }


AUDIT_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE audit_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE alias_records (
    api_alias_id          INTEGER PRIMARY KEY,
    category              INTEGER NOT NULL CHECK (category IN (3, 4)),
    target_type           TEXT NOT NULL CHECK (target_type IN ('character', 'series')),
    antecedent_raw        TEXT NOT NULL,
    consequent_raw        TEXT NOT NULL,
    antecedent_normalized TEXT NOT NULL,
    consequent_normalized TEXT NOT NULL,
    status                TEXT NOT NULL,
    provider              TEXT NOT NULL
);

CREATE INDEX idx_alias_records_antecedent ON alias_records(antecedent_normalized);
CREATE INDEX idx_alias_records_consequent ON alias_records(consequent_normalized);

CREATE TABLE alias_suggestions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    api_alias_id          INTEGER NOT NULL REFERENCES alias_records(api_alias_id),
    target_type           TEXT NOT NULL CHECK (target_type IN ('character', 'series')),
    suggestion_type       TEXT NOT NULL,
    antecedent_group_id   INTEGER,
    consequent_group_id   INTEGER,
    antecedent_series_id  INTEGER,
    consequent_series_id  INTEGER,
    confidence            REAL NOT NULL,
    review_status         TEXT NOT NULL DEFAULT 'pending',
    evidence              TEXT NOT NULL,
    UNIQUE(api_alias_id, target_type)
);

CREATE INDEX idx_alias_suggestions_type ON alias_suggestions(suggestion_type);
CREATE INDEX idx_alias_suggestions_review ON alias_suggestions(review_status);
"""


def classify_suggestion(
    antecedent_id: int | None,
    consequent_id: int | None,
    ambiguous: bool,
) -> tuple[str, float]:
    if ambiguous:
        return "ambiguous_official_alias", 0.0
    if antecedent_id is not None and consequent_id is not None:
        if antecedent_id == consequent_id:
            return "already_same_catalog_target", 1.0
        return "connects_existing_catalog_targets", 0.99
    if consequent_id is not None:
        return "search_alias_for_existing_target", 1.0
    return "canonicalizes_existing_source", 0.99


def build_group_details(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    details: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: {"sources": set(), "series": set(), "names": set()}
    )
    rows = conn.execute(
        """
        SELECT r.exact_group_id, r.source, r.source_name_raw,
               COALESCE(s.source_copyright_tag, r.current_series_raw) AS series_tag
        FROM source_records r LEFT JOIN series s ON s.id = r.series_id
        """
    ).fetchall()
    for row in rows:
        item = details[int(row["exact_group_id"])]
        item["sources"].add(row["source"])
        item["names"].add(row["source_name_raw"])
        if row["series_tag"]:
            item["series"].add(row["series_tag"])
    return {
        group_id: {
            key: " | ".join(sorted(values))
            for key, values in item.items()
        }
        for group_id, item in details.items()
    }


def audit_aliases(
    catalog_path: Path,
    cache_path: Path,
    local_tags_path: Path,
    output_path: Path,
    report_path: Path,
    review_csv_path: Path,
) -> dict[str, Any]:
    paths = [
        catalog_path.resolve(),
        cache_path.resolve(),
        local_tags_path.resolve(),
        output_path.resolve(),
        report_path.resolve(),
        review_csv_path.resolve(),
    ]
    if len(set(paths)) != len(paths):
        raise AliasAuditError("Alias audit inputs and outputs must use distinct paths")
    catalog_path, cache_path, local_tags_path, output_path, report_path, review_csv_path = paths
    if not catalog_path.exists():
        raise AliasAuditError(f"Staging catalogue not found: {catalog_path}")

    cache = load_alias_cache(cache_path)
    local_csv_report = audit_local_tag_csv(local_tags_path)
    catalog_hash_before = sha256_file(catalog_path)

    catalog = sqlite3.connect(catalog_path.resolve().as_uri() + "?mode=ro", uri=True)
    catalog.row_factory = sqlite3.Row
    try:
        group_rows = catalog.execute(
            "SELECT id, match_key, source_mask FROM exact_identity_groups"
        ).fetchall()
        series_rows = catalog.execute(
            "SELECT id, normalized_key, source_copyright_tag FROM series"
        ).fetchall()
        group_details = build_group_details(catalog)
        table_names = {
            row[0]
            for row in catalog.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        existing_character_aliases: dict[str, set[int]] = defaultdict(set)
        if "character_aliases" in table_names:
            for row in catalog.execute(
                "SELECT normalized_alias, exact_group_id FROM character_aliases"
            ).fetchall():
                existing_character_aliases[row["normalized_alias"]].add(
                    int(row["exact_group_id"])
                )
        existing_series_aliases: dict[str, set[int]] = defaultdict(set)
        if "series_aliases" in table_names:
            for row in catalog.execute(
                "SELECT normalized_alias, series_id FROM series_aliases"
            ).fetchall():
                existing_series_aliases[row["normalized_alias"]].add(int(row["series_id"]))
    finally:
        catalog.close()

    groups_by_key = {row["match_key"]: int(row["id"]) for row in group_rows}
    series_by_key = {row["normalized_key"]: int(row["id"]) for row in series_rows}
    series_keys = {int(row["id"]): row["source_copyright_tag"] for row in series_rows}

    aliases = cache["aliases"]
    consequents_by_antecedent: dict[tuple[int, str], set[str]] = defaultdict(set)
    for row in aliases:
        category = int(row["category"])
        antecedent = normalize_text(str(row["antecedent_name"]))
        consequent = normalize_text(str(row["consequent_name"]))
        consequents_by_antecedent[(category, antecedent)].add(consequent)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    review_csv_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temp_review_csv = review_csv_path.with_suffix(review_csv_path.suffix + ".tmp")
    for temp_path in (temp_output, temp_report, temp_review_csv):
        if temp_path.exists():
            temp_path.unlink()

    suggestion_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    integrated_counts: Counter[str] = Counter()
    suggestion_rows: list[dict[str, Any]] = []
    conn = sqlite3.connect(temp_output)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(AUDIT_SCHEMA)
        metadata = {
            "schema_version": str(AUDIT_SCHEMA_VERSION),
            "catalog_sha256": catalog_hash_before,
            "alias_cache_sha256": sha256_file(cache_path),
            "local_tag_csv_sha256": local_csv_report["sha256"],
            "merge_policy": "suggestions_only_no_automatic_merges",
        }
        conn.executemany(
            "INSERT INTO audit_metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )

        for row in aliases:
            alias_id = int(row["id"])
            category = int(row["category"])
            target_type = ALIAS_CATEGORIES[category]
            antecedent_raw = str(row["antecedent_name"])
            consequent_raw = str(row["consequent_name"])
            antecedent = normalize_text(antecedent_raw)
            consequent = normalize_text(consequent_raw)
            conn.execute(
                """
                INSERT INTO alias_records
                (api_alias_id, category, target_type, antecedent_raw, consequent_raw,
                 antecedent_normalized, consequent_normalized, status, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'danbooru_public_api')
                """,
                (
                    alias_id,
                    category,
                    target_type,
                    antecedent_raw,
                    consequent_raw,
                    antecedent,
                    consequent,
                ),
            )

            if target_type == "character":
                antecedent_id = groups_by_key.get(antecedent)
                consequent_id = groups_by_key.get(consequent)
                antecedent_series_id = None
                consequent_series_id = None
            else:
                antecedent_id = series_by_key.get(antecedent)
                consequent_id = series_by_key.get(consequent)
                antecedent_series_id = antecedent_id
                consequent_series_id = consequent_id

            if antecedent_id is None and consequent_id is None:
                continue
            ambiguous = len(consequents_by_antecedent[(category, antecedent)]) > 1
            existing_alias_targets = (
                existing_character_aliases.get(antecedent, set())
                if target_type == "character"
                else existing_series_aliases.get(antecedent, set())
            )
            if (
                not ambiguous
                and antecedent_id is None
                and consequent_id is not None
                and existing_alias_targets == {consequent_id}
            ):
                integrated_counts[target_type] += 1
                continue
            if (
                antecedent_id is None
                and existing_alias_targets
                and consequent_id not in existing_alias_targets
            ):
                suggestion_type, confidence = "catalog_search_alias_target_conflict", 0.0
            else:
                suggestion_type, confidence = classify_suggestion(
                    antecedent_id,
                    consequent_id,
                    ambiguous,
                )
            if target_type == "character":
                antecedent_group_id = antecedent_id
                consequent_group_id = consequent_id
                antecedent_series_id = None
                consequent_series_id = None
            else:
                antecedent_group_id = None
                consequent_group_id = None

            evidence = (
                "active official Danbooru tag alias; review evidence only; "
                "no catalogue merge or prompt mutation applied"
            )
            conn.execute(
                """
                INSERT INTO alias_suggestions
                (api_alias_id, target_type, suggestion_type,
                 antecedent_group_id, consequent_group_id,
                 antecedent_series_id, consequent_series_id,
                 confidence, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alias_id,
                    target_type,
                    suggestion_type,
                    antecedent_group_id,
                    consequent_group_id,
                    antecedent_series_id,
                    consequent_series_id,
                    confidence,
                    evidence,
                ),
            )
            suggestion_counts[suggestion_type] += 1
            target_counts[target_type] += 1

            review_row: dict[str, Any] = {
                "api_alias_id": alias_id,
                "target_type": target_type,
                "suggestion_type": suggestion_type,
                "confidence": confidence,
                "antecedent_raw": antecedent_raw,
                "consequent_raw": consequent_raw,
                "antecedent_normalized": antecedent,
                "consequent_normalized": consequent,
                "antecedent_catalog_id": antecedent_id or "",
                "consequent_catalog_id": consequent_id or "",
                "antecedent_sources": "",
                "consequent_sources": "",
                "antecedent_series": "",
                "consequent_series": "",
            }
            if target_type == "character":
                if antecedent_id is not None:
                    review_row["antecedent_sources"] = group_details[antecedent_id]["sources"]
                    review_row["antecedent_series"] = group_details[antecedent_id]["series"]
                if consequent_id is not None:
                    review_row["consequent_sources"] = group_details[consequent_id]["sources"]
                    review_row["consequent_series"] = group_details[consequent_id]["series"]
            else:
                if antecedent_id is not None:
                    review_row["antecedent_series"] = series_keys[antecedent_id]
                if consequent_id is not None:
                    review_row["consequent_series"] = series_keys[consequent_id]
            suggestion_rows.append(review_row)

        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    except Exception:
        conn.close()
        for temp_path in (temp_output, temp_report, temp_review_csv):
            if temp_path.exists():
                temp_path.unlink()
        raise
    else:
        conn.close()

    fieldnames = [
        "api_alias_id",
        "target_type",
        "suggestion_type",
        "confidence",
        "antecedent_raw",
        "consequent_raw",
        "antecedent_normalized",
        "consequent_normalized",
        "antecedent_catalog_id",
        "consequent_catalog_id",
        "antecedent_sources",
        "consequent_sources",
        "antecedent_series",
        "consequent_series",
    ]
    review_types = {
        "ambiguous_official_alias",
        "catalog_search_alias_target_conflict",
        "canonicalizes_existing_source",
        "connects_existing_catalog_targets",
    }
    review_rows = [
        row for row in suggestion_rows if row["suggestion_type"] in review_types
    ]
    with temp_review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            sorted(
                review_rows,
                key=lambda row: (
                    row["target_type"],
                    row["suggestion_type"],
                    row["antecedent_normalized"],
                    row["api_alias_id"],
                ),
            )
        )

    catalog_hash_after = sha256_file(catalog_path)
    if catalog_hash_after != catalog_hash_before:
        raise AliasAuditError("Staging catalogue changed during the read-only alias audit")
    report = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "policy": "suggestions_only_no_automatic_merges",
        "inputs": {
            "catalog": str(catalog_path),
            "catalog_sha256": catalog_hash_before,
            "catalog_sha256_unchanged": True,
            "alias_cache": str(cache_path),
            "alias_cache_sha256": sha256_file(cache_path),
            "alias_cache_provider": cache.get("provider"),
            "alias_cache_fetched_at": cache.get("fetched_at"),
            "local_tag_csv": local_csv_report,
        },
        "outputs": {
            "database": str(output_path),
            "review_csv": str(review_csv_path),
            "report": str(report_path),
        },
        "alias_records": {
            "total": len(aliases),
            "by_target_type": dict(
                sorted(Counter(str(row["target_type"]) for row in aliases).items())
            ),
        },
        "suggestions": {
            "total": len(suggestion_rows),
            "by_target_type": dict(sorted(target_counts.items())),
            "by_suggestion_type": dict(sorted(suggestion_counts.items())),
            "automatic_merges_applied": 0,
        },
        "integrated_search_aliases": {
            "total": sum(integrated_counts.values()),
            "by_target_type": dict(sorted(integrated_counts.items())),
            "canonical_direction": "antecedent_to_consequent",
        },
        "review_queue": {
            "total": len(review_rows),
            "excluded_safe_search_aliases": len(suggestion_rows) - len(review_rows),
            "policy": "canonicalization, cross-target, and ambiguous suggestions only",
        },
        "validation": {
            "sqlite_integrity": integrity,
            "foreign_key_errors": foreign_key_errors,
        },
    }
    temp_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_output, output_path)
    os.replace(temp_review_csv, review_csv_path)
    os.replace(temp_report, report_path)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--local-tags", type=Path, default=DEFAULT_LOCAL_TAGS)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--rate-limit", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.fetch:
            fetch_alias_cache(
                args.cache.resolve(),
                rate_limit=args.rate_limit,
                login=os.environ.get("DANBOORU_LOGIN", "").strip(),
                api_key=os.environ.get("DANBOORU_API_KEY", "").strip(),
            )
        report = audit_aliases(
            catalog_path=args.catalog,
            cache_path=args.cache,
            local_tags_path=args.local_tags,
            output_path=args.output,
            report_path=args.report,
            review_csv_path=args.review_csv,
        )
    except AliasAuditError as exc:
        print(f"Alias audit blocked: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Alias audit failed: {exc}", file=sys.stderr)
        return 1

    print(f"Alias cache: {report['inputs']['alias_cache']}")
    print(f"Suggestion DB: {report['outputs']['database']}")
    print(f"Review queue: {report['outputs']['review_csv']}")
    print(
        f"Suggestions: {report['suggestions']['total']:,}; "
        "automatic merges applied: 0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
