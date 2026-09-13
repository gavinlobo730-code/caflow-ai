"""What an ageing report OWES the control account: the unapplied advances.

An AR or AP ageing report that lists only OPEN DOCUMENTS cannot be tied to
its control account, and the gap is exactly the money that has moved without
a document to sit against — a payment made to a supplier before the bill
arrives, or a receipt taken from a customer before the invoice is raised.

`ap_aging` and `ar_aging` each summed their open documents and stopped there
(PUR-24). The vendor and customer STATEMENTS, by contrast, debit or credit
every payment and receipt, so the statement's closing balance and the ageing
total legitimately disagreed the moment an advance existed — and the figure a
CA needs, the one that ties to Trade Payables or Trade Receivables, was
neither of them.

WHICH FIGURE IS AUTHORITATIVE. `purchase_payments.unallocated_paise` and
`receipts.unallocated_paise` (migrations 226 and 050) are maintained on every
path that can change them:

  • `purchase_payment_service.create_payment_core` and `receipt_service`
    write `settlement − Σ allocated` at creation;
  • `allocate_payment` rewrites it when an advance is applied later;
  • `routers/purchase_payments.py` writes `0` when the payment names a bill
    and the whole amount when it does not — the single-bill path, which has
    no allocation rows at all.

That last one is why the column is READ rather than DERIVED. Deriving the
advance as `settlement − Σ allocations` looks more careful and is WRONG for
every single-bill payment: there are no allocation rows, so the derivation
returns the whole payment as an advance on money that discharged a bill. The
derivation is used only as a CROSS-CHECK, and only where allocation rows
actually exist; a disagreement is NAMED (`gaps`) rather than absorbed, the
same discipline `fixed_asset_movement` uses when the ledger and the register
differ.

WHAT IS DELIBERATELY NOT DONE HERE.

  • An advance is NOT added into the document buckets. A supplier advance is
    an ASSET and a customer advance a LIABILITY; folding either into the
    payables or receivables ageing would misstate the very note it exists to
    reconcile. They are their own section with their own total.
  • These buckets are NOT the Schedule III ageing columns. `domain/reporting/
    ageing.py` holds those, and they are a different shape on purpose —
    receivables age in five columns from six months, payables in four from
    one year (MCA G.S.R. 207(E), 24-03-2021). The buckets here are the
    OPERATIONAL ones a collections or payments run is worked from. Do not
    reconcile one to the other.
  • No foreign-currency split. `unallocated_paise` is a BASE-currency figure
    (`purchase_payment_service` writes `unalloc_base`) and there is no stored
    transaction-currency counterpart, so an advance carries its base amount
    and its currency label and nothing more. The ageing's `by_currency`
    block reconciles to the DOCUMENT total and advances stay out of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Optional, Sequence

# The operational ageing buckets, in presentation order. One definition:
# `vendor_statement_service`, `customer_statement_service` and
# `collections_service` each carried an identical private copy of the
# function below, which is three places for one rule to drift in.
BUCKET_KEYS: tuple[str, ...] = ("not_due", "0-30", "31-60", "61-90", "90+")


def aging_bucket(days_overdue: int) -> str:
    """The operational bucket a document or advance falls in.

    NOT the Schedule III columns — see the module docstring. `days_overdue`
    is measured from the due date where a document has one and from the
    document date where it does not; for an advance there is no due date, so
    it is measured from the payment or receipt date and means AGE, not
    lateness.
    """
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "0-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


def empty_buckets() -> dict[str, int]:
    return {k: 0 for k in BUCKET_KEYS}


@dataclass(frozen=True)
class AdvanceInput:
    """One payment or receipt, already fetched and normalised by the caller.

    `settlement_paise` is what the document relieved in total — for a customer
    receipt that is cash PLUS the tax the customer withheld (IT Act §198/§199,
    see CLAUDE.md), which is why the caller passes it rather than this module
    reading `amount_paise`.

    `allocated_paise` is `None` when the document has no allocation rows at
    all. None and 0 mean different things here and must not be collapsed:
    None is "this document was never allocated through the bridge table", 0
    is "it was, and nothing is applied".
    """
    document_id: str
    document_no: Optional[str]
    party_id: Optional[str]
    party_name: Optional[str]
    document_date: Optional[str]
    settlement_paise: int
    unallocated_paise: int
    allocated_paise: Optional[int] = None
    currency: str = "INR"


@dataclass(frozen=True)
class AdvancePosition:
    advances: list[dict] = field(default_factory=list)
    total_paise: int = 0
    buckets: dict[str, int] = field(default_factory=empty_buckets)
    gaps: list[str] = field(default_factory=list)


def _age_days(document_date: Optional[str], today: date) -> int:
    if not document_date:
        return 0
    try:
        return (today - date.fromisoformat(str(document_date)[:10])).days
    except (ValueError, TypeError):
        return 0


def unapplied_advances(
    rows: Sequence[AdvanceInput | Mapping],
    *,
    today: date,
    document_label: str = "document",
) -> AdvancePosition:
    """The unapplied portion of every payment or receipt, aged and totalled.

    `document_label` names the thing in a gap sentence ("payment VPMT-2526-0007
    …") so one message serves both sides without the reader having to guess
    which ledger it came from.
    """
    advances: list[dict] = []
    buckets = empty_buckets()
    gaps: list[str] = []
    total = 0

    for raw in rows:
        row = raw if isinstance(raw, AdvanceInput) else AdvanceInput(**dict(raw))
        stored = int(row.unallocated_paise or 0)
        ref = row.document_no or row.document_id

        # OVER-ALLOCATED. A negative unapplied balance means the allocations
        # claim more than the document settled. Treated as nil (a negative
        # advance is not a thing) and NAMED, because the arithmetic that
        # produced it is wrong somewhere upstream and silently clamping is how
        # that stays hidden.
        if stored < 0:
            gaps.append(
                f"{document_label.capitalize()} {ref} has an unapplied balance of "
                f"{stored} paise — allocations exceed what it settled. Reported as nil; "
                f"the allocation rows need correcting."
            )
            stored = 0

        # THE CROSS-CHECK, and only where the bridge table was actually used.
        # See the module docstring: on the single-bill path there are no
        # allocation rows and the derivation would call the whole payment an
        # advance.
        if row.allocated_paise is not None:
            derived = int(row.settlement_paise or 0) - int(row.allocated_paise or 0)
            if derived != stored:
                gaps.append(
                    f"{document_label.capitalize()} {ref}: the stored unapplied balance is "
                    f"{stored} paise but its allocation rows imply {derived} paise. "
                    f"The stored figure is reported; the two need reconciling."
                )

        if stored <= 0:
            continue

        days = _age_days(row.document_date, today)
        bucket = aging_bucket(days)
        buckets[bucket] += stored
        total += stored
        entry = {
            "document_id": row.document_id,
            "document_no": row.document_no,
            "party_id": row.party_id,
            "party_name": row.party_name,
            "document_date": (str(row.document_date)[:10] if row.document_date else None),
            "unapplied_paise": stored,
            "days_old": max(days, 0),
            "aging_bucket": bucket,
        }
        cur = (row.currency or "INR").upper()
        if cur != "INR":
            # Label only — there is no stored transaction-currency counterpart
            # to `unallocated_paise`, and inventing one by re-dividing by the
            # rate would put a float in a paise figure.
            entry["txn_currency"] = cur
        advances.append(entry)

    advances.sort(key=lambda a: (a["document_date"] or "", str(a["document_no"] or "")))
    return AdvancePosition(advances=advances, total_paise=total, buckets=buckets, gaps=gaps)
