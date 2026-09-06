"""
Bank data is held under the same statutes as the ledger, and until task #105 the
retention position did not know it existed.

WHAT WAS WRONG

Task #126 wrote the retention position — nine categories, each naming the law
that requires the record kept and the date that duty lapses. Bank data was not
one of them, and the product has held bank statements since migration 006:
account numbers, IFSC codes, and a narration on every line carrying the name,
UPI handle or reference of whoever was on the other side of the payment.

That counterparty is the part worth saying out loud. They are usually not the
firm's client. Nobody asked them anything. They are a data principal all the
same, and the platform holds thousands of them per client per year.

Under the module's own design an unclassified category REFUSES, which is the
safe direction — so nothing was being wrongly destroyed. But nothing could be
answered either: `erasure_decision("bank_data")` said only "no retention
position is written for this", which is a refusal a CA cannot act on and cannot
publish under Rule 14.

AND THE ONE PLACE THE PRODUCT ERASES BANK DATA SAID NOTHING EITHER

`DELETE /banking/accounts/{id}` refused with a joined list of referential
reasons, and the Accounts panel composed its own sentence from the same list in
the browser: two wordings of one refusal, neither naming a law, neither ever
lapsing. That is exactly what #126 fixed for payroll and #129 fixed for
customers and vendors.

WHAT THESE TESTS PIN

  * the category exists, covers the six record tables, and carries the three
    book-keeping duties;
  * the Companies Act period is the one that decides, because it is the longest;
  * the date comes from the NEWEST statement's `statement_to`, not the first row
    the query happened to return;
  * the real endpoint reaches the real sentence — the trap #126 and #129 both
    hit, where every test drove the helper and reverting the wiring failed
    nothing;
  * an account with no statement does NOT get a statutory date invented for it;
  * an unreadable statements table blocks the delete and still invents no date.
"""
from datetime import date

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from domain.dpdp.retention import CATEGORIES, RULES, erasure_decision
from services import bank_erasure
from models.banking import BankAccountIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-BD"
CLIENT = "CLI-BD"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}

TODAY = date(2026, 9, 6)


def _setup(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, [banking, cust, ven, obs])
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, CLIENT)
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT,
                                  "account_name": "Opening Balance Equity",
                                  "account_code": "3004", "is_active": True})
    return db


def _add_bank(db, *, name="Cosmos Bank", account_no="1234567899", opening=0):
    return banking.create_bank_account(BankAccountIn(
        client_id=CLIENT, bank_name=name, account_no=account_no,
        opening_balance_paise=opening, opening_balance_date="2026-04-01",
        coa_account_id=None), CALLER)["data"]


def _statement(db, account_id, statement_to):
    return db.seed("bank_statements", {
        "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": account_id,
        "bank_name": "Cosmos Bank", "statement_from": "2024-04-01",
        "statement_to": statement_to})


# ══════════════════════════════════════════════════════════════════════════════
# The category
# ══════════════════════════════════════════════════════════════════════════════

def test_bank_data_is_in_the_retention_position_at_all():
    """The #105 finding, as a regression. Before it, this key was absent and
    every question about bank data got the unknown-category refusal."""
    assert "bank_data" in CATEGORIES


def test_the_category_covers_the_tables_that_actually_hold_the_data():
    tables = set(CATEGORIES["bank_data"].tables)
    assert {"bank_accounts", "bank_statements", "bank_transactions"} <= tables
    assert {"bank_transaction_splits", "bank_reconciliations",
            "bank_reconciliation_matches"} <= tables


def test_the_configuration_tables_are_deliberately_not_in_it():
    """A matching rule and a column mapping are the firm's own configuration,
    not a record of anything that happened — DELETE /banking/rules/{id} removes
    one outright and rightly carries no statutory refusal. They are left
    UNCLASSIFIED rather than declared duty-free: unclassified refuses, and
    asserting "no duty" for a table nobody audited is a positive claim."""
    tables = set(CATEGORIES["bank_data"].tables)
    assert "bank_matching_rules" not in tables
    assert "bank_statement_column_mappings" not in tables
    for key in ("bank_matching_rules", "bank_statement_column_mappings"):
        decision = erasure_decision(key, today=TODAY)
        assert decision.erasable is False
        assert "No retention position is written" in decision.reason


def test_it_carries_the_three_book_keeping_duties():
    assert set(CATEGORIES["bank_data"].rules) == {
        "companies_act_books", "income_tax_books", "gst_records"}


def test_the_counterparty_is_named_in_what_the_category_holds():
    """The narration is the reason this category is not just "the client's own
    account number" — it is thousands of third parties who never consented."""
    holds = CATEGORIES["bank_data"].holds
    assert "narration" in holds
    assert "stranger to the engagement" in holds


def test_the_companies_act_is_the_period_that_decides():
    """Longest duty wins. For FY 2024-25: Companies Act 31-03-2033, IT
    31-03-2032, GST 31-12-2031 — so the answer is the Companies Act one, and if
    it were ever dropped the released date would move five years earlier."""
    decision = erasure_decision("bank_data", fy_label="2024-25", today=TODAY)
    assert decision.erasable is False
    assert decision.retained_until == date(2033, 3, 31)
    assert "s. 128(5)" in decision.reason
    assert "2 shorter duties also apply" in decision.reason


def test_the_client_is_the_duty_holder_not_the_platform():
    for key in CATEGORIES["bank_data"].rules:
        assert RULES[key].duty_holder == "client"


def test_a_long_lapsed_year_releases():
    decision = erasure_decision("bank_data", fy_label="2005-06", today=TODAY)
    assert decision.erasable is True


# ══════════════════════════════════════════════════════════════════════════════
# The sentence
# ══════════════════════════════════════════════════════════════════════════════

def test_a_live_duty_names_the_statute_the_holder_and_the_date():
    text = bank_erasure.refusal(
        ["bank statements have been imported for it"],
        latest_statement_end="2025-03-31", today=TODAY)
    assert "Companies Act 2013 (s. 128(5))" in text
    assert "the client" in text
    assert "31 March 2033" in text
    assert "Deactivate it instead" in text


def test_a_lapsed_duty_says_the_obstacle_is_the_books_not_the_law():
    text = bank_erasure.refusal(
        ["bank statements have been imported for it"],
        latest_statement_end="2005-03-31", today=TODAY)
    assert "has lapsed" in text
    assert "no law now requires them kept" in text
    assert "still cannot be deleted" in text
    # And it must not go on to quote a statute it has just said released it.
    assert "s. 128(5)" not in text


def test_no_statement_means_no_statutory_date_is_invented():
    """Reconciliations, payroll and a posted ledger are records of OTHER
    categories. With no statement there is nothing here to date a bank-data duty
    from, and the honest reason is referential."""
    text = bank_erasure.refusal(
        ["it has been reconciled", "payroll has been paid from it"],
        latest_statement_end=None, today=TODAY)
    assert "Companies Act" not in text
    assert "it has been reconciled; payroll has been paid from it" in text


def test_an_unparseable_statement_date_does_not_become_a_date():
    text = bank_erasure.refusal(["bank statements have been imported for it"],
                                latest_statement_end="not-a-date", today=TODAY)
    assert "Companies Act" not in text


def test_every_blocker_still_reaches_the_reader_when_a_statute_leads():
    text = bank_erasure.refusal(
        ["bank statements have been imported for it",
         "its ledger account carries posted journal entries"],
        latest_statement_end="2025-03-31", today=TODAY)
    assert "posted journal entries" in text
    assert "bank statements have been imported for it" in text


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint — the part that would otherwise be an unwired helper
# ══════════════════════════════════════════════════════════════════════════════

def test_the_delete_endpoint_answers_with_the_statute_and_the_date(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db)
    _statement(db, acc["id"], "2025-03-31")

    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    detail = str(e.value.detail)
    assert e.value.status_code == 409
    assert "Companies Act 2013 (s. 128(5))" in detail
    assert "31 March 2033" in detail
    assert db.rows("bank_accounts"), "a refused delete removed the account anyway"


def test_the_newest_statement_decides_not_the_first_row_returned(monkeypatch):
    """Retention runs from the financial year of the record, so the most recent
    statement is held longest. Seeding the OLDER one first is the control: if
    the code took whatever came back first, the answer would be 2032."""
    db = _setup(monkeypatch)
    acc = _add_bank(db)
    _statement(db, acc["id"], "2024-03-31")   # FY 2023-24 → 31 March 2032
    _statement(db, acc["id"], "2025-03-31")   # FY 2024-25 → 31 March 2033

    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    assert "31 March 2033" in str(e.value.detail)


def test_a_statement_ending_after_1_april_is_the_next_financial_year(monkeypatch):
    """The straddle control. 31-03-2025 and 01-04-2025 are one day apart and in
    different financial years, so they must give different release dates —
    a test that used two dates inside one FY would pass under either reading."""
    db = _setup(monkeypatch)
    acc = _add_bank(db)
    _statement(db, acc["id"], "2025-04-01")   # FY 2025-26 → 31 March 2034

    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    assert "31 March 2034" in str(e.value.detail)


def test_an_account_blocked_only_by_the_ledger_gets_no_statute(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db, opening=50_000)

    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    detail = str(e.value.detail)
    assert "posted journal entries" in detail
    assert "Companies Act" not in detail


def test_an_unreadable_statements_table_blocks_and_invents_no_date(monkeypatch):
    """A failed probe means BLOCKED, not clear — but it also means no
    statement_to came back, so the refusal must fall back to the referential
    sentence rather than dating a statute from a query that did not answer."""
    db = _setup(monkeypatch)
    acc = _add_bank(db)

    original = db.table

    def _boom(name):
        if name == "bank_statements":
            raise RuntimeError("permission denied for table bank_statements")
        return original(name)

    monkeypatch.setattr(db, "table", _boom)
    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    detail = str(e.value.detail)
    assert "bank statements have been imported for it" in detail
    assert "Companies Act" not in detail


def test_the_panel_is_told_the_same_sentence_the_delete_would_refuse_with(monkeypatch):
    """One refusal, one wording. The Accounts panel used to compose its own from
    blocked_by in the browser, so the statute would have reached the 409 and
    never reached the tooltip a CA actually sees."""
    db = _setup(monkeypatch)
    acc = _add_bank(db)
    _statement(db, acc["id"], "2025-03-31")

    row = banking.bank_accounts_deletable(
        client_id=CLIENT, current_user=CALLER)["data"][acc["id"]]
    assert row["deletable"] is False
    with pytest.raises(HTTPException) as e:
        banking.delete_bank_account(acc["id"], CALLER)
    assert row["reason"] == str(e.value.detail)


def test_a_deletable_account_carries_no_reason(monkeypatch):
    db = _setup(monkeypatch)
    acc = _add_bank(db)
    row = banking.bank_accounts_deletable(
        client_id=CLIENT, current_user=CALLER)["data"][acc["id"]]
    assert row == {"deletable": True, "blocked_by": [], "reason": None}


# ══════════════════════════════════════════════════════════════════════════════
# The document says the same thing the code does
# ══════════════════════════════════════════════════════════════════════════════

def _doc() -> str:
    from pathlib import Path
    path = (Path(__file__).resolve().parents[3]
            / "docs" / "compliance" / "06-data-protection-dpdp.md")
    return path.read_text(encoding="utf-8")


def test_the_published_position_lists_bank_data():
    from domain.dpdp.retention import position
    entry = [c for c in position() if c["category"] == "bank_data"]
    assert len(entry) == 1
    assert [r["provision"] for r in entry[0]["rules"]] == [
        "s. 128(5)", "r. 6F(5)", "s. 36"]


def test_the_doc_carries_the_bank_data_row():
    text = _doc()
    assert "**bank_data**" in text, "§5b's position table does not list bank_data"


def test_the_doc_records_that_the_aa_half_of_105_is_moot_under_route_3():
    assert "## 5e." in _doc()
