import unittest

from logreader.core import SearchPattern, analyze_lines


class AnalyzeLinesTests(unittest.TestCase):

    def test_search_is_case_insensitive_and_supports_exclusions(self):
        lines = [
            "ERROR: explicit error",
            "A generic Error occurred",
            "error: another explicit error",
        ]
        result = analyze_lines(
            lines,
            [
                SearchPattern("error_colon", "error:"),
                SearchPattern(
                    "error",
                    "error",
                    excluded_substrings=("error:",),
                ),
            ],
        )

        self.assertEqual(result.line_count, 3)
        self.assertEqual(result.category("error_colon").match_count, 2)
        self.assertEqual(result.category("error").match_count, 1)

    def test_touching_context_ranges_are_merged(self):
        lines = [f"line {number}" for number in range(1, 9)]
        lines[2] = "ERROR: first"
        lines[5] = "ERROR: second"

        result = analyze_lines(
            lines,
            [SearchPattern("error", "error:", context=1)],
        ).category("error")

        self.assertEqual(result.match_count, 2)
        self.assertEqual(len(result.excerpts), 1)
        self.assertEqual(
            [line.number for line in result.excerpts[0].lines],
            [2, 3, 4, 5, 6, 7],
        )
        self.assertEqual(
            [line.number for line in result.excerpts[0].lines if line.is_match],
            [3, 6],
        )

    def test_separated_matches_create_separate_excerpts(self):
        lines = [f"line {number}" for number in range(1, 11)]
        lines[1] = "fatal: first"
        lines[7] = "FATAL: second"

        result = analyze_lines(
            lines,
            [SearchPattern("fatal", "fatal", context=1)],
        ).category("fatal")

        self.assertEqual(len(result.excerpts), 2)
        self.assertEqual(
            [[line.number for line in excerpt.lines] for excerpt in result.excerpts],
            [[1, 2, 3], [7, 8, 9]],
        )

    def test_following_context_stops_before_an_excluded_occurrence(self):
        result = analyze_lines(
            ["generic error", "ERROR: explicit", "plain context"],
            [
                SearchPattern(
                    "error",
                    "error",
                    context=2,
                    excluded_substrings=("error:",),
                )
            ],
        ).category("error")

        self.assertEqual(result.match_count, 1)
        self.assertEqual(
            [line.number for line in result.excerpts[0].lines],
            [1],
        )

    def test_duplicate_pattern_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate search pattern key"):
            analyze_lines(
                ["error"],
                [
                    SearchPattern("error", "error"),
                    SearchPattern("error", "failure"),
                ],
            )

    def test_every_match_on_a_line_has_a_visible_span(self):
        category = analyze_lines(
            ["ERROR then error again"],
            [SearchPattern("error", "error")],
        ).category("error")

        result_line = category.excerpts[0].lines[0]
        self.assertEqual(
            tuple(
                result_line.text[span.start : span.end]
                for span in result_line.match_spans
            ),
            ("ERROR", "error"),
        )

    def test_invalid_fixed_regex_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid search pattern regex"):
            SearchPattern("invalid", "[", is_regex=True)

    def test_regex_is_case_sensitive_unless_inline_flags_enable_folding(self):
        result = analyze_lines(
            ["error ERROR"],
            [
                SearchPattern("sensitive", "error", is_regex=True),
                SearchPattern("insensitive", "(?i)error", is_regex=True),
            ],
        )

        sensitive_line = result.category("sensitive").excerpts[0].lines[0]
        insensitive_line = result.category("insensitive").excerpts[0].lines[0]
        self.assertEqual(
            [(span.start, span.end) for span in sensitive_line.match_spans],
            [(0, 5)],
        )
        self.assertEqual(
            [(span.start, span.end) for span in insensitive_line.match_spans],
            [(0, 5), (6, 11)],
        )

    def test_zero_width_regex_matches_are_ignored(self):
        result = analyze_lines(
            ["ERROR"],
            [
                SearchPattern("anchors_only", r"^|$", is_regex=True),
                SearchPattern(
                    "consuming_lookaround",
                    r"^(?=ERROR)ERROR(?=$)",
                    is_regex=True,
                ),
            ],
        )

        self.assertEqual(result.category("anchors_only").match_count, 0)
        consuming = result.category("consuming_lookaround")
        self.assertEqual(consuming.match_count, 1)
        self.assertEqual(
            [
                (span.start, span.end)
                for span in consuming.excerpts[0].lines[0].match_spans
            ],
            [(0, 5)],
        )


if __name__ == "__main__":
    unittest.main()
