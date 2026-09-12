import codecs
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from logreader.cancellation import AnalysisCancelled, CancellationToken
from logreader.core import SearchPattern, analyze_lines
from logreader.file_loader import (
    DEFAULT_MAX_LINES_SCANNED, LogDecodeError, _iter_decoded_lines, load_log,
)


class TailLoadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "source.log"

    def test_default_retains_last_million_and_counts_discarded_lines(self):
        self.path.write_bytes(b"old\n" * 7 + b"new\n" * DEFAULT_MAX_LINES_SCANNED)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Whole-file read")):
            loaded = load_log(self.path)
        self.assertEqual(len(loaded.lines), DEFAULT_MAX_LINES_SCANNED)
        self.assertEqual(loaded.total_line_count, DEFAULT_MAX_LINES_SCANNED + 7)
        self.assertEqual(set(loaded.lines), {"new"})

    def test_chunk_boundaries_preserve_encodings_and_splitlines_semantics(self):
        text = "first\r\n\nblå😀\rnext\vmore\fend\x1c\x1d\x1e\x85\u2028\u2029last\r"
        encodings = (
            ("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
            ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE),
            ("utf-32-le", codecs.BOM_UTF32_LE), ("utf-32-be", codecs.BOM_UTF32_BE),
        )
        for codec, bom in encodings:
            for chunk_size in (1, 3, 8, 64):
                with self.subTest(codec=codec, bom=bom, chunk_size=chunk_size):
                    self.path.write_bytes(bom + text.encode(codec))
                    with patch("logreader.file_loader.READ_CHUNK_BYTES", chunk_size):
                        loaded = load_log(self.path, max_lines_scanned=4)
                    self.assertEqual(loaded.lines, tuple(text.splitlines()[-4:]))
                    self.assertEqual(loaded.total_line_count, len(text.splitlines()))

    def test_empty_unterminated_and_repeated_endings(self):
        for text in ("", "a", "\n", "\r", "a\r\r\n", "a\n\n", "a\r\nb"):
            with self.subTest(text=text), patch("logreader.file_loader.READ_CHUNK_BYTES", 1):
                self.path.write_bytes(text.encode())
                loaded = load_log(self.path, max_lines_scanned=10)
                self.assertEqual(loaded.lines, tuple(text.splitlines()))
                self.assertEqual(loaded.total_line_count, len(text.splitlines()))

    def test_late_fallback_restarts_count_and_validates_discarded_prefix(self):
        self.path.write_bytes(b"old\n" * 30 + "café\nlast".encode("cp1252"))
        with patch("logreader.file_loader.READ_CHUNK_BYTES", 8):
            loaded = load_log(self.path, max_lines_scanned=2)
        self.assertEqual(loaded.lines, ("café", "last"))
        self.assertEqual(loaded.total_line_count, 32)
        self.assertEqual(loaded.encoding, "Windows-1252")
        for data in (b"\x81\nvalid tail", codecs.BOM_UTF16_LE + b"a"):
            self.path.write_bytes(data)
            with self.assertRaises(LogDecodeError):
                load_log(self.path, max_lines_scanned=1)

    def test_invalid_limits_and_cancelled_reads(self):
        for value in (0, -1, None, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_log(self.path, max_lines_scanned=value)
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(AnalysisCancelled):
            load_log(self.path, cancellation=token)

        token = CancellationToken()
        class CancellingStream(io.BytesIO):
            def read(self, size=-1):
                self.assert_bounded(size)
                token.cancel()
                return super().read(size)

            def assert_bounded(self, size):
                if size <= 0:
                    raise AssertionError("Unbounded read")

        with self.assertRaises(AnalysisCancelled):
            list(_iter_decoded_lines(CancellingStream(b"a\nb\n"), "utf-8", token))

    def test_source_offsets_context_and_exclusions_in_both_views(self):
        patterns = (SearchPattern("error", "ERROR", context=3),
                    SearchPattern("fatal", "FATAL", context=3),
                    SearchPattern("exclude", "skip", exclude=True))
        for combined in (False, True):
            result = analyze_lines(("context", "ERROR FATAL", "ERROR skip", "after"),
                                   patterns, combined=combined, line_offset=100)
            self.assertEqual(result.line_count, 4)
            for category in result.categories.values():
                self.assertEqual([line.number for line in category.excerpts[0].lines], [101, 102, 103, 104])
                self.assertEqual([line.number for line in category.excerpts[0].lines if line.is_match], [102])
        with self.assertRaises(ValueError):
            analyze_lines((), (), line_offset=-1)
