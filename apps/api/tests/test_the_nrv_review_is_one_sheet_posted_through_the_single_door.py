"""The NRV review is one sheet for the whole register, posted through the single-item door's own function (POST-A-111, the rest of INV-10).

WHAT WAS MISSING
    The write-down to net realisable value took ONE item per call (`POST /api/inventory/items/{id}/writedown`), from a modal opened on a
    register row. A year-end valuation reviews the whole register, so the CA opened the modal item by item.

WHAT IS HELD
    * the sheet lists every stock-tracked product that holds stock now, and nothing else unless the CA typed an NRV for it;
    * the sheet suggests no NRV: an item the CA typed nothing for has no NRV, no write-down and no value after, and is "not entered";
    * each typed NRV's write-down is exactly the single-item preview's for the same item, and exactly what the posting then records;
    * a preview writes nothing;
    * the batch posts through `apply_nrv_writedown`, one movement and one journal per line that needs one, all under the batch's
      reference, leaves a line that needs nothing alone and names it, and names a line that could not be recorded;
    * posting the same sheet twice writes nothing the second time;
    * a line naming an item twice, an item that is not this client's good, an empty batch and more lines than one POSTING carries are
      each refused before anything is written; the preview is not capped (the screen works the whole sheet out at once and posts it in
      parts), and still refuses an item named twice;
    * a finalised client year refuses both NRV doors before a stock row is written, as the stock-effect retry is refused;
    * one audit entry per line, the single door's event;
    * a journal that did not post behind a written-down item is said, never reported as posted.
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.inventory as inv
from domain.inventory import nrv_review
from models.inventory import NrvReviewPostIn, NrvReviewSheetIn, NrvWritedownPreviewIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [inv])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(inv, "_USE_MOCK", False)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    db.seed("clients", {"id": "OTHER", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    seed_standard_coa(db, FIRM, "CLI")
    for name in ("Inventory", "Stock Write-off Expense", "Miscellaneous Income", "Inventory Write-down Expense"):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_name": name, "is_active": True})
    for pid, name in (("ROD", "Steel Rod"), ("BOLT", "Bolt"), ("NUT", "Nut"), ("EMPTY", "Washer")):
        db.seed("service_catalogue", {"id": pid, "firm_id": FIRM, "client_id": "CLI", "name": name, "kind": "good",
                                      "gst_rate_bps": 1800})
    db.seed("service_catalogue", {"id": "SVC", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    db.seed("service_catalogue", {"id": "THEIRS", "firm_id": FIRM, "client_id": "OTHER", "name": "Pipe", "kind": "good"})
    return db


def _seed_stock(db, item: str, qty: str, value_paise: int, client: str = "CLI"):
    from decimal import Decimal, ROUND_HALF_UP
    avg = int((Decimal(value_paise) / Decimal(qty)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": client, "service_catalogue_id": item,
        "movement_date": "2026-04-01", "movement_type": "opening", "created_at": "2026-04-01T00:00:00+00:00",
        "quantity_delta": qty, "unit_cost_paise": avg, "value_delta_paise": value_paise,
        "running_qty_units": qty, "running_avg_cost_paise": avg, "running_value_paise": value_paise,
    })


def _seed_register(db):
    _seed_stock(db, "ROD", "1000", 1_000_400)   # the case the browser's formula read as nil: 400 paise to write down at Rs 10
    _seed_stock(db, "BOLT", "10", 1_000_000)    # Rs 1,000 a unit
    _seed_stock(db, "NUT", "2.335", 700)        # 2.335 x 100 = 233.5, half up to 234
    _seed_stock(db, "THEIRS", "5", 5_000, client="OTHER")


def _sheet(lines=()) -> dict:
    out = inv.preview_nrv_review(NrvReviewSheetIn(client_id="CLI", lines=[
        {"service_catalogue_id": i, "nrv_per_unit_paise": n} for i, n in lines]), CALLER)
    assert out["success"] is True, out
    return out["data"]


def _post(lines, date="2026-04-20", reference=None) -> dict:
    out = inv.post_nrv_review(NrvReviewPostIn(client_id="CLI", writedown_date=date, reference_no=reference, lines=[
        {"service_catalogue_id": i, "nrv_per_unit_paise": n} for i, n in lines]), CALLER)
    assert out["success"] is True, out
    return out["data"]


def _nrv_rows(db):
    return [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "nrv_writedown"]


def test_the_sheet_lists_the_goods_that_hold_stock_and_suggests_no_nrv(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    got = _sheet()
    ids = [r["service_catalogue_id"] for r in got["items"]]
    assert ids == ["BOLT", "NUT", "ROD"], "name order, goods with stock only: no service, no empty item, no other client's"
    for r in got["items"]:
        assert r["status"] == nrv_review.NOT_ENTERED
        assert r["nrv_per_unit_paise"] is None and r["write_down_paise"] is None and r["new_value_paise"] is None, (
            "an item the CA typed nothing for was given a figure of the sheet's own")
    assert got["entered_count"] == 0 and got["write_down_count"] == 0 and got["write_down_paise"] == 0
    assert got["carrying_value_paise"] == 1_000_400 + 1_000_000 + 700
    assert got["measured_now"] == nrv_review.MEASURED_NOW and got["no_nrv_of_our_own"] == nrv_review.NO_NRV_OF_OUR_OWN


@pytest.mark.parametrize("item, nrv", [("ROD", 1000), ("BOLT", 70_000), ("BOLT", 100_000), ("NUT", 100), ("ROD", 0)])
def test_each_typed_line_is_the_single_preview_and_then_what_posts(monkeypatch, item, nrv):
    db = _setup(monkeypatch)
    _seed_register(db)
    single = inv.preview_writedown_stock_to_nrv(item, NrvWritedownPreviewIn(client_id="CLI", nrv_per_unit_paise=nrv), CALLER)["data"]
    row = next(r for r in _sheet([(item, nrv)])["items"] if r["service_catalogue_id"] == item)
    assert row["write_down_paise"] == single["write_down_paise"]
    assert row["new_value_paise"] == single["new_value_paise"]
    assert row["carrying_value_paise"] == single["carrying_value_paise"]
    assert row["status"] == (nrv_review.WRITE_DOWN if single["needed"] else nrv_review.NOT_BELOW)

    posted = _post([(item, nrv)])
    rows = _nrv_rows(db)
    if single["needed"]:
        assert posted["posted_count"] == 1 and len(rows) == 1
        assert -int(rows[0]["value_delta_paise"]) == row["write_down_paise"] == posted["posted"][0]["write_down_paise"]
        assert int(rows[0]["running_value_paise"]) == row["new_value_paise"]
    else:
        assert posted["posted_count"] == 0 and posted["not_needed_count"] == 1 and rows == []


def test_a_preview_writes_nothing(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    before = (len(db.rows("inventory_stock_ledger")), len(db.rows("journal_entries")), len(db.rows("journal_lines")))
    for _ in range(3):
        _sheet([("ROD", 1000), ("BOLT", 50_000)])
    after = (len(db.rows("inventory_stock_ledger")), len(db.rows("journal_entries")), len(db.rows("journal_lines")))
    assert after == before


def test_a_batch_posts_each_line_under_one_reference_and_names_what_it_left(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    audit = []
    monkeypatch.setattr(inv, "log_event", lambda *a, **k: audit.append((a, k)))
    got = _post([("ROD", 1000), ("BOLT", 70_000), ("NUT", 1000), ("EMPTY", 10)], reference="VAL-2026-03")

    assert [p["service_catalogue_id"] for p in got["posted"]] == ["ROD", "BOLT"]
    assert [p["write_down_paise"] for p in got["posted"]] == [400, 300_000]
    assert got["write_down_paise"] == 300_400
    assert {n["service_catalogue_id"] for n in got["not_needed"]} == {"NUT", "EMPTY"}
    assert got["failed"] == []
    rows = _nrv_rows(db)
    assert len(rows) == 2 and {r["reference_no"] for r in rows} == {"VAL-2026-03"}
    assert all(r["journal_entry_id"] for r in rows), "each write-down has its journal behind it"
    assert all(p["journal_posted"] is True for p in got["posted"])
    entries = [e for e in db.rows("journal_entries") if e.get("source_type") == "nrv_writedown"]
    assert len(entries) == 2
    assert "₹3,004.00" in got["message"] and "VAL-2026-03" in got["message"]
    # One audit entry per line, the single door's own event, the judgement kept for the lines that wrote nothing down too.
    assert len(audit) == 4
    assert {a[1] for a, _ in audit} == {"inventory_nrv_writedown"}
    applied = {a[2]: k["new_data"]["applied"] for a, k in audit}
    assert applied == {"ROD": True, "BOLT": True, "NUT": False, "EMPTY": False}


def test_the_same_sheet_posted_twice_writes_nothing_the_second_time(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    first = _post([("ROD", 1000), ("BOLT", 70_000)])
    second = _post([("ROD", 1000), ("BOLT", 70_000)])
    assert first["posted_count"] == 2
    assert second["posted_count"] == 0 and second["not_needed_count"] == 2
    assert len(_nrv_rows(db)) == 2


def test_the_default_reference_is_the_single_doors(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    _post([("BOLT", 70_000)], date="2026-04-21")
    assert {r["reference_no"] for r in _nrv_rows(db)} == {"NRV-2026-04-21"}


def test_a_line_that_could_not_be_recorded_is_named_not_left_out(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    import domain.inventory_service as svc
    real = svc.apply_nrv_writedown
    monkeypatch.setattr(svc, "apply_nrv_writedown", lambda db_, **k: None if k["service_catalogue_id"] == "BOLT" else real(db_, **k))
    got = _post([("ROD", 1000), ("BOLT", 70_000)])
    assert [p["service_catalogue_id"] for p in got["posted"]] == ["ROD"]
    assert [f["service_catalogue_id"] for f in got["failed"]] == ["BOLT"]
    assert "could not be recorded" in got["message"]


def test_a_write_down_with_no_journal_behind_it_is_said(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    import domain.inventory_service as svc
    monkeypatch.setattr(svc, "post_nrv_writedown_journal_entry", lambda *a, **k: None)
    got = _post([("BOLT", 70_000)])
    assert got["posted"][0]["journal_posted"] is False
    assert "no journal behind it" in got["message"]


@pytest.mark.parametrize("lines, words", [
    ([("ROD", 1000), ("ROD", 900)], "more than once"),
    ([("SVC", 100)], "not one of this client's stock-tracked products"),
    ([("THEIRS", 100)], "not one of this client's stock-tracked products"),
    ([("NOPE", 100), ("THEIRS", 1)], "2 lines name items"),
])
def test_a_bad_line_is_refused_before_anything_is_read_or_written(monkeypatch, lines, words):
    db = _setup(monkeypatch)
    _seed_register(db)
    for call in (_sheet, _post):
        with pytest.raises(HTTPException) as e:
            call(lines)
        assert e.value.status_code == 422 and words in e.value.detail
    assert _nrv_rows(db) == []


def test_an_empty_batch_and_too_many_lines_are_refused(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    with pytest.raises(HTTPException) as e:
        _post([])
    assert e.value.status_code == 422 and "at least one item" in e.value.detail
    assert nrv_review.lines_problem([str(i) for i in range(nrv_review.MAX_LINES + 1)]).startswith("A review can post at most")
    assert nrv_review.lines_problem([str(i) for i in range(nrv_review.MAX_LINES)]) is None


def test_an_item_typed_with_no_stock_stays_on_the_sheet_and_says_so(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    row = next(r for r in _sheet([("EMPTY", 500)])["items"] if r["service_catalogue_id"] == "EMPTY")
    assert row["status"] == nrv_review.NO_STOCK and row["write_down_paise"] == 0


def test_another_clients_sheet_is_refused(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(inv, "assert_client_access", lambda user, cid: (_ for _ in ()).throw(HTTPException(status_code=404)))
    with pytest.raises(HTTPException):
        _sheet()
    with pytest.raises(HTTPException):
        _post([("ROD", 1)])


def test_a_negative_nrv_is_refused_at_the_door():
    with pytest.raises(ValidationError):
        NrvReviewSheetIn(client_id="CLI", lines=[{"service_catalogue_id": "ROD", "nrv_per_unit_paise": -1}])


def test_the_sheet_and_the_single_preview_share_the_postings_arithmetic():
    """The rule, not a spelling: the sheet and the single preview hand the ledger row to one function, and that function hands it to
    the one the posting runs."""
    import inspect
    from domain import inventory_service as svc

    assert "nrv_writedown_answer(" in inspect.getsource(nrv_review.sheet_row)
    assert "nrv_writedown_answer(" in inspect.getsource(svc.preview_nrv_writedown)
    answer = inspect.getsource(svc.nrv_writedown_answer)
    assert "_compute_nrv_writedown(" in answer and "_round_paise" not in answer
    import services.nrv_review_service as service
    assert "apply_nrv_writedown(" in inspect.getsource(service.post_review), "the batch posts through the single door's function"


# ── the review of POST-A-111: the preview is not capped, and a finalised client year refuses both doors ──────────────────────────────

def _seed_many(db, n: int) -> list[str]:
    ids = [f"G{i:03d}" for i in range(n)]
    for gid in ids:
        db.seed("service_catalogue", {"id": gid, "firm_id": FIRM, "client_id": "CLI", "name": f"Part {gid}", "kind": "good",
                                      "gst_rate_bps": 1800})
        _seed_stock(db, gid, "10", 10_000)
    return ids


def test_a_sheet_of_more_typed_lines_than_one_posting_carries_is_still_worked_out(monkeypatch):
    """"Work out the write-downs" sends every typed line at once. While the preview shared the posting's cap, a register with more than
    MAX_LINES typed lines was refused there and so could never be posted (the screen posts in parts, but only a sheet it has worked out)."""
    db = _setup(monkeypatch)
    ids = _seed_many(db, nrv_review.MAX_LINES + 5)
    got = _sheet([(gid, 500) for gid in ids])
    assert got["entered_count"] == nrv_review.MAX_LINES + 5
    assert got["write_down_count"] == nrv_review.MAX_LINES + 5 and got["write_down_paise"] == (nrv_review.MAX_LINES + 5) * 5_000
    assert nrv_review.lines_problem(ids, capped=False) is None


def test_the_preview_still_refuses_an_item_named_twice_and_the_posting_keeps_its_cap(monkeypatch):
    db = _setup(monkeypatch)
    ids = _seed_many(db, nrv_review.MAX_LINES + 1)
    with pytest.raises(HTTPException) as e:
        _sheet([(ids[0], 500), (ids[0], 400)] + [(gid, 500) for gid in ids[1:]])
    assert e.value.status_code == 422 and "more than once" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _post([(gid, 500) for gid in ids])
    assert e.value.status_code == 422 and e.value.detail.startswith("A review can post at most")
    assert _nrv_rows(db) == []


def test_the_screen_posts_in_parts_the_server_takes_and_works_the_whole_sheet_out_at_once():
    """Held from the side that owns the cap: the panel's part size is within `MAX_LINES`, every posting request is one part of the
    lines, and the preview is asked for the lines as they are."""
    import pathlib
    import re
    panel = (pathlib.Path(__file__).resolve().parents[3] / "apps" / "web" / "components" / "inventory" / "NrvReviewPanel.tsx").read_text()
    part = re.search(r"export const NRV_REVIEW_PART = (\d+);", panel)
    assert part and 0 < int(part.group(1)) <= nrv_review.MAX_LINES
    assert "lines: lines.slice(at, at + NRV_REVIEW_PART)" in panel
    assert "api.inventory.nrvReview({ client_id: clientId, lines: asked })" in panel and "onClick={() => ask(lines)}" in panel


def _close_the_clients_year(db, fy="2026-27"):
    db.seed("client_year_locks", {"id": "LOCK", "firm_id": FIRM, "client_id": "CLI", "financial_year": fy,
                                   "reason": "Year-end engagement finalised"})


def test_a_finalised_client_year_refuses_the_batch_before_any_line_is_written(monkeypatch):
    db = _setup(monkeypatch)
    _seed_register(db)
    _close_the_clients_year(db)
    with pytest.raises(HTTPException) as e:
        _post([("ROD", 1000), ("BOLT", 70_000)])
    assert e.value.status_code == 422 and "closed for this client" in e.value.detail
    assert _nrv_rows(db) == [] and [r for r in db.rows("journal_entries") if r.get("source_type") == "nrv_writedown"] == []


def test_a_finalised_client_year_refuses_the_single_write_down_before_the_stock_row_is_written(monkeypatch):
    from models.inventory import NrvWritedownIn
    db = _setup(monkeypatch)
    _seed_register(db)
    _close_the_clients_year(db)
    with pytest.raises(HTTPException) as e:
        inv.writedown_stock_to_nrv("BOLT", NrvWritedownIn(client_id="CLI", writedown_date="2026-04-20", nrv_per_unit_paise=70_000), CALLER)
    assert e.value.status_code == 422 and "closed for this client" in e.value.detail
    assert _nrv_rows(db) == []


def test_another_years_closure_does_not_refuse_either_door(monkeypatch):
    from models.inventory import NrvWritedownIn
    db = _setup(monkeypatch)
    _seed_register(db)
    _close_the_clients_year(db, fy="2025-26")
    assert _post([("ROD", 1000)])["posted_count"] == 1
    out = inv.writedown_stock_to_nrv("BOLT", NrvWritedownIn(client_id="CLI", writedown_date="2026-04-20", nrv_per_unit_paise=70_000), CALLER)
    assert out["success"] is True and out["data"]
    assert len(_nrv_rows(db)) == 2


def test_both_doors_ask_the_clients_closures_before_they_write():
    """The rule, not a spelling of one door: each NRV door calls `assert_not_closed` with the client and the write-down's date, after
    the firm's own year and before `apply_nrv_writedown` or the batch."""
    import inspect
    for fn, writer in ((inv.writedown_stock_to_nrv, "apply_nrv_writedown("), (inv.post_nrv_review, "nrv_review_service.post_review(")):
        src = inspect.getsource(fn)
        ask = src.find("period_lock_service.assert_not_closed(")
        assert ask != -1, f"{fn.__name__} does not ask the client's closures"
        assert "data.client_id, data.writedown_date)" in src[ask:ask + 200]
        assert src.find("validate_posting_date(") < ask < src.find(writer), f"{fn.__name__} asks in the wrong place"
