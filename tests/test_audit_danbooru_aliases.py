from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.audit_danbooru_aliases import AliasAuditError, audit_aliases


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuditDanbooruAliasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.catalog = self.root / "characters_v2.db"
        self.cache = self.root / "aliases.json"
        self.local_tags = self.root / "danbooru_tags.csv"
        self.output = self.root / "alias_suggestions.db"
        self.report = self.root / "alias_suggestions_report.json"
        self.review_csv = self.root / "alias_review_queue.csv"
        self._create_catalog()
        self._write_cache()
        self._write_local_tags()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_catalog(self) -> None:
        conn = sqlite3.connect(self.catalog)
        try:
            conn.executescript(
                """
                CREATE TABLE exact_identity_groups (
                    id INTEGER PRIMARY KEY,
                    match_key TEXT NOT NULL UNIQUE,
                    source_mask INTEGER NOT NULL
                );
                CREATE TABLE series (
                    id INTEGER PRIMARY KEY,
                    normalized_key TEXT NOT NULL UNIQUE,
                    source_copyright_tag TEXT NOT NULL
                );
                CREATE TABLE source_records (
                    id INTEGER PRIMARY KEY,
                    exact_group_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_name_raw TEXT NOT NULL,
                    series_id INTEGER,
                    current_series_raw TEXT,
                    prompt_raw TEXT NOT NULL
                );
                """
            )
            conn.executemany(
                "INSERT INTO exact_identity_groups(id, match_key, source_mask) VALUES (?, ?, ?)",
                [
                    (1, "yor briar", 5),
                    (2, "old hero", 1),
                    (3, "new hero", 4),
                    (4, "legacy only", 1),
                    (5, "ambiguous", 1),
                ],
            )
            conn.executemany(
                "INSERT INTO series(id, normalized_key, source_copyright_tag) VALUES (?, ?, ?)",
                [
                    (1, "kono subarashii sekai ni shukufuku wo!", "kono_subarashii_sekai_ni_shukufuku_wo!"),
                    (2, "old series", "old_series"),
                    (3, "new series", "new_series"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO source_records
                (id, exact_group_id, source, source_name_raw, series_id,
                 current_series_raw, prompt_raw)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, 1, "danbooru", "Yor Briar", 3, None, "yor \\(briar\\), prompt"),
                    (2, 2, "danbooru", "Old Hero", 2, None, "old hero, prompt"),
                    (3, 3, "anima", "New Hero", 3, None, "new hero, prompt"),
                    (4, 4, "danbooru", "Legacy Only", 2, None, "legacy only, prompt"),
                    (5, 5, "danbooru", "Ambiguous", None, "Original", "ambiguous, prompt"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def _write_cache(self) -> None:
        aliases = [
            (1, 4, "character", "yor_forger", "yor_briar"),
            (2, 4, "character", "old_hero", "new_hero"),
            (3, 4, "character", "legacy_only", "canonical_absent"),
            (4, 4, "character", "ambiguous", "new_hero"),
            (5, 4, "character", "ambiguous", "canonical_absent"),
            (6, 4, "character", "missing_alias", "missing_canonical"),
            (
                7,
                3,
                "series",
                "konosuba",
                "kono_subarashii_sekai_ni_shukufuku_wo!",
            ),
            (8, 3, "series", "old_series", "new_series"),
        ]
        data = {
            "schema_version": 1,
            "provider": "test_fixture",
            "fetched_at": "2026-07-22T00:00:00+00:00",
            "aliases": [
                {
                    "id": alias_id,
                    "category": category,
                    "target_type": target_type,
                    "antecedent_name": antecedent,
                    "consequent_name": consequent,
                    "status": "active",
                }
                for alias_id, category, target_type, antecedent, consequent in aliases
            ],
        }
        self.cache.write_text(json.dumps(data), encoding="utf-8")

    def _write_local_tags(self) -> None:
        with self.local_tags.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["tag", "category", "post_count", "aliases"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "tag": "masterpiece",
                    "category": "0",
                    "post_count": "1",
                    "aliases": "",
                }
            )

    def test_builds_review_only_suggestions_and_preserves_catalog(self) -> None:
        catalog_hash = file_sha256(self.catalog)
        report = audit_aliases(
            self.catalog,
            self.cache,
            self.local_tags,
            self.output,
            self.report,
            self.review_csv,
        )

        self.assertEqual(file_sha256(self.catalog), catalog_hash)
        self.assertTrue(report["inputs"]["catalog_sha256_unchanged"])
        self.assertEqual(report["suggestions"]["automatic_merges_applied"], 0)
        self.assertEqual(report["suggestions"]["total"], 7)
        self.assertEqual(report["review_queue"]["total"], 5)
        self.assertEqual(report["review_queue"]["excluded_safe_search_aliases"], 2)
        self.assertEqual(
            report["suggestions"]["by_suggestion_type"],
            {
                "ambiguous_official_alias": 2,
                "canonicalizes_existing_source": 1,
                "connects_existing_catalog_targets": 2,
                "search_alias_for_existing_target": 2,
            },
        )

        conn = sqlite3.connect(self.output)
        try:
            statuses = conn.execute(
                "SELECT DISTINCT review_status FROM alias_suggestions"
            ).fetchall()
            alias_count = conn.execute("SELECT COUNT(*) FROM alias_records").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(statuses, [("pending",)])
        self.assertEqual(alias_count, 8)
        with self.review_csv.open(encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 5)

    def test_refuses_path_collisions(self) -> None:
        with self.assertRaises(AliasAuditError):
            audit_aliases(
                self.catalog,
                self.cache,
                self.local_tags,
                self.catalog,
                self.report,
                self.review_csv,
            )

    def test_separates_already_integrated_directional_aliases(self) -> None:
        conn = sqlite3.connect(self.catalog)
        try:
            conn.executescript(
                """
                CREATE TABLE character_aliases (
                    normalized_alias TEXT NOT NULL,
                    exact_group_id INTEGER NOT NULL
                );
                CREATE TABLE series_aliases (
                    normalized_alias TEXT NOT NULL,
                    series_id INTEGER NOT NULL
                );
                INSERT INTO character_aliases(normalized_alias, exact_group_id)
                VALUES ('yor forger', 1);
                INSERT INTO series_aliases(normalized_alias, series_id)
                VALUES ('konosuba', 1);
                """
            )
            conn.commit()
        finally:
            conn.close()

        report = audit_aliases(
            self.catalog,
            self.cache,
            self.local_tags,
            self.output,
            self.report,
            self.review_csv,
        )

        self.assertEqual(
            report["integrated_search_aliases"],
            {
                "total": 2,
                "by_target_type": {"character": 1, "series": 1},
                "canonical_direction": "antecedent_to_consequent",
            },
        )
        self.assertEqual(report["suggestions"]["total"], 5)
        self.assertEqual(report["review_queue"]["total"], 5)

    def test_rejects_duplicate_alias_ids(self) -> None:
        data = json.loads(self.cache.read_text(encoding="utf-8"))
        data["aliases"].append(dict(data["aliases"][0]))
        self.cache.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(AliasAuditError):
            audit_aliases(
                self.catalog,
                self.cache,
                self.local_tags,
                self.output,
                self.report,
                self.review_csv,
            )


if __name__ == "__main__":
    unittest.main()
