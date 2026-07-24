"""
Task #230 — critical cross-tenant isolation gaps (billing, advance tax).

Both confirmed findings shared the same root cause: a caller-supplied
client_id was used in a write path without checking it belongs to the
caller's own firm — the platform's established core.authz.assert_client_access
guard (already used by routers/engagements.py etc.) was simply missing.

- Billing: routers/billing.py::create_schedule + services/billing_service.py's
  ensure_customer_link (defense-in-depth twin) could read/copy ANOTHER firm's
  client's real PAN/GSTIN into a customer row inside the caller's own books.
- Advance tax: routers/income_tax.py::save_advance_tax could upsert against
  another firm's client_id, and the underlying UNIQUE(client_id,
  financial_year, installment_number) constraint (no firm_id) meant that
  upsert would silently overwrite that firm's real record.

Journal kernel, engagement letters, and year-end adjustments were
independently audited and found already properly firm/client-scoped —
no fix needed there, so no regression tests are added for those areas.
"""
import pytest
from fastapi import HTTPException

import core.authz as authz
import routers.billing as billing_router
import services.billing_service as billing_service
import routers.income_tax as income_tax_router
from routers.billing import BillingScheduleIn
from routers.income_tax import SaveAdvanceTaxRequest
from tests.e2e_harness import FakeDB

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "email": "p1@f1.test"}


@pytest.fixture
def enforced(monkeypatch):
    """Mirrors test_authz_engine.py's fixture: force the real (non-mock)
    client-ownership enforcement path. C1 belongs to F1 (every fixture
    user's firm); C-OTHER belongs to a different firm, F2."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "C-OTHER":
            return firm_id == "F2"
        return firm_id == "F1"
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


@pytest.fixture(autouse=True)
def _clear_billing_mock_stores():
    billing_service.MOCK_BILLING_SCHEDULES.clear()
    billing_service.MOCK_CLIENT_LINKS.clear()
    yield
    billing_service.MOCK_BILLING_SCHEDULES.clear()
    billing_service.MOCK_CLIENT_LINKS.clear()


# ── Billing: create_schedule client-ownership guard ──────────────────────────

def _sched_body(client_id: str) -> BillingScheduleIn:
    return BillingScheduleIn(client_id=client_id, arrangement="retainer",
                             cadence="monthly", amount_paise=100000, service_id="SVC-1")


def test_create_schedule_rejects_another_firms_client(enforced):
    with pytest.raises(HTTPException) as ei:
        billing_router.create_schedule(_sched_body("C-OTHER"), PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_schedule_accepts_own_firms_client(enforced):
    result = billing_router.create_schedule(_sched_body("C1"), PARTNER_F1)
    assert result["success"] is True
    assert result["data"]["client_id"] == "C1"


# ── Billing: ensure_customer_link defense-in-depth firm scoping ──────────────
# The router guard above is the primary fix; this exercises the service-layer
# twin directly, proving a client_id that reaches this far (e.g. a stale
# billing_schedules row created before this fix) still cannot leak another
# firm's PAN/GSTIN.

def test_ensure_customer_link_rejects_cross_firm_client(monkeypatch):
    monkeypatch.setattr(billing_service, "_USE_MOCK", False)
    db = FakeDB()
    monkeypatch.setattr(billing_service, "_db", lambda: db)
    db.seed("clients", {"id": "PC-OTHER", "firm_id": "FIRM-B", "client_name": "Other Firm's Client",
                        "gstin": "27AAAAA0000A1Z5", "pan": "AAAAA0000A"})
    with pytest.raises(HTTPException) as ei:
        billing_service.ensure_customer_link("FIRM-A", "PC-OTHER", "INTERNAL-A")
    assert ei.value.status_code == 404
    # No customer row was created — the PAN/GSTIN must never leak into Firm A's books.
    assert db.rows("customers") == []


def test_ensure_customer_link_accepts_own_firm_client(monkeypatch):
    monkeypatch.setattr(billing_service, "_USE_MOCK", False)
    db = FakeDB()
    monkeypatch.setattr(billing_service, "_db", lambda: db)
    db.seed("clients", {"id": "PC-1", "firm_id": "FIRM-A", "client_name": "Own Client",
                        "gstin": "27AAAAA0000A1Z5", "pan": "AAAAA0000A"})
    cust_id = billing_service.ensure_customer_link("FIRM-A", "PC-1", "INTERNAL-A")
    assert cust_id
    cust = db.rows("customers")[0]
    assert cust["pan"] == "AAAAA0000A" and cust["gstin"] == "27AAAAA0000A1Z5"
    assert cust["client_id"] == "INTERNAL-A"


# ── Advance tax: save_advance_tax client-ownership guard ─────────────────────

def _advance_tax_body(client_id: str) -> SaveAdvanceTaxRequest:
    return SaveAdvanceTaxRequest(client_id=client_id, fy="2024-25",
                                 estimated_tax_paise=1000000, installments=[])


def test_save_advance_tax_rejects_another_firms_client(enforced):
    with pytest.raises(HTTPException) as ei:
        income_tax_router.save_advance_tax(_advance_tax_body("C-OTHER"), PARTNER_F1)
    assert ei.value.status_code == 404


def test_save_advance_tax_accepts_own_firms_client(enforced):
    result = income_tax_router.save_advance_tax(_advance_tax_body("C1"), PARTNER_F1)
    assert result["success"] is True
