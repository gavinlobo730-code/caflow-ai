"""A column layout corrected for one bank account is saved for THAT account, and never overwrites another account's (ledger POST-A-300).

THE DEFECT
    `save_mapping` called `find_mapping`, which looks at the account first and then, for a layout nobody drew for this account, at any
    account of the firm with the same `header_fingerprint` (BANK-26, deliberate and good for READING an import). If it found a
    firm-wide row it UPDATEd that row by id, so a correction made while importing client B's statement changed the layout stored
    for client A's account, and B's account still had none. The second look is the read half of a convenience; the write must
    only ever touch the account's own row.

WHAT IS HELD (no database)
    * saving for an account that has no row of its own records one for it and leaves the other account's row exactly as it was;
    * saving again for the same account updates its own row and does not add a third;
    * an account's own row is still found first, and a firm-wide row is still offered for reading (`match_scope`);
    * the update names the firm and the account as well as the row.
"""
from __future__ import annotations

from domain.banking.normalizer import header_fingerprint
from services import bank_column_mapping_service as svc
from tests.e2e_harness import FakeDB

FIRM, CLIENT_A, CLIENT_B = "firm-300", "client-a", "client-b"
ACCT_A, ACCT_B = "acct-a", "acct-b"
HEADERS = ["Value Date", "Details", "Paid Out", "Paid In", "Running Total"]
A_MAPPING = {"date": 0, "desc": 1, "debit": 2, "credit": 3, "balance": 4}
B_MAPPING = {"date": 0, "desc": 1, "debit": 3, "credit": 2, "balance": 4}      # a different (corrected) answer


def _db_with_a_layout():
    db = FakeDB()
    svc.save_mapping(db, FIRM, CLIENT_A, ACCT_A, HEADERS, A_MAPPING, actor_id="u1")
    return db


def _rows(db):
    return sorted(db.rows("bank_statement_column_mappings"), key=lambda r: r["bank_account_id"])


def test_saving_for_another_account_records_its_own_layout_and_leaves_the_first_untouched():
    db = _db_with_a_layout()
    before = dict(_rows(db)[0])
    assert before["bank_account_id"] == ACCT_A
    # B has no layout of its own; find_mapping would offer A's (match_scope "firm")
    assert svc.find_mapping(db, FIRM, ACCT_B, header_fingerprint(HEADERS))["match_scope"] == "firm"

    svc.save_mapping(db, FIRM, CLIENT_B, ACCT_B, HEADERS, B_MAPPING, actor_id="u2")

    rows = _rows(db)
    assert [r["bank_account_id"] for r in rows] == [ACCT_A, ACCT_B]
    assert rows[0] == before, "account A's saved layout was changed by a correction made for account B"
    assert rows[1]["mapping"]["debit"] == 3 and rows[1]["client_id"] == CLIENT_B and rows[1]["created_by"] == "u2"


def test_saving_again_for_the_same_account_updates_its_own_row_and_adds_no_third():
    db = _db_with_a_layout()
    svc.save_mapping(db, FIRM, CLIENT_B, ACCT_B, HEADERS, B_MAPPING)
    corrected = {"date": 0, "desc": 1, "debit": 2, "credit": 3, "balance": 4}
    svc.save_mapping(db, FIRM, CLIENT_B, ACCT_B, HEADERS, corrected)
    rows = _rows(db)
    assert len(rows) == 2
    assert rows[1]["mapping"]["debit"] == 2                             # B's own row was corrected
    assert rows[0]["mapping"]["debit"] == 2 and rows[0]["bank_account_id"] == ACCT_A     # A's is as it was saved


def test_an_accounts_own_layout_is_found_first_and_a_layout_found_elsewhere_is_marked_as_such():
    db = _db_with_a_layout()
    fp = header_fingerprint(HEADERS)
    assert svc.find_mapping(db, FIRM, ACCT_A, fp)["match_scope"] == "account"
    assert svc.find_mapping(db, FIRM, ACCT_B, fp)["match_scope"] == "firm"
    svc.save_mapping(db, FIRM, CLIENT_B, ACCT_B, HEADERS, B_MAPPING)
    assert svc.find_mapping(db, FIRM, ACCT_B, fp)["match_scope"] == "account"


def test_a_layout_of_another_firm_is_never_updated_or_offered():
    db = FakeDB()
    svc.save_mapping(db, "firm-other", CLIENT_A, ACCT_A, HEADERS, A_MAPPING)
    svc.save_mapping(db, FIRM, CLIENT_B, ACCT_B, HEADERS, B_MAPPING)
    rows = sorted(db.rows("bank_statement_column_mappings"), key=lambda r: r["firm_id"])
    assert [r["firm_id"] for r in rows] == [FIRM, "firm-other"]
    assert rows[1]["mapping"]["debit"] == 2                              # the other firm's layout is untouched


def test_the_update_names_the_firm_and_the_account_as_well_as_the_row():
    import inspect
    src = inspect.getsource(svc.save_mapping)
    update = src[src.index(".update({"):src.index("return out[0] if out else {**existing, **row}")]
    assert '.eq("id", existing["id"])' in update and '.eq("firm_id", firm_id)' in update and '.eq("bank_account_id", bank_account_id)' in update
