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

from core.ist_clock import ist_now, ist_today
from domain.payroll import remittance_match
from domain.payroll.statutory import esi_contribution_period
from core.db_paging import fetch_all, fetch_all_in
from core.db_provider import privileged_for

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
        privileged_for(db).table("statutory_remittances").update(row).eq("id", same[0]["id"]).execute()
        row["id"] = same[0]["id"]
        return row

    inserted = (privileged_for(db).table("statutory_remittances").insert(row).execute().data) or []
    if inserted and inserted[0].get("id"):
        row["id"] = inserted[0]["id"]
    return row


def _read_states(db, client_id: str, scheme: str, wage_month: str) -> list[dict]:
    return (privileged_for(db).table("statutory_remittances").select("id, state")
            .eq("client_id", client_id).eq("scheme", scheme)
            .eq("wage_month", wage_month)
            .is_("deleted_at", "null").execute().data) or []


def read(db, *, firm_id: str, client_id: str,
         wage_month: Optional[str] = None) -> list[dict]:
    """Every live remittance for a client, newest wage month first."""
    q = (privileged_for(db).table("statutory_remittances")
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


def link_payment(db, *, firm_id: str, client_id: str, remittance_id: str,
                 journal_entry_id: str) -> bool:
    """Tie a remittance to the journal entry that paid it.

    A LINK, NOT A POSTING, and the distinction is load-bearing.
    the bank-posting service's `post` already writes Dr <liability> / Cr Bank
    when the CA passes the bank statement line, and it is the one path for money
    movement. Posting from here as well would debit the statutory liability
    twice — once from the bank line they passed, once from the challan they
    typed off the portal. `public.epfo_ecr_filings` carries no journal reference
    for the same reason.
    """
    # The entry must be an entry of THIS client: the link is what the reconciliation reads to say a liability was paid, and an
    # entry of another client of the firm would clear it. Read first, so a refusal changes nothing.
    # And it must still RECORD a payment (`remittance_match.entry_state`, the one rule the candidates and the TDS challan's door use): a draft
    # is not in the books, a reversed original no longer records anything, and the reversal is the entry that undid one. Tying a remittance
    # to one of those would clear the liability on the reconciliation for a payment the ledger does not show.
    # The select names the rule's columns as a literal (a built string is a column list the backend column check cannot read, and counts
    # against its budget); `test_the_entry_state_selects_name_the_rules_columns` holds the literal equal to remittance_match.ENTRY_STATE_COLUMNS.
    rows = (db.table("journal_entries").select("id, deleted_at, is_posted, is_reversed, reversal_of")
            .eq("id", journal_entry_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise RemittanceError("That journal entry is not an entry of this client.")
    state = remittance_match.entry_state(rows[0])
    if state != LIVE:
        raise RemittanceError(NOT_A_PAYMENT[state])
    res = (privileged_for(db).table("statutory_remittances")
           .update({"journal_entry_id": journal_entry_id})
           .eq("id", remittance_id).eq("firm_id", firm_id).eq("client_id", client_id)
           .is_("deleted_at", "null").execute().data)
    return bool(res)


# ── What a tied remittance says about the entry it points at ─────────────────────────────────────────────────────────────────────────────
#
# A remittance is tied to the entry that paid it by `journal_entry_id`. The column is cleared when an entry is hard-deleted, but a posted entry
# is never hard-deleted: it is REVERSED or soft-deleted, and the link then points at an entry that no longer records the payment while the
# reconciliation (`unlinked`) goes on treating the remittance as matched. The words are the server's, in the same five states and the same
# shape as the TDS challan's (`tds_challan_ledger_service`), with this register's own noun.
LIVE, DRAFT, REVERSED, REVERSAL, DELETED = (remittance_match.ENTRY_LIVE, remittance_match.ENTRY_DRAFT, remittance_match.ENTRY_REVERSED,
                                            remittance_match.ENTRY_REVERSAL, remittance_match.ENTRY_DELETED)
MISSING, UNKNOWN = "missing", "unknown"

LINK_LABEL = {
    LIVE: "Tied to an entry",
    REVERSED: "Tied to an entry that was reversed",
    DRAFT: "Tied to an entry that is still a draft",
    REVERSAL: "Tied to an entry that is itself a reversal",
    DELETED: "Tied to an entry that was deleted",
    MISSING: "Tied to an entry that can no longer be found",
    UNKNOWN: "Tied to an entry (not checked just now)",
}
LINK_NOTE = {
    REVERSED: "The ledger entry this remittance is tied to was reversed, so it no longer records the payment. The remittance stays: it was "
              "paid. Take the link back and tie it to the entry that now records the payment, if there is one.",
    DELETED: "The ledger entry this remittance is tied to was deleted, so it no longer records the payment. The remittance stays: it was "
             "paid. Take the link back and tie it to the entry that now records the payment, if there is one.",
    DRAFT: "The ledger entry this remittance is tied to is still a draft, so it is not in the books and does not yet record the payment. "
           "The remittance stays: it was paid. Post the entry, or take the link back and tie the remittance to the entry that records it.",
    REVERSAL: "The ledger entry this remittance is tied to is the entry that undid another one, so it does not record the payment. The "
              "remittance stays: it was paid. Take the link back and tie it to the entry that records the payment.",
    MISSING: "The ledger entry this remittance is tied to could not be found for this client. Take the link back and tie the remittance "
             "to the entry that records the payment, if there is one.",
    UNKNOWN: "The ledger could not be read just now, so whether the entry this remittance is tied to still records the payment is not known.",
}

#: Why an entry that is not LIVE cannot be tied, in words.
NOT_A_PAYMENT = {
    DELETED: "That journal entry was deleted, so it cannot be the payment of this remittance.",
    REVERSED: "That journal entry was reversed, so it no longer records a payment and cannot be the payment of this remittance.",
    REVERSAL: "That journal entry is the one that undid another entry, so it cannot be the payment of this remittance.",
    DRAFT: "That journal entry is still a draft, not yet in the books, so it cannot be the payment of this remittance.",
}

#: Entry ids asked for in one request (they ride in the URL).
_ENTRY_CHUNK = 100


def entry_states(db, *, firm_id: str, client_id: str, entry_ids: list) -> dict:
    """The state of each entry in `entry_ids` for this firm and client: LIVE, DRAFT, REVERSED, REVERSAL, DELETED (`remittance_match.entry_state`,
    the one rule the candidates and both link doors use), or MISSING (no such entry of this client, which includes an id that belongs to
    another client). Reads only; raises what the database raises. Shared with the TDS challan's link."""
    wanted = sorted({str(i) for i in entry_ids if i})
    found: dict = {}
    for at in range(0, len(wanted), _ENTRY_CHUNK):
        rows = (db.table("journal_entries").select("id, deleted_at, is_posted, is_reversed, reversal_of")
                .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", wanted[at:at + _ENTRY_CHUNK]).execute().data) or []
        found.update({str(r["id"]): r for r in rows})
    return {i: MISSING if found.get(i) is None else remittance_match.entry_state(found[i]) for i in wanted}


def link_view(state: str) -> dict:
    """`can_take_back` is the server's judgement that taking the link back is a sensible thing to offer: not when the ledger could not be read
    (UNKNOWN), because a failed read is no reason to undo a link. The screen shows the button on it and reads no state word."""
    return {"state": state, "label": LINK_LABEL[state], "note": LINK_NOTE.get(state), "can_take_back": state != UNKNOWN}


def stale_links(db, *, firm_id: str, client_id: str) -> list:
    """Remittances tied to an entry that no longer records the payment, each with `ledger_link` (`{state, label, note}`).

    A live link is not listed. When the ledger cannot be read every tied remittance is listed as UNKNOWN: a failed read is not a live link, and
    it is not a clean bill either. Nothing is changed by reading, and the link is never cleared on its own."""
    tied = [r for r in read(db, firm_id=firm_id, client_id=client_id) if r.get("journal_entry_id")]
    if not tied:
        return []
    try:
        states = entry_states(db, firm_id=firm_id, client_id=client_id, entry_ids=[r["journal_entry_id"] for r in tied])
    except Exception as exc:                                        # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="statutory_remittance_service.stale_links", firm_id=firm_id, client_id=client_id)
        states = {}
    out = []
    for r in tied:
        state = states.get(str(r["journal_entry_id"]), UNKNOWN)
        if state != LIVE:
            out.append({**r, "ledger_link": link_view(state)})
    return out


def unlink_payment(db, *, firm_id: str, client_id: str, remittance_id: str) -> Optional[str]:
    """Take back the link on a remittance. Returns the entry id it pointed at, or None when the remittance is not found, has no link, or was
    changed under the call (the update is guarded by the id it read, so two people taking it back act once)."""
    rows = (privileged_for(db).table("statutory_remittances").select("id, journal_entry_id")
            .eq("id", remittance_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .is_("deleted_at", "null").limit(1).execute().data) or []
    was = (rows[0].get("journal_entry_id") if rows else None)
    if not was:
        return None
    done = (privileged_for(db).table("statutory_remittances").update({"journal_entry_id": None})
            .eq("id", remittance_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("journal_entry_id", was).is_("deleted_at", "null").execute().data)
    return str(was) if done else None


def retract(db, *, firm_id: str, client_id: str, remittance_id: str,
            at_iso: Optional[str] = None) -> bool:
    """Soft-delete a remittance recorded in error.

    Never a hard delete: the challan number, the date and the amount that
    actually left the bank exist nowhere else, and a row that simply vanished
    would leave no trace that a liability had ever been reported settled.
    """
    res = (privileged_for(db).table("statutory_remittances")
           .update({"deleted_at": at_iso or ist_now().isoformat()})
           .eq("id", remittance_id).eq("firm_id", firm_id).eq("client_id", client_id)
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

    Nothing is linked here. The ranking and every sentence come from
    domain/payroll/remittance_match.py, which has the tests; the query is
    `entries_clearing_account`, which a TDS challan asks the same way.
    """
    paid_on = remittance.get("paid_on")
    if not paid_on:
        return []
    account_id = _liability_account_id(
        db, firm_id=firm_id, client_id=client_id,
        scheme=str(remittance.get("scheme") or ""))
    if not account_id:
        return []
    return entries_clearing_account(
        db, firm_id=firm_id, client_id=client_id, account_id=account_id,
        amount_paise=int(remittance.get("amount_paise") or 0), paid_on=str(paid_on),
        window_days=window_days)


def entries_clearing_account(db, *, firm_id: str, client_id: str, account_id: str,
                             amount_paise: int, paid_on: str,
                             window_days: int = remittance_match.DEFAULT_WINDOW_DAYS
                             ) -> list[dict]:
    """Journal entries inside a fortnight of `paid_on` that DEBIT `account_id`, ranked against `amount_paise`, best first.

    THE QUERY IS BOUNDED BY THE ANSWER, not by the ledger. It reads the entries
    inside the window, then their lines, a handful of rows for a monthly
    obligation, whatever the client's transaction volume. See CLAUDE.md's
    reporting rule; apps/api is in Singapore and Postgres is in Mumbai.

    Shared by the ESI / professional-tax remittance and the TDS challan
    (POST-A-272): each names its own liability account and its own figure, and
    the question asked of the ledger is the same.
    """
    try:
        centre = date.fromisoformat(str(paid_on)[:10])
    except (ValueError, TypeError):
        return []
    lo = (centre - timedelta(days=window_days)).isoformat()
    hi = (centre + timedelta(days=window_days)).isoformat()

    # Only an entry that can still BE the payment: not a draft, not a reversed original, not a reversal (`remittance_match.entry_state`).
    # Offering a reversed entry undid the recovery for a challan whose entry was reversed, which is to take the link back and tie it
    # again: the first candidate it was shown was the entry that had just been undone.
    # EVERY entry in the window, read in keyset pages: PostgREST answers at most a thousand rows to one request and says nothing when it cuts
    # a response short, so a busy client's month would have been offered only the first thousand entries, and a candidate list that silently
    # lacks the entry that paid the challan reads as "nothing paid it". `fetch_all` pages by `id`.
    entries = fetch_all(
        lambda: (db.table("journal_entries")
                 .select("id, entry_date, reference_no, narration, " + ", ".join(remittance_match.ENTRY_STATE_COLUMNS))
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("entry_date", lo).lte("entry_date", hi)
                 .is_("deleted_at", "null")),
        "id", label="statutory_remittance_service.entries_clearing_account.entries")
    entries = [e for e in entries if e.get("id") and remittance_match.entry_state(e) == remittance_match.ENTRY_LIVE]
    if not entries:
        return []

    # Which of those entries DEBIT the account: only the lines of this one account with a debit are read, however many entries the window
    # holds (the id list rides in chunks, `fetch_all_in`). Only then are the whole entries read, and only the shortlisted ones, because the
    # figure a challan matches is the entry's total.
    debit_lines = fetch_all_in(
        lambda: (db.table("journal_lines").select("id, journal_entry_id, debit_paise")
                 .eq("account_id", account_id).gt("debit_paise", 0)),
        "journal_entry_id", [e["id"] for e in entries], "id",
        label="statutory_remittance_service.entries_clearing_account.debits")
    debited: dict = {}
    for ln in debit_lines:
        eid = ln.get("journal_entry_id")
        debited[eid] = debited.get(eid, 0) + int(ln.get("debit_paise") or 0)
    entries = [e for e in entries if debited.get(e["id"], 0) > 0]
    if not entries:
        return []

    lines = fetch_all_in(
        lambda: db.table("journal_lines").select("id, journal_entry_id, credit_paise"),
        "journal_entry_id", [e["id"] for e in entries], "id",
        label="statutory_remittance_service.entries_clearing_account.totals")
    total: dict = {}
    for ln in lines:
        # The entry TOTAL is its credit side, which for a payment entry is what
        # left the bank — see domain/payroll/remittance_match.py for why that,
        # and not the liability debit, is the figure a challan matches.
        eid = ln.get("journal_entry_id")
        total[eid] = total.get(eid, 0) + int(ln.get("credit_paise") or 0)

    # `entries` holds only those that actually CLEARED this liability (narrowed above): an entry in the window that never touched the
    # account is not a candidate for paying it.
    shortlist = [
        {"journal_entry_id": e["id"], "entry_date": e.get("entry_date"),
         "reference_no": e.get("reference_no"), "narration": e.get("narration"),
         "liability_debit_paise": debited.get(e["id"], 0),
         "entry_total_paise": total.get(e["id"], 0)}
        for e in entries
    ]
    return [c.to_dict() for c in remittance_match.candidates(
        amount_paise=int(amount_paise or 0),
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
