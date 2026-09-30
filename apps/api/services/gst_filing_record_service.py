"""
What was filed, recorded — on the return row and in `filings`.

WHY THIS EXISTS
    Two things were true before this module:

    1. gstr1_returns/gstr3b_returns carry submitted_at, arn, ca_approved_by and
       ca_approved_at (migration 036). Marking a return submitted wrote ONLY
       `status`. Every other column stayed NULL, so "what did we actually file,
       when, and who approved it" had no answer in the database.

    2. Nothing in the entire codebase had ever written a row to `filings`. The
       only thing that reads it is journal_period_lock_reason (migration 266) —
       the function that refuses to edit a journal in a period whose return has
       been filed. With the table permanently empty, that half of the lock could
       never fire. The guard was correct and unreachable.

    The second is why this is not a reporting nicety. A lock nobody can trip is
    the same as no lock, and it looked like a working feature: the real-Postgres
    tests for 266 seeded `filings` themselves, which proved the SQL was right
    and proved nothing about whether anything fills the table.

WHAT A FILING RECORD IS FOR
    Three different readers, one row:
      * the period lock — "is this date inside something already filed?"
      * the exception report — "do the books still say what the return said?",
        which needs the payload frozen as at filing
      * the CA — "what is our ARN for GSTR-3B, June?"

    It is also the row a GSP integration will later fill in from the portal's
    response rather than from a CA typing it, which is why the shape follows the
    filing (ARN, filed date, period covered) rather than our own workflow.

IMMUTABILITY
    Once a return is submitted its payload is frozen. A GST return cannot be
    revised — corrections are declared in a later period's amendment tables
    (CGST Act §37) — so a stored payload that could still change would make the
    exception report compare books against a moving target.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.ist_clock import ist_today
from domain.gst import return_period

_logger = logging.getLogger("caflow.gst_filing")

# The `filings.filing_type` values these returns record under. Read by
# journal_period_lock_reason, and shown to the CA in the lock message, so they
# are the names a CA uses rather than our table names.
FILING_TYPE_GSTR1 = "GSTR-1"
FILING_TYPE_GSTR3B = "GSTR-3B"

# filings.status is CHECK-constrained to these (migration 001).
_FILED = "filed"

# Which obligations close a period when they are recorded as filed, and under
# which `filings.filing_type`. Keyed on the vocabulary BOTH calendars share —
# compliance_calendar.compliance_type and compliance_records.obligation_type
# both say "GSTR1" / "GSTR3B" — so the two doors that record a filing ask ONE
# map rather than keeping a copy each. Deliberately NOT every return: see
# NO_FILING_ROW_REASON.
FILING_TYPE_FOR_RETURN = {
    "GSTR1":  FILING_TYPE_GSTR1,
    "GSTR3B": FILING_TYPE_GSTR3B,
}

# Why a type can be marked filed on a calendar and still lock nothing. Said out
# loud, per type, and returned to the caller: a silent no-op here is the same
# defect in a new place — the CA has to be able to see that the tick did not
# close the period.
NO_FILING_ROW_REASON = {
    "GSTR9": ("GSTR-9 is the annual return. Furnishing it closes the CORRECTION "
              "WINDOW under §37(3)/§39(9)/§16(4) — see "
              "compliance_engine.correction_window_closes() — which is a "
              "different rule from the period lock. Recording it here would "
              "freeze a whole financial year's books."),
    "GSTR9C": ("GSTR-9C is the reconciliation statement that goes with the "
               "annual return GSTR-9. It closes no GST period; the correction "
               "window is what GSTR-9 itself closes."),
    "ITR":    "An income-tax return is not a GST period; the GST period lock does not apply.",
    # All the quarterly statements, because the calendar generates all of them
    # (TDS-12 added 24Q) and this map exists to say it PER TYPE — a generic
    # sentence about GST returns is a worse answer than the specific one.
    "TDS24Q": "A TDS return is not a GST period; the GST period lock does not apply.",
    "TDS26Q": "A TDS return is not a GST period; the GST period lock does not apply.",
    "TDS27Q": "A TDS return is not a GST period; the GST period lock does not apply.",
    "TDS27EQ": "A TCS return is not a GST period; the GST period lock does not apply.",
}
NO_FILING_ROW_DEFAULT = (
    "public.filings records GST returns of supplies (GSTR-1 and GSTR-3B). "
    "This obligation is tracked on the calendar but closes no GST period."
)


def not_recorded_reason(obligation_type: str) -> str:
    """Why an obligation of this type recorded no `filings` row."""
    return NO_FILING_ROW_REASON.get(obligation_type, NO_FILING_ROW_DEFAULT)


def record_obligation_filing(
    db, *, record: dict, filed_date: str, arn: Optional[str] = None,
) -> Optional[dict]:
    """Record the filing an OBLIGATION stands for, if it is a GST return of
    supplies — and return the `filings` row, or None if this obligation closes
    no period.

    The window is the obligation's OWN `period_start`/`period_end`, never a
    month derived from them: a QRMP client's GSTR-1 obligation covers a quarter
    and locking only its first month would leave two filed months editable
    (GST-11). Both bounds or no row — `compliance_records` has them NOT NULL, so
    a missing one cannot happen against the real schema, but `record_filing`
    would otherwise fall back to `period_bounds("")` and raise ValueError,
    turning a malformed row into a 500 instead of a stated reason.

    The key is `obligation_type` — `compliance_type` on this table is the
    family ("GST"), not the return.
    """
    filing_type = FILING_TYPE_FOR_RETURN.get(str(record.get("obligation_type") or ""))
    start = str(record.get("period_start") or "")[:10]
    end = str(record.get("period_end") or "")[:10]
    if not filing_type or len(start) != 10 or len(end) != 10:
        return None
    return record_filing(
        db, firm_id=record.get("firm_id") or "", client_id=record.get("client_id") or "",
        filing_type=filing_type, period=f"{start[5:7]}{start[0:4]}",
        filed_date=filed_date, arn=arn, bounds=(start, end),
    )


def period_bounds(period: str, frequency: Optional[str] = None) -> tuple[str, str]:
    """'MMYYYY' → (first_iso, last_iso) of the period the return covered.

    The lock asks `date BETWEEN period_start AND period_end`, so these are the
    two values that decide which entries a filed return freezes.

    A MONTH unless the registration is on QRMP (Rule 61A with the proviso to
    CGST s.39(1)), in which case it is the QUARTER — the return really did
    cover three months, and locking one of them leaves the other two editable
    after a return declaring them has been filed (GST-11).

    It delegates to `domain/gst/return_period`, which is a leaf domain module
    with no database handle, rather than to `gst_return_service._period_bounds`
    — importing the return ENGINE from a module the router imports would drag
    the ledger reader in with it, which is the reason the duplicate existed in
    the first place. There is no second statement of the rule now, only a
    second door onto it.
    """
    return return_period.bounds(period, frequency)


def build_filings_row(
    *, firm_id: str, client_id: str, filing_type: str, period: str,
    filed_date: str, arn: Optional[str] = None,
    tax_payable_paise: Optional[int] = None, summary: Optional[dict] = None,
    bounds: Optional[tuple[str, str]] = None,
    frequency: Optional[str] = None,
) -> dict:
    """The `filings` row for a submitted return.

    Every field here is load-bearing for journal_period_lock_reason, which
    matches on:

        client_id = p_client
        AND deleted_at IS NULL
        AND filed_date IS NOT NULL
        AND p_date BETWEEN period_start AND period_end

    A row missing filed_date, or with the period bounds wrong, is a row the lock
    silently skips — so this is kept in one place and asserted against that
    predicate in the tests rather than being assembled at each call site.

    filed_by is deliberately left unset: the column references team_members(id)
    (migration 001) and the actor we have is a users.id, which would either
    violate the FK or record the wrong person.
    """
    # TWO WAYS TO SAY THE SAME THING, FOR TWO CALLERS THAT HOLD DIFFERENT
    # FACTS, and `bounds` wins where both are given.
    #
    # `bounds` is a window somebody RECORDED: the compliance calendar stores a
    # QRMP obligation's real start and end, and deriving a month from it would
    # write a filings row covering April when the return filed covered April to
    # June — under-locking two of the three months, silently.
    #
    # `frequency` is the REGISTRATION's, for the workspace path, which holds
    # `gstr1_returns.period` and the GSTIN it was filed under and no window at
    # all. It derives the same quarter through the one authority rather than
    # the router doing the arithmetic (GST-11).
    #
    # `bounds` wins because it is a recorded fact and the frequency is only the
    # rule for deriving one; if a caller has both and they disagree, what the
    # obligation says the return covered is the answer.
    start, end = bounds if bounds else period_bounds(period, frequency)
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "filing_type": filing_type,
        "period_start": start,
        "period_end": end,
        "filed_date": filed_date,
        "status": _FILED,
    }
    if arn:
        row["acknowledgement_number"] = arn
    if tax_payable_paise is not None:
        row["tax_payable_paise"] = int(tax_payable_paise)
    if summary is not None:
        row["filing_data"] = summary
    return row


def record_filing(
    db, *, firm_id: str, client_id: str, filing_type: str, period: str,
    filed_date: Optional[str] = None, arn: Optional[str] = None,
    tax_payable_paise: Optional[int] = None, summary: Optional[dict] = None,
    bounds: Optional[tuple[str, str]] = None,
    frequency: Optional[str] = None,
) -> dict:
    """Write (or refresh) the `filings` row for a submitted return.

    Idempotent on (client_id, filing_type, period): `filings` has no unique
    constraint over those, so marking the same return submitted twice would
    otherwise leave two rows claiming the same period. The lock takes the
    earliest filed_date of whatever it finds, so duplicates are not fatal — but
    two rows for one filing is a lie about the world, and the CA reads this
    table.
    """
    row = build_filings_row(
        firm_id=firm_id, client_id=client_id, filing_type=filing_type,
        period=period, filed_date=filed_date or ist_today().isoformat(),
        arn=arn, tax_payable_paise=tax_payable_paise, summary=summary,
        bounds=bounds, frequency=frequency,
    )
    existing = (db.table("filings").select("id")
                .eq("client_id", client_id)
                .eq("filing_type", filing_type)
                .eq("period_start", row["period_start"])
                .eq("period_end", row["period_end"])
                .limit(1).execute().data) or []
    if existing:
        db.table("filings").update(row).eq("id", existing[0]["id"]).execute()
        row["id"] = existing[0]["id"]
    else:
        db.table("filings").insert(row).execute()
    return row


def return_status_patch(
    status: str, *, actor_id: Optional[str] = None, arn: Optional[str] = None,
    now_iso: str,
) -> dict:
    """The columns a status change should write on the return row itself.

    Before this, a status change wrote `status` and nothing else, leaving the
    timestamps and the approver NULL on every return ever filed. Rule 3(1)-style
    reasoning applies to a tax return too: an approval with no approver and no
    time recorded is not much of an approval.
    """
    patch: dict = {"status": status}
    if status == "validated":
        patch["validated_at"] = now_iso
    elif status == "ca_approved":
        patch["ca_approved_at"] = now_iso
        if actor_id:
            patch["ca_approved_by"] = actor_id
    elif status == "submitted":
        patch["submitted_at"] = now_iso
        # A return can go straight from validated to submitted; the CA who
        # confirmed the submit IS the approver, and leaving the column NULL
        # because the intermediate step was skipped would lose that.
        patch["ca_approved_at"] = now_iso
        if actor_id:
            patch["ca_approved_by"] = actor_id
        if arn:
            patch["arn"] = arn
    return patch
