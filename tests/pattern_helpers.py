"""Assertions shared by tests for built-in failure patterns."""

from logreader.core import analyze_lines


class PatternAssertions:
    def assert_lines_match(self, lines, expected):
        for line in lines:
            with self.subTest(line=line):
                result = analyze_lines([line], self.patterns).category(self.patterns[0].key)
                self.assertEqual(result.match_count, int(expected))
                if expected:
                    self.assertTrue(result.excerpts[0].lines[0].match_spans)
