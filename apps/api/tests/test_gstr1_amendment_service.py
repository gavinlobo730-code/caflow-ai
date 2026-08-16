"""
Amendments a period's GSTR-1 must carry from earlier periods already filed.

The proposal logic is tested in test_gstr1_amendments.py against the rule. This
is about the walk backwards: which periods are looked at, in what order, and
whether an invoice edited months after its return was filed actually surfaces —
end to end from a seeded invoice, not from a report the test wrote itself.
"""
from __future__ import annotations

import pytest

import routers.gst_workspace as gw
import services.gst_amendment_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CLIENT = "CLI"
GSTIN = "27AAAAA0000A1Z5"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                         "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, date, taxable, cgst=0, sgst=0):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": invoice_no, "invoice_date": date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": 0, "total_paise": taxable + cgst + sgst,
        "is_interstate": False, "supply_state_code": "27",
        "supply_type": "taxable", "invoice_type": "Regular", "is_reverse_charge": False,
        "deleted_at": None,
    })


def _file(db, period):
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"]
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN,
        "status": "submitted", "payload_json": payload,
        "submitted_at": f"2025-01-01T00:00:00Z", "arn": f"ARN{period}",
    })


def _out(db, period="072025"):
    return svc.outstanding_amendments(db, FIRM, CLIENT, period)


# ── periods are ordered chronologically, not lexically ───────────────────────

def test_periods_sort_by_year_then_month():
    """'012026' sorts before '062025' as a string, which would walk the periods
    backwards and name the wrong month in an omon."""
    assert svc._sort_key("062025") < svc._sort_key("072025")
    assert svc._sort_key("122025") < svc._sort_key("012026")


def test_a_malformed_period_sorts_last_rather_than_crashing():
    assert svc._sort_key("") == (0, 0)
    assert svc._sort_key("nonsense") == (0, 0)


# ── which periods are looked at ──────────────────────────────────────────────

def test_a_client_with_nothing_filed_has_nothing_outstanding(db):
    _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)

    out = _out(db)

    assert out["counts"]["amendments"] == 0
    assert out["source_periods"] == []


def test_the_target_period_itself_is_not_amended(db):
    """You do not amend the return you are preparing.

    The period MUST have real drift for this to test anything. The first
    version filed a period and left it untouched, so it was excluded by the
    is-it-clean check rather than by the period window — widening the window to
    include the target period failed nothing.
    """
    row = _invoice(db, "INV-1", "2025-07-10", 100_000, 9_000, 9_000)
    _file(db, "072025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()

    out = _out(db, "072025")

    assert out["source_periods"] == []
    assert out["counts"]["amendments"] == 0


def test_a_later_filed_period_is_not_amended_in_an_earlier_return(db):
    """August's drift cannot be declared in July's return — the amendment goes
    in a LATER period, never an earlier one. Same trap as above: August needs
    real drift or the window filter is untested."""
    row = _invoice(db, "INV-1", "2025-08-10", 100_000, 9_000, 9_000)
    _file(db, "082025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()

    out = _out(db, "072025")

    assert out["source_periods"] == []
    assert out["counts"]["amendments"] == 0


def test_an_unchanged_filed_period_proposes_nothing(db):
    _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")

    assert _out(db)["counts"]["amendments"] == 0


def test_a_return_still_in_draft_is_not_amended(db):
    """A draft is re-derived from the books every time it is opened, so it
    cannot have drifted from anything.

    Two layers enforce this — the period walk filters on status, and the
    exception report refuses a non-submitted return — so no single mutation
    can break it. The test asserts the behaviour anyway: it is the behaviour
    that matters, and a later refactor could remove either layer.
    """
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, "062025", GSTIN)["payload"]
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": "062025", "gstin": GSTIN,
        "status": "draft", "payload_json": payload,
    })
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()

    out = _out(db)

    assert out["source_periods"] == []
    assert out["counts"]["amendments"] == 0


# ── the real thing ───────────────────────────────────────────────────────────

def test_an_invoice_edited_after_its_period_was_filed_becomes_an_amendment(db):
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")

    db.table("client_sales_invoices").update({
        "taxable_amount_paise": 150_000, "cgst_paise": 13_500, "sgst_paise": 13_500,
    }).eq("id", row["id"]).execute()

    out = _out(db)

    assert out["counts"]["amendments"] == 1
    assert out["source_periods"] == ["062025"]
    b2ba = out["sections"]["b2ba"]
    assert b2ba[0]["ctin"] == "27BBBBB1111B1Z5"
    assert b2ba[0]["inv"][0]["oinum"] == "INV-1"
    assert b2ba[0]["inv"][0]["itms"][0]["itm_det"]["txval"] == 1500.0


def test_amendments_from_several_filed_periods_are_collected_together(db):
    """Drift is not discovered in the month it happens — an April edit may
    surface in September, and nothing forces anyone to reopen April."""
    apr = _invoice(db, "INV-APR", "2025-04-10", 100_000, 9_000, 9_000)
    _file(db, "042025")
    may = _invoice(db, "INV-MAY", "2025-05-10", 100_000, 9_000, 9_000)
    _file(db, "052025")

    for row in (apr, may):
        db.table("client_sales_invoices").update(
            {"taxable_amount_paise": 120_000}).eq("id", row["id"]).execute()

    out = _out(db)

    assert out["source_periods"] == ["042025", "052025"], "oldest first"
    assert out["counts"]["amendments"] == 2


def test_an_invoice_raised_after_filing_is_carried_forward_not_amended(db):
    """It was never declared, and gstr1_from_books selects by date range — so
    without this it would be declared in no return at all."""
    _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")

    _invoice(db, "INV-LATE", "2025-06-28", 40_000, 3_600, 3_600)

    out = _out(db)

    assert out["counts"]["amendments"] == 0
    assert out["counts"]["carry_forward"] == 1
    assert out["carry_forward"][0]["doc_no"] == "INV-LATE"
    assert out["carry_forward"][0]["from_period"] == "062025"


def test_a_cancelled_document_needs_a_decision_rather_than_an_amendment(db):
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")

    db.table("client_sales_invoices").update(
        {"status": "cancelled"}).eq("id", row["id"]).execute()

    out = _out(db)

    assert out["counts"]["amendments"] == 0
    assert out["counts"]["needs_decision"] == 1
    assert out["needs_decision"][0]["from_period"] == "062025"


# ── folding the amendments into a payload ────────────────────────────────────

def test_amendments_merge_into_the_target_periods_payload(db):
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()
    _invoice(db, "INV-JUL", "2025-07-05", 50_000, 4_500, 4_500)

    july = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    merged = svc.apply_amendments(july, _out(db))

    assert "b2ba" in merged, "the amendment table is added"
    assert merged["b2b"] == july["b2b"], "July's own invoices are untouched"


def test_merging_nothing_leaves_the_payload_alone(db):
    _invoice(db, "INV-JUL", "2025-07-05", 50_000, 4_500, 4_500)
    july = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]

    merged = svc.apply_amendments(july, _out(db))

    assert "b2ba" not in merged
    assert merged == july


def test_proposing_does_not_itself_amend_the_payload(db):
    """Reporting and filing are separate steps on purpose — a function that did
    both would make the CA's review easy to skip."""
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()

    out = _out(db)
    july = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]

    assert "b2ba" not in july
    assert out["counts"]["amendments"] == 1


# ── scoping ──────────────────────────────────────────────────────────────────

def test_another_clients_filed_period_is_not_amended_here(db):
    """Another client in the same firm having filed 062025 must not pull that
    period into this client's amendments.

    Defended twice — the period walk is client-scoped, and the exception report
    is looked up per client — so neither layer alone can be mutated into
    failing this. Asserted regardless, because a firm-wide read here would put
    one client's corrections into another's return, which is the worst possible
    outcome for this feature.
    """
    db.seed("clients", {"id": "CLI-2", "firm_id": FIRM, "gstin": "27CCCCC2222C1Z5",
                        "financial_year_start": "2025-04-01", "state_code": "27"})
    db.seed("customers", {"id": "CUST2", "firm_id": FIRM, "client_id": "CLI-2",
                          "name": "Other", "gstin": "27DDDDD3333D1Z5",
                          "state_code": "27", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI-2")
    other = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI-2", "customer_id": "CUST2",
        "invoice_no": "OTHER-1", "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
        "igst_paise": 0, "total_paise": 118_000, "is_interstate": False,
        "supply_state_code": "27", "supply_type": "taxable",
        "invoice_type": "Regular", "is_reverse_charge": False, "deleted_at": None,
    })
    other_payload = grs.gstr1_from_books(db, FIRM, "CLI-2", "062025", "27CCCCC2222C1Z5")["payload"]
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": "CLI-2", "period": "062025",
        "gstin": "27CCCCC2222C1Z5", "status": "submitted",
        "payload_json": other_payload,
    })
    # Real drift, on the OTHER client.
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 500_000}).eq("id", other["id"]).execute()

    out = _out(db)

    assert out["source_periods"] == []
    assert out["counts"]["amendments"] == 0
    assert "OTHER-1" not in str(out["sections"])


# ── the endpoint ─────────────────────────────────────────────────────────────

def test_the_endpoint_returns_the_proposal(db):
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()

    resp = gw.gstr1_outstanding_amendments(
        client_id=CLIENT, period="072025", current_user=CALLER)

    assert resp["success"] is True
    assert resp["data"]["counts"]["amendments"] == 1
    assert resp["data"]["ca_review_required"] is True
