"""
SALES-12 — Invoice Settings configured a numbering series the invoice path
never read.

WHAT WAS WRONG. `invoice_settings` (migration 126) has carried `prefix`,
`include_financial_year`, `sequence_length`, `starting_number` and
`manual_override_allowed` since 2024, and `/settings/invoice-settings` has let
a CA set all five. Nothing read them. Every sales invoice number was typed from
scratch, three separate copies of the Rule 46(b) shape regex disagreed about
nothing only because nobody had changed one of them yet, and Rule 46(b)'s
CONSECUTIVE limb was enforced nowhere at all.

WHAT IT DOES NOW. `GET /api/sales-invoices/next-number` reads the firm's own
settings and answers with the next number in this client's series. The box is
pre-filled, stays editable, and a break in the sequence WARNS — the owner's
decision of 2026-09-12, and the mode Tally calls "Automatic (Manual Override)".
A number the rule FORBIDS is refused, at create, at edit, at bulk import and at
issue.

WHAT THIS TEST HOLDS. Not the pure rules — `test_an_invoice_number_obeys_rule_
46b.py` holds those, against the shared fixture the browser mirror also reads.
This one holds the WIRING: that the settings row is what decides, that the
sequence is read from the client's own books, that the warning reaches the
create response, and that each refusal path actually refuses.
"""
import pytest
from fastapi import HTTPException

from models.invoices import SalesInvoiceIn, InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch, settings: dict | None = None):
    import routers.sales_invoices as si
    import services.sales_numbering_service as sn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, sn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27",
                          "gstin": "27XYZAB5678C1Z2", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    if settings is not None:
        db.seed("invoice_settings", {"id": "IS-1", "firm_id": FIRM, **settings})
    return si, db


def _invoice(invoice_no, date="2026-04-10"):
    return SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date=date,
        due_date="2026-05-10", invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting",
                             hsn_sac="9982", quantity=1, rate_paise=1_000_000,
                             gst_rate_percent=18.0)],
    ).model_dump()


def _seed_invoice(db, invoice_no, date="2026-04-10"):
    db.seed("client_sales_invoices", {
        "id": f"INV-{invoice_no}", "firm_id": FIRM, "client_id": "CLI",
        "invoice_no": invoice_no, "invoice_date": date, "status": "issued",
        "deleted_at": None})


# ---------------------------------------------------------------------------
# The suggestion reads the firm's own settings.
# ---------------------------------------------------------------------------
def test_a_firm_that_never_opened_invoice_settings_still_gets_a_suggestion(monkeypatch):
    # No row at all. Migration 126's column defaults ARE the answer — an
    # un-configured firm must not meet an error or a blank box.
    si, _ = _setup(monkeypatch)
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "INV/2026-27/001"
    assert d["gap"] is None


def test_the_stored_settings_row_is_what_decides(monkeypatch):
    si, _ = _setup(monkeypatch, {"prefix": "TX", "include_financial_year": True,
                                 "sequence_length": 4, "starting_number": 7,
                                 "manual_override_allowed": True})
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "TX/2026-27/0007"
    assert d["manual_override_allowed"] is True


def test_the_year_comes_from_the_invoice_date_and_not_the_clock(monkeypatch):
    # SALES-24's rule. A March invoice keyed in April belongs to March's series.
    si, _ = _setup(monkeypatch)
    march = si.next_invoice_number("CLI", invoice_date="2026-03-31", current_user=CALLER)["data"]
    april = si.next_invoice_number("CLI", invoice_date="2026-04-01", current_user=CALLER)["data"]
    assert march["fy_label"] == "2025-26" and march["suggested_number"] == "INV/2025-26/001"
    assert april["fy_label"] == "2026-27" and april["suggested_number"] == "INV/2026-27/001"


def test_the_sequence_is_read_from_this_clients_own_books(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    _seed_invoice(db, "INV/2026-27/002")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "INV/2026-27/003"


def test_a_deleted_invoices_number_is_not_counted(monkeypatch):
    # The uniqueness index is partial on deleted_at IS NULL, so a soft-deleted
    # draft's number is free again — and the suggestion must agree with the
    # constraint or it hands out a number the insert then rejects.
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    db.seed("client_sales_invoices", {
        "id": "INV-DEAD", "firm_id": FIRM, "client_id": "CLI",
        "invoice_no": "INV/2026-27/002", "invoice_date": "2026-04-10",
        "status": "draft", "deleted_at": "2026-04-11T00:00:00Z"})
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "INV/2026-27/002"


def test_another_clients_numbers_do_not_move_this_clients_series(monkeypatch):
    si, db = _setup(monkeypatch)
    db.seed("clients", {"id": "CLI-2", "firm_id": FIRM, "gstin": "27ZZZZZ9999Z1Z9"})
    db.seed("client_sales_invoices", {
        "id": "INV-OTHER", "firm_id": FIRM, "client_id": "CLI-2",
        "invoice_no": "INV/2026-27/500", "invoice_date": "2026-04-10",
        "status": "issued", "deleted_at": None})
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "INV/2026-27/001"


def test_a_series_without_the_year_keeps_climbing_instead_of_restarting(monkeypatch):
    # The uniqueness index is per CLIENT, not per financial year. A series with
    # no year in the number that restarted at 001 each April would collide with
    # its own previous year on the second year — so the window deliberately
    # sees every year's numbers when the head carries no year.
    si, db = _setup(monkeypatch, {"prefix": "INV", "include_financial_year": False,
                                  "sequence_length": 3, "starting_number": 1})
    _seed_invoice(db, "INV/041", date="2025-06-01")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] == "INV/042"


# ---------------------------------------------------------------------------
# A configuration that cannot produce a legal number says so, and suggests none.
# ---------------------------------------------------------------------------
def test_a_series_that_overflows_sixteen_characters_suggests_nothing_and_names_the_setting(monkeypatch):
    si, _ = _setup(monkeypatch, {"prefix": "INVOICES", "include_financial_year": True,
                                 "sequence_length": 6, "starting_number": 1})
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] is None
    assert d["gap"] and "sixteen" in d["gap"]


def test_a_prefix_with_a_forbidden_character_suggests_nothing(monkeypatch):
    si, _ = _setup(monkeypatch, {"prefix": "IN#V", "include_financial_year": True,
                                 "sequence_length": 3, "starting_number": 1})
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10", current_user=CALLER)["data"]
    assert d["suggested_number"] is None
    assert d["gap"] and "prefix" in d["gap"].lower()


# ---------------------------------------------------------------------------
# A number the CA has typed: refused, warned about, or neither.
# ---------------------------------------------------------------------------
def test_a_typed_number_that_is_next_draws_no_comment(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10",
                               invoice_no="INV/2026-27/002", current_user=CALLER)["data"]
    assert d["format_problem"] is None and d["sequence_warning"] is None


def test_a_typed_number_that_skips_ahead_warns(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10",
                               invoice_no="INV/2026-27/009", current_user=CALLER)["data"]
    assert d["sequence_warning"] and "INV/2026-27/002" in d["sequence_warning"]
    assert d["format_problem"] is None


def test_a_typed_number_from_a_second_series_is_left_alone(monkeypatch):
    # Rule 46(b) allows "one or multiple series". Complaining about the other
    # one trains a CA to ignore the warning that matters.
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10",
                               invoice_no="EXP/2026-27/001", current_user=CALLER)["data"]
    assert d["sequence_warning"] is None


def test_an_illegal_typed_number_reports_a_refusal_not_a_warning(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    d = si.next_invoice_number("CLI", invoice_date="2026-04-10",
                               invoice_no="INV#9", current_user=CALLER)["data"]
    assert d["format_problem"]
    # And not both at once — an illegal number's place in the sequence is not
    # the CA's problem to read about.
    assert d["sequence_warning"] is None


def test_an_unparseable_invoice_date_is_refused_rather_than_answered_for_today(monkeypatch):
    si, _ = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        si.next_invoice_number("CLI", invoice_date="not-a-date", current_user=CALLER)
    assert e.value.status_code == 422


# ---------------------------------------------------------------------------
# Create, edit, bulk and issue.
# ---------------------------------------------------------------------------
def test_creating_an_invoice_that_skips_a_number_succeeds_and_carries_the_warning(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    resp = si.create_invoice(_Payload(_invoice("INV/2026-27/044")), CALLER)
    assert resp["success"] is True
    assert resp["data"]["invoice_no"] == "INV/2026-27/044"
    assert resp["data"]["numbering_warning"], "a skipped number must be reported"


def test_creating_the_next_number_carries_no_warning(monkeypatch):
    si, db = _setup(monkeypatch)
    _seed_invoice(db, "INV/2026-27/001")
    resp = si.create_invoice(_Payload(_invoice("INV/2026-27/002")), CALLER)
    assert resp["success"] is True
    assert resp["data"]["numbering_warning"] is None


def test_the_pydantic_layer_refuses_a_number_rule_46b_forbids():
    # Also passes against the previous code — it refused too, with its own copy
    # of the regex. What this pins is that the copy is GONE and the delegation
    # gives the same answer: there were three spellings of Rule 46(b) in the
    # tree (this model, the router, the browser) and there are now two, pinned
    # to each other by tests/fixtures/invoice_number.json.
    with pytest.raises(Exception) as e:
        SalesInvoiceIn(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
                       invoice_no="INV#001",
                       lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x",
                                            hsn_sac="9982", quantity=1, rate_paise=1,
                                            gst_rate_percent=18.0)])
    assert "46(b)" in str(e.value)


def test_bulk_import_refuses_a_number_rule_46b_forbids(monkeypatch):
    # PASSES AGAINST THE PREVIOUS CODE TOO, and is kept for that reason: the
    # Pydantic field validator was already refusing here, so this pins that
    # delegating the rule to domain/gst/invoice_series did not weaken the bulk
    # path — not that it strengthened it. The row is rejected on its own without
    # aborting the batch, which is the CSV-import contract.
    si, _ = _setup(monkeypatch)
    good = _invoice("INV/2026-27/001")
    bad = dict(good, invoice_no="ABCDEFGHIJKLMNOPQ")
    resp = si.bulk_create_invoices(_BulkPayload([good, bad]), CALLER)
    assert len(resp["data"]["created"]) == 1
    assert len(resp["data"]["errors"]) == 1


def test_issuing_a_legacy_draft_with_an_illegal_number_is_refused(monkeypatch):
    # Drafts created before this change can carry one. Issue is the moment the
    # document becomes a tax invoice and the last moment the number can be
    # corrected without a §34 credit note.
    si, db = _setup(monkeypatch)
    db.seed("client_sales_invoices", {
        "id": "INV-LEGACY", "firm_id": FIRM, "client_id": "CLI",
        "invoice_no": "OLD#1", "invoice_date": "2026-04-10", "status": "draft",
        "supply_state_code": "27", "deleted_at": None})
    with pytest.raises(HTTPException) as e:
        si.issue_invoice("INV-LEGACY", CALLER)
    assert e.value.status_code == 422 and "46(b)" in e.value.detail


class _Payload:
    """Mimics the FastAPI-parsed SalesInvoiceIn body for a direct call."""
    def __init__(self, d):
        self._d = d
        self.client_id = d["client_id"]

    def model_dump(self):
        return self._d


class _BulkPayload:
    def __init__(self, invoices):
        self.invoices = invoices
