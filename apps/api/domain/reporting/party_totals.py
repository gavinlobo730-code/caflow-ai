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


def party_totals(sales: Iterable[dict], bills: Iterable[dict], *,
                 customer_names: dict[str, str], vendor_names: dict[str, str]) -> dict[str, Any]:
    """The answer the screen draws, from the counted document rows.

    `sales` rows carry `customer_id` and `taxable_amount_paise`; `bills` rows carry `vendor_id` and
    `taxable_amount_paise`. The name maps are id -> name, read firm-scoped by the caller.
    """
    revenue, revenue_total, sales_count = _lines(sales, "customer_id", customer_names)
    expenses, expense_total, bills_count = _lines(bills, "vendor_id", vendor_names)
    return {
        "revenue": revenue,
        "expenses": expenses,
        "revenue_total_paise": revenue_total,
        "expense_total_paise": expense_total,
        "net_paise": revenue_total - expense_total,
        "sales_documents": sales_count,
        "purchase_documents": bills_count,
    }
