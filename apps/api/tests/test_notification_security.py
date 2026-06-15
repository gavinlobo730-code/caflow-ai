"""
Module 9.0 / M2 — notification authorization wiring.

The actual SQL scoping lives in the non-mock repo branch; these tests verify the
router threads the recipient's user_id into the repository for list/mark/archive
so a user can only see/mutate their own notifications (the prior code OR'd in
NULL-recipient rows and scoped mutations by firm only).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.notifications as notif_mod
from routers.notifications import router as notif_router
from core.auth import get_current_user

USER = {"id": "u-1", "firm_id": "F1", "role": "Executive"}


def _client(monkeypatch, captured):
    monkeypatch.setattr(notif_mod.notifications_repo, "find_all",
                        lambda **kw: (captured.setdefault("find_all", kw), [])[1])
    monkeypatch.setattr(notif_mod.notifications_repo, "count_unread",
                        lambda **kw: (captured.setdefault("count_unread", kw), 0)[1])
    monkeypatch.setattr(notif_mod.notifications_repo, "mark_read",
                        lambda nid, **kw: (captured.setdefault("mark_read", {**kw, "id": nid}), {"id": nid})[1])
    monkeypatch.setattr(notif_mod.notifications_repo, "archive",
                        lambda nid, **kw: (captured.setdefault("archive", {**kw, "id": nid}), {"id": nid})[1])
    app = FastAPI()
    app.include_router(notif_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


def test_list_is_scoped_to_user(monkeypatch):
    cap = {}
    _client(monkeypatch, cap).get("/api/notifications")
    assert cap["find_all"]["user_id"] == "u-1"
    assert cap["find_all"]["firm_id"] == "F1"


def test_mark_read_is_scoped_to_user(monkeypatch):
    cap = {}
    _client(monkeypatch, cap).patch("/api/notifications/n-1/read")
    assert cap["mark_read"]["user_id"] == "u-1"
    assert cap["mark_read"]["id"] == "n-1"


def test_archive_is_scoped_to_user(monkeypatch):
    cap = {}
    _client(monkeypatch, cap).patch("/api/notifications/n-1/archive")
    assert cap["archive"]["user_id"] == "u-1"


def test_repo_find_all_drops_null_recipient_broadcast():
    """Regression guard: the repo no longer OR's in user_id IS NULL."""
    import inspect
    src = inspect.getsource(notif_mod.notifications_repo.find_all)
    assert "is.null" not in src
