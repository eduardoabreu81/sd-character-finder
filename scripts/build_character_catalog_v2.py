#!/usr/bin/env python3
"""Build an audited v2 character catalogue from local source artifacts.

This script never mutates ``data/characters.db``. DownloadMost records are
copied from that database with their prompt text unchanged. AnimaDex records
are rebuilt from ``data/anima_import/characters.csv`` and must match the
currently bundled Anima prompts exactly before an output database is accepted.

The generated catalogue keeps the review substrate and also materializes the
runtime model used by v2: canonical characters, their reviewed variations, and
source-specific representations. Unreviewed exact-tag groups remain separate,
so the builder never invents an identity merge merely to increase deduplication.

Usage:
    python scripts/fetch_anidb_titles.py
    python scripts/build_character_catalog_v2.py
    python scripts/build_character_catalog_v2.py --output C:\\tmp\\characters_v2.db
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
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEFAULT_CURRENT_DB = DATA_DIR / "generated" / "characters_legacy.db"
DEFAULT_ANIMA_CSV = DATA_DIR / "anima_import" / "characters.csv"
DEFAULT_OVERRIDES = DATA_DIR / "catalog_overrides.json"
DEFAULT_ALIAS_CACHE = DATA_DIR / "generated" / "danbooru_tag_aliases.json"
DEFAULT_ANIDB_TITLES = DATA_DIR / "generated" / "anidb_anime_titles.xml.gz"
DEFAULT_OUTPUT = DATA_DIR / "generated" / "characters_v2.db"
DEFAULT_REPORT = DATA_DIR / "generated" / "characters_v2_report.json"

BUILD_SCHEMA_VERSION = 5
OVERRIDE_SCHEMA_VERSION = 1
ALIAS_CACHE_SCHEMA_VERSION = 1
SOURCE_BITS = {"danbooru": 1, "e621": 2, "anima": 4}
SOURCE_ORDER = ("danbooru", "e621", "anima")
XML_LANGUAGE_ATTRIBUTE = "{http://www.w3.org/XML/1998/namespace}lang"
ANIDB_TITLE_TYPES = {"main", "official", "short", "syn", "card", "kana"}
ANIDB_MATCH_TITLE_TYPES = {"main", "official", "short", "syn"}
ANIDB_MATCH_CONFIDENCE = {
    "main": 1.0,
    "official": 0.98,
    "syn": 0.95,
    "short": 0.90,
}
ANIDB_ACCEPTANCE_THRESHOLD = 0.95
ANIDB_SEARCH_LANGUAGES = {"x-jat", "ja", "en"}


class BuildError(RuntimeError):
    """Raised when source fidelity checks prevent a safe catalogue build."""


def normalize_text(value: str | None) -> str:
    """Normalize a copy of source text for matching without changing the source."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\\(", "(").replace("\\)", ")")
    text = text.replace("_", " ").casefold()
    return " ".join(text.split())


def extract_source_tag(prompt: str | None) -> str:
    """Return the first prompt tag verbatim except for surrounding whitespace."""
    if not prompt:
        return ""
    return prompt.split(",", 1)[0].strip()


def base_match_key(value: str | None) -> str:
    """Remove parenthetical qualifiers from normalized text for review candidates."""
    without_qualifiers = re.sub(r"\s*\([^)]*\)", "", normalize_text(value))
    return " ".join(without_qualifiers.split())


def humanize_source_tag(value: str) -> str:
    """Create a conservative display label; this is not an authoritative title."""
    return " ".join(
        value.replace("\\(", "(").replace("\\)", ")").replace("_", " ").split()
    )


def compose_anima_prompt(trigger: str, core_tags: str) -> str:
    """Compose the Anima prompt using the provider's existing delimiter."""
    trigger = trigger.strip()
    core_tags = core_tags.strip()
    if trigger and core_tags:
        return f"{trigger}, {core_tags}"
    return trigger or core_tags


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_current_records(path: Path) -> list[dict[str, Any]]:
    conn = open_readonly(path)
    try:
        rows = conn.execute(
            """
            SELECT id, name, series, tags, image_url, rank, danbooru_tag,
                   COALESCE(source, 'danbooru') AS source
            FROM characters
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def read_anima_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"character", "copyright", "trigger", "core_tags", "count", "url"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise BuildError(f"Anima CSV is missing columns: {sorted(missing)}")

        for line_number, row in enumerate(reader, start=2):
            character = (row.get("character") or "").strip()
            copyright_tag = (row.get("copyright") or "").strip()
            trigger = (row.get("trigger") or "").strip()
            core_tags = (row.get("core_tags") or "").strip()
            if not character or not trigger:
                raise BuildError(
                    f"Anima CSV line {line_number} lacks character or trigger"
                )
            try:
                count = int(row.get("count") or 0)
            except ValueError as exc:
                raise BuildError(
                    f"Anima CSV line {line_number} has invalid count"
                ) from exc

            prompt_raw = compose_anima_prompt(trigger, core_tags)
            source_tag_raw = extract_source_tag(trigger)
            records.append(
                {
                    "line_number": line_number,
                    "character": character,
                    "copyright": copyright_tag,
                    "trigger": trigger,
                    "core_tags": core_tags,
                    "count": count,
                    "url": (row.get("url") or "").strip(),
                    "prompt_raw": prompt_raw,
                    "source_tag_raw": source_tag_raw,
                    "match_key": normalize_text(source_tag_raw),
                }
            )
    return records


def read_catalog_overrides(path: Path | None) -> dict[str, Any]:
    """Load tracked manual decisions; direct callers may opt out with ``None``."""
    if path is None:
        return {"schema_version": OVERRIDE_SCHEMA_VERSION, "series": [], "records": []}
    if not path.exists():
        raise BuildError(f"Catalogue overrides not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read catalogue overrides: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != OVERRIDE_SCHEMA_VERSION:
        raise BuildError(
            f"Catalogue overrides must use schema_version={OVERRIDE_SCHEMA_VERSION}"
        )
    for key in ("series", "records"):
        if not isinstance(data.get(key), list):
            raise BuildError(f"Catalogue overrides field '{key}' must be a list")
    return data


def read_official_alias_cache(path: Path | None) -> dict[str, Any] | None:
    """Load a category-filtered Danbooru alias snapshot when explicitly supplied."""
    if path is None:
        return None
    if not path.exists():
        raise BuildError(f"Official alias cache not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read official alias cache: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != ALIAS_CACHE_SCHEMA_VERSION:
        raise BuildError(
            f"Official alias cache must use schema_version={ALIAS_CACHE_SCHEMA_VERSION}"
        )
    aliases = data.get("aliases")
    if not isinstance(aliases, list):
        raise BuildError("Official alias cache field 'aliases' must be a list")

    seen_ids: set[int] = set()
    for row in aliases:
        if not isinstance(row, dict):
            raise BuildError("Official alias cache contains a non-object row")
        try:
            alias_id = int(row["id"])
            category = int(row["category"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildError("Official alias cache row has invalid ID or category") from exc
        expected_type = {3: "series", 4: "character"}.get(category)
        if alias_id in seen_ids:
            raise BuildError(f"Official alias cache contains duplicate ID {alias_id}")
        if expected_type is None or row.get("target_type") != expected_type:
            raise BuildError(f"Official alias {alias_id} has an invalid category/type")
        if row.get("status") != "active":
            raise BuildError(f"Official alias {alias_id} is not active")
        if not str(row.get("antecedent_name") or "").strip():
            raise BuildError(f"Official alias {alias_id} has an empty antecedent")
        if not str(row.get("consequent_name") or "").strip():
            raise BuildError(f"Official alias {alias_id} has an empty consequent")
        seen_ids.add(alias_id)
    return data


def read_anidb_title_dump(path: Path | None) -> dict[str, Any] | None:
    """Read the official AniDB title dump without inferring language from text."""
    if path is None:
        return None
    if not path.exists():
        raise BuildError(f"AniDB title dump not found: {path}")

    try:
        with gzip.open(path, "rb") as handle:
            root = ET.parse(handle).getroot()
    except (OSError, ET.ParseError) as exc:
        raise BuildError(f"Cannot read AniDB title dump: {path}") from exc
    if root.tag != "animetitles":
        raise BuildError(f"Unexpected AniDB title dump root: {root.tag}")

    anime_by_aid: dict[int, list[dict[str, Any]]] = {}
    title_count = 0
    for anime_element in root.findall("anime"):
        try:
            aid = int(anime_element.attrib["aid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildError("AniDB title dump contains an invalid anime ID") from exc
        if aid in anime_by_aid:
            raise BuildError(f"AniDB title dump contains duplicate anime ID {aid}")

        titles: list[dict[str, Any]] = []
        for title_element in anime_element.findall("title"):
            title = (title_element.text or "").strip()
            title_type = str(title_element.attrib.get("type") or "").strip()
            language = str(
                title_element.attrib.get(XML_LANGUAGE_ATTRIBUTE) or ""
            ).strip()
            if not title or not language or title_type not in ANIDB_TITLE_TYPES:
                raise BuildError(
                    f"AniDB anime {aid} contains an invalid title row "
                    f"(type={title_type!r}, language={language!r})"
                )
            titles.append(
                {
                    "title": title,
                    "normalized_title": normalize_text(title),
                    "language": language,
                    "title_type": title_type,
                }
            )
        if not titles:
            raise BuildError(f"AniDB anime {aid} does not contain titles")
        if sum(title["title_type"] == "main" for title in titles) != 1:
            raise BuildError(f"AniDB anime {aid} must contain exactly one main title")
        titles.sort(
            key=lambda row: (
                -ANIDB_MATCH_CONFIDENCE.get(row["title_type"], 0.0),
                row["language"],
                row["normalized_title"],
                row["title"],
            )
        )
        anime_by_aid[aid] = titles
        title_count += len(titles)

    return {
        "provider": "anidb_title_dump",
        "anime_by_aid": anime_by_aid,
        "anime_count": len(anime_by_aid),
        "title_count": title_count,
    }


def validate_anima_prompts(
    current_records: list[dict[str, Any]],
    anima_records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Match the local CSV to bundled Anima rows and require exact prompts."""
    current_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in current_records:
        if record["source"] != "anima":
            continue
        raw_tag = extract_source_tag(record.get("tags"))
        current_by_key[normalize_text(raw_tag)].append(record)

    csv_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in anima_records:
        csv_by_key[record["match_key"]].append(record)

    duplicate_current = {key: len(rows) for key, rows in current_by_key.items() if len(rows) != 1}
    duplicate_csv = {key: len(rows) for key, rows in csv_by_key.items() if len(rows) != 1}
    missing_current: list[str] = []
    prompt_mismatches: list[dict[str, Any]] = []
    matched: dict[str, dict[str, Any]] = {}

    for anima in anima_records:
        matches = current_by_key.get(anima["match_key"], [])
        if len(matches) != 1:
            missing_current.append(anima["match_key"])
            continue
        current = matches[0]
        if current.get("tags") != anima["prompt_raw"]:
            prompt_mismatches.append(
                {
                    "match_key": anima["match_key"],
                    "legacy_id": current["id"],
                    "current_sha256": sha256_text(current.get("tags") or ""),
                    "csv_sha256": sha256_text(anima["prompt_raw"]),
                }
            )
            continue
        matched[anima["match_key"]] = current

    extra_current = sorted(set(current_by_key).difference(csv_by_key))
    validation = {
        "csv_records": len(anima_records),
        "current_anima_records": sum(len(rows) for rows in current_by_key.values()),
        "verified_exact_prompts": len(matched),
        "duplicate_current_match_keys": duplicate_current,
        "duplicate_csv_match_keys": duplicate_csv,
        "missing_current_count": len(missing_current),
        "missing_current_samples": missing_current[:20],
        "extra_current_count": len(extra_current),
        "extra_current_samples": extra_current[:20],
        "prompt_mismatch_count": len(prompt_mismatches),
        "prompt_mismatch_samples": prompt_mismatches[:20],
    }

    if duplicate_current or duplicate_csv or missing_current or extra_current or prompt_mismatches:
        raise BuildError(
            "Anima prompt fidelity validation failed: "
            + json.dumps(validation, ensure_ascii=False, sort_keys=True)
        )

    return matched, validation


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE build_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE series (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    source_copyright_tag     TEXT NOT NULL UNIQUE,
    normalized_key           TEXT NOT NULL UNIQUE,
    provisional_display_name TEXT NOT NULL,
    canonical_display_name   TEXT NOT NULL,
    canonical_title_source   TEXT NOT NULL DEFAULT 'source_tag',
    series_scope             TEXT NOT NULL DEFAULT 'unknown' CHECK (
        series_scope IN ('franchise', 'work', 'adaptation', 'unknown')
    ),
    metadata_provider        TEXT NOT NULL,
    metadata_confidence      REAL NOT NULL,
    metadata_verified        INTEGER NOT NULL CHECK (metadata_verified IN (0, 1)),
    title_original_transcription TEXT,
    title_original_language  TEXT,
    title_romaji             TEXT,
    title_english            TEXT,
    title_native             TEXT,
    title_resolution         TEXT NOT NULL DEFAULT 'unresolved',
    title_confidence         REAL NOT NULL DEFAULT 0.0,
    parent_series_id         INTEGER REFERENCES series(id)
);

CREATE TABLE series_aliases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id        INTEGER NOT NULL REFERENCES series(id),
    alias            TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language         TEXT,
    alias_type       TEXT NOT NULL,
    provider         TEXT NOT NULL,
    confidence       REAL NOT NULL,
    verified         INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    UNIQUE(series_id, alias, provider)
);

CREATE INDEX idx_series_aliases_normalized ON series_aliases(normalized_alias);

CREATE TABLE series_title_matches (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id                    INTEGER NOT NULL REFERENCES series(id),
    provider                     TEXT NOT NULL,
    provider_series_id           TEXT NOT NULL,
    matched_catalog_alias        TEXT NOT NULL,
    matched_catalog_alias_type   TEXT NOT NULL,
    matched_provider_title       TEXT NOT NULL,
    matched_provider_language    TEXT NOT NULL,
    matched_provider_title_type  TEXT NOT NULL,
    confidence                   REAL NOT NULL,
    resolution_status            TEXT NOT NULL CHECK (
        resolution_status IN (
            'accepted_exact_unique',
            'ambiguous_exact_match',
            'below_threshold',
            'alias_only_review',
            'superseded_lower_confidence'
        )
    ),
    UNIQUE(series_id, provider, provider_series_id)
);

CREATE INDEX idx_series_title_matches_series
ON series_title_matches(series_id);

CREATE TABLE series_titles (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id          INTEGER NOT NULL REFERENCES series(id),
    title              TEXT NOT NULL,
    normalized_title   TEXT NOT NULL,
    language           TEXT NOT NULL,
    title_type         TEXT NOT NULL CHECK (
        title_type IN ('main', 'official', 'short', 'syn', 'card', 'kana')
    ),
    provider           TEXT NOT NULL,
    provider_series_id TEXT NOT NULL,
    confidence         REAL NOT NULL,
    verified           INTEGER NOT NULL CHECK (verified IN (0, 1)),
    UNIQUE(
        series_id, title, language, title_type, provider, provider_series_id
    )
);

CREATE INDEX idx_series_titles_normalized ON series_titles(normalized_title);

CREATE TABLE exact_identity_groups (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key                    TEXT NOT NULL UNIQUE,
    source_mask                  INTEGER NOT NULL,
    source_count                 INTEGER NOT NULL,
    provisional_exclusive_source TEXT,
    reviewed_exclusive_source    TEXT,
    resolution_status            TEXT NOT NULL DEFAULT 'exact_tag_only'
);

CREATE TABLE character_aliases (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    exact_group_id       INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    alias_raw            TEXT NOT NULL,
    normalized_alias     TEXT NOT NULL UNIQUE,
    canonical_tag_raw    TEXT NOT NULL,
    canonical_normalized TEXT NOT NULL,
    alias_type           TEXT NOT NULL,
    provider             TEXT NOT NULL,
    confidence           REAL NOT NULL,
    verified             INTEGER NOT NULL CHECK (verified IN (0, 1)),
    direction            TEXT NOT NULL CHECK (direction = 'antecedent_to_consequent')
);

CREATE INDEX idx_character_aliases_group ON character_aliases(exact_group_id);

CREATE TABLE source_records (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_id                INTEGER,
    provider                 TEXT NOT NULL,
    source                   TEXT NOT NULL CHECK (source IN ('danbooru', 'e621', 'anima')),
    source_name_raw          TEXT NOT NULL,
    source_character_key_raw TEXT,
    source_tag_raw           TEXT NOT NULL,
    canonical_tag_raw        TEXT,
    match_key                TEXT NOT NULL,
    prompt_raw               TEXT NOT NULL,
    prompt_sha256            TEXT NOT NULL,
    trigger_raw              TEXT,
    core_tags_raw            TEXT,
    copyright_tag_raw        TEXT,
    current_series_raw       TEXT,
    image_url                TEXT,
    source_url               TEXT,
    rank                     INTEGER,
    reference_count          INTEGER,
    exact_group_id           INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    series_id                INTEGER REFERENCES series(id),
    series_resolution        TEXT NOT NULL,
    series_confidence        REAL NOT NULL,
    prompt_verified          INTEGER NOT NULL CHECK (prompt_verified IN (0, 1))
);

CREATE UNIQUE INDEX idx_source_records_legacy
ON source_records(source, legacy_id)
WHERE legacy_id IS NOT NULL;
CREATE INDEX idx_source_records_match ON source_records(match_key);
CREATE INDEX idx_source_records_source ON source_records(source);
CREATE INDEX idx_source_records_series ON source_records(series_id);

CREATE TABLE identity_match_candidates (
    left_group_id  INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    right_group_id INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    reasons        TEXT NOT NULL,
    confidence     REAL NOT NULL,
    review_status  TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY(left_group_id, right_group_id),
    CHECK(left_group_id < right_group_id)
);

CREATE TABLE manual_review_decisions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    override_key              TEXT NOT NULL UNIQUE,
    source_record_id          INTEGER NOT NULL UNIQUE REFERENCES source_records(id),
    series_id                 INTEGER NOT NULL REFERENCES series(id),
    identity_action           TEXT NOT NULL,
    reviewed_exclusive_source TEXT,
    notes                     TEXT NOT NULL
);

CREATE TABLE identity_relations (
    subject_group_id INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    object_group_id  INTEGER NOT NULL REFERENCES exact_identity_groups(id),
    relation_type    TEXT NOT NULL CHECK (
        relation_type IN ('same_variant', 'different_identity', 'variation_of')
    ),
    decision_id      INTEGER NOT NULL REFERENCES manual_review_decisions(id),
    PRIMARY KEY(subject_group_id, object_group_id, relation_type),
    CHECK(subject_group_id != object_group_id)
);

CREATE TABLE canonical_characters (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key              TEXT NOT NULL UNIQUE,
    display_name               TEXT NOT NULL,
    normalized_display_name    TEXT NOT NULL,
    default_variation_group_id INTEGER NOT NULL UNIQUE
                               REFERENCES exact_identity_groups(id),
    primary_series_id          INTEGER REFERENCES series(id),
    source_mask                INTEGER NOT NULL,
    source_count               INTEGER NOT NULL,
    exclusive_source           TEXT CHECK (
        exclusive_source IS NULL
        OR exclusive_source IN ('danbooru', 'e621', 'anima')
    ),
    exclusivity_status         TEXT NOT NULL CHECK (
        exclusivity_status IN (
            'multiple_sources',
            'reviewed',
            'provisional_exact',
            'provisional_variation_family'
        )
    ),
    variation_count            INTEGER NOT NULL CHECK (variation_count > 0),
    resolution_status          TEXT NOT NULL
);

CREATE INDEX idx_canonical_characters_name
ON canonical_characters(normalized_display_name);
CREATE INDEX idx_canonical_characters_series
ON canonical_characters(primary_series_id);
CREATE INDEX idx_canonical_characters_exclusive
ON canonical_characters(exclusive_source, exclusivity_status);

CREATE TABLE character_variations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id            INTEGER NOT NULL REFERENCES canonical_characters(id),
    canonical_group_id      INTEGER NOT NULL UNIQUE REFERENCES exact_identity_groups(id),
    variation_key           TEXT NOT NULL UNIQUE,
    display_name            TEXT NOT NULL,
    normalized_display_name TEXT NOT NULL,
    series_id               INTEGER REFERENCES series(id),
    series_resolution       TEXT NOT NULL,
    is_default              INTEGER NOT NULL CHECK (is_default IN (0, 1)),
    source_mask             INTEGER NOT NULL,
    source_count            INTEGER NOT NULL,
    exclusive_source        TEXT CHECK (
        exclusive_source IS NULL
        OR exclusive_source IN ('danbooru', 'e621', 'anima')
    ),
    exclusivity_status      TEXT NOT NULL CHECK (
        exclusivity_status IN (
            'multiple_sources',
            'reviewed',
            'provisional_exact'
        )
    ),
    resolution_status       TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_character_variations_default
ON character_variations(character_id)
WHERE is_default = 1;
CREATE INDEX idx_character_variations_name
ON character_variations(normalized_display_name);
CREATE INDEX idx_character_variations_series
ON character_variations(series_id);
CREATE INDEX idx_character_variations_exclusive
ON character_variations(exclusive_source, exclusivity_status);

CREATE TABLE variation_identity_groups (
    variation_id  INTEGER NOT NULL REFERENCES character_variations(id),
    exact_group_id INTEGER NOT NULL UNIQUE REFERENCES exact_identity_groups(id),
    PRIMARY KEY(variation_id, exact_group_id)
);

CREATE TABLE character_representations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    variation_id     INTEGER NOT NULL REFERENCES character_variations(id),
    source_record_id INTEGER NOT NULL UNIQUE REFERENCES source_records(id),
    source           TEXT NOT NULL CHECK (source IN ('danbooru', 'e621', 'anima')),
    display_order    INTEGER NOT NULL,
    is_default       INTEGER NOT NULL CHECK (is_default IN (0, 1)),
    UNIQUE(variation_id, source)
);

CREATE UNIQUE INDEX idx_character_representations_default
ON character_representations(variation_id)
WHERE is_default = 1;
CREATE INDEX idx_character_representations_source
ON character_representations(source, variation_id);

CREATE TABLE character_search_terms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    variation_id    INTEGER NOT NULL REFERENCES character_variations(id),
    term_raw        TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    term_type       TEXT NOT NULL,
    provider        TEXT NOT NULL,
    source          TEXT CHECK (
        source IS NULL OR source IN ('danbooru', 'e621', 'anima')
    ),
    verified        INTEGER NOT NULL CHECK (verified IN (0, 1)),
    UNIQUE(variation_id, normalized_term, term_type, provider)
);

CREATE INDEX idx_character_search_terms_normalized
ON character_search_terms(normalized_term);
CREATE INDEX idx_character_search_terms_variation
ON character_search_terms(variation_id);

CREATE VIEW runtime_character_variations AS
SELECT
    v.id,
    v.character_id,
    v.display_name AS name,
    v.variation_key,
    s.canonical_display_name AS series,
    s.source_copyright_tag AS series_source_tag,
    s.series_scope,
    v.is_default,
    CASE WHEN v.is_default = 1 THEN 0 ELSE 1 END AS is_variation,
    v.source_mask,
    v.source_count,
    v.exclusive_source,
    v.exclusivity_status,
    c.variation_count,
    v.resolution_status
FROM character_variations v
JOIN canonical_characters c ON c.id = v.character_id
LEFT JOIN series s ON s.id = v.series_id;
"""


def source_mask(sources: Iterable[str]) -> int:
    mask = 0
    for source in sources:
        mask |= SOURCE_BITS[source]
    return mask


def source_combination(sources: Iterable[str]) -> str:
    source_set = set(sources)
    return "+".join(source for source in SOURCE_ORDER if source in source_set)


def build_match_candidates(
    conn: sqlite3.Connection,
    group_names: dict[int, set[str]],
    group_match_keys: dict[int, str],
) -> dict[str, Any]:
    """Create review-only alias/variation candidates without merging anything."""
    exact_name_index: dict[str, set[int]] = defaultdict(set)
    base_name_index: dict[str, set[int]] = defaultdict(set)
    base_tag_index: dict[str, set[int]] = defaultdict(set)

    for group_id, names in group_names.items():
        for name in names:
            normalized = normalize_text(name)
            if normalized:
                exact_name_index[normalized].add(group_id)
            base = base_match_key(name)
            if len(base) >= 3:
                base_name_index[base].add(group_id)
        tag_base = base_match_key(group_match_keys[group_id])
        if len(tag_base) >= 3:
            base_tag_index[tag_base].add(group_id)

    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    skipped_large_buckets = 0

    def add_index(index: dict[str, set[int]], reason: str, confidence: float) -> None:
        nonlocal skipped_large_buckets
        for group_ids in index.values():
            ids = sorted(group_ids)
            if len(ids) > 50:
                skipped_large_buckets += 1
                continue
            for pos, left_id in enumerate(ids):
                for right_id in ids[pos + 1 :]:
                    key = (left_id, right_id)
                    item = candidates.setdefault(
                        key,
                        {"reasons": set(), "confidence": 0.0},
                    )
                    item["reasons"].add(reason)
                    item["confidence"] = max(item["confidence"], confidence)

    add_index(exact_name_index, "same_normalized_display_name", 0.95)
    add_index(base_tag_index, "same_base_source_tag", 0.80)
    add_index(base_name_index, "same_base_display_name", 0.75)

    for (left_id, right_id), item in sorted(candidates.items()):
        conn.execute(
            """
            INSERT INTO identity_match_candidates
            (left_group_id, right_group_id, reasons, confidence)
            VALUES (?, ?, ?, ?)
            """,
            (
                left_id,
                right_id,
                ",".join(sorted(item["reasons"])),
                item["confidence"],
            ),
        )

    reason_counts: Counter[str] = Counter()
    for item in candidates.values():
        for reason in item["reasons"]:
            reason_counts[reason] += 1
    return {
        "candidate_pairs": len(candidates),
        "pairs_by_reason": dict(sorted(reason_counts.items())),
        "skipped_large_buckets": skipped_large_buckets,
    }


def insert_series_definition(
    conn: sqlite3.Connection,
    series_ids: dict[str, int],
    definition: dict[str, Any],
) -> int:
    """Insert a provenance-bearing series definition and its searchable aliases."""
    source_tag = str(definition.get("source_copyright_tag") or "").strip()
    provider = str(definition.get("provider") or "").strip()
    display_name = str(
        definition.get("provisional_display_name") or humanize_source_tag(source_tag)
    ).strip()
    series_scope = str(definition.get("series_scope") or "unknown").strip()
    confidence = definition.get("confidence", 1.0)
    verified = definition.get("verified", True)
    if not source_tag or not provider or not display_name:
        raise BuildError("Every series definition needs a source tag, provider, and display name")
    if source_tag in series_ids:
        raise BuildError(f"Duplicate series definition: {source_tag}")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        raise BuildError(f"Invalid series confidence for {source_tag}")
    if not isinstance(verified, bool):
        raise BuildError(f"Series verified flag must be boolean for {source_tag}")
    if series_scope not in {"franchise", "work", "adaptation", "unknown"}:
        raise BuildError(f"Invalid series scope for {source_tag}: {series_scope}")

    cursor = conn.execute(
        """
        INSERT INTO series
        (source_copyright_tag, normalized_key, provisional_display_name,
         canonical_display_name, canonical_title_source, series_scope,
         metadata_provider, metadata_confidence, metadata_verified,
         title_original_transcription, title_original_language,
         title_romaji, title_english, title_native)
        VALUES (?, ?, ?, ?, 'source_tag', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_tag,
            normalize_text(source_tag),
            display_name,
            display_name,
            series_scope,
            provider,
            float(confidence),
            int(verified),
            definition.get("title_original_transcription"),
            definition.get("title_original_language"),
            definition.get("title_romaji"),
            definition.get("title_english"),
            definition.get("title_native"),
        ),
    )
    series_id = int(cursor.lastrowid)
    series_ids[source_tag] = series_id

    alias_specs: list[dict[str, Any]] = [
        {"alias": source_tag, "alias_type": "source_tag", "language": None},
        {"alias": display_name, "alias_type": "humanized_source_tag", "language": None},
    ]
    custom_aliases = definition.get("aliases", [])
    if not isinstance(custom_aliases, list):
        raise BuildError(f"Series aliases must be a list for {source_tag}")
    alias_specs.extend(custom_aliases)

    seen_aliases: set[str] = set()
    for alias_spec in alias_specs:
        if not isinstance(alias_spec, dict):
            raise BuildError(f"Invalid series alias for {source_tag}")
        alias = str(alias_spec.get("alias") or "").strip()
        alias_type = str(alias_spec.get("alias_type") or "manual_alias").strip()
        alias_provider = str(alias_spec.get("provider") or provider).strip()
        normalized_alias = normalize_text(alias)
        if not alias or not alias_type or not alias_provider or normalized_alias in seen_aliases:
            continue
        seen_aliases.add(normalized_alias)
        conn.execute(
            """
            INSERT INTO series_aliases
            (series_id, alias, normalized_alias, language, alias_type,
             provider, confidence, verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series_id,
                alias,
                normalized_alias,
                alias_spec.get("language"),
                alias_type,
                alias_provider,
                float(alias_spec.get("confidence", confidence)),
                int(alias_spec.get("verified", verified)),
            ),
        )
    return series_id


def set_candidate_review(
    conn: sqlite3.Connection,
    first_group_id: int,
    second_group_id: int,
    status: str,
) -> None:
    """Set a candidate decision, creating a manual-only candidate if necessary."""
    left_group_id, right_group_id = sorted((first_group_id, second_group_id))
    existing = conn.execute(
        """
        SELECT 1 FROM identity_match_candidates
        WHERE left_group_id = ? AND right_group_id = ?
        """,
        (left_group_id, right_group_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE identity_match_candidates SET review_status = ?
            WHERE left_group_id = ? AND right_group_id = ?
            """,
            (status, left_group_id, right_group_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO identity_match_candidates
            (left_group_id, right_group_id, reasons, confidence, review_status)
            VALUES (?, ?, 'manual_override', 1.0, ?)
            """,
            (left_group_id, right_group_id, status),
        )


def apply_catalog_overrides(
    conn: sqlite3.Connection,
    overrides: dict[str, Any],
    series_ids: dict[str, int],
    group_ids: dict[str, int],
) -> dict[str, Any]:
    """Apply reviewed metadata decisions without touching any source prompt field."""
    report: dict[str, Any] = {
        "series_definitions": len(overrides["series"]),
        "record_decisions": 0,
        "accepted_same_variant_relations": 0,
        "variation_relations": 0,
        "rejected_candidate_pairs": 0,
        "reviewed_exclusive_by_source": {},
        "decision_keys": [],
    }
    reviewed_exclusive: Counter[str] = Counter()
    seen_override_keys: set[str] = set()
    seen_source_records: set[int] = set()

    for decision in overrides["records"]:
        if not isinstance(decision, dict):
            raise BuildError("Every record override must be an object")
        source = str(decision.get("source") or "").strip()
        match_key = normalize_text(str(decision.get("match_key") or ""))
        override_key = str(decision.get("override_key") or f"{source}:{match_key}").strip()
        series_source_tag = str(decision.get("series_source_tag") or "").strip()
        action = str(decision.get("identity_action") or "").strip()
        notes = str(decision.get("notes") or "").strip()
        if source not in SOURCE_BITS or not match_key or not override_key or not notes:
            raise BuildError(f"Incomplete record override: {override_key or '<unknown>'}")
        if override_key in seen_override_keys:
            raise BuildError(f"Duplicate record override key: {override_key}")
        if action not in {"keep_distinct", "same_variant"}:
            raise BuildError(f"Invalid identity action for {override_key}: {action}")
        series_id = series_ids.get(series_source_tag)
        if series_id is None:
            raise BuildError(f"Unknown series '{series_source_tag}' in {override_key}")

        rows = conn.execute(
            """
            SELECT id, exact_group_id, prompt_sha256
            FROM source_records WHERE source = ? AND match_key = ?
            """,
            (source, match_key),
        ).fetchall()
        if len(rows) != 1:
            raise BuildError(
                f"Override {override_key} matched {len(rows)} source records instead of one"
            )
        source_record_id = int(rows[0]["id"])
        group_id = int(rows[0]["exact_group_id"])
        prompt_sha256_before = rows[0]["prompt_sha256"]
        if source_record_id in seen_source_records:
            raise BuildError(f"Multiple overrides target source record {source_record_id}")

        reviewed_source = decision.get("reviewed_exclusive_source")
        if reviewed_source is not None:
            reviewed_source = str(reviewed_source).strip()
        if action == "keep_distinct":
            group_sources = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT source FROM source_records WHERE exact_group_id = ?",
                    (group_id,),
                ).fetchall()
            }
            if reviewed_source != source or group_sources != {source}:
                raise BuildError(
                    f"Reviewed exclusivity for {override_key} conflicts with group sources"
                )
            conn.execute(
                """
                UPDATE exact_identity_groups
                SET reviewed_exclusive_source = ?, resolution_status = 'manual_distinct'
                WHERE id = ?
                """,
                (reviewed_source, group_id),
            )
            reviewed_exclusive[reviewed_source] += 1
        else:
            if reviewed_source is not None:
                raise BuildError(f"Same-variant override cannot be exclusive: {override_key}")
            merge_key = normalize_text(str(decision.get("merge_with_match_key") or ""))
            merge_group_id = group_ids.get(merge_key)
            if merge_group_id is None or merge_group_id == group_id:
                raise BuildError(f"Invalid merge target for {override_key}: {merge_key}")
            set_candidate_review(
                conn,
                group_id,
                merge_group_id,
                "accepted_manual_same_variant",
            )
            conn.execute(
                """
                UPDATE exact_identity_groups
                SET reviewed_exclusive_source = NULL,
                    resolution_status = 'manual_same_variant'
                WHERE id IN (?, ?)
                """,
                (group_id, merge_group_id),
            )
            report["accepted_same_variant_relations"] += 1

        conn.execute(
            """
            UPDATE source_records
            SET series_id = ?, series_resolution = 'manual_catalog_override',
                series_confidence = 1.0
            WHERE id = ?
            """,
            (series_id, source_record_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO manual_review_decisions
            (override_key, source_record_id, series_id, identity_action,
             reviewed_exclusive_source, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (override_key, source_record_id, series_id, action, reviewed_source, notes),
        )
        decision_id = int(cursor.lastrowid)

        if action == "same_variant":
            merge_group_id = group_ids[normalize_text(decision["merge_with_match_key"])]
            conn.execute(
                """
                INSERT INTO identity_relations
                (subject_group_id, object_group_id, relation_type, decision_id)
                VALUES (?, ?, 'same_variant', ?)
                """,
                (group_id, merge_group_id, decision_id),
            )

        rejected_keys = decision.get("reject_match_keys", [])
        if not isinstance(rejected_keys, list):
            raise BuildError(f"reject_match_keys must be a list in {override_key}")
        for rejected_key_raw in rejected_keys:
            rejected_key = normalize_text(str(rejected_key_raw))
            rejected_group_id = group_ids.get(rejected_key)
            if rejected_group_id is None or rejected_group_id == group_id:
                raise BuildError(f"Invalid rejected match in {override_key}: {rejected_key}")
            set_candidate_review(
                conn,
                group_id,
                rejected_group_id,
                "rejected_manual_distinct",
            )
            conn.execute(
                """
                INSERT INTO identity_relations
                (subject_group_id, object_group_id, relation_type, decision_id)
                VALUES (?, ?, 'different_identity', ?)
                """,
                (group_id, rejected_group_id, decision_id),
            )
            report["rejected_candidate_pairs"] += 1

        variation_key_raw = decision.get("variation_of_match_key")
        if variation_key_raw:
            variation_key = normalize_text(str(variation_key_raw))
            variation_group_id = group_ids.get(variation_key)
            if variation_group_id is None or variation_group_id == group_id:
                raise BuildError(f"Invalid variation target in {override_key}: {variation_key}")
            conn.execute(
                """
                INSERT INTO identity_relations
                (subject_group_id, object_group_id, relation_type, decision_id)
                VALUES (?, ?, 'variation_of', ?)
                """,
                (group_id, variation_group_id, decision_id),
            )
            report["variation_relations"] += 1

        prompt_sha256_after = conn.execute(
            "SELECT prompt_sha256 FROM source_records WHERE id = ?",
            (source_record_id,),
        ).fetchone()[0]
        if prompt_sha256_after != prompt_sha256_before:
            raise BuildError(f"Prompt changed while applying override {override_key}")

        seen_override_keys.add(override_key)
        seen_source_records.add(source_record_id)
        report["record_decisions"] += 1
        report["decision_keys"].append(override_key)

    report["reviewed_exclusive_by_source"] = dict(sorted(reviewed_exclusive.items()))
    return report


def import_safe_search_aliases(
    conn: sqlite3.Connection,
    alias_cache: dict[str, Any] | None,
    group_ids: dict[str, int],
    series_ids: dict[str, int],
) -> dict[str, Any]:
    """Import only antecedent search terms whose canonical consequent already exists."""
    if alias_cache is None:
        return {
            "enabled": False,
            "cache_records": 0,
            "imported_by_target_type": {},
            "skipped_by_reason": {},
            "identity_merges_applied": 0,
            "canonical_direction": "antecedent_to_consequent",
        }

    aliases = alias_cache["aliases"]
    series_by_normalized = {
        normalize_text(source_tag): series_id
        for source_tag, series_id in series_ids.items()
    }
    consequents_by_antecedent: dict[tuple[int, str], set[str]] = defaultdict(set)
    for row in aliases:
        category = int(row["category"])
        antecedent = normalize_text(str(row["antecedent_name"]))
        consequent = normalize_text(str(row["consequent_name"]))
        consequents_by_antecedent[(category, antecedent)].add(consequent)

    imported: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for row in aliases:
        category = int(row["category"])
        target_type = "character" if category == 4 else "series"
        antecedent_raw = str(row["antecedent_name"]).strip()
        consequent_raw = str(row["consequent_name"]).strip()
        antecedent = normalize_text(antecedent_raw)
        consequent = normalize_text(consequent_raw)

        if len(consequents_by_antecedent[(category, antecedent)]) > 1:
            skipped["ambiguous_antecedent"] += 1
            continue
        target_lookup = group_ids if target_type == "character" else series_by_normalized
        antecedent_id = target_lookup.get(antecedent)
        consequent_id = target_lookup.get(consequent)
        if consequent_id is None:
            skipped["canonical_target_missing"] += 1
            continue
        if antecedent_id is not None:
            if antecedent_id == consequent_id:
                skipped["already_same_catalog_target"] += 1
            else:
                skipped["connects_existing_catalog_targets"] += 1
            continue

        if target_type == "character":
            existing = conn.execute(
                "SELECT exact_group_id FROM character_aliases WHERE normalized_alias = ?",
                (antecedent,),
            ).fetchone()
            if existing:
                reason = (
                    "already_searchable"
                    if int(existing[0]) == consequent_id
                    else "search_alias_target_conflict"
                )
                skipped[reason] += 1
                continue
            conn.execute(
                """
                INSERT INTO character_aliases
                (exact_group_id, alias_raw, normalized_alias, canonical_tag_raw,
                 canonical_normalized, alias_type, provider, confidence, verified,
                 direction)
                VALUES (?, ?, ?, ?, ?, 'official_search_alias',
                        'danbooru_public_api', 1.0, 1,
                        'antecedent_to_consequent')
                """,
                (
                    consequent_id,
                    antecedent_raw,
                    antecedent,
                    consequent_raw,
                    consequent,
                ),
            )
        else:
            existing_series_ids = {
                int(existing[0])
                for existing in conn.execute(
                    "SELECT series_id FROM series_aliases WHERE normalized_alias = ?",
                    (antecedent,),
                ).fetchall()
            }
            if existing_series_ids:
                reason = (
                    "already_searchable"
                    if existing_series_ids == {consequent_id}
                    else "search_alias_target_conflict"
                )
                skipped[reason] += 1
                continue
            conn.execute(
                """
                INSERT INTO series_aliases
                (series_id, alias, normalized_alias, language, alias_type,
                 provider, confidence, verified)
                VALUES (?, ?, ?, NULL, 'official_search_alias',
                        'danbooru_public_api', 1.0, 1)
                """,
                (consequent_id, antecedent_raw, antecedent),
            )
        imported[target_type] += 1

    return {
        "enabled": True,
        "cache_records": len(aliases),
        "imported_by_target_type": dict(sorted(imported.items())),
        "imported_total": sum(imported.values()),
        "skipped_by_reason": dict(sorted(skipped.items())),
        "identity_merges_applied": 0,
        "canonical_direction": "antecedent_to_consequent",
        "canonical_output_policy": (
            "Aliases are accepted only as search input; the official consequent "
            "remains the canonical catalogue target."
        ),
    }


def enrich_series_titles(
    conn: sqlite3.Connection,
    anidb_titles: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach AniDB titles only when an exact normalized match has one strong winner."""
    total_series = int(conn.execute("SELECT COUNT(*) FROM series").fetchone()[0])
    if anidb_titles is None:
        return {
            "enabled": False,
            "provider": None,
            "cache_anime_records": 0,
            "cache_title_records": 0,
            "accepted_series": 0,
            "ambiguous_series": 0,
            "below_threshold_series": 0,
            "alias_only_review_series": 0,
            "unresolved_series": total_series,
            "candidate_rows": 0,
            "stored_title_rows": 0,
            "imported_search_aliases": 0,
            "matched_by_title_type": {},
            "matched_by_catalog_alias_type": {},
            "populated_summary_fields": {},
            "ambiguous_samples": [],
            "alias_only_review_samples": [],
            "identity_merges_applied": 0,
        }

    anime_by_aid: dict[int, list[dict[str, Any]]] = anidb_titles["anime_by_aid"]
    title_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for aid, titles in anime_by_aid.items():
        for title in titles:
            if title["title_type"] not in ANIDB_MATCH_TITLE_TYPES:
                continue
            title_index[title["normalized_title"]].append(
                {
                    **title,
                    "aid": aid,
                }
            )

    series_rows = conn.execute(
        """
        SELECT s.id, s.source_copyright_tag, a.alias, a.normalized_alias,
               a.alias_type
        FROM series s
        JOIN series_aliases a ON a.series_id = s.id
        WHERE a.verified = 1
        ORDER BY s.id, a.id
        """
    ).fetchall()
    aliases_by_series: dict[int, list[sqlite3.Row]] = defaultdict(list)
    source_tags_by_series: dict[int, str] = {}
    for row in series_rows:
        series_id = int(row["id"])
        aliases_by_series[series_id].append(row)
        source_tags_by_series[series_id] = str(row["source_copyright_tag"])

    accepted_count = 0
    ambiguous_count = 0
    below_threshold_count = 0
    alias_only_review_count = 0
    unresolved_count = total_series - len(aliases_by_series)
    candidate_rows = 0
    stored_title_rows = 0
    imported_search_aliases = 0
    matched_by_title_type: Counter[str] = Counter()
    matched_by_catalog_alias_type: Counter[str] = Counter()
    populated_summary_fields: Counter[str] = Counter()
    ambiguous_samples: list[dict[str, Any]] = []
    alias_only_review_samples: list[dict[str, Any]] = []
    alias_type_priority = {
        "source_tag": 0,
        "manual_alias": 1,
        "official_search_alias": 2,
        "humanized_source_tag": 3,
    }

    for series_id in sorted(aliases_by_series):
        best_by_aid: dict[int, dict[str, Any]] = {}
        best_source_by_aid: dict[int, dict[str, Any]] = {}
        for alias_row in aliases_by_series[series_id]:
            for provider_title in title_index.get(alias_row["normalized_alias"], []):
                candidate = {
                    "aid": int(provider_title["aid"]),
                    "matched_catalog_alias": str(alias_row["alias"]),
                    "matched_catalog_alias_type": str(alias_row["alias_type"]),
                    "matched_provider_title": str(provider_title["title"]),
                    "matched_provider_language": str(provider_title["language"]),
                    "matched_provider_title_type": str(provider_title["title_type"]),
                    "confidence": ANIDB_MATCH_CONFIDENCE[
                        str(provider_title["title_type"])
                    ],
                }
                candidate_key = (
                    -candidate["confidence"],
                    alias_type_priority.get(
                        candidate["matched_catalog_alias_type"],
                        10,
                    ),
                    normalize_text(candidate["matched_catalog_alias"]),
                    candidate["matched_provider_language"],
                    candidate["matched_provider_title"],
                )
                existing = best_by_aid.get(candidate["aid"])
                if existing is None or candidate_key < existing["_sort_key"]:
                    candidate["_sort_key"] = candidate_key
                    best_by_aid[candidate["aid"]] = candidate
                if alias_row["alias_type"] == "source_tag":
                    existing_source = best_source_by_aid.get(candidate["aid"])
                    if (
                        existing_source is None
                        or candidate_key < existing_source["_sort_key"]
                    ):
                        best_source_by_aid[candidate["aid"]] = candidate

        if not best_by_aid:
            unresolved_count += 1
            continue

        if not best_source_by_aid:
            top_confidence = max(
                candidate["confidence"] for candidate in best_by_aid.values()
            )
            alias_only_review_count += 1
            conn.execute(
                """
                UPDATE series
                SET title_resolution = 'alias_only_review', title_confidence = ?
                WHERE id = ?
                """,
                (top_confidence, series_id),
            )
            for aid, candidate in sorted(best_by_aid.items()):
                conn.execute(
                    """
                    INSERT INTO series_title_matches
                    (series_id, provider, provider_series_id,
                     matched_catalog_alias, matched_catalog_alias_type,
                     matched_provider_title, matched_provider_language,
                     matched_provider_title_type, confidence, resolution_status)
                    VALUES (?, 'anidb_title_dump', ?, ?, ?, ?, ?, ?, ?,
                            'alias_only_review')
                    """,
                    (
                        series_id,
                        str(aid),
                        candidate["matched_catalog_alias"],
                        candidate["matched_catalog_alias_type"],
                        candidate["matched_provider_title"],
                        candidate["matched_provider_language"],
                        candidate["matched_provider_title_type"],
                        candidate["confidence"],
                    ),
                )
                candidate_rows += 1
            if len(alias_only_review_samples) < 20:
                alias_only_review_samples.append(
                    {
                        "source_copyright_tag": source_tags_by_series[series_id],
                        "candidate_aids": sorted(best_by_aid),
                        "matched_aliases": sorted(
                            {
                                candidate["matched_catalog_alias"]
                                for candidate in best_by_aid.values()
                            },
                            key=normalize_text,
                        ),
                    }
                )
            continue

        top_confidence = max(
            candidate["confidence"] for candidate in best_source_by_aid.values()
        )
        top_aids = sorted(
            aid
            for aid, candidate in best_source_by_aid.items()
            if candidate["confidence"] == top_confidence
        )
        accepted_aid: int | None = None
        if top_confidence < ANIDB_ACCEPTANCE_THRESHOLD:
            resolution = "below_threshold"
            below_threshold_count += 1
        elif len(top_aids) != 1:
            resolution = "ambiguous_exact_match"
            ambiguous_count += 1
            if len(ambiguous_samples) < 20:
                ambiguous_samples.append(
                    {
                        "source_copyright_tag": source_tags_by_series[series_id],
                        "confidence": top_confidence,
                        "candidate_aids": top_aids,
                        "matched_titles": [
                            best_by_aid[aid]["matched_provider_title"]
                            for aid in top_aids
                        ],
                    }
                )
        else:
            resolution = "accepted_exact_unique"
            accepted_aid = top_aids[0]
            accepted_count += 1

        for aid, best_candidate in sorted(best_by_aid.items()):
            source_candidate = best_source_by_aid.get(aid)
            candidate = source_candidate or best_candidate
            if source_candidate is None:
                candidate_status = "alias_only_review"
            elif accepted_aid == aid:
                candidate_status = "accepted_exact_unique"
            elif aid in top_aids:
                candidate_status = resolution
            else:
                candidate_status = "superseded_lower_confidence"
            conn.execute(
                """
                INSERT INTO series_title_matches
                (series_id, provider, provider_series_id,
                 matched_catalog_alias, matched_catalog_alias_type,
                 matched_provider_title, matched_provider_language,
                 matched_provider_title_type, confidence, resolution_status)
                VALUES (?, 'anidb_title_dump', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    series_id,
                    str(aid),
                    candidate["matched_catalog_alias"],
                    candidate["matched_catalog_alias_type"],
                    candidate["matched_provider_title"],
                    candidate["matched_provider_language"],
                    candidate["matched_provider_title_type"],
                    candidate["confidence"],
                    candidate_status,
                ),
            )
            candidate_rows += 1

        conn.execute(
            """
            UPDATE series SET title_resolution = ?, title_confidence = ?
            WHERE id = ?
            """,
            (resolution, top_confidence, series_id),
        )
        if accepted_aid is None:
            continue

        accepted_match = best_source_by_aid[accepted_aid]
        matched_by_title_type[accepted_match["matched_provider_title_type"]] += 1
        matched_by_catalog_alias_type[
            accepted_match["matched_catalog_alias_type"]
        ] += 1
        accepted_titles = anime_by_aid[accepted_aid]

        def select_summary_title(language: str, title_type: str) -> str | None:
            values = sorted(
                {
                    title["title"]
                    for title in accepted_titles
                    if title["language"] == language
                    and title["title_type"] == title_type
                },
                key=lambda value: (normalize_text(value), value),
            )
            return values[0] if values else None

        main_title = next(
            title for title in accepted_titles if title["title_type"] == "main"
        )
        title_original_transcription = str(main_title["title"])
        title_original_language = str(main_title["language"])
        title_romaji = (
            title_original_transcription
            if title_original_language == "x-jat"
            else None
        )
        title_english = select_summary_title("en", "official")
        title_native = (
            select_summary_title("ja", "official")
            if title_original_language == "x-jat"
            else None
        )
        conn.execute(
            """
            UPDATE series
            SET title_original_transcription =
                    COALESCE(title_original_transcription, ?),
                title_original_language = COALESCE(title_original_language, ?),
                title_romaji = COALESCE(title_romaji, ?),
                title_english = COALESCE(title_english, ?),
                title_native = COALESCE(title_native, ?)
            WHERE id = ?
            """,
            (
                title_original_transcription,
                title_original_language,
                title_romaji,
                title_english,
                title_native,
                series_id,
            ),
        )
        for field_name, value in (
            ("title_original_transcription", title_original_transcription),
            ("title_romaji", title_romaji),
            ("title_english", title_english),
            ("title_native", title_native),
        ):
            if value:
                populated_summary_fields[field_name] += 1

        for title in accepted_titles:
            if title["language"] not in ANIDB_SEARCH_LANGUAGES:
                continue
            conn.execute(
                """
                INSERT INTO series_titles
                (series_id, title, normalized_title, language, title_type,
                 provider, provider_series_id, confidence, verified)
                VALUES (?, ?, ?, ?, ?, 'anidb_title_dump', ?, ?, 1)
                """,
                (
                    series_id,
                    title["title"],
                    title["normalized_title"],
                    title["language"],
                    title["title_type"],
                    str(accepted_aid),
                    top_confidence,
                ),
            )
            stored_title_rows += 1
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO series_aliases
                (series_id, alias, normalized_alias, language, alias_type,
                 provider, confidence, verified)
                VALUES (?, ?, ?, ?, ?, 'anidb_title_dump', ?, 1)
                """,
                (
                    series_id,
                    title["title"],
                    title["normalized_title"],
                    title["language"],
                    f"anidb_{title['title_type']}",
                    top_confidence,
                ),
            )
            imported_search_aliases += max(cursor.rowcount, 0)

    return {
        "enabled": True,
        "provider": anidb_titles["provider"],
        "cache_anime_records": anidb_titles["anime_count"],
        "cache_title_records": anidb_titles["title_count"],
        "acceptance_threshold": ANIDB_ACCEPTANCE_THRESHOLD,
        "accepted_series": accepted_count,
        "ambiguous_series": ambiguous_count,
        "below_threshold_series": below_threshold_count,
        "alias_only_review_series": alias_only_review_count,
        "unresolved_series": unresolved_count,
        "candidate_rows": candidate_rows,
        "stored_title_rows": stored_title_rows,
        "imported_search_aliases": imported_search_aliases,
        "matched_by_title_type": dict(sorted(matched_by_title_type.items())),
        "matched_by_catalog_alias_type": dict(
            sorted(matched_by_catalog_alias_type.items())
        ),
        "populated_summary_fields": dict(sorted(populated_summary_fields.items())),
        "ambiguous_samples": ambiguous_samples,
        "alias_only_review_samples": alias_only_review_samples,
        "identity_merges_applied": 0,
        "association_policy": (
            "AniDB IDs are retained as title evidence only; they do not replace "
            "the Danbooru copyright key or assert franchise/season identity."
        ),
    }


def finalize_series_catalog(conn: sqlite3.Connection) -> dict[str, Any]:
    """Prefer the official English title while preserving every source alias."""
    conn.execute(
        """
        UPDATE series
        SET canonical_display_name = CASE
                WHEN TRIM(COALESCE(title_english, '')) != ''
                    THEN title_english
                WHEN TRIM(COALESCE(title_original_transcription, '')) != ''
                    THEN title_original_transcription
                ELSE provisional_display_name
            END,
            canonical_title_source = CASE
                WHEN TRIM(COALESCE(title_english, '')) != ''
                    THEN 'anidb_official_english'
                WHEN TRIM(COALESCE(title_original_transcription, '')) != ''
                    THEN 'anidb_original_transcription'
                ELSE 'source_tag'
            END
        """
    )
    return {
        "total": int(conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]),
        "using_official_english": int(
            conn.execute(
                """
                SELECT COUNT(*) FROM series
                WHERE canonical_title_source = 'anidb_official_english'
                """
            ).fetchone()[0]
        ),
        "using_original_transcription_fallback": int(
            conn.execute(
                """
                SELECT COUNT(*) FROM series
                WHERE canonical_title_source = 'anidb_original_transcription'
                """
            ).fetchone()[0]
        ),
        "using_source_tag_fallback": int(
            conn.execute(
                """
                SELECT COUNT(*) FROM series
                WHERE canonical_title_source = 'source_tag'
                """
            ).fetchone()[0]
        ),
        "by_scope": {
            row["series_scope"]: int(row["record_count"])
            for row in conn.execute(
                """
                SELECT series_scope, COUNT(*) AS record_count
                FROM series GROUP BY series_scope ORDER BY series_scope
                """
            ).fetchall()
        },
    }


class _DisjointSet:
    """Small deterministic union-find used only while materializing the catalogue."""

    def __init__(self, values: Iterable[int]):
        self._parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        lower, higher = sorted((left_root, right_root))
        self._parent[higher] = lower


def _choose_display_name(
    records: list[sqlite3.Row],
    canonical_group_id: int,
    fallback: str,
) -> str:
    """Prefer the curated Anima label while retaining deterministic fallbacks."""
    display_source_order = {"anima": 0, "danbooru": 1, "e621": 2}
    candidates = [
        row
        for row in records
        if str(row["source_name_raw"] or "").strip()
    ]
    if not candidates:
        return humanize_source_tag(fallback)
    candidates.sort(
        key=lambda row: (
            display_source_order[str(row["source"])],
            0 if int(row["exact_group_id"]) == canonical_group_id else 1,
            int(row["id"]),
        )
    )
    return (
        str(candidates[0]["source_name_raw"])
        .replace("\\(", "(")
        .replace("\\)", ")")
        .strip()
    )


def _resolve_series_for_records(
    records: list[sqlite3.Row],
) -> tuple[int | None, str]:
    series_ids = {
        int(row["series_id"])
        for row in records
        if row["series_id"] is not None
    }
    if not series_ids:
        return None, "unresolved"
    if len(series_ids) == 1:
        return next(iter(series_ids)), "consistent"
    return None, "conflicting_source_metadata"


def _variation_exclusivity_status(
    sources: set[str],
    group_ids: set[int],
    group_rows: dict[int, sqlite3.Row],
) -> tuple[str | None, str]:
    if len(sources) != 1:
        return None, "multiple_sources"
    exclusive_source = next(iter(sources))
    reviewed_sources = {
        str(group_rows[group_id]["reviewed_exclusive_source"])
        for group_id in group_ids
        if group_rows[group_id]["reviewed_exclusive_source"] is not None
    }
    status = "reviewed" if reviewed_sources == {exclusive_source} else "provisional_exact"
    return exclusive_source, status


def materialize_canonical_catalog(conn: sqlite3.Connection) -> dict[str, Any]:
    """Materialize reviewed identity facts into the runtime three-layer model."""
    group_rows = {
        int(row["id"]): row
        for row in conn.execute(
            """
            SELECT id, match_key, source_count, reviewed_exclusive_source,
                   resolution_status
            FROM exact_identity_groups ORDER BY id
            """
        ).fetchall()
    }
    group_ids = sorted(group_rows)
    disjoint = _DisjointSet(group_ids)
    relations = conn.execute(
        """
        SELECT subject_group_id, object_group_id, relation_type
        FROM identity_relations
        WHERE relation_type IN ('same_variant', 'variation_of')
        ORDER BY subject_group_id, object_group_id, relation_type
        """
    ).fetchall()

    same_variant_targets: dict[int, set[int]] = defaultdict(set)
    for relation in relations:
        if relation["relation_type"] != "same_variant":
            continue
        subject = int(relation["subject_group_id"])
        target = int(relation["object_group_id"])
        disjoint.union(subject, target)
        same_variant_targets[subject].add(target)

    component_members: dict[int, set[int]] = defaultdict(set)
    component_by_group: dict[int, int] = {}
    for group_id in group_ids:
        component_id = disjoint.find(group_id)
        component_by_group[group_id] = component_id
        component_members[component_id].add(group_id)

    target_groups_by_component: dict[int, set[int]] = defaultdict(set)
    for subject, targets in same_variant_targets.items():
        component_id = component_by_group[subject]
        target_groups_by_component[component_id].update(targets)

    canonical_group_by_component: dict[int, int] = {}
    for component_id, members in component_members.items():
        preferred = target_groups_by_component.get(component_id, set()).intersection(members)
        candidates = preferred or members
        canonical_group_by_component[component_id] = min(
            candidates,
            key=lambda group_id: (
                -int(group_rows[group_id]["source_count"]),
                str(group_rows[group_id]["match_key"]),
            ),
        )

    parent_candidates: dict[int, set[int]] = defaultdict(set)
    for relation in relations:
        if relation["relation_type"] != "variation_of":
            continue
        subject_component = component_by_group[int(relation["subject_group_id"])]
        object_component = component_by_group[int(relation["object_group_id"])]
        if subject_component == object_component:
            raise BuildError("A reviewed variation cannot also be the same exact variant")
        parent_candidates[subject_component].add(object_component)

    variation_parent: dict[int, int] = {}
    for component_id, candidates in parent_candidates.items():
        if len(candidates) != 1:
            keys = [
                str(group_rows[canonical_group_by_component[item]]["match_key"])
                for item in sorted(candidates)
            ]
            raise BuildError(
                "A reviewed variation has multiple canonical parents: "
                f"{component_id} -> {keys}"
            )
        variation_parent[component_id] = next(iter(candidates))

    def family_root(component_id: int) -> int:
        visited: set[int] = set()
        current = component_id
        while current in variation_parent:
            if current in visited:
                raise BuildError("Cycle detected in reviewed character variations")
            visited.add(current)
            current = variation_parent[current]
        return current

    family_members: dict[int, set[int]] = defaultdict(set)
    for component_id in component_members:
        family_members[family_root(component_id)].add(component_id)

    source_records = conn.execute(
        """
        SELECT id, exact_group_id, source, provider, source_name_raw,
               source_tag_raw, canonical_tag_raw, series_id, prompt_sha256,
               image_url, rank, reference_count
        FROM source_records ORDER BY id
        """
    ).fetchall()
    records_by_component: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for record in source_records:
        component_id = component_by_group[int(record["exact_group_id"])]
        records_by_component[component_id].append(record)

    variation_combinations: Counter[str] = Counter()
    variation_exclusive: Counter[str] = Counter()
    exclusivity_statuses: Counter[str] = Counter()
    series_resolution_counts: Counter[str] = Counter()
    manual_variation_families = 0

    sorted_families = sorted(
        family_members.items(),
        key=lambda item: str(
            group_rows[canonical_group_by_component[item[0]]]["match_key"]
        ),
    )
    for root_component, variation_components in sorted_families:
        root_group_id = canonical_group_by_component[root_component]
        root_key = str(group_rows[root_group_id]["match_key"])
        root_records = records_by_component[root_component]
        character_records = [
            record
            for component_id in variation_components
            for record in records_by_component[component_id]
        ]
        character_sources = {str(record["source"]) for record in character_records}
        character_series_id, _ = _resolve_series_for_records(root_records)
        character_exclusive_source = (
            next(iter(character_sources)) if len(character_sources) == 1 else None
        )
        if len(character_sources) > 1:
            character_exclusivity_status = "multiple_sources"
        elif len(variation_components) > 1:
            character_exclusivity_status = "provisional_variation_family"
        else:
            only_groups = component_members[root_component]
            _, variation_status = _variation_exclusivity_status(
                character_sources,
                only_groups,
                group_rows,
            )
            character_exclusivity_status = variation_status

        character_display_name = _choose_display_name(
            root_records,
            root_group_id,
            root_key,
        )
        character_resolution = (
            "manual_variation_family"
            if len(variation_components) > 1
            else (
                "manual_same_variant"
                if len(component_members[root_component]) > 1
                else "exact_tag_only"
            )
        )
        cursor = conn.execute(
            """
            INSERT INTO canonical_characters
            (canonical_key, display_name, normalized_display_name,
             default_variation_group_id, primary_series_id, source_mask,
             source_count, exclusive_source, exclusivity_status,
             variation_count, resolution_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                root_key,
                character_display_name,
                normalize_text(character_display_name),
                root_group_id,
                character_series_id,
                source_mask(character_sources),
                len(character_sources),
                character_exclusive_source,
                character_exclusivity_status,
                len(variation_components),
                character_resolution,
            ),
        )
        character_id = int(cursor.lastrowid)
        if len(variation_components) > 1:
            manual_variation_families += 1

        sorted_variations = sorted(
            variation_components,
            key=lambda component_id: (
                0 if component_id == root_component else 1,
                str(
                    group_rows[canonical_group_by_component[component_id]][
                        "match_key"
                    ]
                ),
            ),
        )
        for component_id in sorted_variations:
            canonical_group_id = canonical_group_by_component[component_id]
            variation_key = str(group_rows[canonical_group_id]["match_key"])
            records = records_by_component[component_id]
            sources = {str(record["source"]) for record in records}
            members = component_members[component_id]
            exclusive_source, exclusivity_status = _variation_exclusivity_status(
                sources,
                members,
                group_rows,
            )
            variation_series_id, series_resolution = _resolve_series_for_records(records)
            variation_display_name = _choose_display_name(
                records,
                canonical_group_id,
                variation_key,
            )
            is_default = component_id == root_component
            if not is_default and len(members) > 1:
                resolution_status = "manual_variation_same_variant"
            elif not is_default:
                resolution_status = "manual_variation"
            elif len(members) > 1:
                resolution_status = "manual_same_variant"
            else:
                resolution_status = "exact_tag_only"

            cursor = conn.execute(
                """
                INSERT INTO character_variations
                (character_id, canonical_group_id, variation_key, display_name,
                 normalized_display_name, series_id, series_resolution, is_default,
                 source_mask, source_count, exclusive_source, exclusivity_status,
                 resolution_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    character_id,
                    canonical_group_id,
                    variation_key,
                    variation_display_name,
                    normalize_text(variation_display_name),
                    variation_series_id,
                    series_resolution,
                    int(is_default),
                    source_mask(sources),
                    len(sources),
                    exclusive_source,
                    exclusivity_status,
                    resolution_status,
                ),
            )
            variation_id = int(cursor.lastrowid)
            series_resolution_counts[series_resolution] += 1
            variation_combinations[source_combination(sources)] += 1
            exclusivity_statuses[exclusivity_status] += 1
            if exclusive_source:
                variation_exclusive[exclusive_source] += 1

            conn.executemany(
                """
                INSERT INTO variation_identity_groups(variation_id, exact_group_id)
                VALUES (?, ?)
                """,
                [(variation_id, group_id) for group_id in sorted(members)],
            )

            records_by_source: dict[str, sqlite3.Row] = {}
            for record in records:
                source = str(record["source"])
                if source in records_by_source:
                    raise BuildError(
                        "A reviewed same-variant merge produced multiple "
                        f"{source} representations for {variation_key}"
                    )
                records_by_source[source] = record
            ordered_sources = [
                source for source in SOURCE_ORDER if source in records_by_source
            ]
            for display_order, source in enumerate(ordered_sources):
                record = records_by_source[source]
                conn.execute(
                    """
                    INSERT INTO character_representations
                    (variation_id, source_record_id, source, display_order, is_default)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        variation_id,
                        int(record["id"]),
                        source,
                        display_order,
                        int(display_order == 0),
                    ),
                )

            # Canonical names, source tags, and prompt tags are queried directly
            # from their authoritative tables at runtime. Only terms that do not
            # otherwise exist in the runtime model are duplicated here.
            term_specs: list[tuple[str, str, str, str | None, int]] = []
            for group_id in sorted(members):
                if group_id == canonical_group_id:
                    continue
                term_specs.append(
                    (
                        str(group_rows[group_id]["match_key"]),
                        "identity_group",
                        "catalog_v2",
                        None,
                        1,
                    )
                )
            placeholders = ",".join("?" for _ in members)
            alias_rows = conn.execute(
                f"""
                SELECT alias_raw, alias_type, provider, verified
                FROM character_aliases
                WHERE exact_group_id IN ({placeholders})
                ORDER BY id
                """,
                tuple(sorted(members)),
            ).fetchall()
            for alias in alias_rows:
                term_specs.append(
                    (
                        str(alias["alias_raw"]),
                        str(alias["alias_type"]),
                        str(alias["provider"]),
                        None,
                        int(alias["verified"]),
                    )
                )

            seen_terms: set[tuple[str, str, str]] = set()
            for term_raw, term_type, provider, source, verified in term_specs:
                normalized_term = normalize_text(term_raw)
                dedupe_key = (normalized_term, term_type, provider)
                if not normalized_term or dedupe_key in seen_terms:
                    continue
                seen_terms.add(dedupe_key)
                conn.execute(
                    """
                    INSERT INTO character_search_terms
                    (variation_id, term_raw, normalized_term, term_type,
                     provider, source, verified)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        variation_id,
                        term_raw,
                        normalized_term,
                        term_type,
                        provider,
                        source,
                        verified,
                    ),
                )

    source_record_count = int(
        conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
    )
    representation_count = int(
        conn.execute("SELECT COUNT(*) FROM character_representations").fetchone()[0]
    )
    if representation_count != source_record_count:
        raise BuildError(
            "Canonical materialization lost source records: "
            f"records={source_record_count}, representations={representation_count}"
        )
    if conn.execute(
        """
        SELECT 1
        FROM character_representations cr
        JOIN source_records sr ON sr.id = cr.source_record_id
        WHERE cr.source != sr.source
        LIMIT 1
        """
    ).fetchone():
        raise BuildError("A representation source does not match its immutable source record")

    foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise BuildError(f"Foreign-key audit failed: {foreign_key_errors[:5]}")
    integrity_result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity_result != "ok":
        raise BuildError(f"SQLite integrity audit failed: {integrity_result}")

    return {
        "characters": int(
            conn.execute("SELECT COUNT(*) FROM canonical_characters").fetchone()[0]
        ),
        "variations": int(
            conn.execute("SELECT COUNT(*) FROM character_variations").fetchone()[0]
        ),
        "representations": representation_count,
        "search_terms": int(
            conn.execute("SELECT COUNT(*) FROM character_search_terms").fetchone()[0]
        ),
        "manual_variation_families": manual_variation_families,
        "variations_by_source_combination": dict(sorted(variation_combinations.items())),
        "variation_exclusive_by_source": dict(sorted(variation_exclusive.items())),
        "exclusivity_statuses": dict(sorted(exclusivity_statuses.items())),
        "series_resolution": dict(sorted(series_resolution_counts.items())),
        "audits": {
            "source_records_mapped_exactly_once": representation_count,
            "foreign_key_errors": 0,
            "sqlite_integrity": integrity_result,
        },
        "warning": (
            "Exclusivity marked provisional_exact can change when pending identity "
            "or variation reviews are accepted."
        ),
    }


def build_catalog(
    current_db: Path,
    anima_csv: Path,
    output: Path,
    report_path: Path,
    overrides_path: Path | None = None,
    alias_cache_path: Path | None = None,
    anidb_titles_path: Path | None = None,
) -> dict[str, Any]:
    current_db = current_db.resolve()
    anima_csv = anima_csv.resolve()
    output = output.resolve()
    report_path = report_path.resolve()
    if overrides_path is not None:
        overrides_path = overrides_path.resolve()
    if alias_cache_path is not None:
        alias_cache_path = alias_cache_path.resolve()
    if anidb_titles_path is not None:
        anidb_titles_path = anidb_titles_path.resolve()

    if not current_db.exists():
        raise BuildError(f"Current character DB not found: {current_db}")
    if not anima_csv.exists():
        raise BuildError(f"Anima CSV not found: {anima_csv}")
    input_paths = {current_db, anima_csv}
    if overrides_path is not None:
        input_paths.add(overrides_path)
    if alias_cache_path is not None:
        input_paths.add(alias_cache_path)
    if anidb_titles_path is not None:
        input_paths.add(anidb_titles_path)
    if output in input_paths:
        raise BuildError("Refusing to overwrite a catalogue input with the database output")
    if report_path in input_paths | {output}:
        raise BuildError("Refusing to overwrite an input or database output with the report")

    current_records = read_current_records(current_db)
    anima_records = read_anima_records(anima_csv)
    overrides = read_catalog_overrides(overrides_path)
    alias_cache = read_official_alias_cache(alias_cache_path)
    anidb_titles = read_anidb_title_dump(anidb_titles_path)
    matched_anima, prompt_validation = validate_anima_prompts(
        current_records,
        anima_records,
    )

    copyright_by_match_key: dict[str, set[str]] = defaultdict(set)
    for record in anima_records:
        if record["copyright"]:
            copyright_by_match_key[record["match_key"]].add(record["copyright"])

    staged_records: list[dict[str, Any]] = []
    for current in current_records:
        if current["source"] == "anima":
            continue
        prompt_raw = current.get("tags") or ""
        source_tag_raw = extract_source_tag(prompt_raw)
        staged_records.append(
            {
                "legacy_id": current["id"],
                "provider": "downloadmost",
                "source": current["source"],
                "source_name_raw": current.get("name") or source_tag_raw,
                "source_character_key_raw": None,
                "source_tag_raw": source_tag_raw,
                "canonical_tag_raw": current.get("danbooru_tag"),
                "match_key": normalize_text(source_tag_raw),
                "prompt_raw": prompt_raw,
                "trigger_raw": None,
                "core_tags_raw": None,
                "copyright_tag_raw": None,
                "current_series_raw": current.get("series"),
                "image_url": current.get("image_url"),
                "source_url": None,
                "rank": current.get("rank"),
                "reference_count": None,
                "prompt_verified": 1,
            }
        )

    for anima in anima_records:
        current = matched_anima[anima["match_key"]]
        staged_records.append(
            {
                "legacy_id": current["id"],
                "provider": "animadex",
                "source": "anima",
                "source_name_raw": current.get("name") or anima["character"],
                "source_character_key_raw": anima["character"],
                "source_tag_raw": anima["source_tag_raw"],
                "canonical_tag_raw": anima["trigger"],
                "match_key": anima["match_key"],
                "prompt_raw": anima["prompt_raw"],
                "trigger_raw": anima["trigger"],
                "core_tags_raw": anima["core_tags"],
                "copyright_tag_raw": anima["copyright"],
                "current_series_raw": current.get("series"),
                "image_url": current.get("image_url"),
                "source_url": anima["url"],
                "rank": current.get("rank"),
                "reference_count": anima["count"],
                "prompt_verified": 1,
            }
        )

    empty_prompts = [record for record in staged_records if not record["prompt_raw"]]
    empty_match_keys = [record for record in staged_records if not record["match_key"]]
    if empty_prompts or empty_match_keys:
        raise BuildError(
            f"Source validation failed: empty_prompts={len(empty_prompts)}, "
            f"empty_match_keys={len(empty_match_keys)}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    temp_report = report_path.with_suffix(report_path.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()
    if temp_report.exists():
        temp_report.unlink()

    conn = sqlite3.connect(temp_output)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        metadata = {
            "schema_version": str(BUILD_SCHEMA_VERSION),
            "current_db_sha256": sha256_file(current_db),
            "anima_csv_sha256": sha256_file(anima_csv),
        }
        if overrides_path is not None:
            metadata["catalog_overrides_sha256"] = sha256_file(overrides_path)
        if alias_cache_path is not None:
            metadata["official_alias_cache_sha256"] = sha256_file(alias_cache_path)
        if anidb_titles_path is not None:
            metadata["anidb_titles_sha256"] = sha256_file(anidb_titles_path)
        conn.executemany(
            "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )

        copyright_tags = sorted(
            {record["copyright"] for record in anima_records if record["copyright"]},
            key=normalize_text,
        )
        series_ids: dict[str, int] = {}
        for copyright_tag in copyright_tags:
            insert_series_definition(
                conn,
                series_ids,
                {
                    "source_copyright_tag": copyright_tag,
                    "provider": "animadex",
                    "confidence": 1.0,
                    "verified": True,
                },
            )

        for definition in overrides["series"]:
            if not isinstance(definition, dict):
                raise BuildError("Every manual series definition must be an object")
            insert_series_definition(conn, series_ids, definition)

        records_by_match_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in staged_records:
            records_by_match_key[record["match_key"]].append(record)

        group_ids: dict[str, int] = {}
        group_names: dict[int, set[str]] = defaultdict(set)
        group_match_keys: dict[int, str] = {}
        combination_counts: Counter[str] = Counter()
        provisional_exclusive_counts: Counter[str] = Counter()

        for match_key in sorted(records_by_match_key):
            sources = {record["source"] for record in records_by_match_key[match_key]}
            exclusive_source = next(iter(sources)) if len(sources) == 1 else None
            cursor = conn.execute(
                """
                INSERT INTO exact_identity_groups
                (match_key, source_mask, source_count, provisional_exclusive_source)
                VALUES (?, ?, ?, ?)
                """,
                (match_key, source_mask(sources), len(sources), exclusive_source),
            )
            group_id = int(cursor.lastrowid)
            group_ids[match_key] = group_id
            group_match_keys[group_id] = match_key
            combination_counts[source_combination(sources)] += 1
            if exclusive_source:
                provisional_exclusive_counts[exclusive_source] += 1

        resolved_series_by_source: Counter[str] = Counter()
        unresolved_series_by_source: Counter[str] = Counter()
        ambiguous_copyright_keys: dict[str, list[str]] = {}

        for record in staged_records:
            copyright_tag: str | None
            resolution: str
            confidence: float
            if record["source"] == "anima":
                copyright_tag = record["copyright_tag_raw"] or None
                resolution = "animadex_explicit_copyright" if copyright_tag else "unresolved"
                confidence = 1.0 if copyright_tag else 0.0
            else:
                copyright_candidates = copyright_by_match_key.get(record["match_key"], set())
                if len(copyright_candidates) == 1:
                    copyright_tag = next(iter(copyright_candidates))
                    resolution = "animadex_exact_source_tag"
                    confidence = 1.0
                else:
                    copyright_tag = None
                    resolution = "unresolved"
                    confidence = 0.0
                    if len(copyright_candidates) > 1:
                        ambiguous_copyright_keys[record["match_key"]] = sorted(
                            copyright_candidates
                        )

            series_id = series_ids.get(copyright_tag or "")
            if series_id:
                resolved_series_by_source[record["source"]] += 1
            else:
                unresolved_series_by_source[record["source"]] += 1

            group_id = group_ids[record["match_key"]]
            group_names[group_id].add(record["source_name_raw"])
            conn.execute(
                """
                INSERT INTO source_records
                (legacy_id, provider, source, source_name_raw,
                 source_character_key_raw, source_tag_raw, canonical_tag_raw,
                 match_key, prompt_raw, prompt_sha256, trigger_raw, core_tags_raw,
                 copyright_tag_raw, current_series_raw, image_url, source_url,
                 rank, reference_count, exact_group_id, series_id,
                 series_resolution, series_confidence, prompt_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?)
                """,
                (
                    record["legacy_id"],
                    record["provider"],
                    record["source"],
                    record["source_name_raw"],
                    record["source_character_key_raw"],
                    record["source_tag_raw"],
                    record["canonical_tag_raw"],
                    record["match_key"],
                    record["prompt_raw"],
                    sha256_text(record["prompt_raw"]),
                    record["trigger_raw"],
                    record["core_tags_raw"],
                    record["copyright_tag_raw"],
                    record["current_series_raw"],
                    record["image_url"],
                    record["source_url"],
                    record["rank"],
                    record["reference_count"],
                    group_id,
                    series_id,
                    resolution,
                    confidence,
                    record["prompt_verified"],
                ),
            )

        candidate_report = build_match_candidates(
            conn,
            group_names,
            group_match_keys,
        )
        override_report = apply_catalog_overrides(
            conn,
            overrides,
            series_ids,
            group_ids,
        )
        search_alias_report = import_safe_search_aliases(
            conn,
            alias_cache,
            group_ids,
            series_ids,
        )
        series_title_report = enrich_series_titles(conn, anidb_titles)
        series_catalog_report = finalize_series_catalog(conn)
        canonical_catalog_report = materialize_canonical_catalog(conn)
        candidate_report["by_review_status"] = {
            row["review_status"]: row["record_count"]
            for row in conn.execute(
                """
                SELECT review_status, COUNT(*) AS record_count
                FROM identity_match_candidates GROUP BY review_status
                ORDER BY review_status
                """
            ).fetchall()
        }
        candidate_report["candidate_pairs"] = conn.execute(
            "SELECT COUNT(*) FROM identity_match_candidates"
        ).fetchone()[0]

        resolved_series_by_source = Counter(
            {
                row["source"]: row["record_count"]
                for row in conn.execute(
                    """
                    SELECT source, COUNT(*) AS record_count FROM source_records
                    WHERE series_id IS NOT NULL GROUP BY source
                    """
                ).fetchall()
            }
        )
        unresolved_series_by_source = Counter(
            {
                row["source"]: row["record_count"]
                for row in conn.execute(
                    """
                    SELECT source, COUNT(*) AS record_count FROM source_records
                    WHERE series_id IS NULL GROUP BY source
                    """
                ).fetchall()
            }
        )
        conn.commit()

        records_by_source = Counter(record["source"] for record in staged_records)
        prompt_digests: dict[str, str] = {}
        for source in SOURCE_ORDER:
            digest = hashlib.sha256()
            for record in sorted(
                (item for item in staged_records if item["source"] == source),
                key=lambda item: (item["legacy_id"] or 0, item["source_tag_raw"]),
            ):
                digest.update(str(record["legacy_id"] or "").encode("ascii"))
                digest.update(b"\0")
                digest.update(record["prompt_raw"].encode("utf-8"))
                digest.update(b"\n")
            prompt_digests[source] = digest.hexdigest()

        report: dict[str, Any] = {
            "schema_version": BUILD_SCHEMA_VERSION,
            "inputs": {
                "current_db": str(current_db),
                "current_db_sha256": metadata["current_db_sha256"],
                "anima_csv": str(anima_csv),
                "anima_csv_sha256": metadata["anima_csv_sha256"],
            },
            "outputs": {
                "database": str(output),
                "report": str(report_path),
            },
            "prompt_fidelity": {
                **prompt_validation,
                "source_prompt_digests": prompt_digests,
            },
            "source_records": {
                "total": len(staged_records),
                "by_source": dict(records_by_source),
            },
            "series": {
                "distinct_animadex_copyrights": len(copyright_tags),
                "total_series_definitions": len(series_ids),
                "resolved_records_by_source": dict(resolved_series_by_source),
                "unresolved_records_by_source": dict(unresolved_series_by_source),
                "ambiguous_exact_keys_count": len(ambiguous_copyright_keys),
                "ambiguous_exact_keys_samples": dict(
                    list(sorted(ambiguous_copyright_keys.items()))[:20]
                ),
            },
            "exact_identity_groups": {
                "total": len(group_ids),
                "by_source_combination": dict(sorted(combination_counts.items())),
                "provisional_exclusive_by_source": dict(
                    sorted(provisional_exclusive_counts.items())
                ),
                "warning": (
                    "Exact-tag exclusivity is provisional until identity aliases "
                    "and character variations are reviewed."
                ),
            },
            "identity_match_candidates": candidate_report,
            "manual_review": override_report,
            "search_aliases": search_alias_report,
            "series_titles": series_title_report,
            "series_catalog": series_catalog_report,
            "canonical_catalog": canonical_catalog_report,
        }
        if overrides_path is not None:
            report["inputs"]["catalog_overrides"] = str(overrides_path)
            report["inputs"]["catalog_overrides_sha256"] = metadata[
                "catalog_overrides_sha256"
            ]
        if alias_cache_path is not None:
            report["inputs"]["official_alias_cache"] = str(alias_cache_path)
            report["inputs"]["official_alias_cache_sha256"] = metadata[
                "official_alias_cache_sha256"
            ]
        if anidb_titles_path is not None:
            report["inputs"]["anidb_titles"] = str(anidb_titles_path)
            report["inputs"]["anidb_titles_sha256"] = metadata[
                "anidb_titles_sha256"
            ]

        temp_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        conn.close()
        if temp_output.exists():
            temp_output.unlink()
        if temp_report.exists():
            temp_report.unlink()
        raise
    else:
        conn.close()

    os.replace(temp_output, output)
    os.replace(temp_report, report_path)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-db", type=Path, default=DEFAULT_CURRENT_DB)
    parser.add_argument("--anima-csv", type=Path, default=DEFAULT_ANIMA_CSV)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--alias-cache", type=Path, default=DEFAULT_ALIAS_CACHE)
    parser.add_argument("--anidb-titles", type=Path, default=DEFAULT_ANIDB_TITLES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_catalog(
            current_db=args.current_db,
            anima_csv=args.anima_csv,
            output=args.output,
            report_path=args.report,
            overrides_path=args.overrides,
            alias_cache_path=args.alias_cache,
            anidb_titles_path=args.anidb_titles,
        )
    except BuildError as exc:
        print(f"Build blocked: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Built: {report['outputs']['database']}")
    print(f"Report: {report['outputs']['report']}")
    print(
        "Prompt fidelity: "
        f"{report['prompt_fidelity']['verified_exact_prompts']:,} Anima prompts verified"
    )
    print(
        "Records: "
        f"{report['source_records']['total']:,} across "
        f"{report['exact_identity_groups']['total']:,} exact-tag groups"
    )
    print(
        "Manual review: "
        f"{report['manual_review']['record_decisions']:,} decisions, "
        f"{sum(report['manual_review']['reviewed_exclusive_by_source'].values()):,} "
        "reviewed exclusive records"
    )
    print(
        "Directional search aliases: "
        f"{report['search_aliases'].get('imported_total', 0):,} imported; "
        "identity merges applied: 0"
    )
    print(
        "Series titles: "
        f"{report['series_titles']['accepted_series']:,} accepted, "
        f"{report['series_titles']['ambiguous_series']:,} ambiguous, "
        f"{report['series_titles']['unresolved_series']:,} unresolved; "
        "identity merges applied: 0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
