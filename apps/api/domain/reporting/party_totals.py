"""
The firm Reports page's P&L Statement: taxable value by party, and the two totals (POST-A-469).

Two paths, one rule. public.report_party_totals (migration 745) is what production runs: the answer is one line per
party and the input is every counted document in the window, so CLAUDE.md's reporting rule puts the sum in the
database. This module is the identical rule for everything with no SQL functions (mock mode, local dev, the
in-memory suite, and the minutes the API is deployed before the migration has run), and
tests/test_report_party_totals_parity_pg.py holds the two identical.

WHAT IT ADDS
    The taxable value (`taxable_amount_paise`) of each counted document, grouped by the party it names: the
    customer of an issued, part-paid or paid sales invoice is revenue, the supplier of a received, part-paid or paid
    purchase bill is expense. Which documents count, and in which window, is decided by the caller's read
    (services/report_transactions_service.py); this module only adds what it is handed.

    AND THE FOUR CGST SECTION 34 NOTES, SIGNED AS THE LEDGER POSTS THEM (POST-A-502, migration 766). Until then a
    credit note was in this answer nowhere, so a month with one showed more revenue than the books hold:
        a sales credit note      Dr Sales Returns, taxable value    REDUCES the customer's revenue
        a sales debit note       Cr Sales Revenue, taxable value    INCREASES it
        a purchase debit note    Cr Purchases, taxable value        REDUCES the supplier's expense (a purchase return)
        a purchase credit note   Dr Purchases, taxable value        INCREASES it
    A note joins the line of the party it names, so a line is invoices less credit notes plus debit notes and can be
    negative where a note falls in a window its invoice does not. The answer says how much of each side is notes
    (`revenue_notes_paise`, `expense_notes_paise`, signed) and how many were counted (`note_documents`), so a screen can
    say it; `sales_documents` and `purchase_documents` still count invoices and bills only.

    It groups on the party's ID and not on its name. The browser used to group on the name, so two customers who
    share a name were one line, and every document whose customer could not be named fell into one nameless line.
    The totals are unchanged by that; only the lines are.

ORDER
    Largest first, then by party id, then the line with no party last. A name is not used to order, because
    Postgres and Python do not sort text alike and the parity test would then test a collation.

MONEY
    Integer paise throughout; nothing here divides by 100.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


def _lines(rows: Iterable[dict], party_key: str, names: dict[str, str]) -> tuple[list[dict[str, Any]], int, int]:
    totals: dict[Optional[str], list[int]] = {}
    for r in rows:
        pid = r.get(party_key)
        key = str(pid) if pid else None
        slot = totals.setdefault(key, [0, 0])
        slot[0] += int(r.get("taxable_amount_paise") or 0)
        slot[1] += 1
    out = [
        {
            "party_id": key,
            # None when the document names no party, or names one this firm has no row for: a screen says so in
            # words rather than drawing an empty name as if it were one.
            "party_name": (names.get(key) or None) if key else None,
            "total_paise": total,
            "documents": count,
        }
        for key, (total, count) in totals.items()
    ]
    out.sort(key=lambda line: (line["party_id"] is None, -line["total_paise"], line["party_id"] or ""))
    return out, sum(line["total_paise"] for line in out), sum(line["documents"] for line in out)


#: How each kind of note moves the side it sits on: +1 adds its taxable value, -1 takes it away. Named so the test that
#: reads the ledger's own posting functions (tests/test_the_pl_statement_nets_credit_and_debit_notes.py) can compare.
NOTE_SIGNS: dict[str, int] = {
    "sales_credit_notes": -1,        # Dr Sales Returns
    "sales_debit_notes": +1,         # Cr Sales Revenue
    "purchase_debit_notes": -1,      # Cr Purchases
    "purchase_credit_notes": +1,     # Dr Purchases
}


def _noted(rows: Iterable[dict], sign: int) -> list[dict]:
    """The note rows with their taxable value signed for the side they sit on (+1 adds to it, -1 takes from it)."""
    return [{**r, "taxable_amount_paise": sign * int(r.get("taxable_amount_paise") or 0)} for r in rows]


def party_totals(sales: Iterable[dict], bills: Iterable[dict], *,
                 customer_names: dict[str, str], vendor_names: dict[str, str],
                 sales_credit_notes: Iterable[dict] = (), sales_debit_notes: Iterable[dict] = (),
                 purchase_debit_notes: Iterable[dict] = (), purchase_credit_notes: Iterable[dict] = ()) -> dict[str, Any]:
    """The answer the screen draws, from the counted document rows.

    `sales` rows carry `customer_id` and `taxable_amount_paise`; `bills` rows carry `vendor_id` and
    `taxable_amount_paise`. The four note arguments are the counted notes in the same shapes (a sales note names a
    customer, a purchase note a supplier) and default to none, so a caller that knows no notes gets the answer it
    always got. The name maps are id -> name, read firm-scoped by the caller.
    """
    sales = list(sales)
    bills = list(bills)
    sales_credit_notes, sales_debit_notes = list(sales_credit_notes), list(sales_debit_notes)
    purchase_debit_notes, purchase_credit_notes = list(purchase_debit_notes), list(purchase_credit_notes)

    sales_notes = (_noted(sales_credit_notes, NOTE_SIGNS["sales_credit_notes"])
                   + _noted(sales_debit_notes, NOTE_SIGNS["sales_debit_notes"]))
    purchase_notes = (_noted(purchase_debit_notes, NOTE_SIGNS["purchase_debit_notes"])
                      + _noted(purchase_credit_notes, NOTE_SIGNS["purchase_credit_notes"]))
    revenue, revenue_total, _ = _lines(sales + sales_notes, "customer_id", customer_names)
    expenses, expense_total, _ = _lines(bills + purchase_notes, "vendor_id", vendor_names)
    return {
        "revenue": revenue,
        "expenses": expenses,
        "revenue_total_paise": revenue_total,
        "expense_total_paise": expense_total,
        "net_paise": revenue_total - expense_total,
        "sales_documents": len(sales),
        "purchase_documents": len(bills),
        "revenue_notes_paise": sum(int(r["taxable_amount_paise"]) for r in sales_notes),
        "expense_notes_paise": sum(int(r["taxable_amount_paise"]) for r in purchase_notes),
        "note_documents": len(sales_notes) + len(purchase_notes),
    }
