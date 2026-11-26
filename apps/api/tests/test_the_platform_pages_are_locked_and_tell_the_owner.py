"""The platform pages' locks (POST-B-351, the owner's decision of 25-11-2026), each asked of the real gate.

Lock 3: once the platform list holds an account that belongs to no firm, an account that belongs to a firm (staff, a
client's portal contact, an employee with portal access) is refused with the same plain 404 as a stranger. Until then a
list made only of firm members is let through and marked, so adding the dedicated account is what turns the rule on and a
deploy never locks the owner out. A read that cannot answer refuses.

Lock 6: the first platform request of each sign-in session, and every action, is mailed to every address on the list,
once per session, after the response; a mail that fails does not stop the page.
"""
import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import core.platform_auth as pa
from core.auth import get_jwt_user
from services import platform_notice


# ── a tiny stand-in for the service client: rows per table, filters on equality ─────────────────────────────────────
class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.payload = db, table, {}, None

    def select(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        class R: pass
        r = R()
        if self.payload is not None:
            self.db.rows.setdefault(self.table, []).append(self.payload)
            r.data = [self.payload]
            return r
        if self.table in self.db.broken:
            raise RuntimeError("read failed")
        rows = self.db.rows.get(self.table, [])

        def hit(row):
            for col, val in self.filters.items():
                if col.startswith("metadata->>"):
                    if str((row.get("metadata") or {}).get(col.split(">>", 1)[1])) != str(val):
                        return False
                elif str(row.get(col)) != str(val):
                    return False
            return True
        r.data = [row for row in rows if hit(row)]
        return r


class _DB:
    def __init__(self, rows, broken=()):
        self.rows, self.broken = rows, set(broken)

    def table(self, name):
        return _Q(self, name)


def _standing_for(db, uid):
    import core.supabase_client as sc
    original = sc.get_service_supabase
    sc.get_service_supabase = lambda: db
    try:
        return pa._firm_standing(uid)
    finally:
        sc.get_service_supabase = original


# ── lock 3, the facts ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_account_with_a_row_in_any_principal_table_belongs_to_a_firm():
    for table in pa.PRINCIPAL_TABLES:
        column = "portal_user_id" if table == "clients" else "auth_user_id"
        db = _DB({"platform_admins": [{"auth_user_id": "old"}], table: [{column: "old"}]})
        assert _standing_for(db, "old").belongs_to == (table,), table


def test_the_rule_turns_on_only_when_a_firmless_account_is_listed():
    only_members = _DB({"platform_admins": [{"auth_user_id": "old"}], "users": [{"auth_user_id": "old"}]})
    assert _standing_for(only_members, "old") == pa.Standing(belongs_to=("users",), firmless_admin_on_list=False)
    with_dedicated = _DB({"platform_admins": [{"auth_user_id": "old"}, {"auth_user_id": "new"}],
                          "users": [{"auth_user_id": "old"}]})
    assert _standing_for(with_dedicated, "new") == pa.Standing(belongs_to=(), firmless_admin_on_list=True)
    assert _standing_for(with_dedicated, "old").firmless_admin_on_list is True


# ── lock 3, the gate ─────────────────────────────────────────────────────────────────────────────────────────────────
def _gate_client(monkeypatch, standing, *, aal="aal2", visits=None):
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: True)
    if isinstance(standing, Exception):
        def boom(uid):
            raise standing
        monkeypatch.setattr(pa, "_firm_standing", boom)
    else:
        monkeypatch.setattr(pa, "_firm_standing", lambda uid: standing)
    monkeypatch.setattr(platform_notice, "note_visit",
                        lambda admin, address: (visits if visits is not None else []).append((admin, address)))
    monkeypatch.setattr(platform_notice, "later", lambda fn, *a, **k: fn(*a, **k))
    app = FastAPI()

    @app.get("/guarded")
    def guarded(admin: dict = Depends(pa.require_platform_admin)):
        return {"transitional": admin["platform_transitional"]}

    app.dependency_overrides[get_jwt_user] = lambda: {
        "auth_user_id": "u1", "email": "owner@example.com", "aal": aal, "last_authenticator_code_at": time.time(),
        "session_claims": {"session_id": "s-1", "iat": 1}}
    return TestClient(app, raise_server_exceptions=False)


def test_a_firm_member_is_refused_like_a_stranger_once_a_firmless_account_is_listed(monkeypatch):
    r = _gate_client(monkeypatch, pa.Standing(belongs_to=("users",), firmless_admin_on_list=True)).get("/guarded")
    assert r.status_code == 404 and r.json()["detail"] == "Not found"


def test_a_firm_member_is_let_through_and_marked_while_no_firmless_account_is_listed(monkeypatch):
    r = _gate_client(monkeypatch, pa.Standing(belongs_to=("users",), firmless_admin_on_list=False)).get("/guarded")
    assert r.status_code == 200 and r.json() == {"transitional": True}


def test_the_dedicated_account_passes_unmarked(monkeypatch):
    r = _gate_client(monkeypatch, pa.Standing(belongs_to=(), firmless_admin_on_list=True)).get("/guarded")
    assert r.status_code == 200 and r.json() == {"transitional": False}


def test_a_standing_that_cannot_be_read_refuses(monkeypatch):
    r = _gate_client(monkeypatch, RuntimeError("down")).get("/guarded")
    assert r.status_code == 503 and r.json()["detail"] == pa.STANDING_UNREADABLE_SENTENCE


def test_the_second_factor_is_asked_before_anything_is_read_or_mailed(monkeypatch):
    visits = []
    r = _gate_client(monkeypatch, RuntimeError("must not be read"), aal="aal1", visits=visits).get("/guarded")
    assert r.status_code == 403 and r.json()["detail"] == pa.SECOND_FACTOR_SENTENCE
    assert visits == []


def test_a_visit_that_passes_is_handed_to_the_notice(monkeypatch):
    visits = []
    _gate_client(monkeypatch, pa.Standing(belongs_to=(), firmless_admin_on_list=True), visits=visits).get("/guarded")
    assert len(visits) == 1 and visits[0][0]["email"] == "owner@example.com"


def test_me_says_when_the_second_factor_is_still_needed(monkeypatch):
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: True)
    app = FastAPI()

    @app.get("/me")
    def me(ctx: dict = Depends(pa.is_platform_admin)):
        return {"needed": ctx["second_factor_needed"]}

    for aal, needed in (("aal1", True), ("aal2", False)):
        app.dependency_overrides[get_jwt_user] = lambda aal=aal: {"auth_user_id": "u1", "aal": aal}
        assert TestClient(app).get("/me").json() == {"needed": needed}


# ── lock 6, the mails ────────────────────────────────────────────────────────────────────────────────────────────────
def _mail_db(monkeypatch, rows, sent, ok=True):
    import core.supabase_client as sc
    from services import email_service
    db = _DB(rows)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(email_service, "_send", lambda to, subject, body, **k: sent.append((to, subject, body)) or ok)
    platform_notice._told_sessions.clear()
    return db


_ADMIN = {"auth_user_id": "u1", "email": "owner@example.com", "session_claims": {"session_id": "s-1"}}


def test_a_sign_in_is_mailed_to_everyone_on_the_list_once_per_session(monkeypatch):
    sent = []
    db = _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}, {"email": "b@example.com"},
                                                    {"email": None}]}, sent)
    platform_notice.note_visit(_ADMIN, "203.0.113.9")
    platform_notice.note_visit(_ADMIN, "203.0.113.9")
    assert sorted(to for to, _s, _b in sent) == ["a@example.com", "b@example.com"]
    assert "203.0.113.9" in sent[0][2] and "owner@example.com" in sent[0][2] and "IST" in sent[0][2]
    recorded = db.rows["platform_audit"]
    assert len(recorded) == 1 and recorded[0]["action"] == "platform_sign_in" and recorded[0]["metadata"]["mailed"] is True


def test_a_session_already_recorded_is_not_mailed_again_after_a_restart(monkeypatch):
    sent = []
    _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}],
                           "platform_audit": [{"action": "platform_sign_in", "metadata": {"session": "session:s-1"}}]}, sent)
    platform_notice.note_visit(_ADMIN, None)
    assert sent == []


def test_a_new_session_is_a_new_sign_in(monkeypatch):
    sent = []
    _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent)
    platform_notice.note_visit(_ADMIN, None)
    platform_notice.note_visit({**_ADMIN, "session_claims": {"session_id": "s-2"}}, None)
    assert len(sent) == 2


def test_a_mail_that_fails_is_recorded_and_does_not_raise(monkeypatch):
    sent = []
    db = _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent, ok=False)
    platform_notice.note_visit(_ADMIN, None)
    assert db.rows["platform_audit"][0]["metadata"]["mailed"] is False


def test_a_transitional_account_is_named_as_one_in_the_mail(monkeypatch):
    sent = []
    _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent)
    platform_notice.note_visit({**_ADMIN, "platform_transitional": True}, None)
    assert "also a member of a firm" in sent[0][2]


def test_every_action_is_mailed_with_the_firm_name_escaped(monkeypatch):
    for action in platform_notice.ACTION_WORDS:
        sent = []
        db = _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent)
        platform_notice.note_action(_ADMIN, action, "F1", "<b>Acme</b> & Co", "Reason given: test.")
        assert len(sent) == 1, action
        assert "&lt;b&gt;Acme&lt;/b&gt; &amp; Co" in sent[0][2] and "<b>Acme</b>" not in sent[0][2]
        assert db.rows["platform_audit"][0]["action"] == action


def test_the_purge_writes_its_own_row_so_the_notice_does_not_write_a_second(monkeypatch):
    sent = []
    db = _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent)
    platform_notice.note_action(_ADMIN, "platform_purge", "F1", "Acme", record=False)
    assert len(sent) == 1 and "platform_audit" not in db.rows


def test_every_action_route_hands_its_action_to_the_notice():
    import inspect
    from routers import platform as plat
    src = inspect.getsource(plat)
    for action in platform_notice.ACTION_WORDS:
        assert f'platform_notice.note_action, admin, "{action}"' in src, action


# ── the platform administration site's origin ────────────────────────────────────────────────────────────────────────
def test_the_admin_sites_origin_is_added_only_when_it_is_a_plain_https_origin(monkeypatch):
    from core import urls
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("PLATFORM_ADMIN_ORIGIN", raising=False)
    assert urls.allowed_origins() == ["https://app.example.com"]
    monkeypatch.setenv("PLATFORM_ADMIN_ORIGIN", "https://admin.example.com/")
    assert urls.allowed_origins() == ["https://app.example.com", "https://admin.example.com"]
    for bad in ("http://admin.example.com", "https://*.example.com", "https://admin.example.com/path",
                "admin.example.com", "https://admin.example.com:8443", "https://localhost"):
        monkeypatch.setenv("PLATFORM_ADMIN_ORIGIN", bad)
        assert urls.allowed_origins() == ["https://app.example.com"], bad


def test_the_activity_route_is_behind_the_platform_gate():
    import inspect
    from routers import platform as plat
    assert "def activity(_admin: dict = Depends(require_platform_admin))" in inspect.getsource(plat)


# ── found by the independent review of 27-11-2026 ────────────────────────────────────────────────────────────────────
def test_three_first_requests_at_once_send_one_sign_in_mail(monkeypatch):
    import threading
    sent = []
    _mail_db(monkeypatch, {"platform_admins": [{"email": "a@example.com"}]}, sent)
    threads = [threading.Thread(target=platform_notice.note_visit, args=(_ADMIN, None)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sent) == 1


def test_a_refused_first_request_still_mails_the_sign_in(monkeypatch):
    # The notice no longer rides on the response's background tasks, which FastAPI drops when the route raises.
    visits = []
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: True)
    monkeypatch.setattr(pa, "_firm_standing", lambda uid: pa.Standing(belongs_to=(), firmless_admin_on_list=True))
    monkeypatch.setattr(platform_notice, "note_visit", lambda admin, address: visits.append(admin))
    monkeypatch.setattr(platform_notice, "later", lambda fn, *a, **k: fn(*a, **k))
    app = FastAPI()

    @app.post("/refused")
    def refused(_a: dict = Depends(pa.require_platform_admin)):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="refused")

    app.dependency_overrides[get_jwt_user] = lambda: {"auth_user_id": "u1", "email": "o@example.com", "aal": "aal2"}
    assert TestClient(app, raise_server_exceptions=False).post("/refused").status_code == 400
    assert len(visits) == 1


def test_once_on_the_rule_stays_on_when_the_dedicated_account_later_gains_a_firm_row():
    db = _DB({"platform_admins": [{"auth_user_id": "old"}, {"auth_user_id": "new"}], "users": [{"auth_user_id": "old"}]})
    assert _standing_for(db, "old").firmless_admin_on_list is True
    assert [r["action"] for r in db.rows["platform_audit"]] == [pa.FIRMLESS_RULE_ON]
    db.rows["users"].append({"auth_user_id": "new"})          # the dedicated account ran the new-practice wizard
    assert _standing_for(db, "old") == pa.Standing(belongs_to=("users",), firmless_admin_on_list=True)
    assert _standing_for(db, "new").belongs_to == ("users",)
    assert len(db.rows["platform_audit"]) == 1                # recorded once


def test_the_old_one_contact_portal_link_counts_as_belonging_to_a_firm():
    db = _DB({"platform_admins": [{"auth_user_id": "old"}], "clients": [{"portal_user_id": "old", "id": "c1"}]})
    assert _standing_for(db, "old").belongs_to == ("clients",)


def test_every_notice_runs_on_its_own_thread_and_not_on_the_response():
    import inspect
    from routers import platform as plat
    for src in (inspect.getsource(plat), inspect.getsource(pa)):
        assert "background_tasks" not in src and "BackgroundTasks" not in src
    purge = inspect.getsource(plat.purge_firm)
    assert purge.index("platform_notice.later") < purge.index('db.table("platform_audit").insert'), \
        "the purge is mailed before its own audit row, so a failed row still mails"
