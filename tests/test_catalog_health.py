from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wildcard_creator.catalog_health import (
    CatalogRecoveryError,
    DEFAULT_RUNTIME_CATALOG_PATH,
    build_catalog_manifest,
    prepare_runtime_catalog,
    prepare_runtime_sqlite,
    redownload_catalog,
    validate_catalog,
)
from wildcard_creator.character_db import CharacterDB


DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/example/project/test/data/characters.db"
)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.url = DOWNLOAD_URL

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]

    def close(self) -> None:
        return None


class CatalogHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_db = self.root / "source.db"
        self.installed_db = self.root / "installed.db"
        self.runtime_db = self.root / "runtime" / "characters.db"
        self.manifest_path = self.root / "characters.manifest.json"
        self._create_catalog(self.source_db)
        manifest = build_catalog_manifest(
            self.source_db,
            download_url=DOWNLOAD_URL,
        )
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _create_catalog(path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE build_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO build_metadata VALUES ('schema_version', '5');
                CREATE TABLE canonical_characters (id INTEGER PRIMARY KEY);
                CREATE TABLE character_variations (id INTEGER PRIMARY KEY);
                CREATE TABLE source_records (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL
                );
                CREATE TABLE character_representations (
                    id INTEGER PRIMARY KEY,
                    source_record_id INTEGER REFERENCES source_records(id)
                );
                INSERT INTO canonical_characters VALUES (1);
                INSERT INTO character_variations VALUES (1);
                INSERT INTO source_records VALUES (1, 'danbooru');
                INSERT INTO character_representations VALUES (1, 1);
                """
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _create_mutable_catalog(path: Path, rows: int = 1) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO items VALUES (?, ?)",
                [(item_id, f"item-{item_id}") for item_id in range(1, rows + 1)],
            )
            connection.commit()
        finally:
            connection.close()

    def test_validates_checksum_schema_integrity_and_counts(self) -> None:
        validation = validate_catalog(self.source_db, self.manifest_path)
        self.assertTrue(validation.ok)
        self.assertEqual(validation.code, "ok")

    def test_rejects_a_modified_database_before_sqlite_use(self) -> None:
        body = self.source_db.read_bytes()
        self.source_db.write_bytes(body + b"changed")
        validation = validate_catalog(self.source_db, self.manifest_path)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.code, "size_mismatch")

    def test_redownload_verifies_then_atomically_replaces_catalogue(self) -> None:
        expected_body = self.source_db.read_bytes()
        self.installed_db.write_bytes(b"broken")
        overrides_path = self.root / "user_overrides_v2.json"
        overrides_path.write_text('{"keep": true}\n', encoding="utf-8")
        with patch(
            "wildcard_creator.catalog_health.requests.get",
            return_value=_FakeResponse(expected_body),
        ):
            validation = redownload_catalog(
                self.installed_db,
                self.manifest_path,
            )
        self.assertTrue(validation.ok)
        self.assertEqual(self.installed_db.read_bytes(), expected_body)
        self.assertEqual(
            hashlib.sha256(self.installed_db.read_bytes()).hexdigest(),
            hashlib.sha256(expected_body).hexdigest(),
        )
        self.assertEqual(
            overrides_path.read_text(encoding="utf-8"),
            '{"keep": true}\n',
        )

    def test_invalid_download_never_replaces_existing_catalogue(self) -> None:
        original_body = b"existing catalogue must survive"
        self.installed_db.write_bytes(original_body)
        invalid_body = bytearray(self.source_db.read_bytes())
        invalid_body[-1] ^= 0x01

        with patch(
            "wildcard_creator.catalog_health.requests.get",
            return_value=_FakeResponse(bytes(invalid_body)),
        ):
            with self.assertRaises(CatalogRecoveryError):
                redownload_catalog(
                    self.installed_db,
                    self.manifest_path,
                )

        self.assertEqual(self.installed_db.read_bytes(), original_body)
        self.assertFalse(self.installed_db.with_suffix(".db.download").exists())

    def test_runtime_copy_keeps_packaged_catalogue_replaceable(self) -> None:
        validation = prepare_runtime_catalog(
            self.source_db,
            self.runtime_db,
            self.manifest_path,
        )
        self.assertTrue(validation.ok)
        self.assertTrue(validation.details["refreshed"])

        database = CharacterDB(
            self.runtime_db,
            user_overrides_path=self.root / "user_overrides_v2.json",
        )
        try:
            self.assertEqual(database.count(), 1)
            replacement = self.root / "replacement.db"
            self._create_catalog(replacement)
            replacement.replace(self.source_db)
            self.assertTrue(self.source_db.exists())
            self.assertEqual(database.count(), 1)
        finally:
            database.close()

    def test_runtime_refresh_closes_old_copy_before_atomic_replace(self) -> None:
        first_validation = prepare_runtime_catalog(
            self.source_db,
            self.runtime_db,
            self.manifest_path,
        )
        self.assertTrue(first_validation.ok)

        database = CharacterDB(self.runtime_db)
        try:
            self.assertEqual(database.count(), 1)
            connection = sqlite3.connect(self.source_db)
            try:
                connection.executescript(
                    """
                    INSERT INTO canonical_characters VALUES (2);
                    INSERT INTO character_variations VALUES (2);
                    INSERT INTO source_records VALUES (2, 'anima');
                    INSERT INTO character_representations VALUES (2, 2);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            updated_manifest = build_catalog_manifest(
                self.source_db,
                download_url=DOWNLOAD_URL,
            )
            self.manifest_path.write_text(
                json.dumps(updated_manifest, indent=2) + "\n",
                encoding="utf-8",
            )

            refreshed = prepare_runtime_catalog(
                self.source_db,
                self.runtime_db,
                self.manifest_path,
                close_callback=database.close,
            )
            self.assertTrue(refreshed.ok)
            self.assertTrue(refreshed.details["refreshed"])
            self.assertEqual(database.count(), 2)
        finally:
            database.close()

    def test_default_character_db_uses_ignored_runtime_copy(self) -> None:
        database = CharacterDB()
        self.assertEqual(database._path, DEFAULT_RUNTIME_CATALOG_PATH)
        self.assertEqual(
            database._user_overrides_path,
            DEFAULT_RUNTIME_CATALOG_PATH.parent.parent
            / "user_overrides_v2.json",
        )

    def test_mutable_runtime_copy_preserves_local_schema_migrations(self) -> None:
        packaged_db = self.root / "artists.db"
        runtime_db = self.root / "runtime" / "artists.db"
        self._create_mutable_catalog(packaged_db)

        first = prepare_runtime_sqlite(packaged_db, runtime_db)
        self.assertTrue(first.ok)
        self.assertTrue(first.details["refreshed"])
        connection = sqlite3.connect(runtime_db)
        try:
            connection.execute("CREATE TABLE runtime_migration (id INTEGER)")
            connection.commit()
        finally:
            connection.close()

        second = prepare_runtime_sqlite(packaged_db, runtime_db)
        self.assertTrue(second.ok)
        self.assertFalse(second.details["refreshed"])
        connection = sqlite3.connect(runtime_db)
        try:
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'runtime_migration'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(table)

    def test_mutable_runtime_refresh_closes_active_connection(self) -> None:
        packaged_db = self.root / "artists.db"
        runtime_db = self.root / "runtime" / "artists.db"
        self._create_mutable_catalog(packaged_db)
        self.assertTrue(prepare_runtime_sqlite(packaged_db, runtime_db).ok)

        runtime_connection = sqlite3.connect(runtime_db)
        self.assertEqual(
            runtime_connection.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            1,
        )
        packaged_db.unlink()
        self._create_mutable_catalog(packaged_db, rows=2)

        refreshed = prepare_runtime_sqlite(
            packaged_db,
            runtime_db,
            close_callback=runtime_connection.close,
        )
        self.assertTrue(refreshed.ok)
        self.assertTrue(refreshed.details["refreshed"])
        connection = sqlite3.connect(runtime_db)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                2,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
