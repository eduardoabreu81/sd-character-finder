from __future__ import annotations

import gzip
import io
import tempfile
import time
import unittest
from pathlib import Path

from scripts.fetch_anidb_titles import fetch_anidb_titles


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FetchAniDBTitlesTests(unittest.TestCase):
    def test_downloads_once_then_reuses_fresh_valid_cache(self) -> None:
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<animetitles>
  <anime aid="1">
    <title type="main" xml:lang="x-jat">Example</title>
    <title type="official" xml:lang="ja">Example</title>
  </anime>
</animetitles>
"""
        payload = gzip.compress(xml)
        calls = 0

        def opener(*args: object, **kwargs: object) -> _FakeResponse:
            nonlocal calls
            calls += 1
            return _FakeResponse(payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "anime-titles.xml.gz"
            first = fetch_anidb_titles(output, opener=opener)
            second = fetch_anidb_titles(
                output,
                now=time.time(),
                opener=opener,
            )

        self.assertEqual(first["status"], "downloaded")
        self.assertEqual(second["status"], "cached")
        self.assertEqual(first["anime_count"], 1)
        self.assertEqual(first["title_count"], 2)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
