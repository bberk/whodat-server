"""Shared, side-effect-free validation and normalization for untrusted text.

Two kinds of text cross a trust boundary in this application:

* **Identifiers supplied by a user or a URL** (for example the ESPN league id). These are matched
  against a deliberately narrow character set so a value can never carry whitespace, path
  separators, quotes, angle brackets, or control characters into a provider request, a log line,
  or a database lookup.
* **Display text supplied by a provider** (league, team, owner, and division names). ESPN data is
  untrusted too: it can contain NUL or other control/format characters that Postgres rejects or
  that corrupt log output. Display text is normalized rather than escaped here; storage stays raw
  and the browser renders it as text, never as markup.

Nothing in this module reads configuration, performs I/O, or depends on a web framework, so both
the API schemas and the provider-agnostic sync service can share it.
"""

from __future__ import annotations

import re
import unicodedata

#: Longest external provider identifier accepted from a caller. ESPN league ids are numeric today,
#: but the validator deliberately allows letters, dots, underscores, and hyphens so provider ids
#: such as ``e2e-fixture-league`` and future non-numeric ids keep working.
MAX_EXTERNAL_ID_LENGTH = 64

#: External ids contain no whitespace, slash, backslash, control character, quote, or angle
#: bracket. Only the characters below are accepted.
EXTERNAL_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")

#: Longest provider display string persisted. This is far above real league, team, owner, and
#: division names, so it caps pathological input without narrowing legitimate ESPN data.
MAX_DISPLAY_TEXT_LENGTH = 200

#: Unicode categories removed from display text: C0/C1 controls, format characters (zero-width
#: joiners, bidi overrides, soft hyphens), surrogates, private-use characters, and unassigned code
#: points. Line and paragraph separators are handled by whitespace collapsing below.
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def normalize_external_id(value: str) -> str:
    """Return ``value`` trimmed and NFC-normalized, or raise ``ValueError`` when it is not an id.

    The accepted shape is ``[A-Za-z0-9._-]{1,64}`` after trimming. NFC normalization happens
    before the character check so a canonically equivalent spelling is either accepted or rejected
    consistently. The error message is fixed and never repeats the submitted value.
    """
    if not isinstance(value, str):
        raise ValueError("external id must be text")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(normalized) <= MAX_EXTERNAL_ID_LENGTH:
        raise ValueError("external id has an invalid length")
    if EXTERNAL_ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("external id contains invalid characters")
    return normalized


def normalize_display_text(
    value: str,
    *,
    max_length: int = MAX_DISPLAY_TEXT_LENGTH,
) -> str:
    """Return provider display text safe to persist, without escaping markup.

    The result is NFC-normalized, has NUL/control/format characters and Unicode line/paragraph
    separators removed, collapses every run of internal whitespace to one space, is trimmed, and is
    capped at ``max_length`` code points. HTML characters such as ``<`` and ``>`` are preserved as
    literal text; rendering, not storage, owns escaping.
    """
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value)
    kept: list[str] = []
    for character in normalized:
        if character.isspace():
            kept.append(" ")
        elif unicodedata.category(character) in _REMOVED_CATEGORIES:
            continue
        else:
            kept.append(character)
    collapsed = " ".join("".join(kept).split())
    return collapsed[:max_length].rstrip()
