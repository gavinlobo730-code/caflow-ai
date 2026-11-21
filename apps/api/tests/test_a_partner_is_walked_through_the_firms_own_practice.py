"""The first-day card walks a Partner through the firm's OWN practice as well as its clients (POST-A-533).

WHAT WAS WRONG
    The card's four steps are all about clients, so a new CA could finish it without learning that the firm's own books
    exist: the owner, who built the product with Claude, could not find them on the live site on 20 November 2026. And since
    fees are billed from My practice on the same table a client's invoice is on (POST-B-193), the step "raise your first
    invoice" would have been ticked by the firm's own fee bill for a firm that had raised nothing for any client.

WHAT IS ASSERTED
    * the rule: the practice's four steps are a SECOND list with its own counts; the card stays while either list has
      something to do; a person who is not a Partner is sent no practice list at all, and their card is the four steps it was;
    * the facts, from the practice's own rows: its record with a PAN, the first entry in its books, its own bank statement,
      its first issued fee bill; a firm whose practice is not set up has done none of them, which is a fact and not an unknown;
    * a client's invoice or statement does not tick a practice step, and the firm's own does not tick a client's;
    * a read that fails leaves the steps that depend on it unknown, never ticked and never unticked;
    * the route sends the list to a Partner and not to a Manager, with the id of the practice's record for the links.

NOT ASSERTED: nothing here was run against a real database or the live site. The browser's half (which screen each step
opens) is `apps/web/lib/onboarding/firstRun.ts`, held from this side by the parity test at the foot of this file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.onboarding as onboarding
import services.first_run_service as svc
import services.internal_client_service as ics
from core.auth import get_current_user
from domain.onboarding import first_run as rule
from tests.e2e_harness import FakeDB

FIRM, OTHER = "firm-pf-1", "firm-pf-2"
PRACTICE, A_CLIENT = "c-practice", "c-client"
BORN = "2026-09-01T04:00:00+00:00"
PARTNER = {"id": "u-p1", "firm_id": FIRM, "role": "Partner", "email": "p1@f.in", "auth_user_id": "a-p1"}
MANAGER = {"id": "u-m1", "firm_id": FIRM, "role": "Manager", "email": "m@f.in", "auth_user_id": "a-m1"}
F = rule.Fact


# ── the rule ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _all(ids, done):
    return {i: F(done, BORN if done else None) for i in ids}


def test_the_practice_is_a_second_list_with_its_own_counts_and_only_when_it_is_asked_for():
    out = rule.build(_all(rule.STEP_IDS, False), practice_facts=_all(rule.PRACTICE_STEP_IDS, False), practice_client_id=PRACTICE)
    assert [s["id"] for s in out["steps"]] == list(rule.STEP_IDS), "the practice's steps were added to the clients' list"
    assert [s["id"] for s in out["practice"]["steps"]] == [
        "practice_identity", "practice_books", "practice_statement", "practice_fee_bill"]
    assert (out["practice"]["total"], out["practice"]["done_count"], out["practice"]["next_step"]) == (4, 0, "practice_identity")
    assert out["practice"]["client_id"] == PRACTICE
    assert (out["total"], out["done_count"]) == (4, 0)
    assert rule.build(_all(rule.STEP_IDS, False))["practice"] is None


def test_the_card_stays_while_either_list_has_something_to_do():
    clients_done = _all(rule.STEP_IDS, True)
    partner = rule.build(clients_done, practice_facts=_all(rule.PRACTICE_STEP_IDS, False), practice_client_id=PRACTICE)
    assert partner["complete"] is True and partner["visible"] is True, "a Partner's card went with the firm's own practice untouched"
    assert rule.build(clients_done)["visible"] is False, "somebody who is sent no practice list still sees a finished card"
    both = rule.build(clients_done, practice_facts=_all(rule.PRACTICE_STEP_IDS, True), practice_client_id=PRACTICE)
    assert both["visible"] is False and both["practice"]["complete"] is True
    # Dismissed is dismissed, whatever is left.
    assert rule.build(clients_done, practice_facts=_all(rule.PRACTICE_STEP_IDS, False), dismissed=True)["visible"] is False


def test_a_practice_list_nobody_could_read_asks_for_nothing():
    out = rule.build(_all(rule.STEP_IDS, True), practice_facts={}, practice_client_id=None)
    assert out["practice"]["unreadable"] == list(rule.PRACTICE_STEP_IDS)
    assert out["visible"] is False, "four question marks about the practice kept a finished card on the screen"
    assert all(s["done"] is None for s in out["practice"]["steps"])


def test_the_practices_words_carry_no_figure_and_name_what_ticks_them():
    for step in rule.PRACTICE_STEPS:
        assert not re.search(r"[0-9₹%]", step.title + step.why), f"{step.id} states a figure"
        assert len(step.why) > 40
    assert set(rule.PRACTICE_STEP_IDS).isdisjoint(rule.STEP_IDS)


# ── the facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    db.seed("firms", {"id": FIRM, "name": "Sharma & Co", "created_at": BORN})
    db.seed("users", {"id": "u-p1", "firm_id": FIRM, "email": "p1@f.in", "is_active": True, "status": "active",
                      "created_at": BORN, "deleted_at": None, "first_run_dismissed_at": None})
    db.seed("clients", {"id": PRACTICE, "firm_id": FIRM, "client_name": "Sharma & Co", "is_internal": True,
                        "pan": "AAAFS1234K", "deleted_at": None, "created_at": BORN})
    db.seed("clients", {"id": A_CLIENT, "firm_id": FIRM, "client_name": "Acme", "is_internal": False,
                        "pan": "AABCA1234K", "deleted_at": None, "created_at": "2026-09-01T05:00:00+00:00"})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_db", lambda: db)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: PRACTICE if firm_id == FIRM else None)
    return db


def _practice(firm=FIRM):
    return {s["id"]: s for s in svc.first_run(firm, "u-p1", for_partner=True)["practice"]["steps"]}


def _clients(firm=FIRM):
    return {s["id"]: s for s in svc.first_run(firm, "u-p1", for_partner=True)["steps"]}


def _invoice(db, client, *, status="issued", opening=False, at="2026-09-02T06:00:00+00:00"):
    return db.seed("client_sales_invoices", {
        "id": f"i-{len(db.rows('client_sales_invoices'))}", "firm_id": FIRM, "client_id": client,
        "status": status, "is_opening": opening, "deleted_at": None, "created_at": at})


def test_a_practice_that_is_set_up_has_its_details_to_check_and_nothing_else_done(world):
    steps = _practice()
    assert steps["practice_identity"]["done"] is True and steps["practice_identity"]["done_at"] == BORN
    assert [steps[i]["done"] for i in ("practice_books", "practice_statement", "practice_fee_bill")] == [False, False, False]


def test_a_practice_that_is_not_set_up_has_done_none_of_them_and_that_is_a_fact(world, monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: None)
    out = svc.first_run(FIRM, "u-p1", for_partner=True)
    assert [s["done"] for s in out["practice"]["steps"]] == [False, False, False, False]
    assert out["practice"]["client_id"] is None and out["practice"]["unreadable"] == []
    assert out["practice"]["next_step"] == "practice_identity"


def test_a_record_with_no_pan_is_not_one_whose_details_can_be_checked(world):
    world.rows("clients")[0]["pan"] = None
    assert _practice()["practice_identity"]["done"] is False


def test_the_first_entry_of_any_kind_starts_the_books_and_a_deleted_one_does_not(world):
    world.seed("journal_entries", {"id": "j-0", "firm_id": FIRM, "client_id": PRACTICE, "source_type": "Opening",
                                   "deleted_at": "2026-09-03T00:00:00+00:00", "created_at": "2026-09-02T05:00:00+00:00"})
    world.seed("journal_entries", {"id": "j-c", "firm_id": FIRM, "client_id": A_CLIENT, "source_type": "manual",
                                   "deleted_at": None, "created_at": "2026-09-02T05:30:00+00:00"})
    assert _practice()["practice_books"]["done"] is False, "a deleted entry, or a client's entry, started the firm's own books"
    world.seed("journal_entries", {"id": "j-1", "firm_id": FIRM, "client_id": PRACTICE, "source_type": "manual",
                                   "deleted_at": None, "created_at": "2026-09-04T05:00:00+00:00"})
    step = _practice()["practice_books"]
    assert step["done"] is True and step["done_at"] == "2026-09-04T05:00:00+00:00"


def test_the_firms_own_fee_bill_and_a_clients_invoice_each_tick_their_own_step_and_not_the_others(world):
    _invoice(world, PRACTICE)
    assert _practice()["practice_fee_bill"]["done"] is True
    assert _clients()["first_invoice"]["done"] is False, "the firm's own fee bill ticked 'raise your first invoice' for a client"
    world.rows("client_sales_invoices").clear()
    _invoice(world, A_CLIENT)
    assert _practice()["practice_fee_bill"]["done"] is False, "a client's invoice ticked the firm's own fee bill"
    assert _clients()["first_invoice"]["done"] is True


@pytest.mark.parametrize("kwargs", [{"status": "draft"}, {"opening": True}], ids=["a draft", "carried over"])
def test_what_is_not_a_fee_bill_raised_here_does_not_tick_the_step(world, kwargs):
    _invoice(world, PRACTICE, **kwargs)
    assert _practice()["practice_fee_bill"]["done"] is False


def test_the_firms_own_statement_and_a_clients_each_tick_their_own_step(world):
    world.seed("bank_statements", {"id": "bs-p", "firm_id": FIRM, "client_id": PRACTICE, "created_at": "2026-09-02T08:00:00+00:00"})
    assert _practice()["practice_statement"]["done"] is True
    assert _clients()["first_statement"]["done"] is False, "the firm's own statement ticked the client's step"
    world.seed("bank_statements", {"id": "bs-c", "firm_id": FIRM, "client_id": A_CLIENT, "created_at": "2026-09-02T09:00:00+00:00"})
    assert _clients()["first_statement"]["done"] is True


def test_not_knowing_which_record_is_the_practice_leaves_what_depends_on_it_unknown(world, monkeypatch):
    def broken(firm_id):
        raise RuntimeError("could not read the firm")
    monkeypatch.setattr(ics, "get_internal_client_id", broken)
    _invoice(world, PRACTICE)
    out = svc.first_run(FIRM, "u-p1", for_partner=True)
    assert out["practice"]["unreadable"] == list(rule.PRACTICE_STEP_IDS)
    clients = {s["id"]: s["done"] for s in out["steps"]}
    assert clients["first_invoice"] is None and clients["first_statement"] is None, (
        "an invoice that may be the firm's own fee bill was counted as a client's")
    assert clients["first_client"] is True and clients["invite_colleague"] is False


def test_somebody_who_is_not_a_partner_is_read_nothing_of_the_practice(world):
    reads = []
    real = world.table

    def spy(name):
        reads.append(name)
        return real(name)

    world.table = spy
    out = svc.first_run(FIRM, "u-m1")
    assert out["practice"] is None
    assert "journal_entries" not in reads, "the practice's books were read for somebody who is not sent them"


# ── the route ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _app(user):
    app = FastAPI()
    app.include_router(onboarding.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_sends_the_practice_list_to_a_partner_and_not_to_a_manager(world, monkeypatch):
    monkeypatch.setattr(onboarding, "get_service_supabase", lambda: world)
    partner = _app(PARTNER).get("/api/onboarding/status").json()["data"]["first_run"]
    manager = _app(MANAGER).get("/api/onboarding/status").json()["data"]["first_run"]
    assert partner["practice"]["client_id"] == PRACTICE and len(partner["practice"]["steps"]) == 4
    assert manager["practice"] is None
    assert "c-practice" not in str(manager), "the id of the practice's own record reached somebody who is not a Partner"


# ── the browser's half ────────────────────────────────────────────────────────────────────────────────────────────────────────

WEB = Path(__file__).resolve().parents[2] / "web"


def test_every_practice_step_has_a_screen_and_every_screen_a_step():
    src = (WEB / "lib/onboarding/firstRun.ts").read_text(encoding="utf-8")
    # The type of the map holds an arrow (`=>`), so the opening brace is found after the first `=` that a brace follows.
    body = re.search(r"export const PRACTICE_STEP_ROUTES\b.*?=\s*\{\n(.*?)\n\};", src, re.S)
    assert body, "PRACTICE_STEP_ROUTES moved: this parity test reads it"
    routed = set(re.findall(r"^\s*(practice_[a-z_]+):", body.group(1), re.M))
    assert routed == set(rule.PRACTICE_STEP_IDS), (
        f"steps with no screen: {sorted(set(rule.PRACTICE_STEP_IDS) - routed)}; screens with no step: {sorted(routed - set(rule.PRACTICE_STEP_IDS))}")
