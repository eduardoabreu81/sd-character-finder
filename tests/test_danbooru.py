from __future__ import annotations

import unittest

from wildcard_creator.danbooru import _normalize_live_query_tag


class DanbooruQueryTagTests(unittest.TestCase):
    def test_removes_prompt_parenthesis_escapes_for_live_api(self) -> None:
        self.assertEqual(
            _normalize_live_query_tag("astolfo \\(fate\\)"),
            "astolfo_(fate)",
        )


if __name__ == "__main__":
    unittest.main()
