"""
SALES-25a — CGST §34(2), and the period it is measured against.

WHAT WAS WRONG. `routers/credit_notes.py` asked two questions about the note's
OWN date: is its financial year locked, and has a return covering its period
been filed. Both are right and both are about the wrong period. §34(2) closes
the window by reference to "the financial year in which SUCH SUPPLY was made" —
the ORIGINAL INVOICE's year, not the note's.

The two diverge constantly, and in the direction that hurts: a June 2025
invoice credited in January 2027 sits in a wide-open period (January 2027's
GSTR-1 has not been filed) and outside a window that shut on 30 November 2026.
Nothing compared the two, so a note that can never lawfully reduce output tax
was accepted, posted, and reduced it in the books.

WHY A WARNING. §34(2) bars the tax ADJUSTMENT, not the document. A supplier may
still issue a commercial credit note after the window to settle a genuine
dispute; it simply carries no GST. Refusing would stop a lawful commercial act.
So the note is written and the consequence is stated — at create, and again at
issue, because a draft raised inside the window can be issued outside it.

The "whichever is earlier" limb is `compliance_engine.correction_window_closes`
and is not re-implemented here (GST-09): an early GSTR-9 shuts the window
early, and one place knows that.
"""
from datetime import date

import pytest

from domain.gst.credit_note_window import late_credit_note, window_closes


# ---------------------------------------------------------------------------
# The rule.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("supply,closes", [
    (date(2025, 4, 1),   date(2026, 11, 30)),   # first day of FY 2025-26
    (date(2025, 6, 15),  date(2026, 11, 30)),
    (date(2026, 3, 31),  date(2026, 11, 30)),   # last day of the SAME FY
    (date(2026, 4, 1),   date(2027, 11, 30)),   # one day later — next FY
])
def test_the_window_runs_from_the_supplys_financial_year(supply, closes):
    assert window_closes(supply) == closes


def test_a_note_inside_the_window_says_nothing():
    assert late_credit_note(date(2026, 11, 30), date(2025, 6, 15)) is None
    assert late_credit_note(date(2026, 1, 5), date(2025, 6, 15)) is None


def test_a_note_after_30_november_warns_and_says_what_it_cannot_do():
    w = late_credit_note(date(2026, 12, 1), date(2025, 6, 15))
    assert w and "34(2)" in w
    # The distinction that matters: the DOCUMENT is fine, the REDUCTION is not.
    assert "commercial credit" in w and "cannot reduce output tax" in w


def test_the_notes_own_period_being_open_does_not_save_it():
    # January 2027 is an open period by any measure — its own FY is 2026-27 and
    # its return is not due, let alone filed. The supply's window still shut.
    assert late_credit_note(date(2027, 1, 10), date(2025, 6, 15))


def test_an_early_annual_return_shuts_the_window_early():
    # GST-09's rule, reached through compliance_engine rather than restated.
    supply = date(2025, 6, 15)
    assert late_credit_note(date(2026, 9, 1), supply) is None
    w = late_credit_note(date(2026, 9, 1), supply, date(2026, 8, 20))
    assert w and "annual return" in w and "2026-08-20" in w


def test_an_annual_return_filed_AFTER_30_november_does_not_extend_the_window():
    # "whichever is earlier" — a late GSTR-9 cannot lengthen anything.
    assert window_closes(date(2025, 6, 15), date(2026, 12, 20)) == date(2026, 11, 30)
    assert late_credit_note(date(2026, 12, 10), date(2025, 6, 15), date(2026, 12, 20))


def test_no_linked_invoice_means_no_warning_rather_than_a_guess():
    # Guessing the supply's financial year from the NOTE's date is the exact
    # error this exists to catch, so an unlinked note is left alone.
    assert late_credit_note(date(2027, 1, 10), None) is None


# ---------------------------------------------------------------------------
# The wiring.
# ---------------------------------------------------------------------------
from models.invoices import InvoiceLineIn                          # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa   # noqa: E402

FIRM = "FIRM-CN"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firm.test",
          "id": "u1", "role": "Partner"}


def _setup(monkeypatch):
    import routers.credit_notes as cn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return cn, db


def _seed_invoice(db, invoice_date):
    db.seed("client_sales_invoices", {
        "id": "SI-1", "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "invoice_no": "INV/2025-26/001", "invoice_date": invoice_date,
        "status": "issued", "is_interstate": False, "total_paise": 1_180_000,
        "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0,
        "deleted_at": None})


class _Payload:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return self._d


def _note(note_date, sales_invoice_id="SI-1"):
    return _Payload({
        "client_id": "CLI", "customer_id": "CUST", "credit_note_date": note_date,
        "sales_invoice_id": sales_invoice_id, "reason": "Rate revision",
        "is_interstate": False,
        "lines": [InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting",
                                hsn_sac="9982", quantity=1, rate_paise=100_000,
                                gst_rate_percent=18.0).model_dump()],
    })


def test_creating_a_note_inside_the_window_carries_no_warning(monkeypatch):
    cn, db = _setup(monkeypatch)
    _seed_invoice(db, "2025-06-15")
    resp = cn.create_credit_note(_note("2026-01-10"), CALLER)
    assert resp["success"] is True
    assert resp["data"]["section_34_2_warning"] is None


def test_creating_a_note_after_the_supplys_window_warns_but_still_creates(monkeypatch):
    cn, db = _setup(monkeypatch)
    _seed_invoice(db, "2025-06-15")
    resp = cn.create_credit_note(_note("2027-01-10"), CALLER)
    assert resp["success"] is True                     # a warning, never a refusal
    assert resp["data"]["credit_note_no"]              # and it is a real document
    assert "34(2)" in resp["data"]["section_34_2_warning"]


def test_a_note_with_no_linked_invoice_is_created_without_comment(monkeypatch):
    cn, db = _setup(monkeypatch)
    resp = cn.create_credit_note(_note("2027-01-10", sales_invoice_id=None), CALLER)
    assert resp["success"] is True
    assert resp["data"]["section_34_2_warning"] is None


def test_an_early_gstr9_shortens_the_window_on_the_create_path(monkeypatch):
    cn, db = _setup(monkeypatch)
    _seed_invoice(db, "2025-06-15")
    db.seed("gstr1_returns", {"id": "R9", "firm_id": FIRM, "client_id": "CLI",
                              "return_type": "gstr9", "status": "submitted",
                              "financial_year": "2025-26",
                              "submitted_at": "2026-08-20T04:00:00+00:00"})
    resp = cn.create_credit_note(_note("2026-09-01"), CALLER)
    w = resp["data"]["section_34_2_warning"]
    assert w and "annual return" in w and "2026-08-20" in w


def test_the_warning_is_repeated_at_issue(monkeypatch):
    # A draft raised inside the window can be issued outside it, and issue is
    # when the reduction reaches the ledger and the return.
    cn, db = _setup(monkeypatch)
    _seed_invoice(db, "2025-06-15")
    created = cn.create_credit_note(_note("2027-01-10"), CALLER)["data"]
    issued = cn.issue_credit_note(created["id"], CALLER)
    assert issued["success"] is True
    assert issued["data"]["status"] == "issued"
    assert "34(2)" in issued["data"]["section_34_2_warning"]
