"""A permanently deleted firm's people are told their firm is closed, not sent to the new-practice wizard (POST-A-499, migration 772).

WHAT WAS WRONG
    The platform page's suspend and soft delete end a firm's sessions by a stamp on each member's `users` row (`sessions_revoked_at`,
    POST-A-482). A PURGE deletes those rows (migration 141) and leaves the sign-in accounts on purpose, so a person who held a session
    reached `get_current_user` with an account that had no member row: 403 "User not found in firm", and the browser, finding no
    practice, opened the new-practice wizard. Nobody was signed out and nobody was told why. The refusal could not simply be added to
    the four the browser signs out on, because the same 403 is what a person in the middle of sign-up (an account with no practice
    yet) gets.

WHAT IT DOES
    Before the purge the API writes a marker per member (`closed_account_markers`, one row per sign-in account, the instant and how);
    `get_current_user` reads it only on the path where an account has no member row, and a session that BEGAN before the marker is
    answered 403 "Firm unavailable", the words the browser already turns into a sign-out and a sentence. A sign-in made after the
    purge is not refused, so the person can start a practice with the same login. Platform administrators are not marked (their access
    to the platform page survives the purge of their own firm), and a purge that cannot write its markers does not run.

NEGATIVE CONTROLS (each was run and these fail)
    * no markers written              - the writing and the ordering tests fail
    * markers written after the purge - the ordering test fails
    * a platform administrator marked - the administrator test fails
    * every session refused           - the fresh sign-in test fails
    * no session refused              - the old-session tests fail
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.auth as auth
import core.platform_auth as pa
import routers.platform as plat
from core.auth import get_jwt_user

NOW = 1_800_000_000.0
CLOSED_AT = "2027-01-15T10:00:00+00:00"
CLOSED_EPOCH = NOW + 1000.0


class _Rows:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self._eq, self._in, self._upsert, self._insert, self._update, self._delete = {}, None, None, None, None, False

    def select(self, *a, **k): return self
    def eq(self, col, val): self._eq[col] = val; return self
    def in_(self, col, vals): self._in = (col, list(vals)); return self
    def maybe_single(self): return self
    def limit(self, *a): return self
    def insert(self, row): self._insert = row; return self
    def update(self, change): self._update = change; return self
    def delete(self): self._delete = True; return self
    def upsert(self, rows, on_conflict=None): self._upsert = (rows, on_conflict); return self

    def execute(self):
        db, t = self.db, self.table_name
        if self._upsert is not None:
            db.order.append(("upsert", t))
            if db.fail_markers and t == "closed_account_markers":
                raise RuntimeError("the markers could not be written")
            db.upserts.append((t, self._upsert[0], self._upsert[1]))
            return _Rows(self._upsert[0])
        if self._delete:
            db.order.append(("delete", t))
            if db.fail_unmark and t == "closed_account_markers":
                raise RuntimeError("the markers could not be taken back")
            db.deleted.append((t, self._in))
            return _Rows([])
        if self._insert is not None:
            db.order.append(("insert", t))
            db.inserted.append((t, self._insert))
            return _Rows([self._insert])
        if self._update is not None:
            db.order.append(("update", t))
            return _Rows([{"id": "m1"}])
        if t == "firms":
            return _Rows({"id": "FIRM-1", "name": "Acme & Co"})
        if t == "users":
            return _Rows(db.members)
        if t == "platform_admins":
            wanted = set(self._in[1]) if self._in else set()
            return _Rows([{"auth_user_id": a} for a in db.admins if a in wanted])
        return _Rows(None)


class _DB:
    def __init__(self, members, admins=(), fail_markers=False, fail_purge=False, fail_unmark=False):
        self.members, self.admins, self.fail_markers = members, list(admins), fail_markers
        self.fail_purge, self.fail_unmark = fail_purge, fail_unmark
        self.upserts, self.inserted, self.rpc_calls, self.order, self.deleted = [], [], [], [], []

    def table(self, name): return _Query(self, name)

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        self.order.append(("rpc", fn))
        db = self

        class _R:
            def execute(_s):
                if db.fail_purge:
                    raise RuntimeError("the purge function failed")
                return _Rows({"clients_deleted": 0, "users_deleted": len(db.members)})
        return _R()


MEMBERS = [{"auth_user_id": "11111111-0000-4000-8000-000000000001"}, {"auth_user_id": "11111111-0000-4000-8000-000000000002"},
           {"auth_user_id": None},                                                   # invited and never joined: no sign-in account
           {"auth_user_id": "11111111-0000-4000-8000-000000000001"}]                 # a repeat of the first


# ═══ THE MARKERS ARE WRITTEN BEFORE THE PURGE ═══════════════════════════════════════════════════════════════════════════════════

def test_one_marker_per_sign_in_account_of_the_firm_and_how_it_closed():
    db = _DB(MEMBERS)
    assert sorted(plat._mark_closed_accounts(db, "FIRM-1")) == ["11111111-0000-4000-8000-000000000001", "11111111-0000-4000-8000-000000000002"]
    (table, rows, conflict), = db.upserts
    assert table == "closed_account_markers" and conflict == "auth_user_id"
    assert sorted(r["auth_user_id"] for r in rows) == ["11111111-0000-4000-8000-000000000001", "11111111-0000-4000-8000-000000000002"]
    assert {r["closed_how"] for r in rows} == {"firm_purged"} and all(r["closed_at"] for r in rows)


def test_a_platform_administrator_is_not_marked():
    db = _DB(MEMBERS, admins=["11111111-0000-4000-8000-000000000002"])
    assert plat._mark_closed_accounts(db, "FIRM-1") == ["11111111-0000-4000-8000-000000000001"]
    assert [r["auth_user_id"] for r in db.upserts[0][1]] == ["11111111-0000-4000-8000-000000000001"]


def test_a_firm_with_nobody_who_ever_joined_writes_nothing():
    db = _DB([{"auth_user_id": None}])
    assert plat._mark_closed_accounts(db, "FIRM-1") == []
    assert db.upserts == []
    assert plat._mark_closed_accounts(_DB([]), "FIRM-1") == []


def test_a_marker_that_cannot_be_written_raises_rather_than_being_skipped():
    with pytest.raises(RuntimeError):
        plat._mark_closed_accounts(_DB(MEMBERS, fail_markers=True), "FIRM-1")


def _purge_client(monkeypatch, db, *, as_the_server_answers=False):
    app = FastAPI()
    app.include_router(plat.router)
    monkeypatch.setattr(plat, "get_service_supabase", lambda: db)
    monkeypatch.setattr(pa, "_is_platform_admin", lambda auth_user_id: True)
    from services import platform_notice as _notice   # POST-B-351: no database read for lock 3 and no mail
    monkeypatch.setattr(pa, "_firm_standing", lambda uid: pa.Standing(belongs_to=(), firmless_admin_on_list=True))
    monkeypatch.setattr(_notice, "note_visit", lambda *a, **k: None)
    monkeypatch.setattr(_notice, "note_action", lambda *a, **k: None)
    admin = {"auth_user_id": "adm", "email": "admin@x.test", "aal": "aal2", "last_authenticator_code_at": time.time()}
    app.dependency_overrides[get_jwt_user] = lambda: admin
    return TestClient(app, raise_server_exceptions=not as_the_server_answers)


def test_the_markers_are_written_before_the_firm_is_purged(monkeypatch):
    db = _DB(MEMBERS)
    resp = _purge_client(monkeypatch, db).delete("/api/platform/firms/FIRM-1/permanent")
    assert resp.status_code == 200, resp.text
    kinds = [k for k in db.order]
    assert ("upsert", "closed_account_markers") in kinds and ("rpc", "platform_purge_firm") in kinds
    assert kinds.index(("upsert", "closed_account_markers")) < kinds.index(("rpc", "platform_purge_firm"))
    body = resp.json()["data"]
    assert body["status"] == "purged" and body["people_marked_closed"] == 2
    audit = [row for t, row in db.inserted if t == "platform_audit"][0]
    assert audit["metadata"]["people_marked_closed"] == 2


def test_a_purge_that_cannot_write_its_markers_does_not_run(monkeypatch):
    db = _DB(MEMBERS, fail_markers=True)
    resp = _purge_client(monkeypatch, db).delete("/api/platform/firms/FIRM-1/permanent")
    assert resp.status_code == 503
    assert "nothing was deleted" in resp.json()["detail"] if "detail" in resp.json() else "nothing was deleted" in resp.text
    assert db.rpc_calls == [], "the firm was purged although its people could not be marked"
    assert [t for t, _ in db.inserted] == [], "an audit row was written for a purge that did not happen"


def test_a_purge_that_fails_after_the_markers_takes_them_back_and_still_fails(monkeypatch):
    db = _DB(MEMBERS, fail_purge=True)
    client = _purge_client(monkeypatch, db, as_the_server_answers=True)
    resp = client.delete("/api/platform/firms/FIRM-1/permanent")
    assert resp.status_code == 500, resp.text
    assert ("delete", "closed_account_markers") in db.order, "the markers of a firm that still exists were left standing"
    (_, in_filter), = db.deleted
    assert in_filter[0] == "auth_user_id" and sorted(in_filter[1]) == ["11111111-0000-4000-8000-000000000001", "11111111-0000-4000-8000-000000000002"]
    assert [t for t, _ in db.inserted] == [], "an audit row was written for a purge that did not happen"


def test_a_take_back_that_itself_fails_does_not_hide_the_purges_failure(monkeypatch):
    """What reaches the server's own handler is the PURGE's failure, not the clean-up's: the person reading the log is told what went wrong."""
    db = _DB(MEMBERS, fail_purge=True, fail_unmark=True)
    client = _purge_client(monkeypatch, db)              # raises what the app raised, so the exception can be read
    with pytest.raises(RuntimeError) as raised:
        client.delete("/api/platform/firms/FIRM-1/permanent")
    assert "the purge function failed" in str(raised.value), str(raised.value)
    assert db.deleted == [] and ("delete", "closed_account_markers") in db.order


def test_nothing_is_taken_back_when_nothing_was_marked():
    db = _DB([])
    plat._unmark_closed_accounts(db, [])
    assert db.order == []


# ═══ THE MARKER IS READ ONLY WHERE AN ACCOUNT HAS NO MEMBER ROW ═════════════════════════════════════════════════════════════════════════

class _Supabase:
    """The privileged client double for the marker lookup alone."""
    def __init__(self, marker, fail=False):
        self.marker, self.fail = marker, fail

    def table(self, name):
        assert name == "closed_account_markers", name
        sup = self

        class _Q:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def maybe_single(self): return self
            def execute(self_inner):
                if sup.fail:
                    raise RuntimeError("PostgREST said no")
                return _Rows(sup.marker)
        return _Q()


def _token(iat, *amr):
    return {"sub": "11111111-0000-4000-8000-000000000001", "iat": iat, "amr": [{"method": m, "timestamp": ts} for m, ts in amr]}


MARKER = {"closed_at": CLOSED_AT}


def _closed_epoch():
    return auth._instant_epoch(CLOSED_AT)


def test_a_session_that_began_before_the_purge_is_told_the_firm_is_closed():
    before = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    with pytest.raises(HTTPException) as exc:
        auth._refuse_a_closed_firms_person(_Supabase(MARKER), "u1", before)
    assert exc.value.status_code == 403 and exc.value.detail == "Firm unavailable"


def test_a_token_the_browser_renewed_after_the_purge_is_still_that_session():
    renewed = _token(_closed_epoch() + 60, ("password", _closed_epoch() - 3600))
    with pytest.raises(HTTPException) as exc:
        auth._refuse_a_closed_firms_person(_Supabase(MARKER), "u1", renewed)
    assert exc.value.detail == "Firm unavailable"


def test_a_sign_in_made_after_the_purge_is_a_person_who_may_start_a_practice():
    fresh = _token(_closed_epoch() + 30, ("password", _closed_epoch() + 30))
    assert auth._refuse_a_closed_firms_person(_Supabase(MARKER), "u1", fresh) is None


def test_an_account_with_no_marker_is_a_person_mid_sign_up_and_is_not_refused_here():
    old = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    assert auth._refuse_a_closed_firms_person(_Supabase(None), "u1", old) is None
    assert auth._refuse_a_closed_firms_person(_Supabase({}), "u1", old) is None


def test_a_marker_that_cannot_be_read_leaves_the_ordinary_refusal():
    old = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    assert auth._refuse_a_closed_firms_person(_Supabase(MARKER, fail=True), "u1", old) is None


def test_a_closed_at_that_cannot_be_compared_leaves_the_ordinary_refusal():
    old = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    assert auth._refuse_a_closed_firms_person(_Supabase({"closed_at": "not a time"}), "u1", old) is None


def _current_user(monkeypatch, supabase, token_payload):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda token: token_payload)
    monkeypatch.setattr(auth, "get_service_supabase", lambda: supabase)
    monkeypatch.setattr(auth, "_get_user_and_firm", lambda sb, auth_user_id: (None, None))
    return auth.get_current_user(authorization="Bearer t", x_user_role=None, x_firm_id=None, x_user_id=None)


def test_the_door_answers_firm_unavailable_for_an_old_session_and_the_old_words_for_a_new_person(monkeypatch):
    old = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    with pytest.raises(HTTPException) as exc:
        _current_user(monkeypatch, _Supabase(MARKER), old)
    assert exc.value.status_code == 403 and exc.value.detail == "Firm unavailable"

    fresh = _token(_closed_epoch() + 30, ("password", _closed_epoch() + 30))
    with pytest.raises(HTTPException) as exc:
        _current_user(monkeypatch, _Supabase(MARKER), fresh)
    assert exc.value.status_code == 403 and exc.value.detail.startswith("User not found in firm")


def test_a_person_who_has_a_member_row_is_never_asked_about_a_marker(monkeypatch):
    """The marker is a fact about an account that has NO member row. A person with one is let through, or refused for their own reasons,
    and the table is not consulted at all, so a stale marker cannot sign out somebody who has a practice."""
    class _Spy:
        """Records what was read and fails the read: the lookup's own safety catch would swallow an assertion raised inside it, so the
        test asks afterwards what was touched instead of asserting inside the double."""
        def __init__(self):
            self.tables = []

        def table(self, name):
            self.tables.append(name)
            raise RuntimeError(f"the member's request read {name}")

    spy = _Spy()
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    old = _token(_closed_epoch() - 600, ("password", _closed_epoch() - 600))
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda token: old)
    monkeypatch.setattr(auth, "get_service_supabase", lambda: spy)
    member = {"id": "u1", "firm_id": "FIRM-2", "role": "Partner", "is_active": True, "full_name": "A Partner"}
    monkeypatch.setattr(auth, "_get_user_and_firm", lambda sb, auth_user_id: (member, {"is_active": True, "deleted_at": None}))
    me = auth.get_current_user(authorization="Bearer t", x_user_role=None, x_firm_id=None, x_user_id=None)
    assert me["firm_id"] == "FIRM-2" and me["role"] == "Partner"
    assert spy.tables == [], f"a person with a member row caused a read of {spy.tables}"


# ═══ THE TABLE HAS ONE WRITER AND ONE READER ════════════════════════════════════════════════════════════════════════════════════════════

def test_only_the_purge_writes_the_markers_and_only_the_door_reads_them():
    import pathlib
    api = pathlib.Path(auth.__file__).resolve().parents[1]
    users = []
    for path in list(api.glob("**/*.py")):
        rel = path.relative_to(api).as_posix()
        if rel.startswith(("tests/", "migrations/")) or "/tests/" in rel:
            continue
        if 'closed_account_markers' in path.read_text(encoding="utf-8"):
            users.append(rel)
    assert sorted(users) == ["core/auth.py", "routers/platform.py"], users
