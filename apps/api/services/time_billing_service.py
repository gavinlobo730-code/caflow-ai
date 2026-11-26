"""Hourly billing: a client's unbilled time becomes ONE draft sales invoice in the practice's own books (POST-B-194).

WHAT IT IS FOR
    Time recorded as billable is priced when it is recorded (migration 451) and totalled on the Unbilled Work panel, and
    until now nothing turned it into an invoice or marked it billed, so the figure only grew. The owner decided on
    21-11-2026 to build time billing. A Partner picks a client's unbilled entries; this module makes a DRAFT invoice for
    them on the sales engine, in the practice's own books (the firm's internal client), and marks each entry with the
    invoice that bills it.

IT REUSES THE SALES ENGINE AND WRITES NO INVOICE OF ITS OWN
    The draft is made by the function a billing schedule's draft is made by (`routers.sales_invoices.create_invoice`), for
    the customer that stands for the client in the practice's books (`billing_service.ensure_customer_link`, guardrail
    G3), under SAC 998211. So the tax, the place of supply, the draft's placeholder number, the journal on issue and the
    GSTR-1 line are the sales engine's, and a time invoice is an ordinary invoice of the practice. It stays a DRAFT: a
    Partner reviews it, gives it its number and issues it. Nothing is issued or sent from here.

AN HOUR IS WORTH WHAT THE ONE RULE SAYS, AND THE INVOICE ADDS UP TO THE ENTRIES
    Each entry's worth is `domain.billing.time_rate.entry_worth`, the rule the Time screen, the export, the Unbilled Work
    panel and realization all price an hour by: minutes times the rate stored on the entry, floored to the paisa per
    entry. A line is therefore the SUM of its entries' worths, carried as a quantity of one at that amount, with the hours
    said in the line's words. A line written as hours times a rate would not add up to the entries: a quantity holds three
    decimals, so fifty minutes is 0.833 of an hour and bills fifty paise short at Rs 1,500 an hour, and two entries at
    different rates have no one rate at all. The figure a Partner saw as unbilled is the figure the draft bills.

WHAT IS REFUSED, IN WORDS
    An entry that is not this client's, is not billable, is still running, has no time on it, has no rate, or is already
    billed. Nothing is skipped silently: a request that names one such entry changes nothing and says which rule it met.

MARKING IS A CLAIM, AND A LOST RACE LEAVES NOTHING BEHIND
    The draft is created first (an entry's mark is a foreign key to it), then the entries are marked in ONE statement that
    takes only entries still unbilled. If that statement took fewer than were asked for, somebody billed one of them in
    the meantime: the draft is deleted, which releases whatever was taken (the key is ON DELETE SET NULL, migration 078),
    and the request is refused. So two people billing the same hour cannot both succeed, and a failure cannot leave an
    entry marked against an invoice that does not bill it.

RELEASE
    Deleting the draft releases its entries (the database does it, by that same key). Cancelling an ISSUED time invoice
    releases them too (`release_for_invoice`, called by the cancel route): a cancelled invoice bills nothing, so the time
    is unbilled again and is offered for the next one.

NO RATE OF GST IS ASSUMED HERE, AND THE SERVICE IS THE PRACTICE'S OWN
    The rate is the caller's, stated on the request, as a billing schedule's is stated on the schedule. This module holds
    no default. The service each line names is one of the practice's own catalogue, chosen on the request, as a schedule's
    is; the screen offers the rate recorded against that service as a starting figure and the Partner may change it.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core import db_provider
from core.db_paging import fetch_all, fetch_all_in
from core.db_provider import privileged_for
from core.ist_clock import ist_date_of, ist_today
from domain.billing import time_rate
from domain.money_sentence import rupee_text
from models.invoices import SalesInvoiceIn, SalesInvoiceLineIn
from services import billing_service, named_row_ownership
from services.audit_service import log_event
from services.internal_client_service import get_internal_client_id
from services.numbering import draft_placeholder_invoice_no

_logger = logging.getLogger("caflow.time_billing")

_db = db_provider.request_db

#: How a draft's lines are made from the chosen entries.
GROUPINGS = ("single", "by_task", "by_person", "by_entry")
#: The most lines one draft may carry. More than this is a request for a coarser grouping, said in words.
MAX_LINES = 100
#: The most entries one draft may bill.
MAX_ENTRIES = 2000

def _entries_of(db, firm_id: str, client_id: str):
    """One client's time entries of the firm, with the columns this module reads. ONE place builds the read, and the column list is
    written in it and not held in a name: the check that every column the server names exists reads a literal and cannot read a
    variable (two reads through a shared name were two references it could not see)."""
    return (db.table("time_entries")
            .select("id, firm_id, client_id, user_id, task_id, description, started_at, ended_at, duration_minutes, "
                    "is_billable, billable_rate_paise, hourly_rate_paise, billed_invoice_id")
            .eq("firm_id", firm_id).eq("client_id", client_id))


def _hours_text(minutes: int) -> str:
    hours, rest = divmod(max(int(minutes), 0), 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    return f"{hours} h" if hours else f"{rest} min"


def _task_titles(db, firm_id: str, ids: set) -> dict:
    """{task id: title} for the firm's tasks among `ids`. The table is named here and not handed in, so the check that every query on
    a firm table carries its firm can read this one."""
    wanted = sorted({str(i) for i in ids if i})
    if not wanted:
        return {}
    rows = fetch_all_in(lambda: privileged_for(db).table("tasks").select("id, title").eq("firm_id", firm_id), "id", wanted,
                        label="time_billing.task_titles")
    return {str(r["id"]): r.get("title") for r in rows}


def _described(db, firm_id: str, entries: list[dict]) -> list[dict]:
    """The entries as the screen and the lines need them: priced by the one rule, with the names beside the ids."""
    people = billing_service._staff_names(firm_id, {e.get("user_id") for e in entries})
    tasks = _task_titles(db, firm_id, {e.get("task_id") for e in entries})
    out = []
    for e in entries:
        worth = time_rate.entry_worth(e)
        day = ist_date_of(e.get("started_at"))
        out.append({
            "id": e.get("id"), "day": day.isoformat() if day else None,
            "user_id": e.get("user_id"), "user_name": people.get(str(e.get("user_id"))),
            "task_id": e.get("task_id"), "task_title": tasks.get(str(e.get("task_id"))) if e.get("task_id") else None,
            "description": e.get("description"),
            "minutes": int(e.get("duration_minutes") or 0),
            "rate_paise": worth["rate_paise"], "value_paise": worth["value_paise"],
            # Why this entry cannot be billed yet, or None when it can. The screen shows it and offers no tick for it.
            "blocked": _why_not(e),
        })
    return out


def _why_not(entry: dict) -> Optional[str]:
    """The one reason an entry cannot go on an invoice, in words, or None. The order is the order a person would fix them in."""
    if entry.get("billed_invoice_id"):
        return "It is already on an invoice."
    if not entry.get("is_billable"):
        return "It is recorded as not billable."
    if not entry.get("ended_at"):
        return "Its timer is still running. Stop it first."
    if int(entry.get("duration_minutes") or 0) <= 0:
        return "It has no time recorded on it."
    if time_rate.entry_worth(entry)["value_paise"] is None:
        return "It has no rate. Set its rate first."
    return None


def unbilled_entries(firm_id: str, client_id: str) -> dict:
    """One client's unbilled billable time, entry by entry, oldest first: what a Partner chooses from."""
    db = _db()
    rows = fetch_all(
        lambda: (_entries_of(db, firm_id, client_id)
                 .eq("is_billable", True).is_("billed_invoice_id", "null").gt("duration_minutes", 0)),
        label="time_billing.unbilled_entries")
    rows.sort(key=lambda e: (str(e.get("started_at") or ""), str(e.get("id"))))
    entries = _described(db, firm_id, rows)
    billable = [e for e in entries if e["blocked"] is None]
    return {
        "client_id": client_id, "entries": entries,
        "billable_count": len(billable),
        "billable_minutes": sum(e["minutes"] for e in billable),
        "billable_value_paise": sum(e["value_paise"] for e in billable),
        "groupings": list(GROUPINGS), "max_lines": MAX_LINES,
    }


def _chosen(db, firm_id: str, client_id: str, entry_ids: list[str]) -> list[dict]:
    """The entries a request names, read for this firm and this client, each one billable now. Raises in words otherwise."""
    ids = [str(i) for i in entry_ids if isinstance(i, str) and i.strip()]
    if not ids or len(ids) != len(entry_ids):
        raise HTTPException(422, "Choose at least one time entry to bill.")
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "A time entry is named twice. Choose each entry once.")
    if len(ids) > MAX_ENTRIES:
        raise HTTPException(422, f"One invoice can bill at most {MAX_ENTRIES} time entries. Bill the rest on another.")
    rows = fetch_all_in(lambda: _entries_of(db, firm_id, client_id), "id", ids, label="time_billing.chosen")
    found = {str(r["id"]): r for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        # The same words whether the entry does not exist or is another client's: neither is confirmed.
        raise HTTPException(404, f"{len(missing)} of the chosen time entries could not be found for this client. "
                                 "Reload the list and choose again.")
    blocked = [(found[i], _why_not(found[i])) for i in ids if _why_not(found[i])]
    if blocked:
        first = blocked[0][1]
        more = f" ({len(blocked) - 1} more of the chosen entries cannot be billed either.)" if len(blocked) > 1 else ""
        raise HTTPException(409, f"One of the chosen time entries cannot be billed: {first}{more} Reload the list and choose again.")
    return [found[i] for i in ids]


def _lines(entries: list[dict], group_by: str) -> list[dict]:
    """The draft's lines: each the sum of its entries' worths, with the hours in its words. Order is the order of the
    first entry of each line, so the same request always makes the same draft."""
    if group_by not in GROUPINGS:
        raise HTTPException(422, "Choose how the time is to be shown on the invoice: one line, by task, by person or by entry.")

    def key_of(e: dict):
        if group_by == "single":
            return "all"
        if group_by == "by_task":
            return ("task", e.get("task_id") or "")
        if group_by == "by_person":
            return ("person", e.get("user_id") or "")
        return ("entry", e["id"])

    groups: dict = {}
    for e in entries:
        slot = groups.setdefault(key_of(e), {"entries": [], "minutes": 0, "value_paise": 0})
        slot["entries"].append(e)
        slot["minutes"] += e["minutes"]
        slot["value_paise"] += e["value_paise"]
    if len(groups) > MAX_LINES:
        raise HTTPException(422, f"That would make {len(groups)} lines, and an invoice of time carries at most {MAX_LINES}. "
                                 "Choose a coarser grouping (by task, by person or one line).")
    days = sorted(e["day"] for e in entries if e["day"])
    span = "" if not days else (f", {days[0]}" if days[0] == days[-1] else f", {days[0]} to {days[-1]}")
    out = []
    for slot in groups.values():
        first = slot["entries"][0]
        hours = _hours_text(slot["minutes"])
        if group_by == "single":
            words = f"Professional fees for time: {hours}{span}"
        elif group_by == "by_task":
            words = f"{first.get('task_title') or 'Work not recorded against a task'}: {hours}"
        elif group_by == "by_person":
            words = f"Time of {first.get('user_name') or 'a member of staff'}: {hours}"
        else:
            said = " ".join(str(first.get("description") or "").split())[:120]
            words = f"{first.get('day') or ''} {said or first.get('task_title') or 'Time'}: {hours}".strip()
            if first.get("rate_paise") is not None:
                # "Rs" and not the rupee sign: a line's words are printed on the invoice's PDF, whose fonts have no glyph for it.
                words += f" at {rupee_text(first['rate_paise'], unit='Rs ')} an hour"
        out.append({"description": words, "minutes": slot["minutes"], "value_paise": slot["value_paise"],
                    "entry_ids": [e["id"] for e in slot["entries"]]})
    return out


def preview(firm_id: str, client_id: str, entry_ids: list[str], group_by: str) -> dict:
    """The lines a draft would carry and what they add up to, before tax. Nothing is written."""
    db = _db()
    entries = _described(db, firm_id, _chosen(db, firm_id, client_id, entry_ids))
    lines = _lines(entries, group_by)
    return {"lines": [{k: line[k] for k in ("description", "minutes", "value_paise")} for line in lines],
            "entries": len(entries), "minutes": sum(e["minutes"] for e in entries),
            "value_paise": sum(line["value_paise"] for line in lines)}


def create_draft(firm_id: str, client_id: str, entry_ids: list[str], group_by: str, service_id: str,
                 gst_rate_percent: float, current_user: dict) -> dict:
    """Make ONE draft sales invoice in the practice's own books for the chosen entries, and mark them billed by it.

    `service_id` is one of the PRACTICE'S OWN services (its catalogue is the internal client's; `GET
    /api/billing/service-options` lists it), as a billing schedule names one: every line of a sales document names a
    product or service of the document's own client, and the sales engine refuses one that is not."""
    if not isinstance(service_id, str) or not service_id.strip():
        raise HTTPException(422, "Choose which of the practice's services this time is billed as.")
    internal_id = get_internal_client_id(firm_id)
    if not internal_id:
        raise HTTPException(409, "Set up My practice (the firm's own books) before billing time.")
    if str(client_id) == str(internal_id):
        raise HTTPException(422, "Time recorded against the practice itself is the firm's own and is not billed to anybody.")
    db = _db()
    # Whose the named service is, asked before anything is written (the customer link below is a write): a service of another
    # client, or of another firm, is "not found", in the words a missing one gets.
    named_row_ownership.service_is_the_practices(db, firm_id, service_id)
    entries = _described(db, firm_id, _chosen(db, firm_id, client_id, entry_ids))
    lines = _lines(entries, group_by)
    customer_id = billing_service.ensure_customer_link(firm_id, client_id, internal_id)

    inv_in = SalesInvoiceIn(
        client_id=internal_id, customer_id=customer_id,
        # A placeholder the Partner replaces with the real number before issuing, as on a schedule's draft.
        invoice_no=draft_placeholder_invoice_no(),
        invoice_date=ist_today().isoformat(),
        lines=[SalesInvoiceLineIn(service_catalogue_id=service_id, description=line["description"],
                                  hsn_sac=billing_service.CA_SERVICE_SAC, quantity=1,
                                  rate_paise=int(line["value_paise"]), gst_rate_percent=float(gst_rate_percent),
                                  is_service=True) for line in lines],
        notes=f"Time billed: {len(entries)} time entr{'y' if len(entries) == 1 else 'ies'}, {_hours_text(sum(e['minutes'] for e in entries))}.",
    )
    # REUSE the sales engine (GST, place of supply, insert, timeline), as a billing schedule's draft does.
    from routers.sales_invoices import create_invoice
    resp = create_invoice(inv_in, current_user)
    if not resp.get("success") or not (resp.get("data") or {}).get("id"):
        raise HTTPException(500, resp.get("error") or "The draft invoice could not be created, so no time was marked as billed.")
    invoice = resp["data"]

    ids = [e["id"] for e in entries]
    try:
        taken = _claim(db, firm_id, client_id, ids, invoice["id"])
    except Exception:
        _drop_draft(db, firm_id, internal_id, invoice["id"])
        raise
    if taken != len(ids):
        # Somebody billed one of these in the meantime. Deleting the draft releases whatever this request took.
        _drop_draft(db, firm_id, internal_id, invoice["id"])
        raise HTTPException(409, "Some of this time was billed by somebody else a moment ago, so no invoice was made. "
                                 "Reload the list and choose again.")

    log_event(firm_id, "time_billing", str(invoice["id"]), "create",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"client_id": client_id, "entries": len(ids), "group_by": group_by,
                        "value_paise": sum(line["value_paise"] for line in lines)})
    return {
        "invoice_id": invoice["id"], "invoice_no": invoice.get("invoice_no"), "practice_client_id": internal_id,
        "entries_billed": len(ids), "minutes": sum(e["minutes"] for e in entries),
        "value_paise": sum(line["value_paise"] for line in lines),
        "lines": [{k: line[k] for k in ("description", "minutes", "value_paise")} for line in lines],
    }


def _claim(db, firm_id: str, client_id: str, ids: list[str], invoice_id: str) -> int:
    """Mark the entries with the invoice, taking ONLY those still unbilled, and answer how many were taken. Sent in pieces
    a request line can carry; each piece is one statement, and the caller compares the total with what it asked for."""
    taken = 0
    for start in range(0, len(ids), 100):
        piece = ids[start:start + 100]
        res = (privileged_for(db).table("time_entries").update({"billed_invoice_id": invoice_id})
               .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", piece).is_("billed_invoice_id", "null").execute())
        taken += len(res.data or [])
    return taken


def _drop_draft(db, firm_id: str, internal_id: str, invoice_id: str) -> None:
    """Delete the draft this request created. Its lines go with it and the database releases any entry marked with it."""
    try:
        privileged_for(db).table("client_sales_invoice_lines").delete().eq("sales_invoice_id", invoice_id).execute()
        (privileged_for(db).table("client_sales_invoices").delete()
         .eq("id", invoice_id).eq("firm_id", firm_id).eq("client_id", internal_id).eq("status", "draft").execute())
    except Exception:  # noqa: BLE001 - reported; the refusal the caller raises is the one the person must see
        _logger.error("time billing: the draft %s could not be removed after a failed claim", invoice_id, exc_info=True)


def release_for_invoice(db, firm_id: str, invoice_id: str) -> int:
    """Unmark every entry billed by this invoice, and answer how many. For a time invoice that has been cancelled: a
    cancelled invoice bills nothing. An invoice that billed no time releases nothing."""
    res = (privileged_for(db).table("time_entries").update({"billed_invoice_id": None})
           .eq("firm_id", firm_id).eq("billed_invoice_id", invoice_id).execute())
    return len(res.data or [])
