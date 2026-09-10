"""
The statement's OWN totals, checked without anybody being asked for anything.

WHY THIS EXISTS
    `tie_out` is the strongest check in the import — it is the only thing that
    can say the file is the whole period — and it needs two figures typed in. An
    optional manual check on a 300-line statement is one that mostly does not
    happen, so most imports were verified by nothing.

    But most Indian statements END WITH THEIR OWN TOTALS. The 33-page Cosmos
    Co-op statement this was built against prints

        Grand Total   251528.32   252361.07

    so the evidence that every line was read is usually already IN THE FILE, and
    asking the CA for it was asking them to retype what the bank had written
    down. `printed_totals` finds that row; `totals_agreement` sums the parse
    against it; `statement_check` runs both checks and decides.

WHY IT IS A THIRD CHECK AND NOT A REPLACEMENT FOR EITHER
    Three questions, three answers, and none implies another:

      balance_agreement   do the rows agree with each other?   (blind to rows
                          dropped off either END — what remains is still a
                          consistent delta chain)
      totals_agreement    do the rows agree with what the bank printed on this
                          file?                                (blind to a file
                          that is only part of the period)
      tie_out             do the rows carry the account from the opening balance
                          to the closing one?                   (needs a human)

    The dropped-tail case below is the one that separates the first two, and it
    is the case the real world produces: an export that stopped a page early.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from domain.banking.normalizer import (
    balance_agreement, parse_statement_detailed,
)
from domain.banking.tie_out import (
    printed_totals, statement_check, totals_agreement,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-TOT"
CLIENT = "CLI-TOT"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}

# The six-column cheque layout Cosmos Co-op prints, with the totals row it ends
# on. Deliberately NOT the HDFC seven-column shape: this file is the one that
# used to be refused outright, and it is the one that carries the totals.
_HEAD = b"Date,Particulars,Cheque No,Withdrawal,Deposit,Balance\n"
_ROW1 = b"01/04/2026,UPI ACME TRADERS,,,50000.00,150000.00\n"
_ROW2 = b"02/04/2026,NEFT SUPPLIER LTD,000123,20000.00,,130000.00\n"


def _csv(*, total_debits="20000.00", total_credits="50000.00",
         label="Grand Total", rows=(_ROW1, _ROW2)) -> bytes:
    body = b"".join(rows)
    tail = (f"{label},,,{total_debits},{total_credits},\n").encode()
    return _HEAD + body + tail


# ══════════════════════════════════════════════════════════════════════════════
# Finding the row
# ══════════════════════════════════════════════════════════════════════════════

def test_the_grand_total_row_is_found_and_read():
    parsed = parse_statement_detailed("stmt.csv", _csv())
    assert len(parsed.transactions) == 2, "the totals row must not become a transaction"
    assert parsed.printed_totals == {
        "label": "Grand Total",
        "total_debits_paise": 20_000_00,
        "total_credits_paise": 50_000_00,
    }


@pytest.mark.parametrize("label", ["Grand Total", "Total", "Totals", "TOTAL", "total:"])
def test_the_labels_indian_statements_actually_use(label):
    assert parse_statement_detailed("stmt.csv", _csv(label=label)).printed_totals


def test_a_statement_with_no_totals_row_simply_has_none():
    """Not an error and not a guess. Plenty of exports print no totals, and the
    balances are then the only way to check them."""
    parsed = parse_statement_detailed(
        "stmt.csv", _HEAD + _ROW1 + _ROW2)
    assert parsed.printed_totals is None


def test_three_numbers_in_the_row_are_refused_rather_than_guessed():
    """A totals row does not follow the column mapping — the label is in column
    0 and the figures sit wherever the bank put them — so they are read
    positionally, and that is only safe with exactly TWO of them. A third could
    be a closing balance and there would be no way to tell which two are the
    totals. A totals check that is right most of the time is worse than one that
    says it could not find them."""
    row = b"Grand Total,,,20000.00,50000.00,130000.00\n"
    parsed = parse_statement_detailed("stmt.csv", _HEAD + _ROW1 + _ROW2 + row)
    assert parsed.printed_totals is None


def test_the_order_comes_from_the_adapter_and_not_from_a_guess():
    """A bank that prints Deposit before Withdrawal prints its totals in that
    order too. Reading the first figure as a debit because debits usually come
    first would invert the check on exactly the file it is meant to catch."""
    head = b"Date,Particulars,Chq,Deposit,Withdrawal,Balance\n"
    body = (b"01/04/2026,UPI ACME TRADERS,,50000.00,,150000.00\n"
            b"02/04/2026,NEFT SUPPLIER LTD,000123,,20000.00,130000.00\n")
    tail = b"Grand Total,,,50000.00,20000.00,\n"
    mapping = {"date": 0, "desc": 1, "ref": 2, "credit": 3, "debit": 4, "balance": 5}
    parsed = parse_statement_detailed("stmt.csv", head + body + tail, mapping)
    assert parsed.printed_totals["total_credits_paise"] == 50_000_00
    assert parsed.printed_totals["total_debits_paise"] == 20_000_00
    assert totals_agreement(parsed.transactions, parsed.printed_totals)["agrees"] is True


def test_a_date_is_not_mistaken_for_a_total():
    """`_to_paise` will happily read "01/04/2026" as something. The shape is
    checked before the value, so a totals row that repeats the period does not
    turn a date into money."""
    tail = b"Total,01/04/2026,,20000.00,50000.00,\n"
    parsed = parse_statement_detailed("stmt.csv", _HEAD + _ROW1 + _ROW2 + tail)
    assert parsed.printed_totals["total_debits_paise"] == 20_000_00


# ══════════════════════════════════════════════════════════════════════════════
# Checking against it
# ══════════════════════════════════════════════════════════════════════════════

def test_a_parse_that_matches_the_printed_totals_agrees():
    parsed = parse_statement_detailed("stmt.csv", _csv())
    got = totals_agreement(parsed.transactions, parsed.printed_totals)
    assert got["checked"] is True and got["agrees"] is True
    assert got["debit_difference_paise"] == 0
    assert got["credit_difference_paise"] == 0


def test_a_dropped_row_is_caught_HERE_and_not_by_balance_agreement():
    """THE CASE THAT SEPARATES THE TWO CHECKS, and the one the real world
    produces: an export that stopped a page early.

    Remove a row from the END and every remaining pair of balances still agrees
    — a truncated delta chain is a perfectly consistent delta chain. The
    statement's own totals still describe the whole statement, so they do not.
    """
    row3 = b"03/04/2026,NEFT OTHER SUPPLIER,000124,15000.00,,115000.00\n"
    # Three rows' worth of totals, two rows in the file.
    truncated = _csv(total_debits="35000.00", rows=(_ROW1, _ROW2))
    assert len(parse_statement_detailed(
        "stmt.csv", _csv(total_debits="35000.00",
                         rows=(_ROW1, _ROW2, row3))).transactions) == 3
    parsed = parse_statement_detailed("stmt.csv", truncated)
    assert balance_agreement(parsed.transactions)["agrees"] is True, \
        "the surviving rows are self-consistent — that is the whole point"
    got = totals_agreement(parsed.transactions, parsed.printed_totals)
    assert got["agrees"] is False
    assert "Grand Total" in got["reason"]
    assert "₹35,000.00" in got["reason"], "Indian digit grouping"


def test_the_refusal_names_which_side_is_wrong():
    parsed = parse_statement_detailed("stmt.csv", _csv(total_credits="60000.00"))
    got = totals_agreement(parsed.transactions, parsed.printed_totals)
    assert got["agrees"] is False
    assert "deposits" in got["reason"] and "withdrawals" not in got["reason"]


def test_no_printed_totals_names_itself_as_a_gap():
    got = totals_agreement([], None)
    assert got["checked"] is False
    assert "does not print its own totals" in got["gap"]


# ══════════════════════════════════════════════════════════════════════════════
# The two checks together
# ══════════════════════════════════════════════════════════════════════════════

def _two_rows():
    return parse_statement_detailed("stmt.csv", _csv())


def test_printed_totals_alone_are_enough_to_call_an_import_verified():
    """The whole point: nothing was typed in, and the import is still checked."""
    parsed = _two_rows()
    got = statement_check(parsed.transactions, opening_paise=None,
                          closing_paise=None, printed=parsed.printed_totals)
    assert got["verified"] is True
    assert got["refusal"] is None and got["gap"] is None


def test_with_neither_piece_of_evidence_nothing_is_claimed():
    got = statement_check([], opening_paise=None, closing_paise=None, printed=None)
    assert got["verified"] is False and got["refusal"] is None
    assert "no totals of its own" in got["gap"]


def test_a_totals_mismatch_refuses_even_when_the_balances_were_not_given():
    parsed = parse_statement_detailed("stmt.csv", _csv(rows=(_ROW1,)))
    got = statement_check(parsed.transactions, opening_paise=None,
                          closing_paise=None, printed=parsed.printed_totals)
    assert got["verified"] is False
    assert "Grand Total" in got["refusal"]


def test_matching_totals_with_failing_balances_says_the_reading_was_fine():
    """Both checks fail differently and the difference is worth saying. If the
    rows sum to the statement's own totals, nothing was misread — so sending the
    CA to look for a mapping error would send them after a bug that is not
    there. What is wrong is the balances, or the period the file covers."""
    parsed = _two_rows()
    got = statement_check(parsed.transactions, opening_paise=1_00_000_00,
                          closing_paise=1_25_000_00, printed=parsed.printed_totals)
    assert got["verified"] is False
    assert "nothing was missed in the reading" in got["refusal"]
    assert "period" in got["refusal"]


def test_both_agreeing_is_verified():
    parsed = _two_rows()
    got = statement_check(parsed.transactions, opening_paise=1_00_000_00,
                          closing_paise=1_30_000_00, printed=parsed.printed_totals)
    assert got["verified"] is True
    assert got["tie_out"]["agrees"] is True
    assert got["totals_check"]["agrees"] is True


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint — the part that would otherwise be an unwired helper
# ══════════════════════════════════════════════════════════════════════════════

def _setup(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, [banking, cust, ven, obs])
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, CLIENT)
    return db


class _Upload:
    """The slice of UploadFile a SYNC route uses.

    The route is plain `def` (see tests/test_a_blocking_route_is_not_async.py),
    so Starlette runs it in a threadpool and it reads the upload through
    `.file` — the SpooledTemporaryFile — rather than awaiting `.read()`. That
    is what a real UploadFile offers, so the double offers it too.
    """
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content
        self.file = io.BytesIO(content)

    async def read(self):
        return self._content


def _upload(**kw):
    # asyncio.run, not get_event_loop() — see test_statement_pdf_and_tie_out.
    import asyncio
    return banking.upload_statement(
            file=_Upload(kw.pop("filename", "stmt.csv"), kw.pop("content", _csv())),
            client_id=CLIENT, bank_name="Cosmos Co-op Bank", account_number=None,
            bank_account_id=None, column_mapping=None, save_mapping=False,
            opening_balance_paise=kw.pop("opening", None),
            closing_balance_paise=kw.pop("closing", None),
            current_user=CALLER)


def test_the_endpoint_verifies_an_upload_with_nothing_typed_in(monkeypatch):
    db = _setup(monkeypatch)
    res = _upload()
    data = res["data"]
    assert data["verified"] is True, "the statement's own totals verified it"
    assert data["verification_gap"] is None
    assert data["totals_check"]["agrees"] is True
    assert data["tie_out"]["checked"] is False, "no balances were given"
    assert db.rows("bank_transactions")


def test_the_endpoint_refuses_a_statement_that_misses_its_own_totals(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(content=_csv(rows=(_ROW1,)))
    assert e.value.status_code == 422
    assert "Grand Total" in str(e.value.detail)
    assert not db.rows("bank_transactions"), "a refused import wrote transactions"
    assert not db.rows("bank_statements"), "a refused import wrote a statement"


def test_a_statement_with_no_totals_and_no_balances_still_imports_unverified(monkeypatch):
    """An import that used to work keeps working — but it must not come back
    looking verified, which is the whole reason `verified` is a field."""
    db = _setup(monkeypatch)
    res = _upload(content=_HEAD + _ROW1 + _ROW2)
    assert res["data"]["verified"] is False
    assert "no totals of its own" in res["data"]["verification_gap"]
    assert db.rows("bank_transactions")


def test_the_preview_screen_shows_the_totals_check_too(monkeypatch):
    """The preview is where a mapping is judged before importing under it, and a
    mapping whose parse does not sum to the statement's own totals is wrong
    however plausible the twenty rows above it look."""
    import asyncio
    import json
    _setup(monkeypatch)
    mapping = {"date": 0, "desc": 1, "ref": 2, "debit": 3, "credit": 4, "balance": 5}
    res = banking.preview_statement_with_mapping(
        file=_Upload("stmt.csv", _csv()), client_id=CLIENT,
        column_mapping=json.dumps(mapping), current_user=CALLER)
    assert res["data"]["totals_check"]["agrees"] is True


def test_the_six_column_cosmos_layout_needs_no_mapping_at_the_endpoint(monkeypatch):
    """End to end, on the shape that prompted all of this: a real Cosmos Co-op
    statement was detected as HDFC (they share the "cheque" signal) and then
    refused, because HDFC wants a balance in column 6 and this has one in 5."""
    _setup(monkeypatch)
    res = _upload()
    assert res["data"]["column_source"] == "detected"
    assert res["data"]["imported"] == 2
