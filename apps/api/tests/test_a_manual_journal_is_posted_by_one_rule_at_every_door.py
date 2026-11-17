"""A manual journal is put on the books by one rule at every door (POST-A-456, migration 681).

WHAT WAS WRONG
    `POST /api/accounting/journal` sent as posted asked `accounting` `write` (a Manager) and posted at once, while
    `POST /api/accounting/journals/{id}/post`, which posts a SAVED DRAFT, asked `accounting` `approve` (a Partner). A Manager who could not
    post a draft typed it again as new and posted it, so the Approvals queue was a step to go around, and a firm that wanted every manual
    journal approved had no way to say so.

WHAT THIS HOLDS
    * THE RULE (`services/journal_approval_rule`): with the firm's switch off, anyone who may write the books may post, at either door;
      with it on, only someone who may approve may post a new entry, post a draft, or correct or delete an entry already posted. A
      Manager the Team grid gives `approve` is an approver. An Executive (no `write`) may post at neither.
    * THE DOORS: the create door asks the rule only for an entry sent as posted (a draft is saved by any writer); the draft-post route
      admits `write` and asks the rule; the correction and the delete ask it only for a posted entry.
    * THE DRAFT-POST SCOPE: since the route admits a Manager, who is assignment-scoped, posting a draft of a client the caller cannot open
      is a 404, and so is a draft that does not exist, by the route's own guard.
    * THE SETTING: served to the screens by `GET /api/accounting/journal-approval` (what the caller may do), changed by a Partner through
      `PUT` (`settings` `write`); a database without migration 681 reads as off, any other failure to read it is a 503 for a non-approver.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import routers.accounting as acct
from core.permissions import can_user
from models.accounting import JournalEntryIn
from services import journal_approval_rule as rule
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "f-456"
MINE = "c-mine"
THEIRS = "c-theirs"
PARTNER = {"id": "u-p", "firm_id": FIRM, "auth_user_id": "a-p", "email": "p@f.test", "role": "Partner"}
MANAGER = {"id": "u-m", "firm_id": FIRM, "auth_user_id": "a-m", "email": "m@f.test", "role": "Manager"}
EXECUTIVE = {"id": "u-e", "firm_id": FIRM, "auth_user_id": "a-e", "email": "e@f.test", "role": "Executive"}
MANAGER_GRANTED_APPROVE = {**MANAGER, "id": "u-mg", "permission_overrides": {"accounting:approve": True}}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    rule.reset_mock_store()
    yield
    rule.reset_mock_store()


def _entry(status: str) -> JournalEntryIn:
    return JournalEntryIn(client_id=MINE, entry_date="2025-04-01", narration="Provision for audit fee", entry_type="Journal",
                          status=status, lines=[{"account_id": "a1", "debit_paise": 1000, "credit_paise": 0},
                                                {"account_id": "a2", "debit_paise": 0, "credit_paise": 1000}])


@pytest.fixture
def allow_clients(monkeypatch):
    monkeypatch.setattr(acct, "assert_client_access", lambda user, cid: None)
    monkeypatch.setattr(acct, "can_access_client", lambda user, cid: cid != THEIRS)


# ── the rule ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("user, off, on", [
    (PARTNER, True, True),
    (MANAGER, True, False),
    (MANAGER_GRANTED_APPROVE, True, True),
    (EXECUTIVE, False, False),
], ids=["partner", "manager", "manager-granted-approve", "executive"])
def test_who_may_post_with_the_switch_off_and_on(user, off, on):
    assert rule.may_post(user) is off
    rule.set_required(FIRM, True)
    assert rule.may_post(user) is on


def test_the_switch_is_off_until_a_partner_turns_it_on():
    assert rule.approval_required(FIRM) is False
    assert rule.describe(MANAGER) == {"approval_required": False, "may_post": True, "may_approve": False, "may_change_setting": False}


# ── the create door ───────────────────────────────────────────────────────────────────────────────────────────────
def test_a_manager_posts_a_new_entry_while_the_firm_does_not_require_approval(allow_clients):
    assert acct.create_journal_entry(_entry("posted"), current_user=MANAGER)["success"] is True


def test_a_manager_cannot_post_a_new_entry_where_the_firm_requires_approval_and_may_save_it_as_a_draft(allow_clients):
    rule.set_required(FIRM, True)
    with pytest.raises(HTTPException) as refused:
        acct.create_journal_entry(_entry("posted"), current_user=MANAGER)
    assert refused.value.status_code == 403 and refused.value.detail == rule.REFUSAL_TO_POST
    assert acct.create_journal_entry(_entry("draft"), current_user=MANAGER)["success"] is True


@pytest.mark.parametrize("user", [PARTNER, MANAGER_GRANTED_APPROVE], ids=["partner", "manager-granted-approve"])
def test_an_approver_posts_a_new_entry_where_the_firm_requires_approval(allow_clients, user):
    rule.set_required(FIRM, True)
    assert acct.create_journal_entry(_entry("posted"), current_user=user)["success"] is True


# ── the draft-post door ───────────────────────────────────────────────────────────────────────────────────────────
def _rbac_pair(fn) -> tuple[str, str]:
    dep = inspect.signature(fn).parameters["current_user"].default.dependency
    return tuple(dep.__name__.split("_", 2)[1:])  # rbac_<resource>_<action>


def test_the_draft_post_route_admits_what_the_create_route_admits():
    assert _rbac_pair(acct.post_draft_journal) == _rbac_pair(acct.create_journal_entry) == ("accounting", "write")
    assert not can_user(EXECUTIVE, "accounting", "write"), "an Executive is refused by the route itself"


def test_a_manager_posts_a_draft_while_the_firm_does_not_require_approval_and_not_where_it_does():
    assert acct.post_draft_journal("J1", current_user=MANAGER)["success"] is True
    rule.set_required(FIRM, True)
    with pytest.raises(HTTPException) as refused:
        acct.post_draft_journal("J1", current_user=MANAGER)
    assert refused.value.status_code == 403 and refused.value.detail == rule.REFUSAL_TO_POST
    assert acct.post_draft_journal("J1", current_user=PARTNER)["success"] is True


# ── live mode: the draft's scope, the correction and the delete ───────────────────────────────────────────────────
def _live(monkeypatch) -> FakeDB:
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, db, [acct])
    db.seed("firms", {"id": FIRM, "name": "F", "manual_journals_need_approval": False})
    return db


def _require_approval(db: FakeDB) -> None:
    db.rows("firms")[0]["manual_journals_need_approval"] = True


def test_live_the_firms_column_is_what_the_rule_reads(monkeypatch):
    db = _live(monkeypatch)
    assert rule.approval_required(FIRM) is False
    _require_approval(db)
    assert rule.approval_required(FIRM) is True


@pytest.mark.parametrize("journal_id", ["J-theirs", "J-missing"])
def test_live_a_manager_posting_a_draft_of_a_client_they_cannot_open_or_one_that_does_not_exist_gets_a_404(
        monkeypatch, allow_clients, journal_id):
    db = _live(monkeypatch)
    db.seed("journal_entries", {"id": "J-theirs", "firm_id": FIRM, "client_id": THEIRS, "is_posted": False, "entry_date": "2025-04-01",
                                "journal_lines": [{"account_id": "a1", "debit_paise": 100, "credit_paise": 0},
                                                  {"account_id": "a2", "debit_paise": 0, "credit_paise": 100}]})
    with pytest.raises(HTTPException) as refused:
        acct.post_draft_journal(journal_id, current_user=MANAGER)
    assert refused.value.status_code == 404 and refused.value.detail == "Journal entry not found."
    assert db.rows("journal_entries")[0]["is_posted"] is False


def test_live_a_manager_posts_a_draft_of_their_own_client_while_the_firm_does_not_require_approval(monkeypatch, allow_clients):
    db = _live(monkeypatch)
    db.seed("journal_entries", {"id": "J1", "firm_id": FIRM, "client_id": MINE, "is_posted": False, "entry_date": "2025-04-01",
                                "journal_lines": [{"account_id": "a1", "debit_paise": 100, "credit_paise": 0},
                                                  {"account_id": "a2", "debit_paise": 0, "credit_paise": 100}]})
    assert acct.post_draft_journal("J1", current_user=MANAGER)["success"] is True
    assert db.rows("journal_entries")[0]["is_posted"] is True


def _stub_manual_journal(monkeypatch, is_posted: bool) -> list:
    from services.manual_journal_service import manual_journal_service
    updated = []
    monkeypatch.setattr(manual_journal_service, "get", lambda db, firm_id, entry_id: {"id": entry_id, "is_posted": is_posted})
    monkeypatch.setattr(manual_journal_service, "update",
                        lambda db, firm_id, entry_id, data, actor_id=None: updated.append(entry_id) or {"id": entry_id})
    return updated


def _seed_entry(db: FakeDB, is_posted: bool) -> None:
    db.seed("journal_entries", {"id": "J1", "firm_id": FIRM, "client_id": MINE, "is_posted": is_posted, "entry_date": "2025-04-01",
                                "reference_no": "JV-1", "narration": "n", "source_type": "Manual"})


def test_live_a_manager_cannot_correct_a_posted_entry_where_the_firm_requires_approval(monkeypatch, allow_clients):
    db = _live(monkeypatch)
    _seed_entry(db, True)
    updated = _stub_manual_journal(monkeypatch, is_posted=True)
    body = acct.JournalEntryUpdateIn(narration="changed")
    assert acct.update_journal_entry("J1", body, current_user=MANAGER)["success"] is True, "off: a writer corrects a posted entry"
    _require_approval(db)
    with pytest.raises(HTTPException) as refused:
        acct.update_journal_entry("J1", body, current_user=MANAGER)
    assert refused.value.status_code == 403 and refused.value.detail == rule.REFUSAL_TO_CHANGE_POSTED
    assert updated == ["J1"], "the refused correction wrote nothing"
    assert acct.update_journal_entry("J1", body, current_user=PARTNER)["success"] is True


def test_live_a_manager_still_corrects_a_draft_where_the_firm_requires_approval(monkeypatch, allow_clients):
    db = _live(monkeypatch)
    _seed_entry(db, False)
    _require_approval(db)
    updated = _stub_manual_journal(monkeypatch, is_posted=False)
    assert acct.update_journal_entry("J1", acct.JournalEntryUpdateIn(narration="x"), current_user=MANAGER)["success"] is True
    assert updated == ["J1"]


def test_live_a_manager_cannot_delete_a_posted_entry_where_the_firm_requires_approval(monkeypatch, allow_clients):
    db = _live(monkeypatch)
    _seed_entry(db, True)
    _require_approval(db)
    called = []
    monkeypatch.setattr(db, "rpc", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("reached the delete")),
                        raising=False)
    with pytest.raises(HTTPException) as refused:
        acct.discard_journal_entry("J1", with_pair=False, current_user=MANAGER)
    assert refused.value.status_code == 403 and refused.value.detail == rule.REFUSAL_TO_CHANGE_POSTED
    assert called == [] and db.rows("journal_entries")[0].get("deleted_at") is None


# ── reading the setting ───────────────────────────────────────────────────────────────────────────────────────────
class _Failing:
    def __init__(self, exc):
        self.exc = exc

    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        raise self.exc


class _PgError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def test_a_database_without_migration_681_reads_as_off_and_any_other_failure_refuses_a_non_approver(monkeypatch):
    from core import db_provider
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    missing = _PgError("column firms.manual_journals_need_approval does not exist", "42703")
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: _Failing(missing))
    assert rule.approval_required(FIRM) is False
    assert rule.may_post(MANAGER) is True

    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: _Failing(_PgError("connection reset", "08006")))
    with pytest.raises(HTTPException) as unreadable:
        rule.assert_may_post(MANAGER)
    assert unreadable.value.status_code == 503 and unreadable.value.detail == rule.UNREADABLE
    assert rule.may_post(PARTNER) is True, "an approver is never asked the setting"


# ── the two endpoints ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_screens_are_told_what_the_caller_may_do():
    assert acct.get_journal_approval(current_user=MANAGER)["data"]["may_post"] is True
    resp = acct.set_journal_approval(acct.JournalApprovalIn(approval_required=True), current_user=PARTNER)
    assert resp["data"] == {"approval_required": True, "may_post": True, "may_approve": True, "may_change_setting": True}
    assert acct.get_journal_approval(current_user=MANAGER)["data"] == {
        "approval_required": True, "may_post": False, "may_approve": False, "may_change_setting": False}
    assert acct.get_journal_approval(current_user=EXECUTIVE)["data"]["may_post"] is False


def test_only_settings_write_changes_the_switch_and_any_member_who_reads_accounting_reads_it():
    assert _rbac_pair(acct.set_journal_approval) == ("settings", "write")
    assert _rbac_pair(acct.get_journal_approval) == ("accounting", "read")
    assert not can_user(MANAGER, "settings", "write") and can_user(PARTNER, "settings", "write")


# ── the rule is asked at every door, by name ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fn, call", [
    (acct.create_journal_entry, "journal_approval_rule.assert_may_post(current_user)"),
    (acct.post_draft_journal, "journal_approval_rule.assert_may_post(current_user)"),
    (acct.update_journal_entry, "journal_approval_rule.assert_may_change_posted(current_user)"),
    (acct.discard_journal_entry, "journal_approval_rule.assert_may_change_posted(current_user)"),
], ids=["create", "post-draft", "correct-posted", "delete-posted"])
def test_every_door_that_puts_or_changes_a_manual_journal_on_the_books_asks_the_rule(fn, call):
    assert call in inspect.getsource(fn)
