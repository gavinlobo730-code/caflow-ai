"""A bill that is not the SAME number but is probably the same bill.

WHAT THE EXACT CHECK ALREADY DOES, AND WHERE IT STOPS

`routers/purchase_bills._duplicate_bill_id`, with migration 313's unique
index behind it, refuses a second live bill carrying the same vendor's same
invoice number — case- and whitespace-insensitively. That closes the retry, the
re-uploaded CSV and the double-click.

It cannot close the one a practice actually meets. A supplier invoice is keyed
into this product by a human reading a PDF or a scan, and the number is the
field most often mistyped: `INV-2025-1043` entered once as typed and once as
`INV-2025-l043`, `1043` and `1O43`, `INV/1043` and `INV-1043`. Each is a
DIFFERENT key, so the index is satisfied and the bill is booked twice — the
expenditure counted twice, the input tax credit claimed twice under CGST §16,
and, where tax was withheld, the deductee reported twice on the quarterly
statement. Nothing in the product says a word.

WHY THIS WARNS AND NEVER REFUSES

Two bills from one vendor, same date, same amount, different numbers are
perfectly lawful and common — a monthly retainer split across two cost
centres, two identical service calls on one day, a supplier who raises one
invoice per delivery note. Refusing would refuse real work, and a guard that
refuses real work is a guard a CA learns to route around. So this reports and
the CA decides, the same shape as the Rule 46(b) invoice-number sequence gap.

WHAT MAKES TWO BILLS SUSPICIOUS

Both limbs need the same vendor and the same client, and both ignore
cancelled and soft-deleted bills — a cancelled bill is a correction in
progress, and reporting it would make the fix look like the mistake.

  * SAME MONEY, NEAR DATE. Identical `total_paise` within `window_days` of
    each other. The amount is matched EXACTLY and never within a tolerance:
    a tolerance on the amount is a tolerance on the credit claimed, which is
    the same reasoning `domain/gst/itc_matching` gives for never fuzzing the
    tax. Zero-value bills are excluded — several of them in a row is a data
    entry pattern, not a duplicate.

  * SAME NUMBER, DIFFERENT SPELLING. The two invoice numbers are equal once
    separators, leading zeros and the confusion set a mistyped scan produces
    (O/D->0, I/L->1, S->5, B->8, Z->2) are folded away, but are NOT equal the
    way the exact guard compares them. This limb does not require the amounts
    to match, because the typo case is precisely where one of the two figures
    is also wrong.

    It is deliberately NOT an edit distance, and the first draft of this
    module was. A vendor's own invoices are SEQUENTIAL — INV-1043 and
    INV-1044 differ by exactly one character and are two entirely ordinary
    bills — so a one-edit rule warns on very nearly every bill a practice
    enters, and a warning that fires every time is a warning a CA turns off.
    A confusable substitution is a typo signal; a different digit is just the
    next invoice.

The two are reported separately (`reason`) because they send the CA to
different places: the first to compare two documents, the second to look at
one number again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

#: How far apart two bills of identical value may sit and still look like one
#: bill entered twice. A week: a supplier invoice is typically keyed within
#: days of arriving, and the same round retainer in consecutive MONTHS is
#: ordinary business rather than a duplicate.
DEFAULT_WINDOW_DAYS = 7

#: Characters a human or an OCR pass swaps for each other when reading an
#: invoice number off paper. Applied AFTER upper-casing, and the order matters:
#: a case-sensitive map folds "B" to "8" and leaves "b" alone, so "BILL" and
#: "bill" stop matching — the one pair a comparison of invoice numbers must
#: always match.
_CONFUSABLE = {
    "O": "0", "D": "0",
    "I": "1", "L": "1", "|": "1",
    "S": "5",
    "B": "8",
    "Z": "2",
}

#: Stripped before comparison: a supplier's own separators carry no meaning
#: and are the commonest transcription difference (INV/1043 vs INV-1043).
_SEPARATORS = " -_/\\.,#:"


@dataclass(frozen=True)
class NearDuplicate:
    """One existing bill that the new one may be a second copy of."""
    bill_id: str
    bill_no: str
    bill_date: Optional[str]
    total_paise: int
    reason: str        # "same_amount_near_date" | "near_bill_number"
    detail: str        # one sentence a CA can act on


def _as_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalise_number(bill_no: Optional[str]) -> str:
    """An invoice number reduced to what two transcriptions of it share.

    Upper-cased, confusable glyphs folded to one representative, and each
    SEPARATOR-DELIMITED GROUP stripped of its leading zeros before the
    separators go — `INV-2025/0043` and `inv 2025-43` are one number written
    two ways, and a CA who typed both meant one bill.

    The order matters and getting it wrong is silent. Removing the separators
    first fuses `2025` and `0043` into the single group `20250043`, which has
    no leading zero to strip, so the two spellings stay different and the
    warning never fires. Written this way round, they normalise identically.
    """
    if not bill_no:
        return ""
    groups: list[str] = []
    current: list[str] = []
    for ch in str(bill_no):
        if ch in _SEPARATORS:
            if current:
                groups.append("".join(current))
                current = []
            continue
        up = ch.upper()
        current.append(_CONFUSABLE.get(up, up))
    if current:
        groups.append("".join(current))

    out: list[str] = []
    for group in groups:
        # Strip leading zeros only where the whole group is digits: "007" is
        # the number 7, but "A007B" is a code and trimming inside it invents
        # a different one.
        out.append((group.lstrip("0") or "0") if group.isdigit() else group)
    return "".join(out)


def _same_to_the_index(a: Optional[str], b: Optional[str]) -> bool:
    """The exact-duplicate test, spelled the way migration 313's unique index
    and `routers/purchase_bills._duplicate_bill_id` spell it: strip, lower.
    A pair this returns True for has already been refused with a 409."""
    ka, kb = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(ka) and ka == kb


def near_duplicates(
    *,
    bill_no: Optional[str],
    bill_date,
    total_paise: int,
    existing: Iterable[dict],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[NearDuplicate]:
    """Existing bills of the SAME VENDOR that this one may be a copy of.

    `existing` is already scoped to the client and the vendor by the caller —
    this function does not read a database, so the same rule serves the create
    path, the preflight endpoint and the mock-mode doubles without a second
    implementation. Cancelled and soft-deleted rows are dropped here rather
    than in the query, so a caller that forgets the filter still behaves.
    """
    mine_date = _as_date(bill_date)
    mine_key = normalise_number(bill_no)
    out: list[NearDuplicate] = []

    for row in existing:
        if (row.get("status") or "").lower() == "cancelled":
            continue
        if row.get("deleted_at"):
            continue
        other_no = row.get("bill_no") or ""
        other_key = normalise_number(other_no)
        other_total = int(row.get("total_paise") or 0)
        other_date = _as_date(row.get("bill_date"))

        # The exact-number case is the OTHER guard's (a 409 refusal); saying
        # it twice, in two voices, would be worse than saying it once. But
        # "exact" means exact THE WAY THAT GUARD MEANS IT — stripped and
        # lower-cased, matching migration 313's index. Skipping on the
        # NORMALISED key instead would silently drop the whole typo case,
        # since `INV-1043` and `INV-l043` normalise to the same string and
        # the 409 never fires on them.
        if _same_to_the_index(bill_no, other_no):
            continue

        reason = detail = None
        if mine_key and other_key and mine_key == other_key:
            reason = "same_number_different_spelling"
            detail = (
                f"Bill {other_no or '(no number)'} is this same invoice number "
                f"written differently — a separator, a leading zero, or a "
                f"one-for-l. The exact-duplicate check matches the number as "
                f"typed, so two spellings of one number are booked as two "
                f"bills: the expenditure counted twice and the input tax "
                f"credit claimed twice under CGST s.16.")
        elif (total_paise and other_total == total_paise
                and mine_date and other_date
                and abs((mine_date - other_date).days) <= window_days):
            reason = "same_amount_near_date"
            detail = (
                f"Bill {other_no or '(no number)'} dated "
                f"{other_date.isoformat()} is for exactly the same amount and "
                f"is within {window_days} days of this one. If it is the same "
                f"supplier invoice under a different number, booking both "
                f"counts the expenditure twice and claims the input tax credit "
                f"twice under CGST s.16.")

        if reason:
            out.append(NearDuplicate(
                bill_id=str(row.get("id") or ""),
                bill_no=other_no,
                bill_date=other_date.isoformat() if other_date else None,
                total_paise=other_total,
                reason=reason,
                detail=detail or "",
            ))
    return out
