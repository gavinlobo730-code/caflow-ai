"""Recording that an ESI or professional-tax remittance was made (migration 365).

WHAT THIS IS AND IS NOT

It is a RECORD of something a human did at a portal. It transmits nothing, and
it posts nothing to the general ledger — see `link_payment` for why that second
one is a deliberate refusal rather than an omission.

WHY IT REFUSES BEFORE IT WRITES

Migration 365 states every rule as a CHECK constraint, because the frontend
reaches ~83 tables directly over PostgREST where no `rbac()` runs. This module
checks the same rules first anyway, so a CA gets a sentence about ESIC or about
professional tax instead of a Postgres constraint name — the same reason
`models/common` wraps a database refusal. The constraint is the guarantee; this
is the explanation.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here reaches any portal.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from core.ist_clock import ist_today
from domain.payroll import remittance_match
from domain.payroll.statutory import esi_contribution_period

ESIC = "esic"
PROFESSIONAL_TAX = "professional_tax"
SCHEMES = (ESIC, PROFESSIONAL_TAX)

SUBMITTED = "submitted"
PAID = "paid"
STATUSES = (SUBMITTED, PAID)

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

class RemittanceError(ValueError):
    """A refusal with a sentence a CA can act on."""


def contribution_period_for(wage_month: str) -> str:
    """ESI's half-year for a wage month.

    DELEGATES rather than deriving. `domain/payroll/statutory.esi_contribution_period`
    already owns this rule — it is the same one ESI Rule 50's continuation
    depends on, where an employee whose wages cross the ceiling part way through
    a period stays in the scheme until that period ends. A second implementation
    here would be a second thing to get wrong about October-to-March spanning a
    calendar year boundary, and the two would drift.

    This adds only the shape check, because the domain function takes a month it
    can trust and slicing a malformed one would return a confident wrong label.
    """
    if not _MONTH.match(wage_month or ""):
        raise RemittanceError(
            f"{wage_month!r} is not a wage month. Use YYYY-MM — the month whose "
            f"liability is being settled, not the month you paid it in.")
    return esi_contribution_period(wage_month)


def _validate(scheme: str, wage_month: str, state: Optional[str],
              status: str, submitted_on: str, paid_on: Optional[str]) -> None:
    if scheme not in SCHEMES:
        raise RemittanceError(
            f"{scheme!r} is not a scheme this records. It is {ESIC} or "
            f"{PROFESSIONAL_TAX} — EPF has its own record (migration 335), with "
            f"a return-type sequence this table does not carry.")
    if not _MONTH.match(wage_month or ""):
        raise RemittanceError(
            f"{wage_month!r} is not a wage month. Use YYYY-MM — the month whose "
            f"liability is being settled, not the month you paid it in.")
    if status not in STATUSES:
        raise RemittanceError(
            f"{status!r} is not a state. A remittance is {SUBMITTED} when the "
            f"return is filed and {PAID} when the money has gone; ESIC separates "
            f"them, and month end is spent on the gap between.")
    if scheme == PROFESSIONAL_TAX and not (state or "").strip():
        raise RemittanceError(
            "Professional tax is levied by the STATE, so the remittance has to "
            "say which one. A client with staff in two states owes two "
            "authorities for the same month, on two due dates.")
    if scheme == ESIC and (state or "").strip():
        raise RemittanceError(
            "ESI is a central levy and carries no state. A state here is a row "
            "filled in from the professional-tax screen.")
    if paid_on and paid_on < submitted_on:
        raise RemittanceError("A remittance cannot be paid before it was filed.")


def record(
    db, *, firm_id: str, client_id: str, scheme: str, wage_month: str,
    state: Optional[str] = None, status: str = SUBMITTED,
    submitted_on: Optional[str] = None, paid_on: Optional[str] = None,
    challan_number: Optional[str] = None, challan_date: Optional[str] = None,
    amount_paise: int = 0, run_id: Optional[str] = None,
    notes: Optional[str] = None, recorded_by: Optional[str] = None,
) -> dict:
    """Write down a remittance the CA made at the portal.

    UPDATES IN PLACE on (client, scheme, month, state), because filing the
    return and then paying the challan are two entries about ONE remittance —
    and migration 365's partial unique index would reject the second anyway.
    Recording a correction is therefore the same call, not a different one.
    """
    submitted = submitted_on or ist_today().isoformat()
    state = (state or "").strip() or None
    _validate(scheme, wage_month, state, status, submitted, paid_on)

    if status == PAID and not paid_on:
        # The honest fallback for a CA recording both at once: ESIC generates
        # the challan right after the contribution is submitted, so one sitting
        # is the common case. Without this the CHECK refuses the row with
        # nothing useful to say.
        paid_on = submitted

    if int(amount_paise or 0) < 0:
        raise RemittanceError("A remittance is money that left the bank. "
                              "There is no negative one.")

    row: dict = {
        "firm_id": firm_id, "client_id": client_id, "scheme": scheme,
        "wage_month": wage_month, "status": status, "submitted_on": submitted,
        "amount_paise": int(amount_paise or 0),
    }
    if state:
        row["state"] = state
    if scheme == ESIC:
        row["contribution_period"] = contribution_period_for(wage_month)
    if paid_on:
        row["paid_on"] = paid_on
    for key, value in (("challan_number", challan_number),
                       ("challan_date", challan_date), ("run_id", run_id),
                       ("notes", notes), ("recorded_by", recorded_by)):
        if value:
            row[key] = str(value).strip() if isinstance(value, str) else value

    # The state is matched in PYTHON, not in the query: it is NULL for ESI, and
    # PostgREST's .eq() on a null never matches — the existing row would be
    # missed and the insert would then hit the unique index with a constraint
    # error instead of updating in place.
    same = [e for e in _read_states(db, client_id, scheme, wage_month)
            if (e.get("state") or None) == state]
    if same:
        db.table("statutory_remittances").update(row).eq("id", same[0]["id"]).execute()
        row["id"] = same[0]["id"]
        return row

    inserted = (db.table("statutory_remittances").insert(row).execute().data) or []
    if inserted and inserted[0].get("id"):
        row["id"] = inserted[0]["id"]
    return row


def _read_states(db, client_id: str, scheme: str, wage_month: str) -> list[dict]:
    return (db.table("statutory_remittances").select("id, state")
            .eq("client_id", client_id).eq("scheme", scheme)
            .eq("wage_month", wage_month)
            .is_("deleted_at", "null").execute().data) or []


def read(db, *, firm_id: str, client_id: str,
         wage_month: Optional[str] = None) -> list[dict]:
    """Every live remittance for a client, newest wage month first."""
    q = (db.table("statutory_remittances")
         .select("id, firm_id, client_id, scheme, run_id, wage_month, state, "
                 "contribution_period, challan_number, challan_date, "
                 "amount_paise, status, submitted_on, paid_on, "
                 "journal_entry_id, notes, recorded_by")
         .eq("firm_id", firm_id).eq("client_id", client_id)
         .is_("deleted_at", "null"))
    if wage_month:
        q = q.eq("wage_month", wage_month)
    rows = q.execute().data or []
    return sorted(rows, key=lambda r: (r.get("wage_month") or "",
                                       r.get("scheme") or "",
                                       r.get("state") or ""), reverse=True)


def unlinked(db, *, firm_id: str, client_id: str) -> list[dict]:
    """Remittances paid with no journal entry tied to them.

    THE QUESTION THIS ANSWERS, and it is the reason journal_entry_id exists.
    Without the link, a statutory liability that nobody has paid and one that
    was paid but never matched to its bank line look identical on the ledger —
    both sit uncleared. This separates them, so the CA chases the first and
    matches the second.
    """
    return [r for r in read(db, firm_id=firm_id, client_id=client_id)
            if r.get("status") == PAID and not r.get("journal_entry_id")]


def link_payment(db, *, firm_id: str, remittance_id: str,
                 journal_entry_id: str) -> bool:
    """Tie a remittance to the journal entry that paid it.

    A LINK, NOT A POSTING, and the distinction is load-bearing.
    `services/bank_posting_service.post` already writes Dr <liability> / Cr Bank
    when the CA passes the bank statement line, and it is the one path for money
    movement. Posting from here as well would debit the statutory liability
    twice — once from the bank line they passed, once from the challan they
    typed off the portal. `public.epfo_ecr_filings` carries no journal reference
    for the same reason.
    """
    res = (db.table("statutory_remittances")
           .update({"journal_entry_id": journal_entry_id})
           .eq("id", remittance_id).eq("firm_id", firm_id)
           .is_("deleted_at", "null").execute().data)
    return bool(res)


def retract(db, *, firm_id: str, remittance_id: str,
            at_iso: Optional[str] = None) -> bool:
    """Soft-delete a remittance recorded in error.

    Never a hard delete: the challan number, the date and the amount that
    actually left the bank exist nowhere else, and a row that simply vanished
    would leave no trace that a liability had ever been reported settled.
    """
    res = (db.table("statutory_remittances")
           .update({"deleted_at": at_iso or ist_today().isoformat()})
           .eq("id", remittance_id).eq("firm_id", firm_id)
           .is_("deleted_at", "null").execute().data)
    return bool(res)


# ── Which ledger each scheme settles, and how far to look ────────────────────
#
# The name patterns are the ones services/phase2_journal_service already posts
# the accrual to — %ESI Payable% and %PT Payable%. Named here rather than
# re-derived: a matcher looking at a different account from the one the accrual
# credited would find nothing and report every remittance as unmatched, which
# is a worse answer than no matcher at all.
#
# EPF is absent on purpose. It has its own record (migration 335) with EPFO's
# own sequencing, this table does not carry it, and `record` refuses it.
_LIABILITY_PATTERN = {
    ESIC: "%ESI Payable%",
    PROFESSIONAL_TAX: "%PT Payable%",
}


def _liability_account_id(db, *, firm_id: str, client_id: str,
                          scheme: str) -> Optional[str]:
    """The account a scheme's accrual was credited to, or None.

    None rather than a raise: a client whose chart has no ESI Payable has never
    accrued ESI, so there is nothing to reconcile and the caller reports "no
    candidates" rather than failing a screen.
    """
    pattern = _LIABILITY_PATTERN.get(scheme)
    if not pattern:
        return None
    rows = (db.table("chart_of_accounts").select("id, client_id, account_name")
            .eq("firm_id", firm_id).ilike("account_name", pattern)
            .eq("is_active", True).execute().data) or []
    # A firm-level account (client_id IS NULL) is allowed on any of that firm's
    # entries — see the journal_lines trigger in migration 360 — so it is a
    # legitimate match, but this client's OWN account wins where both exist.
    own = [r for r in rows if r.get("client_id") == client_id]
    return (own or rows)[0]["id"] if (own or rows) else None


def payment_candidates(db, *, firm_id: str, client_id: str,
                       remittance: dict,
                       window_days: int = remittance_match.DEFAULT_WINDOW_DAYS
                       ) -> list[dict]:
    """Journal entries that could have paid this remittance, best first.

    THE QUERY IS BOUNDED BY THE ANSWER, not by the ledger. It reads the lines
    on ONE account inside a fortnight, then the entries behind them — a handful
    of rows for a monthly obligation, whatever the client's transaction volume.
    See CLAUDE.md's reporting rule; apps/api is in Singapore and Postgres is in
    Mumbai.

    Nothing is linked here. The ranking and every sentence come from
    domain/payroll/remittance_match.py, which has the tests.
    """
    paid_on = remittance.get("paid_on")
    if not paid_on:
        return []
    account_id = _liability_account_id(
        db, firm_id=firm_id, client_id=client_id,
        scheme=str(remittance.get("scheme") or ""))
    if not account_id:
        return []

    try:
        centre = date.fromisoformat(str(paid_on)[:10])
    except (ValueError, TypeError):
        return []
    lo = (centre - timedelta(days=window_days)).isoformat()
    hi = (centre + timedelta(days=window_days)).isoformat()

    entries = (db.table("journal_entries")
               .select("id, entry_date, reference_no, narration")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .gte("entry_date", lo).lte("entry_date", hi)
               .is_("deleted_at", "null").execute().data) or []
    entries = [e for e in entries if e.get("id")]
    if not entries:
        return []

    lines = (db.table("journal_lines")
             .select("journal_entry_id, account_id, debit_paise, credit_paise")
             .in_("journal_entry_id", [e["id"] for e in entries])
             .execute().data) or []

    debited: dict = {}
    total: dict = {}
    for ln in lines:
        eid = ln.get("journal_entry_id")
        # The entry TOTAL is its credit side, which for a payment entry is what
        # left the bank — see domain/payroll/remittance_match.py for why that,
        # and not the liability debit, is the figure a challan matches.
        total[eid] = total.get(eid, 0) + int(ln.get("credit_paise") or 0)
        if ln.get("account_id") == account_id:
            debited[eid] = debited.get(eid, 0) + int(ln.get("debit_paise") or 0)

    # Only entries that actually CLEARED this liability. An entry in the window
    # that never touched the account is not a candidate for paying it.
    shortlist = [
        {"journal_entry_id": e["id"], "entry_date": e.get("entry_date"),
         "reference_no": e.get("reference_no"), "narration": e.get("narration"),
         "liability_debit_paise": debited.get(e["id"], 0),
         "entry_total_paise": total.get(e["id"], 0)}
        for e in entries if debited.get(e["id"], 0) > 0
    ]
    return [c.to_dict() for c in remittance_match.candidates(
        amount_paise=int(remittance.get("amount_paise") or 0),
        paid_on=str(paid_on)[:10], entries=shortlist, window_days=window_days)]


def unmatched_with_candidates(db, *, firm_id: str, client_id: str) -> list[dict]:
    """Every paid remittance with no entry tied to it, each with its candidates.

    The month-end list. `unlinked` alone says WHICH obligations are unmatched;
    this says what to match them to, which is the difference between a warning
    and a task somebody can finish.
    """
    return [
        {**r, "candidates": payment_candidates(
            db, firm_id=firm_id, client_id=client_id, remittance=r)}
        for r in unlinked(db, firm_id=firm_id, client_id=client_id)
    ]
