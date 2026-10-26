"""POST-A-070 — the door to Part A of the return, and the door that records which row a block is declared on.

WHAT THE DOOR HOLDS

    * `GET /api/itr/filings/{id}/books-schedules` is the YEAR-END STATEMENTS RE-LAID, so it is read under two permissions and not one:
      `income_tax:compute` (who prepares a return) and `year_end:read` (who may see the financial statements). A Partner who kept a
      person from the statements has kept them from this sheet too; the refusal says what the sheet is.
    * IT IS BUILT OVER THE FILING: the form and the year are the filing's, the filing is read under the CALLER's firm, and a filing whose
      form carries no balance sheet is refused in a sentence and not answered with an empty sheet.
    * It reads and writes nothing, produces no file and says on every answer that the line-to-box table is not confirmed.
    * `PUT /api/income-tax/section-32/blocks` takes the block's row only when it was SENT (an older screen cannot clear a recorded row
      by omitting it), refuses a key that is not a row of the return and a row whose rate disagrees with the block's, and writes no
      column the database may not have (migration 552) for a caller that never named it.
    * `GET /api/income-tax/section-32/itr-rows` serves the vocabulary the screen offers, read from the Department's own schema.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.permissions as permissions
import routers.income_tax as income_tax_router
import routers.itr_workspace as iw
from domain.income_tax import itr_workflow
from main import app
from services import itr_books_schedules_service as svc
from tests._books_statements import balanced_statements

client = TestClient(app, raise_server_exceptions=False)
FIRM, CLIENT, FILING = "firm-1", "client-1", "filing-1"


def _h(role: str = "Partner") -> dict:
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


def _filing(form: str = "ITR-3", **kw) -> dict:
    return {"id": FILING, "firm_id": FIRM, "client_id": CLIENT, "itr_form": form, "financial_year": "2025-26",
            "assessment_year": "2026-27", "status": "draft", "return_type": "original", **kw}


@pytest.fixture
def books(monkeypatch):
    """A filing the caller may open, books that balance, and no database: the whole path runs and nothing reaches Postgres."""
    seen = {"firm": []}

    def get_filing(firm_id, filing_id):
        seen["firm"].append(firm_id)
        return _filing() if filing_id == FILING else None

    monkeypatch.setattr(itr_workflow, "get_filing", get_filing)
    monkeypatch.setattr("services.year_end_financial_service.generate_financial_statements",
                        lambda db, client_id, firm_id, fy_start, fy_end, rounding_unit=None: {
                            **balanced_statements(), "fy_start": fy_start, "fy_end": fy_end, "client_id": client_id})
    monkeypatch.setattr(iw.db_provider, "service_db_or_none", lambda: None)
    return seen


def _allow(monkeypatch, allowed):
    """The caller holds exactly the `allowed` pairs, whatever the role table says."""
    monkeypatch.setattr(permissions, "can_user", lambda user, resource, action: (resource, action) in allowed)
    monkeypatch.setattr(iw, "can_user", lambda user, resource, action: (resource, action) in allowed)


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("dev_header_auth")
def test_a_partner_gets_part_a_for_the_filings_own_form_and_year(books):
    r = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["error"] is None
    sheet = body["data"]
    assert sheet["form"] == "ITR-3" and sheet["assessment_year"] == "2026-27" and sheet["financial_year"] == "2025-26"
    assert sheet["period"] == {"start": "2025-04-01", "end": "2026-03-31"}
    assert sheet["filing_id"] == FILING and sheet["status"] == "draft" and sheet["return_type"] == "original"
    assert sheet["mapping_confirmed"] is False
    assert sheet["tie_out"]["ok"] is True and sheet["tie_out"]["difference_paise"] == 0
    assert sheet["balance_sheet"]["layout"] == "funds_sourced_and_applied"
    # No database is configured, so no blocks and no register: said, not filled.
    assert sheet["depreciation"]["rows"] == [] and any("register was not read" in g for g in sheet["gaps"])


@pytest.mark.usefixtures("dev_header_auth")
def test_the_filing_is_read_under_the_callers_firm(books):
    client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h())
    assert books["firm"] == [FIRM]


@pytest.mark.usefixtures("dev_header_auth")
def test_a_filing_the_caller_cannot_see_is_a_404(books):
    r = client.get("/api/itr/filings/someone-elses/books-schedules", headers=_h())
    assert r.status_code == 404 and "Filing not found" in r.text


@pytest.mark.usefixtures("dev_header_auth")
def test_a_reviewer_is_refused_at_the_door(books):
    r = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h("Reviewer"))
    assert r.status_code == 403, r.text
    assert "balance_sheet" not in r.text


@pytest.mark.usefixtures("dev_header_auth")
def test_a_person_kept_from_the_financial_statements_is_kept_from_this_sheet(books, monkeypatch):
    _allow(monkeypatch, {("income_tax", "compute"), ("income_tax", "read")})
    r = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h())
    assert r.status_code == 403, r.text
    assert "financial statements" in r.json()["detail"]
    assert "balance_sheet" not in r.text and "tie_out" not in r.text


@pytest.mark.usefixtures("dev_header_auth")
def test_negative_control_with_both_permissions_the_same_request_is_served(books, monkeypatch):
    _allow(monkeypatch, {("income_tax", "compute"), ("year_end", "read")})
    assert client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h()).status_code == 200


@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("form", ["ITR-1", "ITR-2", "ITR-4", "ITR-7"])
def test_a_filing_whose_form_has_no_balance_sheet_is_refused_in_a_sentence(books, monkeypatch, form):
    monkeypatch.setattr(itr_workflow, "get_filing", lambda firm_id, filing_id: _filing(form))
    r = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert form in body["error"] and "ITR-3, ITR-5, ITR-6" in body["error"]


@pytest.mark.usefixtures("dev_header_auth")
def test_books_that_do_not_balance_are_refused_in_the_statements_own_words(books, monkeypatch):
    def refuse(*a, **k):
        raise ValueError("Balance Sheet does not balance: Assets=5 paise, Equity+Liabilities=4 paise, Difference=1 paise.")
    monkeypatch.setattr("services.year_end_financial_service.generate_financial_statements", refuse)
    body = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h()).json()
    assert body["success"] is False and "does not balance" in body["error"]


def test_the_route_asks_the_prepare_tier_at_the_door():
    route = next(r for r in iw.router.routes if getattr(r, "path", "") == "/itr/filings/{filing_id}/books-schedules"
                 or str(getattr(r, "path", "")).endswith("/filings/{filing_id}/books-schedules"))
    assert [d.call.__name__ for d in route.dependant.dependencies if d.call.__name__.startswith("rbac_")] == [
        "rbac_income_tax_compute"]


@pytest.fixture
def as_a_scoped_executive(monkeypatch):
    """A member assigned to ONE client (not the filing's) of a firm that has the filing: the scope is real, not the mock's open door."""
    from core import authz
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {"C-MINE"})


@pytest.mark.usefixtures("dev_header_auth")
def test_a_filing_of_a_client_the_caller_is_not_assigned_to_is_a_404_and_the_books_are_never_read(books, as_a_scoped_executive,
                                                                                               monkeypatch):
    """The filing EXISTS and is the firm's; the caller is assigned to a different client. The answer is the same 404 an absent filing
    gets, and the year-end statements are not even asked for."""
    read = []
    monkeypatch.setattr("services.year_end_financial_service.generate_financial_statements",
                        lambda *a, **k: read.append(a) or balanced_statements())
    hidden = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h("Executive"))
    missing = client.get("/api/itr/filings/nobody/books-schedules", headers=_h("Executive"))
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    assert read == [] and "balance_sheet" not in hidden.text
    # Negative control: the same filing, assigned to the caller's own client, is served.
    monkeypatch.setattr(itr_workflow, "get_filing", lambda firm_id, filing_id: _filing(client_id="C-MINE"))
    assert client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h("Executive")).status_code == 200
    assert read, "the books were not read for the client the caller IS assigned to"


@pytest.mark.usefixtures("dev_header_auth")
def test_the_scope_is_asked_before_the_statements_permission_so_a_refusal_tells_nothing_about_the_filing(
        books, as_a_scoped_executive, monkeypatch):
    # Not assigned AND kept from the statements: a 404, not a 403 that would confirm the filing exists.
    _allow(monkeypatch, {("income_tax", "compute"), ("income_tax", "read")})
    assert client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h("Executive")).status_code == 404
    # Assigned and kept from the statements: the 403 that says what the sheet is.
    monkeypatch.setattr(itr_workflow, "get_filing", lambda firm_id, filing_id: _filing(client_id="C-MINE"))
    r = client.get(f"/api/itr/filings/{FILING}/books-schedules", headers=_h("Executive"))
    assert r.status_code == 403 and "financial statements" in r.json()["detail"]


def test_the_service_reads_the_filings_form_and_year_and_nothing_else_of_the_request():
    import inspect
    sig = inspect.signature(svc.for_filing)
    assert list(sig.parameters) == ["db", "firm_id", "filing"]
    assert [p.kind.name for p in sig.parameters.values()] == ["POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY", "KEYWORD_ONLY"]


def test_the_service_makes_no_second_read_of_the_ledger():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(svc))
    tables = {n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table" and n.args
              and isinstance(n.args[0], ast.Constant)}
    # The register's rows, and (POST-A-344) the chart account each asset category is booked to, read only for the line it is on. A table
    # that holds the LEDGER (the journals and the monthly balances) is never read here: the statements are the one answer to a balance.
    assert tables == {"fixed_assets", "chart_of_accounts"}, tables


# ── the service, with a database ──────────────────────────────────────────────────────────────────────────────────────────────
class _Query:
    def __init__(self, log):
        self.log = log

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.log.append((col, val))
        return self

    def is_(self, col, val):
        self.log.append((col, val))
        return self


class _Db:
    def __init__(self):
        self.log: list = []

    def table(self, name):
        self.log.append(("table", name))
        return _Query(self.log)


def test_the_register_is_read_under_the_firm_and_the_client_and_fills_the_gross_block_when_it_ties(monkeypatch):
    from tests.test_the_depreciation_schedules_come_from_the_blocks import _plant, _result
    db = _Db()
    # One asset: cost 15 lakh, 5 lakh depreciated to date, so its net block is the ledger's 9.5 lakh of tangible and intangible assets.
    asset = {"asset_category": "Plant", "purchase_cost_paise": 15_00_000_00, "accumulated_depreciation_paise": 5_50_000_00,
             "purchase_date": "2024-06-01", "is_disposed": False, "depreciation_fy": "2025-26",
             "depreciation_fy_start_accum_paise": 0, "firm_id": FIRM, "client_id": CLIENT}
    monkeypatch.setattr(svc, "fetch_all", lambda make_query, **kw: (make_query(), [asset])[1])
    monkeypatch.setattr("services.year_end_financial_service.generate_financial_statements",
                        lambda *a, **k: balanced_statements())
    monkeypatch.setattr(svc.section_32_service, "assemble",
                        lambda db_, firm, client, fy: (db.log.append(("section_32", firm, client, fy)),
                                                       _result(_plant(), rows={"P&M 15%": "PlantMachinery.Rate15"}))[1])
    out = svc.for_filing(db, firm_id=FIRM, filing=_filing())
    assert ("firm_id", FIRM) in db.log and ("client_id", CLIENT) in db.log and ("deleted_at", "null") in db.log
    assert ("section_32", FIRM, CLIENT, "2025-26") in db.log
    parts = {p["label"]: p for p in next(s for s in out["balance_sheet"]["asset_slots"] if s["key"] == "fixed_assets")["parts"]}
    assert parts["Gross block"]["amount_paise"] == 15_00_000_00 and parts["Depreciation"]["amount_paise"] == 5_50_000_00
    assert [r["row_key"] for r in out["depreciation"]["rows"]] == ["PlantMachinery.Rate15"]
    assert out["tie_out"]["ok"] is True


def test_a_financial_year_the_books_cannot_be_read_for_is_refused():
    with pytest.raises(svc.NotAssembled):
        svc.for_filing(None, firm_id=FIRM, filing=_filing(financial_year="not-a-year"))


# ── recording which row a block is declared on ────────────────────────────────────────────────────────────────────────────────────
class _Upsert:
    def __init__(self, sink):
        self.sink = sink

    def table(self, name):
        self.sink["table"] = name
        return self

    def upsert(self, row, on_conflict=None):
        self.sink["row"], self.sink["on_conflict"] = row, on_conflict
        return self

    def execute(self):
        return type("R", (), {"data": [self.sink["row"]]})()


@pytest.fixture
def sink(monkeypatch):
    out: dict = {}
    monkeypatch.setattr(income_tax_router, "_db", lambda: _Upsert(out))
    return out


def _block(**kw) -> dict:
    return {"client_id": CLIENT, "financial_year": "2025-26", "block_key": "P&M 15%", "rate_percent": 15,
            "opening_wdv_paise": 10_00_000_00, **kw}


@pytest.mark.usefixtures("dev_header_auth")
def test_a_block_records_its_row(sink):
    r = client.put("/api/income-tax/section-32/blocks", json=_block(itr_schedule_row="PlantMachinery.Rate15"), headers=_h())
    assert r.status_code == 200, r.text
    assert sink["row"]["itr_schedule_row"] == "PlantMachinery.Rate15" and sink["table"] == "income_tax_asset_blocks"


@pytest.mark.usefixtures("dev_header_auth")
def test_a_request_that_does_not_name_the_row_leaves_a_recorded_row_alone(sink):
    """The upsert replaces the row it names; leaving the key out of the payload is what keeps a recorded row, and keeps the call from
    naming a column a database without migration 552 does not have."""
    r = client.put("/api/income-tax/section-32/blocks", json=_block(), headers=_h())
    assert r.status_code == 200, r.text
    assert "itr_schedule_row" not in sink["row"]


@pytest.mark.usefixtures("dev_header_auth")
def test_sending_null_clears_the_row_on_purpose(sink):
    r = client.put("/api/income-tax/section-32/blocks", json=_block(itr_schedule_row=None), headers=_h())
    assert r.status_code == 200, r.text
    assert sink["row"]["itr_schedule_row"] is None


@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("row,says", [
    ("PlantMachinery.Rate99", "not a row"),
    ("Plant and machinery", "not a row"),
    ("PlantMachinery.Rate30", "30 per cent row"),
    ("Land", "not depreciated"),
])
def test_a_row_that_is_not_the_blocks_is_refused_in_a_sentence(sink, row, says):
    r = client.put("/api/income-tax/section-32/blocks", json=_block(itr_schedule_row=row), headers=_h())
    assert r.status_code == 422, r.text
    assert says in r.text and "row" not in sink


@pytest.mark.usefixtures("dev_header_auth")
def test_land_takes_a_block_at_nil(sink):
    r = client.put("/api/income-tax/section-32/blocks", json=_block(rate_percent=0, itr_schedule_row="Land"), headers=_h())
    assert r.status_code == 200, r.text


@pytest.mark.usefixtures("dev_header_auth")
def test_the_vocabulary_is_served_from_the_departments_schema():
    r = client.get("/api/income-tax/section-32/itr-rows", headers=_h("Reviewer"))
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["rows"]
    assert [x["key"] for x in rows][:2] == ["PlantMachinery.Rate15", "PlantMachinery.Rate30"]
    assert {x["key"]: x["rate_percent"] for x in rows}["Land"] is None


def test_the_section_32_service_carries_the_row_and_the_working_out_to_every_reader():
    from services.section_32_service import block_to_dict
    from tests.test_the_depreciation_schedules_come_from_the_blocks import _plant, FY_END
    from domain.income_tax.section_32 import compute_block
    d = block_to_dict(compute_block(_plant(), fy_end=FY_END), "PlantMachinery.Rate15")
    assert d["itr_schedule_row"] == "PlantMachinery.Rate15" and d["itr_schedule_row_caption"] == "Plant and machinery, 15 per cent"
    assert block_to_dict(compute_block(_plant(), fy_end=FY_END), "Gone.Rate9")["itr_schedule_row_caption"] == "Gone.Rate9"
    for k in ("realization_against_full_paise", "depreciation_base_full_paise", "depreciation_at_full_rate_paise",
              "additional_on_full_rate_additions_paise"):
        assert k in d
    unset = block_to_dict(compute_block(_plant(), fy_end=FY_END))
    assert unset["itr_schedule_row"] is None and unset["itr_schedule_row_caption"] is None


# ── recording a block's row on its own, without touching the rest of the block ─────────────────────────────────────────────────────
class _Blocks:
    """Just enough of the table: one recorded block, a select that finds it by its key, an update that records what it was given."""
    def __init__(self, rate=15, present=True):
        self.rows = [{"id": "b1", "rate_percent": rate}] if present else []
        self.updated = None
        self.filters: list = []

    def table(self, name):
        self.filters.append(("table", name))
        return self

    def select(self, *_a, **_k):
        return self

    def update(self, values):
        self.updated = values
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def execute(self):
        data = self.rows if self.updated is None else [{"id": "b1", **self.updated}]
        return type("R", (), {"data": data})()


def _row_body(**kw) -> dict:
    return {"client_id": CLIENT, "financial_year": "2025-26", "block_key": "P&M 15%", "itr_schedule_row": "PlantMachinery.Rate15", **kw}


@pytest.mark.usefixtures("dev_header_auth")
def test_a_blocks_row_is_recorded_on_its_own_and_only_that_column_is_written(monkeypatch):
    db = _Blocks(rate=15)
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(), headers=_h())
    assert r.status_code == 200, r.text
    assert set(db.updated) == {"itr_schedule_row", "updated_at"} and db.updated["itr_schedule_row"] == "PlantMachinery.Rate15"
    # Found and updated under the caller's firm and the named client, never by the block's id alone.
    assert ("firm_id", FIRM) in db.filters and ("client_id", CLIENT) in db.filters and ("block_key", "P&M 15%") in db.filters


@pytest.mark.usefixtures("dev_header_auth")
def test_a_row_whose_rate_is_not_the_recorded_blocks_is_refused_and_nothing_is_written(monkeypatch):
    db = _Blocks(rate=15)
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(itr_schedule_row="PlantMachinery.Rate30"), headers=_h())
    assert r.status_code == 422 and "30 per cent row" in r.text and "15 per cent" in r.text
    assert db.updated is None


@pytest.mark.usefixtures("dev_header_auth")
def test_a_key_that_is_not_a_row_is_refused_before_the_database_is_asked(monkeypatch):
    db = _Blocks()
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(itr_schedule_row="Spaceship.Rate7"), headers=_h())
    assert r.status_code == 422 and "not a row" in r.text and db.filters == [] and db.updated is None


@pytest.mark.usefixtures("dev_header_auth")
def test_a_block_that_is_not_recorded_is_a_404_and_is_not_made(monkeypatch):
    db = _Blocks(present=False)
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(), headers=_h())
    assert r.status_code == 404 and db.updated is None


@pytest.mark.usefixtures("dev_header_auth")
def test_null_takes_the_recorded_row_back(monkeypatch):
    db = _Blocks()
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(itr_schedule_row=None), headers=_h())
    assert r.status_code == 200 and db.updated["itr_schedule_row"] is None


@pytest.mark.usefixtures("dev_header_auth")
def test_a_reviewer_cannot_record_a_blocks_row(monkeypatch):
    db = _Blocks()
    monkeypatch.setattr(income_tax_router, "_db", lambda: db)
    r = client.put("/api/income-tax/section-32/blocks/row", json=_row_body(), headers=_h("Reviewer"))
    assert r.status_code == 403 and db.updated is None
