import unittest

from logreader.config import HTTP_STATUS_PATTERN_KEYS, LogreaderConfig
from logreader.core import analyze_lines
from pattern_helpers import PatternAssertions


class HttpPatternTests(PatternAssertions, unittest.TestCase):
    def assert_statuses(self, line, expected):
        patterns = LogreaderConfig(context=0, enabled_patterns=HTTP_STATUS_PATTERN_KEYS).search_patterns()
        result = analyze_lines([line], patterns)
        actual = {
            key: [
                row.text[span.start:span.end]
                for excerpt in category.excerpts for row in excerpt.lines
                for span in row.match_spans
            ]
            for key, category in result.categories.items()
            if category.match_count
        }
        self.assertEqual(actual, expected)

    def test_response_messages_and_exact_fields_cover_both_ranges(self):
        for key, code in (("http_4xx", "404"), ("http_5xx", "503")):
            self.patterns = LogreaderConfig(context=0, enabled_patterns=(key,)).search_patterns()
            examples = (
                f"HTTP/1.1 {code}",
                f"HTTP/2 {code}",
                f"upstream returned HTTP {code}",
                f"upstream returned HTTP {code}.",
                f"HTTP {code}: request rejected",
                f"HTTP{code}",
                f"HTTP status code: {code}",
                f"HTTP error: {code}",
                f"Response status code does not indicate success: {code} (Failure).",
                f"the server responded with a status of {code}",
                f"http_status={code}",
                f"httpStatusCode = {code}",
                f'{{"http.response.status_code":{code}}}',
                f'{{"http.status_code":"{code}"}}',
                f'{{"url":"https://example.org/", "http.response.status_code":{code}}}',
                f"HTTP response status={code}",
                f"HTTP request completed response_code={code}",
                f'{{"method":"GET","path":"/missing","statusCode":{code}}}',
                f'{{"status":{code},"http.request.method":"GET"}}',
                f"HttpRequestException: code={code}",
                f"Received expected HTTP {code}; retry succeeded",
                f"Received HTTP {code} as expected",
                f"Health check returned HTTP {code}",
            )
            self.assert_lines_match(examples, True)

    def test_unrelated_numbers_and_fields_do_not_match_either_range(self):
        for key, code in (("http_4xx", "404"), ("http_5xx", "503")):
            self.patterns = LogreaderConfig(context=0, enabled_patterns=(key,)).search_patterns()
            self.assert_lines_match((
                f"processed {code} records",
                f"duration: {code} ms",
                f"2026-09-28 12:00:00,{code} INFO Ready",
                f'{{"duration_ms":{code},"http.response.status_code":200}}',
                f"response_size={code}",
                f"error_count={code}",
                f"HTTP response response_size={code}",
                f'HTTP response {{"error_count":{code}}}',
                f"port={code}",
                f"smtp status={code}",
                f"HTTP request completed; result={code}",
                f"HTTP request parameter code={code}",
                f'{{"http.request.method":"GET","other":{{"code":{code}}}}}',
                f"GET /?status={code} HTTP/1.1",
                f"https://example.org/?http_status={code}",
                f"/errors/HTTP{code}",
                f"request_id=HTTP{code}",
                f"HTTP {code}0",
                f"HTTP {code}.5",
                f"http_status={code}ms",
                f'{{"http_status":"{code} ms"}}',
            ), False)

    def test_policies_negations_and_zero_counters_are_not_responses(self):
        for key, code in (("http_4xx", "404"), ("http_5xx", "503")):
            self.patterns = LogreaderConfig(context=0, enabled_patterns=(key,)).search_patterns()
            self.assert_lines_match((
                f"retry_on_status=[{code},500]",
                f"expected_http_status={code} actual_http_status=200",
                f"No HTTP {code} errors detected",
                f"Without any HTTP {code} responses",
                f"HTTP {code} errors: 0",
                f"HTTP {code} errors were not observed",
                f"HTTP {code} handler registered",
                f"HTTP {code} error counter=7",
                f"Configured HTTP {code}",
                f"Expected HTTP {code}",
                f'Expected "GET / HTTP/1.1" {code}',
                f'No "GET / HTTP/1.1" {code} responses',
                f"retry_on_status=[HTTP {code}]",
                f'{{"expected":{{"http.status_code":{code}}}}}',
                f'{{"settings":{{"httpStatus":{code}}}}}',
            ), False)

    def test_access_logs_only_highlight_status_not_sizes_requests_or_headers(self):
        prefix = '127.0.0.1 - - [28/Sep/2026:12:00:00 +0200] '
        for status, expected in (
            ("200", {}), ("404", {"http_4xx": ["404"]}), ("503", {"http_5xx": ["503"]}),
        ):
            for size in ("404", "500", "-", "12345"):
                for headers in ("", ' "https://example.org/?status=503" "Agent HTTP 500"'):
                    with self.subTest(status=status, size=size, headers=headers):
                        self.assert_statuses(
                            prefix + f'"GET /?http_status=500 HTTP/1.1" {status} {size}' + headers,
                            expected,
                        )
        self.assert_statuses(prefix + '"-" 400 500', {"http_4xx": ["400"]})
        self.assert_statuses('INFO: 127.0.0.1:500 - "GET / HTTP/1.1" 404 Not Found', {"http_4xx": ["404"]})
        self.assert_statuses('INFO: 127.0.0.1:404 - "GET / HTTP/1.1" 503 Service Unavailable', {"http_5xx": ["503"]})

    def test_mixed_fields_and_messages_only_highlight_observed_statuses(self):
        examples = (
            ('{"http.response.status_code":503,"duration_ms":450}', {"http_5xx": ["503"]}),
            ("retry_on_status=500; upstream responded with HTTP 503", {"http_5xx": ["503"]}),
            ("expected_http_status=404 actual_http_status=503", {"http_5xx": ["503"]}),
            ("No HTTP 500 errors; HTTP 404 received", {"http_4xx": ["404"]}),
            ("HTTP 404 handler registered; received HTTP 503", {"http_5xx": ["503"]}),
            ('{"expected":{"httpStatus":404},"httpStatus":503}', {"http_5xx": ["503"]}),
            ("HTTP 404 followed by HTTP 503", {"http_4xx": ["404"], "http_5xx": ["503"]}),
        )
        for line, expected in examples:
            with self.subTest(line=line):
                self.assert_statuses(line, expected)

    def test_internal_noise_checks_preserve_other_patterns_and_context(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("http_4xx", "http_5xx", "error_colon"),
        ).search_patterns()
        lines = ["ERROR: expected_http_status=404", "retry_on_status=500; HTTP 503", "context"]
        for combined in (False, True):
            result = analyze_lines(lines, patterns, combined=combined)
            self.assertEqual(result.category_match_counts, {"error_colon": 1, "http_4xx": 0, "http_5xx": 1})
            category = result.category("combined" if combined else "http_5xx")
            self.assertEqual([row.text for excerpt in category.excerpts for row in excerpt.lines], lines)
            if not combined:
                self.assertEqual([row.is_match for row in category.excerpts[0].lines], [False, True, False])
