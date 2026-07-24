from __future__ import annotations

import unittest

from scripts.audit_e621_series import E621AuditError, E621ExportIndex


class E621ExportIndexTests(unittest.TestCase):
    def test_keeps_only_the_most_specific_copyright_implication(self) -> None:
        index = E621ExportIndex(
            tags={
                "character": (4, 100),
                "specific_work": (3, 200),
                "publisher": (3, 500),
            },
            aliases={},
            implications={
                "character": {"specific_work"},
                "specific_work": {"publisher"},
            },
            wiki_titles=set(),
        )

        self.assertEqual(
            index.most_specific_copyrights("character"),
            {"specific_work"},
        )
        self.assertEqual(
            index.shortest_path("character", "specific_work"),
            ["character", "specific_work"],
        )

    def test_resolves_active_aliases_before_following_implications(self) -> None:
        index = E621ExportIndex(
            tags={
                "current_character": (4, 50),
                "work": (3, 100),
            },
            aliases={"old_character": "current_character"},
            implications={"current_character": {"work"}},
            wiki_titles=set(),
        )

        resolved, chain = index.resolve_alias("old character")
        self.assertEqual(resolved, "current_character")
        self.assertEqual(chain, ["old_character", "current_character"])
        self.assertEqual(index.most_specific_copyrights("old_character"), {"work"})

    def test_rejects_an_active_alias_cycle(self) -> None:
        index = E621ExportIndex(
            tags={},
            aliases={"first": "second", "second": "first"},
            implications={},
            wiki_titles=set(),
        )

        with self.assertRaises(E621AuditError):
            index.resolve_alias("first")


if __name__ == "__main__":
    unittest.main()
