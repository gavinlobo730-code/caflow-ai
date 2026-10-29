"""A route that asserts the client the caller NAMED acts only on a row of that client, and a scope guard cannot be skipped by a missing row (24-10-2026).

Found by mapping every route that reaches the ledger (the plan to take the direct database door to `post_journal_atomic` away makes the
route's own check the only one) and then scanning every router for the shape. The payroll handlers have their own file
(`test_a_payroll_handler_acts_on_an_employee_of_the_client_it_named.py`). Here:

  * Bills of entry: PATCH, POST .../post and DELETE took `client_id` from the query, asserted the caller's access to THAT client,
    and then read the Bill of Entry by id and firm through the privileged client. A member assigned to client A alone could edit,
    delete, or POST (a journal in client B's books) a Bill of Entry of client B by naming A beside B's id.
  * `POST /journal/{id}/reverse` guarded with `if orig and not can_access_client(...)`, which passes when the read found nothing.
  * `PATCH /banking/accounts/{id}` read the account as `or [{}]` and asserted access to the client of an empty row (None, which
    passes), then answered success for an account that was not there.
  * `POST /api/scheduler/run` asked `team:write` only, where its sibling route refuses a caller who is not firm-wide.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from fastapi import HTTPException

import routers.accounting as acc
import routers.banking as bank
import routers.bills_of_entry as boe_router
import routers.scheduler_status as sched
import routers.tasks as tasks
from models.banking import BankAccountUpdateIn
from services import bill_of_entry_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BOE_B = "b0e00000-0000-0000-0000-00000000000b"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    # READY to post (an assessment and a payment account), so a post that got past the client tie would reach the kernel and be caught
    # by the journal assertion below, not by the readiness refusal
    db.seed("bills_of_entry", {"id": BOE_B, "firm_id": FIRM, "client_id": CLIENT_B, "be_number": "111", "be_date": "2026-06-10",
                               "port_code": "INNSA1", "igst_paise": 1_98_000_00, "assessable_value_paise": 10_00_000_00,
                               "payment_account_id": "ACC-BANK", "status": "draft", "deleted_at": None, "notes": "original"})
    wire_e2e(monkeypatch, db, [boe_router])
    monkeypatch.setattr(boe_router, "_mock_enabled", lambda: False)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


# ── bills of entry ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_bill_of_entry_of_another_client_cannot_be_edited_through_ones_own(world):
    before = [dict(r) for r in world.rows("bills_of_entry")]
    with pytest.raises(HTTPException) as e:
        boe_router.update_bill_of_entry(BOE_B, boe_router.BillOfEntryUpdateIn(notes="forged"), client_id=CLIENT_A, current_user=USER)
    assert (e.value.status_code, e.value.detail) == (404, "Bill of Entry not found.")
    assert [dict(r) for r in world.rows("bills_of_entry")] == before


def test_a_bill_of_entry_of_another_client_cannot_be_posted_through_ones_own(world, monkeypatch):
    from services.phase2_journal_service import phase2_journal_service as pjs

    def _boom(*a, **k):
        raise AssertionError("a journal was posted for a Bill of Entry of another client")

    monkeypatch.setattr(pjs, "_create_journal", _boom)
    monkeypatch.setattr(pjs, "_find_account", lambda *a, **k: "ACC")      # so a post past the tie WOULD reach the kernel
    with pytest.raises(HTTPException) as e:
        boe_router.post_bill_of_entry(BOE_B, client_id=CLIENT_A, current_user=USER)
    assert (e.value.status_code, e.value.detail) == (404, "Bill of Entry not found.")
    assert world.rows("journal_entries") == []
    assert [r["status"] for r in world.rows("bills_of_entry")] == ["draft"]


def test_a_bill_of_entry_of_another_client_cannot_be_deleted_through_ones_own(world):
    with pytest.raises(HTTPException) as e:
        boe_router.delete_bill_of_entry(BOE_B, client_id=CLIENT_A, current_user=USER)
    assert (e.value.status_code, e.value.detail) == (404, "Bill of Entry not found.")
    assert [r.get("deleted_at") for r in world.rows("bills_of_entry")] == [None]


def test_the_post_route_hands_the_service_the_client_the_caller_named_and_the_bill(world, monkeypatch):
    """A wiring test: the service refuses another client's Bill, but only if the route hands it the client."""
    seen = {}

    def _spy(db, firm_id, be_id, **kw):
        seen.update(firm_id=firm_id, be_id=be_id, **kw)
        return {"id": be_id, "status": "posted", "journal_entry_id": "J-1"}

    monkeypatch.setattr(svc, "post", _spy)
    out = boe_router.post_bill_of_entry(BOE_B, client_id=CLIENT_A, current_user=USER)
    assert out["success"] is True
    assert (seen["firm_id"], seen["be_id"], seen["client_id"]) == (FIRM, BOE_B, CLIENT_A)


def test_the_clients_own_bill_of_entry_is_still_edited_and_deleted(world):
    out = boe_router.update_bill_of_entry(BOE_B, boe_router.BillOfEntryUpdateIn(notes="corrected"), client_id=CLIENT_B, current_user=USER)
    assert out["success"] is True
    assert [r["notes"] for r in world.rows("bills_of_entry")] == ["corrected"]
    boe_router.delete_bill_of_entry(BOE_B, client_id=CLIENT_B, current_user=USER)
    assert world.rows("bills_of_entry")[0]["deleted_at"]


def test_the_service_reads_by_client_and_has_no_default_for_it():
    for fn in (svc.get, svc.post):
        p = inspect.signature(fn).parameters["client_id"]
        assert p.default is inspect.Parameter.empty and p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
    src = pathlib.Path(boe_router.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "svc" and node.func.attr in ("get", "post")):
            assert "client_id" in {k.arg for k in node.keywords}, f"svc.{node.func.attr} at line {node.lineno} names no client"
    # the two statements that write a Bill of Entry by id name the client as well
    assert src.count('.eq("client_id", client_id)') >= 2


# ── the journal reverse route ────────────────────────────────────────────────────────────────────────────────────────
def test_reversing_a_journal_that_is_not_there_is_a_404_before_the_kernel_is_asked(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    import core.supabase_client as sc
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(acc.period_validation_service, "validate_posting_date", lambda *a, **k: None)

    def _boom(self, *a, **k):
        raise AssertionError("the kernel was asked to reverse an entry the route could not read")

    monkeypatch.setattr(pjs.Phase2JournalService, "reverse_entry", _boom)
    with pytest.raises(HTTPException) as e:
        acc.reverse_journal_entry("c0000000-0000-0000-0000-00000000000c",
                                  acc.JournalReversalIn(reversal_date="2026-06-30"), current_user=USER)
    assert (e.value.status_code, e.value.detail) == (404, "Journal entry not found")


# ── the bank account PATCH ───────────────────────────────────────────────────────────────────────────────────────────
def test_patching_a_bank_account_that_is_not_there_is_a_404_and_not_a_success(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(bank, "_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        bank.update_bank_account("d0000000-0000-0000-0000-00000000000d", BankAccountUpdateIn(bank_name="X"), current_user=USER)
    assert (e.value.status_code, e.value.detail) == (404, "Bank account not found.")


def test_patching_a_bank_account_that_is_there_still_works(monkeypatch):
    db = FakeDB()
    db.seed("bank_accounts", {"id": "d0000000-0000-0000-0000-00000000000d", "firm_id": FIRM, "client_id": CLIENT_A,
                              "bank_name": "Old", "account_type": "current", "opening_balance_paise": 0})
    monkeypatch.setattr(bank, "_db", lambda: db)
    out = bank.update_bank_account("d0000000-0000-0000-0000-00000000000d", BankAccountUpdateIn(bank_name="New"), current_user=USER)
    assert out["success"] is True and db.rows("bank_accounts")[0]["bank_name"] == "New"


# ── the manual scheduler run ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_manual_scheduler_run_is_refused_to_a_caller_who_is_not_firm_wide(monkeypatch):
    import jobs.scheduler as js
    ran = []
    monkeypatch.setattr(js, "start_daily_jobs", lambda firm_id, force=False: ran.append((firm_id, force)) or {"started": True})
    with pytest.raises(HTTPException) as e:
        sched.trigger_run(force=False, current_user={**USER, "role": "Manager"})
    assert e.value.status_code == 403 and "every client in the firm" in e.value.detail
    assert ran == []
    out = sched.trigger_run(force=False, current_user=USER)
    assert out["success"] is True and len(ran) == 1


def test_the_two_manual_batch_routes_share_one_guard_and_one_wording():
    with pytest.raises(HTTPException) as a:
        tasks._assert_firmwide_job({**USER, "role": "Executive"}, "The daily automation batch")
    with pytest.raises(HTTPException) as b:
        sched.assert_firmwide_job({**USER, "role": "Executive"}, "The daily automation batch")
    assert (a.value.status_code, a.value.detail) == (b.value.status_code, b.value.detail)
