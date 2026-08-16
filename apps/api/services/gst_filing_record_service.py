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

import calendar
import logging
from typing import Optional

from core.ist_clock import ist_today

_logger = logging.getLogger("caflow.gst_filing")

# The `filings.filing_type` values these returns record under. Read by
# journal_period_lock_reason, and shown to the CA in the lock message, so they
# are the names a CA uses rather than our table names.
FILING_TYPE_GSTR1 = "GSTR-1"
FILING_TYPE_GSTR3B = "GSTR-3B"

# filings.status is CHECK-constrained to these (migration 001).
_FILED = "filed"


def period_bounds(period: str) -> tuple[str, str]:
    """'MMYYYY' → (first_iso, last_iso) of that calendar month.

    The lock asks `date BETWEEN period_start AND period_end`, so these are the
    two values that decide which entries a filed return freezes. Deliberately a
    duplicate of gst_return_service._period_bounds rather than an import: this
    module is imported by the router and importing the whole return engine to
    get a date pair would drag the ledger reader in with it.
    """
    if len(period) != 6 or not period.isdigit():
        raise ValueError("period must be MMYYYY")
    mm, yyyy = int(period[:2]), int(period[2:])
    if not 1 <= mm <= 12:
        raise ValueError("period month must be 01-12")
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def build_filings_row(
    *, firm_id: str, client_id: str, filing_type: str, period: str,
    filed_date: str, arn: Optional[str] = None,
    tax_payable_paise: Optional[int] = None, summary: Optional[dict] = None,
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
    start, end = period_bounds(period)
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
