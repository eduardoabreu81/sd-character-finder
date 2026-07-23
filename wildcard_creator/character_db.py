"""Read-only SQLite access for the v2 canonical character catalogue."""

from __future__ import annotations

import atexit
import json
import logging
import re
import sqlite3
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "characters.db"
_SOURCE_ORDER = ("danbooru", "e621", "anima")
_REQUIRED_SCHEMA_VERSION = 5


def _normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\\(", "(").replace("\\)", ")")
    text = text.replace("_", " ").casefold()
    return " ".join(text.split())


class CharacterDB:
    """Query canonical variations and hydrate their source representations."""

    def __init__(self, db_path: Path = _DEFAULT_DB):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._write_lock = threading.Lock()
        self._user_overrides_path = self._path.parent / "user_overrides_v2.json"

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._path.exists():
                raise FileNotFoundError(f"Character catalogue not found: {self._path}")
            uri = self._path.resolve().as_uri() + "?mode=ro"
            self._conn = sqlite3.connect(
                uri,
                uri=True,
                check_same_thread=False,
                timeout=15.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.execute("PRAGMA busy_timeout=15000")
            self._validate_schema()
        return self._conn

    def _validate_schema(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM build_metadata WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row else 0
        if version < _REQUIRED_SCHEMA_VERSION:
            raise RuntimeError(
                "This branch requires the v2 character catalogue "
                f"(schema >= {_REQUIRED_SCHEMA_VERSION}, found {version})."
            )

    def is_populated(self) -> bool:
        if not self._path.exists():
            return False
        try:
            return (
                self._get_conn()
                .execute("SELECT 1 FROM character_variations LIMIT 1")
                .fetchone()
                is not None
            )
        except Exception as exc:
            logger.error("is_populated failed: %s", exc, exc_info=True)
            return False

    def count(self) -> int:
        try:
            row = self._get_conn().execute(
                "SELECT COUNT(*) FROM character_variations"
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.error("count failed: %s", exc, exc_info=True)
            return 0

    def count_by_source(self, source: str) -> int:
        try:
            row = self._get_conn().execute(
                """
                SELECT COUNT(DISTINCT variation_id)
                FROM character_representations
                WHERE source = ?
                """,
                (source,),
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.error(
                "count_by_source failed: source=%r, error=%s",
                source,
                exc,
                exc_info=True,
            )
            return 0

    def _load_user_tag_overrides(self) -> dict[str, str]:
        if not self._user_overrides_path.exists():
            return {}
        try:
            payload = json.loads(
                self._user_overrides_path.read_text(encoding="utf-8")
            )
            if payload.get("schema_version") != 2:
                return {}
            values = payload.get("danbooru_tags", {})
            if not isinstance(values, dict):
                return {}
            return {
                str(key): str(value)
                for key, value in values.items()
                if str(key).strip() and str(value).strip()
            }
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            logger.error("Cannot read v2 user overrides: %s", exc)
            return {}

    def _get_representations_many(
        self,
        variation_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not variation_ids:
            return {}
        placeholders = ",".join("?" for _ in variation_ids)
        rows = self._get_conn().execute(
            f"""
            SELECT cr.id AS representation_id, cr.variation_id, cr.source,
                   cr.display_order, cr.is_default, sr.id AS source_record_id,
                   sr.provider, sr.source_name_raw, sr.source_tag_raw,
                   sr.canonical_tag_raw, sr.prompt_raw, sr.image_url,
                   sr.source_url, sr.rank, sr.reference_count
            FROM character_representations cr
            JOIN source_records sr ON sr.id = cr.source_record_id
            WHERE cr.variation_id IN ({placeholders})
            ORDER BY cr.variation_id, cr.display_order
            """,
            variation_ids,
        ).fetchall()
        overrides = self._load_user_tag_overrides()
        variation_keys = {
            int(row["id"]): str(row["variation_key"])
            for row in self._get_conn()
            .execute(
                f"""
                SELECT id, variation_key FROM character_variations
                WHERE id IN ({placeholders})
                """,
                variation_ids,
            )
            .fetchall()
        }
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            representation = dict(row)
            variation_id = int(row["variation_id"])
            if row["source"] in {"danbooru", "e621"}:
                # These profiles target tag-based models, so the value shown in
                # the UI must retain prompt escapes such as ``\(fate\)``.
                canonical_tag = str(
                    row["source_tag_raw"] or row["canonical_tag_raw"] or ""
                )
            else:
                # Anima triggers have their own formatting and may contain more
                # than the first prompt token. Keep the exact imported trigger.
                canonical_tag = str(
                    row["canonical_tag_raw"] or row["source_tag_raw"] or ""
                )
            if row["source"] == "danbooru":
                canonical_tag = overrides.get(
                    variation_keys[variation_id],
                    canonical_tag,
                )
            representation["canonical_tag"] = canonical_tag
            representation["tags"] = str(row["prompt_raw"])
            grouped[variation_id].append(representation)
        return dict(grouped)

    @staticmethod
    def _choose_representation(
        representations: list[dict[str, Any]],
        source_filter: str,
    ) -> dict[str, Any] | None:
        normalized_source = (source_filter or "").casefold()
        if normalized_source not in {"", "all", "both"}:
            return next(
                (
                    representation
                    for representation in representations
                    if representation["source"] == normalized_source
                ),
                None,
            )
        return next(
            (
                representation
                for representation in representations
                if representation["is_default"]
            ),
            representations[0] if representations else None,
        )

    def _hydrate_rows(
        self,
        rows: list[sqlite3.Row],
        source_filter: str,
    ) -> list[dict[str, Any]]:
        variation_ids = [int(row["id"]) for row in rows]
        representations_by_variation = self._get_representations_many(variation_ids)
        hydrated: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            variation_id = int(row["id"])
            representations = representations_by_variation.get(variation_id, [])
            selected = self._choose_representation(representations, source_filter)
            if selected is None:
                continue
            sources = [
                source
                for source in _SOURCE_ORDER
                if any(rep["source"] == source for rep in representations)
            ]
            item.update(
                {
                    "id": variation_id,
                    "variation_id": variation_id,
                    "tags": selected["prompt_raw"],
                    "image_url": selected["image_url"],
                    "rank": selected["rank"],
                    "danbooru_tag": selected["canonical_tag"],
                    "source": selected["source"],
                    "representation_id": selected["representation_id"],
                    "source_record_id": selected["source_record_id"],
                    "sources": sources,
                    "source_combination": "+".join(sources),
                    "representations": representations,
                    "is_variation": bool(row["is_variation"]),
                }
            )
            hydrated.append(item)
        return hydrated

    def search(
        self,
        query: str,
        series_filter: Optional[str] = None,
        tag_status_filter: str = "All",
        source_filter: str = "both",
        favorites_list: Optional[list[int]] = None,
        limit: int = 50,
        offset: int = 0,
        exclusive_filter: str = "All",
    ) -> tuple[list[dict], int]:
        """Search one row per canonical variation with multi-term AND semantics."""
        params: list[Any] = []
        clauses: list[str] = []
        normalized_source = (source_filter or "").casefold()

        terms = [
            _normalize_text(term)
            for term in re.split(r"[,\s]+", (query or "").strip())
            if term.strip()
        ]
        for term in terms:
            like = f"%{term}%"
            clauses.append(
                """
                (
                    v.normalized_display_name LIKE ?
                    OR c.normalized_display_name LIKE ?
                    OR v.variation_key LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM character_search_terms st
                        WHERE st.variation_id = v.id
                          AND st.normalized_term LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM series_aliases sa
                        WHERE sa.series_id = v.series_id
                          AND sa.normalized_alias LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM character_representations qr
                        JOIN source_records qsr ON qsr.id = qr.source_record_id
                        WHERE qr.variation_id = v.id
                          AND qsr.prompt_raw LIKE ?
                    )
                )
                """
            )
            params.extend([like, like, like, like, like, like])

        normalized_series = (series_filter or "").strip()
        if normalized_series and normalized_series != "All":
            clauses.append(
                """
                (
                    s.canonical_display_name = ? COLLATE NOCASE
                    OR s.source_copyright_tag = ? COLLATE NOCASE
                )
                """
            )
            params.extend([normalized_series, normalized_series])

        if tag_status_filter == "Missing Danbooru Tag":
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1 FROM character_representations dr
                    WHERE dr.variation_id = v.id AND dr.source = 'danbooru'
                )
                """
            )
        elif tag_status_filter == "Has Danbooru Tag":
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM character_representations dr
                    WHERE dr.variation_id = v.id AND dr.source = 'danbooru'
                )
                """
            )

        if normalized_source not in {"", "all", "both"}:
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM character_representations sr_filter
                    WHERE sr_filter.variation_id = v.id
                      AND sr_filter.source = ?
                )
                """
            )
            params.append(normalized_source)

        normalized_exclusive = (exclusive_filter or "").strip().casefold()
        if normalized_exclusive.endswith(" only"):
            normalized_exclusive = normalized_exclusive.removesuffix(" only").strip()
        if normalized_exclusive in _SOURCE_ORDER:
            clauses.append("v.exclusive_source = ?")
            params.append(normalized_exclusive)
        elif normalized_exclusive == "reviewed exclusive":
            clauses.append("v.exclusivity_status = 'reviewed'")
        elif normalized_exclusive in {"multiple", "multiple sources", "shared"}:
            clauses.append("v.source_count > 1")

        if favorites_list is not None:
            if not favorites_list:
                return [], 0
            placeholders = ",".join("?" for _ in favorites_list)
            clauses.append(f"v.id IN ({placeholders})")
            params.extend(int(value) for value in favorites_list)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        base_from = """
            FROM character_variations v
            JOIN canonical_characters c ON c.id = v.character_id
            LEFT JOIN series s ON s.id = v.series_id
        """
        sql_count = f"SELECT COUNT(*) {base_from} {where}"
        sql = f"""
            SELECT v.id, v.character_id, v.variation_key, v.display_name AS name,
                   s.canonical_display_name AS series,
                   s.source_copyright_tag AS series_source_tag,
                   s.series_scope, v.is_default,
                   CASE WHEN v.is_default = 1 THEN 0 ELSE 1 END AS is_variation,
                   v.source_mask, v.source_count, v.exclusive_source,
                   v.exclusivity_status, v.resolution_status,
                   c.variation_count
            {base_from}
            {where}
            ORDER BY COALESCE(
                (
                    SELECT MIN(osr.rank)
                    FROM character_representations orp
                    JOIN source_records osr ON osr.id = orp.source_record_id
                    WHERE orp.variation_id = v.id
                ),
                2147483647
            ), v.normalized_display_name
            LIMIT ? OFFSET ?
        """

        try:
            total_row = self._get_conn().execute(sql_count, params).fetchone()
            rows = self._get_conn().execute(
                sql,
                [*params, int(limit), int(offset)],
            ).fetchall()
            return self._hydrate_rows(rows, normalized_source), int(total_row[0])
        except Exception as exc:
            logger.error(
                "search failed: query=%r, series=%r, source=%r, exclusive=%r, error=%s",
                query,
                series_filter,
                source_filter,
                exclusive_filter,
                exc,
                exc_info=True,
            )
            return [], 0

    def get(self, name: str) -> Optional[dict]:
        normalized_name = _normalize_text(name)
        try:
            rows = self._get_conn().execute(
                """
                SELECT v.id, v.character_id, v.variation_key,
                       v.display_name AS name,
                       s.canonical_display_name AS series,
                       s.source_copyright_tag AS series_source_tag,
                       s.series_scope, v.is_default,
                       CASE WHEN v.is_default = 1 THEN 0 ELSE 1 END AS is_variation,
                       v.source_mask, v.source_count, v.exclusive_source,
                       v.exclusivity_status, v.resolution_status,
                       c.variation_count
                FROM character_variations v
                JOIN canonical_characters c ON c.id = v.character_id
                LEFT JOIN series s ON s.id = v.series_id
                WHERE v.normalized_display_name = ? OR v.variation_key = ?
                ORDER BY v.is_default DESC LIMIT 1
                """,
                (normalized_name, normalized_name),
            ).fetchall()
            hydrated = self._hydrate_rows(rows, "all")
            return hydrated[0] if hydrated else None
        except Exception as exc:
            logger.error("get failed: name=%r, error=%s", name, exc, exc_info=True)
            return None

    def get_representations(self, variation_id: int) -> list[dict[str, Any]]:
        return self._get_representations_many([int(variation_id)]).get(
            int(variation_id),
            [],
        )

    def save_danbooru_tag(self, char_id: int, danbooru_tag: str) -> bool:
        """Save a user-only live-tag override without mutating the catalogue."""
        tag = (danbooru_tag or "").strip()
        if not tag:
            return False
        try:
            row = self._get_conn().execute(
                "SELECT variation_key FROM character_variations WHERE id = ?",
                (int(char_id),),
            ).fetchone()
            if not row:
                return False
            with self._write_lock:
                values = self._load_user_tag_overrides()
                values[str(row["variation_key"])] = tag
                payload = {
                    "schema_version": 2,
                    "danbooru_tags": dict(sorted(values.items())),
                }
                temp_path = self._user_overrides_path.with_suffix(".json.tmp")
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temp_path.replace(self._user_overrides_path)
            return True
        except Exception as exc:
            logger.error(
                "save_danbooru_tag failed: char_id=%s, error=%s",
                char_id,
                exc,
                exc_info=True,
            )
            return False

    def list_pending_danbooru(self, limit: int = 500) -> list[dict]:
        try:
            rows = self._get_conn().execute(
                """
                SELECT v.id, v.display_name AS name,
                       s.canonical_display_name AS series
                FROM character_variations v
                LEFT JOIN series s ON s.id = v.series_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM character_representations cr
                    WHERE cr.variation_id = v.id AND cr.source = 'danbooru'
                )
                ORDER BY v.id LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("list_pending_danbooru failed: %s", exc, exc_info=True)
            return []

    def pending_danbooru_count(self) -> int:
        try:
            row = self._get_conn().execute(
                """
                SELECT COUNT(*) FROM character_variations v
                WHERE NOT EXISTS (
                    SELECT 1 FROM character_representations cr
                    WHERE cr.variation_id = v.id AND cr.source = 'danbooru'
                )
                """
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.error("pending_danbooru_count failed: %s", exc, exc_info=True)
            return 0

    def list_series(self) -> list[tuple[str, int]]:
        try:
            rows = self._get_conn().execute(
                """
                SELECT s.canonical_display_name, COUNT(v.id) AS record_count
                FROM series s
                JOIN character_variations v ON v.series_id = s.id
                GROUP BY s.canonical_display_name
                ORDER BY s.canonical_display_name COLLATE NOCASE
                """
            ).fetchall()
            return [(str(row[0]), int(row[1])) for row in rows]
        except Exception as exc:
            logger.error("list_series failed: %s", exc, exc_info=True)
            return []

    def count_unique(self) -> int:
        try:
            row = self._get_conn().execute(
                "SELECT COUNT(*) FROM canonical_characters"
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.error("count_unique failed: %s", exc, exc_info=True)
            return 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


_db_instance: Optional[CharacterDB] = None


def get_character_db() -> CharacterDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = CharacterDB()
    return _db_instance


@atexit.register
def _close_db_on_exit() -> None:
    global _db_instance
    if _db_instance is not None:
        try:
            _db_instance.close()
        except Exception:
            pass
