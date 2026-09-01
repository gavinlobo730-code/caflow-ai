"""
GSTIN structure and its check digit — CGST Act 2017, section 25 read with
Rule 10 and the GSTN's published registration-number format.

WHAT A GSTIN IS

    2 7 A A P F U 0 9 3 9 F 1 Z V
    │ │ └──────────┬──────────┘ │ │ └─ check digit
    └─┴─ state     │            │ └─── literal 'Z'
      code         │            └───── entity number for this PAN in this state
                   └────────────────── the PAN of the registered person

THE CHECK DIGIT IS THE POINT OF THIS MODULE

    Six places in this codebase test a GSTIN against the shape above, and the
    shape is not enough. Every transposition inside the PAN passes it:
    27AAPFU0939F1ZV and 27AAPFU0399F1ZV are both well-formed, and only one is a
    real registration.

    That is not a cosmetic error. The GSTIN on a sales invoice is what puts the
    supply into the recipient's GSTR-2B; sent under a GSTIN that is not theirs,
    the recipient never gets the input tax credit, and the correction is an
    amendment in a later return under section 37(3) — inside the window that
    closes on 30 November following the financial year, or the date GSTR-9 was
    furnished, whichever is earlier. A check digit catches it at the keystroke.

    The algorithm is the GSTN's: over the first fourteen characters, take each
    character's value in the 36-symbol alphabet 0-9 then A-Z, multiply by a
    weight alternating 1 and 2, add the quotient and the remainder of that
    product on division by 36, and total. The check digit is the character whose
    value is (36 - total mod 36) mod 36.

WHY THIS IS NOT WIRED INTO models.client.validate_gstin

    Deliberately. That validator guards a Pydantic field and every fixture in
    this repository flows through it — 512 GSTINs across 95 files are
    well-formed inventions that do not carry a real check digit, because they
    are exercising GST arithmetic and cross-tenant isolation rather than
    registration numbers. Tightening the schema type would fail them all and
    prove nothing.

    The check digit belongs where a HUMAN types a GSTIN: the client, customer
    and vendor forms, and onboarding. Those are the places a typo enters, and
    they are the only places it can still be corrected for free.
"""
from __future__ import annotations

import re
from typing import Optional

# 0-9 then A-Z. Position IS the value, so index() and [] are the two directions
# of one mapping.
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_LENGTH = 15

# The same shape models.client.GSTIN_REGEX enforces, restated here so this
# module is self-contained: state code, PAN, entity number (1-9 or A-Z, never
# 0), the literal Z, and the check digit.
GSTIN_SHAPE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# State codes are 01-38, plus 97 (Other Territory) and 99 (Centre Jurisdiction).
# 26 was Dadra & Nagar Haveli and Daman & Diu's merged code from 2020; the old
# 25 was retired but registrations issued under it still exist, so both are
# accepted. This is a range check, not a lookup: a full table would have to be
# maintained against every reorganisation, and its only job here is to reject a
# leading "00" or "51".
VALID_STATE_CODES = frozenset(
    [f"{i:02d}" for i in range(1, 39)] + ["97", "99"]
)


def checksum_char(first_fourteen: str) -> str:
    """The check digit for the first fourteen characters of a GSTIN.

    Integer arithmetic throughout — this is a modular checksum, not a
    calculation, but the same rule applies: nothing here is allowed to be
    approximate.
    """
    if len(first_fourteen) != GSTIN_LENGTH - 1:
        raise ValueError(
            f"a GSTIN check digit is computed over 14 characters, got {len(first_fourteen)}")
    total = 0
    for i, ch in enumerate(first_fourteen):
        try:
            value = ALPHABET.index(ch)
        except ValueError:
            raise ValueError(f"{ch!r} is not a GSTIN character")
        # Weights alternate 1, 2, 1, 2 … starting at 1 for the first character.
        product = value * (2 if i % 2 else 1)
        total += product // len(ALPHABET) + product % len(ALPHABET)
    return ALPHABET[(len(ALPHABET) - total % len(ALPHABET)) % len(ALPHABET)]


def problem_with(gstin: Optional[str]) -> Optional[str]:
    """What is wrong with this GSTIN, or None if nothing is.

    Returns a sentence for a CA, not a code: the message is shown beside the
    field they are typing into, and "invalid GSTIN" tells them nothing about
    which character to look at.
    """
    if gstin is None:
        return None
    g = gstin.strip().upper()
    if g == "":
        return None                      # blank is "unregistered", not "wrong"

    if len(g) != GSTIN_LENGTH:
        return (f"A GSTIN is {GSTIN_LENGTH} characters; this one is {len(g)}.")
    if not GSTIN_SHAPE.match(g):
        return ("Not a GSTIN pattern. It is a 2-digit state code, then a 10-character "
                "PAN, then the entity number, then Z, then the check digit — "
                "e.g. 27AAPFU0939F1ZV.")
    if g[:2] not in VALID_STATE_CODES:
        return (f"{g[:2]} is not a GST state code. They run 01 to 38, plus 97 "
                f"(Other Territory) and 99 (Centre Jurisdiction).")

    expected = checksum_char(g[:14])
    if g[14] != expected:
        return (f"The check digit does not match: this GSTIN ends in {g[14]}, and "
                f"the first 14 characters compute to {expected}. Usually two "
                f"characters have been swapped — check the PAN.")
    return None


def is_valid(gstin: Optional[str]) -> bool:
    """True when a GSTIN is well-formed AND its check digit agrees. Blank is
    valid: a person who is not registered has no GSTIN, which is different from
    having a wrong one."""
    return problem_with(gstin) is None


def state_code(gstin: str) -> Optional[str]:
    """The two-digit state code, which determines place of supply and so whether
    a supply is inter-State (IGST Act §7) or intra-State (§8). None if the GSTIN
    is not one."""
    g = (gstin or "").strip().upper()
    return g[:2] if is_valid(g) and g else None


def pan_of(gstin: str) -> Optional[str]:
    """The PAN embedded in a GSTIN — characters 3 to 12. A registered person's
    GSTIN and their PAN must agree, and this is how that is checked."""
    g = (gstin or "").strip().upper()
    return g[2:12] if is_valid(g) and g else None
