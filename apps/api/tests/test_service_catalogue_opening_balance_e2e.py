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
