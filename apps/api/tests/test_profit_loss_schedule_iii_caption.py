"""
domain/reporting/builders.py::profit_loss() — each returned line now carries an
authoritative "schedule_iii_caption" (Companies Act 2013, Schedule III, Part II),
computed by the SAME pl_bucket() the /schedule-iii endpoint uses.

Before this, the frontend P&L tab (apps/web/.../accounting/page.tsx) re-derived
this caption itself via its own copy of pl_bucket() — and that copy independently
never looked at the "cost_of_sales" section, so Cost of Goods Sold silently never
appeared on screen even after the backend schedule_iii.py grouping bug was fixed
separately (task, 2026-07-25). Moving the caption into the authoritative backend
response and having the frontend group by it (falling back to its own copy only
when the field is absent, e.g. a not-yet-redeployed backend) means a future fix
to pl_bucket() applies everywhere in one place, as it always should have.
"""
from domain.reporting.builders import profit_loss
from domain.reporting.model import Account, ProjectedLine
from domain.reporting.schedule_iii import pl_bucket

ACCOUNTS = {
    "sales": Account(id="sales", code="4000", name="Sales Revenue", type="Revenue", subtype="Operating Revenue"),
    "cogs": Account(id="cogs", code="5000", name="Cost of Goods Sold", type="Expense", subtype="Cost of Goods Sold"),
    "purchases": Account(id="purchases", code="5001", name="Purchases", type="Expense", subtype="Purchases"),
    "salaries": Account(id="salaries", code="6000", name="Salaries", type="Expense", subtype="Employee Cost"),
}


def _lines():
    return [
        ProjectedLine(account_id="sales", debit_paise=0, credit_paise=10_00_000_00),
        ProjectedLine(account_id="cogs", debit_paise=6_00_000_00, credit_paise=0),
        ProjectedLine(account_id="purchases", debit_paise=1_00, credit_paise=0),
        ProjectedLine(account_id="salaries", debit_paise=1_00_000_00, credit_paise=0),
    ]


def test_cost_of_sales_lines_carry_the_schedule_iii_caption():
    out = profit_loss(_lines(), ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    cogs_line = next(l for l in out["cost_of_sales"]["lines"] if l["account_id"] == "cogs")
    assert cogs_line["schedule_iii_caption"] == "Cost of Materials"


def test_purchases_and_cogs_share_the_same_caption_despite_different_sections():
    # Regression pin: Purchases lives in operating_expenses, Cost of Goods Sold
    # in its own cost_of_sales section — but both bucket into the same Schedule
    # III "Cost of Materials" caption, exactly like schedule_iii.py's grouping.
    out = profit_loss(_lines(), ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    cogs_line = next(l for l in out["cost_of_sales"]["lines"] if l["account_id"] == "cogs")
    purchases_line = next(l for l in out["operating_expenses"]["lines"] if l["account_id"] == "purchases")
    assert cogs_line["schedule_iii_caption"] == purchases_line["schedule_iii_caption"] == "Cost of Materials"


def test_caption_matches_the_authoritative_pl_bucket_for_every_line():
    out = profit_loss(_lines(), ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    for section in ("revenue", "cost_of_sales", "operating_expenses"):
        for line in out[section]["lines"]:
            acc = ACCOUNTS[line["account_id"]]
            assert line["schedule_iii_caption"] == pl_bucket(acc.type, acc.subtype)


def test_revenue_line_caption():
    out = profit_loss(_lines(), ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    sales_line = next(l for l in out["revenue"]["lines"] if l["account_id"] == "sales")
    assert sales_line["schedule_iii_caption"] == "Revenue from Operations"
