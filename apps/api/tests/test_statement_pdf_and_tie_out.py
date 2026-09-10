"""
Two changes to statement import, and they exist because of each other.

WHY A TIE-OUT
    `balance_agreement` already checks the bank's running-balance column between
    consecutive rows, and it is good: swap debit and credit and every row
    disagrees at once. But it is an INTERNAL check — it asks whether the rows
    agree with each other, never whether they agree with the statement. It goes
    quiet entirely when there is no balance column, and it cannot see rows
    dropped off either END of the file, because what remains is still a
    perfectly consistent delta chain.

    `opening + credits - debits == closing`, against the two figures the bank
    PRINTS, is a different question asked of evidence outside the file.

WHY PDF
    Most Indian banks email a PDF. TallyPrime cannot import one at all — its own
    documentation says convert it to CSV first — which is why a small industry
    of PDF-to-Tally converters exists.

WHY THEY SHIP TOGETHER
    A PDF is a layout, not a data format, so a parser will meet statements it
    reads imperfectly. The tie-out is what turns "silently wrong number" into
    "refused import", and it is the reason the geometric fallback below is safe
    to offer at all.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from domain.banking.normalizer import (
    StatementParseError, inspect_statement, parse_statement, balance_agreement,
)
from domain.banking.tie_out import tie_out, totals
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-TIE"
CLIENT = "CLI-TIE"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}


def _txn(debit=0, credit=0):
    return SimpleNamespace(debit_paise=debit, credit_paise=credit)


# ══════════════════════════════════════════════════════════════════════════════
# The tie-out
# ══════════════════════════════════════════════════════════════════════════════

def test_a_statement_that_adds_up_agrees():
    rows = [_txn(credit=50_000_00), _txn(debit=20_000_00)]
    got = tie_out(rows, opening_paise=1_00_000_00, closing_paise=1_30_000_00)
    assert got["checked"] and got["agrees"]
    assert got["difference_paise"] == 0


def test_a_statement_that_does_not_add_up_says_so_with_both_figures():
    rows = [_txn(credit=50_000_00), _txn(debit=20_000_00)]
    got = tie_out(rows, opening_paise=1_00_000_00, closing_paise=1_25_000_00)
    assert got["checked"] and not got["agrees"]
    assert got["difference_paise"] == 5_000_00
    # The CA has to be able to see WHICH number the file failed to reach.
    assert "₹1,30,000.00" in got["reason"], "the computed closing"
    assert "₹1,25,000.00" in got["reason"], "the statement's own closing"
    assert "Nothing has been imported" in got["reason"]


@pytest.mark.parametrize("paise,expected", [
    (13000000, "₹1,30,000.00"),
    (100000000, "₹10,00,000.00"),
    (1234567890, "₹1,23,45,678.90"),
    (100000, "₹1,000.00"),
    (-13000000, "-₹1,30,000.00"),
])
def test_the_refusal_is_written_in_indian_digit_grouping(paise, expected):
    """Three digits then twos — 1,30,000 and not 130,000. The sentence is read
    beside a bank statement and compared against it, and this repository already
    carries a scar from the other direction: parseFloat("1,25,000") is 1."""
    from domain.banking.tie_out import _r
    assert _r(paise) == expected


@pytest.mark.parametrize("opening,closing", [(None, 1), (1, None), (None, None)])
def test_a_missing_balance_names_itself_as_a_gap(opening, closing):
    """An unverified import and a verified one must not look the same. Same
    shape as payroll's statutory_gaps, for the same reason."""
    got = tie_out([_txn(credit=1)], opening_paise=opening, closing_paise=closing)
    assert got["checked"] is False
    assert "gap" in got
    assert "was not given" in got["gap"]
    assert "agrees" not in got, "a gap must not read as agreement"


def test_it_is_blind_to_row_order():
    """balance_agreement needed a special case for newest-first statements
    because a reversed delta chain inverts every sign. A SUM cannot be broken
    that way, and that property belongs in the check that blocks an import."""
    rows = [_txn(credit=10_000_00), _txn(debit=3_000_00), _txn(credit=500_00)]
    forward = tie_out(rows, opening_paise=0, closing_paise=7_500_00)
    reverse = tie_out(list(reversed(rows)), opening_paise=0, closing_paise=7_500_00)
    assert forward["agrees"] and reverse["agrees"]
    assert forward["computed_closing_paise"] == reverse["computed_closing_paise"]


def test_the_arithmetic_is_integer_paise_across_many_rows():
    """300 rows of 33 paise. In float this drifts; in paise it cannot."""
    rows = [_txn(credit=33) for _ in range(300)]
    got = tie_out(rows, opening_paise=0, closing_paise=300 * 33)
    assert got["agrees"], got
    assert totals(rows) == (0, 9900)


def test_a_row_dropped_from_the_END_is_caught_here_and_not_by_balance_agreement():
    """The gap this exists for. Truncate a statement and the remaining delta
    chain is still perfectly self-consistent — balance_agreement sees nothing."""
    from domain.banking.normalizer import NormalizedTxn
    full = [
        NormalizedTxn("2026-04-01", "A", None, 0, 50_000_00, 1_50_000_00),
        NormalizedTxn("2026-04-02", "B", None, 20_000_00, 0, 1_30_000_00),
        NormalizedTxn("2026-04-03", "C", None, 5_000_00, 0, 1_25_000_00),
    ]
    truncated = full[:2]
    assert balance_agreement(truncated)["agrees"] is True, \
        "precondition: the delta chain still agrees after truncation"
    got = tie_out(truncated, opening_paise=1_00_000_00, closing_paise=1_25_000_00)
    assert not got["agrees"], "the tie-out must catch what the delta chain cannot"
    assert got["difference_paise"] == 5_000_00


# ══════════════════════════════════════════════════════════════════════════════
# Reading a PDF
# ══════════════════════════════════════════════════════════════════════════════
# Real PDFs, generated here rather than committed as fixture blobs: a binary
# nobody can read or regenerate is a fixture nobody can change.

_HEAD = ("<tr><td>Date</td><td>Narration</td><td>Value Dt</td><td>Chq/Ref No</td>"
         "<td>Withdrawal Amt.</td><td>Deposit Amt.</td><td>Closing Balance</td></tr>")
_ROWS = """
<tr><td>01/04/2026</td><td>UPI ACME TRADERS</td><td>01/04/2026</td><td>REF1</td>
    <td></td><td>50000.00</td><td>150000.00</td></tr>
<tr><td>02/04/2026</td><td>NEFT SUPPLIER LTD</td><td>02/04/2026</td><td>REF2</td>
    <td>20000.00</td><td></td><td>130000.00</td></tr>"""


def _pdf(html: str) -> bytes:
    from xhtml2pdf import pisa
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf)
    return buf.getvalue()


def _statement_pdf(*, ruled: bool) -> bytes:
    border = ' border="1"' if ruled else ""
    return _pdf(f"<html><body><table{border}>{_HEAD}{_ROWS}</table></body></html>")


@pytest.mark.parametrize("ruled", [True, False], ids=["ruled-table", "borderless"])
def test_a_pdf_statement_parses_into_transactions(ruled):
    txns = parse_statement("statement.pdf", _statement_pdf(ruled=ruled))
    assert len(txns) == 2
    assert [t.transaction_date for t in txns] == ["2026-04-01", "2026-04-02"]
    assert [(t.debit_paise, t.credit_paise) for t in txns] == [
        (0, 50_000_00), (20_000_00, 0)]
    assert [t.balance_paise for t in txns] == [1_50_000_00, 1_30_000_00]


@pytest.mark.parametrize("ruled", [True, False], ids=["ruled-table", "borderless"])
def test_a_parsed_pdf_passes_both_checks(ruled):
    txns = parse_statement("statement.pdf", _statement_pdf(ruled=ruled))
    assert balance_agreement(txns)["agrees"] is True
    assert tie_out(txns, opening_paise=1_00_000_00,
                   closing_paise=1_30_000_00)["agrees"] is True


def test_the_borderless_reader_keeps_an_empty_column_empty():
    """THE FAILURE THIS AVOIDS. Splitting a line on runs of spaces drops an
    empty cell, so every value after it shifts left and a DEPOSIT is read as a
    WITHDRAWAL — the client's cash position inverts. Row 1 here has no
    withdrawal; it must stay a deposit."""
    txns = parse_statement("statement.pdf", _statement_pdf(ruled=False))
    assert (txns[0].debit_paise, txns[0].credit_paise) == (0, 50_000_00)
    assert (txns[1].debit_paise, txns[1].credit_paise) == (20_000_00, 0)


def test_a_multi_word_heading_is_one_column_not_two():
    """"Withdrawal Amt." is one column. Split it and everything to its right
    lands one column over. The gap inside a label was measured at 2.09pt against
    22-61pt between columns, at 7.5pt type — the split is at one em."""
    headers = inspect_statement("statement.pdf", _statement_pdf(ruled=False))["headers"]
    assert headers == ["Date", "Narration", "Value Dt", "Chq/Ref No",
                       "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]


def test_a_pdf_with_no_text_layer_is_refused_and_says_why():
    """A scan is a picture of paper. Reading pixels is a vision model's job and
    is deliberately not done here — but the refusal has to say that, not return
    nothing and look like an empty statement."""
    with pytest.raises(StatementParseError) as e:
        parse_statement("scan.pdf", _pdf("<html><body></body></html>"))
    assert "scanned" in str(e.value).lower()
    assert "csv" in str(e.value).lower(), "tell them what to do instead"


def test_the_mapping_screen_can_read_a_pdf():
    """It matters MORE for PDFs: a PDF's columns come from a layout rather than
    a labelled export, so detection is likelier to miss and the CA likelier to
    need to say where things are."""
    got = inspect_statement("statement.pdf", _statement_pdf(ruled=True))
    assert got["total_rows"] == 2
    assert got["detected_fits"] is True


def test_an_unsupported_extension_now_offers_pdf():
    with pytest.raises(StatementParseError) as e:
        parse_statement("statement.docx", b"x")
    assert ".pdf" in str(e.value)


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


def _csv_bytes() -> bytes:
    return (b"Date,Narration,Value Dt,Chq/Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
            b"01/04/2026,UPI ACME TRADERS,01/04/2026,REF1,,50000.00,150000.00\n"
            b"02/04/2026,NEFT SUPPLIER LTD,02/04/2026,REF2,20000.00,,130000.00\n")


def _upload(db, monkeypatch, **kw):
    # asyncio.run, not get_event_loop().run_until_complete — this repo has no
    # pytest-asyncio, and get_event_loop() picks up whatever loop an earlier
    # test left behind. These passed alone and failed in the full suite until
    # this changed, which is the whole tell.
    import asyncio
    return banking.upload_statement(
            file=_Upload(kw.pop("filename", "stmt.csv"), kw.pop("content", _csv_bytes())),
            client_id=CLIENT, bank_name="HDFC Bank", account_number=None,
            bank_account_id=None, column_mapping=None, save_mapping=False,
            opening_balance_paise=kw.pop("opening", None),
            closing_balance_paise=kw.pop("closing", None),
            acknowledge_totals_mismatch=kw.pop("acknowledge", None),
            current_user=CALLER)


def test_the_endpoint_refuses_a_statement_that_does_not_add_up(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(db, monkeypatch, opening=1_00_000_00, closing=1_25_000_00)
    assert e.value.status_code == 422
    assert "does not add up" in str(e.value.detail)


def test_a_refused_statement_imports_NOTHING(monkeypatch):
    """The tie-out runs BEFORE the write. Reporting "it does not add up" beside
    rows already in the ledger would be a finding nobody can act on."""
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException):
        _upload(db, monkeypatch, opening=1_00_000_00, closing=1_25_000_00)
    assert not db.rows("bank_transactions"), "a refused import wrote transactions"
    assert not db.rows("bank_statements"), "a refused import wrote a statement"


def test_a_statement_that_ties_out_imports(monkeypatch):
    db = _setup(monkeypatch)
    res = _upload(db, monkeypatch, opening=1_00_000_00, closing=1_30_000_00)
    assert res["success"] is True
    assert res["data"]["tie_out"]["agrees"] is True
    assert db.rows("bank_transactions"), "a tying statement did not import"


def test_an_upload_without_the_balances_still_works_and_names_the_gap(monkeypatch):
    """Every existing caller omits them. An import that used to work must keep
    working — but it must not come back looking verified."""
    db = _setup(monkeypatch)
    res = _upload(db, monkeypatch)
    assert res["data"]["tie_out"]["checked"] is False
    assert "was not given" in res["data"]["tie_out"]["gap"]
    assert db.rows("bank_transactions")


def test_a_pdf_reaches_the_endpoint_and_is_recorded_as_a_pdf(monkeypatch):
    db = _setup(monkeypatch)
    res = _upload(db, monkeypatch, filename="stmt.pdf",
                  content=_statement_pdf(ruled=True),
                  opening=1_00_000_00, closing=1_30_000_00)
    assert res["data"]["tie_out"]["agrees"] is True
    stmt = db.rows("bank_statements")
    assert stmt and stmt[0].get("source_format") == "pdf", \
        "the file format must be recorded as what it was"
