"""A lookup that finds NO row answers "not found", never "Internal server error" (ledger POST-A-198).

THE DEFECT
    Supabase's `.single()` RAISES when no row matches (PostgREST 406, code PGRST116, details "The result contains 0
    rows"). `core.exceptions._sqlstate` only recognises five-character SQLSTATEs, so the eight-character PGRST116
    fell through to main.py's catch-all and a wrong or foreign id came back as 500 "Internal server error (reference
    ...)". Thirty-four lookups across the relationships, lifecycle, health, year-end-notes, journal, banking, income-tax
    and GST modules were written as `... .single().execute().data` followed by `if not row: raise 404`, and the
    `if not row` line could never run. `.maybe_single()` answers an absent row with `data=None`
    (core/supabase_client.py restores that contract at the library seam), which is what those lines were written for.

WHAT IS HELD
    * every converted lookup, driven over the REAL postgrest request builders on a mocked HTTP transport that answers
      a single-object request with the genuine 406 / PGRST116 body, ends in the 404 or ValueError written beneath it;
    * the transport really was asked for a single object (so the test cannot pass over a path that never looked);
    * the safety net: `unhandled_failure` answers a zero-rows PGRST116 with 404 and leaves "more than one row" and every
      other PostgREST code a 500, and the app's catch-all speaks it.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from postgrest import SyncPostgrestClient
from postgrest.exceptions import APIError

from core.exceptions import is_absent_single_row, unhandled_failure

ZERO_ROWS = {"code": "PGRST116", "details": "The result contains 0 rows", "hint": None,
             "message": "JSON object requested, multiple (or no) rows returned"}
TWO_ROWS = dict(ZERO_ROWS, details="The result contains 2 rows")
PARTNER = {"id": "u1", "user_id": "u1", "auth_user_id": "a1", "firm_id": "firm-1", "role": "Partner",
           "email": "p@firm.test", "full_name": "P"}


class _AbsentRowDb:
    """A client built on the real postgrest builders. A request for ONE object (`.single()` / `.maybe_single()`) gets
    PostgREST's real answer for no matching row; a list request gets an empty list."""

    def __init__(self) -> None:
        self.object_requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "vnd.pgrst.object" in request.headers.get("accept", ""):
                self.object_requests.append(request.url.path)
                return httpx.Response(406, json=ZERO_ROWS)
            return httpx.Response(200, json=[])

        self._client = SyncPostgrestClient("http://postgrest.test")
        self._client.session = httpx.Client(base_url="http://postgrest.test", transport=httpx.MockTransport(handler))

    def table(self, name: str):
        return self._client.from_(name)


class _Bag:
    """A request body: only what the handler reads before the lookup under test, and None for the rest."""

    def __init__(self, **values) -> None:
        self.__dict__.update(values)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None

    def model_dump(self, *args, **kwargs):
        values = dict(self.__dict__)
        return {k: v for k, v in values.items() if v is not None} if kwargs.get("exclude_none") else values


@pytest.fixture()
def absent():
    return _AbsentRowDb()


def _expect_404(call, db: _AbsentRowDb) -> None:
    with pytest.raises(HTTPException) as got:
        call()
    assert got.value.status_code == 404, got.value.detail
    assert db.object_requests, "the handler never asked for a single row, so this proved nothing"


# ── the routers ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _router_cases():
    from routers import health, lifecycle, relationships

    return [
        ("relationships.update_entity", relationships, lambda: relationships.update_entity(
            "e-1", _Bag(), PARTNER)),
        ("relationships.get_entity", relationships, lambda: relationships.get_entity("e-1", PARTNER)),
        ("relationships.add_entity_role", relationships, lambda: relationships.add_entity_role(
            "e-1", _Bag(client_id=None, role_type="Director"), PARTNER)),
        ("relationships.remove_entity_role", relationships, lambda: relationships.remove_entity_role("r-1", PARTNER)),
        ("relationships.create_relationship", relationships, lambda: relationships.create_relationship(
            _Bag(from_entity_id="e-1", to_entity_id="e-2", relationship_type="Partner"), PARTNER)),
        ("relationships.review_cross_client_match", relationships, lambda: relationships.review_cross_client_match(
            "m-1", _Bag(reviewed=True, status="confirmed"), PARTNER)),
        ("relationships.create_entity_to_entity_relationship", relationships,
         lambda: relationships.create_entity_to_entity_relationship(
             _Bag(from_entity_id="e-1", to_entity_id="e-2", relationship_type="Partner"), PARTNER)),
        ("relationships.create_loan", relationships, lambda: relationships.create_loan(
            _Bag(client_id="c-1", entity_id="e-1"), PARTNER)),
        ("relationships.create_property", relationships, lambda: relationships.create_property(
            _Bag(client_id="c-1", entity_id="e-1", cost_paise=0, annual_rent_paise=0), PARTNER)),
        ("lifecycle.update_lead", lifecycle, lambda: lifecycle.update_lead(
            "l-1", _Bag(stage="won"), PARTNER)),
        ("lifecycle.update_proposal_status", lifecycle, lambda: lifecycle.update_proposal_status(
            "p-1", _Bag(status="accepted"), PARTNER)),
        ("lifecycle.update_onboarding_task", lifecycle, lambda: lifecycle.update_onboarding_task(
            "w-1", "t-1", _Bag(status="done"), PARTNER)),
        ("lifecycle.update_onboarding_status", lifecycle, lambda: lifecycle.update_onboarding_status(
            "w-1", _Bag(status="cancelled"), PARTNER)),
        ("lifecycle.get_onboarding_checklist", lifecycle, lambda: lifecycle.get_onboarding_checklist("w-1", PARTNER)),
        ("lifecycle.update_checklist_step", lifecycle, lambda: lifecycle.update_checklist_step(
            "w-1", 1, _Bag(status="done"), PARTNER)),
        ("lifecycle.complete_onboarding_checklist", lifecycle, lambda: lifecycle.complete_onboarding_checklist(
            "w-1", PARTNER)),
        ("lifecycle.update_renewal_status", lifecycle, lambda: lifecycle.update_renewal_status(
            "rn-1", _Bag(status="renewed"), PARTNER)),
        ("health.get_score", health, lambda: health.get_score("c-1", PARTNER)),
        ("health.calculate_score", health, lambda: health.calculate_score("c-1", PARTNER)),
    ]


@pytest.mark.parametrize("label", [c[0] for c in _router_cases()])
def test_a_router_lookup_that_finds_nothing_is_a_404(label, absent, monkeypatch):
    for name, module, call in _router_cases():
        if name == label:
            monkeypatch.setattr(module, "_db", lambda: absent)
            if module.__name__ == "routers.lifecycle":
                # These handlers first ask a scope helper whether the row is there and the caller may touch it, so
                # the lookup under test is reached only when the row goes between that check and this read (a
                # delete in another tab). Stand the helper aside to drive exactly that window.
                monkeypatch.setattr(module, "_assert_row_scope", lambda *a, **k: None)
                monkeypatch.setattr(module, "_assert_via_parent", lambda *a, **k: None)
            _expect_404(call, absent)
            return
    raise AssertionError(label)


def test_year_end_notes_that_are_not_there_are_a_404(absent, monkeypatch):
    import core.supabase_client as supabase_client
    from routers import year_end_notes

    monkeypatch.setattr(year_end_notes, "_USE_MOCK", False)
    monkeypatch.setattr(year_end_notes, "_assert_engagement_scope", lambda user, engagement_id: {"status": "open"})
    monkeypatch.setattr(supabase_client, "get_supabase", lambda: absent)
    _expect_404(lambda: year_end_notes.get_note("eng-1", "n-1", PARTNER), absent)
    _expect_404(lambda: year_end_notes.update_note("eng-1", "n-1", _Bag(title="x"), PARTNER), absent)
    _expect_404(lambda: year_end_notes.lock_note("eng-1", "n-1", PARTNER), absent)


# ── the services ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_bank_transaction_or_session_that_is_not_there_is_a_404(absent):
    from services.bank_matching_service import BankMatchingService
    from services.bank_posting_service import BankPostingService
    from services.bank_reconciliation_service import BankReconciliationService
    from services.banking_service import BankingService

    _expect_404(lambda: BankMatchingService()._get_txn(absent, "firm-1", "t-1"), absent)
    _expect_404(lambda: BankPostingService()._get_txn(absent, "firm-1", "t-1"), absent)
    _expect_404(lambda: BankReconciliationService()._get_session(absent, "firm-1", "r-1"), absent)
    _expect_404(lambda: BankingService()._get_txn(absent, "firm-1", "t-1"), absent)


def test_a_draft_journal_that_is_not_there_is_a_404(absent):
    from services.journal_posting_service import JournalPostingService

    _expect_404(lambda: JournalPostingService().post_draft(absent, "firm-1", "j-1", "u1", "a1"), absent)


# ── the domain modules, which word their own refusal as a ValueError ─────────────────────────────────────────────────

def _domain_cases():
    from domain.gst import portal_service
    from domain.income_tax import itr_workflow, xbrl_service

    return [
        ("validate_xbrl_package", xbrl_service, "XBRL package not found",
         lambda: xbrl_service.validate_xbrl_package("firm-1", "pkg-1", None)),
        ("generate_xbrl_xml", xbrl_service, "XBRL package not found",
         lambda: xbrl_service.generate_xbrl_xml("firm-1", "pkg-1", "Client", "U00000MH2020PTC000000")),
        ("transition_itr_status", itr_workflow, "Filing not found",
         lambda: itr_workflow.transition_itr_status("firm-1", "filing-1", "in_review", "a1", None)),
        ("run_sync_job", portal_service, "Sync job not found",
         lambda: portal_service.run_sync_job("firm-1", "job-1")),
    ]


@pytest.mark.parametrize("label", [c[0] for c in _domain_cases()])
def test_a_domain_lookup_that_finds_nothing_says_so_in_its_own_words(label, absent, monkeypatch):
    for name, module, sentence, call in _domain_cases():
        if name == label:
            monkeypatch.setattr(module, "_USE_MOCK", False)
            monkeypatch.setattr(module, "_supabase", lambda: absent)
            with pytest.raises(ValueError, match=sentence):
                call()
            assert absent.object_requests
            return
    raise AssertionError(label)


def test_a_tally_job_that_is_not_there_is_none(absent, monkeypatch):
    from domain.tally import migration_service

    monkeypatch.setattr(migration_service, "_USE_MOCK", False)
    monkeypatch.setattr(migration_service, "_supabase", lambda: absent)
    assert migration_service.get_migration_job("firm-1", "job-1") is None
    assert absent.object_requests


# ── the safety net for a `.single()` somebody writes later ──────────────────────────────────────────────────────────

def test_the_library_really_raises_on_single_and_the_net_reads_that_exact_error(absent):
    with pytest.raises(APIError) as got:
        absent.table("entities").select("id").eq("id", "e-1").single().execute()
    assert got.value.code == "PGRST116"
    assert is_absent_single_row(got.value)
    assert unhandled_failure(got.value) == (404, "That record was not found.")


def test_more_than_one_row_where_one_was_promised_stays_a_server_fault():
    assert not is_absent_single_row(APIError(TWO_ROWS))
    assert unhandled_failure(APIError(TWO_ROWS)) is None


def test_another_postgrest_code_is_not_mistaken_for_an_absent_row():
    other = {"code": "PGRST200", "details": "The result contains 0 rows", "hint": None, "message": "x"}
    assert not is_absent_single_row(APIError(other))
    assert unhandled_failure(APIError(other)) is None


def test_the_classifier_never_raises_on_an_exception_it_does_not_understand():
    class Hostile(Exception):
        @property
        def code(self):
            raise RuntimeError("boom")

    assert is_absent_single_row(Hostile()) is False
    assert is_absent_single_row(ValueError("PGRST116")) is False
    assert unhandled_failure(ValueError("x")) is None


def test_the_apps_catch_all_answers_a_404_with_the_envelope_and_no_reference():
    from starlette.requests import Request

    import json

    import main

    request = Request({"type": "http", "method": "GET", "path": "/api/x", "headers": [], "query_string": b""})
    response = main._failure_response(request, APIError(ZERO_ROWS))
    assert response.status_code == 404
    body = json.loads(response.body)
    assert body == {"success": False, "data": None, "error": "That record was not found."}
