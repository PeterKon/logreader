import unittest
from unittest.mock import patch

from logreader.cancellation import AnalysisCancelled, CancellationToken
from logreader.core import ResultLine, SearchPattern, analyze_lines


class CancellationTests(unittest.TestCase):
    def test_cancelled_before_start_does_not_consume_input(self):
        token = CancellationToken()
        token.cancel()

        def lines():
            self.fail("A cancelled analysis consumed input")
            yield "ERROR"

        with self.assertRaises(AnalysisCancelled):
            analyze_lines(lines(), [SearchPattern("error", "ERROR")], cancellation=token)

    def test_cancellation_between_matches_stops_literal_and_regex_scans(self):
        for regex, shared in ((False, False), (False, True), (True, False)):
            with self.subTest(regex=regex, shared=shared):
                token = CancellationToken()
                calls = []

                def validate(line, start, end):
                    calls.append(start)
                    token.cancel()
                    return True

                patterns = [SearchPattern("error", "ERROR", is_regex=regex, match_validator=validate)]
                if shared:
                    patterns.append(SearchPattern("other", "other"))
                with self.assertRaises(AnalysisCancelled):
                    analyze_lines(("ERROR " * 100,) * 100, patterns, cancellation=token)
                self.assertEqual(len(calls), 1)

    def test_cancellation_during_result_construction_returns_no_partial_result(self):
        for combined in (False, True):
            with self.subTest(combined=combined):
                token = CancellationToken()
                built = []

                def build_line(**kwargs):
                    built.append(kwargs["number"])
                    if len(built) == 3:
                        token.cancel()
                    return ResultLine(**kwargs)

                with patch("logreader.core.ResultLine", side_effect=build_line):
                    with self.assertRaises(AnalysisCancelled):
                        analyze_lines(("ERROR",) * 100, [SearchPattern("error", "ERROR")],
                                      combined=combined, cancellation=token)
                self.assertEqual(built, [1, 2, 3])

    def test_uncancelled_token_preserves_analysis_results(self):
        patterns = [SearchPattern("error", "ERROR", context=2), SearchPattern("failed", "failed")]
        lines = ("before", "ERROR failed", "after", "failed")
        for combined in (False, True):
            self.assertEqual(
                analyze_lines(lines, patterns, combined=combined),
                analyze_lines(lines, patterns, combined=combined, cancellation=CancellationToken()),
            )
