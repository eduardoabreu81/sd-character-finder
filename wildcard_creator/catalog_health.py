"""Validation and recovery helpers for the packaged character catalogue."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests


_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = _ROOT / "data" / "characters.db"
DEFAULT_MANIFEST_PATH = _ROOT / "data" / "characters.manifest.json"
MANIFEST_SCHEMA_VERSION = 1
_COUNT_TABLES = (
    "canonical_characters",
    "character_variations",
    "character_representations",
    "source_records",
)
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


@dataclass(frozen=True)
class CatalogValidation:
    """Result of validating the immutable packaged catalogue."""

    ok: bool
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class CatalogRecoveryError(RuntimeError):
    """Raised when a replacement catalogue cannot be downloaded safely."""


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_catalog_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load and minimally validate the tracked catalogue manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogRecoveryError(f"Catalogue manifest not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogRecoveryError(f"Cannot read catalogue manifest: {path}") from exc

    if not isinstance(payload, dict):
        raise CatalogRecoveryError("Catalogue manifest must be a JSON object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CatalogRecoveryError(
            f"Catalogue manifest must use schema_version={MANIFEST_SCHEMA_VERSION}"
        )
    if not str(payload.get("catalog_sha256") or "").strip():
        raise CatalogRecoveryError("Catalogue manifest has no SHA-256 digest")
    try:
        if int(payload.get("catalog_bytes", 0)) <= 0:
            raise ValueError
        if int(payload.get("catalog_schema_version", 0)) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise CatalogRecoveryError("Catalogue manifest has invalid numeric fields") from exc
    if (
        not isinstance(payload.get("counts"), dict)
        or set(payload["counts"]) != set(_COUNT_TABLES)
    ):
        raise CatalogRecoveryError("Catalogue manifest has no count audit")
    if not isinstance(payload.get("source_records_by_source"), dict):
        raise CatalogRecoveryError("Catalogue manifest has no source count audit")
    return payload


def validate_catalog(
    db_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> CatalogValidation:
    """Validate the packaged DB without including user JSON overlays."""
    db_path = db_path.resolve()
    try:
        manifest = load_catalog_manifest(manifest_path.resolve())
    except CatalogRecoveryError as exc:
        return CatalogValidation(False, "manifest_invalid", str(exc))

    try:
        catalog_exists = db_path.exists()
        actual_bytes = db_path.stat().st_size if catalog_exists else 0
    except OSError as exc:
        return CatalogValidation(
            False,
            "catalog_unreadable",
            f"The character catalogue cannot be inspected: {exc}",
        )

    if not catalog_exists:
        return CatalogValidation(
            False,
            "catalog_missing",
            "The packaged character catalogue is missing.",
            {"path": str(db_path)},
        )

    expected_bytes = int(manifest["catalog_bytes"])
    if actual_bytes != expected_bytes:
        return CatalogValidation(
            False,
            "size_mismatch",
            "The character catalogue size does not match its manifest.",
            {"expected_bytes": expected_bytes, "actual_bytes": actual_bytes},
        )

    try:
        actual_sha256 = sha256_file(db_path)
    except OSError as exc:
        return CatalogValidation(
            False,
            "catalog_unreadable",
            f"The character catalogue cannot be read: {exc}",
        )
    expected_sha256 = str(manifest["catalog_sha256"])
    if actual_sha256 != expected_sha256:
        return CatalogValidation(
            False,
            "checksum_mismatch",
            "The character catalogue checksum does not match its manifest.",
            {
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            },
        )

    connection: sqlite3.Connection | None = None
    try:
        uri = db_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=15.0)
        schema_row = connection.execute(
            "SELECT value FROM build_metadata WHERE key = 'schema_version'"
        ).fetchone()
        schema_version = int(schema_row[0]) if schema_row else 0
        expected_schema = int(manifest["catalog_schema_version"])
        if schema_version != expected_schema:
            return CatalogValidation(
                False,
                "schema_mismatch",
                "The character catalogue schema is incompatible.",
                {
                    "expected_schema": expected_schema,
                    "actual_schema": schema_version,
                },
            )

        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check != "ok":
            return CatalogValidation(
                False,
                "sqlite_corrupt",
                f"SQLite quick_check failed: {quick_check}",
            )

        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            return CatalogValidation(
                False,
                "foreign_key_errors",
                "The character catalogue has invalid relationships.",
                {"error_count": len(foreign_key_errors)},
            )

        actual_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in manifest["counts"]
        }
        expected_counts = {
            str(table): int(value)
            for table, value in manifest["counts"].items()
        }
        if actual_counts != expected_counts:
            return CatalogValidation(
                False,
                "count_mismatch",
                "The character catalogue record counts do not match its manifest.",
                {"expected": expected_counts, "actual": actual_counts},
            )

        actual_sources = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT source, COUNT(*) FROM source_records GROUP BY source"
            ).fetchall()
        }
        expected_sources = {
            str(source): int(value)
            for source, value in manifest["source_records_by_source"].items()
        }
        if actual_sources != expected_sources:
            return CatalogValidation(
                False,
                "source_count_mismatch",
                "The character catalogue source counts do not match its manifest.",
                {"expected": expected_sources, "actual": actual_sources},
            )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return CatalogValidation(
            False,
            "sqlite_unreadable",
            f"The character catalogue cannot be validated: {exc}",
        )
    finally:
        if connection is not None:
            connection.close()

    return CatalogValidation(
        True,
        "ok",
        "The character catalogue passed checksum and SQLite validation.",
        {
            "sha256": actual_sha256,
            "catalog_bytes": actual_bytes,
            "schema_version": int(manifest["catalog_schema_version"]),
        },
    )


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise CatalogRecoveryError(
            "Catalogue downloads are restricted to trusted GitHub HTTPS hosts"
        )


def redownload_catalog(
    db_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    close_callback: Callable[[], None] | None = None,
    download_url: str | None = None,
) -> CatalogValidation:
    """Download, verify, and atomically install the exact manifest catalogue."""
    db_path = db_path.resolve()
    manifest = load_catalog_manifest(manifest_path.resolve())
    url = str(download_url or manifest.get("download_url") or "").strip()
    if not url:
        raise CatalogRecoveryError("Catalogue manifest has no download URL")
    _validate_download_url(url)

    expected_bytes = int(manifest["catalog_bytes"])
    expected_sha256 = str(manifest["catalog_sha256"])
    temp_path = db_path.with_suffix(db_path.suffix + ".download")
    response = None
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(
            url,
            stream=True,
            timeout=(15, 180),
            headers={"User-Agent": "SDCharacterFinder/catalog-recovery"},
        )
        response.raise_for_status()
        final_url = str(getattr(response, "url", url) or url)
        _validate_download_url(final_url)

        digest = hashlib.sha256()
        downloaded_bytes = 0
        with temp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded_bytes += len(chunk)
                if downloaded_bytes > expected_bytes:
                    raise CatalogRecoveryError(
                        "Downloaded catalogue is larger than its manifest"
                    )
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

        if downloaded_bytes != expected_bytes:
            raise CatalogRecoveryError(
                "Downloaded catalogue size does not match its manifest"
            )
        if digest.hexdigest() != expected_sha256:
            raise CatalogRecoveryError(
                "Downloaded catalogue checksum does not match its manifest"
            )

        downloaded_validation = validate_catalog(temp_path, manifest_path)
        if not downloaded_validation.ok:
            raise CatalogRecoveryError(downloaded_validation.message)

        if close_callback is not None:
            close_callback()
        os.replace(temp_path, db_path)
        installed_validation = validate_catalog(db_path, manifest_path)
        if not installed_validation.ok:
            raise CatalogRecoveryError(installed_validation.message)
        return installed_validation
    except requests.RequestException as exc:
        raise CatalogRecoveryError(f"Catalogue download failed: {exc}") from exc
    except CatalogRecoveryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise CatalogRecoveryError(f"Catalogue recovery failed: {exc}") from exc
    finally:
        if response is not None:
            response.close()
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def build_catalog_manifest(
    db_path: Path,
    *,
    download_url: str,
) -> dict[str, Any]:
    """Create manifest data for a completed v2 catalogue."""
    db_path = db_path.resolve()
    _validate_download_url(download_url)
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        schema_row = connection.execute(
            "SELECT value FROM build_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if not schema_row:
            raise CatalogRecoveryError("Catalogue has no schema version")
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _COUNT_TABLES
        }
        source_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT source, COUNT(*) FROM source_records GROUP BY source"
            ).fetchall()
        }
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if quick_check != "ok" or foreign_key_errors:
            raise CatalogRecoveryError("Cannot manifest an invalid catalogue")
    finally:
        connection.close()

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "catalog_schema_version": int(schema_row[0]),
        "catalog_bytes": db_path.stat().st_size,
        "catalog_sha256": sha256_file(db_path),
        "download_url": download_url,
        "counts": counts,
        "source_records_by_source": source_counts,
    }
