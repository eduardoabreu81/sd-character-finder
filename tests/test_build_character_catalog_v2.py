from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_character_catalog_v2 import (
    BuildError,
    build_catalog,
    provisional_e621_series_display,
)
from wildcard_creator.character_db import CharacterDB


class BuildCharacterCatalogV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.current_db = self.root / "characters.db"
        self.anima_csv = self.root / "characters.csv"
        self.output = self.root / "characters_v2.db"
        self.report = self.root / "characters_v2_report.json"
        self._create_current_db()
        self._write_anima_csv()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_current_db(self) -> None:
        conn = sqlite3.connect(self.current_db)
        try:
            conn.execute(
                """
                CREATE TABLE characters (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    series TEXT,
                    tags TEXT NOT NULL,
                    image_url TEXT,
                    rank INTEGER,
                    danbooru_tag TEXT,
                    source TEXT
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO characters
                (id, name, series, tags, image_url, rank, danbooru_tag, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        1,
                        "Astolfo",
                        "Fate",
                        "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
                        "https://example.test/danbooru.jpg",
                        1,
                        "astolfo (fate)",
                        "danbooru",
                    ),
                    (
                        2,
                        "Astolfo (Fate)",
                        "Fate",
                        "astolfo (fate), fate (series), 1boy, pink hair",
                        "https://example.test/anima.jpg",
                        2,
                        "astolfo (fate), fate (series)",
                        "anima",
                    ),
                    (
                        3,
                        "Astolfo (Saber) (Fate)",
                        "Fate",
                        "astolfo (saber) (fate), fate (series), 1boy, rabbit ears",
                        "https://example.test/anima-variant.jpg",
                        3,
                        "astolfo (saber) (fate), fate (series)",
                        "anima",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def _write_anima_csv(self) -> None:
        with self.anima_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["character", "copyright", "trigger", "core_tags", "count", "url"],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "character": "astolfo_(fate)",
                        "copyright": "fate_(series)",
                        "trigger": "astolfo (fate), fate (series)",
                        "core_tags": "1boy, pink hair",
                        "count": "100",
                        "url": "https://example.test/astolfo",
                    },
                    {
                        "character": "astolfo_(saber)_(fate)",
                        "copyright": "fate_(series)",
                        "trigger": "astolfo (saber) (fate), fate (series)",
                        "core_tags": "1boy, rabbit ears",
                        "count": "50",
                        "url": "https://example.test/astolfo-saber",
                    },
                ]
            )

    def _write_anidb_dump(self, xml: str) -> Path:
        path = self.root / "anime-titles.xml.gz"
        with gzip.open(path, "wb") as handle:
            handle.write(xml.encode("utf-8"))
        return path

    def test_preserves_source_specific_prompts_and_resolves_series(self) -> None:
        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
        )

        conn = sqlite3.connect(self.output)
        try:
            rows = conn.execute(
                """
                SELECT source, prompt_raw, series_resolution
                FROM source_records
                ORDER BY legacy_id
                """
            ).fetchall()
            representations = conn.execute(
                """
                SELECT rv.name, cr.source, sr.prompt_raw, sr.image_url
                FROM runtime_character_variations rv
                JOIN character_representations cr ON cr.variation_id = rv.id
                JOIN source_records sr ON sr.id = cr.source_record_id
                WHERE rv.variation_key = 'astolfo (fate)'
                ORDER BY cr.display_order
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(
            rows[0][1],
            "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
        )
        self.assertEqual(
            rows[1][1],
            "astolfo (fate), fate (series), 1boy, pink hair",
        )
        self.assertEqual(rows[0][2], "animadex_exact_source_tag")
        self.assertEqual(rows[1][2], "animadex_explicit_copyright")
        self.assertEqual(
            representations,
            [
                (
                    "Astolfo (Fate)",
                    "danbooru",
                    "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
                    "https://example.test/danbooru.jpg",
                ),
                (
                    "Astolfo (Fate)",
                    "anima",
                    "astolfo (fate), fate (series), 1boy, pink hair",
                    "https://example.test/anima.jpg",
                ),
            ],
        )
        self.assertEqual(report["prompt_fidelity"]["verified_exact_prompts"], 2)
        self.assertEqual(report["exact_identity_groups"]["total"], 2)
        self.assertEqual(report["identity_match_candidates"]["candidate_pairs"], 1)
        self.assertEqual(
            report["canonical_catalog"]["characters"],
            2,
        )
        self.assertEqual(
            report["canonical_catalog"]["variations"],
            2,
        )
        self.assertEqual(
            report["canonical_catalog"]["representations"],
            3,
        )

    def test_runtime_search_switches_the_complete_source_representation(self) -> None:
        build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
        )
        database = CharacterDB(self.output)
        try:
            self.assertEqual(database.count(), 2)
            self.assertEqual(database.count_unique(), 2)
            self.assertEqual(database.count_by_source("danbooru"), 1)
            self.assertEqual(database.count_by_source("anima"), 2)

            danbooru_results, danbooru_total = database.search(
                "astolfo",
                source_filter="danbooru",
            )
            anima_results, anima_total = database.search(
                "astolfo",
                source_filter="anima",
            )
            exclusive_results, exclusive_total = database.search(
                "",
                source_filter="all",
                exclusive_filter="anima",
            )

            self.assertEqual(danbooru_total, 1)
            self.assertEqual(danbooru_results[0]["source"], "danbooru")
            self.assertEqual(
                danbooru_results[0]["tags"],
                "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
            )
            self.assertEqual(
                danbooru_results[0]["danbooru_tag"],
                "astolfo \\(fate\\)",
            )
            self.assertEqual(
                danbooru_results[0]["image_url"],
                "https://example.test/danbooru.jpg",
            )
            self.assertEqual(anima_total, 2)
            self.assertTrue(all(row["source"] == "anima" for row in anima_results))
            self.assertEqual(exclusive_total, 1)
            self.assertEqual(
                exclusive_results[0]["name"],
                "Astolfo (Saber) (Fate)",
            )
            self.assertEqual(
                exclusive_results[0]["exclusive_source"],
                "anima",
            )

            base = next(
                row
                for row in anima_results
                if row["variation_key"] == "astolfo (fate)"
            )
            self.assertEqual(
                [item["source"] for item in base["representations"]],
                ["danbooru", "anima"],
            )
            self.assertTrue(
                database.save_danbooru_tag(base["id"], "astolfo_live_override")
            )
            updated, _ = database.search("astolfo", source_filter="danbooru")
            self.assertEqual(updated[0]["danbooru_tag"], "astolfo_live_override")
            self.assertEqual(
                updated[0]["tags"],
                "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
            )
            edited_prompt = (
                "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair, cape"
            )
            self.assertTrue(
                database.save_prompt_override(
                    base["id"],
                    "danbooru",
                    edited_prompt,
                )
            )
            updated, _ = database.search("astolfo", source_filter="danbooru")
            self.assertEqual(updated[0]["tags"], edited_prompt)
            self.assertTrue(updated[0]["prompt_overridden"])
            anima_after_override, _ = database.search(
                "astolfo",
                source_filter="anima",
            )
            anima_base = next(
                row
                for row in anima_after_override
                if row["variation_key"] == "astolfo (fate)"
            )
            self.assertEqual(
                anima_base["tags"],
                "astolfo (fate), fate (series), 1boy, pink hair",
            )
            override_payload = json.loads(
                database._user_overrides_path.read_text(encoding="utf-8")
            )
            self.assertEqual(override_payload["schema_version"], 3)
            self.assertIn(
                "danbooru:astolfo (fate)",
                override_payload["prompt_overrides"],
            )
            conn = sqlite3.connect(self.output)
            try:
                stored_prompt = conn.execute(
                    """
                    SELECT prompt_raw FROM source_records
                    WHERE source = 'danbooru' AND match_key = 'astolfo (fate)'
                    """
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(
                stored_prompt,
                "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
            )
            self.assertTrue(
                database.reset_prompt_override(base["id"], "danbooru")
            )
            reset, _ = database.search("astolfo", source_filter="danbooru")
            self.assertEqual(reset[0]["tags"], stored_prompt)
        finally:
            database.close()

    def test_migrates_schema_two_overrides_without_losing_lookup_tags(self) -> None:
        build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
        )
        overrides_path = self.output.parent / "user_overrides_v2.json"
        overrides_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "danbooru_tags": {
                        "astolfo (fate)": "astolfo_existing_override",
                    },
                }
            ),
            encoding="utf-8",
        )

        database = CharacterDB(self.output)
        try:
            results, _ = database.search("astolfo", source_filter="danbooru")
            self.assertEqual(
                results[0]["danbooru_tag"],
                "astolfo_existing_override",
            )
            self.assertTrue(
                database.save_prompt_override(
                    results[0]["id"],
                    "danbooru",
                    results[0]["tags"] + ", cape",
                )
            )
        finally:
            database.close()

        migrated = json.loads(overrides_path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(
            migrated["danbooru_tags"]["astolfo (fate)"],
            "astolfo_existing_override",
        )
        self.assertIn(
            "danbooru:astolfo (fate)",
            migrated["prompt_overrides"],
        )

    def test_stale_prompt_override_falls_back_to_packaged_prompt(self) -> None:
        build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
        )
        database = CharacterDB(self.output)
        try:
            results, _ = database.search("astolfo", source_filter="danbooru")
            base_prompt = results[0]["source_prompt_raw"]
            self.assertTrue(
                database.save_prompt_override(
                    results[0]["id"],
                    "danbooru",
                    base_prompt + ", cape",
                )
            )
            payload = json.loads(
                database._user_overrides_path.read_text(encoding="utf-8")
            )
            payload["prompt_overrides"]["danbooru:astolfo (fate)"][
                "base_prompt_sha256"
            ] = "stale"
            database._user_overrides_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            stale_results, _ = database.search(
                "astolfo",
                source_filter="danbooru",
            )
            self.assertEqual(stale_results[0]["tags"], base_prompt)
            self.assertFalse(stale_results[0]["prompt_overridden"])
            self.assertTrue(stale_results[0]["prompt_override_conflict"])
        finally:
            database.close()

    def test_blocks_output_when_anima_prompt_changes(self) -> None:
        conn = sqlite3.connect(self.current_db)
        try:
            conn.execute(
                "UPDATE characters SET tags = ? WHERE id = 2",
                ("astolfo (fate), changed",),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(BuildError):
            build_catalog(
                self.current_db,
                self.anima_csv,
                self.output,
                self.report,
            )

        self.assertFalse(self.output.exists())

    def test_refuses_conflicting_input_and_output_paths(self) -> None:
        conflicts = [
            (self.current_db, self.report),
            (self.anima_csv, self.report),
            (self.output, self.current_db),
            (self.output, self.anima_csv),
            (self.output, self.output),
        ]
        for output, report in conflicts:
            with self.subTest(output=output, report=report):
                with self.assertRaises(BuildError):
                    build_catalog(
                        self.current_db,
                        self.anima_csv,
                        output,
                        report,
                    )

    def test_applies_reviewed_overrides_without_changing_prompts(self) -> None:
        sagami_prompt = (
            "sagami jun, bakusou kyoudai let's & go!!, 1girl, brown hair"
        )
        variant_prompt = (
            "astolfo \\(saber\\) \\(fate!\\), fate \\(series\\), 1boy"
        )
        conn = sqlite3.connect(self.current_db)
        try:
            conn.executemany(
                """
                INSERT INTO characters
                (id, name, series, tags, image_url, rank, danbooru_tag, source)
                VALUES (?, ?, ?, ?, NULL, ?, ?, 'danbooru')
                """,
                [
                    (4, "Sagami Jun", "Loli", sagami_prompt, 4, "sagami jun"),
                    (
                        5,
                        "Astolfo Saber Alias",
                        "Fate",
                        variant_prompt,
                        5,
                        "astolfo (saber) (fate!)",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        overrides_path = self.root / "catalog_overrides.json"
        overrides_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "series": [
                        {
                            "source_copyright_tag": "bakusou_kyoudai_let's_&_go!!",
                            "provider": "test_manual_review",
                            "confidence": 1.0,
                            "verified": True,
                            "aliases": [],
                        }
                    ],
                    "records": [
                        {
                            "override_key": "test:sagami_jun",
                            "source": "danbooru",
                            "match_key": "sagami jun",
                            "series_source_tag": "bakusou_kyoudai_let's_&_go!!",
                            "identity_action": "keep_distinct",
                            "reviewed_exclusive_source": "danbooru",
                            "reject_match_keys": [],
                            "notes": "Fixture series correction.",
                        },
                        {
                            "override_key": "test:astolfo_saber_alias",
                            "source": "danbooru",
                            "match_key": "astolfo (saber) (fate!)",
                            "series_source_tag": "fate_(series)",
                            "identity_action": "same_variant",
                            "merge_with_match_key": "astolfo (saber) (fate)",
                            "variation_of_match_key": "astolfo (fate)",
                            "reject_match_keys": [],
                            "notes": "Fixture provider punctuation alias.",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            overrides_path,
        )

        conn = sqlite3.connect(self.output)
        try:
            rows = conn.execute(
                """
                SELECT r.legacy_id, r.prompt_raw, r.series_resolution,
                       s.source_copyright_tag, g.reviewed_exclusive_source
                FROM source_records r
                JOIN series s ON s.id = r.series_id
                JOIN exact_identity_groups g ON g.id = r.exact_group_id
                WHERE r.legacy_id IN (4, 5) ORDER BY r.legacy_id
                """
            ).fetchall()
            relation_types = {
                row[0] for row in conn.execute("SELECT relation_type FROM identity_relations")
            }
            astolfo_variations = conn.execute(
                """
                SELECT c.canonical_key, c.variation_count, v.variation_key,
                       v.is_default, v.source_count, v.exclusive_source
                FROM canonical_characters c
                JOIN character_variations v ON v.character_id = c.id
                WHERE c.canonical_key = 'astolfo (fate)'
                ORDER BY v.is_default DESC, v.variation_key
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(rows[0][1], sagami_prompt)
        self.assertEqual(rows[1][1], variant_prompt)
        self.assertEqual(rows[0][2], "manual_catalog_override")
        self.assertEqual(rows[0][3], "bakusou_kyoudai_let's_&_go!!")
        self.assertEqual(rows[0][4], "danbooru")
        self.assertEqual(rows[1][3], "fate_(series)")
        self.assertIsNone(rows[1][4])
        self.assertEqual(relation_types, {"same_variant", "variation_of"})
        self.assertEqual(
            astolfo_variations,
            [
                ("astolfo (fate)", 2, "astolfo (fate)", 1, 2, None),
                (
                    "astolfo (fate)",
                    2,
                    "astolfo (saber) (fate)",
                    0,
                    2,
                    None,
                ),
            ],
        )
        self.assertEqual(report["manual_review"]["record_decisions"], 2)
        self.assertEqual(report["canonical_catalog"]["characters"], 2)
        self.assertEqual(report["canonical_catalog"]["variations"], 3)
        self.assertEqual(report["canonical_catalog"]["representations"], 5)
        self.assertEqual(report["canonical_catalog"]["manual_variation_families"], 1)
        self.assertEqual(
            report["manual_review"]["reviewed_exclusive_by_source"],
            {"danbooru": 1},
        )
        runtime = CharacterDB(self.output)
        try:
            reviewed_exclusive, reviewed_total = runtime.search(
                "",
                exclusive_filter="Reviewed exclusive",
            )
        finally:
            runtime.close()
        self.assertEqual(reviewed_total, 1)
        self.assertEqual(reviewed_exclusive[0]["name"], "Sagami Jun")
        self.assertEqual(
            reviewed_exclusive[0]["exclusivity_status"],
            "reviewed",
        )

    def test_imports_directional_search_aliases_without_merging_targets(self) -> None:
        alias_cache_path = self.root / "danbooru_tag_aliases.json"
        aliases = [
            (1, 4, "character", "rider_of_black", "astolfo_(fate)"),
            (
                2,
                4,
                "character",
                "astolfo_(fate)",
                "astolfo_(saber)_(fate)",
            ),
            (3, 4, "character", "unknown_old", "unknown_new"),
            (4, 3, "series", "fate", "fate_(series)"),
            (5, 3, "series", "fate_(series)", "fate_(series)"),
        ]
        alias_cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": "test_fixture",
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
            ),
            encoding="utf-8",
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            None,
            alias_cache_path,
        )

        conn = sqlite3.connect(self.output)
        try:
            character_alias = conn.execute(
                """
                SELECT a.alias_raw, a.canonical_tag_raw, a.direction, g.match_key
                FROM character_aliases a
                JOIN exact_identity_groups g ON g.id = a.exact_group_id
                """
            ).fetchone()
            series_alias = conn.execute(
                """
                SELECT a.alias, s.source_copyright_tag
                FROM series_aliases a JOIN series s ON s.id = a.series_id
                WHERE a.provider = 'danbooru_public_api'
                """
            ).fetchone()
            prompts = conn.execute(
                "SELECT prompt_raw FROM source_records ORDER BY legacy_id"
            ).fetchall()
            identity_candidate_count = conn.execute(
                "SELECT COUNT(*) FROM identity_match_candidates"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(
            character_alias,
            (
                "rider_of_black",
                "astolfo_(fate)",
                "antecedent_to_consequent",
                "astolfo (fate)",
            ),
        )
        self.assertEqual(series_alias, ("fate", "fate_(series)"))
        self.assertEqual(
            prompts[0][0],
            "astolfo \\(fate\\), fate \\(series\\), 1boy, pink hair",
        )
        self.assertEqual(
            prompts[1][0],
            "astolfo (fate), fate (series), 1boy, pink hair",
        )
        self.assertEqual(identity_candidate_count, 1)
        self.assertEqual(
            report["search_aliases"]["imported_by_target_type"],
            {"character": 1, "series": 1},
        )
        self.assertEqual(report["search_aliases"]["identity_merges_applied"], 0)
        runtime = CharacterDB(self.output)
        try:
            alias_results, alias_total = runtime.search("rider_of_black")
        finally:
            runtime.close()
        self.assertEqual(alias_total, 1)
        self.assertEqual(alias_results[0]["variation_key"], "astolfo (fate)")
        self.assertEqual(
            report["search_aliases"]["skipped_by_reason"],
            {
                "already_same_catalog_target": 1,
                "canonical_target_missing": 1,
                "connects_existing_catalog_targets": 1,
            },
        )

    def test_enriches_unique_konosuba_titles_without_changing_prompt(self) -> None:
        konosuba_prompt = (
            "aqua (konosuba), kono subarashii sekai ni shukufuku wo!, "
            "1girl, blue hair"
        )
        conn = sqlite3.connect(self.current_db)
        try:
            conn.execute(
                """
                INSERT INTO characters
                (id, name, series, tags, image_url, rank, danbooru_tag, source)
                VALUES (?, ?, ?, ?, NULL, ?, ?, 'anima')
                """,
                (
                    4,
                    "Aqua (Konosuba)",
                    "Konosuba",
                    konosuba_prompt,
                    4,
                    "aqua (konosuba), kono subarashii sekai ni shukufuku wo!",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        with self.anima_csv.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["character", "copyright", "trigger", "core_tags", "count", "url"],
            )
            writer.writerow(
                {
                    "character": "aqua_(konosuba)",
                    "copyright": "kono_subarashii_sekai_ni_shukufuku_wo!",
                    "trigger": (
                        "aqua (konosuba), "
                        "kono subarashii sekai ni shukufuku wo!"
                    ),
                    "core_tags": "1girl, blue hair",
                    "count": "200",
                    "url": "https://example.test/aqua",
                }
            )

        anidb_titles = self._write_anidb_dump(
            """<?xml version="1.0" encoding="UTF-8"?>
<animetitles>
  <anime aid="11261">
    <title type="main" xml:lang="x-jat">Kono Subarashii Sekai ni Shukufuku o!</title>
    <title type="syn" xml:lang="x-jat">Kono Subarashii Sekai ni Shukufuku wo!</title>
    <title type="short" xml:lang="x-jat">konosuba</title>
    <title type="official" xml:lang="en">Konosuba: God's Blessing on This Wonderful World!</title>
    <title type="official" xml:lang="ja">この素晴らしい世界に祝福を!</title>
    <title type="kana" xml:lang="ja">このすばらしいせかいにしゅくふくを!</title>
    <title type="card" xml:lang="ja">この素晴らしい世界に祝福を!</title>
    <title type="official" xml:lang="pt-BR">KONOSUBA - As Bênçãos de Deus Nesse Mundo Maravilhoso!</title>
  </anime>
  <anime aid="11992">
    <title type="main" xml:lang="x-jat">Kono Subarashii Sekai ni Shukufuku o! 2</title>
    <title type="short" xml:lang="x-jat">konosuba 2</title>
  </anime>
</animetitles>
"""
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            anidb_titles_path=anidb_titles,
        )

        conn = sqlite3.connect(self.output)
        try:
            series = conn.execute(
                """
                SELECT canonical_display_name, canonical_title_source,
                       title_original_transcription, title_original_language,
                       title_romaji, title_english, title_native,
                       title_resolution, title_confidence
                FROM series
                WHERE source_copyright_tag =
                      'kono_subarashii_sekai_ni_shukufuku_wo!'
                """
            ).fetchone()
            match = conn.execute(
                """
                SELECT provider_series_id, matched_provider_title_type,
                       resolution_status
                FROM series_title_matches
                """
            ).fetchone()
            aliases = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT normalized_alias FROM series_aliases
                    WHERE provider = 'anidb_title_dump'
                    """
                )
            }
            stored_languages = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT language FROM series_titles"
                )
            }
            stored_title_types = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT title_type FROM series_titles"
                )
            }
            prompt = conn.execute(
                "SELECT prompt_raw FROM source_records WHERE legacy_id = 4"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(
            series,
            (
                "Konosuba: God's Blessing on This Wonderful World!",
                "anidb_official_english",
                "Kono Subarashii Sekai ni Shukufuku o!",
                "x-jat",
                "Kono Subarashii Sekai ni Shukufuku o!",
                "Konosuba: God's Blessing on This Wonderful World!",
                "この素晴らしい世界に祝福を!",
                "accepted_exact_unique",
                0.95,
            ),
        )
        self.assertEqual(match, ("11261", "syn", "accepted_exact_unique"))
        self.assertIn("konosuba", aliases)
        self.assertEqual(stored_languages, {"x-jat", "ja", "en"})
        self.assertEqual(
            stored_title_types,
            {"main", "official", "syn", "short", "kana", "card"},
        )
        self.assertEqual(prompt, konosuba_prompt)
        self.assertEqual(report["series_titles"]["accepted_series"], 1)
        self.assertEqual(report["series_titles"]["identity_merges_applied"], 0)
        self.assertEqual(
            report["series_catalog"]["using_official_english"],
            1,
        )

    def test_leaves_tied_anidb_title_matches_ambiguous(self) -> None:
        anidb_titles = self._write_anidb_dump(
            """<?xml version="1.0" encoding="UTF-8"?>
<animetitles>
  <anime aid="1">
    <title type="main" xml:lang="x-jat">First Work</title>
    <title type="syn" xml:lang="x-jat">Fate (series)</title>
  </anime>
  <anime aid="2">
    <title type="main" xml:lang="x-jat">Second Work</title>
    <title type="syn" xml:lang="x-jat">Fate (series)</title>
  </anime>
</animetitles>
"""
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            anidb_titles_path=anidb_titles,
        )

        conn = sqlite3.connect(self.output)
        try:
            series = conn.execute(
                """
                SELECT title_romaji, title_english, title_native,
                       title_resolution, title_confidence
                FROM series WHERE source_copyright_tag = 'fate_(series)'
                """
            ).fetchone()
            matches = conn.execute(
                """
                SELECT provider_series_id, resolution_status
                FROM series_title_matches ORDER BY provider_series_id
                """
            ).fetchall()
            imported_title_count = conn.execute(
                "SELECT COUNT(*) FROM series_titles"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(
            series,
            (None, None, None, "ambiguous_exact_match", 0.95),
        )
        self.assertEqual(
            matches,
            [
                ("1", "ambiguous_exact_match"),
                ("2", "ambiguous_exact_match"),
            ],
        )
        self.assertEqual(imported_title_count, 0)
        self.assertEqual(report["series_titles"]["ambiguous_series"], 1)
        self.assertEqual(report["series_titles"]["accepted_series"], 0)

    def test_keeps_alias_only_anidb_match_for_review(self) -> None:
        alias_cache_path = self.root / "danbooru_tag_aliases.json"
        alias_cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": "test_fixture",
                    "aliases": [
                        {
                            "id": 1,
                            "category": 3,
                            "target_type": "series",
                            "antecedent_name": "fate",
                            "consequent_name": "fate_(series)",
                            "status": "active",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        anidb_titles = self._write_anidb_dump(
            """<?xml version="1.0" encoding="UTF-8"?>
<animetitles>
  <anime aid="1">
    <title type="main" xml:lang="x-jat">Fate</title>
    <title type="official" xml:lang="en">Fate</title>
    <title type="official" xml:lang="ja">フェイト</title>
  </anime>
</animetitles>
"""
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            alias_cache_path=alias_cache_path,
            anidb_titles_path=anidb_titles,
        )

        conn = sqlite3.connect(self.output)
        try:
            series = conn.execute(
                """
                SELECT title_romaji, title_english, title_native,
                       title_resolution
                FROM series WHERE source_copyright_tag = 'fate_(series)'
                """
            ).fetchone()
            match_status = conn.execute(
                "SELECT resolution_status FROM series_title_matches"
            ).fetchone()[0]
            stored_title_count = conn.execute(
                "SELECT COUNT(*) FROM series_titles"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(series, (None, None, None, "alias_only_review"))
        self.assertEqual(match_status, "alias_only_review")
        self.assertEqual(stored_title_count, 0)
        self.assertEqual(report["series_titles"]["alias_only_review_series"], 1)
        self.assertEqual(report["series_titles"]["accepted_series"], 0)

    def test_does_not_label_non_japanese_main_title_as_romaji_or_native(self) -> None:
        anidb_titles = self._write_anidb_dump(
            """<?xml version="1.0" encoding="UTF-8"?>
<animetitles>
  <anime aid="1">
    <title type="main" xml:lang="x-zht">Fate (series)</title>
    <title type="official" xml:lang="en">Fate Saga</title>
    <title type="official" xml:lang="ja">フェイト</title>
  </anime>
</animetitles>
"""
        )

        build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            anidb_titles_path=anidb_titles,
        )

        conn = sqlite3.connect(self.output)
        try:
            series = conn.execute(
                """
                SELECT canonical_display_name, canonical_title_source,
                       title_original_transcription, title_original_language,
                       title_romaji, title_english, title_native,
                       title_resolution
                FROM series WHERE source_copyright_tag = 'fate_(series)'
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(
            series,
            (
                "Fate Saga",
                "anidb_official_english",
                "Fate (series)",
                "x-zht",
                None,
                "Fate Saga",
                None,
                "accepted_exact_unique",
            ),
        )

    def test_applies_official_e621_implication_without_changing_prompt(self) -> None:
        prompt = "narinder, cult of the lamb"
        conn = sqlite3.connect(self.current_db)
        try:
            conn.execute(
                """
                INSERT INTO characters
                (id, name, series, tags, image_url, rank, danbooru_tag, source)
                VALUES (?, ?, ?, ?, NULL, ?, NULL, 'e621')
                """,
                (4, "narinder", "Christmas", prompt, 4),
            )
            conn.commit()
        finally:
            conn.close()

        evidence_path = self.root / "e621_series_implications.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": "e621_db_export",
                    "export_date": "2026-07-23",
                    "source_files": {},
                    "assignments": [
                        {
                            "source_record_id": 4,
                            "legacy_id": 4,
                            "match_key": "narinder",
                            "source_tag_raw": "narinder",
                            "resolved_tag": "narinder",
                            "alias_chain": ["narinder"],
                            "character_post_count": 100,
                            "copyright_tag": "cult_of_the_lamb",
                            "series_source_tag": "cult_of_the_lamb",
                            "catalog_match_type": "new_series_definition",
                            "implication_path": [
                                "narinder",
                                "cult_of_the_lamb",
                            ],
                            "implication_depth": 1,
                            "current_series_raw": "Christmas",
                            "prompt_sha256": hashlib.sha256(
                                prompt.encode("utf-8")
                            ).hexdigest(),
                            "confidence": 1.0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = build_catalog(
            self.current_db,
            self.anima_csv,
            self.output,
            self.report,
            e621_series_evidence_path=evidence_path,
        )

        conn = sqlite3.connect(self.output)
        try:
            source_record = conn.execute(
                """
                SELECT r.prompt_raw, r.copyright_tag_raw, r.series_resolution,
                       r.series_confidence, s.source_copyright_tag,
                       s.metadata_provider, s.metadata_verified
                FROM source_records r
                JOIN series s ON s.id = r.series_id
                WHERE r.source = 'e621' AND r.legacy_id = 4
                """
            ).fetchone()
            variation_series = conn.execute(
                """
                SELECT s.source_copyright_tag
                FROM character_variations v
                JOIN character_representations cr ON cr.variation_id = v.id
                JOIN source_records r ON r.id = cr.source_record_id
                JOIN series s ON s.id = v.series_id
                WHERE r.source = 'e621' AND r.legacy_id = 4
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(
            source_record,
            (
                prompt,
                "cult_of_the_lamb",
                "e621_export_active_implication",
                1.0,
                "cult_of_the_lamb",
                "e621_db_export",
                1,
            ),
        )
        self.assertEqual(variation_series, ("cult_of_the_lamb",))
        self.assertEqual(report["e621_series_evidence"]["assignments"], 1)
        self.assertEqual(
            report["e621_series_evidence"]["series_definitions_added"],
            1,
        )
        self.assertEqual(report["e621_series_evidence"]["source_prompts_changed"], 0)

    def test_formats_new_e621_series_as_readable_provisional_english(self) -> None:
        self.assertEqual(
            provisional_e621_series_display(
                {"series_source_tag": "friendship_is_magic"}
            ),
            "Friendship Is Magic",
        )
        self.assertEqual(
            provisional_e621_series_display(
                {"series_source_tag": "sonic_the_hedgehog_(series)"}
            ),
            "Sonic the Hedgehog",
        )
        self.assertEqual(
            provisional_e621_series_display(
                {"series_source_tag": "t.u.f.f._puppy"}
            ),
            "T.U.F.F. Puppy",
        )


if __name__ == "__main__":
    unittest.main()
