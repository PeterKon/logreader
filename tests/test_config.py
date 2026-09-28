import unittest

from logreader.config import (
    COMBINED_CATEGORY_LABEL,
    DATABASE_PATTERN_KEYS,
    DEFAULT_ENABLED_PATTERNS,
    HTTP_STATUS_PATTERN_KEYS,
    NETWORK_PATTERN_KEYS,
    PAIRED_PATTERN_KEYS,
    PATTERN_KEYS,
    SYSTEM_RUNTIME_PATTERN_KEYS,
    TEXT_PATTERN_KEYS,
    LogreaderConfig,
)
from logreader.core import COMBINED_CATEGORY_KEY, analyze_lines


class LogreaderConfigTests(unittest.TestCase):

    def test_regex_exclusions_override_matches_and_keep_context(self):
        self.assertEqual(
            LogreaderConfig(regex_patterns=("skip",)).regex_pattern_exclude, (False,),
        )
        config = LogreaderConfig(
            context=2, enabled_patterns=("error_colon",), custom_patterns=("ERROR",),
            regex_patterns=(r"(?i)(?=.*skip\d+)", "ERROR"),
            regex_pattern_exclude=(True, False),
        )
        for combined in (False, True):
            result = analyze_lines(
                ["ERROR: keep", "ERROR: SKIP42", "ERROR: skip7"],
                config.search_patterns(), combined=combined,
            )
            self.assertEqual(result.category_match_counts, {
                "error_colon": 1, "custom_1": 1, "regex_2": 1,
            })
            category = result.category("combined" if combined else "error_colon")
            self.assertEqual(
                [line.is_match for line in category.excerpts[0].lines],
                [True, False, False],
            )
        for flags in ((True, False), ("true",)):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                LogreaderConfig(regex_patterns=("skip",), regex_pattern_exclude=flags)
        with self.assertRaises(ValueError):
            LogreaderConfig(regex_patterns=("[",), regex_pattern_exclude=(True,)).search_patterns()

    def test_exclude_options_default_off_and_reach_engine_patterns(self):
        config = LogreaderConfig(custom_patterns=("skip", "Keep"))
        self.assertEqual(config.custom_pattern_exclude, (False, False))
        config = LogreaderConfig(
            enabled_patterns=("error_colon", "http_5xx"),
            custom_patterns=("skip", "Keep"), custom_pattern_exclude=(True, False),
            regex_patterns=("ERROR",),
        )
        result = analyze_lines(["ERROR: skip HTTP 500", "Keep"], config.search_patterns())
        self.assertEqual(result.category_match_counts, {
            "error_colon": 0, "http_5xx": 0, "custom_2": 1, "regex_1": 0,
        })
        for flags in ((True,), (True, False, True), (True, "false")):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                LogreaderConfig(custom_patterns=("skip", "Keep"), custom_pattern_exclude=flags)

    def test_custom_match_case_defaults_and_validation(self):
        config = LogreaderConfig(custom_patterns=("Error", "Error"))
        self.assertEqual(config.custom_pattern_match_case, (False, False))
        config = LogreaderConfig(
            enabled_patterns=(), custom_patterns=("Error", "Error"),
            custom_pattern_match_case=(True, False),
        )
        self.assertEqual(
            tuple(pattern.case_sensitive for pattern in config.search_patterns()),
            (True, False),
        )
        for flags in ((True,), (True, False, True), (True, "false")):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                LogreaderConfig(
                    custom_patterns=("Error", "Error"),
                    custom_pattern_match_case=flags,
                )

    def test_defaults_enable_high_signal_patterns_with_shared_context(self):
        config = LogreaderConfig()
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            [
                "error_colon",
                "error",
                "exception",
                "exception_generic",
                "failed",
                "failure",
                "fatal",
                "critical",
                "refused",
            ],
        )
        self.assertEqual(patterns[0].context, 5)
        self.assertEqual(patterns[1].context, 5)
        self.assertEqual(patterns[1].excluded_substrings, ("error:",))
        self.assertEqual(config.regex_patterns, ())
        self.assertTrue(config.separate_entries)
        self.assertTrue(config.combined_view)

    def test_combined_view_has_a_single_category_label(self):
        config = LogreaderConfig(combined_view=True)

        self.assertTrue(config.combined_view)
        self.assertEqual(
            config.label_for(COMBINED_CATEGORY_KEY),
            COMBINED_CATEGORY_LABEL,
        )

    def test_patterns_have_a_stable_logical_display_order(self):
        expected_order = (
            "error_colon",
            "error",
            "exception",
            "exception_generic",
            "warning",
            "warning_generic",
            "failed",
            "failure",
            "fatal",
            "critical",
            "invalid",
            "illegal",
            "not_found",
            "uninitialized",
            "refused",
            "denied",
            "unauthorized",
            "expired",
            "aborted",
            "terminated",
            "timeout",
            "unavailable",
            "http_4xx",
            "http_5xx",
            "connection_failures",
            "reachability_timeouts",
            "tls_certificates",
            "database_connections",
            "database_queries",
            "database_transactions",
            "files_storage",
            "memory_resources",
            "crashes_hangs",
        )
        config = LogreaderConfig(enabled_patterns=tuple(reversed(PATTERN_KEYS)))

        self.assertEqual(PATTERN_KEYS, expected_order)
        self.assertEqual(
            PATTERN_KEYS,
            PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS + NETWORK_PATTERN_KEYS
            + DATABASE_PATTERN_KEYS + SYSTEM_RUNTIME_PATTERN_KEYS,
        )
        self.assertEqual(
            DEFAULT_ENABLED_PATTERNS,
            (
                "error_colon",
                "error",
                "exception",
                "exception_generic",
                "failed",
                "failure",
                "fatal",
                "critical",
                "refused",
            ),
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

    def test_connection_failures_recognize_messages_codes_and_network_context(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("connection_failures",),
        ).search_patterns()
        examples = (
            "connect ECONNREFUSED 127.0.0.1:8080",
            "read ECONNRESET",
            "write WSAECONNABORTED",
            "socket WSAENETRESET",
            "listen EADDRINUSE",
            "bind WSAEADDRNOTAVAIL",
            "send ENOTCONN",
            "net::ERR_CONNECTION_CLOSED",
            "net::ERR_CONNECTION_FAILED",
            "ConnectionRefusedError: target rejected the request",
            "ConnectionResetError: peer disconnected",
            "ConnectionAbortedError: software abort",
            "java.net.BindException: Cannot bind",
            "[WinError 10061] target rejected the request",
            "SocketException (10054): transport stopped",
            "Winsock error: 10048",
            "No connection could be made because the target machine actively refused it",
            "Software caused connection abort",
            "CONNECTION REFUSED by upstream",
            "connection was reset by peer",
            "Connection has been forcibly closed by the remote host",
            "connection dropped during transfer",
            "Lost connection to MySQL server during query",
            "connection closed unexpectedly",
            "upstream prematurely closed connection",
            "server closed the connection unexpectedly",
            "Error: socket hang up",
            "socket read failed",
            "socket error: access denied",
            "failed to connect to server",
            "Unable to connect to https://example.test",
            "Failed to establish a connection",
            "failed to bind to 127.0.0.1:8080",
            "could not bind to [::1]:8080",
            "bind() failed for socket",
            "port 8080 is already in use",
            "listen: address already in use",
            "bind: cannot assign requested address",
            "socket write: broken pipe",
            "tcp write EPIPE",
            "BrokenPipeError while writing to connection",
            "retry succeeded after ECONNRESET",
        )
        for line in examples:
            with self.subTest(line=line):
                category = analyze_lines([line], patterns).category("connection_failures")
                self.assertEqual(category.match_count, 1)
                self.assertTrue(category.excerpts[0].lines[0].match_spans)

    def test_connection_failures_reject_normal_states_and_ambiguous_text(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("connection_failures",),
        ).search_patterns()
        examples = (
            "connection closed normally",
            "socket closed by user",
            "connection established",
            "reset connection requested by administrator",
            "connection reset requested",
            "connection reset handler registered",
            "socket error handler installed",
            "connection reset count=0",
            "no connection reset detected",
            "without any connection failure",
            "connection refused: false",
            '"ECONNRESET": 0',
            "connection reset not observed",
            "retry_on=ECONNRESET",
            'expected_errors=["ECONNREFUSED"]',
            "ECONNRESET_count=0",
            "MY_ECONNREFUSED_ERROR",
            "WinError 100610",
            "order=10054; port=10061",
            "broken pipe while writing stdout",
            "subprocess write EPIPE",
            "BrokenPipeError while writing to a FIFO",
            "email address already in use",
            "failed to bind configuration property",
            "could not connect the graph nodes",
            "socket opened; local pipe write EPIPE",
            "connection timeout=30",
            "connection timed out",
            "host unreachable",
            "DNS lookup failed",
            "TLS handshake failed",
            "WSAEWOULDBLOCK",
            "EINPROGRESS",
        )
        for line in examples:
            with self.subTest(line=line):
                result = analyze_lines([line], patterns)
                self.assertEqual(result.category_match_counts["connection_failures"], 0)

    def test_connection_failure_noise_checks_preserve_other_matches_and_context(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("connection_failures", "error_colon"),
        ).search_patterns()
        lines = [
            "no connection reset; ERROR: socket hang up, ECONNRESET",
            "no connection reset; ERROR: disk full",
            "retry_on=ECONNRESET; connection refused",
        ]
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 2, "connection_failures": 2,
                })
                category = result.category("combined" if combined else "connection_failures")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], lines)
                highlights = [
                    [line.text[span.start:span.end] for span in line.match_spans]
                    for line in rendered
                ]
                self.assertNotIn("connection reset", highlights[0])
                self.assertIn("socket hang up", highlights[0])
                self.assertIn("ECONNRESET", highlights[0])
                self.assertEqual(highlights[2], ["connection refused"])
                if not combined:
                    self.assertEqual(highlights[1], [])

    def test_reachability_timeouts_recognize_network_dns_and_timeout_failures(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("reachability_timeouts",),
        ).search_patterns()
        examples = (
            "connect ENETUNREACH 192.0.2.1",
            "send EHOSTUNREACH",
            "WSAENETDOWN",
            "EHOSTDOWN",
            "connect ETIMEDOUT",
            "WSAETIMEDOUT",
            "getaddrinfo EAI_AGAIN example.test",
            "EAI_NONAME",
            "EAI_NODATA",
            "EAI_FAIL",
            "getaddrinfo ENOTFOUND example.test",
            "CURLE_COULDNT_RESOLVE_HOST",
            "CURLE_COULDNT_RESOLVE_PROXY",
            "CURLE_OPERATION_TIMEDOUT",
            "WSAHOST_NOT_FOUND",
            "WSATRY_AGAIN",
            "WSANO_RECOVERY",
            "WSANO_DATA",
            "net::ERR_NAME_NOT_RESOLVED",
            "net::ERR_ADDRESS_UNREACHABLE",
            "net::ERR_CONNECTION_TIMED_OUT",
            "net::ERR_DNS_TIMED_OUT",
            "net::ERR_TIMED_OUT",
            "[WinError 10060] peer did not respond",
            "SocketException (11001): lookup failed",
            "Winsock error: 10065",
            "java.net.SocketTimeoutException: Read timed out",
            "java.net.UnknownHostException: example.test",
            "java.net.NoRouteToHostException",
            "requests.exceptions.ConnectTimeout: request failed",
            "httpx.ReadTimeout",
            "httpcore.WriteTimeout",
            "Destination Host Unreachable",
            "network is unreachable",
            "gateway not reachable",
            "No route to host",
            "network is down",
            "IP routing failed",
            "DNS lookup failed",
            "name resolution failure",
            "DNS query timed out",
            "Could not resolve host: example.test",
            "unable to resolve hostname",
            "Could not resolve proxy: proxy.example.test",
            "Temporary failure in name resolution",
            "Name or service not known",
            "nodename nor servname provided, or not known",
            "getaddrinfo failed",
            "DNS response: NXDOMAIN",
            "DNS response: SERVFAIL",
            "connection timed out",
            "connection attempt timed out",
            "connect timeout after 30 seconds",
            "socket timeout during transfer",
            "request has timed out",
            "response timeout after 30s",
            "upstream timed out while reading response header",
            "504 Gateway Timeout",
            "timed out waiting for a response",
            "read timeout while receiving HTTP response",
            "socket write timed out",
            "operation timed out for https://example.test",
            "TimeoutError while connecting socket",
            "HTTP request: TimeoutException",
            "dial tcp 192.0.2.1:443: i/o timeout",
            'Get "https://example.test": context deadline exceeded',
            "rpc error: deadline exceeded",
            "curl: (28) Operation timed out after 30000 milliseconds",
            "retry succeeded after request timed out",
        )
        for line in examples:
            with self.subTest(line=line):
                category = analyze_lines([line], patterns).category("reachability_timeouts")
                self.assertEqual(category.match_count, 1)
                self.assertTrue(category.excerpts[0].lines[0].match_spans)

    def test_reachability_timeouts_reject_settings_and_unrelated_operations(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("reachability_timeouts",),
        ).search_patterns()
        examples = (
            "connection timeout=30",
            "connection timeout=30s",
            '"connection timeout": 3000',
            "connect_timeout=30",
            "request timeout 500ms",
            "response timeout is 30 seconds",
            "socket timeout of 1.5s",
            "default connection timeout",
            "configured request timeout",
            "request timeout set to 10s",
            "request timeout handler registered",
            "request timeout count=5",
            "socket timeout disabled",
            "no connection timeout",
            "without any DNS lookup failure",
            "DNS lookup failed: false",
            '"NXDOMAIN": 0',
            "DNS lookup failure not observed",
            "retry_on=EAI_AGAIN",
            "expected_errors=WSAETIMEDOUT",
            "MY_EAI_AGAIN_CODE",
            "ERR_CONNECTION_TIMED_OUT_count=0",
            "WinError 100600",
            "order=11001; port=10060",
            "HTTP status=408",
            "HTTP status=504",
            "DNS lookup succeeded",
            "host is reachable",
            "request completed in 30s",
            "unreachable code detected",
            "route not found for /settings",
            "failed to resolve dependency",
            "ENOTFOUND while loading a local resource",
            "ETIMEDOUT reading a local device",
            "TimeoutError waiting for a worker",
            "TimeoutException acquiring a lock",
            "database query timeout",
            "job timed out",
            "read timeout from local disk",
            "local file read: i/o timeout",
            "background job: context deadline exceeded",
            "HTTP request completed; operation timed out waiting for lock",
            "connection refused",
            "ECONNRESET",
            "TLS certificate expired",
        )
        for line in examples:
            with self.subTest(line=line):
                result = analyze_lines([line], patterns)
                self.assertEqual(result.category_match_counts["reachability_timeouts"], 0)

    def test_reachability_noise_checks_preserve_other_matches_and_context(self):
        patterns = LogreaderConfig(
            context=1,
            enabled_patterns=("reachability_timeouts", "connection_failures", "error_colon"),
        ).search_patterns()
        lines = [
            "connection timeout=30s; ERROR: request timed out; DNS lookup failed",
            "no DNS lookup failure; ERROR: connection refused",
            "retry_on=EAI_AGAIN; network is unreachable",
        ]
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 2, "connection_failures": 1, "reachability_timeouts": 2,
                })
                category = result.category("combined" if combined else "reachability_timeouts")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], lines)
                highlights = [
                    [line.text[span.start:span.end] for span in line.match_spans]
                    for line in rendered
                ]
                self.assertNotIn("connection timeout", highlights[0])
                self.assertIn("request timed out", highlights[0])
                self.assertIn("DNS lookup failed", highlights[0])
                self.assertEqual(highlights[2], ["network is unreachable"])
                if not combined:
                    self.assertEqual(highlights[1], [])

    def test_tls_certificates_recognize_handshake_trust_and_identity_failures(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("tls_certificates",),
        ).search_patterns()
        examples = (
            "ERR_TLS_CERT_ALTNAME_INVALID",
            "ERR_TLS_HANDSHAKE_TIMEOUT",
            "net::ERR_CERT_AUTHORITY_INVALID",
            "net::ERR_CERT_DATE_INVALID",
            "net::ERR_SSL_VERSION_OR_CIPHER_MISMATCH",
            "CERT_HAS_EXPIRED",
            "X509_V_ERR_CERT_NOT_YET_VALID",
            "X509_V_ERR_HOSTNAME_MISMATCH",
            "DEPTH_ZERO_SELF_SIGNED_CERT",
            "SELF_SIGNED_CERT_IN_CHAIN",
            "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
            "UNABLE_TO_GET_ISSUER_CERT_LOCALLY",
            "CERTIFICATE_VERIFY_FAILED",
            "SSLV3_ALERT_HANDSHAKE_FAILURE",
            "TLSV1_ALERT_UNKNOWN_CA",
            "TLS1_ALERT_CERTIFICATE_EXPIRED",
            "SEC_E_UNTRUSTED_ROOT",
            "SEC_E_CERT_EXPIRED",
            "Schannel: SEC_E_ILLEGAL_MESSAGE",
            "TLS: SEC_E_WRONG_PRINCIPAL",
            "CERT_E_CN_NO_MATCH",
            "CRYPT_E_REVOKED",
            "CURLE_SSL_CONNECT_ERROR",
            "CURLE_PEER_FAILED_VERIFICATION",
            "CURLE_SSL_CACERT_BADFILE",
            "javax.net.ssl.SSLHandshakeException: peer rejected handshake",
            "SSLPeerUnverifiedException",
            "ssl.SSLCertVerificationError",
            "CertificateExpiredException",
            "RemoteCertificateNameMismatch",
            "RemoteCertificateChainErrors",
            "TLS handshake failed",
            "SSLv3 handshake failure",
            "TLSv1.3 negotiation failed",
            "SSL connection error",
            "SSL_do_handshake() failed",
            "Could not create SSL/TLS secure channel",
            "failed to establish a secure connection",
            "secure channel failure",
            "certificate has expired",
            "certificate is not yet valid",
            "certificate is not trusted",
            "The remote certificate is invalid according to the validation procedure",
            "untrusted certificate",
            "certificate verification failed",
            "certificate verify failed: self-signed certificate",
            "failed to validate the certificate",
            "x509: certificate signed by unknown authority",
            "unable to get local issuer certificate",
            "unable to verify the first certificate",
            "PKIX path building failed",
            "x509: certificate is valid for example.test, not other.test",
            "Hostname/IP does not match certificate's altnames",
            "TLS: hostname mismatch",
            "SSL: handshake failure",
            "OpenSSL: no shared cipher",
            "SSL: wrong version number",
            "verify error:num=18:self-signed certificate",
            "retry succeeded after TLS handshake failed",
        )
        for line in examples:
            with self.subTest(line=line):
                category = analyze_lines([line], patterns).category("tls_certificates")
                self.assertEqual(category.match_count, 1)
                self.assertTrue(category.excerpts[0].lines[0].match_spans)

    def test_tls_certificates_reject_routine_states_and_unrelated_failures(self):
        patterns = LogreaderConfig(
            context=0, enabled_patterns=("tls_certificates",),
        ).search_patterns()
        examples = (
            "TLS handshake completed successfully",
            "SSL connection established",
            "TLSv1.3 negotiated",
            "certificate expires in 30 days",
            "certificate has not expired",
            "certificate is valid",
            "certificate verification enabled",
            "verify_certificate=false",
            "using a self-signed certificate for TLS",
            "self-signed certificate added to trust store",
            "self signed certificate loaded",
            "SSL_ERROR_WANT_READ",
            "SSL_ERROR_WANT_WRITE",
            "SSL_ERROR_ZERO_RETURN",
            "SSL error: SSL_ERROR_WANT_READ",
            "SSL error: SSL_ERROR_ZERO_RETURN",
            "TLS alert close_notify",
            "no TLS handshake failure",
            "without any certificate verification failure",
            "TLS handshake failed: false",
            "certificate expired=false",
            '"CERT_HAS_EXPIRED": 0',
            "TLS handshake failure count=0",
            "TLS handshake failure handler installed",
            "certificate verification failure not observed",
            "expected_errors=ERR_TLS_CERT_ALTNAME_INVALID",
            "retry_on=SSLV3_ALERT_HANDSHAKE_FAILURE",
            "MY_CERT_HAS_EXPIRED_ERROR",
            "ERR_CERT_DATE_INVALID_count=0",
            "error=0x80090328; status=45",
            "WebSocket handshake failed",
            "SSH handshake failure",
            "hostname mismatch in configuration",
            "HOSTNAME_MISMATCH",
            "Kerberos: SEC_E_WRONG_PRINCIPAL",
            "SEC_E_ILLEGAL_MESSAGE",
            "package has wrong version number",
            "TLS initialized; SSH handshake failed",
            "ERROR disk full; loaded self-signed certificate",
            "connection refused",
            "DNS lookup failed",
            "request timed out",
            "authentication token expired",
        )
        for line in examples:
            with self.subTest(line=line):
                result = analyze_lines([line], patterns)
                self.assertEqual(result.category_match_counts["tls_certificates"], 0)

    def test_tls_noise_checks_preserve_other_matches_and_context(self):
        patterns = LogreaderConfig(
            context=1,
            enabled_patterns=("tls_certificates", "reachability_timeouts", "error_colon"),
        ).search_patterns()
        lines = [
            "no TLS handshake failure; ERROR: certificate has expired; CERT_HAS_EXPIRED",
            "using self-signed certificate; ERROR: request timed out",
            "retry_on=ERR_CERT_DATE_INVALID; TLS handshake failed",
        ]
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 2, "reachability_timeouts": 1, "tls_certificates": 2,
                })
                category = result.category("combined" if combined else "tls_certificates")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], lines)
                highlights = [
                    [line.text[span.start:span.end] for span in line.match_spans]
                    for line in rendered
                ]
                self.assertNotIn("TLS handshake failure", highlights[0])
                self.assertIn("certificate has expired", highlights[0])
                self.assertIn("CERT_HAS_EXPIRED", highlights[0])
                self.assertEqual(highlights[2], ["TLS handshake failed"])
                if not combined:
                    self.assertEqual(highlights[1], [])

    def test_new_operational_state_patterns_are_searchable(self):
        keys = (
            "aborted",
            "terminated",
            "timeout",
            "uninitialized",
            "not_found",
            "denied",
            "refused",
            "unauthorized",
            "expired",
        )
        config = LogreaderConfig(enabled_patterns=keys)
        analysis = analyze_lines(
            [
                "Job ABORTED by operator",
                "Session terminated unexpectedly",
                "Connection timeout",
                "Variable is uninitialized",
                "Requested resource not found",
                "Access denied by policy",
                "Connection refused by upstream",
                "Request unauthorized",
                "Certificate expired",
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
            max_lines_scanned=10,
            enabled_patterns=("warning", "exception"),
            custom_patterns=(" timeout ",),
            regex_patterns=(r" ERROR\s+[0-9]+ ",),
            separate_entries=True,
        )
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            ["exception", "warning", "custom_1", "regex_1"],
        )
        self.assertEqual(config.custom_patterns, ("timeout",))
        self.assertEqual(config.regex_patterns, (r"ERROR\s+[0-9]+",))
        self.assertTrue(all(pattern.context == 5 for pattern in patterns))
        self.assertEqual(config.label_for("custom_1"), "timeout")
        self.assertEqual(config.label_for("regex_1"), r"ERROR\s+[0-9]+")
        self.assertTrue(patterns[-1].is_regex)
        self.assertTrue(config.separate_entries)

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Context cannot be negative"):
            LogreaderConfig(context=-1)
        with self.assertRaisesRegex(ValueError, "Max lines scanned must be a positive integer"):
            LogreaderConfig(max_lines_scanned=0)
        with self.assertRaisesRegex(ValueError, "Unknown pattern"):
            LogreaderConfig(enabled_patterns=("unknown",))
        with self.assertRaisesRegex(ValueError, "Custom patterns cannot be empty"):
            LogreaderConfig(custom_patterns=(" ",))
        with self.assertRaisesRegex(ValueError, "Regex patterns cannot be empty"):
            LogreaderConfig(regex_patterns=(" ",))


if __name__ == "__main__":
    unittest.main()
