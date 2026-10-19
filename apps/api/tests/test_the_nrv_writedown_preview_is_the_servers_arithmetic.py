"""The write-down preview is the server's arithmetic, not the browser's (ledger POST-A-134).

WHAT WAS WRONG
    The inventory "Write Down to NRV" modal showed the amount it was about to write down, and worked it out itself:
    `Math.round((average cost - NRV) x quantity)`, in binary floating point, from the item's ROUNDED average cost. The
    server posts something else: it compares the CARRYING VALUE on the stock ledger's latest row (the exact total cost,
    which is not average x quantity because the average is rounded to a paisa) with `round_half_up(quantity x NRV)`,
    and writes the difference down. So the modal could say "NRV is at or above the current average cost, no write-down
    needed; nothing will be posted" where the server would post one, or name an amount away from the posted one by up
    to half a paisa a unit.

WHAT IS HELD
    * the preview route answers from `preview_nrv_writedown`, which runs `_compute_nrv_writedown` (the function the
      posting runs) on the same ledger row, so for every case below the previewed amount, the value after and the
      decision "needed or not" are exactly what the posting then records;
    * the case that made the old formula wrong is pinned: 1,000 units carried at Rs 10,004.00 (an average of Rs 10.004,
      held as Rs 10.00 a unit) against an NRV of Rs 10.00 a unit is a write-down of Rs 4.00 (400 paise), which the
      average-cost formula reads as zero;
    * a preview writes nothing: no ledger row, no journal, no audit entry;
    * no stock, an NRV at or above the carrying value, an unknown item and a service item each answer plainly.
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.inventory as inv
from models.inventory import NrvWritedownIn, NrvWritedownPreviewIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [inv])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(inv, "_USE_MOCK", False)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    seed_standard_coa(db, FIRM, "CLI")
    for name in ("Inventory", "Stock Write-off Expense", "Miscellaneous Income", "Inventory Write-down Expense"):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_name": name, "is_active": True})
    db.seed("service_catalogue", {"id": "PROD-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Steel Rod", "kind": "good", "gst_rate_bps": 1800})
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return db


def _seed_stock(db, qty: str, value_paise: int):
    """One ledger row carrying `qty` units at a total carrying value, the average rounded the way the ledger rounds it."""
    from decimal import Decimal, ROUND_HALF_UP
    avg = int((Decimal(value_paise) / Decimal(qty)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": "CLI", "service_catalogue_id": "PROD-1",
        "movement_date": "2026-04-01", "movement_type": "opening",
        "quantity_delta": qty, "unit_cost_paise": avg, "value_delta_paise": value_paise,
        "running_qty_units": qty, "running_avg_cost_paise": avg, "running_value_paise": value_paise,
    })
    return avg


def _preview(nrv_paise: int, item: str = "PROD-1") -> dict:
    out = inv.preview_writedown_stock_to_nrv(item, NrvWritedownPreviewIn(client_id="CLI", nrv_per_unit_paise=nrv_paise), CALLER)
    assert out["success"] is True, out
    return out["data"]


def test_the_case_that_made_the_browser_formula_wrong(monkeypatch):
    """1,000 units carried at 10,00,400 paise: the average rounds to 1,000 paise a unit, so (average - NRV) x quantity is
    zero for an NRV of 1,000 paise, and the server nevertheless writes down 400 paise (1,000 x 1,000 = 10,00,000 is
    below the carrying value)."""
    db = _setup(monkeypatch)
    avg = _seed_stock(db, "1000", 1_000_400)
    assert avg == 1000
    browser_formula = max(0, avg - 1000) * 1000          # what the modal used to show for NRV = 1,000 paise
    assert browser_formula == 0

    got = _preview(1000)
    assert got == {
        "has_stock": True, "needed": True, "quantity_units": "1000",
        "carrying_value_paise": 1_000_400, "new_value_paise": 1_000_000, "write_down_paise": 400,
    }


@pytest.mark.parametrize("qty, value, nrv", [
    ("10", 1_000_000, 70_000),     # the ordinary case: Rs 1,000 a unit down to Rs 700
    ("1000", 1_000_400, 1000),     # average rounds down: the average-cost formula reads nil
    ("2.335", 700, 100),           # 2.335 x 100 = 233.5 exactly: half up is 234, binary floating point gives 233.49999...
    ("3", 301, 100),               # 300 < 301: a write-down of a single paisa
    ("7.5", 10_000, 1334),         # 7.5 x 1,334 = 10,005 >= 10,000: nothing to write down
    ("0.001", 5, 1000),            # a thousandth of a unit: 1 paisa carried at 4 above its NRV
    ("12.345", 123_456, 10_000),   # three decimals of quantity: 123,450 < 123,456
    ("100", 5_000_000, 50_000),    # NRV exactly equal to the average: no write-down
    ("100", 5_000_000, 0),         # worthless stock: the whole carrying value
])
def test_the_preview_is_exactly_what_the_posting_then_records(monkeypatch, qty, value, nrv):
    db = _setup(monkeypatch)
    _seed_stock(db, qty, value)
    got = _preview(nrv)

    written = inv.writedown_stock_to_nrv("PROD-1", NrvWritedownIn(
        client_id="CLI", writedown_date="2026-04-20", nrv_per_unit_paise=nrv), CALLER)
    assert written["success"] is True
    rows = [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "nrv_writedown"]
    if got["needed"]:
        assert written["data"] is not None and len(rows) == 1
        assert -int(rows[0]["value_delta_paise"]) == got["write_down_paise"] > 0
        assert int(rows[0]["running_value_paise"]) == got["new_value_paise"]
        assert got["carrying_value_paise"] - got["new_value_paise"] == got["write_down_paise"]
    else:
        assert written["data"] is None and rows == [], "the preview said nothing would post, and something did"
        assert got["write_down_paise"] == 0 and got["new_value_paise"] == got["carrying_value_paise"] == value


def test_a_preview_writes_nothing(monkeypatch):
    db = _setup(monkeypatch)
    _seed_stock(db, "1000", 1_000_400)
    before = (len(db.rows("inventory_stock_ledger")), len(db.rows("journal_entries")), len(db.rows("journal_lines")),
              len(db.rows("audit_log")))
    for _ in range(3):
        _preview(1000)
    after = (len(db.rows("inventory_stock_ledger")), len(db.rows("journal_entries")), len(db.rows("journal_lines")),
             len(db.rows("audit_log")))
    assert after == before


def test_an_item_with_no_stock_answers_plainly_and_is_not_an_error(monkeypatch):
    _setup(monkeypatch)
    assert _preview(1000) == {
        "has_stock": False, "needed": False, "quantity_units": "0",
        "carrying_value_paise": 0, "new_value_paise": 0, "write_down_paise": 0,
    }


def test_an_nrv_at_or_above_the_carrying_value_is_not_a_write_down(monkeypatch):
    db = _setup(monkeypatch)
    _seed_stock(db, "10", 1_000_000)
    got = _preview(100_000)
    assert got["needed"] is False and got["write_down_paise"] == 0
    assert got["carrying_value_paise"] == got["new_value_paise"] == 1_000_000


def test_an_unknown_item_is_a_404_and_a_service_is_a_422(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        inv.preview_writedown_stock_to_nrv("NOPE", NrvWritedownPreviewIn(client_id="CLI", nrv_per_unit_paise=100), CALLER)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        inv.preview_writedown_stock_to_nrv("SVC-1", NrvWritedownPreviewIn(client_id="CLI", nrv_per_unit_paise=100), CALLER)
    assert e.value.status_code == 422


def test_an_item_of_another_client_is_not_found(monkeypatch):
    db = _setup(monkeypatch)
    _seed_stock(db, "10", 1_000_000)
    with pytest.raises(HTTPException) as e:
        inv.preview_writedown_stock_to_nrv("PROD-1", NrvWritedownPreviewIn(client_id="OTHER-CLIENT", nrv_per_unit_paise=100), CALLER)
    assert e.value.status_code in (403, 404)


def test_a_negative_nrv_is_refused_at_the_door():
    with pytest.raises(ValidationError):
        NrvWritedownPreviewIn(client_id="CLI", nrv_per_unit_paise=-1)


def test_the_preview_and_the_posting_share_one_arithmetic_function():
    """The rule, not a spelling: the preview does no arithmetic of its own. It reads the ledger row and hands it to the
    function the posting uses."""
    import inspect
    from domain import inventory_service as svc

    src = inspect.getsource(svc.preview_nrv_writedown)
    assert "_compute_nrv_writedown(" in src
    assert "_round_paise" not in src and "Decimal(" not in src.replace("Decimal(str(", ""), (
        "the preview is computing with its own rounding instead of asking _compute_nrv_writedown")
    assert "_compute_nrv_writedown(" in inspect.getsource(svc.record_nrv_writedown)
