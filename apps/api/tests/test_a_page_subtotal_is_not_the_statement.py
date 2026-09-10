"""
BANK-01: a page subtotal labelled "Total" refused the import outright.

WHAT WAS WRONG

`printed_totals` returned the FIRST row whose first cell matched the totals
label and which carried exactly two numeric cells. On a multi-page statement
that is a PAGE SUBTOTAL. The parse — which covers every page — then disagreed
with it, `statement_check` treated the disagreement as a failed check, and the
router refused the upload with 422 before writing anything. The message told the
CA to check their debit/credit column mapping, when no mapping was involved and
nothing had been misread.

Per-page and per-month subtotals labelled "Total" are ordinary in Indian bank
PDF and Excel exports, so a perfectly good statement could not be imported at
all. The only way past it was to edit the bank's file by hand, which destroys
the evidence the check exists to read.

WHAT IT IS NOW

The FILE has to say which row totals the whole statement, and there are two ways
it can: it prints one totals row, or it prints several and exactly one of them
is labelled "Grand Total". Anything else is ambiguous and is REPORTED as
ambiguous — the check is not made, the import falls back to the typed balances
exactly as it does for a statement that prints no totals at all, and the CA is
told which of the two cases they are in.

And where the check IS made and genuinely fails, it is a stop rather than a
wall: a CA who has compared the figures themselves may import over it by writing
down why, which is stored on the statement row beside the two differences it
excused (migration 354). The import is not `verified` and does not pretend to be.

WHAT IS DELIBERATELY NOT DONE: pick whichever candidate agrees with the parsed
sums. `test_the_choice_never_looks_at_the_parsed_sums` is the guard — that rule
would make the check prove itself, and the whole value of this evidence is that
it comes from outside the reading being checked.
"""
import io

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from domain.banking.normalizer import _TOTAL_LABEL, parse_statement_detailed
from domain.banking.tie_out import (
    _GRAND_LABEL, printed_totals, statement_check, totals_agreement,
    totals_candidates,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-SUB"
CLIENT = "CLI-SUB"
CALLER = {"firm_id": FIRM, "id": "u-internal-7", "auth_user_id": "auth-7",
          "email": "ca@firm.test", "role": "Partner"}

# The six-column cheque layout, printed across two pages the way a real export
# does: each page ends with its own "Total", and the statement ends with the
# "Grand Total".
_HEAD = b"Date,Particulars,Cheque No,Withdrawal,Deposit,Balance\n"
_PAGE1 = b"01/04/2026,UPI ACME TRADERS,,,50000.00,150000.00\n"
_PAGE2 = b"02/04/2026,NEFT SUPPLIER LTD,000123,20000.00,,130000.00\n"


def _line(label: str, debits: str, credits: str) -> bytes:
    return f"{label},,,{debits},{credits},\n".encode()


#: Two pages, each subtotalled, then the grand total. This is the file the
#: import used to refuse.
_TWO_PAGES = (_HEAD
              + _PAGE1 + _line("Total", "0.00", "50000.00")
              + _PAGE2 + _line("Total", "20000.00", "0.00")
              + _line("Grand Total", "20000.00", "50000.00"))

_ADAPTER = {"date": 0, "description": 1, "ref": 2, "debit": 3, "credit": 4, "balance": 5}


def _rows(csv: bytes) -> list[list[str]]:
    return [line.split(",") for line in csv.decode().splitlines()]


# ══════════════════════════════════════════════════════════════════════════════
# Finding the candidates, and choosing between them
# ══════════════════════════════════════════════════════════════════════════════

def test_every_totals_row_is_found_not_just_the_first():
    got = totals_candidates(_rows(_TWO_PAGES), _ADAPTER)
    assert [c["label"] for c in got] == ["Total", "Total", "Grand Total"]
    assert got[0] == {"label": "Total", "total_debits_paise": 0,
                      "total_credits_paise": 50_000_00}


def test_the_grand_total_wins_over_the_page_subtotals():
    """The whole bug in one assertion. Before this change `printed_totals`
    returned the first page's subtotal — 0 withdrawals — and the parse's
    ₹20,000 of withdrawals was reported as a discrepancy."""
    got = printed_totals(_rows(_TWO_PAGES), _ADAPTER)
    assert got["label"] == "Grand Total"
    assert got["total_debits_paise"] == 20_000_00
    assert got["total_credits_paise"] == 50_000_00
    assert not got.get("ambiguous")


def test_a_single_totals_row_is_still_simply_used():
    """No regression for the ordinary statement: one totals row, no choosing."""
    one = _HEAD + _PAGE1 + _PAGE2 + _line("Total", "20000.00", "50000.00")
    got = printed_totals(_rows(one), _ADAPTER)
    assert got["label"] == "Total" and got["total_debits_paise"] == 20_000_00


def test_several_totals_and_no_grand_total_is_ambiguous_not_a_guess():
    no_grand = (_HEAD
                + _PAGE1 + _line("Total", "0.00", "50000.00")
                + _PAGE2 + _line("Total", "20000.00", "0.00"))
    got = printed_totals(_rows(no_grand), _ADAPTER)
    assert got["ambiguous"] is True
    assert got["candidates"] == 2
    assert "page or month subtotals" in got["gap"]
    assert "opening and closing balances" in got["gap"], (
        "an ambiguity has to name what the CA can do instead")


def test_two_grand_totals_are_ambiguous_too():
    """"Exactly one" means exactly one. A file that says "Grand Total" twice has
    not distinguished anything."""
    twice = (_HEAD + _PAGE1 + _line("Grand Total", "0.00", "50000.00")
             + _PAGE2 + _line("Grand Total", "20000.00", "50000.00"))
    assert printed_totals(_rows(twice), _ADAPTER)["ambiguous"] is True


def test_the_choice_never_looks_at_the_parsed_sums():
    """The obvious fix — take whichever candidate matches what we parsed — is
    the one thing this must not do. It would make the check prove itself: a
    misread statement would simply select the row that agreed with the misreading.

    Here the SECOND "Total" is cumulative and equals the parse exactly. It is
    still not chosen, because nothing in the file says it is the whole."""
    cumulative = (_HEAD
                  + _PAGE1 + _line("Total", "0.00", "50000.00")
                  + _PAGE2 + _line("Total", "20000.00", "50000.00"))
    parsed = parse_statement_detailed("stmt.csv", cumulative)
    assert len(parsed.transactions) == 2
    assert parsed.printed_totals["ambiguous"] is True, (
        "a candidate was chosen because it agreed with the parse")


def test_the_grand_label_is_a_subset_of_the_totals_label():
    """The two patterns live in different modules and must not drift: a row this
    one matches and the normalizer's does not would be a totals row the parser
    never skipped, which would make it a transaction."""
    for label in ("Grand Total", "grand totals", "  GRAND TOTAL :", "Grand Total:"):
        assert _GRAND_LABEL.match(label), label
        assert _TOTAL_LABEL.match(label), f"{label!r} is not a totals label"
    for not_grand in ("Total", "Totals", "Page Total", "Grand"):
        assert not _GRAND_LABEL.match(not_grand), not_grand


# ══════════════════════════════════════════════════════════════════════════════
# What the checks say about an ambiguous statement
# ══════════════════════════════════════════════════════════════════════════════

def _ambiguous():
    return printed_totals(_rows(
        _HEAD + _PAGE1 + _line("Total", "0.00", "50000.00")
        + _PAGE2 + _line("Total", "20000.00", "0.00")), _ADAPTER)


def test_ambiguous_is_reported_as_unchecked_and_not_as_absent():
    """"This statement does not print its own totals" in front of a statement
    that visibly does would send somebody looking for a parsing bug."""
    got = totals_agreement([], _ambiguous())
    assert got["checked"] is False and got["ambiguous"] is True
    assert "does not print its own totals" not in got["gap"]
    assert "2 totals rows" in got["gap"]


def test_an_ambiguous_statement_is_not_refused():
    got = statement_check([], opening_paise=None, closing_paise=None,
                          printed=_ambiguous())
    assert got["refusal"] is None, "ambiguity must not block the import"
    assert got["verified"] is False
    assert "2 totals rows" in got["gap"] and "0 transactions were parsed" in got["gap"]


def test_typed_balances_still_verify_an_ambiguous_statement():
    parsed = parse_statement_detailed("stmt.csv", _HEAD + _PAGE1 + _PAGE2
                                      + _line("Total", "0.00", "50000.00")
                                      + _line("Total", "20000.00", "0.00"))
    got = statement_check(parsed.transactions, opening_paise=1_00_000_00,
                          closing_paise=1_30_000_00, printed=parsed.printed_totals)
    assert got["verified"] is True and got["refusal"] is None


# ══════════════════════════════════════════════════════════════════════════════
# The refusal that remains, and what it says
# ══════════════════════════════════════════════════════════════════════════════

def _mismatch():
    """One line read, a totals row that says there were two."""
    return parse_statement_detailed(
        "stmt.csv", _HEAD + _PAGE1 + _line("Grand Total", "20000.00", "50000.00"))


def test_the_refusal_names_the_third_explanation_and_the_way_past():
    got = totals_agreement(_mismatch().transactions, _mismatch().printed_totals)
    assert got["agrees"] is False
    assert "does not cover the same lines this file does" in got["reason"], (
        "the bank's own row not being comparable is a real third case")
    assert "import it again with a note saying why" in got["reason"], (
        "a refusal with no way past is a wall")


def test_a_refusal_carries_a_code_for_the_screen_to_act_on():
    got = statement_check(_mismatch().transactions, opening_paise=None,
                          closing_paise=None, printed=_mismatch().printed_totals)
    assert got["refusal_code"] == "totals_mismatch"
    tie = statement_check([], opening_paise=0, closing_paise=1_00, printed=None)
    assert tie["refusal_code"] == "tie_out"


# ══════════════════════════════════════════════════════════════════════════════
# The acknowledgement
# ══════════════════════════════════════════════════════════════════════════════

REASON = "the export was filtered to UPI only; the printed total covers the month"


def test_an_acknowledged_mismatch_stops_refusing_but_is_never_verified():
    parsed = _mismatch()
    got = statement_check(parsed.transactions, opening_paise=None, closing_paise=None,
                          printed=parsed.printed_totals,
                          totals_mismatch_acknowledged=True)
    assert got["refusal"] is None and got["acknowledged"] is True
    assert got["verified"] is False, (
        "something in the file contradicts the parse; a note does not unsay it")
    assert "accepted anyway, on a written note" in got["gap"]
    assert "Nothing else confirmed" in got["gap"]


def test_an_acknowledgement_does_not_clear_the_tie_out():
    """The asymmetry is the point: the balances were typed into this same
    request, so a CA who does not want that check simply does not type them.
    There is nothing to acknowledge — only a figure to correct or omit."""
    parsed = _mismatch()
    got = statement_check(parsed.transactions, opening_paise=1_00_000_00,
                          closing_paise=9_99_999_00, printed=parsed.printed_totals,
                          totals_mismatch_acknowledged=True)
    assert got["refusal"] is not None and got["refusal_code"] == "tie_out"


def test_an_acknowledged_import_whose_balances_tie_out_says_so():
    parsed = _mismatch()
    got = statement_check(parsed.transactions, opening_paise=1_00_000_00,
                          closing_paise=1_50_000_00, printed=parsed.printed_totals,
                          totals_mismatch_acknowledged=True)
    assert got["acknowledged"] is True and got["verified"] is False
    assert "balances given do tie out" in got["gap"]


def test_acknowledging_a_check_that_passed_changes_nothing():
    ok = parse_statement_detailed("stmt.csv", _HEAD + _PAGE1 + _PAGE2
                                  + _line("Grand Total", "20000.00", "50000.00"))
    got = statement_check(ok.transactions, opening_paise=None, closing_paise=None,
                          printed=ok.printed_totals, totals_mismatch_acknowledged=True)
    assert got["acknowledged"] is False and got["verified"] is True


# ══════════════════════════════════════════════════════════════════════════════
# End to end, through the endpoint that used to refuse
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
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content
        self.file = io.BytesIO(content)

    async def read(self):
        return self._content


def _upload(**kw):
    return banking.upload_statement(
        file=_Upload(kw.pop("filename", "stmt.csv"), kw.pop("content", _TWO_PAGES)),
        client_id=CLIENT, bank_name="Cosmos Co-op Bank", account_number=None,
        bank_account_id=None, column_mapping=None, save_mapping=False,
        opening_balance_paise=kw.pop("opening", None),
        closing_balance_paise=kw.pop("closing", None),
        allow_vision=kw.pop("allow_vision", False),
        acknowledge_totals_mismatch=kw.pop("acknowledge", None),
        current_user=CALLER)


def test_a_two_page_statement_imports_and_is_verified(monkeypatch):
    """BANK-01 reproduced end to end. This upload used to raise 422."""
    db = _setup(monkeypatch)
    data = _upload()["data"]
    assert data["verified"] is True
    assert data["totals_check"]["label"] == "Grand Total"
    assert data["imported"] == 2
    assert len(db.rows("bank_transactions")) == 2, (
        "the subtotal rows must not become transactions")


def test_page_subtotals_with_no_grand_total_import_unverified(monkeypatch):
    db = _setup(monkeypatch)
    no_grand = (_HEAD + _PAGE1 + _line("Total", "0.00", "50000.00")
                + _PAGE2 + _line("Total", "20000.00", "0.00"))
    data = _upload(content=no_grand)["data"]
    assert data["verified"] is False, "nothing checked it, and it says so"
    assert "2 totals rows" in data["verification_gap"]
    assert len(db.rows("bank_transactions")) == 2, "it still imported"


def test_a_genuine_mismatch_is_still_refused_with_a_code(monkeypatch):
    db = _setup(monkeypatch)
    one_line = _HEAD + _PAGE1 + _line("Grand Total", "20000.00", "50000.00")
    with pytest.raises(HTTPException) as e:
        _upload(content=one_line)
    assert e.value.status_code == 422
    assert e.value.detail["code"] == "totals_mismatch"
    assert "Grand Total" in e.value.detail["message"]
    assert not db.rows("bank_transactions") and not db.rows("bank_statements")


def test_the_acknowledgement_imports_and_lands_on_the_statement_row(monkeypatch):
    db = _setup(monkeypatch)
    one_line = _HEAD + _PAGE1 + _line("Grand Total", "20000.00", "50000.00")
    data = _upload(content=one_line, acknowledge=REASON)["data"]
    assert data["imported"] == 1
    assert data["verified"] is False
    assert data["totals_mismatch_acknowledged"] is True

    stmt = db.rows("bank_statements")[0]
    assert stmt["totals_mismatch_reason"] == REASON
    # The reason sits beside the figures it excused — parsed minus printed.
    assert stmt["totals_mismatch_debit_difference_paise"] == -20_000_00
    assert stmt["totals_mismatch_credit_difference_paise"] == 0
    assert stmt["totals_mismatch_acknowledged_at"]
    # public.users.id, NOT the Supabase auth id — the column FKs users(id).
    assert stmt["totals_mismatch_acknowledged_by"] == "u-internal-7"


def test_an_ordinary_import_records_no_acknowledgement(monkeypatch):
    db = _setup(monkeypatch)
    _upload()
    stmt = db.rows("bank_statements")[0]
    assert "totals_mismatch_reason" not in stmt or stmt["totals_mismatch_reason"] is None
    assert stmt.get("totals_mismatch_acknowledged_by") is None


def test_the_override_is_on_the_clients_timeline_as_a_warning(monkeypatch):
    """A partner scanning the timeline should not have to open the statement row
    to find out that somebody overrode the check.

    Spied rather than read back, because the e2e harness stubs the timeline out
    (tests/e2e_harness.wire_e2e) so an import is not judged on a side effect."""
    from services.timeline_service import timeline_service
    db = _setup(monkeypatch)
    logged: list[dict] = []
    monkeypatch.setattr(timeline_service, "log",
                        lambda *a, **kw: logged.append({"args": a, "kw": kw}))

    one_line = _HEAD + _PAGE1 + _line("Grand Total", "20000.00", "50000.00")
    _upload(content=one_line, acknowledge=REASON)

    warnings = [e for e in logged if "warning" in e["args"]]
    assert len(warnings) == 1, "an override with no timeline entry is a silent one"
    title, description = warnings[0]["args"][2], warnings[0]["args"][3]
    assert "totals" in title.lower()
    assert REASON in description


def test_an_ordinary_import_writes_no_warning(monkeypatch):
    """The control. If every import logged a warning the warning would mean
    nothing."""
    from services.timeline_service import timeline_service
    _setup(monkeypatch)
    logged: list[tuple] = []
    monkeypatch.setattr(timeline_service, "log", lambda *a, **kw: logged.append(a))
    _upload()
    assert not [e for e in logged if "warning" in e]


def test_a_scribbled_reason_is_refused(monkeypatch):
    db = _setup(monkeypatch)
    one_line = _HEAD + _PAGE1 + _line("Grand Total", "20000.00", "50000.00")
    with pytest.raises(HTTPException) as e:
        _upload(content=one_line, acknowledge="fine")
    assert e.value.status_code == 422
    assert "at least 10 characters" in str(e.value.detail)
    assert not db.rows("bank_statements")


def test_a_reason_against_a_check_that_passed_is_refused(monkeypatch):
    """A box that can be ticked when it does not apply is a box people tick out
    of habit — and the record then carries an explanation for nothing."""
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(acknowledge=REASON)
    assert e.value.status_code == 422
    assert "nothing to acknowledge" in str(e.value.detail)
    assert not db.rows("bank_statements"), "and it did not import either"


# The scan half of this rule lives in tests/test_statement_vision.py
# (test_a_scan_cannot_be_imported_over_its_own_totals), where the model doubles
# and the rasteriser are already wired: an acknowledgement is refused outright
# on a scan, because there the only reading of the file is the one that does not
# add up.
