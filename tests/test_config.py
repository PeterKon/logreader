import unittest

from logreader.config import (
    DEFAULT_ENABLED_PATTERNS,
    HTTP_STATUS_PATTERN_KEYS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
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
            "warning",
            "warning_generic",
            "exception",
            "exception_generic",
            "failed",
            "fatal",
            "failure",
            "critical",
            "illegal",
            "invalid",
            "aborted",
            "terminated",
            "timeout",
            "uninitialized",
            "not_found",
            "http_4xx",
            "http_5xx",
        )
        config = LogreaderConfig(enabled_patterns=tuple(reversed(PATTERN_KEYS)))

        self.assertEqual(PATTERN_KEYS, expected_order)
        self.assertEqual(
            PATTERN_KEYS,
            PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS + HTTP_STATUS_PATTERN_KEYS,
        )
        self.assertEqual(
            DEFAULT_ENABLED_PATTERNS,
            ("error_colon", "error", "failed", "fatal"),
        )
        self.assertEqual(
            tuple(pattern.key for pattern in config.search_patterns()),
            expected_order,
        )

    def test_http_status_patterns_match_exact_three_digit_numeric_runs(self):
        config = LogreaderConfig(enabled_patterns=HTTP_STATUS_PATTERN_KEYS)
        analysis = analyze_lines(
            [
                "HTTP/1.1 400 Bad Request",
                "HTTP/1.1 404 Not Found",
                "status=499",
                "HTTP404 and upstream 503",
                "server returned 500",
                "retry failed with [599]",
                "ignore 1404, 5000, 399, 600, 4xx, and 5xx",
            ],
            config.search_patterns(),
        )

        client_errors = analysis.category("http_4xx")
        server_errors = analysis.category("http_5xx")
        self.assertEqual(client_errors.match_count, 4)
        self.assertEqual(server_errors.match_count, 3)
        self.assertEqual(
            tuple(
                line.text[span.start : span.end]
                for excerpt in client_errors.excerpts
                for line in excerpt.lines
                for span in line.match_spans
            ),
            ("400", "404", "499", "404"),
        )
        self.assertEqual(
            tuple(
                line.text[span.start : span.end]
                for excerpt in server_errors.excerpts
                for line in excerpt.lines
                for span in line.match_spans
            ),
            ("503", "500", "599"),
        )

    def test_http_status_patterns_reject_identifier_and_url_values(self):
        config = LogreaderConfig(enabled_patterns=HTTP_STATUS_PATTERN_KEYS)
        analysis = analyze_lines(
            [
                "studio/sessions/5fd2c3c2-4a95-4a98-8dc5-451162f0f383/"
                "foreground/submissions/697CE459-A458-B64A-A81E-8551BBB687A1/"
                "longpoll?start=458&logType=html:1 Failed to load resource: "
                "the server responded with a status of 500 "
                "(Internal Server Error)",
                "ignore order-404-value, port=500, and /errors/404?retry=500",
            ],
            config.search_patterns(),
        )

        self.assertEqual(analysis.category("http_4xx").match_count, 0)
        server_errors = analysis.category("http_5xx")
        self.assertEqual(server_errors.match_count, 1)
        self.assertEqual(
            tuple(
                line.text[span.start : span.end]
                for excerpt in server_errors.excerpts
                for line in excerpt.lines
                for span in line.match_spans
            ),
            ("500",),
        )

    def test_http_status_patterns_keep_liberal_status_exceptions(self):
        config = LogreaderConfig(enabled_patterns=HTTP_STATUS_PATTERN_KEYS)
        analysis = analyze_lines(
            [
                "HTTP404NotFound",
                "statusCode404",
                "status=499",
                "response_code = 422",
                "error-result-451",
                "plain [418]",
                "httpStatus500InternalServerError",
                "response_code=503",
                "rc = 599",
                "result=500",
                "server-502",
                "plain (504)",
            ],
            config.search_patterns(),
        )

        self.assertEqual(analysis.category("http_4xx").match_count, 6)
        self.assertEqual(analysis.category("http_5xx").match_count, 6)

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
