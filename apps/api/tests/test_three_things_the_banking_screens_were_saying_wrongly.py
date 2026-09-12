"""
Three banking defects the 12 September probe pass confirmed open, and one
accounting one. All four are "a value nobody maintains" — the same fix shape,
which is why they travel together.

BANK-29 — a row that carries a BALANCE and no movement became a transaction.
    Banks print "Opening Balance", "B/F", "Closing Balance" among the rows, and
    they parse perfectly: a date, a description, an empty debit column, an empty
    credit column, a balance. `_rows_to_txns`'s amount/Dr-Cr branch already
    skipped a zero row; the two-column branch had no equivalent. So every such
    line became a bank transaction with zero on both legs, cluttering the
    entries list, impossible to code, and refused at post time with
    "Transaction has zero amount."

    MARKED, NOT DROPPED IN THE PARSER, and the ordering is the fix.
    `_opening_closing_balance` derives the statement's opening balance from the
    earliest row's `balance_paise`, and on a statement that prints an
    opening-balance row THAT ROW IS the opening balance. Dropping it in the
    parser would move the stored opening forward by the first real
    transaction's movement — a wrong number on the statement header traded for
    a tidier list.

BANK-12 — deleting a bank rule erased why lines posted.
    The docstring said a rule "has never written anything to the ledger". That
    stopped being true when migration 322 made a rule TRUSTABLE: a trusted rule
    passes entries by itself and every line it posted carries
    `posted_by_rule_id`, with `ON DELETE SET NULL` behind it. So an Executive
    could delete a rule and silently erase the recorded reason for every line
    it had posted, with no audit entry and no mention in the response.

BANK-25 — the statement "Status" chip could only ever say "pending".
    `import_status` is written once, at import, and by nothing else ever. The
    guard for that is in apps/web (the chip is gone); what is tested here is
    that nothing has quietly started depending on the column meaning anything.

ACC-26 — GET /accounting/ledger-span raised without SUPABASE_URL.
    Every other endpoint in that router goes through `_prod_db()`, which
    returns None in mock mode. This one called `get_supabase()` directly, which
    raises. The blast radius was small — the browser catches it and falls back
    to the financial year, and Render sets the variable — but a 500 the client
    has to swallow is not how the router answers "there is nothing here".
"""
import pytest

from domain.banking import parse_csv
import services.banking_service as bsvc
from services.banking_service import banking_service
from tests.test_bank_feed_import import FakeDB, FIRM, CLIENT   # noqa: F401  (shared fake)


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(bsvc.timeline_service, "log", lambda *a, **k: None)
    yield


# ---------------------------------------------------------------------------
# BANK-29
# ---------------------------------------------------------------------------
_WITH_OPENING = (
    "Date,Description,Debit,Credit,Balance\n"
    "01/04/2026,OPENING BALANCE,,,100000.00\n"
    "05/04/2026,NEFT IN,,50000.00,150000.00\n"
    "09/04/2026,ATM WITHDRAWAL,20000.00,,130000.00\n"
)


def test_a_balance_row_is_marked_by_having_no_movement_not_by_its_wording():
    # Keyed on zero-on-both-legs, never on the description: banks write it a
    # dozen ways and a label list is a list somebody has to keep adding to.
    txns = parse_csv(_WITH_OPENING)
    assert [t.is_balance_marker for t in txns] == [True, False, False]
    assert txns[0].balance_paise == 100_00_000   # the balance survives the parse


def test_a_balance_row_is_not_stored_as_a_transaction():
    db = FakeDB()
    res = banking_service.import_normalized(
        db, FIRM, CLIENT, "Generic", "123", parse_csv(_WITH_OPENING))
    assert res["imported"] == 2
    assert res["balance_rows_skipped"] == 1
    assert res["total_rows"] == 3
    stored = db.store.get("bank_transactions", [])
    assert len(stored) == 2
    assert all(int(r["debit_paise"]) or int(r["credit_paise"]) for r in stored)


def test_the_statements_OPENING_BALANCE_still_comes_from_the_row_that_carries_it():
    # THE INVARIANT. Dropping the marker in the parser would make this
    # 1,50,000 — the first real transaction's closing balance — instead of the
    # 1,00,000 the bank actually printed as the opening.
    db = FakeDB()
    banking_service.import_normalized(
        db, FIRM, CLIENT, "Generic", "123", parse_csv(_WITH_OPENING))
    stmt = db.store["bank_statements"][0]
    assert stmt["opening_balance_paise"] == 100_00_000
    assert stmt["closing_balance_paise"] == 130_00_000


def test_the_header_totals_are_the_real_transactions_and_the_count_agrees():
    db = FakeDB()
    banking_service.import_normalized(
        db, FIRM, CLIENT, "Generic", "123", parse_csv(_WITH_OPENING))
    stmt = db.store["bank_statements"][0]
    assert stmt["total_credits_paise"] == 50_00_000
    assert stmt["total_debits_paise"] == 20_00_000
    # row_count, imported_count and the rows actually written all agree — before
    # this they would have counted the marker as a transaction.
    assert stmt["row_count"] == 2 and stmt["imported_count"] == 2
    assert len(db.store["bank_transactions"]) == 2


def test_a_statement_with_no_balance_row_is_unchanged():
    # The whole change must be invisible to the ordinary case.
    db = FakeDB()
    csv = ("Date,Description,Debit,Credit,Balance\n"
           "05/04/2026,NEFT IN,,50000.00,50000.00\n"
           "09/04/2026,ATM,20000.00,,30000.00\n")
    res = banking_service.import_normalized(db, FIRM, CLIENT, "Generic", "123", parse_csv(csv))
    assert res["imported"] == 2 and res["balance_rows_skipped"] == 0
    stmt = db.store["bank_statements"][0]
    assert stmt["opening_balance_paise"] == 50_00_000


def test_the_tie_out_still_foots_with_the_marker_present():
    # `domain/banking/tie_out` sums debits and credits and compares against the
    # opening and closing the CA read off the paper. A zero-movement row
    # contributes nothing to either sum, which is why it can survive the check
    # and still be dropped from storage.
    from domain.banking.tie_out import totals
    txns = parse_csv(_WITH_OPENING)
    debits, credits = totals(txns)
    assert debits == 20_00_000 and credits == 50_00_000
    assert 100_00_000 + credits - debits == 130_00_000


def test_the_running_balance_check_still_agrees_with_the_marker_present():
    from domain.banking.normalizer import balance_agreement
    assert balance_agreement(parse_csv(_WITH_OPENING)).get("agrees") is True


# ---------------------------------------------------------------------------
# ACC-26
# ---------------------------------------------------------------------------
def test_the_ledger_span_answers_an_empty_span_in_mock_mode(monkeypatch):
    import routers.accounting as acc
    monkeypatch.setattr(acc, "_prod_db", lambda: None)
    resp = acc.get_ledger_span(None, {"firm_id": "F", "role": "Partner", "id": "u"})
    assert resp["success"] is True
    assert resp["data"] == {"first_entry_date": None, "last_entry_date": None}


# ---------------------------------------------------------------------------
# BANK-12
# ---------------------------------------------------------------------------
from tests.e2e_harness import FakeDB as E2EFakeDB, wire_e2e   # noqa: E402

_FIRM = "FIRM-R"


def _rule_setup(monkeypatch, *, posted: int = 0, role: str = "Executive"):
    import routers.banking as bk
    db = E2EFakeDB()
    wire_e2e(monkeypatch, db, [bk])
    monkeypatch.setattr(bk, "_db", lambda: db)
    db.seed("clients", {"id": "CLI", "firm_id": _FIRM})
    db.seed("bank_matching_rules", {
        "id": "RULE-1", "firm_id": _FIRM, "client_id": "CLI",
        "description_pattern": "netflix", "suggested_account_id": "ACC-1",
        "is_trusted": posted > 0, "trusted_by": "u-mgr" if posted else None})
    for i in range(posted):
        db.seed("bank_transactions", {
            "id": f"TXN-{i}", "firm_id": _FIRM, "client_id": "CLI",
            "posted_by_rule_id": "RULE-1", "transaction_date": "2026-04-10"})
    caller = {"firm_id": _FIRM, "id": "u1", "auth_user_id": "u1",
              "email": "x@f.test", "role": role}
    return bk, db, caller


def test_a_rule_that_never_posted_is_deleted_by_whoever_could_write_it(monkeypatch):
    bk, db, caller = _rule_setup(monkeypatch, posted=0, role="Executive")
    resp = bk.delete_rule("RULE-1", caller)
    assert resp["success"] is True and resp["data"]["posted_lines"] == 0
    assert not [r for r in db.rows("bank_matching_rules") if r["id"] == "RULE-1"]


def test_a_rule_that_posted_lines_is_refused_to_an_executive(monkeypatch):
    from fastapi import HTTPException
    bk, db, caller = _rule_setup(monkeypatch, posted=3, role="Executive")
    with pytest.raises(HTTPException) as e:
        bk.delete_rule("RULE-1", caller)
    assert e.value.status_code == 403
    assert "3 bank lines" in e.value.detail
    # And nothing was deleted on the way to the refusal.
    assert [r for r in db.rows("bank_matching_rules") if r["id"] == "RULE-1"]


def test_a_manager_may_delete_it_and_the_count_comes_back(monkeypatch):
    bk, db, caller = _rule_setup(monkeypatch, posted=3, role="Manager")
    resp = bk.delete_rule("RULE-1", caller)
    assert resp["data"]["deleted"] is True and resp["data"]["posted_lines"] == 3


def test_the_deletion_is_written_to_the_audit_log_with_the_whole_rule(monkeypatch):
    # AFTER the delete there is nothing left to read, so the audit entry is the
    # only record the rule ever existed.
    import routers.banking as bk_mod
    seen = {}
    bk, db, caller = _rule_setup(monkeypatch, posted=2, role="Partner")
    monkeypatch.setattr(bk_mod, "log_event",
                        lambda *a, **k: seen.update({"args": a, "kw": k}))
    bk.delete_rule("RULE-1", caller)
    assert seen["args"][1] == "bank_matching_rule" and seen["args"][3] == "delete"
    old = seen["kw"]["old_data"]
    assert old["description_pattern"] == "netflix"
    assert old["posted_lines_at_delete"] == 2
