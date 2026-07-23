#!/usr/bin/env python3
"""Export a deterministic, review-only queue for unresolved series titles.

The staging catalogue and AniDB cache are opened read-only. Decision columns are
left blank so this artifact cannot silently approve title associations.

Usage:
    python scripts/generate_series_title_review.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__:
    from scripts.build_character_catalog_v2 import (
        BUILD_SCHEMA_VERSION,
        DEFAULT_ANIDB_TITLES,
        DEFAULT_OUTPUT,
        open_readonly,
        read_anidb_title_dump,
        sha256_file,
    )
else:
    from build_character_catalog_v2 import (
        BUILD_SCHEMA_VERSION,
        DEFAULT_ANIDB_TITLES,
        DEFAULT_OUTPUT,
        open_readonly,
        read_anidb_title_dump,
        sha256_file,
    )


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_REVIEW_CSV = DATA_DIR / "generated" / "series_title_review.csv"
REVIEW_RESOLUTIONS = (
    "ambiguous_exact_match",
    "below_threshold",
    "alias_only_review",
)
REVIEW_FIELDS = (
    "review_key",
    "resolution",
    "source_copyright_tag",
    "provisional_display_name",
    "title_confidence",
    "source_record_count",
    "danbooru_records",
    "e621_records",
    "anima_records",
    "character_examples",
    "candidate_aids",
    "candidate_urls",
    "candidate_evidence_json",
    "decision_action",
    "selected_aid",
    "accepted_aliases",
    "review_notes",
)


class ReviewQueueError(RuntimeError):
    """Raised when a review queue cannot be generated without mutating inputs."""


def _candidate_evidence(
    matches: list[sqlite3.Row],
    anime_by_aid: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for match in matches:
        try:
            aid = int(match["provider_series_id"])
        except (TypeError, ValueError) as exc:
            raise ReviewQueueError("Series title match contains an invalid AniDB AID") from exc
        titles = anime_by_aid.get(aid)
        if titles is None:
            raise ReviewQueueError(f"AniDB title cache does not contain AID {aid}")
        evidence.append(
            {
                "aid": aid,
                "url": f"https://anidb.net/anime/{aid}",
                "match": {
                    "catalog_alias": match["matched_catalog_alias"],
                    "catalog_alias_type": match["matched_catalog_alias_type"],
                    "provider_title": match["matched_provider_title"],
                    "provider_language": match["matched_provider_language"],
                    "provider_title_type": match["matched_provider_title_type"],
                    "confidence": match["confidence"],
                    "resolution_status": match["resolution_status"],
                },
                "titles": [
                    {
                        "title": title["title"],
                        "language": title["language"],
                        "title_type": title["title_type"],
                    }
                    for title in titles
                    if title["language"] in {"x-jat", "ja", "en"}
                ],
            }
        )
    return evidence


def generate_review_queue(
    catalog_path: Path,
    anidb_titles_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Generate the CSV without changing either source artifact."""
    catalog_path = catalog_path.resolve()
    anidb_titles_path = anidb_titles_path.resolve()
    output_path = output_path.resolve()
    if not catalog_path.exists():
        raise ReviewQueueError(f"Staging catalogue not found: {catalog_path}")
    if not anidb_titles_path.exists():
        raise ReviewQueueError(f"AniDB title dump not found: {anidb_titles_path}")
    if output_path in {catalog_path, anidb_titles_path}:
        raise ReviewQueueError("Refusing to overwrite a review-queue input")

    catalog_sha256_before = sha256_file(catalog_path)
    anidb_sha256_before = sha256_file(anidb_titles_path)
    anidb_titles = read_anidb_title_dump(anidb_titles_path)
    if anidb_titles is None:
        raise ReviewQueueError("AniDB title dump is required for the review queue")

    conn = open_readonly(catalog_path)
    try:
        metadata = conn.execute(
            "SELECT value FROM build_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if metadata is None or int(metadata[0]) != BUILD_SCHEMA_VERSION:
            raise ReviewQueueError(
                f"Review queue requires catalogue schema {BUILD_SCHEMA_VERSION}"
            )

        placeholders = ",".join("?" for _ in REVIEW_RESOLUTIONS)
        series_rows = conn.execute(
            f"""
            SELECT id, source_copyright_tag, provisional_display_name,
                   title_resolution, title_confidence
            FROM series
            WHERE title_resolution IN ({placeholders})
            ORDER BY source_copyright_tag
            """,
            REVIEW_RESOLUTIONS,
        ).fetchall()
        output_rows: list[dict[str, Any]] = []
        resolution_counts: Counter[str] = Counter()

        for series in series_rows:
            series_id = int(series["id"])
            source_counts = defaultdict(int)
            for source_row in conn.execute(
                """
                SELECT source, COUNT(*) AS record_count
                FROM source_records WHERE series_id = ?
                GROUP BY source ORDER BY source
                """,
                (series_id,),
            ).fetchall():
                source_counts[str(source_row["source"])] = int(
                    source_row["record_count"]
                )
            character_examples = [
                str(row["source_name_raw"])
                for row in conn.execute(
                    """
                    SELECT source_name_raw, MAX(COALESCE(reference_count, 0)) AS weight
                    FROM source_records WHERE series_id = ?
                    GROUP BY source_name_raw
                    ORDER BY weight DESC, source_name_raw
                    LIMIT 8
                    """,
                    (series_id,),
                ).fetchall()
            ]
            matches = conn.execute(
                """
                SELECT provider_series_id, matched_catalog_alias,
                       matched_catalog_alias_type, matched_provider_title,
                       matched_provider_language, matched_provider_title_type,
                       confidence, resolution_status
                FROM series_title_matches
                WHERE series_id = ?
                ORDER BY CAST(provider_series_id AS INTEGER), provider_series_id
                """,
                (series_id,),
            ).fetchall()
            if not matches:
                raise ReviewQueueError(
                    f"Review series {series['source_copyright_tag']} has no candidates"
                )
            evidence = _candidate_evidence(
                matches,
                anidb_titles["anime_by_aid"],
            )
            aids = [str(item["aid"]) for item in evidence]
            resolution = str(series["title_resolution"])
            resolution_counts[resolution] += 1
            output_rows.append(
                {
                    "review_key": (
                        f"series-title:{series['source_copyright_tag']}"
                    ),
                    "resolution": resolution,
                    "source_copyright_tag": series["source_copyright_tag"],
                    "provisional_display_name": series[
                        "provisional_display_name"
                    ],
                    "title_confidence": series["title_confidence"],
                    "source_record_count": sum(source_counts.values()),
                    "danbooru_records": source_counts["danbooru"],
                    "e621_records": source_counts["e621"],
                    "anima_records": source_counts["anima"],
                    "character_examples": " | ".join(character_examples),
                    "candidate_aids": " | ".join(aids),
                    "candidate_urls": " | ".join(
                        item["url"] for item in evidence
                    ),
                    "candidate_evidence_json": json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "decision_action": "",
                    "selected_aid": "",
                    "accepted_aliases": "",
                    "review_notes": "",
                }
            )
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()
    try:
        with temp_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            writer.writerows(output_rows)
        os.replace(temp_output, output_path)
    except Exception:
        if temp_output.exists():
            temp_output.unlink()
        raise

    catalog_sha256_after = sha256_file(catalog_path)
    anidb_sha256_after = sha256_file(anidb_titles_path)
    if catalog_sha256_after != catalog_sha256_before:
        raise ReviewQueueError("Staging catalogue changed while exporting review rows")
    if anidb_sha256_after != anidb_sha256_before:
        raise ReviewQueueError("AniDB title dump changed while exporting review rows")

    return {
        "output": str(output_path),
        "rows": len(output_rows),
        "by_resolution": dict(sorted(resolution_counts.items())),
        "catalog_sha256": catalog_sha256_after,
        "anidb_titles_sha256": anidb_sha256_after,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--anidb-titles", type=Path, default=DEFAULT_ANIDB_TITLES)
    parser.add_argument("--output", type=Path, default=DEFAULT_REVIEW_CSV)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = generate_review_queue(
            args.catalog,
            args.anidb_titles,
            args.output,
        )
    except (ReviewQueueError, OSError, sqlite3.Error) as exc:
        print(f"Series-title review export blocked: {exc}", file=sys.stderr)
        return 1

    print(f"Review queue: {report['output']}")
    print(f"Rows: {report['rows']:,} {report['by_resolution']}")
    print("Input mutations: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
