"""
ACC-10 — one Schedule III vocabulary, and every table that translates it is
TOTAL over it.

WHAT THIS EXISTS TO PREVENT, WITH THE ONE THAT HAPPENED

    `routers/year_end_mappings._CAPTION_TO_SCHEDULE_LINE` carried the key
    "Cost of Materials" while `pl_bucket` has always returned "Cost of Materials
    Consumed", and the lookup's fallback was the literal `"other_current_assets"`.

    So on a trading or manufacturing client the single largest expense on the
    P&L was classified as a CURRENT ASSET in the year-end financial statements:
    profit overstated by the whole cost of materials, and a phantom asset of the
    same amount on the balance sheet. Nothing failed, nothing warned, and the
    existing test for that function checked seven accounts, none of them an
    expense with a materials subtype.

    A caption is a STRING that travels — the year-end statements translate it,
    the P&L tab prints it, the ratio engine matches on it — and a caption a
    caller does not know falls through that caller's default, silently. So the
    set is declared once and every translation is asserted total over it.

THE OTHER HALF: THE CA'S OWN MAPPING IS NOW READ

    `chart_of_accounts.schedule_iii_mapping` was written by the CSV importer,
    displayed by a read-only screen, and read by NO computation — so a CA could
    spend an afternoon on the Schedule III Mapping screen and the Balance Sheet
    would not move by a rupee. It now outranks the subtype scan, and `classify`
    reports WHICH of the two decided, so a report can say how many balances are
    on an "Other" line because nobody chose rather than because somebody did.
"""
import pytest

from domain.reporting.schedule_iii import (
    BALANCE_SHEET_CAPTIONS, CAPTIONS, PROFIT_LOSS_CAPTIONS, RESIDUAL_CAPTIONS,
    bs_bucket, classify, pl_bucket,
)

# Every (type, subtype) pair the seeded chart of accounts and the keyword scan
# can produce. Deliberately broad — the point is to drive the functions over
# their whole range, not to assert one answer.
SUBTYPES = [
    "Share Capital", "Capital Account", "Reserves", "Retained Earnings",
    "Deferred Tax", "Trade Payable", "Payable", "Creditor", "GST Payable",
    "TDS Payable", "Short Term Loan", "Overdraft", "CC Limit", "Term Loan",
    "Long Term Loan", "Debenture", "Intangible Asset", "Goodwill", "Software",
    "Fixed Asset", "Tangible", "Plant", "Machinery", "Furniture", "Building",
    "Vehicle", "Long Term Investment", "Investment", "Inventory", "Stock",
    "Trade Receivable", "Debtor", "Receivable", "Cash", "Bank", "Advance",
    "Other Income", "Interest Income", "Dividend", "Sales", "Raw Material",
    "Cost of Goods", "Purchase", "Employee", "Salary", "Wages", "Staff",
    "Finance", "Interest Expense", "Bank Charge", "Depreciation",
    "Amortisation", "Income Tax", "Deferred Tax", "Sundry", "Widget", None, "",
]
TYPES = ["Asset", "Liability", "Equity", "Revenue", "Expense", "", "Nonsense"]


def _every_caption() -> set[str]:
    out = set()
    for typ in TYPES:
        for sub in SUBTYPES:
            for fn in (bs_bucket, pl_bucket):
                c = fn(typ, sub)
                if c:
                    out.add(c)
    return out


# ── The vocabulary is closed ─────────────────────────────────────────────────

def test_the_buckets_return_only_declared_captions():
    """If a new caption is added to a bucket without being declared, this fails
    — which is the moment to add it to every translation table too."""
    assert _every_caption() <= CAPTIONS


def test_every_declared_caption_is_reachable():
    """The other direction: a declared caption no bucket returns is a lie in the
    vocabulary, and the totality tests below would then be asserting rows that
    can never be used."""
    reachable = _every_caption()
    assert CAPTIONS - reachable == set(), f"unreachable: {sorted(CAPTIONS - reachable)}"


def test_the_two_halves_do_not_overlap():
    """A caption on both statements would make bs_bucket-or-pl_bucket
    order-dependent, which is how a P&L line ends up on a balance sheet."""
    assert set(BALANCE_SHEET_CAPTIONS) & set(PROFIT_LOSS_CAPTIONS) == set()


def test_the_residual_captions_are_declared_captions():
    assert RESIDUAL_CAPTIONS <= CAPTIONS


# ── Every translation table is TOTAL over the vocabulary ─────────────────────

def test_every_caption_has_a_schedule_line():
    """THE ONE THAT WOULD HAVE CAUGHT IT. _CAPTION_TO_SCHEDULE_LINE must hold
    every caption the buckets can return — a missing row is not an error, it is
    a silent reclassification into whatever the fallback points at."""
    from routers.year_end_mappings import _CAPTION_TO_SCHEDULE_LINE
    missing = sorted(c for c in CAPTIONS if c not in _CAPTION_TO_SCHEDULE_LINE)
    assert missing == [], (
        f"Schedule III captions with no year-end schedule_line: {missing}. "
        "Without a row each of these is classified by the fallback — which put "
        "Cost of Materials Consumed into other_current_assets for months.")


def test_the_schedule_line_table_holds_no_caption_that_cannot_happen():
    """A key no bucket returns is dead — and a dead key beside a live one is
    exactly how "Cost of Materials" sat there looking correct."""
    from routers.year_end_mappings import _CAPTION_TO_SCHEDULE_LINE
    # Two aliases are deliberate: the year-end taxonomy splits Tax Expense into
    # current and deferred, and carries both names so a hand-edited mapping is
    # still understood.
    aliases = {"Current Tax", "Deferred Tax"}
    dead = sorted(set(_CAPTION_TO_SCHEDULE_LINE) - CAPTIONS - aliases)
    assert dead == [], f"captions no bucket returns: {dead}"


def test_cost_of_materials_is_an_expense_not_an_asset():
    """The defect itself, named, so the fix cannot be mistaken for a rename."""
    from routers.year_end_mappings import _schedule_line_for_account
    assert _schedule_line_for_account("Expense", "Raw Material Purchases") == \
        "cost_of_materials_consumed"
    assert _schedule_line_for_account("Expense", "Cost of Goods Sold") == \
        "cost_of_materials_consumed"


# ── The CA's mapping is read, and only where it makes sense ──────────────────

def test_an_explicit_mapping_outranks_the_subtype_scan():
    caption, basis = classify("Asset", "Widget Deposits", "Long-term Investments")
    assert (caption, basis) == ("Long-term Investments", "mapping")


def test_without_a_mapping_the_subtype_still_decides():
    assert classify("Asset", "Trade Receivables") == ("Trade Receivables", "subtype")


def test_a_mapping_for_the_other_statement_is_ignored():
    """An "Inventories" mapping on a Revenue account is a mistake in the data,
    not an instruction — honouring it would put turnover on the balance sheet."""
    assert classify("Revenue", "Sales", "Inventories") == \
        ("Revenue from Operations", "subtype")
    assert classify("Asset", "Bank", "Finance Costs") == \
        ("Cash & Cash Equivalents", "subtype")


def test_a_mapping_that_is_not_a_caption_is_ignored():
    """The column is free text with no CHECK and an importer can put anything in
    it. An unknown string would otherwise travel into the year-end translation
    and land wherever that table's fallback points."""
    assert classify("Asset", "Deposits", "Not A Caption") == \
        ("Other Current Assets", "residual")
    assert classify("Asset", "Trade Receivables", "") == \
        ("Trade Receivables", "subtype")


# ── The basis is the half that makes the mapping screen mean something ───────

def test_an_unmatched_account_says_it_landed_there_by_default():
    assert classify("Asset", "Widget Deposits") == ("Other Current Assets", "residual")
    assert classify("Liability", "Widget Accrual") == ("Other Current Liabilities", "residual")
    assert classify("Expense", "Sundry") == ("Other Expenses", "residual")


def test_ordinary_revenue_and_reserves_are_not_reported_as_gaps():
    """They are the last branch of their section AND the right answer for the
    ordinary case. Reporting them would flag every well-classified client and
    teach people to ignore the count."""
    assert classify("Revenue", "Sales")[1] == "subtype"
    assert classify("Equity", "Retained Earnings")[1] == "subtype"


def test_an_off_statement_account_has_no_caption():
    assert classify("Nonsense", "Whatever") == (None, "residual")


@pytest.mark.parametrize("typ,sub", [(t, s) for t in TYPES for s in SUBTYPES])
def test_classify_agrees_with_the_buckets_it_wraps(typ, sub):
    """classify() must never be a second implementation — it is the buckets
    plus a basis, and a divergence would put two answers on one statement."""
    expected = bs_bucket(typ, sub) or pl_bucket(typ, sub)
    assert classify(typ, sub)[0] == expected
