"""
Client-assignment scope (M2) on time_tracking.py.

stop_timer/update_entry/delete_entry resolved a time entry by firm_id alone
and never checked its client against the caller's assignment (unlike
list_entries just above them, which already applies filter_by_client — M2/M5)
— an Executive/Reviewer/Manager could stop, edit or delete another staff
member's time entry against an assigned client outside their own book.
create_manual_entry/start_timer took an optional client_id and never checked
it either. Fixed with _assert_entry_scope (can_access_client, ONE fixed
message for missing-vs-hidden — mirrors year_end.py's
_assert_engagement_scope) for the row-addressed trio, and assert_client_access
on the two creators — a no-op for client_id=None (client-less/internal work),
since can_access_client(user, None) is always True.

Also found beyond the audit doc's original 2-route count for this path:
export_entries (GET /export) had NO assignment filtering at all — an
Executive/Reviewer/Manager could export another staff member's unassigned
client's billing data, or the whole firm's, via the client_id filter (or by
omitting it). Fixed by threading effective_client_ids through to
time_export_service.export_time_entries, which now drops any entry whose
client_id falls outside it (client-less entries are always kept) — mirrors
list_entries's own filter_by_client, applied at the export layer instead.
"""
import pytest
from fastapi import HTTPException

import routers.time_tracking as tt
import repositories.time_tracking_repository as tt_repo_module
import services.time_export_service as export_service_module
from services.time_export_service import export_time_entries
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}


def _wire_db(monkeypatch, db):
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest (including client_id=None)."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(tt, "assert_client_access", _assert)
    monkeypatch.setattr(tt, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════
# create_manual_entry / start_timer (client_id known up front, optional)
# ══════════════════════════════════════════════════════════════════════════

def test_creating_a_manual_entry_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        tt.create_manual_entry(
            tt.ManualEntryCreate(client_id=THEIRS, started_at="2026-01-01T00:00:00Z"),
            current_user=EXEC_USER,
        )
    assert exc.value.status_code == 404


def test_creating_a_manual_entry_for_an_own_client_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    resp = tt.create_manual_entry(
        tt.ManualEntryCreate(client_id=MINE, started_at="2026-01-01T00:00:00Z"),
        current_user=EXEC_USER,
    )
    assert resp["success"] is True
    assert deny == [MINE]


def test_creating_a_manual_entry_with_no_client_is_allowed(deny, monkeypatch):
    """Internal/admin time has no client — can_access_client(user, None) is
    always True, so this must never be refused."""
    db = FakeDB()
    _wire_db(monkeypatch, db)
    resp = tt.create_manual_entry(
        tt.ManualEntryCreate(started_at="2026-01-01T00:00:00Z"),
        current_user=EXEC_USER,
    )
    assert resp["success"] is True
    assert deny == [None]


def test_starting_a_timer_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        tt.start_timer(tt.StartTimerBody(client_id=THEIRS), current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_starting_a_timer_for_an_own_client_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    resp = tt.start_timer(tt.StartTimerBody(client_id=MINE), current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════
# stop_timer / update_entry / delete_entry (row-addressed)
# ══════════════════════════════════════════════════════════════════════════

def test_stopping_a_hidden_clients_timer_is_refused(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": THEIRS, "started_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(HTTPException) as exc:
        tt.stop_timer(entry["id"], current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_stopping_an_own_clients_timer_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": MINE, "started_at": "2026-01-01T00:00:00Z"})
    resp = tt.stop_timer(entry["id"], current_user=MANAGER_USER)
    assert resp["success"] is True
    assert resp["data"]["entry"]["ended_at"] is not None


def test_stopping_a_client_less_timer_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": None, "started_at": "2026-01-01T00:00:00Z"})
    resp = tt.stop_timer(entry["id"], current_user=MANAGER_USER)
    assert resp["success"] is True


def test_updating_a_hidden_clients_entry_is_refused(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": THEIRS, "started_at": "2026-01-01T00:00:00Z", "hourly_rate_paise": 100000})
    with pytest.raises(HTTPException) as exc:
        tt.update_entry(entry["id"], tt.EntryUpdate(hourly_rate_paise=999999999), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert db.rows("time_entries")[0]["hourly_rate_paise"] == 100000


def test_updating_an_own_clients_entry_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": MINE, "started_at": "2026-01-01T00:00:00Z", "hourly_rate_paise": 100000})
    resp = tt.update_entry(entry["id"], tt.EntryUpdate(hourly_rate_paise=200000), current_user=MANAGER_USER)
    assert resp["success"] is True
    assert resp["data"]["entry"]["hourly_rate_paise"] == 200000


def test_deleting_a_hidden_clients_entry_is_refused(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": THEIRS, "started_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(HTTPException) as exc:
        tt.delete_entry(entry["id"], current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert len(db.rows("time_entries")) == 1


def test_deleting_an_own_clients_entry_is_allowed(deny, monkeypatch):
    db = FakeDB()
    _wire_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": FIRM, "user_id": "u9", "client_id": MINE, "started_at": "2026-01-01T00:00:00Z"})
    resp = tt.delete_entry(entry["id"], current_user=MANAGER_USER)
    assert resp["success"] is True
    assert len(db.rows("time_entries")) == 0


def test_hidden_and_missing_entry_errors_match(deny, monkeypatch):
    # Same id in both scenarios — absent from the store, then present but
    # belonging to another client — so the message can only differ if the
    # wording itself differs between the two branches.
    db = FakeDB()
    _wire_db(monkeypatch, db)
    with pytest.raises(HTTPException) as exc_missing:
        tt.stop_timer("NOPE", current_user=MANAGER_USER)
    db.seed("time_entries", {"id": "NOPE", "firm_id": FIRM, "user_id": "u9", "client_id": THEIRS, "started_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(HTTPException) as exc_hidden:
        tt.stop_timer("NOPE", current_user=MANAGER_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# export_entries — assignment-scope filtering (not present at all before)
# ══════════════════════════════════════════════════════════════════════════

def test_export_time_entries_drops_rows_outside_the_effective_scope():
    db = FakeDB()
    import repositories.time_tracking_repository as _tt_repo
    import repositories.user_repository as _user_repo
    import repositories.client_repository as _client_repo
    # These two are best-effort in the service (wrapped in try/except) and
    # aren't needed for this assertion, so leave them unwired — they'll
    # raise (no SUPABASE_URL) and the service swallows it into {}.
    db.seed("time_entries", {"firm_id": FIRM, "client_id": MINE, "user_id": "u1",
                              "started_at": "2026-01-01T00:00:00Z", "duration_minutes": 60,
                              "is_billable": True, "description": "mine-desc"})
    db.seed("time_entries", {"firm_id": FIRM, "client_id": THEIRS, "user_id": "u1",
                              "started_at": "2026-01-01T00:00:00Z", "duration_minutes": 90,
                              "is_billable": True, "description": "theirs-desc"})
    db.seed("time_entries", {"firm_id": FIRM, "client_id": None, "user_id": "u1",
                              "started_at": "2026-01-01T00:00:00Z", "duration_minutes": 30,
                              "is_billable": False, "description": "internal-desc"})

    import unittest.mock as mock
    with mock.patch.object(_tt_repo, "_get_db", lambda: db):
        content, _filename, _media = export_time_entries(
            firm_id=FIRM, fmt="csv", effective_client_ids={MINE},
        )
    text = content.decode("utf-8-sig")
    assert "mine-desc" in text
    assert "internal-desc" in text
    assert "theirs-desc" not in text


def test_export_time_entries_with_no_scope_restriction_keeps_everything():
    """effective_client_ids=None means a firm-wide role (or mock/dev) — no
    filtering at all, matching the pre-fix behaviour for those callers."""
    db = FakeDB()
    import repositories.time_tracking_repository as _tt_repo
    db.seed("time_entries", {"firm_id": FIRM, "client_id": THEIRS, "user_id": "u1",
                              "started_at": "2026-01-01T00:00:00Z", "duration_minutes": 90,
                              "is_billable": True, "description": "theirs-desc"})
    import unittest.mock as mock
    with mock.patch.object(_tt_repo, "_get_db", lambda: db):
        content, _filename, _media = export_time_entries(firm_id=FIRM, fmt="csv")
    assert "theirs-desc" in content.decode("utf-8-sig")


def test_export_entries_router_passes_effective_client_ids_to_the_service(monkeypatch):
    captured = {}

    def fake_export(**kwargs):
        captured.update(kwargs)
        return (b"data", "f.csv", "text/csv")

    monkeypatch.setattr(export_service_module, "export_time_entries", fake_export)
    monkeypatch.setattr(tt, "effective_client_ids", lambda user: {MINE})
    tt.export_entries(current_user=MANAGER_USER)
    assert captured.get("effective_client_ids") == {MINE}
