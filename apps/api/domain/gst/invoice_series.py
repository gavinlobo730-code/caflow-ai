"""
A tax invoice's number — CGST Rule 46(b), as code.

THE RULE, in full, because all three limbs matter and only two were enforced:

    "a CONSECUTIVE SERIAL NUMBER not exceeding SIXTEEN CHARACTERS, in one or
     multiple series, containing alphabets or numerals or special characters
     hyphen or dash and slash symbolised as '-' and '/' respectively, and any
     combination thereof, UNIQUE FOR A FINANCIAL YEAR"

  * SIXTEEN CHARACTERS — `services/numbering.py` knew this one: its DRAFT-
    placeholder is sized to fit. Nothing checked a number the CA typed.
  * UNIQUE FOR A FINANCIAL YEAR — enforced, and deliberately stricter: a
    partial unique index on (firm_id, client_id, invoice_no) makes it unique
    for the client full stop (migration 151, made partial by 209).
  * CONSECUTIVE — enforced NOWHERE. A CA could type INV-1, then INV-57, then
    INV-9, and all three were accepted. Gaps and out-of-order numbers are a
    standard GSTR-1 scrutiny query, and it is the one limb manual typing
    cannot self-enforce.
  * THE CHARACTER SET — also enforced nowhere. `INV#001` is not a number Rule
    46(b) permits, and the IRP rejects malformed document numbers outright, so
    a number typed today can be one e-invoicing refuses tomorrow.

WHY THIS EXISTS NOW, AND WHAT IT REVERSES
    `numbering.py` and `routers/sales_invoices.py` both recorded a decision:
    "numbering is fully manual — no Caflow-generated scheme". That decision was
    not wrong on the law; manual numbering is legal. But it left CONSECUTIVE
    unguarded, and it put the product out of step with every tool a CA already
    uses — Tally's voucher numbering offers Automatic, Manual and
    "Automatic (Manual Override)", and the third is what practices actually
    run. `invoice_settings.manual_override_allowed` is that mode's name; the
    column has been modelling this since migration 126.

    Reversed on the owner's decision of 2026-09-12, and reversed in its DEFAULT
    only, not its capability: the number is suggested, stays editable, and a
    break in the sequence WARNS rather than blocks. The case the original
    decision protected is exactly the case a warning serves — a client arriving
    mid-year with a series already running, an import, a correction. Blocking
    would strand them; saying nothing is what we did before.

WHAT REFUSES AND WHAT WARNS, and the line is the statute's own
    A number that BREAKS THE RULE is refused: over sixteen characters, or
    carrying a character Rule 46(b) does not permit. Those are not judgement
    calls and no legitimate series needs them.
    A number that BREAKS THE SEQUENCE only warns. A gap can be a cancelled
    invoice, a migration mid-year, or a second series the firm runs on
    purpose — the rule allows "one or multiple series" — and refusing would
    make the product wrong about a practice that is right.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

#: Rule 46(b)'s ceiling.
MAX_LENGTH = 16

#: Rule 46(b)'s permitted characters: alphabets, numerals, hyphen/dash, slash.
#: Nothing else — not '#', not '_', not a space. Anchored, so a stray character
#: anywhere fails rather than only at the ends.
ALLOWED_RE = re.compile(r"^[A-Za-z0-9/-]+$")

#: The separator between the parts of a generated number. Rule 46(b) permits
#: '-' and '/'; '/' is the Indian convention (INV/2026-27/001) and is what a CA
#: reading a ledger expects. Not configurable, because a second separator would
#: be a second series shape to keep in step for no gain.
SEPARATOR = "/"


@dataclass(frozen=True)
class SeriesSettings:
    """The firm's own numbering choices, from `invoice_settings` (migration 126)."""
    prefix: str = "INV"
    include_financial_year: bool = True
    sequence_length: int = 3
    starting_number: int = 1
    manual_override_allowed: bool = False

    @classmethod
    def from_row(cls, row: Optional[dict]) -> "SeriesSettings":
        """Build from the stored row, falling back to the column defaults.

        A firm that has never opened Invoice Settings has no row at all, and
        the defaults here are migration 126's own — so an un-configured firm
        gets INV/2026-27/001 rather than an error or a blank."""
        r = row or {}
        return cls(
            prefix=(r.get("prefix") or "INV").strip(),
            include_financial_year=bool(r.get("include_financial_year", True)),
            sequence_length=int(r.get("sequence_length") or 3),
            starting_number=int(r.get("starting_number") or 1),
            manual_override_allowed=bool(r.get("manual_override_allowed", False)),
        )


def format_number(settings: SeriesSettings, fy_label: str, sequence: int) -> str:
    """One number in the series, e.g. `INV/2026-27/001`.

    `fy_label` is the readable `YYYY-YY` form, not `fy_code`'s `2627`: this
    string is printed on a document a customer reads and a CA reconciles, and
    seven characters of the sixteen is a price worth paying for that. Where it
    does not fit, `length_gap` below says which setting to shorten rather than
    silently truncating — a truncated number is a different number.
    """
    parts = [settings.prefix]
    if settings.include_financial_year:
        parts.append(fy_label)
    parts.append(str(max(1, sequence)).zfill(max(1, settings.sequence_length)))
    return SEPARATOR.join(p for p in parts if p)


def length_gap(settings: SeriesSettings, fy_label: str) -> Optional[str]:
    """Why this configuration cannot produce a legal number, or None.

    Checked against the LAST number the series can reach, not the first: a
    prefix that fits at 001 and overflows at 1000 is a series that breaks in
    the middle of a busy year, which is the worst time to find out.
    """
    longest = format_number(settings, fy_label, 10 ** max(1, settings.sequence_length) - 1)
    if len(longest) <= MAX_LENGTH:
        return None
    over = len(longest) - MAX_LENGTH
    return (f"This numbering series reaches {len(longest)} characters at its highest "
            f"number ({longest}), and CGST Rule 46(b) allows sixteen. Shorten the "
            f"prefix by {over} character{'s' if over > 1 else ''}"
            + (", or turn off the financial year." if settings.include_financial_year
               else "."))


def format_violation(invoice_no: str) -> Optional[str]:
    """Why this number breaks Rule 46(b) outright, or None. A refusal, not a
    warning: no legitimate series needs seventeen characters or a '#'."""
    n = (invoice_no or "").strip()
    if not n:
        return "An invoice needs a number — CGST Rule 46(b)."
    if len(n) > MAX_LENGTH:
        return (f"“{n}” is {len(n)} characters. CGST Rule 46(b) allows a maximum of "
                f"sixteen on a tax invoice.")
    if not ALLOWED_RE.match(n):
        bad = sorted({c for c in n if not ALLOWED_RE.match(c)})
        shown = " ".join(repr(c) for c in bad)
        return (f"“{n}” contains {shown}. CGST Rule 46(b) allows only letters, digits, "
                f"hyphen and slash in an invoice number.")
    return None


def settings_gap(settings: SeriesSettings, fy_label: str) -> Optional[str]:
    """Why this firm's configuration cannot produce a legal number, or None.

    Two ways it can fail, and both have to be asked or the answer is wrong for
    half the firms: the PREFIX is free text with no CHECK on the column, so it
    can carry a character Rule 46(b) forbids; and the whole number can overflow
    sixteen characters at the top of the series even when it fits at the
    bottom. Asked together here so the one caller that needs an answer gets
    one string back, rather than a first complaint that hides a second.
    """
    first = format_number(settings, fy_label, max(1, settings.starting_number))
    bad = format_violation(first)
    if bad and len(first) <= MAX_LENGTH:
        # A character problem: it comes from the prefix, since the financial
        # year and the digits cannot contribute one. Say so, because the CA is
        # looking at a settings screen, not at this number.
        return (f"This numbering series produces “{first}”, which CGST Rule 46(b) does "
                f"not permit: only letters, digits, hyphen and slash are allowed in an "
                f"invoice number. Change the prefix.")
    return length_gap(settings, fy_label)


#: Trailing digits are the sequence. Everything before them is the series' own
#: identity — prefix and financial year — so two numbers belong to the same
#: series when that leading part matches.
_TAIL = re.compile(r"^(?P<head>.*?)(?P<seq>\d+)$")


def split_number(invoice_no: str) -> tuple[str, Optional[int]]:
    """(series head, sequence) — or (whole string, None) when it ends in no digit."""
    m = _TAIL.match((invoice_no or "").strip())
    if not m:
        return (invoice_no or "").strip(), None
    return m.group("head"), int(m.group("seq"))


def next_sequence(existing: Iterable[str], settings: SeriesSettings, fy_label: str) -> int:
    """One past the HIGHEST sequence already used in this series this year.

    Max+1, never count+1 — the reasoning is `services/numbering.sequence_after`'s
    and it is the same trap: count+1 returns a number already taken as soon as
    one document in the middle is deleted, deterministically, for the rest of
    the year.

    Only numbers sharing this series' head are counted. A firm running a second
    series on purpose — Rule 46(b) allows "one or multiple" — does not have its
    other series' numbers dragged into this one's tally.
    """
    head, _ = split_number(format_number(settings, fy_label, 1))
    highest = 0
    for n in existing or []:
        h, seq = split_number(n)
        if seq is not None and h == head:
            highest = max(highest, seq)
    return max(highest + 1, max(1, settings.starting_number))


def sequence_break(invoice_no: str, existing: Iterable[str],
                   settings: SeriesSettings, fy_label: str) -> Optional[str]:
    """Why this number is not the next one in its series, or None.

    A WARNING. Rule 46(b) requires a consecutive serial number, and this is the
    limb nothing in the product checked — but a gap has legitimate causes (a
    series carried over mid-year, a cancelled invoice, a second series) and
    refusing would make the product wrong about practices that are right. So it
    is said, once, at the point the number is chosen, and the CA decides.

    Silent when the number is not in this series at all: a firm's other series
    is not this one's business, and complaining about it would train the CA to
    ignore the warning that matters.
    """
    expected = next_sequence(existing, settings, fy_label)
    head, seq = split_number(invoice_no)
    if seq is None:
        return None
    series_head, _ = split_number(format_number(settings, fy_label, 1))
    if head != series_head:
        return None
    if seq == expected:
        return None
    if seq < expected:
        return (f"“{invoice_no}” is out of order — this series has already reached "
                f"{expected - 1}. CGST Rule 46(b) requires a consecutive serial number.")
    missing = seq - expected
    return (f"“{invoice_no}” skips {missing} number{'s' if missing > 1 else ''} — the next "
            f"in this series is {format_number(settings, fy_label, expected)}. CGST Rule "
            f"46(b) requires a consecutive serial number; a gap is a standard GSTR-1 "
            f"scrutiny query, so keep a record of why if it is deliberate.")
