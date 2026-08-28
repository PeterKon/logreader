import unittest

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from logreader.presentation import build_category_presentations


class PresentationTests(unittest.TestCase):

    def test_zero_match_categories_are_kept_out_of_detailed_presentations(self):
        config = LogreaderConfig(enabled_patterns=("error_colon", "fatal"))
        analysis = analyze_lines(["ERROR: boom"], config.search_patterns())

        presentations = build_category_presentations(analysis, limit=None)

        self.assertEqual(
            tuple(presentation.key for presentation in presentations),
            ("error_colon",),
        )
        self.assertIn("ERROR: boom", presentations[0].excerpts[0].lines[0].text)

    def test_limit_keeps_context_after_last_visible_match(self):
        config = LogreaderConfig(
            context=1,
            enabled_patterns=("error_colon",),
        )
        analysis = analyze_lines(
            ["ERROR: first", "context", "ERROR: second"],
            config.search_patterns(),
        )

        presentation = build_category_presentations(analysis, limit=1)[0]

        self.assertEqual(
            tuple(line.number for line in presentation.excerpts[0].lines),
            (1, 2),
        )
        self.assertEqual(presentation.shown_match_count, 1)
        self.assertTrue(presentation.is_limited)
        self.assertEqual(presentation.limit_message(), "Showing 1 of 2 matches.")

    def test_unlimited_presentation_retains_every_excerpt(self):
        config = LogreaderConfig(context=0, enabled_patterns=("fatal",))
        analysis = analyze_lines(
            ["FATAL first", "neutral", "FATAL second"],
            config.search_patterns(),
        )

        presentation = build_category_presentations(analysis, limit=None)[0]

        self.assertEqual(len(presentation.excerpts), 2)
        self.assertEqual(presentation.heading("FATAL"), "FATAL — 2 matches")
        self.assertFalse(presentation.is_limited)
        self.assertIsNone(presentation.limit_message())

    def test_non_positive_limit_is_rejected(self):
        analysis = analyze_lines([], ())

        with self.assertRaisesRegex(ValueError, "Limit must be positive"):
            build_category_presentations(analysis, limit=0)


if __name__ == "__main__":
    unittest.main()
