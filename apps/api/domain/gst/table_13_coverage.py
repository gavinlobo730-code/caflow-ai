"""GSTR-1 Table 13 — what this build looked at, and what it did not (POST-A-415).

WHAT WAS WRONG
    Table 13 has twelve document natures and the builder reads three: invoices
    for outward supply, debit notes and credit notes (`gstr1_builder._NATURE_OF`).
    A client that issued a receipt voucher for an advance, a delivery challan or
    a self-invoice for a supply from an unregistered person filed a return whose
    Table 13 left it out, and nothing on the return said the other nine natures
    had not been looked at. The cancelled count had its own sentence
    (`GAP_CANCELLED_NOT_READ`); these had none.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
    It says what the build did not look at. It does NOT say what the client must
    declare: which natures a given client has to put in Table 13 is a reading of
    the Rules that the owner or a practising CA confirms, and a sentence that
    claimed it would be the confident wrong statement this product exists not to
    make. So every sentence here says "the form lists" and "is for the CA to
    settle", and none says "must", "required" or "liable".

    The one concrete fact it adds is a COUNT, because that is a thing the books
    hold and not a reading: how many delivery challans the client issued in the
    window (issued or received back, not drafts and not cancelled), by the
    reason each was issued for, in the reason's own words. It does not say which
    Table 13 row each belongs in. Rule 55(4) and (5) challans are issued for a
    supply, and whether the form files them under "other than by way of supply"
    is exactly the question nobody here has confirmed from the form's own
    instructions — it is on the owner's list, and the challans are built into
    the table when it is answered.

IT IS NOT A GAP, AND THAT IS A DECISION
    `payload_gaps` is read by three things that mean something specific by it:
    the screen's "validated" status (a return with any gap is saved as a draft),
    the GSTR-3B tie-out (which lists every withheld gap as a document held out
    of the GSTR-1 that explains a difference in taxable value) and the red "not
    declared" count. A sentence that is true of EVERY return would make every
    return a draft for ever, and a delivery challan carries no taxable value to
    explain a difference in. So this is its own field on the result,
    `table_13_coverage`, which the screen renders as a note beside the gaps and
    which changes none of those.

AN UNKNOWN IS NEVER A COUNT
    A read that failed is `read: False` with `count: None` and a sentence saying
    so, never `count: 0`: "none were issued" and "we could not look" are
    different facts and the second is the one a CA has to act on.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from . import delivery_challan as dc


def not_read(all_natures: Sequence[str], declared: Iterable[str]) -> list[str]:
    """The natures the form lists that the builder does not declare, in the form's own order."""
    done = set(declared)
    return [n for n in all_natures if n not in done]


def natures_note(all_natures: Sequence[str], declared: Iterable[str]) -> str:
    """One sentence about the whole table: the natures declared, the natures not looked at, and whose call the rest is."""
    done = set(declared)
    carried = [n for n in all_natures if n in done]
    left = not_read(all_natures, done)
    if not left:
        return ""
    n = len(left)
    return (
        "This build reads " + str(len(carried)) + " "
        + ("nature" if len(carried) == 1 else "natures") + " of document for "
        "Table 13: " + _join(carried) + ". It did not look for the other "
        + str(n) + " " + ("nature" if n == 1 else "natures") + " the form lists: "
        + "; ".join(left) + ". If this client issued any of them in the "
        "period, they are not in this return. Whether they fall to be declared "
        "is for the CA to settle against the form."
    )


def _join(items: Sequence[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else (items[0] if items else "nothing")


#: Said when the challans could not be read, so a missing count is not a nil.
CHALLANS_NOT_READ = (
    "The delivery challans issued in this period could not be read, so whether "
    "any of them is missing from Table 13 is not known."
)

#: Said when the read worked and found none: a genuine zero is a reading.
NO_CHALLANS = (
    "The books record no delivery challan issued in this period. Drafts and "
    "cancelled challans are not counted."
)


def _label(reason: str) -> str:
    return dc.REASON_LABELS.get(reason, reason)


def by_reason(counts: Mapping[str, int]) -> list[dict]:
    """The counts as rows in the order `delivery_challan.REASONS` fixes, then any reason outside it, each with the reason's own words."""
    rows = [{"reason": r, "label": _label(r), "count": int(counts[r])}
            for r in dc.REASONS if int(counts.get(r, 0)) > 0]
    rows += [{"reason": r, "label": _label(r), "count": int(n)}
             for r, n in sorted(counts.items()) if r not in dc.REASONS and int(n) > 0]
    return rows


def challans_note(counts: Optional[Mapping[str, int]]) -> str:
    """The sentence about the delivery challans issued in the window. `None` is a read that failed."""
    if counts is None:
        return CHALLANS_NOT_READ
    rows = by_reason(counts)
    total = sum(r["count"] for r in rows)
    if not total:
        return NO_CHALLANS
    head = ("1 delivery challan was issued in this period and is" if total == 1
            else f"{total} delivery challans were issued in this period and are")
    return (
        f"{head} not in this return's Table 13: "
        + "; ".join(f"{r['count']} for {r['label']}" for r in rows)
        + ". This build does not declare delivery challans, and which row of "
          "the table each belongs in is for the CA to settle against the form. "
          "Drafts and cancelled challans are not counted."
    )


def coverage(all_natures: Sequence[str], declared: Iterable[str],
             challan_counts: Optional[Mapping[str, int]]) -> dict:
    """The whole answer the result carries as `table_13_coverage`."""
    done = set(declared)
    rows = by_reason(challan_counts) if challan_counts is not None else []
    return {
        "declared_natures": [n for n in all_natures if n in done],
        "not_read_natures": not_read(all_natures, done),
        "note": natures_note(all_natures, done),
        # NOT named for the table: `tests/test_a_challan_amendment_cannot_stop_the_clock...` reads the string "delivery_challans" anywhere in
        # the API as a use of the table, and this is a count of challans, not a use of it.
        "challans": {
            "read": challan_counts is not None,
            "count": (sum(r["count"] for r in rows) if challan_counts is not None else None),
            "by_reason": rows,
            "note": challans_note(challan_counts),
        },
    }
