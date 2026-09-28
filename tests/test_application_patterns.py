import unittest

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines
from pattern_helpers import PatternAssertions


class AccessCredentialsPatternTests(PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("access_credentials",),
        ).search_patterns()

    def test_authentication_and_rejected_credentials(self):
        self.assert_lines_match((
            "Authentication failed", "client authentication has failed",
            "authorization denied", "authorisation failure", "login failed for user alice",
            "sign-in rejected", "Failed to authenticate user", "Unable to sign in",
            "Failed authentication for user alice", "Wrong password",
            "sshd[123]: Failed password for invalid user guest from 10.0.0.1",
            "Failed publickey for alice", "Invalid credentials", "incorrect password",
            "bad credentials", "credentials were rejected", "password has expired", "password is incorrect",
            "incorrect username or password", "username or password is invalid",
            "invalid API key", "client secret expired",
            "org.springframework.security.authentication.BadCredentialsException: Bad credentials",
            "CredentialsExpiredException", "AuthenticationCredentialsNotFoundException",
            "AADSTS50126", "AADSTS7000215: Invalid client secret provided",
            "AADSTS7000222", "UnrecognizedClientException",
            "ERROR handled invalid credentials for user alice",
            "caught BadCredentialsException: Bad credentials",
        ), True)

    def test_invalid_expired_and_revoked_authentication_tokens(self):
        self.assert_lines_match((
            "access token expired", "The refresh token has expired", "revoked bearer token",
            "security token is invalid", "Invalid ID token", "JWT expired",
            "TokenExpiredError: jwt expired", "JsonWebTokenError: invalid signature",
            "jwt.exceptions.ExpiredSignatureError: Signature has expired",
            "jwt.exceptions.InvalidTokenError", "jwt.InvalidSignatureError",
            "ImmatureSignatureError", "SecurityTokenExpiredException",
            "SecurityTokenInvalidAudienceException", "ExpiredTokenException",
            "InvalidClientTokenId", "AADSTS700082",
            'WWW-Authenticate: Bearer error="invalid_token"',
            '{"error":"invalid_grant","error_description":"Token revoked"}',
            'error=invalid_client', 'error_code="unauthorized_client"',
            "OAuth insufficient_scope", "OAuth token expired", "Bearer invalid token",
            "token expired", "expired token", "token has been revoked",
            "JWT signature verification failed", "SAML invalid signature",
        ), True)

    def test_application_denials_and_account_lockouts(self):
        self.assert_lines_match((
            "Application access denied", "API access rejected", "access denied for user alice",
            "permission denied for application dashboard", "AccessDeniedException: IAM policy denies action",
            "User arn:aws:iam::123:user/alice is not authorized to perform: s3:GetObject",
            "user not authorized to access dashboard", 'OAuth error="access_denied"',
            "ForbiddenException: API endpoint restricted", "user account is locked",
            "An error occurred (AccessDenied) when calling the GetObject operation: denied",
            "user is locked out",
            'account "alice" has been locked out', "Account lockout detected",
            "account was disabled", "AADSTS50053", "AADSTS50055", "AADSTS50057",
            "org.springframework.security.authentication.LockedException",
            "AuthenticationException: login rejected",
        ), True)

    def test_normal_activity_settings_counters_and_negations(self):
        self.assert_lines_match((
            "Authentication succeeded", "login successful", "access granted",
            "access token expires in 300 seconds", "token refresh completed",
            "refreshing access token before expiry", "account unlocked", "account is not locked",
            "password not expired", "no authentication failures", "without any invalid credentials",
            "no jwt.exceptions.ExpiredSignatureError", "expected jwt.ExpiredSignatureError",
            "no new account lockout", "expected invalid credentials", "simulated login failed",
            "configured account lockout", "account lockout threshold=5", "account lockout duration=30",
            "authentication failure handler registered", "invalid token handler registered for OAuth",
            "failed login attempts=0",
            "invalid credentials count=0", "authentication failure events=0",
            '"invalid_token": false', 'error="invalid_token": false',
            '"account locked": false', "AADSTS50126=0", "access token expired not observed",
            'expected_errors=["BadCredentialsException", "ExpiredToken"]',
            'retry_on=["invalid_grant", "invalid_token"]',
            "except jwt.exceptions.InvalidTokenError:", "catch (BadCredentialsException ex)",
            "at org.springframework.security.authentication.BadCredentialsException.java:42",
            "MY_EXPIREDTOKEN_SETTING", "AADSTS501260", "AADSTS70016: AuthorizationPending",
            "JWT signature verification succeeded", "OAuth authorization pending",
        ), False)

    def test_ambiguous_permissions_tokens_and_unrelated_failures(self):
        self.assert_lines_match((
            "access denied", "permission denied", "AccessDeniedException", "UnauthorizedAccessException",
            "HTTP 401 Unauthorized", "HTTP 403 Forbidden", "status=401", "403", "expired", "rejected",
            "invalid token", "SyntaxError: invalid token at line 1", 'parser error="invalid_token"',
            "invalid signature on package archive", "checksum signature failed",
            "API file access denied", "permission denied for directory /data user=alice",
            "user not authorized to access file /data",
            "java.nio.file.AccessDeniedException: /data/user", "database access denied for user alice",
            "MySQL: Access denied for user 'app'", "permission denied for table users",
            "file lock conflict", "account database is locked", "certificate expired",
            "OAuth ready; invalid token", "user authenticated | access denied",
            "AWS IAM ready; file access denied", "LockedException: database busy",
            "invalid username format", "invalid client identifier in connection settings",
        ), False)

    def test_local_exclusions_preserve_real_failures_and_other_categories(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("access_credentials", "files_storage", "error_colon"),
        ).search_patterns()
        lines = (
            "no authentication failures; ERROR: credentials rejected",
            "account lockout threshold=5; ERROR: disk full",
            'expected_errors=["ExpiredToken"]; invalid API key',
            '"account locked": false, access token expired',
            'Bearer error="invalid_token": access token expired',
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"error_colon": 2, "access_credentials": 4, "files_storage": 1})
                category = result.category("combined" if combined else "access_credentials")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                              for line in rendered]
                self.assertNotIn("authentication failures", highlights[0])
                self.assertIn("credentials rejected", highlights[0])
                self.assertEqual(highlights[2], ["invalid API key"])
                self.assertEqual(highlights[3], ["access token expired"])
                if not combined:
                    self.assertEqual(highlights[1], [])


class ConfigurationStartupPatternTests(PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("configuration_startup",),
        ).search_patterns()

    def test_missing_invalid_and_unreadable_settings(self):
        self.assert_lines_match((
            "Missing configuration file", "invalid configuration value for port",
            "Malformed config", "Unrecognized configuration section startup",
            "Missing required environment variable DB_HOST", "environment variable DB_HOST is not set",
            "Environment variable 'DB_HOST' is missing", "env var APP_MODE is undefined",
            "Required environment variable DB_HOST has not been set",
            "required setting 'endpoint' is missing", "invalid settings",
            "configuration file 'app.yml' not found", "config is malformed",
            "Failed to load configuration", "Unable to read the config file",
            "Could not parse configuration", "configuration validation failed",
            "Failed to bind properties under 'server.port' to java.lang.Integer",
            "Failed to bind configuration property", "Could not resolve placeholder 'DB_HOST' in value '${DB_HOST}'",
            "System.Configuration.ConfigurationErrorsException: invalid section",
            "Microsoft.Extensions.Options.OptionsValidationException: invalid options",
            "ConfigDataLocationNotFoundException", "ConfigurationPropertiesBindException",
        ), True)

    def test_missing_dependencies_and_library_loading(self):
        self.assert_lines_match((
            "ModuleNotFoundError: No module named 'requests'", "ImportError: cannot import name 'client'",
            "No module named requests", "Error: Cannot find module 'express'",
            "Cannot find package 'client' imported from /app/main.js",
            "ERR_MODULE_NOT_FOUND", "code='MODULE_NOT_FOUND'", "ERR_DLOPEN_FAILED",
            "ERR_PACKAGE_PATH_NOT_EXPORTED", "ERR_INVALID_PACKAGE_CONFIG",
            "java.lang.NoClassDefFoundError: com/example/Main", "ClassNotFoundException",
            "UnsatisfiedLinkError", "DllNotFoundException", "Could not load file or assembly 'Client'",
            "Unable to load shared library 'client.so'", "failed to load plugin authentication",
            "DLL load failed while importing client", "error while loading shared libraries: libssl.so",
            "missing dependency client", "unresolved dependencies", "unmet dependencies",
            "dependency resolution failed", "UnsatisfiedDependencyException",
            "caught ImportError: cannot import name client",
            "handled ModuleNotFoundError: No module named client", "ModuleNotFoundError was caught",
            "ERROR caught ImportError while starting application",
        ), True)

    def test_incompatible_versions_and_failed_initialization(self):
        self.assert_lines_match((
            "UnsupportedClassVersionError: class compiled by a more recent Java Runtime",
            "incompatible runtime version", "unsupported Python version", "Node.js version mismatch",
            ".NET version not supported", "library version incompatible", "ABI mismatch", "binary incompatibility",
            "BadImageFormatException", "ERR_REQUIRE_ESM", "ExceptionInInitializerError",
            "System.TypeInitializationException", "BeanCreationException", "BeanDefinitionStoreException",
            "Error creating bean with name 'client'", "initialization failed", "initialisation failure",
            "Unable to initialize application", "Failed to initialise plugin", "bootstrap failed",
        ), True)

    def test_startup_and_deployment_failures(self):
        self.assert_lines_match((
            "APPLICATION FAILED TO START", "Application run failed", "Startup failed",
            "start-up failure", "server failed to start", "service 'worker' failed to start",
            "Failed to start nginx.service", "Unable to start the application", "Cannot start container",
            "deployment failed", "rollout has failed", "failed to deploy application",
            'error: deployment "nginx" exceeded its progress deadline',
            "CreateContainerConfigError", "CreateContainerError", "ErrImagePull", "ImagePullBackOff",
            "ProgressDeadlineExceeded", "startup failed; retry succeeded",
            "optional configuration file not found and application failed to start",
        ), True)

    def test_normal_operation_optional_values_and_defaults(self):
        self.assert_lines_match((
            "Configuration loaded successfully", "Application started", "deployment progressing",
            "initialization complete", "startup timeout=30", "checking dependencies",
            "package requires Python >=3.10", "runtime version=3.12", "module imported successfully",
            "optional configuration file not found", "optional module missing",
            "optional dependency: ModuleNotFoundError", "optional plugin not loaded",
            "optional dependency: ModuleNotFoundError: No module named client",
            "configuration file not found, using defaults", "missing setting 'color', using defaults",
            "environment variable APP_MODE not set, falling back to defaults",
            "configuration is not invalid", "no startup failures", "no new initialization failures",
            "without any missing dependencies", "zero deployment failures", "expected ImportError",
            "simulated startup failure", "example ModuleNotFoundError",
            'expected_errors=["ImportError", "MODULE_NOT_FOUND"]',
            "if startup failed", "on deployment failure", "when ModuleNotFoundError",
        ), False)

    def test_handlers_counters_flags_and_identifier_boundaries(self):
        self.assert_lines_match((
            "except ModuleNotFoundError:", "catch (TypeInitializationException ex)",
            "ModuleNotFoundError not raised", "no caught ImportError",
            "registering handler for ImportError", "startup failure handler registered",
            "initialization failure policy=retry", "startup failures count=0",
            "deployment failures=0", '"CreateContainerConfigError": false',
            "MODULE_NOT_FOUND=0", "configuration validation failures=0",
            "startup failure was not observed",
            "at org.example.ConfigurationException.java:42", "ImportError.py:20",
            "MY_MODULE_NOT_FOUND_SETTING", "ModuleNotFoundErrorHandler", "startup_failure_count=0",
        ), False)

    def test_unrelated_failures_do_not_borrow_startup_context(self):
        self.assert_lines_match((
            "invalid password", "missing file", "invalid input", "invalid token",
            "SyntaxError: invalid JSON", "configuration parser ready; invalid input",
            "application ready; failed to start transaction", "failed to start job",
            "failed to start request", "version mismatch in HTTP protocol",
            "schema version mismatch", "certificate version not supported",
            "failed to load resource: HTTP 404", "startup probe failed",
            "Configuration complete | database connection refused",
        ), False)

    def test_local_noise_checks_preserve_highlights_context_and_other_rules(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("configuration_startup", "files_storage", "error_colon"),
        ).search_patterns()
        lines = (
            "no startup failures; ERROR: invalid configuration",
            "optional configuration file not found; ERROR: disk full",
            'expected_errors=["ImportError"]; startup failed',
            '"CreateContainerConfigError": false, deployment failed',
            "configuration file not found, using defaults; application failed to start",
            "environment variable APP_MODE not set, using defaults",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"error_colon": 2, "configuration_startup": 4, "files_storage": 2})
                category = result.category("combined" if combined else "configuration_startup")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                if not combined:
                    highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                                  for line in rendered]
                    self.assertEqual(highlights, [
                        ["invalid configuration"], [], ["startup failed"], ["deployment failed"],
                        ["application failed to start"], [],
                    ])


class DataParsingPatternTests(PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("data_parsing",),
        ).search_patterns()

    def test_malformed_input_and_format_specific_parsers(self):
        self.assert_lines_match((
            "json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
            "System.Text.Json.JsonException: invalid JSON text",
            "com.fasterxml.jackson.core.JsonParseException: unexpected character",
            "JsonReaderException", "JsonMappingException", "MismatchedInputException",
            "XMLSyntaxError", "System.Xml.XmlException", "org.xml.sax.SAXParseException",
            "xml.etree.ElementTree.ParseError: mismatched tag",
            "yaml.parser.ParserError: while parsing a block mapping",
            "yaml.scanner.ScannerError: mapping values are not allowed here",
            "InvalidProtocolBufferException", "Malformed input", "invalid payload",
            "truncated JSON", "corrupted document", "JSON parse error", "XML parsing failed",
            "Unable to parse the request body", "Failed to parse CSV", "Cannot parse response body",
            "SyntaxError: Unexpected token '<' in JSON at position 0",
            "Unexpected end of JSON input", "unexpected end of input in JSON document",
            "invalid token in XML document", "parse failure in CSV parser",
            "caught JsonException: invalid JSON", "JsonException was handled",
            "ERROR caught JSONDecodeError while decoding request body",
        ), True)

    def test_validation_requires_data_or_library_context(self):
        self.assert_lines_match((
            "input validation failed", "payload validation failure", "schema validation error",
            "document validation failed", "Failed to validate JSON",
            "validation failed for field email", "ValidationError: invalid field age",
            "pydantic_core._pydantic_core.ValidationError: 2 validation errors for User",
            "1 validation error for User", "jsonschema.exceptions.ValidationError: type mismatch",
            "marshmallow.exceptions.ValidationError", "Ajv validation failed",
            "ValidationException: request body violates schema",
            "ConstraintViolationException: input field email must not be blank",
        ), True)

    def test_encoding_and_serialization_failures(self):
        self.assert_lines_match((
            "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0",
            "UnicodeEncodeError", "UnicodeTranslateError", "DecoderFallbackException",
            "EncoderFallbackException", "MalformedInputException", "UnmappableCharacterException",
            "ERR_ENCODING_INVALID_ENCODED_DATA", "invalid UTF-8 sequence", "malformed Unicode",
            "illegal byte sequence", "invalid base64 data", "base64 decoding failed",
            "'ascii' codec can't encode character", "UTF-16 encoding error",
            "PicklingError", "pickle.UnpicklingError: invalid load key",
            "NotSerializableException", "DataCloneError", "JsonSerializationException",
            "System.Runtime.Serialization.SerializationException", "deserialization failed",
            "serialization failure", "Unable to deserialize JSON", "Cannot serialize object",
            "Could not deserialize instance of User", "object is not JSON serializable",
            "TypeError: Object of type datetime is not JSON serializable",
            "value is not serialisable", "SQL client: cannot deserialize JSON response",
            "handled UnicodeDecodeError: invalid UTF-8",
        ), True)

    def test_checksums_compressed_data_and_integrity(self):
        self.assert_lines_match((
            "checksum mismatch", "checksum verification failed", "invalid checksum",
            "checksum mismatches detected", "CRC errors detected",
            "CRC check failed", "Bad CRC-32 for file 'payload.csv'", "CRC32 mismatch",
            "data integrity check failed", "file integrity violation", "archive integrity failure",
            "BadZipFile: File is not a zip file", "gzip.BadGzipFile", "DataFormatException",
            "ERR_ZIP_INVALID_ARCHIVE", "ERR_ZIP_ENTRY_CORRUPT",
            "zlib.error: Error -3 while decompressing data: incorrect data check",
            "gzip: incorrect length check", "zlib Z_DATA_ERROR", "hash mismatch for archive download",
            "integrity check failed for payload",
        ), True)

    def test_normal_activity_counters_and_negations(self):
        self.assert_lines_match((
            "JSON parsed successfully", "payload validation succeeded", "checksum verified",
            "encoding=UTF-8", "serializer initialized", "CRC32=0x12345678", "integrity check passed",
            "request body is valid", "JSON is not malformed", "no JSONDecodeError",
            "no new checksum mismatches", "without any invalid input", "zero validation errors for User",
            "0 validation errors for User", "0 JSON parse errors", '"JSONDecodeError": false',
            '"checksum mismatch": 0', "JSON parse errors=0", "serialization failure count=0",
            "CRC check failed=false", "checksum mismatch was not observed", "JSONDecodeError not raised",
            "expected invalid JSON", "simulated checksum mismatch", "when deserialization failed",
            "invalid input handler registered", "checksum mismatch detection enabled",
            "validation error policy for JSON parser", "malformed input recovery enabled",
            'expected_errors=["UnicodeDecodeError", "JSONDecodeError"]',
        ), False)

    def test_handlers_and_identifiers_do_not_become_events(self):
        self.assert_lines_match((
            "except json.decoder.JSONDecodeError:", "catch (JsonException ex)",
            "no caught JSONDecodeError", "expected JsonException: invalid JSON",
            "registering handler for XMLSyntaxError", "class JSONDecodeError(ValueError):",
            "at com.example.JsonParseException.java:42", "JSONDecodeError.py:12",
            "MY_JSONDecodeError_SETTING", "JsonExceptionHandler", "invalid_json_allowed=true",
            "checksum_mismatch_count=0", "ERR_ENCODING_INVALID_ENCODED_DATA_EXTRA",
        ), False)

    def test_ambiguous_and_unrelated_failures_are_not_misclassified(self):
        self.assert_lines_match((
            "ValidationError", "validation failed", "SyntaxError", "invalid token", "ParseError",
            "parser ready; invalid token", "JSON parser initialized | validation failed",
            "configuration validation failed", "certificate validation failed", "JWT validation failed",
            "password validation failed for input", "validation failed for database connection",
            "OptionsValidationException", "SecurityTokenValidationException",
            "SQL parser: syntax error", "SyntaxError: unexpected token in SQL query",
            "database serialization failure", "SQLSTATE 40001: serialization failure",
            "could not serialize access due to concurrent update", "transaction SerializationException",
            "invalid signature on JWT", "hash mismatch for password", "integrity check failed for certificate",
            "DataIntegrityViolationException: duplicate key", "HTTP 400 Bad Request", "status=422",
            "JSON logger ready; certificate validation failed", "configuration file missing",
        ), False)

    def test_local_noise_checks_preserve_real_failures_and_other_rules(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("data_parsing", "access_credentials", "configuration_startup",
                                         "database_transactions", "error_colon"),
        ).search_patterns()
        lines = (
            "no JSON parse errors; ERROR: checksum mismatch",
            "checksum mismatch count=0; invalid credentials",
            'expected_errors=["UnicodeDecodeError"]; malformed payload',
            '"JSONDecodeError": false, invalid UTF-8',
            "configuration validation failed; JSON parse error",
            "database serialization failure; cannot deserialize JSON",
            "context after the final match",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 1, "access_credentials": 1, "configuration_startup": 1,
                    "data_parsing": 5, "database_transactions": 1,
                })
                category = result.category("combined" if combined else "data_parsing")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                if not combined:
                    highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                                  for line in rendered]
                    self.assertEqual(highlights, [
                        ["checksum mismatch"], [], ["malformed payload"], ["invalid UTF-8"],
                        ["JSON parse error"], ["cannot deserialize JSON"], [],
                    ])


class ServicesJobsPatternTests(PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("services_jobs",),
        ).search_patterns()

    def test_failed_jobs_tasks_and_workers(self):
        self.assert_lines_match((
            "background job failed", "scheduled task has failed", "batch job 'billing' failed",
            "job 123 execution failed", "Task app.send_mail[abc-123] raised unexpected: ValueError()",
            "Task handler raised error: WorkerLostError()", "worker 'consumer-1' failed",
            "job export timed out", "Failed to execute the scheduled task", "Unable to run background job",
            "Could not process event", "failed jobs=2", "JobExecutionException",
            "TaskFailedException", "billiard.exceptions.WorkerLostError", "SoftTimeLimitExceeded",
            "TimeLimitExceeded for Celery task", "job failed queue=orders",
        ), True)

    def test_message_processing_delivery_and_dead_letters(self):
        self.assert_lines_match((
            "failed to process message", "Unable to publish the message", "Cannot send message",
            "Could not deliver a message", "Failed to acknowledge message", "unable to consume message",
            "message delivery failed", "message 'order-42' processing failed", "message publishing failure",
            "MessageDeliveryException", "MessageHandlingException", "AmqpRejectAndDontRequeueException",
            "message 123 was dead-lettered", "message has been dead lettered", "dead-lettered messages=2",
            "delivery acknowledgement timed out", "consumer acknowledgment timeout",
            "publisher confirm failed", "publisher confirmation timed out",
        ), True)

    def test_unavailable_dependencies_and_failed_health_checks(self):
        self.assert_lines_match((
            "service unavailable", "upstream is unavailable", "backend 'payments' temporarily unavailable",
            "dependency redis is not responding", "downstream inventory not available",
            "service api unhealthy", "no healthy upstream", "no healthy backends",
            "no healthy service instances", "ServiceUnavailableException",
            "health check failed", "healthcheck 'redis' has failed", "health-check timed out",
            "Health check sql with status Unhealthy completed after 10ms",
            "health check status=Unhealthy", "health check is unhealthy",
            "Liveness probe failed: HTTP probe failed with statuscode: 500",
            "readiness probe failed", "startup probe failed", "health check failed; later recovered",
        ), True)

    def test_exhausted_retries_and_open_circuits(self):
        self.assert_lines_match((
            "retries exhausted", "retry attempts are exhausted", "retry limit exceeded",
            "retry budget has been exhausted", "maximum retries reached", "max retries exceeded with url /api",
            "maximum retry attempts exceeded", "exhausted all retries", "MaxRetriesExceededError",
            "RetriesExhaustedException", "RetryExhaustedException", "urllib3.exceptions.MaxRetryError",
            "request giving up after 3 attempts", "job giving up after 2 retries",
            "CallNotPermittedException", "Polly.CircuitBreaker.BrokenCircuitException",
            "CircuitBreakerOpenException", "CircuitBreakerOpenError",
            "circuit breaker is open", "CircuitBreaker 'backendA' is OPEN and does not permit further calls",
            "circuit breaker opened", "circuit breaker billing tripped", "circuit breaker state=OPEN",
            "circuit breaker 'billing' changed from CLOSED to OPEN",
            "circuit breaker transitioned from HALF_OPEN to OPEN",
            "circuit breaker opened; retry later succeeded",
        ), True)

    def test_throttling_and_request_limits(self):
        self.assert_lines_match((
            "ThrottlingException", "ThrottledException", "TooManyRequestsException",
            "RequestLimitExceeded", "ProvisionedThroughputExceededException", "RateLimitExceededException",
            "rate limit exceeded", "rate-limit reached", "Too many requests",
            "request throttled", "API calls rate-limited", "throttling detected for service billing",
            "HTTP 429", "HTTP/1.1 429 Too Many Requests", "HTTP/2 429",
            "caught ThrottlingException: too many requests", "ThrottlingException was handled",
            "ERROR caught ThrottlingException while delivering message",
        ), True)

    def test_replication_quorum_and_leader_election_failures(self):
        self.assert_lines_match((
            "replication failed", "database replication failed", "replication has failed",
            "replication error: unable to apply changes", "failed to replicate records",
            "quorum lost", "lost quorum", "loss of quorum", "quorum has been lost",
            "quorum unavailable", "quorum not reached", "unable to reach a quorum",
            "leader election failed", "leader-election timed out", "could not elect a leader",
            "replication failed; retry succeeded", "quorum lost; quorum restored",
        ), True)
        self.assert_lines_match((
            "replication completed", "replication lag=0", "quorum restored", "quorum reached",
            "leader election completed", "electing a leader", "replication has not failed",
            "quorum was not lost", "no replication failures", "no leader election failures",
            "replication failures=0", "quorum lost=false", '"replication failed": false',
            "quorum loss detection enabled", "replication failure handler registered",
            "leader election failure policy=retry", "expected replication failure",
        ), False)

    def test_normal_activity_settings_counters_and_negations(self):
        self.assert_lines_match((
            "job completed successfully", "Task app.send_mail[abc-123] succeeded in 0.02s",
            "Task app.send_mail[abc-123] retry: Retry in 30s", "retry attempt 3 of 3",
            "max_retries=3", "retry limit=5", "retry budget remaining=0", "retry scheduled",
            "health check succeeded", "Health check sql with status Healthy completed",
            "readiness probe configured", "service stopped normally", "worker shutdown requested",
            "job cancelled by user", "message acknowledged", "queue declared", "dead-letter queue created",
            "dead-letter exchange configured", "basic.nack requeue=false", "rate limit=100",
            "rate limiting enabled", "circuit breaker is closed", "circuit breaker is half-open",
            "circuit breaker transitioned from OPEN to CLOSED", "circuit breaker OPEN -> HALF_OPEN",
            "circuit breaker state=OPEN -> CLOSED", "job not failed", "service not unavailable",
            "circuit breaker not open", "service redis is not unavailable", "no failed jobs",
            "no new health check failures", "zero retries exhausted", "no throttling detected",
            "failed jobs=0", "job failures count=0", "dead-lettered messages=0",
            '"CallNotPermittedException": false', '"service unavailable": false',
            "retry limit exceeded=false", "request throttled=false", "consumer acknowledgement timeout=30000",
            "delivery acknowledgment timeout of 30 seconds", "job failed handler registered",
            "health check failure threshold=3", "circuit breaker open duration=30",
        ), False)

    def test_ambiguous_other_domains_and_diagnostic_mentions(self):
        self.assert_lines_match((
            "unavailable", "failed", "throttled", "TimeLimitExceeded", "giving up after 3 attempts",
            "429", "port=429", "HTTP 4290", "/orders/429", "CPU throttled", "API worker CPU throttled",
            "GPU throttled", "package dependency unavailable", "npm dependency 'module' unavailable",
            "missing dependency", "configuration initialization failed", "invalid credentials",
            "optional dependency metrics unavailable", "parser job complete; throttled",
            "expected task failed", "simulated health check failed", "when service unavailable",
            "registering handler for MaxRetriesExceededError", "except CallNotPermittedException:",
            "catch (BrokenCircuitException ex)", "no caught ThrottlingException",
            "class JobExecutionException(Exception):", "JobExecutionException.java:42",
            'retry_on=["ThrottlingException", "ServiceUnavailableException"]',
            "RequestLimitExceededSetting", "MY_JOB_FAILED_SETTING", "job_failed_count=0",
            "job failed was not observed", "BrokenCircuitException not raised",
        ), False)

    def test_local_noise_checks_preserve_other_failures_and_context(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("services_jobs", "data_parsing", "configuration_startup", "error_colon"),
        ).search_patterns()
        lines = (
            "no failed jobs; ERROR: message delivery failed",
            "consumer acknowledgement timeout=30000; startup failed",
            'retry_on=["ThrottlingException"]; retries exhausted',
            '"service unavailable": false, health check failed',
            "circuit breaker OPEN -> CLOSED; job billing failed",
            "job failures count=0; invalid JSON",
            "request throttled; later retry succeeded",
            "no replication failures; database replication failed",
            "quorum lost; leader election failed",
            "context after the final match",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 1, "configuration_startup": 1, "data_parsing": 1, "services_jobs": 7,
                })
                category = result.category("combined" if combined else "services_jobs")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                if not combined:
                    highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                                  for line in rendered]
                    self.assertEqual(highlights, [
                        ["message delivery failed"], [], ["retries exhausted"], ["health check failed"],
                        ["job billing failed"], [], ["throttled"], ["replication failed"],
                        ["quorum lost", "leader election failed"], [],
                    ])


if __name__ == "__main__":
    unittest.main()
