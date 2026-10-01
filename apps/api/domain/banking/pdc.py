"""The post-dated cheque register: what is due, what is stale, and what may be
converted (accounting-21, migration 460).

READ THIS FIRST: A POST-DATED CHEQUE IS A MEMORANDUM, NOT A TRANSACTION.
Until its date it is a promise on a piece of paper; recording it as a receipt
would put money in the bank ledger that is not in the bank and settle an invoice
with a cheque that has not cleared. So the register posts NOTHING — it has no
journal column — and this module reads no database and writes none. Converting a
due cheque hands it to the ordinary receipt / vendor-payment engine
(`services/receipt_service.create_receipt_core`,
`services/purchase_payment_service.create_payment_core`), which is also what the
bank match queue calls; there is no second posting path.

WHAT IS DERIVED AND NEVER STORED. `status` holds three things — held, converted,
cancelled — because those are events somebody did. "Due" and "stale" are
functions of the cheque's date and TODAY, so a stored flag would be wrong by the
next morning; `state_of` and `is_stale` are answered on every read.

DUE MEANS ON OR AFTER THE CHEQUE'S OWN DATE. A cheque dated 15 November can be
presented on the 15th, so it is due that day, not the next. Until then it cannot
be converted: the refusal says when it falls due.

STALE IS A WARNING AND NEVER A REFUSAL. A cheque is valid for three months from
its date (RBI, from 1 April 2012) and a bank returns one presented after that,
which is worth the CA's attention. But converting records a fact — "this money
arrived" — and a CA who holds proof the bank honoured an old cheque must still be
able to record it; refusing would push the entry outside the product, which is
worse than a warning nobody read. Graded `[S]`: egress is refused here, so the
validity period could not be read against the RBI circular.

THE DATE OF THE RECEIPT IS THE DAY THE CHEQUE WAS PRESENTED, not the date
printed on it. It defaults to today (IST), may not be before the cheque's own
date and may not be in the future. The period locks (a closed year, a filed
return where a receipt feeds one) are the receipt engine's to ask, at that date,
exactly as for a receipt typed on the Receipts screen.

THE ALLOCATIONS ARE INTENT, NOT A CLAIM. They name the invoices (or bills) the
cheque is meant for, in the engine's own shape; nothing is reserved against the
invoice, and the engine re-validates each against the LIVE outstanding when the
cheque is converted. Only their SHAPE is checked here.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from domain.recurrence import add_months_clamped

RECEIVED = "received"
ISSUED = "issued"
DIRECTIONS = (RECEIVED, ISSUED)

HELD = "held"
CONVERTED = "converted"
CANCELLED = "cancelled"
STATUSES = (HELD, CONVERTED, CANCELLED)

# What the register shows. `not_due` and `due` are both HELD; the difference is
# the date and today.
NOT_DUE = "not_due"
DUE = "due"

#: RBI: a cheque is valid for three months from its date. `[S]`.
CHEQUE_VALIDITY_MONTHS = 3
VALIDITY_GRADE = "[S]"
STALE_SENTENCE = (
    "This cheque is dated more than three months ago. A cheque is valid for three "
    "months from its date (RBI, from 1 April 2012; graded [S], not read against the "
    "circular here), so the bank may return it unpaid. If the bank did honour it, "
    "record it; if it did not, ask for a fresh cheque and cancel this one.")

#: The engine's own key for the document an allocation points at.
ALLOCATION_KEY = {RECEIVED: "sales_invoice_id", ISSUED: "purchase_bill_id"}
PARTY_COLUMN = {RECEIVED: "customer_id", ISSUED: "vendor_id"}

#: Written into the receipt's / payment's own notes, so the ledger drill-through
#: can say where it came from. `payment_mode` is `cheque`, a value migration 050's
#: CHECK on both tables allows.
PAYMENT_MODE = "cheque"


def as_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def is_due(cheque_date, today: date) -> bool:
    """On or after the cheque's own date."""
    d = as_date(cheque_date)
    return d is not None and today >= d


def stale_after(cheque_date) -> Optional[date]:
    """The last day a cheque is good: three calendar months after its date."""
    d = as_date(cheque_date)
    return None if d is None else add_months_clamped(d, CHEQUE_VALIDITY_MONTHS)


def is_stale(cheque_date, today: date) -> bool:
    """Presented after the three months are up. A cheque dated 15 Nov is still
    good on 15 Feb and stale from the 16th."""
    last = stale_after(cheque_date)
    return last is not None and today > last


def state_of(status: str, cheque_date, today: date) -> str:
    """held -> not_due | due; converted and cancelled are what they say."""
    if status != HELD:
        return status
    return DUE if is_due(cheque_date, today) else NOT_DUE


# ── Shape checks on what a person typed ──────────────────────────────────────

def party_problem(direction: str, customer_id, vendor_id) -> Optional[str]:
    """A received cheque is a CUSTOMER's and an issued one a VENDOR's. The table
    CHECKs the same thing; this is the sentence."""
    if direction not in DIRECTIONS:
        return "A cheque is either received (from a customer) or issued (to a supplier)."
    if direction == RECEIVED:
        if not customer_id or vendor_id:
            return "A cheque received names the customer who gave it, and no supplier."
    else:
        if not vendor_id or customer_id:
            return "A cheque issued names the supplier it was given to, and no customer."
    return None


def allocations_problem(direction: str, allocations: Iterable[dict],
                        amount_paise: int) -> Optional[str]:
    """The SHAPE of the intended allocations: the right document key for the
    direction, a positive whole-paise amount each, no document twice, and no more
    than the cheque. Whether each document is open and how much it still owes is
    the engine's to say at conversion."""
    key = ALLOCATION_KEY.get(direction)
    seen: set[str] = set()
    total = 0
    for a in allocations:
        doc = a.get(key)
        if not doc:
            return (f"Each allocation names its {'invoice' if direction == RECEIVED else 'bill'} "
                    f"({key}).")
        if doc in seen:
            return "The same document is listed twice; combine the amounts into one line."
        seen.add(doc)
        amt = a.get("allocated_paise")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            return "Each allocation is a positive whole number of paise."
        total += amt
    if total > int(amount_paise):
        return (f"The allocations add up to more than the cheque ({total} paise against "
                f"{int(amount_paise)}).")
    return None


def clean_allocations(direction: str, allocations: Iterable[dict]) -> list[dict]:
    """Only the engine's two keys survive, so nothing else rides along into the
    column or the engine."""
    key = ALLOCATION_KEY[direction]
    return [{key: a[key], "allocated_paise": int(a["allocated_paise"])} for a in allocations]


def cheque_no_problem(cheque_no) -> Optional[str]:
    if not str(cheque_no or "").strip():
        return "A cheque needs its number: it is how one cheque is told from the next."
    return None


def normalise_cheque_no(cheque_no) -> str:
    return " ".join(str(cheque_no or "").split())


# ── Conversion ───────────────────────────────────────────────────────────────

def presented_on_for(presented_on, today: date) -> date:
    """The receipt's date: the day it was presented, defaulting to today."""
    return as_date(presented_on) if presented_on else today


def conversion_problem(*, status: str, cheque_date, presented_on: date,
                       today: date) -> Optional[str]:
    """The sentence when this cheque may NOT become a receipt or payment yet, or
    None. Order matters: what has already happened outranks what is merely early."""
    if status == CONVERTED:
        return "This cheque has already been converted. Its receipt or payment is on the register."
    if status == CANCELLED:
        return "This cheque was cancelled, so it cannot be converted. Record it again if it is real."
    d = as_date(cheque_date)
    if d is None:
        return "This cheque has no date to fall due on."
    if today < d:
        return (f"This cheque is dated {d.isoformat()} and is not due until then. A "
                "post-dated cheque is a memorandum until its date: it posts nothing, "
                "so there is nothing to convert yet.")
    if presented_on < d:
        return (f"A cheque dated {d.isoformat()} cannot have been presented on "
                f"{presented_on.isoformat()}, before its own date.")
    if presented_on > today:
        return (f"{presented_on.isoformat()} is in the future. Record the day the cheque "
                "was actually presented.")
    return None


def engine_notes(*, direction: str, cheque_no: str, cheque_date, drawee_bank,
                 notes) -> str:
    """The text the receipt / payment carries about where it came from."""
    d = as_date(cheque_date)
    where = f" drawn on {drawee_bank.strip()}" if (drawee_bank or "").strip() else ""
    head = (f"Post-dated cheque {normalise_cheque_no(cheque_no)}{where}, dated "
            f"{d.isoformat() if d else '—'}, "
            f"{'received' if direction == RECEIVED else 'issued'}; converted from the "
            "post-dated cheque register.")
    extra = (notes or "").strip()
    return f"{head} {extra}".strip()


def engine_payload(*, row: dict, presented_on: date, client_id: str) -> tuple[str, dict]:
    """(`received` | `issued`, the dict the matching engine takes).

    The SAME keys `BankPostingService.match_and_settle_multi` hands those engines:
    that is the point — the cheque reaches the books by the door every other
    settlement does. Nothing here is computed: the amount is the cheque's, the
    allocations are the stored intent, and the engine does the rest."""
    direction = row["direction"]
    allocations = clean_allocations(direction, row.get("allocations") or [])
    reference = normalise_cheque_no(row["cheque_no"])
    notes = engine_notes(direction=direction, cheque_no=row["cheque_no"],
                         cheque_date=row["cheque_date"], drawee_bank=row.get("drawee_bank"),
                         notes=row.get("notes"))
    if direction == RECEIVED:
        return direction, {
            "client_id": client_id, "customer_id": row["customer_id"],
            "receipt_date": presented_on.isoformat(), "amount_paise": int(row["amount_paise"]),
            "tds_paise": 0, "payment_mode": PAYMENT_MODE, "reference_no": reference,
            "notes": notes, "allocations": allocations,
            "bank_account_id": row.get("bank_account_id"),
        }
    return direction, {
        "client_id": client_id, "vendor_id": row["vendor_id"],
        "payment_date": presented_on.isoformat(), "amount_paise": int(row["amount_paise"]),
        "payment_mode": PAYMENT_MODE, "reference_no": reference,
        "notes": notes, "allocations": allocations,
        "bank_account_id": row.get("bank_account_id"),
    }


# ── The register as a worklist ───────────────────────────────────────────────

def register_row(row: dict, today: date) -> dict:
    """One stored cheque with the derived facts a screen shows."""
    state = state_of(row.get("status") or HELD, row.get("cheque_date"), today)
    held = row.get("status") == HELD
    stale = held and is_stale(row.get("cheque_date"), today)
    return {**row, "state": state, "is_due": state == DUE,
            "is_stale": stale, "stale_note": STALE_SENTENCE if stale else None,
            "stale_after": (stale_after(row.get("cheque_date")).isoformat()
                            if stale_after(row.get("cheque_date")) else None)}


def sort_key(r: dict):
    """Due cheques first, oldest date at the top (the one most overdue for the
    bank); then what is still to come, soonest first; then what is finished."""
    order = {DUE: 0, NOT_DUE: 1, CONVERTED: 2, CANCELLED: 3}
    return (order.get(r["state"], 9), str(r.get("cheque_date") or ""), str(r.get("cheque_no") or ""))


def summarise(rows: list[dict]) -> dict:
    """What is waiting, by direction and by state, in integer paise."""
    out = {d: {s: {"count": 0, "amount_paise": 0} for s in (DUE, NOT_DUE, CONVERTED, CANCELLED)}
           for d in DIRECTIONS}
    for r in rows:
        bucket = out.get(r.get("direction"), {}).get(r["state"])
        if bucket is not None:
            bucket["count"] += 1
            bucket["amount_paise"] += int(r.get("amount_paise") or 0)
    return out
