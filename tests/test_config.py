import unittest

from logreader.config import DEFAULT_ENABLED_PATTERNS, PATTERN_KEYS, LogreaderConfig
from logreader.core import analyze_lines


class LogreaderConfigTests(unittest.TestCase):

    def test_defaults_enable_the_four_primary_patterns_with_shared_context(self):
        config = LogreaderConfig()
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            ["error_colon", "error", "failed", "fatal"],
        )
        self.assertEqual(patterns[0].context, 3)
        self.assertEqual(patterns[1].context, 3)
        self.assertEqual(patterns[1].excluded_substrings, ("error:",))

    def test_patterns_have_a_stable_logical_display_order(self):
        expected_order = (
            "error_colon",
            "error",
            "failed",
            "fatal",
            "warning",
            "warning_generic",
            "exception",
            "exception_generic",
            "failure",
            "critical",
            "illegal",
            "invalid",
            "aborted",
            "terminated",
            "timeout",
            "uninitialized",
            "not_found",
        )
        config = LogreaderConfig(enabled_patterns=tuple(reversed(PATTERN_KEYS)))

        self.assertEqual(PATTERN_KEYS, expected_order)
        self.assertEqual(PATTERN_KEYS[:4], DEFAULT_ENABLED_PATTERNS)
        self.assertEqual(
            tuple(pattern.key for pattern in config.search_patterns()),
            expected_order,
        )

    def test_new_operational_state_patterns_are_searchable(self):
        keys = ("aborted", "terminated", "timeout", "uninitialized", "not_found")
        config = LogreaderConfig(enabled_patterns=keys)
        analysis = analyze_lines(
            [
                "Job ABORTED by operator",
                "Session terminated unexpectedly",
                "Connection timeout",
                "Variable is uninitialized",
                "Requested resource not found",
            ],
            config.search_patterns(),
        )

        self.assertEqual(
            {key: analysis.category(key).match_count for key in keys},
            {key: 1 for key in keys},
        )

    def test_plain_warning_and_exception_do_not_duplicate_colon_matches(self):
        config = LogreaderConfig(
            enabled_patterns=(
                "warning",
                "warning_generic",
                "exception",
                "exception_generic",
            )
        )
        analysis = analyze_lines(
            [
                "WARNING: colon form",
                "A plain warning occurred",
                "EXCEPTION: colon form",
                "A plain exception occurred",
            ],
            config.search_patterns(),
        )

        self.assertEqual(analysis.category("warning").match_count, 1)
        self.assertEqual(analysis.category("warning_generic").match_count, 1)
        self.assertEqual(analysis.category("exception").match_count, 1)
        self.assertEqual(analysis.category("exception_generic").match_count, 1)

    def test_selected_and_custom_patterns_share_context_and_limits(self):
        config = LogreaderConfig(
            context=5,
            limit=10,
            enabled_patterns=("warning", "exception"),
            custom_patterns=(" timeout ",),
            separate_entries=True,
        )
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            ["warning", "exception", "custom_1"],
        )
        self.assertEqual(config.custom_patterns, ("timeout",))
        self.assertTrue(all(pattern.context == 5 for pattern in patterns))
        self.assertEqual(config.label_for("custom_1"), "timeout")
        self.assertTrue(config.separate_entries)

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Context cannot be negative"):
            LogreaderConfig(context=-1)
        with self.assertRaisesRegex(ValueError, "Limit must be positive"):
            LogreaderConfig(limit=0)
        with self.assertRaisesRegex(ValueError, "Unknown pattern"):
            LogreaderConfig(enabled_patterns=("unknown",))
        with self.assertRaisesRegex(ValueError, "Custom patterns cannot be empty"):
            LogreaderConfig(custom_patterns=(" ",))


if __name__ == "__main__":
    unittest.main()
