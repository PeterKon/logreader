import unittest

from logreader.core import COMBINED_CATEGORY_KEY, SearchPattern, analyze_lines


class AnalyzeLinesTests(unittest.TestCase):

    def test_global_exclusions_override_all_matches_but_remain_context(self):
        lines = ["ERROR keep", "ERROR Skip code=500", "ERROR SKIP code=500"]
        for combined in (False, True):
            result = analyze_lines(lines, (
                SearchPattern("error", "ERROR", context=2),
                SearchPattern("custom", "keep", context=2),
                SearchPattern("regex", r"code=\d+", is_regex=True, context=2),
                SearchPattern("exclude", "skip", exclude=True),
            ), combined=combined)
            self.assertEqual(result.pattern_count, 3)
            self.assertEqual(result.category_match_counts, {"error": 1, "custom": 1, "regex": 0})
            category = result.category("combined" if combined else "error")
            context = category.excerpts[0].lines
            self.assertEqual([line.text for line in context], lines)
            self.assertEqual([line.is_match for line in context], [True, False, False])
            self.assertNotIn("exclude", result.categories)

    def test_exclusions_respect_case_and_work_without_positive_patterns(self):
        lines = ["ERROR skip", "ERROR Skip", "ERROR other"]
        exclusion = SearchPattern("exclude", "Skip", exclude=True, case_sensitive=True)
        for patterns, expected in (
            ((exclusion,), {}),
            ((SearchPattern("error", "ERROR"), exclusion), {"error": 2}),
            ((SearchPattern("regex", "ERROR", is_regex=True), exclusion), {"regex": 2}),
            ((SearchPattern("error", "ERROR"), exclusion,
              SearchPattern("other", "other", exclude=True)), {"error": 1}),
        ):
            result = analyze_lines(lines, patterns)
            self.assertEqual(result.category_match_counts, expected)
            for category in result.categories.values():
                self.assertTrue(all(
                    line.number != 2 for excerpt in category.excerpts for line in excerpt.lines
                ))

    def test_literal_match_case_preserves_exact_spans_in_both_search_paths(self):
        exact = SearchPattern("exact", "Error[1]", case_sensitive=True)
        folded = SearchPattern("folded", "Error[1]")
        for patterns in ((exact,), (exact, folded)):
            for combined in (False, True):
                with self.subTest(patterns=patterns, combined=combined):
                    result = analyze_lines(
                        ["error[1]", "ERROR[1]", "Error[1] error[1]", "Error1"],
                        patterns, combined=combined,
                    )
                    self.assertEqual(result.category_match_counts["exact"], 1)
                    if len(patterns) > 1:
                        self.assertEqual(result.category_match_counts["folded"], 3)
                    if not combined:
                        line = result.category("exact").excerpts[0].lines[0]
                        self.assertEqual(line.number, 3)
                        self.assertEqual(
                            [(span.start, span.end) for span in line.match_spans],
                            [(0, 8)],
                        )

    def test_combined_analysis_builds_only_one_line_counted_category(self):
        result = analyze_lines(
            [
                "ERROR: failed and error again",
                "context",
                "FATAL shutdown",
            ],
            [
                SearchPattern("error", "error", context=1),
                SearchPattern("error_colon", "error:", context=1),
                SearchPattern("failed", "failed", context=1),
                SearchPattern("fatal", "fatal", context=1),
            ],
            combined=True,
        )

        self.assertEqual(tuple(result.categories), (COMBINED_CATEGORY_KEY,))
        self.assertEqual(result.pattern_count, 4)
        self.assertEqual(
            result.category_match_counts,
            {
                "error": 1,
                "error_colon": 1,
                "failed": 1,
                "fatal": 1,
            },
        )
        combined = result.category(COMBINED_CATEGORY_KEY)
        self.assertIsNone(combined.pattern)
        self.assertEqual(combined.match_count, 4)
        self.assertEqual(combined.limit_count, 2)
        self.assertEqual(
            tuple(line.number for line in combined.excerpts[0].lines),
            (1, 2, 3),
        )
        self.assertEqual(
            tuple(
                (span.start, span.end)
                for span in combined.excerpts[0].lines[0].match_spans
            ),
            ((0, 6), (7, 13), (18, 23)),
        )

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

    def test_exclusions_collect_spans_and_raw_matches_in_one_pass(self):
        validator_calls = []

        def validator(line, start, end):
            validator_calls.append((line, start, end))
            return not line.startswith("ERROR:") or start > 0

        result = analyze_lines(
            [
                "generic error and error",
                "ERROR: rejected error accepted",
                "plain context",
            ],
            [
                SearchPattern(
                    "error",
                    "error",
                    context=2,
                    excluded_substrings=("error:",),
                    match_validator=validator,
                ),
                SearchPattern("unused", "unused"),
            ],
        ).category("error")

        self.assertEqual(result.match_count, 1)
        self.assertEqual(
            [line.number for line in result.excerpts[0].lines],
            [1],
        )
        self.assertEqual(
            [
                (span.start, span.end)
                for span in result.excerpts[0].lines[0].match_spans
            ],
            [(8, 13), (18, 23)],
        )
        self.assertEqual(
            validator_calls,
            [
                ("generic error and error", 8, 13),
                ("generic error and error", 18, 23),
                ("ERROR: rejected error accepted", 0, 5),
                ("ERROR: rejected error accepted", 16, 21),
            ],
        )

    def test_sparse_matches_preserve_large_line_numbers_and_context(self):
        lines = ["neutral"] * 10_000
        lines[5_000] = "generic error"
        lines[5_002] = "ERROR: explicit"

        result = analyze_lines(
            lines,
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
            [4_999, 5_000, 5_001, 5_002],
        )
        self.assertEqual(
            [
                line.number
                for line in result.excerpts[0].lines
                if line.is_match
            ],
            [5_001],
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

    def test_shared_literal_scan_preserves_overlapping_pattern_spans(self):
        result = analyze_lines(
            ["ababa ERROR: K"],
            [
                SearchPattern("aba", "aba"),
                SearchPattern("bab", "bab"),
                SearchPattern("error", "error"),
                SearchPattern("error_colon", "error:"),
                SearchPattern("kelvin", "k"),
            ],
        )

        self.assertEqual(
            tuple(result.categories),
            ("aba", "bab", "error", "error_colon", "kelvin"),
        )
        expected_spans = {
            "aba": [(0, 3)],
            "bab": [(1, 4)],
            "error": [(6, 11)],
            "error_colon": [(6, 12)],
            "kelvin": [(13, 14)],
        }
        for key, spans in expected_spans.items():
            self.assertEqual(
                [
                    (span.start, span.end)
                    for span in result.category(key).excerpts[0].lines[0].match_spans
                ],
                spans,
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
                SearchPattern("literal_failure", "failure"),
                SearchPattern("literal_fatal", "fatal"),
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
