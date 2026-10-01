"""A model may WORD computed facts and may not add to them (ai-08, ai-25).

THE RULE
    Every screen in this product that puts a model's sentence beside a computed
    number has the same exposure: the model is handed "12 overdue filings" and
    writes "12 overdue filings, about a third of the book", and "a third" is a
    figure no engine computed. A CA reads the whole paragraph as the software's
    own and cannot tell which part was arithmetic.

    So the facts go IN as a closed set of numbers, the reply comes OUT and is
    read for numbers, and a reply carrying any number outside that set is
    DISCARDED — the caller falls back to the plain sentence it already built
    from the same facts. The model never gets to decide what is true; at most
    it gets to decide how a true thing is phrased.

WHAT COUNTS AS A NUMBER
    A standalone figure: `12`, `1,25,000`, `4.5`. NOT a figure that is part of a
    word or an identifier — `20th`, `GSTR-3B`, `26Q`, `194J`, `FY2026-27`'s
    letters — because those name a thing rather than quantify one, and refusing
    a reply for saying "GSTR-3B" would make the check a nuisance nobody keeps.
    That is also its limit and it is stated rather than hidden: a form number
    spelled as a bare digit ("Form 140") IS read as a figure, so the facts a
    caller passes must include any such number it expects the model to use.

WHAT IT DOES NOT CHECK
    Whether a number is attached to the right thing. "3 overdue filings" where
    the engine said 3 overdue returns and 3 unfiled ones passes. It stops
    INVENTED figures; it does not make the prose correct. The numbers are also
    shown beside the sentence on every screen that uses this, which is the
    other half of the defence.

Pure: no model call, no I/O.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable

# A figure that stands alone: not glued to a letter either side (so `3B`, `26Q`,
# `20th` and `FY26` are skipped) and not the tail of a longer figure.
_FIGURE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")


def _canonical(token: str) -> str | None:
    try:
        d = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    text = format(d.normalize(), "f")
    return text


def numbers_in(text: str) -> set[str]:
    """The standalone figures in `text`, as canonical strings ("1,20" -> "120")."""
    found = set()
    for m in _FIGURE.finditer(text or ""):
        c = _canonical(m.group(1))
        if c is not None:
            found.add(c)
    return found


def allowed_set(values: Iterable) -> set[str]:
    """The closed set of figures a reply may contain."""
    out: set[str] = set()
    for v in values:
        if v is None or isinstance(v, bool):
            continue
        c = _canonical(str(v))
        if c is not None:
            out.add(c)
    return out


def ungrounded_numbers(text: str, allowed: Iterable) -> list[str]:
    """Figures the reply contains that nobody computed, sorted."""
    return sorted(numbers_in(text) - allowed_set(allowed),
                  key=lambda s: (len(s), s))


def is_grounded(text: str, allowed: Iterable) -> bool:
    """True when every standalone figure in the reply is one of `allowed`."""
    return not ungrounded_numbers(text, allowed)
