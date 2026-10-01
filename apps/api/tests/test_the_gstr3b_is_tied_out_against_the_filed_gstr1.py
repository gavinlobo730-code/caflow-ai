"""
GST-07 — the GSTR-3B build is checked against the GSTR-1 that was FILED.

WHAT WAS WRONG
    From the July 2025 tax period the portal fills GSTR-3B Table 3.1 from the
    period's GSTR-1 and locks it (GSTN advisory 606, 07-06-2025). This product
    builds the same figures from the books, so an invoice raised after the
    GSTR-1 was filed makes the books-built 3B differ from the one the portal
    will show — and nothing in the real path compared the two. The one thing
    that does compares DOCUMENTS and lives on the Amendments tab.

WHAT THIS ASSERTS
    * a difference is reported in integer paise, NAMED, with the document that
      caused it and the route that closes it — and neither return is changed;
    * a period with NO filed GSTR-1 says "not filed" and never reports a zero
      difference (a nil that means "nothing to compare against" is not a nil
      that means "they agree");
    * a draft is not a filed return, and a submitted one with no stored payload
      is "cannot compare" and not "everything is missing";
    * what no GSTR-1 can carry (a bank receipt marked as carrying GST) is NOT
      reported as a missing invoice;
    * the filed return's rupee figures come back EXACTLY — `Decimal(str(v))`,
      never `int(v * 100)`;
    * the registration is part of the key, and a quarter is compared against
      the quarter.
"""
from __future__ import annotations

import inspect

import pytest

import routers.gst_workspace as gw
import services.gst_return_service as grs
import services.gstr3b_tie_out_service as svc
from domain.gst import gstr1_3b_tie_out as tie
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CLIENT = "CLI"
GSTIN = "27AAAAA0000A1Z2"
OTHER_GSTIN = "29AAAAA0000A1Z0"
PERIOD = "082025"          # after the July 2025 lock


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1ZN",
                         "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, taxable, cgst=0, sgst=0, igst=0, date="2025-08-10", **extra):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": invoice_no, "invoice_date": date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": igst, "total_paise": taxable + cgst + sgst + igst,
        "is_interstate": bool(igst), "supply_state_code": "27",
        "supply_type": "taxable", "invoice_type": "Regular",
        "is_reverse_charge": False, "deleted_at": None, **extra,
    })


def _filed_payload(db, period=PERIOD):
    return grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"]


def _file(db, payload, *, status="submitted", period=PERIOD, gstin=GSTIN):
    return db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": gstin,
        "status": status, "payload_json": payload,
        "submitted_at": "2025-09-11T10:00:00Z", "arn": "AA270825000001X",
    })


def _build(db, period=PERIOD, **kw):
    return grs.gstr3b_from_books(db, FIRM, CLIENT, period, GSTIN, **kw)


def _tie(db, period=PERIOD, **kw):
    return _build(db, period, **kw)["gstr1_tie_out"]


def _combined(out):
    return out["rows"][0]["figures"]


# ── the headline: Rs 1,00,000 filed, Rs 18,000 raised afterwards ─────────────

def test_an_invoice_raised_after_the_gstr1_was_filed_is_a_named_difference(db):
    """The verify line of the finding, end to end: a filed GSTR-1 declaring
    Rs 1,00,000 of tax, and books that now hold a further Rs 18,000 invoice."""
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db))
    _invoice(db, "INV-2", 1_00_000_00, cgst=9_000_00, sgst=9_000_00)

    out = _tie(db)

    assert out["status"] == "ok"
    assert out["tied"] is False
    figs = _combined(out)
    assert figs["cgst_paise"]["gstr1_filed"] == 50_000_00
    assert figs["sgst_paise"]["gstr1_filed"] == 50_000_00
    assert figs["cgst_paise"]["difference"] == 9_000_00
    assert figs["sgst_paise"]["difference"] == 9_000_00
    # Rs 18,000 of tax in all, and Rs 1,00,000 of taxable value.
    assert (figs["cgst_paise"]["difference"] + figs["sgst_paise"]["difference"]
            == 18_000_00)
    assert figs["taxable_value_paise"]["difference"] == 1_00_000_00


def test_the_difference_names_the_document_that_caused_it(db):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db))
    _invoice(db, "INV-2", 1_00_000_00, cgst=9_000_00, sgst=9_000_00)

    out = _tie(db)

    cause = next(c for c in out["causes"]
                 if c["kind"] == "documents_changed_since_filing")
    named = [d["doc_no"] for d in cause["missing_from_return"]["documents"]]
    assert named == ["INV-2"]
    # The whole of the difference is drift: nothing is left unexplained.
    assert out["attribution"]["remainder"] == {k: 0 for k in tie.FIGURE_KEYS}
    assert cause["figures_paise"]["cgst_paise"] == 9_000_00


def test_the_route_is_gstr_1a_before_the_3b_and_amendments_after(db):
    """GSTR-1A closes the moment the period's GSTR-3B is filed, so the advice
    depends on whether it is — and on a period the portal locks, the table is
    not editable at all."""
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db))
    _invoice(db, "INV-2", 1_00_000_00, cgst=9_000_00, sgst=9_000_00)

    out = _tie(db)
    text = " ".join(out["route"])
    assert out["portal_locks_outward_tables"] is True
    assert "GSTR-1A" in text
    assert "not editable" in text
    assert "ordinary tables" in text, "an invoice never filed has no entry to amend"

    # Same books, 3B recorded as FILED: GSTR-1A has closed.
    db.seed("gstr3b_returns", {"firm_id": FIRM, "client_id": CLIENT,
                               "period": PERIOD, "gstin": GSTIN,
                               "status": "submitted"})
    filed = _tie(db)
    assert filed["gstr3b_filed"] is True
    assert "GSTR-1A has closed" in " ".join(filed["route"])


def test_neither_return_is_changed(db):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    payload = _filed_payload(db)
    row = _file(db, payload)
    _invoice(db, "INV-2", 1_00_000_00, cgst=9_000_00, sgst=9_000_00)
    before = [dict(r) for r in db.rows("gstr1_returns")]

    _tie(db)

    assert [dict(r) for r in db.rows("gstr1_returns")] == before
    assert row["status"] == "submitted"
    assert not db.rows("gstr3b_returns"), (
        "the tie-out must not write a 3B row")


# ── not filed is an answer, and never a zero ─────────────────────────────────

def test_no_filed_gstr1_says_not_filed_and_not_zero(db):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)

    out = _tie(db)

    assert out["status"] == "not_filed"
    assert "tied" not in out and "rows" not in out, (
        "a period with nothing filed must not carry a zero difference")
    assert out["draft_exists"] is False
    assert "not the same as the two agreeing" in out["message"]


@pytest.mark.parametrize("status", ["draft", "validated", "ca_approved"])
def test_a_draft_is_not_a_filed_return(db, status):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db), status=status)

    out = _tie(db)

    assert out["status"] == "not_filed"
    assert out["draft_exists"] is True


def test_a_filed_return_with_no_stored_payload_is_cannot_compare(db):
    """Submitted before the payload was recorded: comparing the books against
    NULL would report every invoice as missing from the return."""
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, None)

    out = _tie(db)

    assert out["status"] == "payload_missing"
    assert "rows" not in out and "causes" not in out
    assert out["arn"] == "AA270825000001X"


# ── tied ─────────────────────────────────────────────────────────────────────

def test_books_untouched_since_filing_are_tied_to_the_paisa(db):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db))

    out = _tie(db)

    assert out["status"] == "ok"
    assert out["tied"] is True
    assert all(r["state"] == "matched" for r in out["rows"])
    # A tied return never pays for the expensive rebuild that explains a gap.
    assert "causes" not in out and "attribution" not in out


# ── what no GSTR-1 can carry ─────────────────────────────────────────────────

def test_a_bank_receipt_marked_as_carrying_gst_is_not_a_missing_invoice(db, monkeypatch):
    """BANK-24: real output tax in the ledger and on the 3B, with no tax invoice
    behind it, so it is in NO GSTR-1. Reporting it as an invoice the filed
    return forgot would send the CA to declare something that has no invoice."""
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, _filed_payload(db))

    from domain.gst.gstr3b_computer import SalesTransaction

    real = grs._outward_transactions

    def with_a_bank_receipt(*a, **kw):
        sales = real(*a, **kw)
        sales.append(SalesTransaction(
            transaction_type="bank_receipt", taxable_amount_paise=1_000_00,
            igst_paise=0, cess_paise=0, is_reverse_charge=False,
            cgst_paise=90_00, sgst_paise=90_00, supply_type="taxable"))
        return sales

    monkeypatch.setattr(grs, "_outward_transactions", with_a_bank_receipt)

    out = _tie(db)

    assert out["tied"] is False
    kinds = [c["kind"] for c in out["causes"]]
    assert "supplies_no_gstr1_can_carry" in kinds
    cause = next(c for c in out["causes"] if c["kind"] == "supplies_no_gstr1_can_carry")
    assert cause["figures_paise"]["cgst_paise"] == 90_00
    assert "will not show these" in cause["consequence"]
    # ... and the drift is NIL: no invoice moved.
    assert out["attribution"]["drift"] == {k: 0 for k in tie.FIGURE_KEYS}
    assert out["attribution"]["remainder"] == {k: 0 for k in tie.FIGURE_KEYS}


# ── the money is read exactly ────────────────────────────────────────────────

def test_a_filed_rupee_figure_is_read_back_exactly():
    """8.29 * 100 is 828.9999999999999 in binary floating point, so
    `int(8.29 * 100)` is 828 and a paisa is lost on some values only. The
    comparison is a total of exactly these figures."""
    assert int(8.29 * 100) == 828, "the premise: the naive conversion is wrong"
    payload = {"b2cs": [{"sply_ty": "INTRA", "rt": 18, "pos": "27",
                         "txval": 8.29, "iamt": 0, "camt": 0.75, "samt": 0.75,
                         "csamt": 0}]}
    out = tie.read_gstr1_outward(payload).taxable_and_zero_rated
    assert out["taxable_value_paise"] == 829
    assert out["cgst_paise"] == 75


def test_a_credit_note_subtracts_and_a_debit_note_adds():
    item = lambda tx, c: [{"num": 1, "itm_det": {"txval": tx, "camt": c, "samt": c}}]
    payload = {
        "b2b": [{"ctin": "27BBBBB1111B1ZN", "inv": [
            {"inum": "I1", "rchrg": "N", "inv_typ": "R", "itms": item(1000.00, 90.00)}]}],
        "cdnr": [{"ctin": "27BBBBB1111B1ZN", "nt": [
            {"ntty": "C", "nt_num": "C1", "itms": item(100.00, 9.00)},
            {"ntty": "D", "nt_num": "D1", "itms": item(50.00, 4.50)}]}],
    }
    out = tie.read_gstr1_outward(payload).taxable_and_zero_rated
    assert out["taxable_value_paise"] == (1000_00 - 100_00 + 50_00)
    assert out["cgst_paise"] == 90_00 - 9_00 + 4_50


def test_table_11_advances_are_read_from_their_own_shape():
    """`at` / `txpd` have NO `itm_det` wrapper and carry the value in `ad_amt`.
    Read like any other table they come back as a confident nil."""
    payload = {
        "at": [{"pos": "27", "sply_ty": "INTRA",
                "itms": [{"rt": 18, "ad_amt": 1000.00, "camt": 90.00, "samt": 90.00}]}],
        "txpd": [{"pos": "27", "sply_ty": "INTRA",
                  "itms": [{"rt": 18, "ad_amt": 400.00, "camt": 36.00, "samt": 36.00}]}],
    }
    out = tie.read_gstr1_outward(payload).taxable_and_zero_rated
    assert out["taxable_value_paise"] == 1000_00 - 400_00
    assert out["cgst_paise"] == 90_00 - 36_00


def test_outward_reverse_charge_is_held_out_not_folded_in():
    item = [{"num": 1, "itm_det": {"txval": 500.00, "camt": 45.00, "samt": 45.00}}]
    payload = {"b2b": [{"ctin": "27BBBBB1111B1ZN", "inv": [
        {"inum": "R1", "rchrg": "Y", "inv_typ": "R", "itms": item}]}]}
    out = tie.read_gstr1_outward(payload)
    assert out.taxable_and_zero_rated["taxable_value_paise"] == 0
    assert out.held_out_reverse_charge["taxable_value_paise"] == 500_00


def test_amendment_sections_in_the_filed_payload_are_named_not_netted():
    out = tie.read_gstr1_outward({"b2ba": [{"ctin": "x"}], "b2csa": [{"x": 1}]})
    assert out.amendment_sections == ["b2ba", "b2csa"]


# ── the key ──────────────────────────────────────────────────────────────────

def test_another_registrations_return_is_not_this_ones(db):
    """Migration 390 keyed `gstr1_returns` on (client, period, gstin). A read on
    (client, period) alone would compare the books against somebody else's
    frozen payload."""
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)
    _file(db, {"gstin": OTHER_GSTIN}, gstin=OTHER_GSTIN)

    assert _tie(db)["status"] == "not_filed"


def test_the_read_goes_through_the_one_the_amendments_tab_uses():
    src = inspect.getsource(svc)
    assert "exceptions.filed_gstr1" in src
    assert "table(\"gstr1_returns\")" not in src, (
        "a second read of the filed return is a second definition of 'filed'")


# ── never breaks the build ───────────────────────────────────────────────────

def test_a_failure_to_read_is_reported_and_does_not_stop_the_3b(db, monkeypatch):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00)

    def boom(*a, **k):
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(svc.exceptions, "filed_gstr1", boom)
    out = _build(db)

    assert out["gstr1_tie_out"]["status"] == "unavailable"
    assert "NOT been checked" in out["gstr1_tie_out"]["message"]
    assert out["tax_liability_paise"] == 1_00_000_00, "the return itself is untouched"


# ── before the lock ──────────────────────────────────────────────────────────

def test_a_period_before_the_july_2025_lock_says_the_table_is_editable(db):
    _invoice(db, "INV-1", 5_55_555_00, cgst=50_000_00, sgst=50_000_00, date="2025-06-10")
    _file(db, _filed_payload(db, "062025"), period="062025")
    _invoice(db, "INV-2", 1_00_000_00, cgst=9_000_00, sgst=9_000_00, date="2025-06-12")

    out = _tie(db, "062025")

    assert out["portal_locks_outward_tables"] is False
    text = " ".join(out["route"])
    assert "precedes the July 2025 lock" in text
    assert "not editable" not in text


def test_the_lock_date_is_a_named_unverified_constant():
    assert tie.OUTWARD_TABLES_LOCKED_FROM == "2025-07-01"
    assert tie.VERIFIED is False
    assert tie.locks_outward("2025-07-01") is True
    assert tie.locks_outward("2025-06-30") is False


# ── a quarter is compared against the quarter ────────────────────────────────

def test_a_qrmp_quarter_is_compared_over_its_three_months(db):
    db.rows("clients")[0]["gst_filing_frequency"] = "quarterly"
    _invoice(db, "INV-A", 1_00_000_00, cgst=9_000_00, sgst=9_000_00, date="2025-07-10")
    _invoice(db, "INV-B", 1_00_000_00, cgst=9_000_00, sgst=9_000_00, date="2025-08-10")
    _invoice(db, "INV-C", 1_00_000_00, cgst=9_000_00, sgst=9_000_00, date="2025-09-10")
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN,
                                   frequency="quarterly")["payload"]
    _file(db, payload, period="072025")
    _invoice(db, "INV-D", 1_00_000_00, cgst=9_000_00, sgst=9_000_00, date="2025-09-20")

    out = _build(db, "072025", frequency="quarterly")["gstr1_tie_out"]

    assert out["period"] == "072025"
    assert out["tied"] is False
    assert _combined(out)["cgst_paise"]["gstr1_filed"] == 27_000_00
    assert _combined(out)["cgst_paise"]["difference"] == 9_000_00
    cause = next(c for c in out["causes"]
                 if c["kind"] == "documents_changed_since_filing")
    assert [d["doc_no"] for d in cause["missing_from_return"]["documents"]] == ["INV-D"]
    assert any("IFF" in g for g in out["gaps"])
