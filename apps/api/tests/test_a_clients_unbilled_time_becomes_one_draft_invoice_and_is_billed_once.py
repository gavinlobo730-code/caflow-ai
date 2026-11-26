"""POST-B-194, hourly billing: a client's unbilled time becomes ONE draft invoice in the practice's own books, each entry
is billed once, and a cancelled or deleted invoice releases its time.

WHAT IS HELD
    * the entries a Partner chooses from are priced by the one rule (`time_rate.entry_worth`), and an entry that cannot be
      billed says why (already billed, not billable, still running, no time, no rate);
    * the draft is made by the sales engine's own create function, for the customer that stands for the client in the
      practice's books, under SAC 998211, at the rate of GST the request states; its lines ADD UP TO THE ENTRIES, whatever
      the grouping (a line is the sum of its entries' worths at a quantity of one, with the hours in its words);
    * a request that names an entry of another client, a billed one, an unrated one or a running one changes nothing and
      says which rule it met; so does one that would make more lines than a draft carries;
    * the entries are marked in a claim that takes only entries still unbilled: when somebody else billed one in the
      meantime the draft is removed, nothing stays marked and the request is refused;
    * a cancelled time invoice releases its entries, and time on an invoice cannot be deleted;
    * the earlier route that billed time on the fee tables is gone, with the marker function nothing called.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import main
import services.time_billing_service as tb
from domain.billing import time_rate
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER, PRACTICE = "F1", "C-SHARMA", "C-OTHER", "C-PRACTICE"
PARTNER = {"id": "u-p", "auth_user_id": "a-p", "email": "p@f.in", "role": "Partner", "firm_id": FIRM}


def _entry(eid, minutes=60, rate=150000, **over):
    return {"id": eid, "firm_id": FIRM, "client_id": CLIENT, "user_id": "u-1", "task_id": "t-1", "description": f"Work {eid}",
            "started_at": "2026-11-10T04:30:00+00:00", "ended_at": "2026-11-10T05:30:00+00:00", "duration_minutes": minutes,
            "is_billable": True, "billable_rate_paise": rate, "hourly_rate_paise": None, "billed_invoice_id": None, **over}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    rows = [
        _entry("e-1", 60, 150000),                                         # Rs 1,500.00
        _entry("e-2", 50, 150000, task_id="t-2", user_id="u-2"),           # 50 min at Rs 1,500 = Rs 1,250.00
        _entry("e-3", 7, 99999, task_id="t-2"),                            # floored: 7 * 99999 // 60 = 11666
        _entry("e-billed", billed_invoice_id="inv-old"),
        _entry("e-norate", rate=None),
        _entry("e-running", ended_at=None),
        _entry("e-notbillable", is_billable=False),
        _entry("e-other", client_id=OTHER),
    ]
    for r in rows:
        db.seed("time_entries", r)
    db.seed("tasks", {"id": "t-1", "firm_id": FIRM, "title": "GST returns"})
    db.seed("tasks", {"id": "t-2", "firm_id": FIRM, "title": "Books review"})
    # The practice's own catalogue is its internal client's. One service of the practice, and one that is another client's.
    db.seed("service_catalogue", {"id": "svc-fees", "firm_id": FIRM, "client_id": PRACTICE, "name": "Professional fees"})
    db.seed("service_catalogue", {"id": "svc-of-a-client", "firm_id": FIRM, "client_id": CLIENT, "name": "Somebody's product"})
    made = []

    def create_invoice(inv_in, current_user):
        row = {"id": f"inv-{len(made) + 1}", "firm_id": FIRM, "client_id": inv_in.client_id, "customer_id": inv_in.customer_id,
               "invoice_no": inv_in.invoice_no, "status": "draft"}
        db.seed("client_sales_invoices", row)
        made.append(inv_in)
        return {"success": True, "data": row, "error": None}

    import routers.sales_invoices as si
    monkeypatch.setattr(si, "create_invoice", create_invoice)
    monkeypatch.setattr(tb, "_db", lambda: db)
    monkeypatch.setattr(tb, "privileged_for", lambda d: d)
    monkeypatch.setattr(tb, "get_internal_client_id", lambda firm_id: PRACTICE)
    # `named_row_ownership.service_is_the_practices` asks the same question of the module that owns it.
    import services.internal_client_service as ics
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: PRACTICE)
    linked = []
    monkeypatch.setattr(tb.billing_service, "ensure_customer_link",
                        lambda firm, client, internal: linked.append(client) or f"cust-of-{client}")
    monkeypatch.setattr(tb.billing_service, "_staff_names", lambda firm, ids: {"u-1": "Asha Rao", "u-2": "Dev Mehta"})
    audit = []
    monkeypatch.setattr(tb, "log_event", lambda *a, **k: audit.append((a, k)))
    return {"db": db, "made": made, "audit": audit, "linked": linked}


def _billed(world):
    return {r["id"]: r["billed_invoice_id"] for r in world["db"].rows("time_entries")}


# ── what a Partner chooses from ──────────────────────────────────────────────

def test_the_list_is_the_clients_unbilled_time_priced_by_the_one_rule_and_says_why_an_entry_cannot_be_billed(world):
    out = tb.unbilled_entries(FIRM, CLIENT)
    by_id = {e["id"]: e for e in out["entries"]}
    assert set(by_id) == {"e-1", "e-2", "e-3", "e-norate", "e-running"}, "a billed, non-billable or another client's entry is listed"
    for eid in ("e-1", "e-2", "e-3"):
        row = next(r for r in world["db"].rows("time_entries") if r["id"] == eid)
        assert by_id[eid]["value_paise"] == time_rate.entry_worth(row)["value_paise"]
        assert by_id[eid]["blocked"] is None
    assert by_id["e-3"]["value_paise"] == 11666
    assert by_id["e-norate"]["blocked"] == "It has no rate. Set its rate first." and by_id["e-norate"]["value_paise"] is None
    assert "still running" in by_id["e-running"]["blocked"]
    assert (out["billable_count"], out["billable_minutes"], out["billable_value_paise"]) == (3, 117, 150000 + 125000 + 11666)
    assert by_id["e-2"]["user_name"] == "Dev Mehta" and by_id["e-2"]["task_title"] == "Books review"
    # The day is the Indian day the work started on.
    assert by_id["e-1"]["day"] == "2026-11-10"


# ── the draft ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("group_by,lines", [("single", 1), ("by_task", 2), ("by_person", 2), ("by_entry", 3)])
def test_the_drafts_lines_add_up_to_the_entries_whatever_the_grouping(world, group_by, lines):
    out = tb.create_draft(FIRM, CLIENT, ["e-1", "e-2", "e-3"], group_by, "svc-fees", 18.0, PARTNER)
    total = 150000 + 125000 + 11666
    assert out["value_paise"] == total and out["entries_billed"] == 3 and out["minutes"] == 117
    inv = world["made"][0]
    assert len(inv.lines) == lines
    assert sum(int(line.quantity * line.rate_paise) for line in inv.lines) == total, "the invoice does not add up to the time"
    assert all(line.quantity == 1 and line.hsn_sac == "998211" and line.is_service and line.gst_rate_percent == 18.0 for line in inv.lines)
    assert all(line.service_catalogue_id == "svc-fees" for line in inv.lines), "a line names no service of the practice"
    assert inv.client_id == PRACTICE and inv.customer_id == f"cust-of-{CLIENT}"
    assert inv.invoice_no.startswith("DRAFT-")
    assert {eid: _billed(world)[eid] for eid in ("e-1", "e-2", "e-3")} == dict.fromkeys(("e-1", "e-2", "e-3"), out["invoice_id"])
    assert _billed(world)["e-billed"] == "inv-old" and _billed(world)["e-other"] is None


def test_a_line_says_its_hours_and_the_rate_of_gst_is_the_one_the_request_states(world):
    tb.create_draft(FIRM, CLIENT, ["e-1", "e-2", "e-3"], "by_task", "svc-fees", 5.0, PARTNER)
    lines = {line.description: line for line in world["made"][0].lines}
    assert set(lines) == {"GST returns: 1 h", "Books review: 57 min"}
    assert all(line.gst_rate_percent == 5.0 for line in lines.values())


def test_a_draft_names_one_of_the_practices_services(world):
    for missing in ("", "   ", None):
        with pytest.raises(HTTPException) as exc:
            tb.create_draft(FIRM, CLIENT, ["e-1"], "single", missing, 18.0, PARTNER)
        assert exc.value.status_code == 422 and "practice's services" in exc.value.detail
    assert world["made"] == []


def test_an_entry_line_names_its_rate_in_words_a_pdf_can_print(world):
    # e-1 only: the others are billed by the test above in another fixture instance.
    tb.create_draft(FIRM, CLIENT, ["e-1"], "by_entry", "svc-fees", 18.0, PARTNER)
    words = world["made"][0].lines[0].description
    assert words == "2026-11-10 Work e-1: 1 h at Rs 1,500.00 an hour"
    assert "₹" not in words


def test_the_preview_is_the_drafts_lines_and_writes_nothing(world):
    out = tb.preview(FIRM, CLIENT, ["e-1", "e-2", "e-3"], "by_task")
    assert out == {"lines": [{"description": "GST returns: 1 h", "minutes": 60, "value_paise": 150000},
                             {"description": "Books review: 57 min", "minutes": 57, "value_paise": 136666}],
                   "entries": 3, "minutes": 117, "value_paise": 286666}
    assert world["made"] == [] and all(v is None or v == "inv-old" for v in _billed(world).values())


# ── what is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("ids,status,says", [
    (["e-1", "e-billed"], 409, "already on an invoice"),
    (["e-1", "e-norate"], 409, "no rate"),
    (["e-1", "e-running"], 409, "still running"),
    (["e-1", "e-notbillable"], 409, "not billable"),
    (["e-1", "e-other"], 404, "could not be found for this client"),
    (["e-1", "e-nobody"], 404, "could not be found for this client"),
    (["e-1", "e-1"], 422, "named twice"),
    ([], 422, "at least one"),
])
def test_a_request_that_names_one_entry_that_cannot_be_billed_changes_nothing_and_says_why(world, ids, status, says):
    before = _billed(world)
    for call in (lambda: tb.preview(FIRM, CLIENT, ids, "single"), lambda: tb.create_draft(FIRM, CLIENT, ids, "single", "svc-fees", 18.0, PARTNER)):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == status and says in exc.value.detail, exc.value.detail
    assert world["made"] == [] and _billed(world) == before


def test_more_lines_than_a_draft_carries_asks_for_a_coarser_grouping(world, monkeypatch):
    monkeypatch.setattr(tb, "MAX_LINES", 2)
    with pytest.raises(HTTPException) as exc:
        tb.create_draft(FIRM, CLIENT, ["e-1", "e-2", "e-3"], "by_entry", "svc-fees", 18.0, PARTNER)
    assert exc.value.status_code == 422 and "coarser grouping" in exc.value.detail
    assert world["made"] == []
    with pytest.raises(HTTPException) as exc:
        tb.preview(FIRM, CLIENT, ["e-1"], "by_colour")
    assert exc.value.status_code == 422


def test_the_practices_own_time_is_not_billed_and_a_practice_not_set_up_says_so(world, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        tb.create_draft(FIRM, PRACTICE, ["e-1"], "single", "svc-fees", 18.0, PARTNER)
    assert exc.value.status_code == 422
    monkeypatch.setattr(tb, "get_internal_client_id", lambda firm_id: None)
    with pytest.raises(HTTPException) as exc:
        tb.create_draft(FIRM, CLIENT, ["e-1"], "single", "svc-fees", 18.0, PARTNER)
    assert exc.value.status_code == 409 and "My practice" in exc.value.detail
    assert world["made"] == []


def test_a_service_that_is_not_the_practices_own_is_not_found_and_nothing_is_written(world):
    """The request names a service by its id. One of another client (or an invented id) is answered as a missing one is, before the
    customer link, the draft or any mark is written."""
    for service_id in ("svc-of-a-client", "svc-nobody-has"):
        with pytest.raises(HTTPException) as exc:
            tb.create_draft(FIRM, CLIENT, ["e-1"], "single", service_id, 18.0, PARTNER)
        assert exc.value.status_code == 404 and "not found" in str(exc.value.detail).lower(), exc.value.detail
    assert world["linked"] == [], "a customer link was written before the service was asked about"
    assert world["made"] == [] and _billed(world)["e-1"] is None


# ── billed once ──────────────────────────────────────────────────────────────

def test_a_second_request_for_the_same_time_is_refused(world):
    tb.create_draft(FIRM, CLIENT, ["e-1", "e-2"], "single", "svc-fees", 18.0, PARTNER)
    with pytest.raises(HTTPException) as exc:
        tb.create_draft(FIRM, CLIENT, ["e-2", "e-3"], "single", "svc-fees", 18.0, PARTNER)
    assert exc.value.status_code == 409
    assert len(world["made"]) == 1 and _billed(world)["e-3"] is None


def test_when_somebody_bills_one_of_them_in_the_meantime_the_draft_is_removed_and_nothing_stays_marked(world, monkeypatch):
    """The race: both requests passed the check, and the other one's claim landed first. This request's claim takes fewer
    than it asked for, so its draft goes and so does every mark it made."""
    real_chosen = tb._chosen

    def chosen_then_the_other_request_wins(db, firm_id, client_id, entry_ids):
        rows = real_chosen(db, firm_id, client_id, entry_ids)
        next(r for r in db.rows("time_entries") if r["id"] == "e-2")["billed_invoice_id"] = "inv-theirs"
        return rows
    monkeypatch.setattr(tb, "_chosen", chosen_then_the_other_request_wins)
    # The database's key releases an entry when its invoice is deleted (ON DELETE SET NULL, migration 078); the double has
    # no keys, so the release is played here on the delete this request makes.
    real_drop = tb._drop_draft

    def drop_and_release(db, firm_id, internal_id, invoice_id):
        real_drop(db, firm_id, internal_id, invoice_id)
        for r in db.rows("time_entries"):
            if r["billed_invoice_id"] == invoice_id:
                r["billed_invoice_id"] = None
    monkeypatch.setattr(tb, "_drop_draft", drop_and_release)

    with pytest.raises(HTTPException) as exc:
        tb.create_draft(FIRM, CLIENT, ["e-1", "e-2", "e-3"], "single", "svc-fees", 18.0, PARTNER)
    assert exc.value.status_code == 409 and "billed by somebody else" in exc.value.detail
    assert world["db"].rows("client_sales_invoices") == [], "the draft that bills nothing was left behind"
    assert _billed(world)["e-1"] is None and _billed(world)["e-3"] is None and _billed(world)["e-2"] == "inv-theirs"
    assert world["audit"] == []


def test_the_claim_takes_only_entries_still_unbilled_and_names_the_firm_and_the_client(world):
    world["db"].seed("client_sales_invoices", {"id": "inv-x", "firm_id": FIRM, "client_id": PRACTICE, "status": "draft"})
    taken = tb._claim(world["db"], FIRM, CLIENT, ["e-1", "e-billed", "e-other"], "inv-x")
    assert taken == 1
    assert _billed(world)["e-1"] == "inv-x" and _billed(world)["e-billed"] == "inv-old" and _billed(world)["e-other"] is None


# ── release ──────────────────────────────────────────────────────────────────

def test_a_cancelled_time_invoice_releases_its_entries_and_no_others(world):
    out = tb.create_draft(FIRM, CLIENT, ["e-1", "e-2"], "single", "svc-fees", 18.0, PARTNER)
    assert tb.release_for_invoice(world["db"], FIRM, out["invoice_id"]) == 2
    assert _billed(world)["e-1"] is None and _billed(world)["e-2"] is None and _billed(world)["e-billed"] == "inv-old"
    assert tb.release_for_invoice(world["db"], FIRM, "inv-that-billed-no-time") == 0


def test_the_cancel_route_releases_time_after_the_cancellation_and_a_billed_entry_cannot_be_deleted():
    import ast
    import inspect
    import routers.sales_invoices as si
    import routers.time_tracking as tt
    cancel = inspect.getsource(si.cancel_invoice)
    assert '_release_billed_time(db, firm_id or "", invoice_id, inv.get("client_id"))' in cancel
    assert cancel.index("update_header(") < cancel.index("_release_billed_time("), "time is released before the cancellation is committed"
    delete = inspect.getsource(tt.delete_entry)
    assert 'get("billed_invoice_id")' in delete and "409" in delete
    assert delete.index("billed_invoice_id") < delete.index("time_tracking_repo.delete("), "the entry is deleted before it is asked whether it is billed"
    assert ast.parse(cancel) and ast.parse(delete)


def test_a_release_that_fails_is_reported_and_never_raised_because_the_cancellation_already_stands(monkeypatch):
    """Driven, not read: the first version of this step named its reporter without importing it, so a failed release would have raised
    a NameError inside the handler and answered an error for a cancellation that had been committed."""
    import core.observability as obs
    import routers.sales_invoices as si
    reported = []
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **ctx: reported.append((type(exc).__name__, ctx)))
    monkeypatch.setattr(tb, "release_for_invoice", lambda db, firm_id, invoice_id: 3)
    assert si._release_billed_time(object(), FIRM, "inv-1", CLIENT) == 3 and reported == []

    def boom(db, firm_id, invoice_id):
        raise RuntimeError("the database did not answer")
    monkeypatch.setattr(tb, "release_for_invoice", boom)
    assert si._release_billed_time(object(), FIRM, "inv-1", CLIENT) is None
    assert reported == [("RuntimeError", {"operation": "sales_invoice.cancel.release_time", "firm_id": FIRM, "client_id": CLIENT})]


# ── the doors, and what went ─────────────────────────────────────────────────

def _pairs(path, method):
    route = next(r for r in main.app.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", set()) or set()))
    return {d.call.__name__ for d in route.dependant.dependencies if getattr(d.call, "__name__", "").startswith("rbac_")}


def test_the_three_doors_are_the_practices_billing_permission_and_only_the_last_writes():
    assert _pairs("/api/billing/unbilled-work/entries", "GET") == {"rbac_billing_read"}
    assert _pairs("/api/billing/time-invoices/preview", "POST") == {"rbac_billing_read"}
    assert _pairs("/api/billing/time-invoices", "POST") == {"rbac_billing_write"}


def test_the_request_states_the_rate_of_gst_and_the_route_holds_no_default():
    from pydantic import ValidationError
    from routers.billing import TimeInvoiceCreateIn
    with pytest.raises(ValidationError):
        TimeInvoiceCreateIn(client_id=CLIENT, entry_ids=["e-1"], service_id="svc-fees")
    with pytest.raises(ValidationError):
        TimeInvoiceCreateIn(client_id=CLIENT, entry_ids=["e-1"], gst_rate_percent=18)
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            TimeInvoiceCreateIn(client_id=CLIENT, entry_ids=["e-1"], service_id="svc-fees", gst_rate_percent=bad)
    assert TimeInvoiceCreateIn(client_id=CLIENT, entry_ids=["e-1"], service_id="svc-fees", gst_rate_percent=0).gst_rate_percent == 0.0


def test_the_earlier_route_that_billed_time_on_the_fee_tables_is_gone_with_the_marker_nothing_called():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert not any("from-time" in p for p in paths)
    import services.billing_service as bs
    import services.invoice_generation_service as igs
    assert not hasattr(igs, "generate_invoice_from_time_entries")
    assert not hasattr(bs, "mark_time_entries_billed")
