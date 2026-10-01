"""The marketing site's COPY, as sentences — shared by the claims ledger's guard.

`apps/marketing` has no test runner, so what the public site says is checked from
here (the Schedule III caption lesson: a guard inside the thing it guards passes
whenever the thing and its copy drift together).

WHAT COUNTS AS COPY. Every string literal and every run of JSX text in the site's
`.ts`/`.tsx` under `app/`, `components/` and `lib/`, comments blanked first (a
comment explaining why a claim was removed must not read as the claim), split
into sentences. A fragment of fewer than four words is not a sentence a visitor
would read as a claim and is dropped, and so is anything that is plainly a CSS
class list or an import.

WHAT IT CANNOT SEE, and says so. Text assembled at run time — `"a " + b`, a
template with a `${}` hole — is read as the fragments around the hole, and copy
that lives in an image or a PDF is not text at all. A claim made that way is
invisible to every guard built on this module, which is why the ledger's own
header asks for the sentence to be written out whole.
"""
from __future__ import annotations

import re
from pathlib import Path

MARKETING = Path(__file__).resolve().parents[2] / "marketing"
SOURCE_DIRS = ("app", "components", "lib")

# A single quote only OPENS a string where it is not part of a word: an apostrophe in
# "firm's" or "clients'" in JSX text is not a string delimiter.
_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|(?<!\w)\'((?:[^\'\\\n]|\\.)*)\'(?!\w)|`((?:[^`\\]|\\.)*)`')
# JSX text runs from a `>` to the next `<`, across lines (a paragraph is formatted onto its
# own line, so the character after the `>` is very often a newline), and holds a letter.
_JSX_TEXT = re.compile(r">([^<>{}]*[A-Za-z][^<>{}]*)<")
# An inline element does not end a sentence: `a <strong>never</strong> b` is one.
_INLINE_TAG = re.compile(r"</?(?:strong|b|em|i|span|a|code|u|mark|sup|sub|br)\b[^<>{}]*>")
_SPACE_EXPR = re.compile(r"\{\s*(?:\" \"|' '|`\s*`)\s*\}")
_ENTITIES = {"&apos;": "'", "&#39;": "'", "&amp;": "&", "&quot;": '"', "&nbsp;": " ",
             "&mdash;": "—", "&ndash;": "–", "&rsquo;": "'", "&lsquo;": "'"}


def sources() -> list[Path]:
    return sorted(p for d in SOURCE_DIRS for p in (MARKETING / d).rglob("*")
                  if p.suffix in (".tsx", ".ts") and p.is_file())


def blank_comments(src: str) -> str:
    """Comment characters replaced with spaces (a `://` is not a comment)."""
    out = list(src)
    i, n = 0, len(src)
    block = line = False
    while i < n:
        if block:
            if src.startswith("*/", i):
                out[i] = out[i + 1] = " "
                i += 2
                block = False
                continue
            if src[i] != "\n":
                out[i] = " "
            i += 1
            continue
        if line:
            if src[i] == "\n":
                line = False
            else:
                out[i] = " "
            i += 1
            continue
        if src.startswith("//", i) and not (i and src[i - 1] == ":"):
            line = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        if src.startswith("/*", i):
            block = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        i += 1
    return "".join(out)


def normalise(text: str) -> str:
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    text = text.replace("\\'", "'").replace('\\"', '"').replace("\\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_copy(unit: str) -> bool:
    if not re.search(r"[A-Za-z]{3,} [A-Za-z]{3,}", unit):
        return False
    # a class list, an import, a CSS declaration, an inline image — not something a visitor reads
    return not re.search(
        r"className|=>|\bimport\b.*\bfrom\b|^\s*[#.\w-]+\s*:\s*[\w-]+;|data:image|<svg|\burl\(", unit)


def _units(src: str):
    src = _SPACE_EXPR.sub(" ", _INLINE_TAG.sub(" ", blank_comments(src)))
    for m in _STRING.finditer(src):
        yield next(g for g in m.groups() if g is not None)
    for m in _JSX_TEXT.finditer(src):
        yield m.group(1)


# A full stop that ends an abbreviation does not end a sentence.
_ABBREVIATION = re.compile(r"\b(e\.g|i\.e|vs|etc|no|approx)\.$", re.I)


def sentences_of(text: str, min_words: int = 4):
    text = normalise(text)
    pieces: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", text):
        if pieces and _ABBREVIATION.search(pieces[-1]):
            pieces[-1] = f"{pieces[-1]} {part}"
        else:
            pieces.append(part)
    for s in pieces:
        if len(s.split()) >= min_words:
            yield s


def copy_sentences(min_words: int = 4) -> dict[str, set[str]]:
    """{sentence: {site-relative files it appears in}}.

    `min_words` is 4 for "a sentence a visitor reads as a claim". A feature BULLET
    ("Single sign-on (SSO)", "SLA & account manager") is two or three words and is
    exactly where a plan's promises live, so the claims ledger asks for 2 and lets
    its own vocabulary do the choosing."""
    found: dict[str, set[str]] = {}
    for path in sources():
        rel = path.relative_to(MARKETING).as_posix()
        for unit in _units(path.read_text(encoding="utf-8")):
            if not _looks_like_copy(unit):
                continue
            for s in sentences_of(unit, min_words):
                found.setdefault(s, set()).add(rel)
    return found
