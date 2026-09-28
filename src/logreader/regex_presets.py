_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = rf"{_OCTET}(?:\.{_OCTET}){{3}}"
_HEX = r"[0-9A-Fa-f]{1,4}"


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

REGEX_PRESETS = (
    ("Email addresses", r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+"),
    ("IPv4 addresses", rf"(?<![\w.]){_IPV4}(?!\w|\.\w)"),
    ("IPv6 addresses", _ipv6_expression()),
    ("URLs", rf"(?<![\w@+.-])(?i:[a-z][a-z0-9+.-]*://|www\.){_URL_BODY}*{_URL_END}"),
)
