"""Which lot the stock came from, and when it goes off (INV-03a, migration 398).

WHAT A BATCH IS

A traceability and expiry device: which lot is in stock, when it expires, and
what to pull if there is a recall. For a pharmaceutical, food or chemical
client this is the difference between "we have 400 units" and "we have 400
units of which 120 expire next month".

WHAT A BATCH IS NOT, AND THIS IS THE LINE THAT MATTERS

It is NOT a cost formula. AS-2 paragraph 14 permits FIFO or weighted average,
and migration 394 made the choice between them a property of the client's
inventories (paragraph 16) that no caller may override. Paragraph 13's SPECIFIC
IDENTIFICATION — costing an issue at the cost of the particular batch issued —
is a THIRD formula, and it is the one a batch column silently invites. Applying
it here would give a client a closing stock figure, and therefore a profit,
that their own accounting policy note does not describe. So `record_stock_out`
is untouched: the cost of an issue is still the client's own formula, and the
batch says only which lot left.

Named rather than half-built. AS-2 paragraph 14 does require specific
identification for goods that are not ordinarily interchangeable, so a client
who genuinely needs it needs a THIRD policy value and the same
`switch_refusal` machinery migration 394 built — a decision, not an extension.

EXPIRY IS A DATE, NOT A JOURNAL

Stock past its date is written off through the adjustment path that already
exists, which is also where CGST s.17(5)(h) is asked — credit on goods "lost,
stolen, destroyed, written off or disposed of by way of gift or free samples"
must be reversed (INV-06). This module reports what is expiring; it posts
nothing and reverses nothing.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

#: The buckets an expiry report answers in, in the order a CA reads them.
#: DAYS rather than months, because a shelf life is quoted in days and the
#: question ("what do I have to move this month") is a day count.
EXPIRED = "expired"
WITHIN_30 = "within_30_days"
WITHIN_90 = "within_90_days"
LATER = "later"
NO_EXPIRY_RECORDED = "no_expiry_recorded"

BUCKETS = (EXPIRED, WITHIN_30, WITHIN_90, LATER, NO_EXPIRY_RECORDED)

BUCKET_LABELS = {
    EXPIRED: "Already expired",
    WITHIN_30: "Expires within 30 days",
    WITHIN_90: "Expires within 90 days",
    LATER: "Expires later",
    NO_EXPIRY_RECORDED: "No expiry date recorded",
}

#: A BATCH WITH NO DATE IS ITS OWN ANSWER, never folded into "later". Plenty of
#: stock does not expire at all, and plenty more expires and nobody wrote the
#: date down — and those are opposite situations. "Later" would tell a CA the
#: stock is sound; this tells them nobody knows.
NO_EXPIRY_MEANS = (
    "No expiry date is recorded for these batches. That is not the same as "
    "stock that does not expire: one needs nothing and the other needs "
    "somebody to look at the carton. Record the date, or record that the item "
    "has none."
)

EXPIRED_STOCK_IS_A_WRITE_OFF = (
    "Stock past its expiry date is still on the books at cost until it is "
    "written off. The write-off goes through the stock adjustment, which is "
    "also where CGST s.17(5)(h) is asked — the input tax credit on goods "
    "written off must be reversed. Nothing here posts it."
)

SPECIFIC_IDENTIFICATION_NOT_A_COST_FORMULA = (
    "A batch records WHICH lot moved; it does not change what the movement "
    "cost. AS-2 paragraph 14 permits FIFO or weighted average and this client's "
    "choice between them is their accounting policy (paragraph 16); costing an "
    "issue at its own batch's cost is paragraph 13's specific identification, a "
    "third formula, and applying it silently would give a closing stock figure "
    "the client's own policy note does not describe."
)


@dataclass(frozen=True)
class BatchPosition:
    """One lot in stock, as at a date."""
    batch_id: Optional[str]
    batch_no: Optional[str]
    service_catalogue_id: str
    item_name: str
    quantity: Decimal
    value_paise: int
    expiry_date: Optional[date] = None
    godown_id: Optional[str] = None
    godown_name: Optional[str] = None


def bucket_for(expiry: Optional[date], as_of: date) -> str:
    """Which bucket a batch falls in.

    ON the expiry date the stock is NOT yet expired — a shelf life runs to the
    end of the stated day, so "expires 30 September" means it is good on the
    30th. Reading it the other way writes off a day of sound stock, which is a
    real cost and a wrong §17(5)(h) reversal.
    """
    if expiry is None:
        return NO_EXPIRY_RECORDED
    if expiry < as_of:
        return EXPIRED
    if expiry <= as_of + timedelta(days=30):
        return WITHIN_30
    if expiry <= as_of + timedelta(days=90):
        return WITHIN_90
    return LATER


@dataclass
class ExpiryReport:
    as_of: date
    buckets: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "bucket_order": list(BUCKETS),
            "bucket_labels": dict(BUCKET_LABELS),
            "buckets": {b: dict(v) for b, v in self.buckets.items()},
            "rows": list(self.rows),
            "notes": list(self.notes),
        }


def expiry_report(positions: Iterable[BatchPosition], *, as_of: date) -> ExpiryReport:
    """What is expiring, and what has.

    ONLY STOCK THAT IS ACTUALLY THERE. A batch fully issued has nothing to
    expire, and listing it would put a CA on the phone about goods that left
    months ago. A NEGATIVE quantity is kept and shown, because that is a real
    defect in the records rather than an absence — it means more was issued
    than was ever received into that lot.
    """
    out = ExpiryReport(as_of=as_of)
    out.buckets = {b: {"quantity": "0", "value_paise": 0, "batches": 0} for b in BUCKETS}
    seen_no_date = False
    seen_expired = False

    for pos in positions:
        if pos.quantity == 0:
            continue
        bucket = bucket_for(pos.expiry_date, as_of)
        slot = out.buckets[bucket]
        slot["quantity"] = str(Decimal(slot["quantity"]) + pos.quantity)
        slot["value_paise"] += int(pos.value_paise)
        slot["batches"] += 1
        if bucket == NO_EXPIRY_RECORDED:
            seen_no_date = True
        if bucket == EXPIRED:
            seen_expired = True
        out.rows.append({
            "batch_id": pos.batch_id,
            "batch_no": pos.batch_no,
            "service_catalogue_id": pos.service_catalogue_id,
            "item_name": pos.item_name,
            "godown_id": pos.godown_id,
            "godown_name": pos.godown_name,
            "quantity": str(pos.quantity),
            "value_paise": int(pos.value_paise),
            "expiry_date": pos.expiry_date.isoformat() if pos.expiry_date else None,
            "bucket": bucket,
            "days_to_expiry": ((pos.expiry_date - as_of).days
                               if pos.expiry_date else None),
        })

    # Soonest first, and a batch with no date last — it is the one nobody can
    # act on until somebody looks at the carton.
    out.rows.sort(key=lambda r: (r["expiry_date"] is None,
                                 r["expiry_date"] or "",
                                 r["item_name"], r["batch_no"] or ""))
    if seen_expired:
        out.notes.append(EXPIRED_STOCK_IS_A_WRITE_OFF)
    if seen_no_date:
        out.notes.append(NO_EXPIRY_MEANS)
    out.notes.append(SPECIFIC_IDENTIFICATION_NOT_A_COST_FORMULA)
    return out


def first_expiry_first_out(positions: Iterable[BatchPosition]) -> list:
    """The batches in the order a store SHOULD issue them.

    SUGGESTED, NEVER APPLIED. This is a picking order — which carton to take
    off the shelf — and not a cost formula: what an issue costs is the client's
    own AS-2 paragraph 14 policy, and forcing an order here would change their
    closing stock. A batch with no recorded expiry sorts LAST rather than
    first: there is nothing urgent about it that anybody has established.
    """
    live = [p for p in positions if p.quantity > 0]
    return sorted(live, key=lambda p: (p.expiry_date is None,
                                       p.expiry_date or date.max,
                                       p.batch_no or ""))
