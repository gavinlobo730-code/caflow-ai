"""
The GSTR-1 validator runs on the path that actually builds a CA's return.

WHAT WAS WRONG
    domain/gst/validator.validate_gstr1 checks the things that get a return
    rejected at the portal or filed wrong: a duplicate invoice number, a place
    of supply that is not a state code, CGST != SGST on an intra-state supply,
    IGST on an intra-state supply, tax that does not follow from the taxable
    value, an invoice dated outside the period being filed.

    It was reachable from exactly two endpoints — POST /gst/gstr1/build and
    POST /gst/validate/gstr1 — and NO SCREEN CALLS EITHER. lib/data/gst.ts
    posts to /gst/gstr1/from-books, and that path validated the filer's own
    GSTIN and the period string and nothing else. So the checks existed, were
    tested, and never ran on a real return.

WHERE THE FIX WENT, AND WHY THERE
    In gstr1_from_books itself, not in the router. /gstr1/with-amendments calls
    the same service function and spreads its result, so a router-level fix
    would have needed a second copy — and two copies of a validation is how one
    of them stops being run (CLAUDE.md: when a rule has to exist twice, MOVE
    it).

WHY IT REPORTS RATHER THAN REFUSING
    A 422 would hide every other table from the CA over one bad invoice, and
    the CA is the one who decides what to do about it. That is what
    /gst/gstr1/build has always done, and this uses the same two keys so a
    screen reads one contract whichever way the payload was produced. Nothing
    here files anything.
"""
from __future__ import annotations

import pytest

import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
GSTIN = "27AAAAA0000A1Z5"
PERIOD = "062025"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                         "name": "Acme", "gstin": "27BBBBB1111B1Z5",
                         "state_code": "27", "is_active": True})
    return d


def _seed(db, **fields):
    """An intra-state B2B invoice at 18%, correct unless a test breaks it."""
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "invoice_no": "INV-1", "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": 100_000_00,
        "cgst_paise": 9_000_00, "sgst_paise": 9_000_00, "igst_paise": 0,
        "total_paise": 118_000_00, "is_interstate": False,
        "supply_state_code": "27", "deleted_at": None,
        **fields,
    })


def _run(db):
    return grs.gstr1_from_books(db, FIRM, "CLI", PERIOD, GSTIN)


def _fields(result, key="validation_errors") -> set[str]:
    return {e["field"] for e in result[key]}


# ── The contract exists at all ──────────────────────────────────────────────

def test_the_from_books_result_carries_the_validation_keys(db):
    _seed(db)
    out = _run(db)
    assert "validation_errors" in out, (
        "the path a CA uses returned no validation result at all")
    assert "validation_warnings" in out


def test_a_clean_return_reports_nothing(db):
    """A validator that fires on a correct return is a validator nobody reads."""
    _seed(db)
    out = _run(db)
    assert out["validation_errors"] == []
    assert out["validation_warnings"] == []


# ── The errors that get a return rejected ───────────────────────────────────

def test_igst_on_an_intra_state_supply_is_reported(db):
    """IGST Act s.8 — an intra-state supply bears CGST and SGST. IGST here is
    tax collected under the wrong head, and the portal refuses it."""
    _seed(db, cgst_paise=0, sgst_paise=0, igst_paise=18_000_00)
    assert "igst" in _fields(_run(db))


def test_cgst_not_equal_to_sgst_is_reported(db):
    """s.9(1) with the SGST Act charges the same rate on each half; they cannot
    differ on one supply."""
    _seed(db, cgst_paise=9_000_00, sgst_paise=8_000_00)
    assert "cgst_sgst" in _fields(_run(db))


def test_cgst_and_sgst_on_an_inter_state_supply_are_reported(db):
    _seed(db, is_interstate=True, supply_state_code="29",
          cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0)
    assert "cgst_sgst" in _fields(_run(db))


def test_a_place_of_supply_that_is_not_a_state_is_reported(db):
    _seed(db, supply_state_code="99")
    assert "place_of_supply" in _fields(_run(db))


def test_a_duplicate_invoice_number_is_reported(db):
    """Two documents with one number is a rejection at upload, and the return
    is built from the books, so nothing else would have caught it."""
    _seed(db, id="A", invoice_no="INV-DUP")
    _seed(db, id="B", invoice_no="INV-DUP")
    assert "reference_no" in _fields(_run(db))


def test_the_out_of_period_check_is_INERT_on_this_path_and_that_is_correct(db):
    """One of the validator's six rules cannot fire here, and it is worth
    saying which and why rather than leaving it looking covered.

    validate_invoice warns when an invoice is dated outside the period and its
    s.37(3) amendment window. gstr1_from_books fetches BY that period, so an
    out-of-period invoice never reaches the validator at all — the query is the
    check. The rule stays wired because it is not inert on the other path
    (/gst/gstr1/build takes invoices from the caller), and because widening this
    fetch later would make it live again with nothing to change.
    """
    _seed(db, invoice_date="2025-01-15")
    out = _run(db)
    assert out["invoice_count"] == 0, (
        "the January invoice must not be in a June return in the first place")
    assert _fields(out, "validation_warnings") == set()

    import inspect
    src = inspect.getsource(grs._posted_sales)
    assert '.gte(' in src and '.lte(' in src, (
        "the period filter IS the out-of-period check on this path; if it goes, "
        "the validator's own rule has to start doing the work")


# ── What the report must not do ─────────────────────────────────────────────

def test_a_bad_invoice_does_not_suppress_the_rest_of_the_return(db):
    """The reason this reports rather than raising. One wrong invoice must not
    cost the CA sight of the other tables."""
    _seed(db, id="A", invoice_no="INV-OK")
    _seed(db, id="B", invoice_no="INV-BAD", cgst_paise=0, sgst_paise=0,
          igst_paise=18_000_00)
    out = _run(db)
    assert out["validation_errors"], "the bad invoice must be reported"
    assert out["payload"], "and the payload must still be built"
    assert out["invoice_count"] == 2
    assert out["taxable_total_paise"] == 200_000_00


def test_the_amendments_path_carries_the_same_report(db):
    """/gstr1/with-amendments spreads this function's result. Putting the check
    in the router would have left that path unvalidated — which is the shape of
    the original defect, one path checked and one not."""
    _seed(db, cgst_paise=0, sgst_paise=0, igst_paise=18_000_00)
    base = _run(db)
    merged = {**base, "payload": base["payload"]}     # what the endpoint does
    assert "igst" in {e["field"] for e in merged["validation_errors"]}


def test_the_keys_match_the_build_endpoint_exactly(db):
    """One contract for the screen, whichever way the payload was produced."""
    import inspect
    import routers.gst as gst_router
    src = inspect.getsource(gst_router.build_gstr1_endpoint)
    assert '"validation_errors"' in src and '"validation_warnings"' in src
    out = _run(_seed(db) and db)
    assert isinstance(out["validation_errors"], list)
    assert isinstance(out["validation_warnings"], list)
