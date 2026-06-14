"""
Batch 5 (Amendment v1.1) — billable/cost-rate capture + unbilled-work visibility
(mock mode). Strictly data-capture: NO realization/margin/profitability/forecasting.
"""
import pytest

from core.permissions import can
import services.billing_service as billing
from routers.time_tracking import ManualEntryCreate, EntryUpdate


@pytest.fixture(autouse=True)
def _clear():
    billing.MOCK_COST_RATES.clear()
    yield
    billing.MOCK_COST_RATES.clear()


def test_unbilled_value_paise_arithmetic():
    # 60 min @ ₹1,000/hr (1,00,000 paise) -> ₹1,000
    assert billing.unbilled_value_paise(60, 100000, None) == 100000
    # 90 min @ same rate -> 1,50,000 paise
    assert billing.unbilled_value_paise(90, 100000, None) == 150000
    # billable_rate preferred over hourly_rate
    assert billing.unbilled_value_paise(60, 200000, 100000) == 200000
    # fallback to hourly_rate when billable_rate absent
    assert billing.unbilled_value_paise(60, None, 120000) == 120000
    # integer paise (floor), never float
    assert billing.unbilled_value_paise(50, 100000, None) == 83333


def test_group_unbilled_filters_and_groups():
    entries = [
        {"client_id": "C1", "task_id": "T1", "duration_minutes": 60,
         "is_billable": True, "billable_rate_paise": 100000, "billed_invoice_id": None},
        {"client_id": "C1", "task_id": "T2", "duration_minutes": 30,
         "is_billable": True, "billable_rate_paise": 100000, "billed_invoice_id": None},
        # billed -> excluded
        {"client_id": "C1", "task_id": "T1", "duration_minutes": 60,
         "is_billable": True, "billable_rate_paise": 100000, "billed_invoice_id": "INV1"},
        # non-billable -> excluded
        {"client_id": "C2", "task_id": "T3", "duration_minutes": 60,
         "is_billable": False, "billable_rate_paise": 100000, "billed_invoice_id": None},
        # zero minutes -> excluded
        {"client_id": "C2", "task_id": "T3", "duration_minutes": 0,
         "is_billable": True, "billable_rate_paise": 100000, "billed_invoice_id": None},
    ]
    g = billing.group_unbilled(entries)
    assert g["total_minutes"] == 90
    assert g["total_value_paise"] == 150000           # 100000 + 50000
    assert g["by_client"]["C1"] == {"minutes": 90, "value_paise": 150000, "count": 2}
    assert "C2" not in g["by_client"]                 # all C2 entries excluded
    assert g["by_work_item"]["T1"]["value_paise"] == 100000
    assert g["by_work_item"]["T2"]["value_paise"] == 50000


def test_cost_rate_capture_mock():
    billing.set_staff_cost_rate("F1", "u1", 80000)
    rates = {r["user_id"]: r["cost_rate_paise"] for r in billing.list_staff_cost_rates("F1")}
    assert rates["u1"] == 80000


def test_cost_rate_rejects_negative():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        billing.set_staff_cost_rate("F1", "u1", -1)


def test_cost_rate_not_used_in_unbilled_value():
    # Data-capture only: cost_rate must NOT influence unbilled (billable) value.
    assert billing.unbilled_value_paise(60, 100000, None) == 100000  # independent of any cost rate


def test_is_billed_not_manually_editable_via_models():
    # System-controlled fields must be absent from input models.
    assert "is_billed" not in ManualEntryCreate.model_fields
    assert "billed_invoice_id" not in ManualEntryCreate.model_fields
    assert "is_billed" not in EntryUpdate.model_fields
    assert "billed_invoice_id" not in EntryUpdate.model_fields
    # billable_rate_paise IS capturable
    assert "billable_rate_paise" in ManualEntryCreate.model_fields
    assert "billable_rate_paise" in EntryUpdate.model_fields


def test_partner_only_access():
    assert can("Partner", "billing", "read") is True
    assert can("Partner", "billing", "write") is True
    assert can("Manager", "billing", "read") is False
    assert can("Executive", "billing", "write") is False
