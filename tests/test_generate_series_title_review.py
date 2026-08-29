from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_character_catalog_v2 import BUILD_SCHEMA_VERSION
from scripts.generate_series_title_review import (
    ReviewQueueError,
    generate_review_queue,
)


class GenerateSeriesTitleReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.catalog = self.root / "characters_v2.db"
        self.titles = self.root / "anime-titles.xml.gz"
        self.output = self.root / "series_title_review.csv"
        self._create_catalog()
        self._create_titles()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_catalog(self) -> None:
        conn = sqlite3.connect(self.catalog)
        try:
            conn.executescript(
                """
                CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE series (
                    id INTEGER PRIMARY KEY,
                    source_copyright_tag TEXT,
                    provisional_display_name TEXT,
                    title_resolution TEXT,
                    title_confidence REAL
                );
                CREATE TABLE source_records (
                    id INTEGER PRIMARY KEY,
                    source TEXT,
                    source_name_raw TEXT,
                    reference_count INTEGER,
                    series_id INTEGER
                );
                CREATE TABLE series_title_matches (
                    series_id INTEGER,
                    provider_series_id TEXT,
                    matched_catalog_alias TEXT,
                    matched_catalog_alias_type TEXT,
                    matched_provider_title TEXT,
                    matched_provider_language TEXT,
                    matched_provider_title_type TEXT,
                    confidence REAL,
                    resolution_status TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO build_metadata VALUES ('schema_version', ?)",
                (str(BUILD_SCHEMA_VERSION),),
            )
            conn.executemany(
                "INSERT INTO series VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "alpha", "Alpha", "ambiguous_exact_match", 0.98),
                    (2, "beta", "Beta", "below_threshold", 0.90),
                    (3, "gamma", "Gamma", "alias_only_review", 1.0),
                    (4, "accepted", "Accepted", "accepted_exact_unique", 1.0),
                ],
            )
            conn.executemany(
                "INSERT INTO source_records VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "anima", "Alpha One", 10, 1),
                    (2, "danbooru", "Alpha One", None, 1),
                    (3, "anima", "Beta One", 5, 2),
                    (4, "e621", "Gamma One", None, 3),
                ],
            )
            conn.executemany(
                "INSERT INTO series_title_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (1, "10", "alpha", "source_tag", "Alpha", "en", "official", 0.98,
                     "ambiguous_exact_match"),
                    (1, "11", "alpha", "source_tag", "Alpha", "en", "official", 0.98,
                     "ambiguous_exact_match"),
                    (2, "20", "beta", "source_tag", "Beta", "x-jat", "short", 0.90,
                     "below_threshold"),
                    (3, "30", "gamma_old", "official_search_alias", "Gamma", "x-jat",
                     "main", 1.0, "alias_only_review"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def _create_titles(self) -> None:
        entries = "\n".join(
            f"""
  <anime aid="{aid}">
    <title type="main" xml:lang="x-jat">{title} Main</title>
    <title type="official" xml:lang="en">{title}</title>
    <title type="official" xml:lang="ja">{title} JP</title>
  </anime>"""
            for aid, title in ((10, "Alpha"), (11, "Alpha"), (20, "Beta"), (30, "Gamma"))
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<animetitles>{entries}\n</animetitles>\n"
        )
        with gzip.open(self.titles, "wb") as handle:
            handle.write(xml.encode("utf-8"))

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_exports_all_review_classes_deterministically_without_mutation(self) -> None:
        catalog_hash = self._sha256(self.catalog)
        title_hash = self._sha256(self.titles)

        first = generate_review_queue(self.catalog, self.titles, self.output)
        first_bytes = self.output.read_bytes()
        second = generate_review_queue(self.catalog, self.titles, self.output)

        with self.output.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(first["rows"], 3)
        self.assertEqual(first["by_resolution"], {
            "alias_only_review": 1,
            "ambiguous_exact_match": 1,
            "below_threshold": 1,
        })
        self.assertEqual(second["rows"], 3)
        self.assertEqual(self.output.read_bytes(), first_bytes)
        self.assertEqual(self._sha256(self.catalog), catalog_hash)
        self.assertEqual(self._sha256(self.titles), title_hash)
        self.assertEqual([row["source_copyright_tag"] for row in rows], [
            "alpha",
            "beta",
            "gamma",
        ])
        self.assertEqual(rows[0]["candidate_aids"], "10 | 11")
        self.assertEqual(rows[0]["decision_action"], "")
        self.assertEqual(rows[0]["selected_aid"], "")
        evidence = json.loads(rows[0]["candidate_evidence_json"])
        self.assertEqual([item["aid"] for item in evidence], [10, 11])
        self.assertEqual(rows[0]["source_record_count"], "2")
        self.assertEqual(rows[0]["danbooru_records"], "1")
        self.assertEqual(rows[0]["anima_records"], "1")

    def test_refuses_to_overwrite_an_input(self) -> None:
        catalog_hash = self._sha256(self.catalog)
        title_hash = self._sha256(self.titles)
        for output in (self.catalog, self.titles):
            with self.subTest(output=output):
                with self.assertRaises(ReviewQueueError):
                    generate_review_queue(self.catalog, self.titles, output)
        self.assertEqual(self._sha256(self.catalog), catalog_hash)
        self.assertEqual(self._sha256(self.titles), title_hash)


if __name__ == "__main__":
    unittest.main()
