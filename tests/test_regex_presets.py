import ipaddress
import re
import unittest

from logreader.regex_presets import REGEX_PRESETS


class RegexPresetTests(unittest.TestCase):
    expressions = {name: re.compile(pattern) for name, pattern in REGEX_PRESETS}

    def assert_matches(self, name, text, expected):
        self.assertEqual([match.group() for match in self.expressions[name].finditer(text)],
                         expected, text)

    def test_ipv4_ranges_and_surrounding_log_text(self):
        for address in ("0.0.0.0", "10.0.0.1", "172.16.0.1", "192.168.1.42",
                        "127.0.0.1", "8.8.8.8", "255.255.255.255"):
            self.assert_matches("IPv4 addresses", f"peer={address}:8080, subnet={address}/24.",
                                [address, address])
        self.assert_matches("IPv4 addresses", "Connected to 192.168.1.42.", ["192.168.1.42"])
        for octet in range(256):
            address = f"{octet}.{octet}.{octet}.{octet}"
            self.assert_matches("IPv4 addresses", address, [address])
        for invalid in ("999.1.2.3", "1.256.2.3", "1.2.300.3", "1.2.3.999",
                        "1.2.3.4.5", "9999.1.2.3", "1.2.3", "01.2.3.4",
                        "x1.2.3.4", "1.2.3.4x"):
            self.assert_matches("IPv4 addresses", invalid, [])

    def test_ipv6_full_and_every_compression_position(self):
        for start in range(8):
            for count in range(1, 9 - start):
                groups = ["abcd"] * 8
                groups[start:start + count] = ["0"] * count
                full = ":".join(groups)
                compressed = ":".join(groups[:start]) + "::" + ":".join(groups[start + count:])
                self.assertEqual(ipaddress.IPv6Address(full), ipaddress.IPv6Address(compressed))
                for address in (full, compressed, compressed.upper()):
                    self.assert_matches("IPv6 addresses", f"peer=[{address}]:443", [address])
        for address in ("::", "::1", "2001:db8::1", "fe80::1234%eth0", "fe80::1%12",
                        "fe80::1%eth0.100", "fe80::1%en-us", "::ffff:192.0.2.128%eth0"):
            self.assert_matches("IPv6 addresses", f"peer=[{address}]:8080,", [address])
        self.assert_matches("IPv6 addresses", "fe80::1%eth0.", ["fe80::1%eth0"])
        self.assert_matches("IPv6 addresses", "::1/128; 2001:db8::1.", ["::1", "2001:db8::1"])

    def test_ipv6_embedded_ipv4_full_and_compressed(self):
        for start in range(6):
            for count in range(1, 7 - start):
                groups = ["abcd"] * 6
                groups[start:start + count] = ["0"] * count
                full = ":".join(groups) + ":192.0.2.1"
                compressed = ":".join(groups[:start]) + "::"
                compressed += ":".join(groups[start + count:] + ["192.0.2.1"])
                self.assertEqual(ipaddress.IPv6Address(full), ipaddress.IPv6Address(compressed))
                for address in (full, compressed):
                    self.assert_matches("IPv6 addresses", f"[{address}]:443", [address])
        self.assert_matches("IPv6 addresses", "::ffff:192.0.2.128", ["::ffff:192.0.2.128"])

    def test_ipv6_does_not_extract_fragments_of_invalid_addresses(self):
        for invalid in ("2001:db8:1", "1:2:3:4:5:6:7:8:9", "1:2:3:4:5:6:7::8",
                        "2001::db8::1", "2001:::1", "2001:db8::gggg", "12345::1",
                        "::ffff:999.0.2.1", "::ffff:192.0.2.1.5", "::ffff:192.0.2",
                        "1:2:3:4:5:6::192.0.2.1", "fe80::1%", "x2001:db8::1"):
            self.assert_matches("IPv6 addresses", invalid, [])

    def test_urls_keep_paths_queries_fragments_ports_and_ip_hosts(self):
        urls = ["https://example.org/api/v1?q=one%20two&x=1#result",
                "HTTP://EXAMPLE.ORG:8080/path", "ftp://user:pass@host.example/file.zip",
                "ws://127.0.0.1:9000/socket", "https://[2001:db8::1]:443/a?q=1#b",
                "http://[fe80::1%25eth0]:8080/", "file:///C:/Logs/app.log",
                "git+ssh://host.example/repo", "www.example.org/a?q=1#b",
                "https://例子.公司/路径", "https://example.org/wiki/Thing_(detail)",
                "https://example.org/a_(b_(c))", "https://example.org/a,b;c:d!e"]
        for url in urls:
            self.assert_matches("URLs", f'url="{url}"', [url])

    def test_url_boundaries_trim_prose_but_leave_bare_domains_alone(self):
        self.assert_matches("URLs", "See (https://example.org/a_(b)). Next: www.example.net!",
                            ["https://example.org/a_(b)", "www.example.net"])
        self.assert_matches("URLs", "<https://[::1]:8080/>; https://example.org/a?x=1,",
                            ["https://[::1]:8080/", "https://example.org/a?x=1"])
        self.assert_matches("URLs", "example.org user@www.example.org www. https:// ERROR:thing", [])

    def test_uuid_case_versions_wrappers_and_boundaries(self):
        for version in "0123456789abcdef":
            uuid = f"550e8400-e29b-{version}1d4-a716-446655440000"
            for value in (uuid, uuid.upper()):
                self.assert_matches("UUIDs", f"id={{{value}}}; urn:uuid:{value}", [value, value])
        for value in ("00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff"):
            self.assert_matches("UUIDs", value, [value])
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        for value in ("x" + uuid, uuid + "0", uuid + "-1234", uuid[:-1], uuid.replace("-", ""),
                      uuid.replace("e29b", "g29b")):
            self.assert_matches("UUIDs", value, [])

    def test_mac_addresses_formats_case_and_address_types(self):
        for digits in ("001A2b3C4d5E", "000000000000", "FFFFFFFFFFFF", "020000000001", "01005E000001"):
            for address in (":".join(digits[i:i + 2] for i in range(0, 12, 2)),
                            "-".join(digits[i:i + 2] for i in range(0, 12, 2)),
                            ".".join(digits[i:i + 4] for i in range(0, 12, 4))):
                for value in (address, address.lower(), address.upper()):
                    with self.subTest(address=value):
                        self.assert_matches("MAC addresses", f'src="{value}", dst=[{value}].', [value, value])
        self.assert_matches("MAC addresses", "00:1a:2b:3c:4d:5e;00-1A-2B-3C-4D-5E;001a.2b3c.4d5e",
                            ["00:1a:2b:3c:4d:5e", "00-1A-2B-3C-4D-5E", "001a.2b3c.4d5e"])

    def test_mac_addresses_reject_malformed_and_embedded_fragments(self):
        invalid = ["00:1a:2b:3c:4d", "00:1a:2b:3c:4d:5e:6f", "00:1a:2b:3c:4d:5e:6f:70",
                   "00-1a-2b-3c-4d-5e-6f-70", "001a.2b3c.4d5e.6f70", "00:1a-2b:3c:4d:5e",
                   "00-1a:2b-3c-4d-5e", "00:1a:2b:3c:4d:5g", "0:1a:2b:3c:4d:5e",
                   "000:1a:2b:3c:4d:5e", "001a.2b3c.4d5", "001a.2b3c.4d5e0", "001a2b3c4d5e",
                   "x00:1a:2b:3c:4d:5e", "00:1a:2b:3c:4d:5ex", "name-001a.2b3c.4d5e",
                   "2001:db8:00:1a:2b:3c:4d:5e", "550e8400-e29b-41d4-a716-446655440000"]
        for value in invalid:
            with self.subTest(value=value):
                self.assert_matches("MAC addresses", value, [])

    def test_windows_path_forms_and_log_boundaries(self):
        paths = [r"C:\Logs\app.log", "d:/logs/app.log", "C:\\", r"C:logs\app.log",
                 r"\\server\share", r"\\server\share\logs\app.log", r"\\?\C:\Logs\app.log",
                 r"\\?\UNC\server\share\app.log", r"\\.\pipe\app", r".\app.log",
                 r"..\logs\app.log", "./app.log", "../logs/app.log",
                 r"\Windows\app.log", r"C:\logs\..", r"C:\logs\.",
                 r"\\?\Volume{550e8400-e29b-41d4-a716-446655440000}\app.log"]
        for path in paths:
            self.assert_matches("Windows paths", f'path="{path}"', [path])
            self.assert_matches("Windows paths", f"path={path}; next", [path])
        self.assert_matches("Windows paths", r"Failed (C:\Logs\app.log).", [r"C:\Logs\app.log"])
        self.assert_matches("Windows paths", "app.log logs/app.log logs\\app.log https://example.org/C:/logs",
                            [])

    def test_iso_timestamps_separators_precision_and_offsets(self):
        for separator in ("T", "t", " "):
            for fraction in ("", ".1", ".123", ".123456", ".123456789", ",123"):
                for zone in ("", "Z", "z", "+02:00", "-05:30", "+0545", "-0330", "+02", "-00:00"):
                    value = f"2026-09-28{separator}14:32:08{fraction}{zone}"
                    with self.subTest(value=value):
                        self.assert_matches("ISO timestamps", f'time="{value}"', [value])
        self.assert_matches("ISO timestamps", "1990-12-31T23:59:60Z", ["1990-12-31T23:59:60Z"])

    def test_iso_timestamps_in_log_entries(self):
        cases = [
            ('{"log":"Started","stream":"stdout","time":"2019-01-01T11:11:11.111111111Z"}',
             ["2019-01-01T11:11:11.111111111Z"]),
            ("2026-09-28T14:32:08.123+02:00 INFO 1234 --- [main] Server started",
             ["2026-09-28T14:32:08.123+02:00"]),
            ("2026-09-28 12:32:08,123 INFO worker: Started", ["2026-09-28 12:32:08,123"]),
            ("2026-09-28 12:32:08.123 UTC [1234] LOG: checkpoint complete", ["2026-09-28 12:32:08.123"]),
            ("start=[2026-09-28T12:32:08Z], end=2026-09-28T12:33:08.5Z.",
             ["2026-09-28T12:32:08Z", "2026-09-28T12:33:08.5Z"]),
        ]
        for line, expected in cases:
            self.assert_matches("ISO timestamps", line, expected)

    def test_iso_timestamps_reject_invalid_fields_and_partial_tokens(self):
        invalid = ["2026-00-28T12:32:08Z", "2026-13-28T12:32:08Z", "2026-09-00T12:32:08Z",
                   "2026-09-32T12:32:08Z", "2026-09-28T25:32:08Z", "2026-09-28T12:60:08Z",
                   "2026-09-28T12:32:61Z", "2026-09-28T12:32:08+25:00", "2026-09-28T12:32:08+02:60",
                   "2026-09-28T12:32:08+020", "2026-09-28T12:32:08+2:00", "2026-09-28T12:32:08+",
                   "2026-09-28T12:32:08.Z", "2026-09-28T12:32:08.123x", "2026-09-28T12:32:08.1.2Z",
                   "2026-09-28T12:32:08Z+02:00", "2026-09-28T12:32:080Z", "12026-09-28T12:32:08Z",
                   "id2026-09-28T12:32:08Z", "2026-09-28T12:32:08Zsuffix", "2026-09-28", "12:32:08",
                   "2026-9-28T12:32:08Z", "2026-W40-1T12:32:08Z", "20260928T123208Z",
                   "2026-09-28\n12:32:08Z", "2026-09-28  12:32:08Z"]
        for value in invalid:
            with self.subTest(value=value):
                self.assert_matches("ISO timestamps", value, [])

    def test_quoted_windows_paths_preserve_spaces_and_punctuation(self):
        for path in (r"C:\Program Files (x86)\app\app.log", r"\\server\Shared Files\app.log",
                     r"\\?\C:\Long Folder\app.log", r"..\My Files\data,old.txt"):
            for quote in ('"', "'"):
                self.assert_matches("Windows paths", f"path={quote}{path}{quote}, next", [path])
        path = r"C:\Users\O'Connor\report.txt"
        self.assert_matches("Windows paths", f'"{path}"', [path])
        self.assert_matches("Windows paths", '"C:\\broken\npath.txt"', [])

    def test_unix_path_forms_and_log_boundaries(self):
        paths = ["/var/log/app.log", "/tmp/", "./app.log", "../logs/app.log",
                 "../../app.log", "~/logs/app.log", "~alex/logs/app.log", "/tmp/.hidden",
                 "/tmp/..", "/tmp/.", "/var//log/app.log", "//server/share/app.log",
                 "/tmp/日志.txt", "/saswork/session/#LN00024", "/data/&batch./input"]
        for path in paths:
            self.assert_matches("Unix paths", f"file={path}; next", [path])
        self.assert_matches("Unix paths", "Failed (/var/log/app.log).", ["/var/log/app.log"])
        self.assert_matches("Unix paths", "app.log logs/app.log https://example.org/a/b "
                            "http://[::1]/var/log file:///var/log C:/logs/app.log 1/2 2026/09/28", [])

    def test_quoted_unix_paths_preserve_spaces_and_punctuation(self):
        for path in ("/home/alex/My Files/report (old).txt", "../My Files/report.txt",
                     "~/My Files/[draft];report.txt", "/tmp/file."):
            for quote in ('"', "'"):
                self.assert_matches("Unix paths", f"file={quote}{path}{quote}, next", [path])
        self.assert_matches("Unix paths", '''"/tmp/O'Connor.txt"''', ["/tmp/O'Connor.txt"])
        self.assert_matches("Unix paths", ''''/tmp/say "hello".txt' ''', ['/tmp/say "hello".txt'])
        self.assert_matches("Unix paths", '"/tmp/broken\npath.txt"', [])

    def test_path_presets_reject_separators_comments_and_escaped_punctuation(self):
        noise = ["/", "//", "./", "../", "~/", "../../", "\\", ".\\", "..\\",
                 "/* Generate the process id for job */", "/*---------------------",
                 "/**", "/****************************************************************************",
                 "/*==========================================================================*",
                 "/*Compliance Analytics*/", "value / count", "value /2*3", "/tmp/*.sas",
                 r"EC|EU|Europe|FCDO \(UK\) Sanctions List - Asset Freeze",
                 r"\(UK\)", r"\[value\]", r"\.*", "/ID.CF0009%(WorkTable%)"]
        for name in ("Windows paths", "Unix paths"):
            for line in noise:
                with self.subTest(name=name, line=line):
                    self.assert_matches(name, line, [])
            for token in ("/", "//", "/*", "/**/", "/*comment*/", "\\", "\\(\\)"):
                self.assert_matches(name, f'"{token}"', [])

    def test_unix_paths_in_sas_style_logs_keep_real_paths(self):
        cases = [
            ("NOTE: AUTOEXEC processing beginning; file is /opt/app/BatchServer/autoexec.sas.",
             ["/opt/app/BatchServer/autoexec.sas"]),
            ("SYMBOLGEN: Macro variable ROOT resolves to /opt", ["/opt"]),
            ('144 +%inc "/opt/app/custom/config/autoexec.sas";', ["/opt/app/custom/config/autoexec.sas"]),
            ('288 +/* options SETUP="/opt/app/config";*/', ["/opt/app/config"]),
            ("232 +%let macro_path=/opt/app/macros; /* configuration */", ["/opt/app/macros"]),
            ("Filename=/work/session/#LN00024,", ["/work/session/#LN00024"]),
            ("file=/data/&batch./input;", ["/data/&batch./input"]),
            ("file=/data/My%20Files/report.txt;", ["/data/My%20Files/report.txt"]),
        ]
        for line, expected in cases:
            self.assert_matches("Unix paths", line, expected)


if __name__ == "__main__":
    unittest.main()
