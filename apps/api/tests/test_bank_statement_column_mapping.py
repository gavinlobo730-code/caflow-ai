"""
An unrecognised bank must be mappable, once, instead of being a dead end.

WHAT WAS WRONG
    domain/banking/normalizer._ADAPTERS knows six statement layouts: HDFC, SBI,
    ICICI, Axis and two generic ones. Every other bank — Kotak, IDFC First,
    PNB, Canara, Union, and every co-operative bank in the country — reached

        "Unsupported bank statement format …"

    and stopped there. There was no way past it. A CA whose client banks
    anywhere unusual could not get a statement into the product at all, and
    nothing they could do would change that.

WHY A MAPPING RATHER THAN THE EIGHT MORE ADAPTERS THE AUDIT ASKED FOR
    An adapter is a guess about a layout nobody here has seen. Writing eight of
    them from memory is how a Canara adapter ships reading the balance column
    as a credit — silently wrong numbers, which is precisely what
    _validate_adapter was written to prevent, arrived at deliberately instead
    of by accident. A mapping is not a guess: the person holding the file says
    where the columns are.

THE SAFETY ARGUMENT, WHICH IS THE POINT OF THIS MODULE
    An explicit mapping DELIBERATELY skips _validate_adapter's label check —
    unrecognised labels are the whole reason it exists. So something else has
    to catch a mapping that parses cleanly and is wrong. Three things do:
    validate_mapping refuses a self-contradictory shape, the CA sees the parsed
    rows before importing, and balance_agreement checks the result against the
    bank's own running balance. The last is the one that matters: debit and
    credit swapped parses perfectly, every amount and date correct, and inverts
    the client's entire cash position. No label check could ever catch it.
"""
import json

import pytest
from fastapi.testclient import TestClient

from domain.banking.normalizer import (
    MAPPING_KEYS, StatementParseError, balance_agreement, header_fingerprint,
    inspect_statement, parse_statement, validate_mapping,
)
from main import app
from services import bank_column_mapping_service as svc

pytestmark = pytest.mark.usefixtures("dev_header_auth")

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}

# A layout none of the six adapters handles: "Withdrawal Amt"/"Deposit Amt"
# rather than Debit/Credit, and a "Chq" column that makes detect_format guess
# HDFC. This is the shape the whole feature exists for.
KOTAK_CSV = b"""Date,Particulars,Chq,Withdrawal Amt,Deposit Amt,Closing Bal
01/04/2025,UPI/DR/1234/RAMESH K,,5000.00,,95000.00
02/04/2025,NEFT SALARY CREDIT,,,20000.00,115000.00
03/04/2025,BANK CHARGES GST,,590.00,,114410.00
"""
GOOD = {"date": 0, "desc": 1, "ref": 2, "debit": 3, "credit": 4, "balance": 5}
SWAPPED = {"date": 0, "desc": 1, "ref": 2, "debit": 4, "credit": 3, "balance": 5}


# ── The dead end, and the way past it ────────────────────────────────────────

def test_this_bank_is_a_dead_end_without_a_mapping():
    """The starting condition. If this ever stops raising, the rest of this
    module is testing a feature nobody needs."""
    with pytest.raises(StatementParseError) as e:
        parse_statement("kotak.csv", KOTAK_CSV)
    # There are TWO dead-end messages — "Unsupported bank statement format" and
    # the detected-adapter-does-not-fit one this file happens to hit. Asserting
    # the exact sentence would pass for the wrong reason if detection shifted;
    # what matters is that the CA is told only which banks work, with no way to
    # say where THIS bank's columns are.
    assert "Supported: HDFC, SBI, ICICI, Axis" in str(e.value)


def test_the_same_file_parses_once_the_columns_are_mapped():
    txns = parse_statement("kotak.csv", KOTAK_CSV, GOOD)
    assert len(txns) == 3
    assert txns[0].transaction_date == "2025-04-01"
    assert txns[0].debit_paise == 500_000 and txns[0].credit_paise == 0
    assert txns[1].credit_paise == 2_000_000 and txns[1].debit_paise == 0
    assert txns[2].balance_paise == 11_441_000


def test_detection_is_untouched_when_no_mapping_is_given():
    """The mapping is an addition, not a replacement. An HDFC file must still
    parse with nobody mapping anything."""
    hdfc = (b"Date,Narration,Value Dt,Chq/Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
            b"01/04/2025,UPI-RAMESH,01/04/2025,000000,5000.00,,95000.00\n")
    txns = parse_statement("hdfc.csv", hdfc)
    assert len(txns) == 1 and txns[0].debit_paise == 500_000


# ── The safety net: the bank's own arithmetic ────────────────────────────────

def test_a_swapped_mapping_parses_perfectly_and_is_caught_anyway():
    """THE case this feature could have got wrong. Every date right, every
    amount right, and the direction of the client's cash inverted."""
    txns = parse_statement("kotak.csv", KOTAK_CSV, SWAPPED)
    assert len(txns) == 3, "it parses — that is the danger"
    assert txns[0].credit_paise == 500_000, "a payment out has become money in"

    check = balance_agreement(txns)
    assert check["checked"] is True
    assert check["agrees"] is False
    assert "swapped" in check["reason"]
    assert check["first_disagreement"]["description"].startswith("NEFT")


def test_a_correct_mapping_agrees_with_the_balance_column():
    check = balance_agreement(parse_statement("kotak.csv", KOTAK_CSV, GOOD))
    assert check["agrees"] is True and check["order"] == "oldest-first"


def test_a_newest_first_statement_is_recognised_not_condemned():
    """A real export option. Every delta simply has the opposite sign. Calling
    a correct mapping wrong is how a correct mapping gets 'fixed' into a broken
    one."""
    reversed_csv = (b"Date,Particulars,Chq,Withdrawal Amt,Deposit Amt,Closing Bal\n"
                    b"03/04/2025,BANK CHARGES GST,,590.00,,114410.00\n"
                    b"02/04/2025,NEFT SALARY CREDIT,,,20000.00,115000.00\n"
                    b"01/04/2025,UPI/DR/1234/RAMESH K,,5000.00,,95000.00\n")
    check = balance_agreement(parse_statement("k.csv", reversed_csv, GOOD))
    assert check["agrees"] is True
    assert check["order"] == "newest-first"


def test_a_statement_with_no_balance_column_says_it_could_not_check():
    """Silence and a pass are different answers. A file with nothing to check
    against must not report that it checked out."""
    no_bal = (b"Date,Particulars,Withdrawal Amt,Deposit Amt\n"
              b"01/04/2025,UPI-RAMESH,5000.00,\n02/04/2025,NEFT IN,,20000.00\n")
    check = balance_agreement(parse_statement("x.csv", no_bal,
                                              {"date": 0, "desc": 1, "debit": 2, "credit": 3}))
    assert check["checked"] is False
    assert "no balance column" in check["reason"]


# ── validate_mapping refuses what cannot work ────────────────────────────────

@pytest.mark.parametrize("mapping,fragment", [
    ({"desc": 1, "debit": 3, "credit": 4},                      "date column must be mapped"),
    ({"date": 0, "debit": 3, "credit": 4},                      "desc column must be mapped"),
    ({"date": 0, "desc": 1},                                    "Map the amounts"),
    ({"date": 0, "desc": 1, "debit": 3, "amount": 4, "drcr": 5}, "not both"),
    ({"date": 0, "desc": 1, "amount": 3},                       "Dr/Cr indicator"),
    ({"date": 0, "desc": 0, "debit": 3, "credit": 4},           "only be one thing"),
    ({"date": 0, "desc": 1, "debit": 3, "credit": 99},          "the file has 6 columns"),
    ({"date": 0, "desc": 1, "debit": 3, "credit": "x"},         "must be a column position"),
    ({"date": 0, "desc": 1, "debit": 3, "credit": 4, "nope": 2}, "Unknown column"),
])
def test_a_mapping_that_cannot_work_is_refused_with_a_reason(mapping, fragment):
    with pytest.raises(StatementParseError) as e:
        validate_mapping(mapping, 6)
    assert fragment in str(e.value)


def test_a_valid_mapping_comes_back_with_every_key_filled_in():
    """_rows_to_txns reads with .get(); returning the full shape means no caller
    has to remember which keys are optional."""
    out = validate_mapping({"date": 0, "desc": 1, "debit": 3, "credit": 4}, 6)
    assert set(out) == set(MAPPING_KEYS)
    assert out["ref"] is None and out["amount"] is None


def test_the_single_amount_layout_is_mappable_too():
    csv_bytes = (b"Txn Dt,Remarks,Amount,Type,Bal\n"
                 b"01/04/2025,UPI-RAMESH,5000.00,Dr,95000.00\n"
                 b"02/04/2025,SALARY,20000.00,Cr,115000.00\n")
    txns = parse_statement("x.csv", csv_bytes,
                           {"date": 0, "desc": 1, "amount": 2, "drcr": 3, "balance": 4})
    assert txns[0].debit_paise == 500_000 and txns[1].credit_paise == 2_000_000
    assert balance_agreement(txns)["agrees"] is True


# ── The fingerprint is what makes reuse safe ─────────────────────────────────

def test_the_same_layout_fingerprints_the_same_however_it_is_spelled():
    a = header_fingerprint(["Date", "Particulars", "Chq", "Withdrawal Amt"])
    b = header_fingerprint(["  date ", "PARTICULARS", "chq", "Withdrawal  Amt"])
    assert a == b, "case and whitespace vary between exports and mean nothing"


@pytest.mark.parametrize("changed", [
    ["Date", "Particulars", "Chq", "Withdrawal Amt", "Deposit Amt"],          # dropped
    ["Date", "Particulars", "Chq", "Value Dt", "Withdrawal Amt", "Deposit Amt"],  # inserted
    ["Date", "Narration", "Chq", "Withdrawal Amt", "Deposit Amt", "Closing Bal"],  # renamed
])
def test_a_changed_layout_fingerprints_differently(changed):
    """This is the whole reason the fingerprint is part of the key. If a bank
    changes its export and the mapping still applied, we would read the new
    layout at the old positions — wrong numbers, no error."""
    original = ["Date", "Particulars", "Chq", "Withdrawal Amt", "Deposit Amt", "Closing Bal"]
    assert header_fingerprint(changed) != header_fingerprint(original)


def test_a_saved_mapping_is_never_used_for_a_different_layout():
    """find_mapping must return None rather than the account's other mapping."""
    class _DB:
        def table(self, _): return self
        def select(self, *_a, **_k): return self
        def eq(self, col, val):
            self._fp = val if col == "header_fingerprint" else getattr(self, "_fp", None)
            return self
        def limit(self, _): return self
        def execute(self):
            class R: pass
            r = R()
            r.data = [{"id": "m1", "mapping": GOOD}] if self._fp == "MATCHING" else []
            return r
    db = _DB()
    assert svc.find_mapping(db, "firm-001", "acct-1", "MATCHING") is not None
    assert svc.find_mapping(db, "firm-001", "acct-1", "DIFFERENT") is None


def test_a_failed_lookup_does_not_block_an_import_that_would_work():
    class _Boom:
        def table(self, _): raise RuntimeError("postgrest down")
    assert svc.find_mapping(_Boom(), "firm-001", "acct-1", "fp") is None


# ── inspect_statement: what the mapping screen is built on ───────────────────

def test_inspect_returns_the_header_and_real_rows():
    info = inspect_statement("kotak.csv", KOTAK_CSV)
    assert info["headers"][0] == "Date" and info["headers"][3] == "Withdrawal Amt"
    assert info["total_rows"] == 3
    assert info["sample_rows"][0][1] == "UPI/DR/1234/RAMESH K"


def test_inspect_does_not_offer_a_mapping_it_has_just_shown_to_be_wrong():
    """detect_format guesses 'hdfc' off the shared cheque signal, and
    _validate_adapter rejects it. Prefilling that guess would hand the CA the
    error to confirm."""
    info = inspect_statement("kotak.csv", KOTAK_CSV)
    assert info["detected_format"] == "hdfc"
    assert info["detected_fits"] is False
    assert info["proposed_mapping"] is None


def test_inspect_does_offer_a_starting_point_when_the_adapter_really_fits():
    hdfc = (b"Date,Narration,Value Dt,Chq/Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
            b"01/04/2025,UPI-RAMESH,01/04/2025,000000,5000.00,,95000.00\n")
    info = inspect_statement("hdfc.csv", hdfc)
    assert info["detected_fits"] is True
    assert info["proposed_mapping"]["debit"] == 4


def test_inspect_refuses_a_file_type_it_cannot_read():
    with pytest.raises(StatementParseError):
        inspect_statement("statement.pdf", b"%PDF-1.4")


# ── Through the API ──────────────────────────────────────────────────────────

def _upload(path, **form):
    files = {"file": ("kotak.csv", KOTAK_CSV, "text/csv")}
    return client.post(path, headers=HEADERS, files=files,
                       data={"client_id": "client-001", **form})


def test_the_inspect_endpoint_gives_a_ca_something_to_map():
    res = _upload("/api/banking/statements/inspect")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["headers"][3] == "Withdrawal Amt"
    assert data["detected_fits"] is False


def test_the_preview_endpoint_shows_the_result_without_importing():
    res = _upload("/api/banking/statements/preview", column_mapping=json.dumps(GOOD))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["parsed_count"] == 3
    assert data["rows"][0]["debit_paise"] == 500_000
    assert data["balance_check"]["agrees"] is True


def test_the_preview_endpoint_reports_a_swapped_mapping_rather_than_accepting_it():
    res = _upload("/api/banking/statements/preview", column_mapping=json.dumps(SWAPPED))
    assert res.status_code == 200, res.text
    check = res.json()["data"]["balance_check"]
    assert check["agrees"] is False and "swapped" in check["reason"]


def test_the_preview_endpoint_refuses_a_mapping_that_cannot_work():
    res = _upload("/api/banking/statements/preview",
                  column_mapping=json.dumps({"date": 0, "desc": 1}))
    assert res.status_code == 422
    assert "Map the amounts" in res.json()["detail"]


def test_a_mapping_that_is_not_json_is_a_422_not_a_500():
    res = _upload("/api/banking/statements/preview", column_mapping="not json")
    assert res.status_code == 422


def test_upload_accepts_a_supplied_mapping_and_says_it_used_it():
    res = _upload("/api/banking/statements/upload", column_mapping=json.dumps(GOOD))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["imported"] == 3
    assert data["column_source"] == "supplied"
    assert data["balance_check"]["agrees"] is True


def test_upload_without_a_mapping_still_reports_how_it_read_the_columns():
    hdfc = (b"Date,Narration,Value Dt,Chq/Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
            b"01/04/2025,UPI-RAMESH,01/04/2025,000000,5000.00,,95000.00\n")
    res = client.post("/api/banking/statements/upload", headers=HEADERS,
                      files={"file": ("hdfc.csv", hdfc, "text/csv")},
                      data={"client_id": "client-001"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["column_source"] == "detected"


# ── The actor id, which the mock suite cannot see ────────────────────────────

def test_the_saved_mapping_records_the_internal_user_id_not_the_auth_id():
    """created_by FKs public.users(id) — the INTERNAL id. current_user carries
    BOTH that and the Supabase auth id, and CLAUDE.md says which one belongs
    here; this was still written the wrong way round first time.

    It cannot be caught by the rest of this module: mock mode has no database,
    so an FK violation is invisible, and the failure was swallowed into
    `mapping_saved: false` — the statement imported, the layout was silently
    not learned, and the next month asked again. A live harness surfaced it as
    SQLSTATE 23503. Reading the source is the cheap way to keep it fixed."""
    src = open("routers/banking.py").read()
    start = src.index("if save_mapping and mapping and bank_account_id:")
    block = src[start:start + 1200]
    assert 'actor_id=current_user.get("id")' in block, (
        "the saved mapping's created_by must come from the internal user id")
    assert 'actor_id=current_user.get("auth_user_id")' not in block, (
        "auth_user_id is not a public.users.id — this FK-violates on every save")


def test_a_save_failure_is_reported_rather_than_swallowed():
    """The import legitimately succeeds even when the convenience cannot be
    stored — but silently is how the wrong actor id survived. The response has
    to say which happened."""
    src = open("routers/banking.py").read()
    assert '"mapping_saved"' in src
    assert 'result["mapping_saved"] = False' in src
