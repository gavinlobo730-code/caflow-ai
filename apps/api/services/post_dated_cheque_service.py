"""The post-dated cheque register: record it, see what is due, convert it
(accounting-21, migration 460).

The rule is `domain/banking/pdc.py` — read its header first. A post-dated cheque
is a MEMORANDUM: this module records one and POSTS NOTHING. The books are the
same the day a cheque is recorded as they were the day before.

THERE IS NO SECOND POSTING PATH. Converting a due cheque calls
`receipt_service.create_receipt_core` (a cheque RECEIVED) or
`purchase_payment_service.create_payment_core` (a cheque ISSUED), the two
engines every other settlement reaches the books through. They are the same two
calls `BankPostingService.match_and_settle_multi` makes for a bank-statement
line — and that is why this does not go through `bank_posting_service.post`: a
PDC has no imported statement line for `post` to read, and `post` is the
statement-line path, while `match_and_settle_multi` itself ends in exactly these
engines. So the journal, the invoice settlement (CAS-guarded, validated against
the LIVE outstanding), the closed-year check, the filed-return check where a
receipt feeds a return and the GST advance rules are a normal receipt's. Nothing
in this module writes a journal, a receipt row or an invoice.

CONVERSION IS CLAIMED BEFORE IT IS PERFORMED. Two clicks in one instant would
each read the cheque as held and each make a receipt, so the first act is a
compare-and-set on `status` (`held` -> `converted`); only the winner calls the
engine, and a failed engine call puts the cheque back to held so the CA can
retry. The link to the document it became is written after, and a failure of
THAT write is logged loudly and does not undo a receipt that exists.

Every read and write carries `firm_id` and `client_id`; a cheque, party, bank
account or document belonging to another client is reported as not found, never
confirmed as existing elsewhere.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import ist_today
from domain.accounting import payment_account
from domain.banking import pdc as P

_logger = logging.getLogger("caflow.post_dated_cheques")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(err: Exception) -> bool:
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def _audit(firm_id: str, cheque_id: str, action: str, actor: Optional[dict], data: dict) -> None:
    """The edit log. `audit_log.actor_id` takes the AUTH id (see the audit-actor
    rule); `created_by` / `converted_by` on the row take the internal user id."""
    try:
        from services.audit_service import log_event
        log_event(firm_id, "post_dated_cheque", cheque_id, action,
                  actor_id=(actor or {}).get("auth_user_id"), new_data=data,
                  metadata={"source": "post_dated_cheques"})
    except Exception:                                      # pragma: no cover - audit never blocks
        _logger.warning("could not write the audit entry for cheque %s", cheque_id)


# ── Reads ────────────────────────────────────────────────────────────────────

def _get(db, firm_id: str, client_id: str, cheque_id: str) -> dict:
    # The projection is written out at each read, as a literal: the schema guard
    # (tests/test_backend_columns_exist_pg) checks a select list as a string and
    # cannot see one reached through a name.
    rows = (db.table("post_dated_cheques")
            .select("id, firm_id, client_id, direction, customer_id, vendor_id, cheque_no, "
                    "cheque_date, amount_paise, drawee_bank, bank_account_id, allocations, "
                    "status, notes, converted_receipt_id, converted_payment_id, converted_at, "
                    "cancelled_at, cancel_reason, created_at")
            .eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data) or []
    if not rows:
        # One message for "absent" and for "another client's".
        raise HTTPException(status_code=404, detail="Cheque not found.")
    return rows[0]


def _customer_names(db, firm_id: str, client_id: str, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = fetch_all_in(lambda: (
        db.table("customers").select("id, name")
        .eq("firm_id", firm_id).eq("client_id", client_id)),
        "id", ids, label="pdc.customers")
    return {r["id"]: r.get("name") for r in rows}


def _vendor_names(db, firm_id: str, client_id: str, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = fetch_all_in(lambda: (
        db.table("vendors").select("id, name")
        .eq("firm_id", firm_id).eq("client_id", client_id)),
        "id", ids, label="pdc.vendors")
    return {r["id"]: r.get("name") for r in rows}


def list_register(db, firm_id: str, client_id: str, *, today=None,
                  direction: Optional[str] = None, include_finished: bool = False) -> dict:
    """The register as a worklist: what is due, what is coming, with the party's
    name and the derived state. By default only HELD cheques are read — the
    answer is what is waiting, not every cheque ever recorded — and finished ones
    (converted, cancelled) come back when asked for."""
    today = today or ist_today()
    if direction is not None and direction not in P.DIRECTIONS:
        raise HTTPException(status_code=422, detail="direction is received or issued.")

    def one_page():
        q = (db.table("post_dated_cheques")
             .select("id, firm_id, client_id, direction, customer_id, vendor_id, cheque_no, "
                     "cheque_date, amount_paise, drawee_bank, bank_account_id, allocations, "
                     "status, notes, converted_receipt_id, converted_payment_id, converted_at, "
                     "cancelled_at, cancel_reason, created_at")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        if not include_finished:
            q = q.eq("status", P.HELD)
        return q.eq("direction", direction) if direction else q

    rows = fetch_all(one_page, label="pdc.register")
    customers = _customer_names(db, firm_id, client_id,
                                [r["customer_id"] for r in rows if r.get("customer_id")])
    vendors = _vendor_names(db, firm_id, client_id,
                            [r["vendor_id"] for r in rows if r.get("vendor_id")])
    out = []
    for r in rows:
        shown = P.register_row(r, today)
        shown["party_name"] = (customers.get(r.get("customer_id")) if r.get("customer_id")
                               else vendors.get(r.get("vendor_id")))
        # The row says up front, from its own two facts, that no bank account is
        # named: the engine would post to the firm's general Bank ledger and say
        # so afterwards, which is a worse moment to find out.
        shown[payment_account.NOTICE_KEY] = (
            payment_account.row_notice(r.get("bank_account_id"), P.PAYMENT_MODE)
            if r.get("status") == P.HELD else None)
        out.append(shown)
    out.sort(key=P.sort_key)
    return {
        "as_of": today.isoformat(),
        "cheques": out,
        "summary": P.summarise(out),
        "notes": [
            "A post-dated cheque is a memorandum. Nothing on this register is in the books "
            "until a due cheque is converted into a receipt or a payment.",
            f"A cheque is valid for {P.CHEQUE_VALIDITY_MONTHS} months from its date "
            f"(RBI; {P.VALIDITY_GRADE}).",
        ],
        "includes_finished": include_finished,
    }


# ── What the "record a cheque" form offers ───────────────────────────────────

def _dead_states() -> list[str]:
    """The SAME set the receivables and payables ageing filter on: a draft was
    never issued and a cancelled one is terminal, so neither can be settled."""
    from services.customer_statement_service import _DEAD_INVOICE
    return sorted(_DEAD_INVOICE)


def options(db, firm_id: str, client_id: str, direction: str,
            party_id: Optional[str] = None) -> dict:
    """What the form picks from: the client's active parties, its bank accounts
    and — once a party is chosen — that party's OPEN documents with what each
    still owes (`outstanding_paise`, migration 278's generated column, read and
    never re-subtracted).

    Served here rather than read by the screen over PostgREST, so the form goes
    through `rbac()` and the client scope like everything else on the register,
    and so what it offers to settle is what the engine will accept."""
    if direction not in P.DIRECTIONS:
        raise HTTPException(status_code=422, detail="direction is received or issued.")
    if direction == P.RECEIVED:
        people = fetch_all(lambda: (
            db.table("customers").select("id, name, gstin")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("is_active", True)), label="pdc.parties")
    else:
        people = fetch_all(lambda: (
            db.table("vendors").select("id, name, gstin")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("is_active", True)), label="pdc.parties")
    banks = fetch_all(lambda: (
        db.table("bank_accounts").select("id, bank_name, account_no, is_active")
        .eq("firm_id", firm_id).eq("client_id", client_id)), label="pdc.banks")
    documents: list[dict] = []
    if party_id:
        if direction == P.RECEIVED:
            rows = fetch_all(lambda: (
                db.table("client_sales_invoices")
                .select("id, invoice_no, invoice_date, due_date, outstanding_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("customer_id", party_id).is_("deleted_at", "null")
                .not_.in_("status", _dead_states()).gt("outstanding_paise", 0)),
                label="pdc.open_invoices")
            documents = [{"id": r["id"], "number": r.get("invoice_no"), "date": r.get("invoice_date"),
                          "due_date": r.get("due_date"),
                          "outstanding_paise": int(r.get("outstanding_paise") or 0)} for r in rows]
        else:
            rows = fetch_all(lambda: (
                db.table("purchase_bills")
                .select("id, bill_no, bill_date, due_date, outstanding_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("vendor_id", party_id).is_("deleted_at", "null")
                .not_.in_("status", _dead_states()).gt("outstanding_paise", 0)),
                label="pdc.open_bills")
            documents = [{"id": r["id"], "number": r.get("bill_no"), "date": r.get("bill_date"),
                          "due_date": r.get("due_date"),
                          "outstanding_paise": int(r.get("outstanding_paise") or 0)} for r in rows]
    documents.sort(key=lambda d: (str(d.get("due_date") or d.get("date") or ""), str(d["number"] or "")))
    return {
        "parties": sorted(({"id": r["id"], "name": r.get("name"), "gstin": r.get("gstin")}
                           for r in people), key=lambda p: str(p["name"] or "").lower()),
        "bank_accounts": [
            {"id": b["id"],
             # Masked: this is read over a shoulder. The last four digits tell
             # two accounts at one bank apart.
             "name": f"{b.get('bank_name') or 'Bank'} ····{str(b.get('account_no') or '')[-4:]}"}
            for b in banks if b.get("is_active") is not False],
        "documents": documents,
    }


# ── Checks that need the database ────────────────────────────────────────────

def _check_party(db, firm_id: str, client_id: str, direction: str,
                 customer_id: Optional[str], vendor_id: Optional[str]) -> None:
    if direction == P.RECEIVED:
        found = (db.table("customers").select("id").eq("id", customer_id)
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .limit(1).execute().data) or []
        label = "Customer"
    else:
        found = (db.table("vendors").select("id").eq("id", vendor_id)
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .limit(1).execute().data) or []
        label = "Supplier"
    if not found:
        raise HTTPException(status_code=404, detail=f"{label} not found.")


def _check_bank_account(db, firm_id: str, client_id: str, bank_account_id: Optional[str]) -> None:
    if not bank_account_id:
        return
    found = (db.table("bank_accounts").select("id").eq("id", bank_account_id)
             .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not found:
        raise HTTPException(status_code=404, detail="Bank account not found.")


def _check_documents(db, firm_id: str, client_id: str, direction: str, party_id: str,
                     allocations: list[dict]) -> None:
    """Each document the cheque is meant for is THIS client's AND this party's.
    Whether it is open, and for how much, is the engine's to say at conversion."""
    if not allocations:
        return
    key = P.ALLOCATION_KEY[direction]
    ids = [a[key] for a in allocations]
    if direction == P.RECEIVED:
        rows = fetch_all_in(lambda: (
            db.table("client_sales_invoices").select("id, customer_id")
            .eq("firm_id", firm_id).eq("client_id", client_id)),
            "id", ids, label="pdc.invoices")
        belongs = {r["id"]: r.get("customer_id") for r in rows}
    else:
        rows = fetch_all_in(lambda: (
            db.table("purchase_bills").select("id, vendor_id")
            .eq("firm_id", firm_id).eq("client_id", client_id)),
            "id", ids, label="pdc.bills")
        belongs = {r["id"]: r.get("vendor_id") for r in rows}
    missing = [i for i in ids if i not in belongs]
    if missing:
        raise HTTPException(status_code=422, detail=(
            f"{'Invoice' if direction == P.RECEIVED else 'Bill'} not part of this client's "
            "books: " + ", ".join(missing)))
    wrong = [i for i in ids if belongs[i] != party_id]
    if wrong:
        raise HTTPException(status_code=422, detail=(
            "A cheque settles one party's documents, and these belong to somebody else: "
            + ", ".join(wrong)))


def _check_not_a_duplicate(db, client_id: str, direction: str, party_id: str,
                           cheque_no: str, except_id: Optional[str] = None) -> None:
    def one_page():
        q = (db.table("post_dated_cheques").select("id, cheque_no, status")
             .eq("client_id", client_id).eq("direction", direction))
        if direction == P.RECEIVED:
            return q.eq("customer_id", party_id)
        return q.eq("vendor_id", party_id)

    rows = fetch_all(one_page, label="pdc.duplicates")
    wanted = P.normalise_cheque_no(cheque_no).lower()
    for r in rows:
        if r["id"] == except_id or r.get("status") == P.CANCELLED:
            continue
        if P.normalise_cheque_no(r.get("cheque_no")).lower() == wanted:
            raise HTTPException(status_code=409, detail=(
                f"Cheque {P.normalise_cheque_no(cheque_no)} is already on the register for "
                "this party. If it was a keying slip, edit that one; if it was cancelled "
                "and is real again, cancel the old row first."))


def _shape_problems(direction, cheque_no, cheque_date, amount_paise, allocations) -> None:
    for problem in (
        P.cheque_no_problem(cheque_no),
        None if P.as_date(cheque_date) else "The cheque needs the date written on it.",
        (None if isinstance(amount_paise, int) and not isinstance(amount_paise, bool)
         and amount_paise > 0 else "The amount is a positive number of paise."),
        P.allocations_problem(direction, allocations or [], amount_paise
                              if isinstance(amount_paise, int) else 0),
    ):
        if problem:
            raise HTTPException(status_code=422, detail=problem)


# ── Writes ───────────────────────────────────────────────────────────────────

def create(db, firm_id: str, client_id: str, *, direction: str,
           customer_id: Optional[str], vendor_id: Optional[str], cheque_no: str,
           cheque_date: str, amount_paise: int, drawee_bank: Optional[str],
           bank_account_id: Optional[str], allocations: list[dict],
           notes: Optional[str], actor: Optional[dict] = None, today=None) -> dict:
    """Record a cheque. Posts nothing, reserves nothing."""
    problem = P.party_problem(direction, customer_id, vendor_id)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    _shape_problems(direction, cheque_no, cheque_date, amount_paise, allocations)
    party_id = customer_id if direction == P.RECEIVED else vendor_id
    _check_party(db, firm_id, client_id, direction, customer_id, vendor_id)
    _check_bank_account(db, firm_id, client_id, bank_account_id)
    _check_documents(db, firm_id, client_id, direction, party_id, allocations or [])
    _check_not_a_duplicate(db, client_id, direction, party_id, cheque_no)
    try:
        # One statement with literal keys (the schema guard reads them).
        saved = (db.table("post_dated_cheques").insert({
            "firm_id": firm_id, "client_id": client_id, "direction": direction,
            "customer_id": customer_id if direction == P.RECEIVED else None,
            "vendor_id": vendor_id if direction == P.ISSUED else None,
            "cheque_no": P.normalise_cheque_no(cheque_no),
            "cheque_date": P.as_date(cheque_date).isoformat(),
            "amount_paise": int(amount_paise),
            "drawee_bank": (drawee_bank or "").strip() or None,
            "bank_account_id": bank_account_id or None,
            "allocations": P.clean_allocations(direction, allocations or []),
            "status": P.HELD, "notes": (notes or "").strip() or None,
            "created_by": (actor or {}).get("id"),
        }).execute().data) or []
    except Exception as e:
        if _is_unique_violation(e):
            # The pre-check above lost a race with another request.
            raise HTTPException(status_code=409, detail=(
                "That cheque number was just recorded for this party.")) from e
        raise
    row = saved[0]
    _audit(firm_id, row["id"], "create", actor,
           {"direction": direction, "cheque_no": row.get("cheque_no"),
            "cheque_date": row.get("cheque_date"), "amount_paise": int(amount_paise)})
    return P.register_row(row, today or ist_today())


def update(db, firm_id: str, client_id: str, cheque_id: str, changes: dict,
           actor: Optional[dict] = None, today=None) -> dict:
    """Correct a cheque that is still HELD. The direction and the party are not
    editable: a cheque recorded against the wrong party is cancelled and entered
    again, which keeps the register honest about what was once on it."""
    current = _get(db, firm_id, client_id, cheque_id)
    if current["status"] != P.HELD:
        raise HTTPException(status_code=409, detail=(
            f"This cheque is {current['status']} and can no longer be edited."))
    direction = current["direction"]
    party_id = current["customer_id"] if direction == P.RECEIVED else current["vendor_id"]

    def pick(key):
        return changes[key] if key in changes else current.get(key)

    cheque_no, cheque_date = pick("cheque_no"), pick("cheque_date")
    amount_paise, allocations = pick("amount_paise"), pick("allocations") or []
    bank_account_id = pick("bank_account_id")
    _shape_problems(direction, cheque_no, cheque_date, amount_paise, allocations)
    if "bank_account_id" in changes:
        _check_bank_account(db, firm_id, client_id, bank_account_id)
    if "allocations" in changes:
        _check_documents(db, firm_id, client_id, direction, party_id, allocations)
    if "cheque_no" in changes:
        _check_not_a_duplicate(db, client_id, direction, party_id, cheque_no, except_id=cheque_id)
    saved = (db.table("post_dated_cheques").update({
        "cheque_no": P.normalise_cheque_no(cheque_no),
        "cheque_date": P.as_date(cheque_date).isoformat(),
        "amount_paise": int(amount_paise),
        "drawee_bank": (pick("drawee_bank") or "").strip() or None,
        "bank_account_id": bank_account_id or None,
        "allocations": P.clean_allocations(direction, allocations),
        "notes": (pick("notes") or "").strip() or None,
        "updated_at": _now(),
    }).eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("status", P.HELD).execute().data) or []
    if not saved:
        raise HTTPException(status_code=409, detail=(
            "This cheque was converted or cancelled while you were editing it."))
    _audit(firm_id, cheque_id, "update", actor, {"changed": sorted(changes)})
    return P.register_row(saved[0], today or ist_today())


def cancel(db, firm_id: str, client_id: str, cheque_id: str, reason: Optional[str],
           actor: Optional[dict] = None, today=None) -> dict:
    """Cancel a cheque that is still HELD (returned by the customer, replaced,
    never banked). Posts nothing — there was nothing posted to take back."""
    current = _get(db, firm_id, client_id, cheque_id)
    if current["status"] != P.HELD:
        raise HTTPException(status_code=409, detail=(
            "This cheque has already been converted into a receipt or payment; reverse that "
            "document on its own screen." if current["status"] == P.CONVERTED
            else "This cheque is already cancelled."))
    saved = (db.table("post_dated_cheques").update({
        "status": P.CANCELLED, "cancelled_at": _now(),
        "cancel_reason": (reason or "").strip() or None, "updated_at": _now(),
    }).eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("status", P.HELD).execute().data) or []
    if not saved:
        raise HTTPException(status_code=409, detail="This cheque has just been converted.")
    _audit(firm_id, cheque_id, "cancel", actor, {"reason": (reason or "").strip() or None})
    return P.register_row(saved[0], today or ist_today())


def convert(db, firm_id: str, client_id: str, cheque_id: str, *, presented_on=None,
            actor: Optional[dict] = None, today=None, engine_db=None) -> dict:
    """Turn a DUE cheque into an ordinary receipt (received) or vendor payment
    (issued), through the one engine for each. Nothing else writes the books.

    TWO CLIENTS, ON PURPOSE. `db` is the privileged client the register's own
    table needs (its writes are service-role-only by grant, migration 460).
    `engine_db` is what the receipt or payment engine is handed, and the router
    passes the REQUEST-scoped client — the caller's own, so row-level security
    applies to the receipt, its allocations and the invoice exactly as it does for
    a receipt typed on the Receipts screen and for the bank match queue, which hands
    the same engines the same client. Handing the engine the privileged one would
    quietly take that defence in depth off every converted cheque. None means "the
    same client", which is what the tests and a deployment without per-user JWTs
    have."""
    today = today or ist_today()
    engine_db = engine_db if engine_db is not None else db
    row = _get(db, firm_id, client_id, cheque_id)
    when = P.presented_on_for(presented_on, today)
    if when is None:
        raise HTTPException(status_code=422, detail="presented_on is not a date.")
    problem = P.conversion_problem(status=row["status"], cheque_date=row["cheque_date"],
                                   presented_on=when, today=today)
    if problem:
        raise HTTPException(status_code=409, detail=problem)

    # CLAIM FIRST. Only the click that wins this compare-and-set calls the engine.
    claimed = (db.table("post_dated_cheques").update({
        "status": P.CONVERTED, "converted_at": _now(),
        "converted_by": (actor or {}).get("id"), "updated_at": _now(),
    }).eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("status", P.HELD).execute().data) or []
    if not claimed:
        raise HTTPException(status_code=409, detail=(
            "This cheque has just been converted or cancelled."))

    direction, data = P.engine_payload(row=row, presented_on=when, client_id=client_id)
    try:
        if direction == P.RECEIVED:
            from services import receipt_service
            document = receipt_service.create_receipt_core(firm_id, data, actor or {}, engine_db)
        else:
            from services import purchase_payment_service
            document = purchase_payment_service.create_payment_core(
                firm_id, data, actor or {}, engine_db)
    except Exception:
        # The engine refused (a closed year, an over-allocation, an inactive
        # party) or failed: nothing was posted, so the cheque goes back to HELD
        # for the CA to fix the cause and try again.
        (db.table("post_dated_cheques").update({
            "status": P.HELD, "converted_at": None, "converted_by": None,
            "updated_at": _now(),
        }).eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", P.CONVERTED).execute())
        raise

    document_id = document.get("id")
    try:
        linked = (db.table("post_dated_cheques").update({
            "converted_receipt_id": document_id if direction == P.RECEIVED else None,
            "converted_payment_id": document_id if direction == P.ISSUED else None,
            "updated_at": _now(),
        }).eq("id", cheque_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    except Exception as e:                               # pragma: no cover - logged, never raised
        # The document EXISTS and is in the books; only the pointer back to it
        # is missing. Undoing the conversion here would leave a receipt the
        # register does not know about and a cheque offered for conversion
        # again, which is the double posting this order of steps prevents.
        _logger.error("cheque %s converted to %s %s but the link was not written: %s",
                      cheque_id, direction, document_id, e)
        linked = []
    final = linked[0] if linked else {**row, "status": P.CONVERTED}
    _audit(firm_id, cheque_id, "convert", actor,
           {"direction": direction, "document_id": document_id,
            "presented_on": when.isoformat(), "amount_paise": int(row["amount_paise"])})
    shown = P.register_row(final, today)
    # Whether it WAS stale is a fact about the cheque as it stood when it was
    # presented; a converted row is never called stale, so it is read off the row
    # as fetched, before the claim.
    stale_note = P.register_row(row, today).get("stale_note")
    stamped = payment_account.stamp(dict(document))
    return {
        "cheque": shown,
        "document": {
            "kind": "receipt" if direction == P.RECEIVED else "payment",
            "id": document_id,
            "number": document.get("receipt_no") or document.get("payment_no"),
            "date": when.isoformat(),
            "amount_paise": int(row["amount_paise"]),
            "journal_entry_id": document.get("journal_entry_id"),
            "unallocated_paise": document.get("unallocated_paise"),
            payment_account.NOTICE_KEY: stamped.get(payment_account.NOTICE_KEY),
        },
        "stale_note": stale_note,
    }
