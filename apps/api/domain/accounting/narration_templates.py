"""A narration template: words a practice reuses on a client's manual journals (POST-A-093).

A manual journal's narration is required and is the one place an entry says why it was made ("Being depreciation for the month on
the straight-line method", "Being salary payable for the month"). A practice types the same few dozen sentences every month for every
client, and Tally keeps them for exactly that reason. A template here is those words and nothing else: picking one FILLS the journal's
narration box, which the CA may still change, and the entry stores the words, never the template. So archiving or rewording a
template later changes no entry, and no figure reads a template.

This module is the rule for the words themselves; `services/narration_template_service` reads and writes them.

    * `normalise` is what is stored and compared: the ends trimmed and every run of white space (a newline included: the journal's
      narration box is a single line) made one space.
    * `problem` refuses words that are empty once normalised, longer than `MAX_LENGTH`, or carry a control character; it returns
      the sentence, or None.
    * `same_words` is the duplicate test: two templates are the same when their normalised words match ignoring case, because a
      picker that offers "Being salary payable" twice is two rows a CA must read to find they say one thing.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: The longest template kept. Not a statutory figure: a picker shows each template on one line, and a narration much longer than this
#: is a note, which belongs in the entry's supporting documents.
MAX_LENGTH = 300

_WHITE = re.compile(r"\s+")

#: The direction controls (U+202A..U+202E, U+2066..U+2069): text that reads differently from what it stores. A joiner (U+200C, U+200D)
#: is not one: Devanagari and Malayalam need them.
_BIDI_CONTROLS = frozenset(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))


def normalise(text: Optional[str]) -> str:
    """The words as they are stored: ends trimmed, every run of white space one space."""
    return _WHITE.sub(" ", str(text or "")).strip()


def problem(text: Optional[str]) -> Optional[str]:
    """Why these words cannot be a template, in one sentence, or None."""
    words = normalise(text)
    if not words or not any(not unicodedata.category(ch).startswith(("Z", "C")) for ch in words):
        return "A narration template needs some words."
    if len(words) > MAX_LENGTH:
        return f"A narration template is at most {MAX_LENGTH} characters; this one is {len(words)}."
    if any(unicodedata.category(ch) == "Cc" or ch in _BIDI_CONTROLS for ch in words):
        return "A narration template cannot carry a control character."
    return None


def key(text: Optional[str]) -> str:
    """What two templates are compared by, and what the database's unique index holds: the normalised words, case-folded."""
    return normalise(text).casefold()


def same_words(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two templates say the same thing: their keys match."""
    return key(a) == key(b)
