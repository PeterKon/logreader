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


if __name__ == "__main__":
    unittest.main()
