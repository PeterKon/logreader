import unittest

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines


class DatabasePatternTests(unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("database_connections",),
        ).search_patterns()

    def assert_line_matches(self, line, expected, patterns=None):
        patterns = self.patterns if patterns is None else patterns
        result = analyze_lines([line], patterns).category(patterns[0].key)
        self.assertEqual(result.match_count, int(expected), line)
        if expected:
            self.assertTrue(result.excerpts[0].lines[0].match_spans)

    def test_connection_login_and_session_failures(self):
        examples = (
            "Unable to connect to the database",
            "failed to establish a connection to PostgreSQL",
            "Could not connect to MySQL on localhost",
            "Cannot connect to database",
            "Couldn't connect to database",
            "Error connecting to MySQL",
            "Unable to establish a database connection",
            'psycopg.OperationalError: connection to server at "localhost", port 5432 failed',
            "database connection failed",
            "DB connection is unavailable",
            "Npgsql: connection was lost",
            "PostgreSQL session was lost",
            "psycopg.OperationalError: server closed the connection unexpectedly",
            "postgres: terminating connection due to administrator command",
            "Lost connection to MySQL server during query",
            "MySQL server has gone away",
            "MySQL: Access denied for user 'app'@'localhost'",
            "SqlClient.SqlException: Login failed for user 'app'",
            "[ODBC Driver for SQL Server] Login timeout expired",
            "A network-related or instance-specific error occurred while establishing a connection to SQL Server",
            "SqlClient: A connection was successfully established with the server, but then an error occurred during the login process",
            "SqlClient: error occurred during the pre-login handshake",
            'Cannot open database "app" requested by the login. The login failed.',
            'postgres FATAL: password authentication failed for user "app"',
            'FATAL: password authentication failed for user "app"',
            'FATAL: peer authentication failed for user "app"',
            'FATAL: no pg_hba.conf entry for host "10.0.0.5", user "app"',
            "FATAL: remaining connection slots are reserved for superusers",
            "FATAL: sorry, too many clients already",
            "PostgreSQL: too many connections",
            "database is unavailable",
            "org.postgresql.util.PSQLException: connection refused",
            "MySqlConnector.MySqlException: connect ECONNREFUSED",
            "psycopg: connect ETIMEDOUT",
            "MongoDB authentication failed",
            "MongoServerSelectionError: no usable server",
            "MongoNetworkError: transport closed",
            "MongoNetworkTimeoutError: connection establishment timed out",
            "pymongo.errors.AutoReconnect: connection interrupted",
            "pymongo.errors.ConnectionFailure: transport failed",
            "pymongo.errors.ServerSelectionTimeoutError: no servers found",
            "java.sql.SQLTransientConnectionException: unavailable",
            "java.sql.SQLNonTransientConnectionException: unavailable",
            "org.hibernate.exception.JDBCConnectionException: could not obtain connection",
            "org.springframework.jdbc.CannotGetJdbcConnectionException: unavailable",
            "retry succeeded after MySQL server has gone away",
            "SequelizeConnectionRefusedError: refused",
            "SequelizeConnectionError: unavailable",
            "SequelizeAccessDeniedError: access denied",
            "MSSQL: connection failed",
        )
        for line in examples:
            with self.subTest(line=line):
                self.assert_line_matches(line, True)

    def test_exhausted_pools_and_acquisition_timeouts(self):
        examples = (
            "Database connection pool exhausted",
            "db pool is full",
            "HikariPool-1 - Connection is not available, request timed out after 30000ms",
            "customPool - Connection is not available, request timed out after 30000ms",
            "HikariPool-4: Failed to validate connection org.postgresql.jdbc.PgConnection@123",
            "QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00",
            "Timeout expired. The timeout period elapsed prior to obtaining a connection from the pool.",
            "SqlClient: maximum pool size was reached",
            "Hibernate: Unable to acquire JDBC Connection",
            "ODBC: unable to obtain a connection",
            "SQLAlchemy: timed out waiting for a connection",
            "DBCP2: Timeout waiting for idle object",
            "psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec",
            "Npgsql: no connections available",
            "MongoWaitQueueTimeoutError: timed out checking out a connection",
            "SequelizeConnectionAcquireTimeoutError: Operation timeout",
            "HikariPool-1: Failed to initialize pool",
        )
        for line in examples:
            with self.subTest(line=line):
                self.assert_line_matches(line, True)

    def test_vendor_codes_require_their_error_namespace(self):
        examples = (
            "SQLSTATE[08001] connection could not be established",
            '"sqlstate": "08006"',
            "SQL state: 28P01",
            "SQLSTATE=53300",
            "SQLSTATE 57P03",
            "SQLSTATE: 28000",
            "[ODBC Driver 18 for SQL Server] [08S01] link failure",
            "MySQL error 1040: Too many connections",
            "MySQL errno=1045",
            "MySQLdb.OperationalError: (2003, 'unavailable')",
            "Microsoft SQL Server, Error: 18456",
            "SqlException: Error Number:4060,State:1,Class:11",
            "SQL Server error 40613",
            "CR_SERVER_GONE_ERROR",
            "CR_SERVER_LOST",
            "ER_CON_COUNT_ERROR",
            "ER_ACCESS_DENIED_ERROR",
            "ORA-01017: invalid credentials",
            "ORA-03113: end-of-file on communication channel",
            "ORA-03114: not connected to ORACLE",
            "ORA-12170: connect timeout occurred",
            "ORA-12516: no available handler",
            "TNS-12541: no listener",
        )
        for line in examples:
            with self.subTest(line=line):
                self.assert_line_matches(line, True)

    def test_normal_activity_settings_and_unrelated_errors_do_not_match(self):
        examples = (
            "database connection established successfully",
            "database connection closed normally",
            "database session terminated by user",
            "HikariPool-1 - Added connection; Pool stats (total=10, active=10, idle=0)",
            "HikariPool-1 - Shutdown completed",
            "database connection timeout=30",
            "database connection timeout: 30",
            "database connection timeout is 30 seconds",
            "database connection timeout 30 seconds",
            "database connection timeout=disabled",
            "configured database connection timeout",
            "database pool_size=5 max_overflow=10 pool_timeout=30",
            "database connection failure count=0",
            "no database connection failure detected",
            "without any database connection failure",
            '"database connection failed": false',
            "database connection failure not observed",
            "database connection failure handler registered",
            "no SQLSTATE 08006 reported",
            "retry_on=SQLSTATE[08006]",
            'expected_errors=["CR_SERVER_LOST", "ORA-12541"]',
            'retryable_sqlstates=["08001", "08006"]',
            '"ER_CON_COUNT_ERROR": 0',
            "ORA-125410 is an unrelated identifier",
            "MY_CR_SERVER_LOST_FLAG",
            "at java.sql.SQLTransientConnectionException.java:42",
            "PostgreSQL statement timeout expired",
            "SqlClient.SqlException: execution timeout expired",
            "SQLAlchemy.exc.OperationalError: database is locked",
            "SQLSTATE 40001 serialization failure",
            "SQLSTATE 23505 duplicate key",
            "ORA-00060 deadlock detected",
            "MySQL error 1064 SQL syntax error",
            "PostgreSQL permission denied for table customers",
            "SQL Server port=18456",
            "MySQL duration=2006",
            "MySQL records [1045]",
            "PostgreSQL port=53300",
            "order=08006",
            "status=1045",
            "SQLSTATE=080060",
            "HTTP connection pool exhausted",
            "HTTP: Failed to initialize pool",
            "Error connecting to https://example.test",
            "SSH login timeout expired",
            "urllib3: no connections available",
            "requests: timed out waiting for a connection",
            "SSH: authentication failed",
            "application: Login failed for user 'app'",
            "web: Access denied for user 'app'",
            "connect ECONNREFUSED 127.0.0.1:8080",
            "database connected; HTTP connection refused",
            "database healthy | user authentication failed",
            "pool exhausted",
        )
        for line in examples:
            with self.subTest(line=line):
                self.assert_line_matches(line, False)

    def test_noise_is_local_and_preserves_other_matches_and_context(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("database_connections", "error_colon"),
        ).search_patterns()
        lines = (
            "no database connection failure; ERROR: MySQL server has gone away",
            "database connection timeout=30; ERROR: query failed",
            "retry_on=CR_SERVER_LOST; database connection pool exhausted",
            "database connection timeout=30, database connection refused",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts, {
                    "error_colon": 2, "database_connections": 3,
                })
                category = result.category("combined" if combined else "database_connections")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                highlights = [
                    [line.text[span.start:span.end] for span in line.match_spans]
                    for line in rendered
                ]
                self.assertNotIn("database connection failure", highlights[0])
                self.assertIn("MySQL server has gone away", highlights[0])
                self.assertNotIn("CR_SERVER_LOST", highlights[2])
                self.assertEqual(highlights[3], ["database connection refused"])
                if not combined:
                    self.assertEqual(highlights[1], [])


    def test_query_and_data_failures_cover_distinct_message_and_code_formats(self):
        patterns = LogreaderConfig(context=0, enabled_patterns=("database_queries",)).search_patterns()
        for line in (
            "SQL query failed", "Hibernate: could not execute statement",
            'ERROR: syntax error at or near "SELECT"', 'PostgreSQL: relation "users" does not exist',
            "no such table: users", "SqlClient: Invalid column name 'age'",
            "SQLSTATE[42601]", '"sqlstate": "22P02"', "ODBC [23000] constraint failure",
            "MySQL error 1064", "SQL Server error 207", "ORA-00942: missing table",
            'invalid input syntax for type integer: "abc"', "data too long for column 'name'",
            "UNIQUE constraint failed: users.id", "ORA-00001", "SQLSTATE 23503",
            "ER_DUP_ENTRY", "SQLITE_CONSTRAINT_FOREIGNKEY", "E11000 duplicate key error",
            "MongoDB: document failed validation",
            "SqlClient: Execution Timeout Expired", "PostgreSQL query timed out",
            "canceling statement due to statement timeout: 30000 ms", "MySQL error 3024",
        ):
            with self.subTest(line=line):
                self.assert_line_matches(line, True, patterns)

    def test_query_noise_and_other_failure_categories_do_not_match(self):
        patterns = LogreaderConfig(context=0, enabled_patterns=("database_queries",)).search_patterns()
        for line in (
            "SQL query succeeded", "SQL CREATE TABLE users (id INTEGER PRIMARY KEY)",
            "database query timeout=30", "configured SQL statement timeout",
            "no SQL query failures", '"SQLITE_CONSTRAINT_UNIQUE": false',
            'expected_errors=["ER_DUP_ENTRY"]', "SQL query error handler registered",
            "HTTP status=207", "MySQL rows=1064", "SQLSTATE 235050", "ORA-000010",
            "DNS query failed", "Python syntax error", "CSV: invalid column name 'age'",
            "database healthy; DNS query timed out", "SqlClient: connection timeout expired",
            "PostgreSQL deadlock detected", "MySQL error 1205", "SQLITE_BUSY",
            "SQLSTATE 57014: canceling statement due to user request", "SQLSTATE HYT00",
        ):
            with self.subTest(line=line):
                self.assert_line_matches(line, False, patterns)

    def test_query_noise_preserves_real_failures_and_other_selected_patterns(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("database_queries", "database_connections"),
        ).search_patterns()
        lines = [
            "SQL query timeout=30; SQLSTATE[23505]",
            "no SQL query failures; database connection refused",
            'expected_errors=["ER_DUP_ENTRY"]; SQL query failed',
        ]
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"database_connections": 1, "database_queries": 2})
                category = result.category("combined" if combined else "database_queries")
                highlights = [line.text[span.start:span.end]
                              for excerpt in category.excerpts for line in excerpt.lines
                              for span in line.match_spans]
                self.assertIn("SQLSTATE[23505", highlights)
                self.assertIn("SQL query failed", highlights)
                self.assertNotIn("ER_DUP_ENTRY", highlights)
                self.assertNotIn("SQL query timeout", highlights)


    def test_transaction_failures_cover_messages_and_vendor_code_namespaces(self):
        patterns = LogreaderConfig(context=0, enabled_patterns=("database_transactions",)).search_patterns()
        for line in (
            "PostgreSQL: deadlock detected", "MySQL error 1205", "SQL Server error 1205",
            "MySQL error 1213", "SqlClient: error 1222", "MSSQL error 3960",
            "ER_LOCK_DEADLOCK", "SQLSTATE[40P01]", '"sqlstate": "40001"', "ODBC [55P03]",
            "ORA-00060", "ORA-08177", "ORA-02091", "SQLITE_BUSY_SNAPSHOT",
            "database is locked", "database table is locked", "SQLITE_LOCKED_SHAREDCACHE",
            "SQLTransactionRollbackException", "psycopg.errors.InFailedSqlTransaction",
            "canceling statement due to lock timeout: 30000 ms", "Lock wait timeout exceeded",
            "Lock request time out period exceeded", "Hibernate: could not acquire lock",
            "could not serialize access due to concurrent update", "MongoDB: WriteConflict",
            "MongoServerError: Transaction with { txnNumber: 2 } has been aborted",
            "JDBC: failed to commit transaction", "database commit failed", "SQL transaction aborted",
            "current transaction is aborted, commands ignored until end of transaction block",
            "retry succeeded after PostgreSQL deadlock detected",
            "PostgreSQL deadlock detected retry succeeded",
        ):
            with self.subTest(line=line):
                self.assert_line_matches(line, True, patterns)

    def test_transaction_noise_and_unrelated_failures_do_not_match(self):
        patterns = LogreaderConfig(context=0, enabled_patterns=("database_transactions",)).search_patterns()
        for line in (
            "SQL COMMIT", "SQL ROLLBACK", "database transaction rolled back", "database lock acquired",
            "PostgreSQL waiting for lock", "SET lock_timeout = 30000", "database lock timeout=30",
            "configured database lock timeout", "PostgreSQL deadlock detection enabled",
            "PostgreSQL no deadlocks detected", "PostgreSQL deadlocks=0", '"SQLITE_BUSY": false',
            'retryable_errors=["ER_LOCK_DEADLOCK", "SQLITE_BUSY"]',
            "database transaction aborted by user", "database transaction aborted intentionally",
            "expected SQL transaction aborted", "Git commit failed", "payment transaction failed",
            "thread deadlock detected", "file lock timed out", "database healthy; Git commit failed",
            "SQL Server trace flag 1222 enabled", "MySQL rows=1213", "SQL Server error 1213",
            "SQLSTATE 400010", "ORA-000600", "SQLSTATE HY000", "SQLSTATE 57014",
            "database connection refused", "SQL query timed out", "SQLSTATE[23505]",
            "MongoDB write failure", "SQL update failure",
        ):
            with self.subTest(line=line):
                self.assert_line_matches(line, False, patterns)

    def test_transaction_exclusions_preserve_other_candidates_and_categories(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("database_transactions", "database_queries"),
        ).search_patterns()
        lines = [
            "database lock timeout=30; SQLSTATE[40P01]",
            'retryable_errors=["ER_LOCK_DEADLOCK"]; database commit failed',
            "database transaction aborted by user; SQLSTATE[23505]",
        ]
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"database_queries": 1, "database_transactions": 2})
                category = result.category("combined" if combined else "database_transactions")
                highlights = [line.text[span.start:span.end]
                              for excerpt in category.excerpts for line in excerpt.lines
                              for span in line.match_spans]
                self.assertIn("SQLSTATE[40P01", highlights)
                self.assertIn("database commit failed", highlights)
                self.assertNotIn("ER_LOCK_DEADLOCK", highlights)
                self.assertNotIn("database lock timeout", highlights)
                self.assertNotIn("database transaction aborted", highlights)


if __name__ == "__main__":
    unittest.main()
