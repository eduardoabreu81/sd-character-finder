#!/usr/bin/env python3
"""Fetch and validate the official daily AniDB anime-title dump.

AniDB explicitly limits this dump to one request per day. This collector has no
force-refresh option: a cache younger than 24 hours is always reused.

Usage:
    python scripts/fetch_anidb_titles.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

if __package__:
    from scripts.build_character_catalog_v2 import (
        BuildError,
        DEFAULT_ANIDB_TITLES,
        read_anidb_title_dump,
        sha256_file,
    )
else:
    from build_character_catalog_v2 import (
        BuildError,
        DEFAULT_ANIDB_TITLES,
        read_anidb_title_dump,
        sha256_file,
    )


ANIDB_TITLES_URL = "https://anidb.net/api/anime-titles.xml.gz"
MIN_REFRESH_AGE_SECONDS = 24 * 60 * 60
USER_AGENT = "sd-character-finder/0.6.1 (AniDB daily title-dump cache)"


class FetchError(RuntimeError):
    """Raised when the existing cache cannot be reused or refreshed safely."""


def fetch_anidb_titles(
    output: Path,
    *,
    now: float | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Reuse a fresh cache or atomically download and validate a stale one."""
    output = output.resolve()
    current_time = time.time() if now is None else now
    if output.exists():
        age_seconds = max(0.0, current_time - output.stat().st_mtime)
        if age_seconds < MIN_REFRESH_AGE_SECONDS:
            parsed = read_anidb_title_dump(output)
            if parsed is None:
                raise FetchError(f"Cannot validate AniDB cache: {output}")
            return {
                "status": "cached",
                "output": str(output),
                "age_seconds": age_seconds,
                "sha256": sha256_file(output),
                "anime_count": parsed["anime_count"],
                "title_count": parsed["title_count"],
            }

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()

    request = urllib.request.Request(
        ANIDB_TITLES_URL,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with opener(request, timeout=60) as response:
            with temp_output.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
        parsed = read_anidb_title_dump(temp_output)
        if parsed is None:
            raise FetchError("Downloaded AniDB dump could not be validated")
        os.replace(temp_output, output)
    except (OSError, urllib.error.URLError, BuildError, FetchError) as exc:
        if temp_output.exists():
            temp_output.unlink()
        raise FetchError(f"Cannot refresh AniDB title dump: {exc}") from exc

    return {
        "status": "downloaded",
        "output": str(output),
        "age_seconds": 0.0,
        "sha256": sha256_file(output),
        "anime_count": parsed["anime_count"],
        "title_count": parsed["title_count"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_ANIDB_TITLES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = fetch_anidb_titles(args.output)
    except FetchError as exc:
        print(f"AniDB title fetch blocked: {exc}", file=sys.stderr)
        return 1

    print(
        f"AniDB titles: {result['status']} "
        f"({result['anime_count']:,} anime, {result['title_count']:,} titles)"
    )
    print(f"Cache: {result['output']}")
    print(f"SHA-256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
