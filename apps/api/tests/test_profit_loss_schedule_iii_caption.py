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
    assert cogs_line["schedule_iii_caption"] == "Cost of Materials Consumed"


def test_purchases_and_cogs_share_the_same_caption_despite_different_sections():
    # Regression pin: Purchases lives in operating_expenses, Cost of Goods Sold
    # in its own cost_of_sales section — but both bucket into the same Schedule
    # III "Cost of Materials Consumed" caption, exactly like schedule_iii.py's
    # grouping.
    out = profit_loss(_lines(), ACCOUNTS, "2025-04-01", "2026-03-31", "accrual")
    cogs_line = next(l for l in out["cost_of_sales"]["lines"] if l["account_id"] == "cogs")
    purchases_line = next(l for l in out["operating_expenses"]["lines"] if l["account_id"] == "purchases")
    assert cogs_line["schedule_iii_caption"] == purchases_line["schedule_iii_caption"] == "Cost of Materials Consumed"


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


# ── Cross-language vocabulary contract ────────────────────────────────────────
#
# apps/web/app/clients/[id]/accounting/page.tsx renders P&L lines by looking
# their schedule_iii_caption up in fixed arrays (PL_REV_ORDER / PL_EXP_ORDER).
# A caption pl_bucket() can return that ISN'T in those arrays used to make the
# whole line silently vanish from the tab (the exact "Cost of Materials" vs
# "Cost of Materials Consumed" mismatch that caused the 2026-07-25 incident —
# the total stayed right because it's summed independently of bucketing, but
# the line itself disappeared). The frontend now also renders any caption NOT
# in its fixed lists as a fallback "extra" section, so a mismatch can no longer
# hide a line entirely — but this test still pins the exact set of strings
# pl_bucket() can produce, so a future addition here is a deliberate, visible
# change to review against PL_REV_ORDER / PL_EXP_ORDER (accounting/page.tsx)
# and the mirrored pinning test in accounting page.test.ts, not a silent drift.
_KNOWN_REVENUE_CAPTIONS = {"Revenue from Operations", "Other Income"}
_KNOWN_EXPENSE_CAPTIONS = {
    "Cost of Materials Consumed", "Employee Benefit Expense", "Finance Costs",
    "Depreciation & Amortisation", "Tax Expense", "Other Expenses",
}


def test_pl_bucket_revenue_caption_vocabulary_is_fully_pinned():
    subtypes = ["Operating Revenue", None, "Other Income", "Interest Income", "Dividend Income", "Some New Subtype"]
    for s in subtypes:
        assert pl_bucket("Revenue", s) in _KNOWN_REVENUE_CAPTIONS


def test_pl_bucket_expense_caption_vocabulary_is_fully_pinned():
    subtypes = [
        "Cost of Goods Sold", "Purchases", "Raw Material", "Employee Cost", "Salary",
        "Finance Cost", "Bank Charges", "Depreciation", "Amortisation", "Income Tax",
        "Deferred Tax", "Rent", None, "Some New Subtype",
    ]
    for s in subtypes:
        assert pl_bucket("Expense", s) in _KNOWN_EXPENSE_CAPTIONS
