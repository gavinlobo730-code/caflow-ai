"""
Which live e-way bills are about to expire, and which cannot be told.

WHY THIS EXISTS (SALES-28's other half)

    `eway_validity.py` has computed Rule 138(10)'s answer since SALES-28's
    first half, and `/records/{id}/validity` serves it — but only when somebody
    opens that one record. A bill that lapses while the lorry is still moving
    exposes the consignment to detention and seizure under CGST §129, and
    nothing anywhere told the CA it was coming. The extension path
    (`/records/{id}/extend`, the proviso to Rule 138(10)) has existed the whole
    time with nothing to prompt it.

AN EXPIRY IS NOT A COMPLIANCE OBLIGATION AND IS NOT MODELLED AS ONE

    The deadlines screen renders `ComplianceEntry` rows from
    `compliance_engine`, each with a `filing_status` and a Mark Filed action.
    An e-way bill is a document in transit, not a return: nothing is filed, the
    action is to EXTEND, and forcing it into that shape would mean inventing a
    `compliance_type` and offering a button that means nothing. So it is its own
    answer with its own panel — the same reasoning that keeps the filing demo
    off the deadline list.

THE RECORDED DATE WINS OVER THE COMPUTED ONE

    The portal is authoritative and this module says so, exactly as
    `record_ewb_generated` already does: NIC computes the real figure and can
    see things this cannot — a leg by ship, an extension already granted.
    `eway_validity`'s answer is used only where the record carries no date of
    its own, and the answer SAYS which one it used.

MIDNIGHT, NOT A ROLLING DAY

    The Explanation to Rule 138(10) makes a day expire at midnight, so a bill
    valid upto the 20th is good for the whole of the 20th. `EXPIRED` therefore
    means strictly BEFORE today and `EXPIRES_TODAY` is its own bucket — the one
    that most needs saying, because it is the last chance to extend and reads
    as "fine" under a naive `<` comparison.

A BILL WHOSE EXPIRY NOBODY CAN TELL IS NAMED, NOT DROPPED

    A record with no recorded date and no distance produces no expiry at all.
    Leaving it out would make a silent omission look like a clean answer, which
    is the `table_4a_gaps` discipline; counting it as expiring would raise an
    alarm on a fact nobody holds. It is `UNKNOWN`, listed, with the reason
    `eway_validity.expiry_gap` already gives.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

#: Buckets. `UNKNOWN` is not a degree of the others — see the docstring.
EXPIRED = "expired"
EXPIRES_TODAY = "expires_today"
EXPIRING = "expiring"
UNKNOWN = "unknown"

#: What "about to expire" means by default. Rule 138(10) gives one day per 200
#: km, so a two-day horizon is the whole life of most single-day consignments
#: and is short enough that the panel is a prompt rather than a list of
#: everything in transit. The caller may widen it.
DEFAULT_HORIZON_DAYS = 2

SOURCE_RECORDED = "recorded"
SOURCE_COMPUTED = "computed"

PORTAL_IS_AUTHORITATIVE = (
    "The NIC portal computes the real validity and may know things this cannot "
    "— a leg by ship, or an extension already granted. Where a bill carries a "
    "date recorded off the portal that date is used; a computed one is a "
    "cross-check and a prompt, never a substitute.")

EXTENSION_IS_THE_ACTION = (
    "Nothing is filed for an e-way bill. Where a consignment is still in "
    "transit the proviso to Rule 138(10) allows the validity to be extended on "
    "the portal; record it here afterwards.")


@dataclass(frozen=True)
class Expiring:
    record_id: str
    client_id: str
    invoice_number: str
    ewb_number: Optional[str]
    valid_upto: Optional[str]
    source: Optional[str]
    days_left: Optional[int]
    state: str
    gap: Optional[str] = None


def _as_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except (ValueError, TypeError):
        return None


def state_for(valid_upto: Optional[date], today: date,
              horizon_days: int) -> tuple[str, Optional[int]]:
    """Which bucket a date falls in, and how many days are left.

    Split out so the boundaries are testable without a record: the difference
    between "expires today" and "expired" is one day on a document whose lapse
    is a §129 detention, and it is exactly the boundary a `<` gets wrong.
    """
    if valid_upto is None:
        return UNKNOWN, None
    days = (valid_upto - today).days
    if days < 0:
        return EXPIRED, days
    if days == 0:
        return EXPIRES_TODAY, 0
    if days <= horizon_days:
        return EXPIRING, days
    return "", days


def assess(records, today: date, horizon_days: int = DEFAULT_HORIZON_DAYS,
           computed_expiry=None) -> dict:
    """The live bills worth telling the CA about, worst first.

    `records` are `eway_bill_records` rows. `computed_expiry` is an optional
    callable taking a row and returning an ISO date or None — the caller passes
    `_computed_validity`'s answer so Rule 138(10) is not restated here.
    """
    out: list = []
    for row in records or []:
        if not (row.get("ewb_number") or "").strip():
            continue                     # never generated — nothing is running
        if (row.get("status") or "").lower() == "cancelled":
            continue

        recorded = _as_date(row.get("ewb_valid_upto"))
        source = SOURCE_RECORDED if recorded else None
        valid = recorded
        gap = None
        if valid is None and computed_expiry is not None:
            answer = computed_expiry(row) or {}
            valid = _as_date(answer.get("valid_upto"))
            source = SOURCE_COMPUTED if valid else None
            gap = answer.get("gap")

        state, days = state_for(valid, today, horizon_days)
        if not state:
            continue                     # comfortably live — not a prompt
        out.append(Expiring(
            record_id=str(row.get("id") or ""),
            client_id=str(row.get("client_id") or ""),
            invoice_number=row.get("invoice_number") or "",
            ewb_number=row.get("ewb_number"),
            valid_upto=valid.isoformat() if valid else None,
            source=source,
            days_left=days,
            state=state,
            gap=gap,
        ))

    rank = {EXPIRED: 0, EXPIRES_TODAY: 1, EXPIRING: 2, UNKNOWN: 3}
    out.sort(key=lambda e: (rank[e.state], e.days_left if e.days_left is not None else 0,
                            e.invoice_number))
    return {
        "as_of": today.isoformat(),
        "horizon_days": horizon_days,
        "bills": out,
        "expired": sum(1 for e in out if e.state == EXPIRED),
        "expires_today": sum(1 for e in out if e.state == EXPIRES_TODAY),
        "expiring": sum(1 for e in out if e.state == EXPIRING),
        "undeterminable": sum(1 for e in out if e.state == UNKNOWN),
        "caveats": [PORTAL_IS_AUTHORITATIVE, EXTENSION_IS_THE_ACTION],
    }
