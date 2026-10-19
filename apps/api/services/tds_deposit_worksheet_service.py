"""The TDS deposit worksheet for one deduction month: what is read from the books, and how it is put together.

WHY THIS IS A SERVICE. The worksheet used to be assembled inside `GET /api/tds-workspace/deposit-due`, and a second reader
now needs the same answer: a challan recorded for a quarter closes the monthly deposit obligation of every month it paid in
full (`services/tds_deposit_closes_obligation`), and that decision must be the worksheet's own ("every section of the month
deposited in full") and not a second reading of the same rows. The reads and the call to `domain/tds/deposit_due` are here,
once; the route keeps only the HTTP, the in-memory mock mode and the answer's envelope.

WHAT WAS DEPOSITED IS THE CHALLAN REGISTER'S ANSWER, for the QUARTER the month is in: the deductions from the quarter's first
day to the end of the month asked about and the challans recorded for that financial year and quarter, matched first in first
out by `domain/tds/challan_mapping` exactly as the quarterly statement matches them. A short April moves its shortfall to the
later deductions, so April's rows have to be in the match when June is asked about.

NO `.order()` ON EITHER READ: `fetch_all` pages by keyset on `id` and adds its own ordering, and a second one makes the cursor
skip and repeat rows past the first thousand. The match sorts what it is given. The column lists are written out at the call,
because `tests/test_backend_columns_exist_pg.py` parses a literal select list and checks it against the real schema.
"""
from __future__ import annotations

from datetime import date, timedelta

from core.db_paging import fetch_all
from core.ist_clock import ist_fy_label, ist_today
from domain.tds import deposit_due as deposit_due_rules
from domain.tds.section_rates import quarter_dates
from services.compliance_engine import tds_deposit_due_date, tds_quarter_of_month


def month_window(year: int, mon: int) -> dict:
    """The financial year, the quarter and the dates a deduction month's worksheet reads between."""
    month_start = date(year, mon, 1)
    month_end = date(year + (mon == 12), (mon % 12) + 1, 1) - timedelta(days=1)
    fy = ist_fy_label(month_start)
    quarter = tds_quarter_of_month(mon)
    return {"fy": fy, "quarter": quarter, "month_start": month_start, "month_end": month_end,
            "quarter_start": quarter_dates(fy, quarter)[0], "due": tds_deposit_due_date(year, mon)}


def read_register(db, firm_id: str, client_id: str, window: dict) -> tuple[list, list]:
    """(the quarter's deductions up to the month's end, the quarter's challans) for one client."""
    fy, quarter = window["fy"], window["quarter"]
    quarter_rows = fetch_all(
        lambda: (db.table("tds_deductions")
                 .select("id, section, transaction_date, challan_date, "
                         "status, deductee_name, payment_amount_paise, "
                         "tds_paise, surcharge_paise, cess_paise")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("transaction_date", window["quarter_start"])
                 .lte("transaction_date", window["month_end"].isoformat())),
        label="tds.deposit_due")
    challans = fetch_all(
        lambda: (db.table("tds_challans").select("*")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .eq("financial_year", fy).eq("quarter", quarter)),
        label="tds.deposit_due.challans")
    return quarter_rows, challans


def build_sheet(year: int, mon: int, window: dict, quarter_rows: list, challans: list):
    """The worksheet for the month, from the quarter's rows and challans already read, and the register's match behind it.

    Returns (worksheet, mapping, rows): the rows are the quarter's rows dated inside the month."""
    month_start, month_end = window["month_start"].isoformat(), window["month_end"].isoformat()
    rows = [r for r in quarter_rows if month_start <= str(r.get("transaction_date") or "")[:10] <= month_end]
    counted = [c for c in challans if str(c.get("section") or "").strip() != "192"]
    label = f"{window['quarter']} FY {window['fy']}"
    mapping = deposit_due_rules.mapping_from_register(quarter_rows, challans, fy=window["fy"])
    sheet = deposit_due_rules.build(
        rows, month=f"{year:04d}-{mon:02d}", due_date=window["due"], as_at=ist_today(), deposits=mapping,
        deposits_read=(f"{len(counted)} non-salary challan{'' if len(counted) == 1 else 's'} recorded for {label}, "
                       "matched to the quarter's deductions first in first out, section by section."
                       if counted else
                       f"No non-salary challan is recorded for {label}, so no tax is counted as deposited."))
    return sheet, mapping, rows
