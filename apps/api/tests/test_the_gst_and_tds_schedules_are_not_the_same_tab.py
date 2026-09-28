"""The GST, TDS and Payables year-end schedule tabs rendered byte-for-byte
identical rows and totals.

Confirmed live against Apex Trading Solutions production data: the GST and
TDS tabs both showed the exact same ₹2,93,25,965.11 total, and Payables was
Trade Payables plus the same nine statutory-liability rows both other tabs
carried.

ROOT CAUSE: `_schedule_to_lines` in routers/year_end_statements.py mapped
'gst' and 'tds' to the identical coarse Schedule III bucket list
(`other_current_liabilities`, `short_term_loans_and_advances`), and 'payables'
included `other_current_liabilities` too. Every statutory-liability account —
GST Output Tax Payable, Compensation Cess Payable, TDS Payable, TDS Payable -
Salary, PF/ESI/PT Payable, Net Salary Payable, Income Tax Payable — shares
`account_subtype = 'Current Liability'`, and
`domain.reporting.year_end_lines.schedule_line_for_account` has no finer
Balance Sheet caption to give any of them: Schedule III itself does not
distinguish "GST payable" from "TDS payable", only "Other Current
Liabilities". So all three tabs pulled the same account set. The GST tab was
also one-sided — GST Output only, no GST Input/ITC asset-side row, because
that row resolves to `other_current_assets`, which was in none of the three
tabs' line lists at all.

FIX: `domain.reporting.year_end_lines.statutory_schedule_bucket` is a second,
finer classification asked PER ACCOUNT, on top of the coarse line — "gst",
"tds" or None — resolved system_account_key first (the same two-step order
services.gst_return_service._gl_gst_movements and
services.itc_register_service._gst_input_credit_on already use), falling back
to the account's own name using the identical ILIKE substrings
services.phase2_journal_service._find_account and
services.coa_seed_service.STANDARD_COA's own comments already commit this
codebase to for POSTING money.

THE KEY ALONE WOULD NOT HAVE FIXED THIS. `system_account_key` is NULL on
every account of a firm onboarded through the real path,
services.coa_seed_service.seed_firm_coa — the one Apex went through — because
that seeder's own STANDARD_COA sets no key at all; the key is only stamped by
migrations 092/098/374/389 on accounts THEY seeded or backfilled, and never
at all on the payroll-statutory accounts (PF/ESI/PT/Net Salary/TDS-Salary).
A key-only classifier would have left the GST and TDS tabs both EMPTY for the
exact client this was found on — worse than the defect it replaces. This
suite exercises the chart shape Apex actually has (every system_account_key
NULL) as the primary case, and the key-stamped shape as a second, narrower
case.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_statements as yes
from domain.reporting.year_end_lines import statutory_schedule_bucket
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-apex"
CLIENT = "client-apex"
PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "p@f.test"}


# ── Unit coverage on the classifier itself ─────────────────────────────────

def test_a_coa_seed_service_chart_has_no_system_account_key_and_is_named_by_key_pattern():
    """The shape every real firm is onboarded with (coa_seed_service.STANDARD_COA
    stamps no system_account_key at all) — resolved by name."""
    assert statutory_schedule_bucket(None, "GST Output Tax Payable") == "gst"
    assert statutory_schedule_bucket(None, "GST Input Tax Credit") == "gst"
    assert statutory_schedule_bucket(None, "Compensation Cess Payable") == "gst"
    assert statutory_schedule_bucket(None, "Compensation Cess Input Credit") == "gst"
    assert statutory_schedule_bucket(None, "TDS Payable") == "tds"
    # A substring of the one above, and deliberately still "tds" — both belong
    # in the same schedule, so the ambiguity that matters for POSTING (which
    # ONE account to credit) does not apply to GROUPING.
    assert statutory_schedule_bucket(None, "TDS Payable - Salary") == "tds"
    assert statutory_schedule_bucket(None, "TDS Receivable") == "tds"
    assert statutory_schedule_bucket(None, "PF Payable") == "tds"
    assert statutory_schedule_bucket(None, "ESI Payable") == "tds"
    assert statutory_schedule_bucket(None, "PT Payable") == "tds"
    assert statutory_schedule_bucket(None, "Net Salary Payable") == "tds"


def test_income_tax_payable_is_neither_gst_nor_tds():
    """It is not TDS and it is not GST — nothing here decides it belongs on
    Payables, that falls out of it belonging to NEITHER statutory bucket."""
    assert statutory_schedule_bucket(None, "Income Tax Payable") is None
    assert statutory_schedule_bucket(None, "Trade Payables") is None


def test_an_older_stamped_chart_resolves_by_key_before_the_name_is_even_looked_at():
    """migrations 092/098/374/389 stamp system_account_key on the charts THEY
    touched. A name that matches NOTHING must still resolve correctly from the
    key alone."""
    assert statutory_schedule_bucket("gst_cgst", "Statutory Dues - GST") == "gst"
    assert statutory_schedule_bucket("gst_cess_input", "Statutory Dues - GST") == "gst"
    assert statutory_schedule_bucket("tds_payable", "Statutory Dues - Withholding") == "tds"
    assert statutory_schedule_bucket("tds_receivable", "Statutory Dues - Withholding") == "tds"


def test_an_ordinary_account_is_neither():
    assert statutory_schedule_bucket(None, "Office Rent Payable") is None
    assert statutory_schedule_bucket(None, "Sundry Creditors") is None
    assert statutory_schedule_bucket("bank", "Current Account - HDFC") is None


# ── The live schedule endpoint, on a chart shaped exactly like Apex's ──────
#
# Every account below carries NO system_account_key, because that is what
# services.coa_seed_service.seed_firm_coa actually writes — the onboarding
# path a real second client goes through. If the fix regressed to a
# key-only classifier this whole fixture would resolve every statutory
# account to None and both tabs would come back empty.

_ACCOUNTS = [
    # code, name,                             type,        subtype,             balance (paise)
    ("2001", "Trade Payables",                "Liability", "Payable",            300000),
    ("2002", "GST Output Tax Payable",        "Liability", "Current Liability",  200000),
    ("2010", "Compensation Cess Payable",     "Liability", "Current Liability",   50000),
    ("1301", "GST Input Tax Credit",          "Asset",     "Tax",                 80000),
    ("1302", "Compensation Cess Input Credit","Asset",     "Tax",                 10000),
    ("2003", "TDS Payable",                   "Liability", "Current Liability",   60000),
    ("2004", "TDS Payable - Salary",          "Liability", "Current Liability",   40000),
    ("1401", "TDS Receivable",                "Asset",     "Tax",                 25000),
    ("2005", "PF Payable",                    "Liability", "Current Liability",   30000),
    ("2006", "ESI Payable",                   "Liability", "Current Liability",   20000),
    ("2007", "PT Payable",                    "Liability", "Current Liability",    5000),
    ("2008", "Net Salary Payable",            "Liability", "Current Liability", 150000),
    ("2009", "Income Tax Payable",            "Liability", "Current Liability",   70000),
]

_ASSET_TYPES = {"Asset"}


def _seed_apex_books(db: FakeDB) -> dict:
    eng = db.seed("year_end_engagements", {
        "id": "E-APEX", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2024-25", "fy_start": "2024-04-01",
        "fy_end": "2025-03-31", "status": "draft",
    })
    for code, name, atype, subtype, amount in _ACCOUNTS:
        acct = db.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": None,  # firm-wide, like coa_seed_service
            "account_code": code, "account_name": name,
            "account_type": atype, "account_subtype": subtype,
            "schedule_iii_mapping": None,
            "system_account_key": None,   # <- the Apex shape
            "is_active": True,
        })
        if atype in _ASSET_TYPES:
            debit, credit = amount, 0
        else:
            debit, credit = 0, amount
        db.seed("account_period_balances", {
            "firm_id": FIRM, "client_id": CLIENT, "account_id": acct["id"],
            "period_month": "2024-06-01",
            "debit_paise": debit, "credit_paise": credit,
        })
    return eng


def _names(resp: dict) -> set[str]:
    return {li["description"] for li in resp["data"]["line_items"]}


@pytest.fixture
def apex(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yes])
    _seed_apex_books(db)
    return db


def test_the_gst_tab_shows_only_gst_accounts_both_sides(apex):
    resp = yes.get_schedule("E-APEX", "gst", current_user=PARTNER)
    assert _names(resp) == {
        "GST Output Tax Payable", "Compensation Cess Payable",
        "GST Input Tax Credit", "Compensation Cess Input Credit",
    }
    # -(200000+50000) + (80000+10000)
    assert resp["data"]["total_paise"] == -160000


def test_the_tds_tab_shows_only_tds_and_payroll_statutory_accounts(apex):
    resp = yes.get_schedule("E-APEX", "tds", current_user=PARTNER)
    assert _names(resp) == {
        "TDS Payable", "TDS Payable - Salary", "TDS Receivable",
        "PF Payable", "ESI Payable", "PT Payable", "Net Salary Payable",
    }
    # -(60000+40000+30000+20000+5000+150000) + 25000
    assert resp["data"]["total_paise"] == -280000


def test_the_payables_tab_is_trade_payables_plus_what_neither_bucket_claims(apex):
    resp = yes.get_schedule("E-APEX", "payables", current_user=PARTNER)
    assert _names(resp) == {"Trade Payables", "Income Tax Payable"}
    assert resp["data"]["total_paise"] == -370000


def test_gst_and_tds_no_longer_render_the_same_rows_or_total(apex):
    """THE HEADLINE DEFECT. Both tabs used to be byte-for-byte identical."""
    gst = yes.get_schedule("E-APEX", "gst", current_user=PARTNER)
    tds = yes.get_schedule("E-APEX", "tds", current_user=PARTNER)
    assert _names(gst) != _names(tds)
    assert gst["data"]["total_paise"] != tds["data"]["total_paise"]
    assert _names(gst).isdisjoint(_names(tds))


def test_every_statutory_account_lands_in_exactly_one_of_the_three_tabs(apex):
    """Not "at least one" only — the three tabs must PARTITION the thirteen
    seeded accounts. Nothing is silently dropped from all three, and nothing
    is silently duplicated across two."""
    gst = _names(yes.get_schedule("E-APEX", "gst", current_user=PARTNER))
    tds = _names(yes.get_schedule("E-APEX", "tds", current_user=PARTNER))
    payables = _names(yes.get_schedule("E-APEX", "payables", current_user=PARTNER))

    all_names = {name for _, name, *_ in _ACCOUNTS}
    assert gst | tds | payables == all_names, (
        "an account was dropped from all three tabs")
    assert gst.isdisjoint(tds), "an account is on both GST and TDS"
    assert gst.isdisjoint(payables), "a GST account still leaked into Payables"
    assert tds.isdisjoint(payables), "a TDS account still leaked into Payables"


def test_a_pre_098_stamped_chart_still_works_from_the_key_alone(monkeypatch):
    """A chart whose GST heads were seeded/backfilled before this fix, so
    system_account_key IS set — the accounts must still land correctly even
    where their NAME alone would not have said so."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yes])
    db.seed("year_end_engagements", {
        "id": "E-OLD", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2024-25", "fy_start": "2024-04-01",
        "fy_end": "2025-03-31", "status": "draft",
    })
    cgst = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": None, "account_code": "2011",
        "account_name": "Statutory Dues - GST", "account_type": "Liability",
        "account_subtype": "Current Liability", "schedule_iii_mapping": None,
        "system_account_key": "gst_cgst", "is_active": True,
    })
    tds = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": None, "account_code": "2012",
        "account_name": "Statutory Dues - Withholding", "account_type": "Liability",
        "account_subtype": "Current Liability", "schedule_iii_mapping": None,
        "system_account_key": "tds_payable", "is_active": True,
    })
    db.seed("account_period_balances", {
        "firm_id": FIRM, "client_id": CLIENT, "account_id": cgst["id"],
        "period_month": "2024-06-01", "debit_paise": 0, "credit_paise": 12345,
    })
    db.seed("account_period_balances", {
        "firm_id": FIRM, "client_id": CLIENT, "account_id": tds["id"],
        "period_month": "2024-06-01", "debit_paise": 0, "credit_paise": 6789,
    })

    gst_resp = yes.get_schedule("E-OLD", "gst", current_user=PARTNER)
    tds_resp = yes.get_schedule("E-OLD", "tds", current_user=PARTNER)
    assert _names(gst_resp) == {"Statutory Dues - GST"}
    assert _names(tds_resp) == {"Statutory Dues - Withholding"}


def test_cash_bank_receivables_fixed_assets_and_loans_are_unaffected(apex):
    """The finer split is asked only for 'gst' and 'tds'. Every other tab
    keeps its exact pre-fix selection — this fix touches nothing else."""
    for schedule_type in ("cash_bank", "receivables", "fixed_assets", "loans"):
        resp = yes.get_schedule("E-APEX", schedule_type, current_user=PARTNER)
        assert resp["success"] is True
        # None of the statutory accounts seeded above belong on any of these
        # four tabs (they are all Current Liability / Tax subtype).
        assert _names(resp) == set(), (
            f"{schedule_type} unexpectedly picked up a statutory account: "
            f"{_names(resp)}")
