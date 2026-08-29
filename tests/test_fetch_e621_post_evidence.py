from __future__ import annotations

import unittest

from scripts.fetch_e621_post_evidence import (
    E621PostEvidenceError,
    extract_post_sample,
)


class E621PostEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue_row = {
            "source_record_id": "10",
            "resolved_tag": "example_character",
            "source_tag_raw": "example character",
            "source_name_raw": "Example Character",
            "current_series_raw": "Publisher",
            "post_count": "100",
            "prompt_sha256": "a" * 64,
        }

    def test_extracts_categorized_copyright_and_character_tags(self) -> None:
        sample = extract_post_sample(
            self.queue_row,
            {
                "posts": [
                    {
                        "id": 123,
                        "tags": {
                            "copyright": ["specific_work"],
                            "character": ["example_character"],
                        },
                    }
                ]
            },
        )

        self.assertEqual(sample["sample_status"], "single_copyright")
        self.assertEqual(sample["post_id"], 123)
        self.assertEqual(sample["copyright_tags"], ["specific_work"])
        self.assertEqual(sample["character_tags"], ["example_character"])

    def test_records_an_empty_post_result_without_inventing_metadata(self) -> None:
        sample = extract_post_sample(self.queue_row, {"posts": []})

        self.assertEqual(sample["sample_status"], "no_post_returned")
        self.assertIsNone(sample["post_id"])
        self.assertEqual(sample["copyright_tags"], [])

    def test_rejects_uncategorized_post_tags(self) -> None:
        with self.assertRaises(E621PostEvidenceError):
            extract_post_sample(
                self.queue_row,
                {"posts": [{"id": 123, "tags": ["not", "categorized"]}]},
            )


if __name__ == "__main__":
    unittest.main()
