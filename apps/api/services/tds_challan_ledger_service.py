"""A recorded TDS challan is tied to the ledger entry that paid it (POST-A-272).

WHAT WAS WRONG
    `tds_challans` carried the challan's own facts and nothing that says whether the ledger knows the tax was paid. The product's one
    path for money leaving a bank is passing a statement line (the bank-posting service's `post` writes Dr <liability> / Cr Bank), so after
    the tax was deposited and the challan recorded, TDS Payable kept its whole credit until somebody passed a bank line to it by hand,
    nothing offered the entry whose amount equals a recorded challan, and nothing said a challan had no entry behind it. A liability
    nobody has paid and one that was paid and never tied back look identical on the ledger. ESI and professional tax answered this in
    migration 365 (`statutory_remittances.journal_entry_id`); this gives the TDS register the same.

WHAT THIS DOES
    A LINK, NEVER A POSTING. Posting from the challan as well as from the bank line would debit TDS Payable twice, which is the note
    in `statutory_remittance_service.link_payment`. So this only offers the entries that could be the payment (`payment_candidates`,
    the same ranking the remittances use, with a reason sentence and never a score), ties one to the challan (`link_payment`) and
    takes it back (`unlink_payment`). Nothing is linked automatically.

    A link is refused in words unless: the challan has none already; the entry is a live entry of THIS client (posted, not deleted, not
    reversed, not itself a reversal: `remittance_match.entry_state`); the entry debits the
    TDS Payable account the challan's section belongs to (a salary challan clears "TDS Payable - Salary", every other section clears
    "TDS Payable": two distinct accounts, and a substring lookup of one finds the other); and no other challan of the client is tied to
    the same entry (one bank debit cannot be the payment of two challans). The update names "no link yet" as its condition, so two
    people linking at the same moment tie it once and the second is told.

ONE ENTRY PAYS ONE CHALLAN IN THE DATABASE, NOT ONLY IN THIS READ. The "no other challan holds it" check below is a read followed by a write, so
    two requests tying two challans to one entry at the same moment both read "free" (the review of migration 568 found it). Migration 573
    makes it a partial unique index on the column, and a write that loses to it is answered with the same sentence and status as the read:
    the index decides and the read only names the other challan. The same migration refuses, in the database, an entry of another client.

A LINK OR ITS REMOVAL IS RECORDED BEFORE IT IS MADE, OR NOT MADE. Both write the audit log first, as the person (the AUTH id, the audit log's
    flavour of actor), and refuse in words with a 503 and "Nothing changed" when the log cannot be written: `audit_service.log_event` swallows
    its failures, and a link the ledger reads as "the tax was paid" with no account of who said so is the thing the log is for. The entry says
    what was ASKED; a write that then loses a race is refused afterwards and a second entry says it was not applied (`link_payment_not_applied`),
    and one that raises leaves a second entry saying it failed with the SQLSTATE (`link_payment_failed`; not "not applied", because after a
    timeout nobody knows), so the log is a true account of every outcome (the shape `bf_loss_service` uses for a hand correction).

A LINK CAN GO STALE, AND THE SCREEN SAYS SO. `journal_entry_id` is cleared when the entry is hard-deleted (ON DELETE SET NULL), but a
    posted entry is not hard-deleted: it is REVERSED (a reversal entry is appended and the original is flagged) or soft-deleted. The
    link then still points at an entry that no longer records the payment, and "Tied to an entry" would be a false statement about the
    ledger. `ledger_link` reads the entry's state for each tied challan (live, reversed, deleted, or no longer found) and carries the
    server's own words; the link is never cleared by this, because whether the challan should be tied to a different entry or to none
    is the CA's decision (Take the link back, then tie it again).

WHAT IT DOES NOT DO
    It does not re-check that a LIVE tied entry still debits the TDS Payable account (a manual journal can be edited in place after the
    link), and it does not propose from the bank queue, and it does not raise an exception for a challan with no entry after some days: both
    stay on the ledger line (POST-A-272). It does not backfill: which entry paid which challan is the CA's answer.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this edits the practice's own register. It transmits nothing.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional

from core.db_provider import privileged_for
from domain.payroll import remittance_match
from domain.tds import deposit_due
from services import statutory_remittance_service as remittances

_logger = logging.getLogger("caflow.tds.challan_ledger")

#: The two real accounts the chart holds. Exact names, never a pattern: "TDS Payable - Salary" contains "TDS Payable".
SALARY_ACCOUNT = "TDS Payable - Salary"
OTHER_ACCOUNT = "TDS Payable"


#: The state of the entry a tied challan points at, and what the screen says about it. The words are the server's.
LIVE, DRAFT, REVERSED, REVERSAL, DELETED = (remittance_match.ENTRY_LIVE, remittance_match.ENTRY_DRAFT, remittance_match.ENTRY_REVERSED,
                                            remittance_match.ENTRY_REVERSAL, remittance_match.ENTRY_DELETED)
MISSING, UNKNOWN = remittances.MISSING, remittances.UNKNOWN

_LABEL = {
    LIVE: "Tied to an entry",
    REVERSED: "Tied to an entry that was reversed",
    DRAFT: "Tied to an entry that is still a draft",
    REVERSAL: "Tied to an entry that is itself a reversal",
    DELETED: "Tied to an entry that was deleted",
    MISSING: "Tied to an entry that can no longer be found",
    UNKNOWN: "Tied to an entry (not checked just now)",
}
_NOTE = {
    REVERSED: "The ledger entry this challan is tied to was reversed, so it no longer records the payment. The challan stays: the tax was "
              "deposited. Take the link back and tie the challan to the entry that now records the payment, if there is one.",
    DELETED: "The ledger entry this challan is tied to was deleted, so it no longer records the payment. The challan stays: the tax was "
             "deposited. Take the link back and tie the challan to the entry that now records the payment, if there is one.",
    DRAFT: "The ledger entry this challan is tied to is still a draft, so it is not in the books and does not yet record the payment. The "
           "challan stays: the tax was deposited. Post the entry, or take the link back and tie the challan to the entry that records it.",
    REVERSAL: "The ledger entry this challan is tied to is the entry that undid another one, so it does not record the payment. The "
              "challan stays: the tax was deposited. Take the link back and tie the challan to the entry that records the payment.",
    MISSING: "The ledger entry this challan is tied to could not be found for this client. Take the link back and tie the challan to the "
             "entry that records the payment, if there is one.",
    UNKNOWN: "The ledger could not be read just now, so whether the entry this challan is tied to still records the payment is not known.",
}

class LinkRefused(Exception):
    """A link or unlink that must not go ahead, with the sentence to show. `status` is the HTTP status the route answers."""

    def __init__(self, sentence: str, status: int = 422):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def _link(state: str) -> dict:
    return {"state": state, "label": _LABEL[state], "note": _NOTE.get(state)}


def entry_states(db, *, firm_id: str, client_id: str, entry_ids: list[str]) -> dict[str, str]:
    """The state of each entry in `entry_ids` for this firm and client: LIVE, DRAFT, REVERSED, REVERSAL, DELETED, or MISSING (no such
    entry of this client, which includes an id that belongs to another client). One reader for both registers: the ESI / professional-tax
    remittance's link asks the same function (`statutory_remittance_service.entry_states`). Reads only; raises what the database raises."""
    return remittances.entry_states(db, firm_id=firm_id, client_id=client_id, entry_ids=entry_ids)


def annotate_links(db, *, firm_id: str, client_id: str, rows: list[dict]) -> None:
    """Put `ledger_link` (`{state, label, note}`) on each challan in `rows` that is tied to an entry; an untied challan gets none. A
    failure to read the ledger is reported and every tied challan is marked UNKNOWN: a failed read is not a live link."""
    tied = [r for r in rows if r.get("journal_entry_id")]
    if not tied:
        return
    try:
        states = entry_states(db, firm_id=firm_id, client_id=client_id, entry_ids=[r["journal_entry_id"] for r in tied])
    except Exception as exc:                                    # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds_challan_ledger_service.annotate_links", firm_id=firm_id, client_id=client_id)
        states = {}
    for r in tied:
        r["ledger_link"] = _link(states.get(str(r["journal_entry_id"]), UNKNOWN))


def account_name_for(section: Optional[str]) -> str:
    """Which TDS Payable account a challan of this section is paid out of."""
    return SALARY_ACCOUNT if deposit_due.is_salary(str(section or "")) else OTHER_ACCOUNT


def liability_account_id(db, *, firm_id: str, client_id: str, section: Optional[str]) -> Optional[str]:
    """The id of the account a challan of `section` clears, or None when the client's chart has none (a client that never accrued TDS).

    A firm-level account (client_id IS NULL) is allowed on any of that firm's entries (migration 360); this client's own account wins
    where both exist."""
    rows = (db.table("chart_of_accounts").select("id, client_id")
            .eq("firm_id", firm_id).eq("account_name", account_name_for(section))
            .eq("is_active", True).execute().data) or []
    own = [r for r in rows if r.get("client_id") == client_id]
    shared = [r for r in rows if not r.get("client_id")]
    pick = (own or shared)
    return pick[0]["id"] if pick else None


def payment_candidates(db, *, firm_id: str, client_id: str, challan: dict,
                       window_days: int = remittance_match.DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    """The entries that could have paid this challan, best first, and what was asked. Reads only."""
    account = account_name_for(challan.get("section"))
    paid_on = str(challan.get("payment_date") or "")[:10]
    base = {"challan_id": challan.get("id"), "account_name": account, "window_days": window_days,
            "journal_entry_id": challan.get("journal_entry_id"), "ledger_link": None}
    if challan.get("journal_entry_id"):
        tied = {**challan}
        annotate_links(db, firm_id=firm_id, client_id=client_id, rows=[tied])
        base["ledger_link"] = tied.get("ledger_link")
    if not paid_on:
        return {**base, "candidates": [], "gap": "The challan has no payment date, so there is no window to look in."}
    account_id = liability_account_id(db, firm_id=firm_id, client_id=client_id, section=challan.get("section"))
    if not account_id:
        return {**base, "candidates": [],
                "gap": f"This client's chart of accounts has no \"{account}\" account, so no entry can have cleared it."}
    found = remittances.entries_clearing_account(
        db, firm_id=firm_id, client_id=client_id, account_id=account_id,
        amount_paise=int(challan.get("total_paise") or 0), paid_on=paid_on, window_days=window_days)
    return {**base, "candidates": found, "gap": None}


def _entry(db, *, firm_id: str, client_id: str, journal_entry_id: str) -> Optional[dict]:
    """The entry for this firm and client, deleted or not, with the columns `entry_state` reads; None when it is not this client's."""
    rows = (db.table("journal_entries").select("id, entry_date, reference_no, deleted_at, " + ", ".join(remittance_match.ENTRY_STATE_COLUMNS))
            .eq("id", journal_entry_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    return rows[0] if rows else None


#: Why an entry that is not LIVE cannot be tied, in words.
_NOT_A_PAYMENT = {
    DELETED: "That journal entry was deleted, so it cannot be the payment of this challan.",
    REVERSED: "That journal entry was reversed, so it no longer records a payment and cannot be the payment of this challan.",
    REVERSAL: "That journal entry is the one that undid another entry, so it cannot be the payment of this challan.",
    DRAFT: "That journal entry is still a draft, not yet in the books, so it cannot be the payment of this challan.",
}


#: A SQLSTATE is five characters from 0-9 and A-Z.
_SQLSTATE_SHAPE = re.compile(r"^[0-9A-Z]{5}$")


def _sqlstate(exc: Exception) -> Optional[str]:
    """The five-character SQLSTATE the driver kept on `exc` (its `code`, or the `code` of the dict PostgREST puts in `args`), or None."""
    for got in (getattr(exc, "code", None), (getattr(exc, "args", None) or [None])[0]):
        if isinstance(got, dict):
            got = got.get("code")
        if isinstance(got, str) and _SQLSTATE_SHAPE.match(got.strip()):
            return got.strip()
    return None


def _is_unique_violation(exc: Exception) -> bool:
    """True when `exc` is Postgres's unique-violation (23505).

    THE STATE IS READ, NOT SEARCHED FOR. A substring match for "23505" over the whole message also matches a foreign-key violation whose key
    text happens to hold those digits (a uuid can). Only an error that carries no state at all falls back to the words Postgres uses."""
    state = _sqlstate(exc)
    if state is not None:
        return state == "23505"
    return "duplicate key value violates unique constraint" in str(exc).lower()


def _write_audit_or_refuse(*, firm_id: str, client_id: str, challan: dict, action: str, old: Mapping[str, Any], new: Mapping[str, Any],
                           actor: Mapping[str, Any]) -> None:
    """Keep what was asked in the audit log, or refuse. Not `audit_service.log_event`, which swallows its failures."""
    from core.supabase_client import get_service_supabase
    try:
        get_service_supabase().table("audit_log").insert({
            "firm_id": firm_id,
            "actor_id": actor.get("auth_user_id"),          # the AUTH id: that is the audit log's flavour of actor
            "actor_email": actor.get("email"),
            "entity_type": "tds_challan",
            "entity_id": challan.get("id"),
            "action": action,
            "old_data": dict(old),
            "new_data": dict(new),
            "metadata": {"client_id": client_id, "challan_no": challan.get("challan_no")},
        }).execute()
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation=f"tds_challan_ledger_service.{action}_audit", firm_id=firm_id, client_id=client_id)
        raise LinkRefused("The challan's link was not changed, because the audit log could not be written just now and the audit log is the "
                          "only account of who tied or untied it. Nothing changed; try again in a moment.", 503) from exc


def _say_in_log(*, firm_id: str, client_id: str, challan: dict, action: str, actor: Mapping[str, Any],
                detail: Optional[Mapping[str, Any]] = None) -> None:
    """Add a second entry to the audit log saying what became of the request an earlier entry recorded. Non-fatal by design: the person is
    already being told, and this entry only keeps the log true."""
    from services.audit_service import log_event
    log_event(firm_id=firm_id, entity_type="tds_challan", entity_id=str(challan.get("id")), action=action,
              actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
              new_data=dict(detail) if detail else None,
              metadata={"client_id": client_id, "challan_no": challan.get("challan_no")})


def _say_not_applied(*, firm_id: str, client_id: str, challan: dict, action: str, actor: Mapping[str, Any]) -> None:
    """The write that followed an audit entry matched nothing (another request got there first): `<action>_not_applied`."""
    _say_in_log(firm_id=firm_id, client_id=client_id, challan=challan, action=f"{action}_not_applied", actor=actor)


def _say_failed(*, firm_id: str, client_id: str, challan: dict, action: str, actor: Mapping[str, Any], exc: Exception) -> None:
    """The write that followed an audit entry RAISED: `<action>_failed`, with the SQLSTATE if the driver kept one. This is deliberately not
    "not applied": a timeout or a dropped connection leaves it unknown whether the database did the work, and the log must not claim more
    than is known. The row-level edit log (migration 111) records what the table really did."""
    _say_in_log(firm_id=firm_id, client_id=client_id, challan=challan, action=f"{action}_failed", actor=actor,
                detail={"sqlstate": _sqlstate(exc), "error": type(exc).__name__})


def link_payment(db, *, firm_id: str, client_id: str, challan: dict, journal_entry_id: str, actor: Mapping[str, Any]) -> dict:
    """Tie `challan` (already read for this firm and client) to the entry that paid it, as `actor`. Returns the challan's id and the entry.
    Raises `LinkRefused`."""
    if challan.get("journal_entry_id"):
        raise LinkRefused("This challan is already tied to a ledger entry. Take that link back first if it is the wrong one.", 409)
    entry = _entry(db, firm_id=firm_id, client_id=client_id, journal_entry_id=journal_entry_id)
    if not entry:
        raise LinkRefused("That journal entry is not an entry of this client.")
    state = remittance_match.entry_state(entry)
    if state != LIVE:
        raise LinkRefused(_NOT_A_PAYMENT[state])
    account = account_name_for(challan.get("section"))
    account_id = liability_account_id(db, firm_id=firm_id, client_id=client_id, section=challan.get("section"))
    if not account_id:
        raise LinkRefused(f"This client's chart of accounts has no \"{account}\" account, so no entry can have cleared it.")
    debits = (db.table("journal_lines").select("debit_paise")
              .eq("journal_entry_id", journal_entry_id).eq("account_id", account_id).execute().data) or []
    if not any(int(d.get("debit_paise") or 0) > 0 for d in debits):
        raise LinkRefused(f"That entry does not debit \"{account}\", so it cannot be the payment of this challan.")
    taken = (db.table("tds_challans").select("id, challan_no")
             .eq("firm_id", firm_id).eq("client_id", client_id).eq("journal_entry_id", journal_entry_id)
             .neq("id", challan["id"]).limit(1).execute().data) or []
    if taken:
        raise LinkRefused("That entry is already tied to another challan"
                          + (f" ({taken[0].get('challan_no')})" if taken[0].get("challan_no") else "")
                          + ". One payment entry cannot be the payment of two challans.", 409)
    _write_audit_or_refuse(firm_id=firm_id, client_id=client_id, challan=challan, action="link_payment", actor=actor,
                           old={"journal_entry_id": None}, new={"journal_entry_id": journal_entry_id})
    try:
        done = (privileged_for(db).table("tds_challans").update({"journal_entry_id": journal_entry_id})
                .eq("id", challan["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("journal_entry_id", "null").execute().data)
    except Exception as exc:                                # noqa: BLE001
        if not _is_unique_violation(exc):
            _say_failed(firm_id=firm_id, client_id=client_id, challan=challan, action="link_payment", actor=actor, exc=exc)
            raise
        # Another request tied this entry to another challan between the read above and this write: the unique index (migration 573) decides.
        _say_not_applied(firm_id=firm_id, client_id=client_id, challan=challan, action="link_payment", actor=actor)
        raise LinkRefused("That entry was tied to another challan just now. One payment entry cannot be the payment of two challans.", 409) from exc
    if not done:
        _say_not_applied(firm_id=firm_id, client_id=client_id, challan=challan, action="link_payment", actor=actor)
        raise LinkRefused("This challan was tied to an entry just now by somebody else, or is no longer in the register.", 409)
    return {"challan_id": challan["id"], "journal_entry_id": journal_entry_id,
            "entry_date": entry.get("entry_date"), "reference_no": entry.get("reference_no")}


def unlink_payment(db, *, firm_id: str, client_id: str, challan: dict, actor: Mapping[str, Any]) -> dict:
    """Take back the link on `challan`, as `actor`. Raises `LinkRefused` when there is none."""
    was = challan.get("journal_entry_id")
    if not was:
        raise LinkRefused("This challan is not tied to a ledger entry.", 409)
    _write_audit_or_refuse(firm_id=firm_id, client_id=client_id, challan=challan, action="unlink_payment", actor=actor,
                           old={"journal_entry_id": was}, new={"journal_entry_id": None})
    try:
        done = (privileged_for(db).table("tds_challans").update({"journal_entry_id": None})
                .eq("id", challan["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("journal_entry_id", was).execute().data)
    except Exception as exc:                                # noqa: BLE001
        _say_failed(firm_id=firm_id, client_id=client_id, challan=challan, action="unlink_payment", actor=actor, exc=exc)
        raise
    if not done:
        _say_not_applied(firm_id=firm_id, client_id=client_id, challan=challan, action="unlink_payment", actor=actor)
        raise LinkRefused("This challan's link was changed just now by somebody else. Reload it.", 409)
    return {"challan_id": challan["id"], "journal_entry_id": None, "was": was}
