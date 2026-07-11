"""
Opening-balance date resolution through the REAL (non-mock) create_service /
bulk_create_services code paths — the mock-mode tests in
test_service_catalogue.py / test_service_catalogue_bulk_create.py never
exercise _resolve_opening_balance_date at all (it's gated behind
`if not _USE_MOCK`), so this uses the e2e FakeDB harness the same way
test_purchase_bill_bulk_create.py does.
"""
import routers.service_catalogue as sc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "user-1", "auth_user_id": "auth-1", "email": "ca@firma.test", "role": "Partner"}
CLIENT = "CLI-A"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [sc])
    return db


class _BulkPayload:
    def __init__(self, services, opening_balance_date=None):
        self.services = services
        self.opening_balance_date = opening_balance_date


def test_create_service_persists_resolved_opening_balance_date(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn
    data = ServiceCatalogueIn(
        client_id=CLIENT, name="Widget", kind="good",
        opening_qty_units=10, opening_cost_paise=10_000_00,
    )
    resp = sc.create_service(data, CALLER)

    assert resp["success"] is True
    assert resp["data"]["opening_balance_date"] == "2025-04-01"
    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 1
    assert ledger[0]["movement_date"] == "2025-04-01"


def test_create_service_honors_explicit_opening_balance_date(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn
    data = ServiceCatalogueIn(
        client_id=CLIENT, name="Widget", kind="good",
        opening_qty_units=10, opening_cost_paise=10_000_00,
        opening_balance_date="2026-06-01",
    )
    resp = sc.create_service(data, CALLER)

    assert resp["data"]["opening_balance_date"] == "2026-06-01"
    assert db.rows("inventory_stock_ledger")[0]["movement_date"] == "2026-06-01"


def test_bulk_create_resolves_one_date_per_client_not_per_row(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    calls = {"clients": 0}
    orig_table = db.table

    def counting_table(name):
        if name == "clients":
            calls["clients"] += 1
        return orig_table(name)

    monkeypatch.setattr(db, "table", counting_table)

    items = [
        {"client_id": CLIENT, "name": f"Widget {i}", "kind": "good",
         "opening_qty_units": 10, "opening_cost_paise": 10_000_00}
        for i in range(5)
    ]
    resp = sc.bulk_create_services(_BulkPayload(items), CALLER)

    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 5
    for row in resp["data"]["created"]:
        assert row["opening_balance_date"] == "2025-04-01"
    assert calls["clients"] == 1  # resolved once for the whole batch, not once per row

    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 5
    assert all(r["movement_date"] == "2025-04-01" for r in ledger)


def test_bulk_create_honors_explicit_batch_opening_balance_date(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    items = [{"client_id": CLIENT, "name": "Widget", "kind": "good",
              "opening_qty_units": 10, "opening_cost_paise": 10_000_00}]
    resp = sc.bulk_create_services(_BulkPayload(items, opening_balance_date="2026-05-20"), CALLER)

    assert resp["data"]["created"][0]["opening_balance_date"] == "2026-05-20"
    assert db.rows("inventory_stock_ledger")[0]["movement_date"] == "2026-05-20"


def test_bulk_create_service_rows_without_opening_balance_get_no_date(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    items = [{"client_id": CLIENT, "name": "Statutory Audit", "kind": "service"}]
    resp = sc.bulk_create_services(_BulkPayload(items), CALLER)

    assert resp["data"]["created"][0].get("opening_balance_date") is None
    assert db.rows("inventory_stock_ledger") == []


def _block_posting_date(monkeypatch, message="Cannot post to a locked financial year: 2025-26."):
    from fastapi import HTTPException

    def _blocked(firm_id, date_str):
        raise HTTPException(status_code=422, detail=message)

    monkeypatch.setattr(sc.period_validation_service, "validate_posting_date", _blocked)


def test_create_service_fails_outright_when_opening_date_falls_in_locked_fy(monkeypatch):
    """An unresolvable opening-balance date must fail the whole create —
    silently creating the product without the opening balance the CA asked
    for (while reporting success) is itself the bug this feature exists to
    fix."""
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    _block_posting_date(monkeypatch)

    from models.service_catalogue import ServiceCatalogueIn
    data = ServiceCatalogueIn(
        client_id=CLIENT, name="Widget", kind="good",
        opening_qty_units=10, opening_cost_paise=10_000_00,
    )
    resp = sc.create_service(data, CALLER)

    assert resp["success"] is False
    assert "locked financial year" in resp["error"]
    assert db.rows("service_catalogue") == []
    assert db.rows("inventory_stock_ledger") == []


def test_bulk_create_reports_locked_fy_as_a_per_row_error_not_a_silent_skip(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})
    _block_posting_date(monkeypatch)

    items = [
        {"client_id": CLIENT, "name": "Widget A", "kind": "good",
         "opening_qty_units": 10, "opening_cost_paise": 10_000_00},
        {"client_id": CLIENT, "name": "Service Only", "kind": "service"},
    ]
    resp = sc.bulk_create_services(_BulkPayload(items), CALLER)

    assert resp["success"] is True  # the batch itself still completes
    created_names = {r["name"] for r in resp["data"]["created"]}
    assert created_names == {"Service Only"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["name"] == "Widget A"
    assert "locked financial year" in resp["data"]["errors"][0]["error"]
    assert not any(r["name"] == "Widget A" for r in db.rows("service_catalogue"))
    assert db.rows("inventory_stock_ledger") == []


def test_update_service_seeds_when_patch_only_sends_the_field_missing_from_create(monkeypatch):
    """A PATCH that supplies only ONE of opening_qty_units/opening_cost_paise
    (the other already set from an earlier save) must still resolve+seed
    against the combined state — not silently skip because this one PATCH
    didn't repeat both keys."""
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn, ServiceCatalogueUpdateIn
    created = sc.create_service(
        ServiceCatalogueIn(client_id=CLIENT, name="Widget", kind="good", opening_qty_units=10),
        CALLER,
    )
    service_id = created["data"]["id"]
    assert db.rows("inventory_stock_ledger") == []  # no cost yet on create — nothing seeded

    resp = sc.update_service(service_id, ServiceCatalogueUpdateIn(opening_cost_paise=5_000_00), CALLER)

    assert resp["success"] is True
    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 1
    assert ledger[0]["movement_date"] == "2025-04-01"


def test_update_service_never_nulls_existing_opening_date_on_locked_fy_failure(monkeypatch):
    """A locked-FY resolution failure on edit must fail the whole PATCH, not
    silently null out an already-persisted opening_balance_date while still
    reporting success."""
    db = _setup(monkeypatch)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn, ServiceCatalogueUpdateIn
    created = sc.create_service(
        ServiceCatalogueIn(client_id=CLIENT, name="Widget", kind="good",
                            opening_qty_units=10, opening_cost_paise=10_000_00),
        CALLER,
    )
    service_id = created["data"]["id"]
    assert created["data"]["opening_balance_date"] == "2025-04-01"

    _block_posting_date(monkeypatch)
    resp = sc.update_service(
        service_id, ServiceCatalogueUpdateIn(opening_qty_units=20, opening_cost_paise=20_000_00), CALLER,
    )

    assert resp["success"] is False
    row = next(r for r in db.rows("service_catalogue") if r["id"] == service_id)
    assert row["opening_balance_date"] == "2025-04-01"  # untouched
    assert row["opening_qty_units"] == 10  # untouched too — the whole PATCH was rejected
