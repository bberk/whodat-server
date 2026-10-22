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

#: Unicode categories removed outright from display text: C0/C1 controls (including NUL) and
#: surrogates. Line and paragraph separators are whitespace, so the collapsing pass below turns
#: them into a single space instead.
_REMOVED_CATEGORIES = frozenset({"Cc", "Cs"})

#: Individual invisible or bidi-affecting code points removed from display text. This is
#: deliberately *not* a blanket ``Cf`` strip: ZWJ (U+200D) and ZWNJ (U+200C) are meaningful in
#: emoji sequences and in Persian/Indic text, and Arabic number signs are meaningful too.
_REMOVED_CODE_POINTS = frozenset(
    {
        0x061C,  # Arabic letter mark
        0x200B,  # zero width space
        0x200E,  # left-to-right mark
        0x200F,  # right-to-left mark
        0x2060,  # word joiner
        0xFEFF,  # BOM / zero width no-break space
    }
)

#: Ranges of bidi embedding/override and isolate controls that can reorder rendered text.
_REMOVED_CODE_POINT_RANGES = ((0x202A, 0x202E), (0x2066, 0x2069))


def _is_removed_code_point(character: str) -> bool:
    """Return whether a display-text character is invisible or unsafe to render."""
    code_point = ord(character)
    if code_point in _REMOVED_CODE_POINTS:
        return True
    if unicodedata.category(character) in _REMOVED_CATEGORIES:
        return True
    return any(start <= code_point <= end for start, end in _REMOVED_CODE_POINT_RANGES)


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

    The result is NFC-normalized, has NUL/C0-C1 controls, surrogates, Unicode line/paragraph
    separators, bidi embedding/override/isolate controls, bidi marks, zero-width spacing
    characters, and any BOM removed, collapses every run of internal whitespace to one space, is
    trimmed, and is capped at ``max_length`` code points. Meaningful format characters — notably
    ZWJ/ZWNJ used by emoji and Persian/Indic text, and Arabic number signs — are preserved. HTML
    characters such as ``<`` and ``>`` stay literal text; rendering, not storage, owns escaping.
    """
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value)
    kept: list[str] = []
    for character in normalized:
        if character.isspace():
            kept.append(" ")
        elif _is_removed_code_point(character):
            continue
        else:
            kept.append(character)
    collapsed = " ".join("".join(kept).split())
    return collapsed[:max_length].rstrip()
