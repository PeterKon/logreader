import codecs
import tempfile
import unittest
from pathlib import Path

from logreader.file_loader import LogDecodeError, decode_log_bytes, load_log


class FileLoaderTests(unittest.TestCase):

    def test_loads_utf8_and_splits_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utf8.log"
            path.write_bytes("start\nERROR: blåskjerm\n".encode("utf-8"))

            loaded = load_log(path)

        self.assertEqual(loaded.lines, ("start", "ERROR: blåskjerm"))
        self.assertEqual(loaded.encoding, "UTF-8")

    def test_detects_utf8_byte_order_mark(self):
        text, encoding = decode_log_bytes(
            codecs.BOM_UTF8 + "ERROR: boom".encode("utf-8")
        )

        self.assertEqual(text, "ERROR: boom")
        self.assertEqual(encoding, "UTF-8 with BOM")

    def test_detects_utf16_byte_order_mark(self):
        text, encoding = decode_log_bytes("ERROR: boom".encode("utf-16"))

        self.assertEqual(text, "ERROR: boom")
        self.assertIn(encoding, ("UTF-16 LE", "UTF-16 BE"))

    def test_falls_back_to_windows_1252(self):
        text, encoding = decode_log_bytes("ERROR: café".encode("cp1252"))

        self.assertEqual(text, "ERROR: café")
        self.assertEqual(encoding, "Windows-1252")

    def test_empty_file_is_valid_utf8(self):
        text, encoding = decode_log_bytes(b"")

        self.assertEqual(text, "")
        self.assertEqual(encoding, "UTF-8")

    def test_rejects_bytes_unsupported_by_all_fallbacks(self):
        with self.assertRaisesRegex(LogDecodeError, "not valid UTF-8"):
            decode_log_bytes(b"\x81")

    def test_missing_file_error_is_preserved(self):
        with self.assertRaises(FileNotFoundError):
            load_log("missing.log")


if __name__ == "__main__":
    unittest.main()
