"""
Where a deduction is FILED, and what a 26Q return must stop swallowing.

Rule 31A(4) splits the quarterly statement by the payee's residence: (a) 26Q
for non-salary payments to residents, (b) 27Q for payments to non-residents.
Before migration 308 nothing recorded the difference and every deduction went
into 26Q — so a foreign remittance was not merely missing from 27Q, it was
wrongly present in 26Q, which is a return that reconciles and is still wrong.

Two halves: the register row (services/tds_register_service) and the 26Q
assembled from the books (services/tds_return_service).
"""
from __future__ import annotations

from domain.tds.residency import (
    FORM_26Q, FORM_27Q, GAP_27Q_IDENTIFIERS_MISSING, GAP_RESIDENCY_NOT_CLASSIFIED,
)
from services.tds_register_service import sync_for_bill


class _DB:
    """Minimal Supabase double — records the upserted payload."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._pending_delete = False
        self._filters: dict = {}

    def table(self, name):
        assert name == "tds_deductions", name
        self._pending_delete = False
        self._filters = {}
        return self

    def upsert(self, payload, on_conflict=None):
        self.rows[payload["purchase_bill_id"]] = payload
        return self

    def delete(self):
        self._pending_delete = True
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        if self._pending_delete:
            self.rows.pop(self._filters.get("purchase_bill_id"), None)
        return type("R", (), {"data": []})()


BILL = {
    "id": "b1", "client_id": "c1", "vendor_id": "v1", "status": "received",
    "bill_date": "2025-10-25", "taxable_amount_paise": 18_000_00,
    "tds_paise": 360_00, "tds_rate_bps": 200, "tds_section": "194C",
}

RESIDENT_VENDOR = {"id": "v1", "name": "Pinnacle Engineering", "pan": "AAGCP7788R",
                   "residential_status": "resident"}
NR_VENDOR = {"id": "v1", "name": "Helvetica Design AG", "pan": None,
             "residential_status": "non_resident",
             "country_of_residence": "CH", "tax_identification_number": "CHE-113.456.789"}


def _sync(vendor):
    db = _DB()
    out = sync_for_bill(db, "f1", "c1", dict(BILL), vendor)
    return db.rows["b1"], out


# ── The register row ─────────────────────────────────────────────────────────

def test_a_resident_vendors_deduction_is_a_26q_row():
    row, out = _sync(RESIDENT_VENDOR)
    assert row["return_type"] == FORM_26Q
    assert out["return_type"] == FORM_26Q
    assert "statutory_gaps" not in out


def test_a_non_residents_deduction_is_a_27q_row_carrying_country_and_tin():
    row, out = _sync(NR_VENDOR)
    assert row["return_type"] == FORM_27Q
    assert row["country_of_residence"] == "CH"
    assert row["deductee_tin"] == "CHE-113.456.789"
    assert "statutory_gaps" not in out


def test_a_26q_row_carries_no_country_or_tin():
    """26Q has no field for either. A value in a column the return never reads
    is worse than an empty one — it looks like somebody meant something by it."""
    row, _ = _sync({**RESIDENT_VENDOR,
                    "country_of_residence": "IN",
                    "tax_identification_number": "SHOULD-NOT-BE-COPIED"})
    assert row["country_of_residence"] is None
    assert row["deductee_tin"] is None


def test_an_unclassified_vendor_files_26q_and_says_so():
    """The default is defensible; the silence was not."""
    row, out = _sync({"id": "v1", "name": "Someone", "pan": "AAGCP7788R"})
    assert row["return_type"] == FORM_26Q
    assert out["statutory_gaps"] == [GAP_RESIDENCY_NOT_CLASSIFIED]
    assert out["vendor_name"] == "Someone", "a gap nobody can trace to a vendor is not actionable"


def test_a_non_resident_missing_its_27q_identifiers_is_reported():
    row, out = _sync({"id": "v1", "name": "Opaque Ltd", "pan": None,
                      "residential_status": "non_resident"})
    assert row["return_type"] == FORM_27Q, "the row still belongs in 27Q"
    assert out["statutory_gaps"] == [GAP_27Q_IDENTIFIERS_MISSING]


def test_an_unclassified_vendor_is_not_also_reported_as_missing_27q_fields():
    """It is a 26Q row — asking it for a TIN would be noise, and two gaps for
    one unknown fact reads as two problems."""
    _, out = _sync({"id": "v1", "name": "Someone"})
    assert out["statutory_gaps"] == [GAP_RESIDENCY_NOT_CLASSIFIED]


# ── 26Q from the books ───────────────────────────────────────────────────────

class _BooksDB:
    """Enough of Supabase for tds_26q_from_books: bills, vendors, challans,
    accounts and journal lines."""

    def __init__(self, bills, vendors):
        self._bills = bills
        self._vendors = vendors
        self._t = None
        self._filters: dict = {}

    def table(self, name):
        self._t = name
        self._filters = {}
        return self

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[col] = list(vals)
        return self

    def or_(self, *a):
        return self

    def limit(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def gt(self, *a):
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def execute(self):
        if self._t == "purchase_bills":
            return type("R", (), {"data": list(self._bills)})()
        if self._t == "vendors":
            wanted = self._filters.get("id") or []
            return type("R", (), {"data": [v for v in self._vendors if v["id"] in wanted]})()
        return type("R", (), {"data": []})()


def _books(bills, vendors):
    from services.tds_return_service import tds_26q_from_books
    return tds_26q_from_books(
        _BooksDB(bills, vendors), "f1", "c1", "2025-26", "Q3",
        "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")


def _bill(bid, vid, tds):
    return {"id": bid, "vendor_id": vid, "bill_no": f"BILL-{bid}",
            "bill_date": "2025-10-25", "status": "received",
            "taxable_amount_paise": 18_000_00, "tds_paise": tds,
            "tds_rate_bps": 200, "tds_section": "194C", "journal_entry_id": None}


def test_26q_leaves_a_non_residents_bill_out_and_names_it():
    out = _books(
        [_bill("b1", "v1", 360_00), _bill("b2", "v2", 500_00)],
        [{"id": "v1", "name": "Pinnacle Engineering", "pan": "AAGCP7788R",
          "residential_status": "resident"},
         {"id": "v2", "name": "Helvetica Design AG", "pan": None,
          "residential_status": "non_resident"}])
    assert out["deductee_count"] == 1
    assert out["deductees"][0]["deductee_name"] == "Pinnacle Engineering"
    excluded = out["excluded_non_resident"]
    assert excluded["bill_count"] == 1
    assert excluded["tds_paise"] == 500_00
    assert excluded["bills"][0]["vendor_name"] == "Helvetica Design AG"
    assert "27Q" in excluded["reason"]


def test_the_excluded_tds_is_out_of_the_26q_total_too():
    """Excluded before the totals, not filtered out of the deductee list after
    — otherwise the return's own total would not equal its own rows."""
    out = _books(
        [_bill("b1", "v1", 360_00), _bill("b2", "v2", 500_00)],
        [{"id": "v1", "name": "R", "pan": "AAGCP7788R", "residential_status": "resident"},
         {"id": "v2", "name": "NR", "pan": None, "residential_status": "non_resident"}])
    assert out["total_tds_deducted_paise"] == 360_00
    assert out["total_tds_deducted_paise"] == sum(
        d["tds_deducted_paise"] for d in out["deductees"])


def test_an_unclassified_vendor_stays_in_26q():
    """Excluding on 'not known to be resident' would empty every existing
    client's return the day the column was added."""
    out = _books([_bill("b1", "v1", 360_00)],
                 [{"id": "v1", "name": "Legacy Vendor", "pan": "AAGCP7788R"}])
    assert out["deductee_count"] == 1
    assert out["excluded_non_resident"]["bill_count"] == 0


def test_a_return_with_nothing_excluded_still_reports_the_key():
    """A key that appears only when there is bad news is a key nobody builds a
    screen against."""
    out = _books([_bill("b1", "v1", 360_00)],
                 [{"id": "v1", "name": "R", "pan": "AAGCP7788R",
                   "residential_status": "resident"}])
    assert out["excluded_non_resident"] == {
        "bill_count": 0, "tds_paise": 0,
        "reason": out["excluded_non_resident"]["reason"], "bills": []}


def test_the_24q_salary_return_did_not_grow_a_non_resident_key():
    """The two return dicts share their last two lines, so a blind edit puts a
    'non-resident' exclusion into the SALARY return, where it means nothing."""
    import inspect
    from services import tds_return_service as m
    src = inspect.getsource(m.tds_24q_from_books)
    assert "excluded_non_resident" not in src


# ── The bill path refuses, rather than deducting at the wrong section ────────

def _compute(vendor, section="194C"):
    """Drive the shared create/update compute path for a one-line bill."""
    from domain.currency.document_currency import identity_currency
    from routers.purchase_bills import _compute_bill_lines_and_totals
    return _compute_bill_lines_and_totals(
        lines_data=[{"description": "Job work", "quantity": 1,
                     "rate_paise": 5_00_000_00, "gst_rate": 18}],
        is_interstate=False,
        vendor={**vendor, "tds_applicable": True, "tds_section": section,
                "state_code": "27"},
        bill_date="2025-10-25",
        firm_id="f1",
        dc=identity_currency("2025-10-25"),
        db=None,
    )


def test_a_resident_vendor_still_deducts_under_194c():
    """The negative control for every refusal below: nothing changed for the
    domestic vendor this platform is built for."""
    out = _compute({"id": "v1", "pan": "AAGCP7788R", "residential_status": "resident"})
    assert out["tds_section"] == "194C"
    assert out["tds_paise"] == 10_000_00          # 2% of Rs 5,00,000
    assert out["tds_rate_bps"] == 200


def test_an_unclassified_vendor_still_deducts_under_194c():
    out = _compute({"id": "v1", "pan": "AAGCP7788R"})
    assert out["tds_paise"] == 10_000_00


def test_194c_on_a_non_resident_is_refused_not_deducted():
    """s.194C(1) charges sums paid 'to any resident'. Deducting 2% here would
    be a wrong deduction AND a wrong return — and under-deduction under s.195
    disallows the whole expenditure under s.40(a)(i)."""
    from fastapi import HTTPException
    import pytest as _pytest
    with _pytest.raises(HTTPException) as e:
        _compute({"id": "v1", "pan": None, "residential_status": "non_resident",
                  "country_of_residence": "CH"})
    assert e.value.status_code == 422
    assert "195" in e.value.detail
    assert "non-resident" in e.value.detail.lower()


def test_section_195_on_the_vendor_is_refused_with_its_own_message():
    """Before this it raised 'Unknown TDS section 195' — true, and useless."""
    from fastapi import HTTPException
    import pytest as _pytest
    with _pytest.raises(HTTPException) as e:
        _compute({"id": "v1", "pan": None, "residential_status": "non_resident",
                  "country_of_residence": "CH"}, section="195")
    assert "Unknown TDS section" not in e.value.detail
    assert "15CA" in e.value.detail


def test_a_non_resident_with_tds_switched_off_books_normally():
    """The refusal is aimed at an instruction the software cannot carry out,
    not at the bill. A foreign supplier's invoice is ordinary bookkeeping."""
    from domain.currency.document_currency import identity_currency
    from routers.purchase_bills import _compute_bill_lines_and_totals
    out = _compute_bill_lines_and_totals(
        lines_data=[{"description": "Design retainer", "quantity": 1,
                     "rate_paise": 5_00_000_00, "gst_rate": 0}],
        is_interstate=False,
        vendor={"id": "v1", "tds_applicable": False, "tds_section": "194J",
                "state_code": "27", "residential_status": "non_resident",
                "country_of_residence": "CH"},
        bill_date="2025-10-25", firm_id="f1",
        dc=identity_currency("2025-10-25"), db=None)
    assert out["tds_paise"] == 0
    assert out["total_paise"] == 5_00_000_00


# ── Reading one statement's rows back out ───────────────────────────────────

def test_the_register_can_be_read_as_one_statement_or_the_other(monkeypatch):
    """The register holds both, because they come from the same bills and the
    same deduction event. They are FILED apart, so a caller assembling either
    has to be able to ask for one — Rule 31A(4)(a) and (b)."""
    from repositories import tds_repository as repo

    rows = [
        {"id": "1", "firm_id": "f1", "client_id": "c1", "return_type": "26Q",
         "deductee_name": "Pinnacle", "tds_paise": 36000},
        {"id": "2", "firm_id": "f1", "client_id": "c1", "return_type": "27Q",
         "deductee_name": "Helvetica Design AG", "tds_paise": 50000,
         "country_of_residence": "CH"},
        # Written before migration 014's default landed: no return_type at all,
        # and it was a 26Q deduction.
        {"id": "3", "firm_id": "f1", "client_id": "c1",
         "deductee_name": "Legacy", "tds_paise": 1000},
    ]
    monkeypatch.setattr(repo, "MOCK_TDS_DEDUCTIONS", rows)
    monkeypatch.setattr(repo, "_USE_MOCK", True)

    def ids(return_type):
        return [r["id"] for r in repo.tds_repo.get_deductions(
            client_id="c1", firm_id="f1", return_type=return_type)]

    assert ids("27Q") == ["2"]
    assert ids("26Q") == ["1", "3"], (
        "a row predating the return_type default was a 26Q deduction and must "
        "not vanish from 26Q or appear in 27Q")
    assert ids(None) == ["1", "2", "3"], "no filter still means the whole register"


def test_a_return_type_the_column_cannot_hold_is_refused():
    """Passing '27B' would otherwise return an empty list, which reads as 'this
    client made no such deductions' rather than 'you asked for a form that does
    not exist'."""
    import inspect
    from routers import tds as m
    src = inspect.getsource(m.get_tds_deductions)
    assert '("24Q", "26Q", "27Q", "27EQ")' in src
    assert "422" in src


def test_omitting_the_filter_does_not_422_a_direct_caller():
    """FastAPI's Query default is a truthy object, not None, so a direct call
    that never asked for a filter would fail the return_type validation. Caught
    by tests/test_tds_repository.py before this shipped; pinned here because the
    next person to add a validated Query parameter meets the same trap."""
    from routers.tds import get_tds_deductions
    import inspect
    default = inspect.signature(get_tds_deductions).parameters["return_type"].default
    assert not isinstance(default, str) and bool(default), (
        "the premise of this test — the default is a truthy non-string")
    src = inspect.getsource(get_tds_deductions)
    assert "isinstance(return_type, str)" in src
