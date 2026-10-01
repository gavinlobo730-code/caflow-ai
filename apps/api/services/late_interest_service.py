"""Interest on an overdue customer balance: the figure, and a PREPARED draft
(accounting-22, migration 461).

The rule is `domain/sales/late_interest.py` — read its header first: the
convention (simple, actual/365, half-up), what the balance is, and the one
statutory reading it carries (CGST s.15(2)(d), `[S]`). This module FETCHES the
inputs and, on a click, hands a draft to the sales engine; it decides nothing
the domain module decides.

WHAT IT READS

    * `customers` — the terms. Three columns, written by ONE door
      (`set_terms`), so one validation rule (`terms_problem`).
    * `client_sales_invoices.outstanding_paise` — migration 278's GENERATED
      column, read and never re-subtracted, filtered IN THE QUERY (`gt
      outstanding_paise 0`, not a draft, not cancelled, not deleted) exactly as
      `customer_statement_service.ar_aging` does it, so what crosses the wire is
      what is OWED rather than everything ever billed. Paged by
      `core.db_paging.fetch_all`.
    * `late_interest_charges` — what an earlier draft already covers.

WHAT A STANDING CHARGE IS

    A charge row records "this overdue invoice's interest to <date> is on that
    draft". It STANDS only while the draft does — derived at read time from the
    interest invoice's own `status` and `deleted_at` — so deleting an unwanted
    draft releases its period with no second write to forget (migration 278's
    reasoning, applied to a different fact). A cancelled interest invoice
    releases it too. An interest invoice is also taken OUT of the base of every
    later preview, so interest is never charged on interest.

    A RELEASED CLAIM STILL HOLDS ITS KEY UNTIL SOMEBODY TAKES THE PERIOD UP AGAIN.
    "Releases" above is a statement about what the PREVIEW offers, and the unique
    index on (sales_invoice_id, period_to) knows nothing about a draft's status:
    it covers every row, so a cancelled draft's claim (which keeps its pointer)
    and a hard-deleted draft's claim (migration 461's pointer is set to NULL and
    the row KEPT) both go on occupying the key. A preview offered the same days
    again, the CA clicked, the new claim collided with the dead one, and the
    click answered "just drafted by another request" after taking back the draft
    it had just made. So `prepare_drafts` REMOVES the dead claim that is in the
    way (`_release_stale_claims`) between making the draft and recording its
    claim: only a claim whose draft does not stand, only one holding exactly a
    key this draft is about to claim, and by its own id — so a rival's claim that
    stands is never touched and the index remains the arbiter of the race.
    Every other dead claim is left where it is, as the record of what that draft
    was computed from; the audit event of the draft that replaced one names it.

WHAT A DRAFT IS

    `routers.sales_invoices.create_invoice` — the existing engine, the same call
    `recurring_invoice_service` makes — with ONE line per overdue invoice at the
    GST rate of the invoice it relates to (s.15(2)(d) puts the interest in that
    supply's value). It is a DRAFT: no journal, no number the CA has not typed
    (the placeholder must be replaced before Issue), nothing emailed. A document
    the draft cannot reproduce the tax treatment of is NAMED and left for the CA
    (`domain/sales/late_interest.block_reason`).

    The figures are recomputed here from the books on every call and never taken
    from the request, so a stale screen cannot put a number on an invoice.

    THE CLAIM IS RECORDED AFTER THE DRAFT EXISTS and a duplicate claim (two
    clicks in one instant) deletes the draft it just made: the unique index on
    (sales_invoice_id, period_to) is the arbiter, and a draft with no claim
    behind it is the one outcome worse than a refused click.

NOTHING HERE POSTS. NOTHING HERE ISSUES, EMAILS OR REMINDS.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import ist_today
from domain.sales import late_interest as L

_logger = logging.getLogger("caflow.late_interest")

#: An invoice in these states is not a receivable. The SAME set
#: `customer_statement_service.ar_aging` filters on; imported there rather than
#: restated so the two cannot disagree about what is open.
def _dead_invoice_states() -> list[str]:
    from services.customer_statement_service import _DEAD_INVOICE
    return sorted(_DEAD_INVOICE)


# ── Terms ────────────────────────────────────────────────────────────────────

def list_terms(db, firm_id: str, client_id: str) -> list[dict]:
    """Every customer of the client with the interest terms on record."""
    rows = fetch_all(lambda: (
        db.table("customers")
        .select("id, name, late_interest_rate_bps, late_interest_grace_days, late_interest_from")
        .eq("firm_id", firm_id).eq("client_id", client_id)), label="late_interest.terms")
    out = [_terms_row(r) for r in rows]
    out.sort(key=lambda r: str(r["customer_name"] or "").lower())
    return out


def _terms_row(r: dict) -> dict:
    rate = r.get("late_interest_rate_bps")
    return {
        "customer_id": r.get("id"),
        "customer_name": r.get("name"),
        "rate_bps": None if rate is None else int(rate),
        "grace_days": int(r.get("late_interest_grace_days") or 0),
        "basis": r.get("late_interest_from") or L.FROM_DUE_DATE,
    }


def set_terms(db, firm_id: str, client_id: str, customer_id: str, *,
              rate_bps: Optional[int], grace_days: int, basis: str,
              actor: Optional[dict] = None) -> dict:
    """Record (or, with `rate_bps=None`, clear) a customer's interest terms.

    The ONE writer of these three columns. `rate_bps=None` clears the rate; the
    grace and basis are kept so a rate typed again later starts from what was
    there.
    """
    problem = L.terms_problem(rate_bps, grace_days, basis)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    found = (db.table("customers").select("id")
             .eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id)
             .limit(1).execute().data) or []
    if not found:
        # One fixed message for missing and for another client's — never a
        # confirmation that the id exists somewhere else.
        raise HTTPException(status_code=404, detail="Customer not found.")
    saved = (db.table("customers").update({
        "late_interest_rate_bps": rate_bps,
        "late_interest_grace_days": int(grace_days),
        "late_interest_from": basis,
    }).eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id)
        .execute().data) or []
    row = saved[0] if saved else {"id": customer_id, "late_interest_rate_bps": rate_bps,
                                  "late_interest_grace_days": grace_days,
                                  "late_interest_from": basis}
    try:
        from services.audit_service import log_event
        log_event(firm_id, "customer", customer_id, "late_interest_terms",
                  actor_id=(actor or {}).get("auth_user_id"),
                  new_data={"rate_bps": rate_bps, "grace_days": grace_days, "basis": basis},
                  metadata={"source": "late_interest"})
    except Exception:                                    # pragma: no cover - audit never blocks
        pass
    return _terms_row({**row, "name": row.get("name")})


# ── What is already charged ──────────────────────────────────────────────────

def _charge_rows(db, firm_id: str, client_id: str,
                 invoice_ids: Optional[list[str]] = None) -> list[dict]:
    """The client's charge rows (or those on `invoice_ids`), each stamped with
    `standing`: whether the draft it produced still stands (not deleted, not
    cancelled). THE ONE DEFINITION of that — what the preview counts as covered
    and what a re-prepare may release both ask it, so they cannot disagree."""
    def charges():
        return (db.table("late_interest_charges")
                .select("id, sales_invoice_id, interest_invoice_id, period_to, "
                        "interest_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id))
    rows = (fetch_all(charges, label="late_interest.charges") if invoice_ids is None
            else fetch_all_in(charges, "sales_invoice_id", invoice_ids,
                              label="late_interest.charges"))
    live_ids = {r["interest_invoice_id"] for r in rows if r.get("interest_invoice_id")}
    standing: set[str] = set()
    if live_ids:
        states = fetch_all_in(lambda: (
            db.table("client_sales_invoices").select("id, status, deleted_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)),
            "id", sorted(live_ids), label="late_interest.interest_invoices")
        standing = {s["id"] for s in states
                    if not s.get("deleted_at") and (s.get("status") or "") != "cancelled"}
    return [{**r, "standing": r.get("interest_invoice_id") in standing} for r in rows]


def _standing_charges(db, firm_id: str, client_id: str) -> tuple[dict[str, date], set[str]]:
    """({overdue invoice id: the as-at date its interest is charged through},
    {interest invoice ids}) — counting only charges whose draft still stands."""
    through: dict[str, date] = {}
    interest_invoices: set[str] = set()
    for r in _charge_rows(db, firm_id, client_id):
        if not r["standing"]:
            continue
        d = L.as_date(r.get("period_to"))
        if d is None:
            continue
        iid = r["sales_invoice_id"]
        if iid not in through or d > through[iid]:
            through[iid] = d
        interest_invoices.add(r["interest_invoice_id"])
    return through, interest_invoices


def _stale_claims(db, firm_id: str, client_id: str, documents) -> list[dict]:
    """The dead claims that hold a key one of `documents` is about to claim: a
    row for the same overdue invoice up to the same date whose draft no longer
    stands (cancelled, deleted, or its pointer cleared by a hard delete)."""
    wanted = {(d.invoice_id, L.as_date(d.period_to)) for d in documents}
    rows = _charge_rows(db, firm_id, client_id, [d.invoice_id for d in documents])
    return [r for r in rows
            if not r["standing"]
            and (r["sales_invoice_id"], L.as_date(r.get("period_to"))) in wanted]


def _release_stale_claims(db, firm_id: str, client_id: str, documents) -> list[dict]:
    """Remove the dead claims `_stale_claims` finds, each BY ITS OWN ID.

    By id and never by key: between the read and the delete a rival request may
    have released the same row and written a claim of its own on that key, and a
    delete by key would erase a claim that stands and let the same days be
    charged twice. By id the worst a race can do is delete a row that is already
    gone. Returns what was removed, for the audit event.
    """
    gone = []
    for r in _stale_claims(db, firm_id, client_id, documents):
        (db.table("late_interest_charges").delete()
         .eq("id", r["id"]).eq("firm_id", firm_id).eq("client_id", client_id).execute())
        gone.append({"charge_id": r["id"], "interest_invoice_id": r.get("interest_invoice_id"),
                     "sales_invoice_id": r["sales_invoice_id"],
                     "period_to": str(r.get("period_to"))[:10],
                     "interest_paise": r.get("interest_paise")})
    return gone


# ── The preview ──────────────────────────────────────────────────────────────

def _open_invoices(db, firm_id: str, client_id: str, customer_id: Optional[str]) -> list[dict]:
    def one():
        q = (db.table("client_sales_invoices")
             .select("id, customer_id, invoice_no, invoice_date, due_date, "
                     "outstanding_paise, status")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .is_("deleted_at", "null")
             .not_.in_("status", _dead_invoice_states())
             .gt("outstanding_paise", 0))
        return q.eq("customer_id", customer_id) if customer_id else q
    return fetch_all(one, label="late_interest.open_invoices")


def _party_inputs(db, firm_id: str, client_id: str,
                  customer_id: Optional[str]) -> list[L.PartyInput]:
    def customers():
        q = (db.table("customers")
             .select("id, name, late_interest_rate_bps, late_interest_grace_days, "
                     "late_interest_from")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        return q.eq("id", customer_id) if customer_id else q
    people = {c["id"]: c for c in fetch_all(customers, label="late_interest.customers")}
    invoices = _open_invoices(db, firm_id, client_id, customer_id)
    through, interest_invoices = _standing_charges(db, firm_id, client_id)

    by_customer: dict[str, list[L.DocInput]] = {}
    for inv in invoices:
        cid = inv.get("customer_id")
        if cid not in people:
            continue
        by_customer.setdefault(cid, []).append(L.DocInput(
            invoice_id=inv["id"], invoice_no=inv.get("invoice_no") or "",
            invoice_date=inv.get("invoice_date"), due_date=inv.get("due_date"),
            outstanding_paise=int(inv.get("outstanding_paise") or 0),
            charged_through=through.get(inv["id"]),
            is_interest_invoice=inv["id"] in interest_invoices))
    out = []
    for cid, docs in by_customer.items():
        c = people[cid]
        t = _terms_row(c)
        out.append(L.PartyInput(
            customer_id=cid, name=c.get("name") or "",
            terms=L.Terms(rate_bps=t["rate_bps"], grace_days=t["grace_days"], basis=t["basis"]),
            documents=tuple(docs)))
    return out


def preview(db, firm_id: str, client_id: str, as_of: Optional[date] = None,
            customer_id: Optional[str] = None) -> dict:
    """Interest due per party as at a date. Reads; writes nothing."""
    as_of = as_of or ist_today()
    return L.build_preview(_party_inputs(db, firm_id, client_id, customer_id), as_of)


# ── The prepared draft ───────────────────────────────────────────────────────

#: The catalogue item every interest line is put under. EVERY sales-invoice line
#: must name a Product/Service (`models/invoices.InvoiceLineIn`), and it cannot
#: be one of the client's own GOODS: a goods line is how
#: `domain/inventory_service` recognises a stock movement, so an interest line
#: under a stocked item would take stock out when the draft is issued. So the
#: interest goes under a SERVICE of its own, found by name and created once if
#: the client has none — a billing preset, which is all `service_catalogue` is.
INTEREST_ITEM_NAME = "Interest on delayed payment"


def _norm(name) -> str:
    return " ".join(str(name or "").split()).lower()


def _interest_item(db, firm_id: str, client_id: str) -> str:
    rows = (db.table("service_catalogue").select("id, name, kind, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("is_active", True).execute().data) or []
    for r in rows:
        if _norm(r.get("name")) != _norm(INTEREST_ITEM_NAME):
            continue
        if (r.get("kind") or "service") != "service":
            raise HTTPException(status_code=422, detail=(
                f"This client already has a stocked product called '{INTEREST_ITEM_NAME}'. "
                "Interest cannot be put on a stock item — rename that product, then "
                "try again."))
        return r["id"]
    made = (db.table("service_catalogue").insert({
        "firm_id": firm_id, "client_id": client_id, "name": INTEREST_ITEM_NAME,
        "kind": "service", "default_rate_paise": 0, "is_active": True,
        "notes": "Created for the overdue-interest drafts (accounting-22). Interest lines are "
                 "priced on the draft itself; this item carries no rate.",
    }).execute().data) or []
    if not made:
        raise HTTPException(status_code=500,
                            detail="The 'Interest on delayed payment' item could not be created.")
    return made[0]["id"]

def _invoice_facts(db, firm_id: str, client_id: str, invoice_ids: list[str]) -> dict[str, dict]:
    """What each invoice's own header and lines say about the tax its interest
    follows: GST rate (one, several or none), place of supply, supply class and
    the one HSN/SAC its lines share, if they share one."""
    heads = {h["id"]: h for h in fetch_all_in(lambda: (
        db.table("client_sales_invoices")
        .select("id, is_interstate, supply_state_code, supply_type, invoice_type, "
                "is_reverse_charge")
        .eq("firm_id", firm_id).eq("client_id", client_id)),
        "id", invoice_ids, label="late_interest.invoice_heads")}
    lines: dict[str, list[dict]] = {}
    for ln in fetch_all_in(lambda: db.table("client_sales_invoice_lines")
                           .select("id, sales_invoice_id, gst_rate_bps, hsn_sac"),
                           "sales_invoice_id", invoice_ids, label="late_interest.invoice_lines"):
        lines.setdefault(ln["sales_invoice_id"], []).append(ln)
    out: dict[str, dict] = {}
    for iid in invoice_ids:
        head, ls = heads.get(iid) or {}, lines.get(iid) or []
        rates = {int(x["gst_rate_bps"]) for x in ls if x.get("gst_rate_bps") is not None}
        codes = {str(x["hsn_sac"]).strip() for x in ls if x.get("hsn_sac")}
        out[iid] = {
            "rate_state": "none" if not rates else ("single" if len(rates) == 1 else "mixed"),
            "gst_rate_bps": next(iter(rates)) if len(rates) == 1 else None,
            "hsn_sac": next(iter(codes)) if len(codes) == 1 else None,
            "is_interstate": bool(head.get("is_interstate")),
            "supply_state_code": head.get("supply_state_code") or None,
            "supply_type": head.get("supply_type") or "taxable",
            "invoice_type": head.get("invoice_type") or "Regular",
            "is_reverse_charge": bool(head.get("is_reverse_charge")),
        }
    return out


def _delete_draft(db, firm_id: str, invoice_id: str) -> None:
    """Take back a draft this module just made (a draft has no journal)."""
    try:
        db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", invoice_id).execute()
        (db.table("client_sales_invoices").delete()
         .eq("id", invoice_id).eq("firm_id", firm_id).eq("status", "draft").execute())
    except Exception as e:                                # pragma: no cover - logged, never raised
        _logger.error("could not remove draft %s after a failed claim: %s", invoice_id, e)


def prepare_drafts(db, firm_id: str, client_id: str, customer_id: str, as_of: Optional[date],
                   actor: dict, invoice_ids: Optional[list[str]] = None) -> dict:
    """Prepare DRAFT sales invoice(s) for one customer's interest as at a date.

    Posts nothing and issues nothing. Returns the drafts created, the documents
    a draft cannot be made for (named), and the same convention and statutory
    reading the preview carries.
    """
    from models.invoices import SalesInvoiceIn, SalesInvoiceLineIn
    from routers.sales_invoices import create_invoice
    from services.numbering import draft_placeholder_invoice_no

    as_of = as_of or ist_today()
    preview_doc = preview(db, firm_id, client_id, as_of, customer_id)
    party = next((p for p in preview_doc["parties"] if p["customer_id"] == customer_id), None)
    if party is None:
        raise HTTPException(status_code=409, detail=(
            f"This customer has nothing overdue as at {as_of.isoformat()}, so there is "
            "no interest to charge."))
    if not party["terms_set"]:
        raise HTTPException(status_code=422, detail=(
            "This customer has no interest rate on record, so no interest is computed "
            "and none can be drafted. Record the rate first."))

    due = [d for d in party["documents"] if d["status"] == L.CHARGE]
    if invoice_ids is not None:
        wanted = set(invoice_ids)
        due = [d for d in due if d["invoice_id"] in wanted]
    if not due:
        covered = [d for d in party["documents"] if d["status"] == L.COVERED]
        why = (" A draft already covers the days up to this date for "
               f"{len(covered)} invoice(s)." if covered else "")
        raise HTTPException(status_code=409, detail=(
            f"There is no interest to charge as at {as_of.isoformat()}.{why}"))

    ids = [d["invoice_id"] for d in due]
    facts = _invoice_facts(db, firm_id, client_id, ids)
    rate_bps = int(party["terms"]["rate_bps"])
    grace = int(party["terms"]["grace_days"])
    chargeable = [L.ChargeableDoc(
        invoice_id=d["invoice_id"], invoice_no=d["invoice_no"], customer_id=customer_id,
        interest_paise=int(d["interest_paise"]), period_from=d["period_from"],
        period_to=d["period_to"], days=int(d["days_charged"]),
        outstanding_paise=int(d["outstanding_paise"]), interest_rate_bps=rate_bps,
        **facts[d["invoice_id"]]) for d in due]
    groups, blocked = L.plan_drafts(chargeable)
    if not groups:
        raise HTTPException(status_code=422, detail=" ".join(b["reason"] for b in blocked))

    item_id = _interest_item(db, firm_id, client_id)
    created: list[dict] = []
    failed: list[dict] = []
    for group in groups:
        lines = [SalesInvoiceLineIn(
            description=L.line_description(doc), hsn_sac=doc.hsn_sac, quantity=1,
            rate_paise=doc.interest_paise, gst_rate_percent=group.gst_rate_bps / 100.0,
            service_catalogue_id=item_id)
            for doc in group.documents]
        inv_in = SalesInvoiceIn(
            client_id=client_id, customer_id=customer_id,
            # The CA types the real number; the engine refuses to issue a
            # placeholder (services/numbering.draft_placeholder_invoice_no).
            invoice_no=draft_placeholder_invoice_no(),
            invoice_date=as_of.isoformat(), lines=lines,
            is_inter_state=group.is_interstate,
            supply_state_code=group.supply_state_code,
            notes=(f"Interest for delayed payment, computed to {as_of.isoformat()}: "
                   f"{preview_doc['convention']['statement']} PREPARED DRAFT — the CA "
                   "confirms the rate, the figures and the tax treatment before issuing."),
        )
        try:
            resp = create_invoice(inv_in, actor)
        except HTTPException as e:
            failed.append({"reason": str(e.detail),
                           "invoice_nos": [d.invoice_no for d in group.documents]})
            continue
        if not resp.get("success"):
            failed.append({"reason": resp.get("error") or "The sales engine refused the draft.",
                           "invoice_nos": [d.invoice_no for d in group.documents]})
            continue
        draft = resp["data"]
        try:
            # A dead claim on one of these keys would make the insert below fail
            # against the unique index (see the module header); a claim that
            # still stands is never in this list.
            released = _release_stale_claims(db, firm_id, client_id, group.documents)
            # Written INLINE with literal keys, in ONE statement: a payload built
            # in a variable hides every column name from
            # tests/test_backend_columns_exist_pg.py (which budgets exactly that),
            # and one statement is what makes a group's claims all-or-nothing.
            db.table("late_interest_charges").insert([{
                "firm_id": firm_id, "client_id": client_id, "customer_id": customer_id,
                "sales_invoice_id": doc.invoice_id, "interest_invoice_id": draft["id"],
                "period_from": doc.period_from, "period_to": doc.period_to, "days": doc.days,
                "outstanding_paise": doc.outstanding_paise, "rate_bps": rate_bps,
                "grace_days": grace, "day_count": L.DAY_COUNT,
                "interest_paise": doc.interest_paise, "created_by": actor.get("id"),
            } for doc in group.documents]).execute()
        except Exception as e:
            # The unique index says another click got there first. The draft
            # this one made has no claim behind it, so it goes.
            _delete_draft(db, firm_id, draft["id"])
            failed.append({"reason": ("The interest for these invoices up to this date "
                                      "was just drafted by another request. "
                                      f"({type(e).__name__})"),
                           "invoice_nos": [d.invoice_no for d in group.documents]})
            continue
        created.append({
            "invoice_id": draft["id"], "invoice_no": draft.get("invoice_no"),
            "status": draft.get("status", "draft"),
            "total_paise": draft.get("total_paise"),
            "interest_paise": group.interest_paise,
            "gst_rate_bps": group.gst_rate_bps, "is_interstate": group.is_interstate,
            "invoice_nos": [d.invoice_no for d in group.documents],
        })
        try:
            from services.audit_service import log_event
            log_event(firm_id, "sales_invoice", draft["id"], "late_interest_draft",
                      actor_id=actor.get("auth_user_id"),
                      new_data={"as_of": as_of.isoformat(), "interest_paise": group.interest_paise,
                                "overdue_invoices": [d.invoice_id for d in group.documents],
                                "replaced_claims": released},
                      metadata={"source": "late_interest", "status": "draft"})
        except Exception:                                  # pragma: no cover
            pass

    if not created:
        reasons = "; ".join(f["reason"] for f in failed) or "No draft could be made."
        raise HTTPException(status_code=409, detail=reasons)
    return {
        "as_of": as_of.isoformat(),
        "drafts": created,
        "not_drafted": blocked,
        "failed": failed,
        "convention": preview_doc["convention"],
        "statutory_reading": preview_doc["statutory_reading"],
        "caveats": preview_doc["caveats"],
    }
