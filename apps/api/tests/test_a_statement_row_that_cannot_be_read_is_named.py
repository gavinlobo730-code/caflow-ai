"""A bank statement row that looks like a transaction and cannot be read is NAMED, never read as a row with no movement (POST-A-551).

WHAT WAS WRONG
    `_to_paise` answered 0 for an amount cell it could not read ("12x4.00", "1.2.3", a word in the amount column), exactly as it does
    for a blank cell. On a statement with one amount column and a Dr/Cr marker the row was then skipped; on a two-column statement an
    unreadable debit beside an empty credit made the row a balance marker and not a transaction. Either way a real transaction was left
    out of the import and nothing said which. Where the statement prints its own totals, or the CA types the two balances, the import
    was refused for not adding up, with a sentence that sent the CA to the column mapping; where neither was there, it went in short.

WHAT IS ASSERTED
    * the reader tells an unreadable cell (None) from an empty one (0), and the figure-only reader (`_to_paise`) still answers 0 for
      both, which is what a balance or a totals row needs;
    * a row with an unreadable amount is not a transaction and not a balance marker: it is carried as an unread row, with the cell as
      printed, its date and its narration, on both layouts; a genuinely empty row is still a balance marker and is not named;
    * a row whose DATE cannot be read is named when it carries a figure, and a totals row or a sub-header with no figure is not;
    * the sentence names up to three rows and counts the rest, and agrees in number;
    * a file in which nothing could be read says which rows, not only "no transactions found";
    * the preview route and the upload route carry the rows and the sentence, an upload that is refused for not adding up names them
      in the refusal, and a file with nothing unread carries an empty list and no sentence.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from domain.banking import StatementParseError
from domain.banking import normalizer as n
from main import app

TWO_COLUMN = (
    "Date,Description,Debit,Credit,Balance\n"
    "01/04/2026,Opening Balance,,,10000.00\n"
    "02/04/2026,Rent,5000.00,,5000.00\n"
    "03/04/2026,UPI to vendor,12x4.00,,3766.00\n"
    "04/04/2026,Receipt,,2000.00,5766.00\n"
)
AMOUNT_MODE = (
    "Date,Narration,Amount,Dr/Cr,Balance\n"
    "02/04/2026,Rent,5000.00,Dr,5000.00\n"
    "03/04/2026,UPI to vendor,1.2.3,Dr,3766.00\n"
    "04/04/2026,Zero line,0.00,Dr,3766.00\n"
    "05/04/2026,Receipt,2000.00,Cr,5766.00\n"
)


@pytest.mark.parametrize("cell", ["12x4.00", "1.2.3", "abc", "12,3x4", "NaN", "Infinity", "(12a)"])
def test_a_cell_that_is_not_an_amount_is_none_to_the_reader_and_nil_to_the_figure_only_reader(cell):
    assert n._read_paise(cell) is None
    assert n._to_paise(cell) == 0


@pytest.mark.parametrize("cell,paise", [(None, 0), ("", 0), ("-", 0), ("  ", 0), ("5,000.00", 500000), ("150.00 Dr", -15000),
                                        ("(150.00)", -15000), (12, 1200), (12.5, 1250), ("₹ 1,25,000", 12500000)])
def test_an_empty_cell_is_nil_and_a_figure_is_read_as_before(cell, paise):
    assert n._read_paise(cell) == paise
    assert n._to_paise(cell) == paise


def test_on_a_two_column_statement_the_row_is_named_and_is_neither_a_transaction_nor_a_balance_marker():
    parsed = n.parse_statement_detailed("s.csv", TWO_COLUMN.encode())
    assert [t.description for t in parsed.transactions] == ["Opening Balance", "Rent", "Receipt"]
    # The genuinely empty row is still the marker it always was, and is not named.
    assert [t.is_balance_marker for t in parsed.transactions] == [True, False, False]
    assert [u.to_dict() for u in parsed.unread_rows] == [
        {"column": "debit", "cell": "12x4.00", "date": "2026-04-03", "description": "UPI to vendor"}]


def test_on_an_amount_and_marker_statement_the_row_is_named_and_a_zero_line_is_not():
    parsed = n.parse_statement_detailed("s.csv", AMOUNT_MODE.encode())
    assert [t.description for t in parsed.transactions] == ["Rent", "Receipt"]
    assert [u.to_dict() for u in parsed.unread_rows] == [
        {"column": "amount", "cell": "1.2.3", "date": "2026-04-03", "description": "UPI to vendor"}]


def test_an_unreadable_credit_is_named_by_its_own_leg():
    text = TWO_COLUMN.replace("04/04/2026,Receipt,,2000.00,5766.00", "04/04/2026,Receipt,,2OOO.00,5766.00")
    parsed = n.parse_statement_detailed("s.csv", text.encode())
    assert [(u.column, u.cell) for u in parsed.unread_rows] == [("debit", "12x4.00"), ("credit", "2OOO.00")]


def test_a_row_whose_date_cannot_be_read_is_named_when_it_carries_a_figure_and_not_otherwise():
    text = ("Date,Description,Debit,Credit,Balance\n"
            "02/04/2026,Rent,5000.00,,5000.00\n"
            "3rd April,Cheque 1042,100.00,,4900.00\n"           # a transaction whose date is not one: named
            "Note,Charges are as per the schedule,,,\n"          # words and no figure: a sub-header, not named
            "Total,Grand Total,5100.00,0.00,\n")                 # the statement's own totals row: read elsewhere, not named
    parsed = n.parse_statement_detailed("s.csv", text.encode())
    assert [t.description for t in parsed.transactions] == ["Rent"]
    assert [u.to_dict() for u in parsed.unread_rows] == [
        {"column": "date", "cell": "3rd April", "date": None, "description": "Cheque 1042"}]


def test_the_sentence_names_up_to_three_and_counts_the_rest():
    one = [n.UnreadRow("debit", "12x4.00", "2026-04-03", "UPI to vendor")]
    assert n.unread_sentence(one) == (
        '1 row of the file could not be read and is not in these figures: 2026-04-03, "UPI to vendor" (debit printed as "12x4.00"). '
        "Correct it in the file, or check the column mapping, and upload it again.")
    five = [n.UnreadRow("amount", f"x{i}", "2026-04-03", f"Row {i}") for i in range(5)]
    said = n.unread_sentence(five)
    assert said.startswith("5 rows of the file could not be read and are not in these figures: ")
    assert '"Row 2"' in said and '"Row 3"' not in said and said.count("printed as") == 3
    assert "; and 2 more. Correct them in the file" in said
    assert n.unread_sentence([]) is None and n.unread_sentence(None) is None


def test_a_file_in_which_nothing_could_be_read_says_which_rows():
    text = "Date,Description,Debit,Credit,Balance\n03/04/2026,UPI to vendor,12x4.00,,3766.00\n"
    with pytest.raises(StatementParseError) as refused:
        n.parse_statement_detailed("s.csv", text.encode())
    assert "No transactions found" in str(refused.value)
    assert '"UPI to vendor" (debit printed as "12x4.00")' in str(refused.value)


def test_a_file_with_nothing_unread_carries_none():
    clean = TWO_COLUMN.replace("12x4.00", "1234.00")
    parsed = n.parse_statement_detailed("s.csv", clean.encode())
    assert parsed.unread_rows == () and len(parsed.transactions) == 4


# ── the routes ──────────────────────────────────────────────────────────────────────────────────────────────────────────

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}
MAPPING = {"date": 0, "desc": 1, "debit": 2, "credit": 3, "balance": 4}
NAMED = [{"column": "debit", "cell": "12x4.00", "date": "2026-04-03", "description": "UPI to vendor"}]


def _post(path, text, **form):
    return client.post(path, headers=HEADERS, files={"file": ("statement.csv", text.encode(), "text/csv")},
                       data={"client_id": "client-001", "bank_account_id": "ba-1", **form})


@pytest.mark.usefixtures("dev_header_auth")
def test_the_preview_names_the_rows_before_anything_is_imported():
    res = _post("/api/banking/statements/preview", TWO_COLUMN, column_mapping=json.dumps(MAPPING))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["unread_rows"] == NAMED
    assert data["unread_note"].startswith("1 row of the file could not be read")
    clean = _post("/api/banking/statements/preview", TWO_COLUMN.replace("12x4.00", "1234.00"), column_mapping=json.dumps(MAPPING))
    assert clean.json()["data"]["unread_rows"] == [] and clean.json()["data"]["unread_note"] is None


@pytest.mark.usefixtures("dev_header_auth")
def test_an_import_that_goes_in_says_which_row_is_missing():
    res = _post("/api/banking/statements/upload", TWO_COLUMN)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["unread_rows"] == NAMED and data["unread_note"].startswith("1 row of the file could not be read")
    assert data["verified"] is False, "nothing checked this statement, and it is short by a row: it must not read as verified"


@pytest.mark.usefixtures("dev_header_auth")
def test_an_import_refused_for_not_adding_up_names_the_row_in_the_refusal():
    # The two balances are the statement's own: 10,000 opening, 5,766 closing. The parse is short by the unread row, so it does not tie.
    res = _post("/api/banking/statements/upload", TWO_COLUMN, opening_balance_paise="1000000", closing_balance_paise="576600")
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["unread_rows"] == NAMED
    assert '"UPI to vendor" (debit printed as "12x4.00")' in detail["message"]
