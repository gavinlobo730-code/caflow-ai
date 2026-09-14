"""What else the goods cost to get here — AS-2 paragraph 6 (INV-05).

WHY THIS EXISTS

`apply_purchase_to_inventory` costs a receipt at the line's taxable value plus
its CGST s.17(5)-blocked tax (INV-05a, closed) and nothing else. AS-2
paragraph 6:

    "The costs of purchase consist of the purchase price including duties and
    taxes (other than those subsequently recoverable by the enterprise from
    the taxing authorities), FREIGHT INWARDS and OTHER EXPENDITURE DIRECTLY
    ATTRIBUTABLE TO THE ACQUISITION of finished goods, materials and services.
    Trade discounts, rebates, duty drawbacks and other similar items are
    deducted in determining the costs of purchase."

So a client who pays to bring a consignment in carries stock at less than it
cost, takes the expense in the month it was billed rather than when the goods
are sold, and — the cost formula running off the same figure — gets every later
COGS wrong too.

THE BASIS IS A POLICY, BECAUSE THE STANDARD DOES NOT GIVE ONE

AS-2 settles what goes IN. It does not say how to split one freight bill across
the lines it covered, and there is no single right split: by value is wrong for
a container of identical t-shirts, by quantity is wrong for 200 chairs and 20
tables. Every product in this tier that has the feature offers BOTH and lets
the user choose — TallyPrime per expense ledger, Zoho Books in a popup on
save, QuickBooks Enterprise per bill. Xero has no landed-cost allocation at
all.

So the basis is an accounting policy: stored on the client and applied
consistently, with a per-bill override for the consignment that differs.
Migration 396. Owner decision of 14-09-2026.

WHAT THIS MODULE REFUSES

  WEIGHT AND VOLUME. The most accurate basis for freight, and not offered:
  `service_catalogue` holds no weight, so it needs a column and a figure typed
  for every stock item first. Named rather than silently absent.

  A SERVICE LINE TAKES NO SHARE. Only goods reach the stock ledger, so a
  charge apportioned over a service line would vanish — the receipt would
  carry less than the charge and the difference would be nobody's.

  A CHARGE WITH NOTHING TO ATTACH TO. A bill of services only, or one whose
  goods lines are all zero on the chosen basis, cannot apportion anything. It
  is reported, never spread over lines that are not there and never silently
  dropped.

  FREIGHT OUTWARD. AS-2 paragraph 13(d) excludes selling and distribution
  costs, so freight on the way OUT is a period expense and not stock cost.
  This module cannot tell one from the other — the description is the CA's —
  so it says so rather than checking.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

#: The two bases, and nothing else. Both of them, because the right answer
#: genuinely differs by consignment and every product that ships this feature
#: offers both.
BY_VALUE = "value"
BY_QUANTITY = "quantity"
BASES = (BY_VALUE, BY_QUANTITY)

BASIS_LABELS = {
    BY_VALUE: "By value — pro-rata on each line's own cost",
    BY_QUANTITY: "By quantity — pro-rata on units",
}

#: What a client with nothing recorded gets. Not an arbitrary pick: it is the
#: basis QuickBooks' own guidance recommends, and the one that cannot be badly
#: wrong on a mixed consignment — where quantity would charge a ₹200 chair and
#: a ₹20,000 table the same freight.
BASIS_WHEN_UNRECORDED = BY_VALUE

UNRECORDED_MEANS = (
    "No basis is recorded for this client, so landed costs are split by value. "
    "AS-2 says what belongs in the cost of purchase and not how to split it "
    "across lines, so this is an accounting policy rather than a figure the "
    "Standard gives — record it to say it was considered."
)

WEIGHT_AND_VOLUME_REFUSED = (
    "Weight and volume are not offered. They are the most accurate basis for "
    "freight specifically, and nothing here holds a weight per item — it would "
    "need a column on the product master and a figure typed for every stock "
    "item before any of it worked. No mainstream product in this tier ships "
    "them either."
)

FREIGHT_OUTWARD_IS_NOT_COST = (
    "AS-2 paragraph 13(d) excludes selling and distribution costs from the "
    "cost of inventories, so freight OUTWARD is an expense of the period and "
    "does not belong here. Only what brought the goods in does."
)

QUANTITY_ASSUMES_ONE_UNIT = (
    "Splitting by quantity adds the lines' quantities together, and "
    "`purchase_bill_lines` records no unit of measure — so a bill mixing "
    "kilograms and pieces is split on a total that means nothing, and nothing "
    "here can detect it. Use value on a consignment of mixed units."
)

RECORDED_AFTER_THE_RECEIPT = (
    "This charge was recorded after the goods were received, so it is NOT in "
    "the cost of the stock. The receipt's journal is posted and a posted entry "
    "cannot be rewritten, so the cost cannot be reopened — raise the "
    "adjustment yourself, or reverse the receipt and receive it again with the "
    "charge in place."
)


def basis_for(client_recorded: Optional[str],
              bill_override: Optional[str] = None) -> str:
    """The basis in force: the bill's own, else the client's, else value.

    The bill wins because it is the narrower statement — the consignment that
    differs from the client's usual is exactly what the override exists for.
    """
    for candidate in (bill_override, client_recorded):
        value = (candidate or "").strip().lower()
        if value in BASES:
            return value
    return BASIS_WHEN_UNRECORDED


def basis_refusal(wanted: str) -> Optional[str]:
    """Why this basis cannot be recorded, or None."""
    if (wanted or "").strip().lower() in BASES:
        return None
    if (wanted or "").strip().lower() in ("weight", "volume"):
        return WEIGHT_AND_VOLUME_REFUSED
    return ("A landed cost is split by value or by quantity. "
            + " ".join(BASIS_LABELS[b] for b in BASES) + " " + WEIGHT_AND_VOLUME_REFUSED)


@dataclass(frozen=True)
class Line:
    """One goods line of the bill, as the apportionment sees it.

    `cost_paise` is the SAME figure the receipt is costed at — taxable value
    plus blocked tax — so the weight and the thing being weighted agree. Using
    the taxable value alone would split a charge over a base the ledger does
    not use.
    """
    line_id: str
    service_catalogue_id: str
    cost_paise: int
    quantity: Decimal


@dataclass
class Apportionment:
    basis: str = BASIS_WHEN_UNRECORDED
    #: line_id -> paise of the charge that line carries.
    by_line: dict = field(default_factory=dict)
    total_paise: int = 0
    #: What could not be apportioned and why. NEVER silently dropped.
    unapportioned_paise: int = 0
    gaps: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "basis": self.basis,
            "basis_label": BASIS_LABELS.get(self.basis, self.basis),
            "by_line": dict(self.by_line),
            "total_paise": self.total_paise,
            "unapportioned_paise": self.unapportioned_paise,
            "gaps": list(self.gaps),
            "notes": list(self.notes),
        }


def apportion(lines, charge_paise: int, *, basis: str) -> Apportionment:
    """Split `charge_paise` across the GOODS lines on the stated basis.

    LARGEST REMAINDER, so the parts sum to the charge EXACTLY — the same
    discipline `domain/gst/discount.py` uses for a document-level discount and
    `domain/inventory/costing.rebase` for a FIFO re-base. A per-line rounding
    would leave a residue that has to go somewhere, and every candidate place
    is wrong: on the last line it distorts that line's cost, in the expense
    account it defeats the whole point.

    `lines` are the goods lines only. A service line never reaches the stock
    ledger, so a share allocated to one would simply disappear.
    """
    out = Apportionment(basis=basis if basis in BASES else BASIS_WHEN_UNRECORDED)
    charge = int(charge_paise)
    if charge <= 0:
        return out
    if out.basis == BY_QUANTITY:
        out.notes.append(QUANTITY_ASSUMES_ONE_UNIT)

    lines = list(lines)
    if not lines:
        out.unapportioned_paise = charge
        out.gaps.append(
            "This bill has no stock-tracked goods lines, so there is nothing "
            "to add the charge to. AS-2 paragraph 6 puts it in the cost of "
            "INVENTORIES; on a bill of services it is an expense of the period.")
        return out

    weights = [_weight_of(line, out.basis) for line in lines]
    if sum(weights) <= 0:
        out.unapportioned_paise = charge
        out.gaps.append(
            f"Every goods line on this bill weighs nothing on the "
            f"{out.basis} basis, so the charge cannot be split. "
            + ("Check the quantities." if out.basis == BY_QUANTITY
               else "Check the line values."))
        return out

    shares = split_pro_rata(charge, weights)
    out.by_line = {line.line_id: shares[i] for i, line in enumerate(lines)
                   if shares[i]}
    out.total_paise = sum(shares)
    return out


def split_pro_rata(amount_paise: int, weights) -> list:
    """`amount_paise` divided in proportion to `weights`, summing EXACTLY.

    LARGEST REMAINDER — the same discipline `domain/gst/discount.py` uses for a
    document-level discount and `domain/inventory/costing.rebase` for a FIFO
    re-base. A per-share rounding leaves a residue that has to go somewhere,
    and every candidate place is wrong: on the last share it distorts that
    line, left over it defeats the point of splitting at all.

    WHERE `amount_paise` EQUALS THE WEIGHTS' TOTAL THE ANSWER IS THE WEIGHTS,
    exactly, with nothing to round — which is what lets the receipt journal use
    this for its ordinary case as well as the oversold one, with no branch and
    so no second path to keep in step.
    """
    weights = [max(Decimal(0), Decimal(str(w or 0))) for w in weights]
    total = sum(weights)
    if amount_paise <= 0 or total <= 0:
        return [0] * len(weights)
    shares, remainders = [], []
    for i, w in enumerate(weights):
        exact = Decimal(int(amount_paise)) * w / total
        whole = int(exact)          # weights are non-negative, so this truncates
        shares.append(whole)
        remainders.append((exact - whole, i))
    residue = int(amount_paise) - sum(shares)
    for _, i in sorted(remainders, key=lambda t: (-t[0], t[1]))[:max(0, residue)]:
        shares[i] += 1
    return shares


def _weight_of(line: "Line", basis: str) -> Decimal:
    if basis == BY_QUANTITY:
        return max(Decimal(0), Decimal(str(line.quantity or 0)))
    return max(Decimal(0), Decimal(int(line.cost_paise or 0)))


def apportion_many(lines, charges, *, basis: str) -> Apportionment:
    """Several charges over the same lines, split one at a time and summed.

    EACH CHARGE IS SPLIT SEPARATELY rather than the total being split once,
    which sounds equivalent and is not: largest-remainder on ₹2,000 and then
    on ₹1,000 does not in general give the same per-line figures as one split
    of ₹3,000, and the separate splits are the ones a CA can check against
    each charge. The totals agree either way — that is what largest remainder
    guarantees — so only the pennies move, and they move to where the working
    shows them.

    `charges` are `(identifier, amount_paise)` pairs. The identifier is carried
    into `per_charge` so the caller can stamp each source row as applied.
    """
    combined = Apportionment(basis=basis if basis in BASES else BASIS_WHEN_UNRECORDED)
    per_charge: dict = {}
    seen_notes: set = set()
    for identifier, amount in charges:
        one = apportion(lines, amount, basis=combined.basis)
        per_charge[identifier] = one
        for line_id, paise in one.by_line.items():
            combined.by_line[line_id] = combined.by_line.get(line_id, 0) + paise
        combined.total_paise += one.total_paise
        combined.unapportioned_paise += one.unapportioned_paise
        for g in one.gaps:
            if g not in combined.gaps:
                combined.gaps.append(g)
        for n in one.notes:
            if n not in seen_notes:
                seen_notes.add(n)
                combined.notes.append(n)
    combined.per_charge = per_charge          # type: ignore[attr-defined]
    return combined
