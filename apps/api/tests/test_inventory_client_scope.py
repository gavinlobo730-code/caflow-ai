"""
Client-assignment scope on the inventory router — stock register, per-item
ledger, manual adjustment and NRV write-down (migration 188).

None of the four endpoints imported core.authz at all before this fix.
list_stock_items/get_item_stock_ledger take client_id from the query string;
adjust_stock/writedown_stock_to_nrv take it from the request body
(StockAdjustmentIn.client_id / NrvWritedownIn.client_id, both required).
None of the four checked it against the caller's assignment — an unassigned
Executive (read) or Manager (write) could read another staff member's
client's stock register, or post a real inventory adjustment (with its own
GL journal, CGST Act §17(5)(h) ITC reversal) against it.
"""
import pytest
from fastapi import HTTPException

import routers.inventory as inv
from models.inventory import StockAdjustmentIn, NrvWritedownIn

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access on
    the router module, mirroring the other *_client_scope.py test files in
    this sweep. Forces mock mode so the "your own client still works"
    assertions don't depend on ambient SUPABASE_URL state left over from
    another test module."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(inv, "assert_client_access", _assert)
    monkeypatch.setattr(inv, "_USE_MOCK", True)
    return seen


def test_listing_another_clients_stock_register_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        inv.list_stock_items(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_stock_register_still_works(deny):
    out = inv.list_stock_items(client_id=MINE, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


def test_getting_another_clients_stock_ledger_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        inv.get_item_stock_ledger("PROD-1", client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_getting_your_own_clients_stock_ledger_still_works(deny):
    out = inv.get_item_stock_ledger("PROD-1", client_id=MINE, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


def test_adjusting_another_clients_stock_is_refused(deny):
    data = StockAdjustmentIn(
        client_id=THEIRS, adjustment_date="2026-04-15", quantity=2,
        direction="decrease", reason="physical_count_shortage",
    )
    with pytest.raises(HTTPException) as e:
        inv.adjust_stock("PROD-1", data, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_adjusting_your_own_clients_stock_still_works(deny):
    data = StockAdjustmentIn(
        client_id=MINE, adjustment_date="2026-04-15", quantity=2,
        direction="decrease", reason="physical_count_shortage",
    )
    out = inv.adjust_stock("PROD-1", data, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


def test_writing_down_another_clients_stock_is_refused(deny):
    data = NrvWritedownIn(client_id=THEIRS, writedown_date="2026-04-15", nrv_per_unit_paise=500)
    with pytest.raises(HTTPException) as e:
        inv.writedown_stock_to_nrv("PROD-1", data, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_writing_down_your_own_clients_stock_still_works(deny):
    data = NrvWritedownIn(client_id=MINE, writedown_date="2026-04-15", nrv_per_unit_paise=500)
    out = inv.writedown_stock_to_nrv("PROD-1", data, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]
