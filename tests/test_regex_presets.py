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


if __name__ == "__main__":
    unittest.main()
