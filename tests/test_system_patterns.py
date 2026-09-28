import unittest

from logreader.config import LogreaderConfig
from logreader.core import analyze_lines


class _PatternAssertions:
    def assert_lines_match(self, lines, expected):
        for line in lines:
            with self.subTest(line=line):
                result = analyze_lines([line], self.patterns).category(self.patterns[0].key)
                self.assertEqual(result.match_count, int(expected))
                if expected:
                    self.assertTrue(result.excerpts[0].lines[0].match_spans)


class FilesStoragePatternTests(_PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("files_storage",),
        ).search_patterns()

    def test_missing_files_and_file_permissions(self):
        self.assert_lines_match((
            "FileNotFoundError: [Errno 2] No such file or directory: 'config.ini'",
            "ENOENT: no such file or directory, open '/var/log/app.log'",
            "System.IO.FileNotFoundException: missing config.ini",
            "java.nio.file.NoSuchFileException: /tmp/input.csv",
            "System.IO.DirectoryNotFoundException: missing directory",
            "The system cannot find the path specified.",
            "file 'config.ini' not found",
            'directory "/var/data" does not exist',
            "Could not find file 'settings.json'",
            "ERROR_FILE_NOT_FOUND", "ERROR_PATH_NOT_FOUND",
            "[WinError 2]", "Windows error 3", "Win32 error: 32",
            "PermissionError: [Errno 13] Permission denied: '/var/log/app.log'",
            "PermissionError: [Errno 13] Permission denied: 'config.ini'",
            "PermissionError: [Errno 13] Permission denied: '/data'",
            "EACCES: permission denied, open '/etc/app.conf'",
            "EPERM: operation not permitted, unlink 'cache.dat'",
            "file access denied", "permission denied for directory /data",
            "java.nio.file.AccessDeniedException: /tmp/output.csv",
            r"System.UnauthorizedAccessException: Access to the path 'C:\data\a.txt' is denied",
            r"Access to the path 'C:\data\a.txt' is denied",
            "ERROR_ACCESS_DENIED when calling CreateFile",
            r"[WinError 5] Access is denied: 'C:\data\output.log'",
            'error=EACCES syscall="open" path="settings.json"',
        ), True)

    def test_capacity_io_and_read_only_failures(self):
        self.assert_lines_match((
            "ENOSPC", "EDQUOT", "EROFS", "ERROR_DISK_FULL", "ERROR_HANDLE_DISK_FULL",
            "No space left on device", "Disk quota exceeded", "The disk is full",
            "filesystem full", "volume is out of space", "not enough disk space",
            "[WinError 112]", "ERROR_READ_FAULT", "ERROR_WRITE_FAULT",
            "The system cannot write to the specified device.",
            "file read error", "disk I/O error", "filesystem error",
            "Input/output error reading file /data/index",
            "EIO: read '/var/data/index'", "IOException: failed to write file",
            "read failed for disk /dev/sda", "unable to flush file output.log",
            "failed to open '/tmp/input.csv'", "could not write to file report.csv",
            "Read-only file system", "filesystem is read-only",
            "OSError: [Errno 30] Read-only file system: '/data/output'",
            "write failed on mounted read-only filesystem",
            "ERROR_WRITE_PROTECT", "ERROR_FILE_CORRUPT",
        ), True)

    def test_file_lock_and_mount_failures(self):
        self.assert_lines_match((
            "ERROR_SHARING_VIOLATION", "ERROR_LOCK_VIOLATION",
            "The process cannot access the file because it is being used by another process.",
            "file is locked by another process", "file lock conflict", "file lock timed out",
            "file lock timeout", "unable to lock file report.csv",
            "EBUSY: resource busy, open '/data/state'",
            "mount: /data: device is busy", "mount failed", "failed to mount /data",
            "unable to mount volume", "MountVolume.SetUp failed for volume cache",
            "Warning FailedMount volume unavailable",
            "mount: /data: permission denied",
            "mount: /data: wrong fs type, bad option, bad superblock on /dev/sda",
            "mount: /data: unknown filesystem type 'badfs'",
        ), True)

    def test_normal_activity_settings_and_negation_do_not_match(self):
        self.assert_lines_match((
            "file opened successfully", "file read completed", "file lock acquired",
            "file is locked", "waiting for file lock", "mount completed successfully",
            "mounted read-only filesystem", "using a read-only file system",
            "volume mounted with options: read-only filesystem",
            "read-only filesystem mounted successfully",
            "file lock timeout=30", "file lock timeout: 30", "configured file lock timeout",
            "disk_full=false read_only=true", "disk full threshold=90",
            "disk full detection enabled", "disk full handler registered",
            "no disk full errors", "without any file access errors",
            "file read error count=0", '"ERROR_DISK_FULL": false',
            '"ENOENT": 0', "disk full not observed", "no ENOSPC reported",
            "optional file not found", "optional configuration file not found, using defaults",
            'expected_errors=["ENOENT", "EROFS"]',
            'retry_on=["EACCES", "ENOSPC"]',
            "except FileNotFoundError:", "catch (FileNotFoundException ex)",
            "at java.io.FileNotFoundException.java:42",
            "MY_ENOSPC_SETTING", "ERROR_FILE_NOT_FOUND_EXTRA", "WinError 320",
        ), False)

    def test_unrelated_errors_and_ambiguous_numbers_do_not_match(self):
        self.assert_lines_match((
            "access denied", "PermissionError", "EACCES", "EPERM", "EIO", "EBUSY",
            "IOException: connection reset", "read error from socket", "write failed on TCP socket",
            "HTTP GET /api/users: permission denied", "access denied: https://example.test/a/b",
            "HTTP GET /api/file/123: permission denied",
            "EACCES: permission denied, bind 127.0.0.1:80",
            "permission denied for table customers", "database is locked",
            "database lock timeout", "database transaction failed",
            "CPU resource busy", "process failed to open connection", "HTTP 404 not found",
            "EAGAIN reading file; retry later",
            "404", "code=2", "error 32", "errno=13", "status=112", "[WinError 5]",
            "file loaded; access denied for user", "disk healthy | read error from socket",
            "mount successful; EACCES: bind 127.0.0.1:80",
            "file loaded; failed to open https://example.test/a/b",
            "SQL data validation failed", "authentication failed", "not enough memory",
        ), False)

    def test_local_noise_preserves_real_failures_highlights_and_other_patterns(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("files_storage", "error_colon"),
        ).search_patterns()
        lines = (
            "no disk full errors; ERROR: ENOSPC",
            "file lock timeout=30; ERROR: login rejected",
            'expected_errors=["ENOENT"]; file access denied',
            "file lock timeout=30, file lock timed out",
            "retry succeeded after file read error",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"error_colon": 2, "files_storage": 4})
                category = result.category("combined" if combined else "files_storage")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                              for line in rendered]
                self.assertNotIn("disk full", highlights[0])
                self.assertIn("ENOSPC", highlights[0])
                self.assertNotIn("ENOENT", highlights[2])
                self.assertIn("file access denied", highlights[2])
                self.assertEqual(highlights[3], ["file lock timed out"])
                if not combined:
                    self.assertEqual(highlights[1], [])


class MemoryResourcesPatternTests(_PatternAssertions, unittest.TestCase):
    def setUp(self):
        self.patterns = LogreaderConfig(
            context=0, enabled_patterns=("memory_resources",),
        ).search_patterns()

    def test_memory_exhaustion_and_allocation_failures(self):
        self.assert_lines_match((
            "java.lang.OutOfMemoryError: Java heap space",
            "java.lang.OutOfMemoryError: Metaspace", "System.OutOfMemoryException",
            "System.InsufficientMemoryException", "MemoryError", "std::bad_alloc",
            "ENOMEM", "ERR_MEMORY_ALLOCATION_FAILED", "ERR_WORKER_OUT_OF_MEMORY",
            "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory",
            "kernel: Out of memory: Killed process 123 (python)", 'reason="OOMKilled"',
            "cannot allocate memory", "failed to allocate memory", "not enough memory",
            "insufficient native memory", "memory allocation failed",
            "memory allocation of 4096 bytes failed", "Unable to allocate 128.5 MiB for an array",
            "GC overhead limit exceeded", "memory exhausted", "heap is exhausted",
            "memory limit exceeded", "heap limit has been reached",
            "malloc failed", "calloc() failed", "realloc: allocation failed",
            "E_OUTOFMEMORY", "ERROR_NOT_ENOUGH_MEMORY", "ERROR_OUTOFMEMORY",
            "[WinError 8]", "Windows error 14", "Win32 error: 1455",
            "Not enough storage is available to process this command.",
            "The paging file is too small for this operation to complete.",
        ), True)

    def test_handle_thread_process_and_system_resource_exhaustion(self):
        self.assert_lines_match((
            "EMFILE: too many open files", "ENFILE", "too many open files in system",
            "ERROR_TOO_MANY_OPEN_FILES", "[WinError 4]", "file descriptors exhausted",
            "file handle limit reached", "file descriptor table exhaustion",
            "RuntimeError: can't start new thread", "unable to create new native thread",
            "thread limit reached", "process limit exceeded", "PID quota exhausted",
            "thread pool exhausted", "worker pool is exhausted",
            "Insufficient resources to create another thread",
            "insufficient system resources exist to complete the requested service",
            "ERROR_NO_SYSTEM_RESOURCES", "ERROR_NONPAGED_SYSTEM_RESOURCES",
            "ERROR_PAGED_SYSTEM_RESOURCES", "ERROR_WORKING_SET_QUOTA",
            "ERROR_PAGEFILE_QUOTA", "ERROR_COMMITMENT_LIMIT", "[WinError 1450]",
            "system resource exhaustion", "RESOURCE_EXHAUSTED: memory exhausted",
        ), True)

    def test_ambiguous_signals_require_matching_local_context(self):
        self.assert_lines_match((
            "pthread_create failed (EAGAIN)", "bash: fork: Resource temporarily unavailable",
            "clone() failed: EAGAIN", "spawn process failed: EAGAIN",
            "EAGAIN while creating a native thread",
            "allocation failed for heap buffer", "VirtualAlloc: allocation failed",
            "resources exhausted while creating threads",
        ), True)
        self.assert_lines_match((
            "EAGAIN", "read() returned EAGAIN", "socket resource temporarily unavailable",
            "fork succeeded; socket read returned EAGAIN", "thread idle | EAGAIN",
            "allocation failed for IP address", "disk allocation failed",
            "resource exhausted", "RESOURCE_EXHAUSTED: daily API quota exceeded",
            "database connection pool exhausted", "no space left on device",
            "ENOSPC", "ERROR_DISK_FULL", "[WinError 112]", "HTTP 429",
            "CPU usage=100%", "memory usage=99%", "exit code 137", "SIGKILL", "OOM",
            "cannot create thread: permission denied", "mmap failed: EACCES",
            "unable to create native thread: EPERM",
            "memory healthy; allocation failed for IP address",
            "errno=12", "code=24", "status=1450", "error 8", "WinError 14550",
        ), False)

    def test_settings_counters_handlers_and_normal_gc_do_not_match(self):
        self.assert_lines_match((
            "memory_limit=512MB", "configured memory limit", "heap size=4096MB",
            "max_threads=100", "RLIMIT_NOFILE=1024", "ulimit -n 4096",
            "[GC (Allocation Failure) 1024K->256K heap=4096K]",
            "[gc] Pause Young (Allocation Failure) 10M->2M",
            "GC completed", "Java heap space=1024MB", "heap dump completed",
            "-XX:+HeapDumpOnOutOfMemoryError", "oom_score_adj=1000",
            "out-of-memory killer enabled", "out of memory handler registered",
            "out of memory events=0", "no OutOfMemoryError", "without any memory allocation failures",
            '"OOMKilled": false', "OOMKilled=false", "MemoryError: 0", "ENOMEM=0",
            "memory allocation failure count=0", "file descriptor exhaustion not observed",
            "expected out of memory", "configured thread limit reached",
            "process is not out of memory",
            'expected_errors=["ENOMEM", "EMFILE"]', 'retryable_errors=["MemoryError", "ENFILE"]',
            "retry_on=EAGAIN", "except MemoryError:", "catch (OutOfMemoryException ex)",
            "at java.lang.OutOfMemoryError.java:42", "MY_ENOMEM_SETTING",
        ), False)

    def test_local_exclusions_preserve_real_failures_and_other_categories(self):
        patterns = LogreaderConfig(
            context=1, enabled_patterns=("memory_resources", "files_storage", "error_colon"),
        ).search_patterns()
        lines = (
            "no OutOfMemoryError; ERROR: ENOMEM",
            "memory_limit=512MB; ERROR: disk full",
            'expected_errors=["ENOMEM"]; fork failed: EAGAIN',
            '"OOMKilled": false, MemoryError',
            "retry succeeded after memory allocation failed",
            "ENOMEM: cannot allocate memory",
        )
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(lines, patterns, combined=combined)
                self.assertEqual(result.category_match_counts,
                                 {"error_colon": 2, "files_storage": 1, "memory_resources": 5})
                category = result.category("combined" if combined else "memory_resources")
                rendered = category.excerpts[0].lines
                self.assertEqual([line.text for line in rendered], list(lines))
                highlights = [[line.text[span.start:span.end] for span in line.match_spans]
                              for line in rendered]
                self.assertNotIn("OutOfMemoryError", highlights[0])
                self.assertIn("ENOMEM", highlights[0])
                self.assertEqual(highlights[2], ["EAGAIN"])
                self.assertEqual(highlights[3], ["MemoryError"])
                if not combined:
                    self.assertEqual(highlights[1], [])


if __name__ == "__main__":
    unittest.main()
