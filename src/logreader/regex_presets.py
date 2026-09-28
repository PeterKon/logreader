from typing import Callable


_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = rf"{_OCTET}(?:\.{_OCTET}){{3}}"
_HEX = r"[0-9A-Fa-f]{1,4}"
_UUID = r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}"


def _ipv6_expression() -> str:
    forms = [rf"(?:{_HEX}:){{6}}{_IPV4}", rf"{_HEX}(?::{_HEX}){{7}}"]
    for left in range(8):
        prefix = rf"{_HEX}(?::{_HEX}){{{left - 1}}}" if left else ""
        remaining = 7 - left
        suffix = rf"(?:{_HEX}(?::{_HEX}){{0,{remaining - 1}}})?" if remaining else ""
        forms.append(prefix + "::" + suffix)
        if left <= 5:
            forms.append(prefix + rf"::(?:{_HEX}:){{0,{5 - left}}}{_IPV4}")
    address = "(?:" + "|".join(forms) + ")"
    zone = r"(?:%[\w~-]+(?:\.[\w~-]+)*)?"
    return rf"(?<![\w:.%]){address}{zone}(?![\w:%]|\.[\w])"


_URL_CHAR = r"[^\s<>\"'`(){}\[\]]"
_URL_PARENS = rf"\((?:{_URL_CHAR}|\({_URL_CHAR}*\))*\)"
_URL_HOST = r"\[[A-Za-z0-9:.%_~-]+\]"
_URL_BODY = rf"(?:{_URL_CHAR}|{_URL_PARENS}|{_URL_HOST})"
_URL_END = rf"(?:[^\s<>\"'`(){{}}\[\].,;:!?]|{_URL_PARENS}|{_URL_HOST})"


def _windows_path(component: str) -> str:
    segment = rf"(?:{component}|\.{{1,2}})"
    tail = rf"(?:\.{{1,2}}[\\/])*{component}(?:[\\/]{segment})*[\\/]?"
    drive = rf"[A-Za-z]:[\\/](?:{tail})?"
    drive_relative = rf"[A-Za-z]:{component}(?:[\\/]{component})*[\\/]?"
    share = rf"{component}\\{component}(?:\\{component})*\\?"
    volume = rf"(?i:Volume)\{{{_UUID}\}}\\(?:{tail})?"
    extended = rf"\\\\[?.]\\(?:{drive}|{volume}|(?i:UNC)\\{share}|{component}(?:\\{component})*\\?)"
    return rf"(?:{extended}|\\\\{share}|{drive}|{drive_relative}|(?:\.{{1,2}}[\\/]|(?<!:)\\(?!\\)){tail})"


def _unix_path(component: str) -> str:
    prefix = r"(?:/+(?!\*)|\.{1,2}/|~[\w.-]*/)"
    segment = rf"(?:{component}|\.{{1,2}})"
    return rf"{prefix}(?:\.{{1,2}}/+)*{component}(?:/+{segment})*/?"


def _path_expression(build_path: Callable[[str], str], invalid: str, start: str) -> str:
    forms = []
    for quote in ('"', "'"):
        component = rf"(?=[^{invalid}{quote}]*\w)[^{invalid}{quote}]+"
        forms.append(rf"(?<={quote}){build_path(component)}(?={quote})")
    # Unquoted log tokens need stricter characters than filesystem names.
    character = r"(?:[\w.@+~$!#&=-]|%[0-9A-Fa-f]{2})"
    component = rf"(?={character}*\w){character}+"
    ending = (r"(?:(?<!\.)|(?<=[/\\]\.)|(?<=[/\\]\.\.))"
              r'''(?=$|[\s"'<>()\[\]{},;:]|\.+(?:$|[\s"'<>()\[\]{},;:]))''')
    forms.append(start + build_path(component) + ending)
    return "(?:" + "|".join(forms) + ")"


REGEX_PRESETS = (
    ("Email addresses", r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+"),
    ("IPv4 addresses", rf"(?<![\w.]){_IPV4}(?!\w|\.\w)"),
    ("IPv6 addresses", _ipv6_expression()),
    ("URLs", rf"(?<![\w@+.-])(?i:[a-z][a-z0-9+.-]*://|www\.){_URL_BODY}*{_URL_END}"),
    ("UUIDs", rf"(?<![\w-]){_UUID}(?![\w-])"),
    ("Windows paths", _path_expression(_windows_path, r'\\/:*?"<>|\x00-\x1f',
                                       r"(?<![^\s=:(\[{,;])")),
    ("Unix paths", _path_expression(_unix_path, r"/\x00-\x1f", r"(?<![^\s=(\[{,;])")),
    ("MAC addresses", r"(?<![\w.:-])(?i:(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|"
                      r"(?:[0-9a-f]{2}-){5}[0-9a-f]{2}|(?:[0-9a-f]{4}\.){2}[0-9a-f]{4})"
                      r"(?![\w:-]|\.\w)"),
    ("ISO timestamps", r"(?<![\w.+-])[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
                       r"[Tt ](?:[01][0-9]|2[0-3]):[0-5][0-9]:(?:[0-5][0-9]|60)"
                       r"(?:[.,][0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3])(?::?[0-5][0-9])?)?"
                       r"(?![\w:+-]|[.,][\w.,])"),
)
