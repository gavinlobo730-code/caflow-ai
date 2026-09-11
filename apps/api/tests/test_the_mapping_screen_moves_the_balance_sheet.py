"""
ACC-10, end to end: an account the CA maps presents where they mapped it.

WHY THIS TEST AND NOT ONLY THE UNIT ONES

    The unit tests next door prove `classify` honours
    `chart_of_accounts.schedule_iii_mapping`. That was never the hard part. The
    defect was that the mapping did not TRAVEL: it was written by the CSV
    importer, displayed by a read-only screen, and read by no computation —
    so a CA could spend an afternoon on the Schedule III Mapping screen and the
    Balance Sheet would not move by a rupee, while the screen showed a green
    "37 of 53 accounts mapped" that measured nothing.

    So this walks the whole chain that was broken — Account record →
    builders.balance_sheet / profit_loss → bucket_amounts → build_schedule_iii —
    and asserts the RUPEES land on the caption the CA chose. Each link was
    individually plausible; the chain was not.
"""
from domain.reporting.builders import balance_sheet, profit_loss
from domain.reporting.model import Account, ProjectedLine
from domain.reporting.schedule_iii import bucket_amounts


FY = ("2026-04-01", "2027-03-31")


def _accounts(mapping=None):
    """One awkward asset — a security deposit whose subtype matches no keyword,
    so it falls into Other Current Assets unless somebody says otherwise — plus
    the contra it is posted against."""
    return {
        "a1": Account(id="a1", code="1900", name="Security Deposit — Landlord",
                      type="Asset", subtype="Widget Deposits",
                      schedule_iii_mapping=mapping),
        "a2": Account(id="a2", code="1100", name="HDFC Bank",
                      type="Asset", subtype="Bank"),
    }


LINES = [ProjectedLine("a1", 5_00_000, 0), ProjectedLine("a2", 0, 5_00_000)]


def _captions(mapping=None):
    accts = _accounts(mapping)
    bs = balance_sheet(LINES, accts, FY[1], "accrual")
    pl = profit_loss([], accts, FY[0], FY[1], "accrual")
    bs_buckets, _ = bucket_amounts(pl, bs)
    return bs_buckets


def test_unmapped_the_deposit_falls_into_other_current_assets():
    """The behaviour before, stated as a test so the fix cannot be mistaken for
    a no-op: a subtype that matches no keyword lands on the residual line with
    no warning."""
    assert _captions()["Other Current Assets"] == 5_00_000
    assert "Long Term Loans & Advances" not in _captions()


def test_mapped_the_rupees_move_to_the_caption_the_ca_chose():
    """THE POINT OF ACC-10. Same ledger, same subtype — one column changed on
    the chart of accounts, and the Balance Sheet presents it there."""
    out = _captions("Long Term Investments")
    assert out["Long Term Investments"] == 5_00_000
    assert out.get("Other Current Assets", 0) == 0


def test_the_balance_sheet_still_balances_whichever_caption_it_lands_on():
    """A reclassification must move a balance BETWEEN captions, never create or
    destroy one — the tie to the trial balance is what makes the statement
    signable."""
    for mapping in (None, "Long Term Investments", "Inventories", "Not A Caption"):
        assert sum(_captions(mapping).values()) == 0, mapping
        # Dr deposit 5,00,000 / Cr bank 5,00,000 nets to nil across the sheet.


def test_the_line_carries_how_it_was_classified():
    """The half that makes the mapping screen's count mean something: a report
    can now say which balances are on an "Other" line because nobody decided."""
    bs = balance_sheet(LINES, _accounts(), FY[1], "accrual")
    rows = {r["account_code"]: r for s in bs["assets"] for r in s["lines"]}
    assert rows["1900"]["schedule_iii_basis"] == "residual"
    assert rows["1100"]["schedule_iii_basis"] == "subtype"

    bs = balance_sheet(LINES, _accounts("Long Term Investments"), FY[1], "accrual")
    rows = {r["account_code"]: r for s in bs["assets"] for r in s["lines"]}
    assert rows["1900"]["schedule_iii_basis"] == "mapping"
    assert rows["1900"]["schedule_iii_mapping"] == "Long Term Investments"


def test_a_mapping_that_is_not_a_caption_changes_nothing():
    """The column is free text with no CHECK. An importer's stray value must not
    move a balance anywhere."""
    assert _captions("Not A Caption")["Other Current Assets"] == 5_00_000


def test_an_expense_mapping_on_an_asset_is_ignored_by_the_balance_sheet():
    """Honouring it would put an expense caption on the balance sheet, where
    Schedule III has no such line — the amount would vanish from the statement
    while still being in the trial balance."""
    out = _captions("Finance Costs")
    assert out["Other Current Assets"] == 5_00_000
    assert "Finance Costs" not in out


# ── The P&L side, and the defect that was live ───────────────────────────────

def test_cost_of_materials_reaches_the_profit_and_loss_not_the_balance_sheet():
    """`_CAPTION_TO_SCHEDULE_LINE` carried the key "Cost of Materials" while
    pl_bucket returns "Cost of Materials Consumed", and the fallback was
    other_current_assets — so on a trading client the largest expense on the P&L
    was a current asset in the year-end statements."""
    accts = {
        "e1": Account(id="e1", code="5100", name="Purchases — Raw Material",
                      type="Expense", subtype="Raw Material"),
        "a2": Account(id="a2", code="1100", name="HDFC Bank", type="Asset", subtype="Bank"),
    }
    lines = [ProjectedLine("e1", 12_00_000, 0), ProjectedLine("a2", 0, 12_00_000)]
    pl = profit_loss(lines, accts, FY[0], FY[1], "accrual")
    bs = balance_sheet(lines, accts, FY[1], "accrual")
    bs_buckets, pl_buckets = bucket_amounts(pl, bs)

    assert pl_buckets["Cost of Materials Consumed"] == 12_00_000
    assert "Cost of Materials Consumed" not in bs_buckets

    from routers.year_end_mappings import _schedule_line_for_account
    assert _schedule_line_for_account("Expense", "Raw Material") == \
        "cost_of_materials_consumed"
