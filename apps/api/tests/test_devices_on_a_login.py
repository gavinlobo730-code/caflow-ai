"""POST-A-486 — a login says which devices it is signed in on, tells the Partners when a second appears, and signs the others out.

Four things are held here, each against the code as it was:

  * the RULE: what "live" means, the words for a browser, the sentence, and that the server's window is the browser's own two
    numbers (so changing the idle limit cannot leave the server describing a different product);
  * the RECORD: a sign-in stores the address OUR proxy wrote (never the first entry the caller typed), the browser and the sign-in
    service's session id; a sign-out closes the session;
  * the NOTICE: a second live session under one login tells every active Partner in the app, once, and a first session or a
    repeat sighting tells nobody;
  * the SIGN-OUT: "sign out my other sessions" refuses the other sessions' tokens and not the one asking, and does not use the
    mark that ends everything.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import repositories.login_events_repository as le
import repositories.login_sessions_repository as ls
import routers.identity as idmod
from core import auth_time
from core.auth import get_current_user
from domain.identity import devices
from routers.identity import router as identity_router
from services import login_devices_service as svc

WEB = Path(__file__).resolve().parents[2] / "web"
NOW = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)

CHROME_WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Safari/537.36")
EDGE_WINDOWS = CHROME_WINDOWS + " Edg/130.0.0.0"
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                 "Version/17.5 Mobile/15E148 Safari/604.1")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
CHROME_ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Mobile Safari/537.36")


# ── the rule ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _row(**kw):
    base = {"id": "r1", "session_id": "s1", "ip": "203.0.113.9", "user_agent": CHROME_WINDOWS,
            "started_at": NOW.isoformat(), "last_seen_at": NOW.isoformat(), "ended_at": None}
    return {**base, **kw}


def test_a_session_is_live_inside_the_window_and_not_after_or_when_ended_or_unreadable():
    assert devices.is_live(_row(last_seen_at=(NOW - timedelta(minutes=39)).isoformat()), NOW)
    assert not devices.is_live(_row(last_seen_at=(NOW - timedelta(minutes=41)).isoformat()), NOW)
    assert not devices.is_live(_row(ended_at=NOW.isoformat()), NOW)
    assert not devices.is_live(_row(last_seen_at="not a time"), NOW)
    assert not devices.is_live(_row(last_seen_at=None), NOW)


def test_the_server_window_is_the_browsers_idle_limit_plus_its_report_interval():
    """The window is not a number of its own: it is the idle limit the tab enforces plus how often the tab reports. A test reads
    both TypeScript files, so changing either without the other fails here and not in a person's Team screen."""
    idle = (WEB / "lib/auth/idleTimeout.ts").read_text(encoding="utf-8")
    seen = (WEB / "lib/auth/deviceSeen.ts").read_text(encoding="utf-8")
    idle_ms = re.search(r"export const IDLE_LIMIT_MS = (\d+) \* 60 \* 1000;", idle)
    seen_ms = re.search(r"export const SEEN_EVERY_MS = (\d+) \* 60 \* 1000;", seen)
    assert idle_ms and seen_ms, "the two constants are no longer written as minutes * 60 * 1000; update this reader with them"
    assert int(idle_ms.group(1)) == devices.IDLE_LIMIT_MINUTES
    assert int(seen_ms.group(1)) == devices.SEEN_EVERY_MINUTES
    assert devices.LIVE_WINDOW == timedelta(minutes=devices.IDLE_LIMIT_MINUTES + devices.SEEN_EVERY_MINUTES)


@pytest.mark.parametrize("ua,expected", [
    (CHROME_WINDOWS, "Chrome on Windows"),
    (EDGE_WINDOWS, "Edge on Windows"),
    (SAFARI_IPHONE, "Safari on iPhone"),
    (FIREFOX_LINUX, "Firefox on Linux"),
    (CHROME_ANDROID, "Chrome on Android"),
    (CHROME_ANDROID.replace("Chrome/130.0.0.0", "Chrome/130.0.0.0 EdgA/130.0.0.0"), "Edge on Android"),
    (SAFARI_IPHONE + " EdgiOS/130.0.0.0", "Edge on iPhone"),
    ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36",
     "Samsung Internet on Android"),
    (SAFARI_IPHONE + " OPT/4.1", "Opera on iPhone"),
    ("curl/8.5.0", "an unrecognised browser"),
    ("", "an unrecognised browser"),
    (None, "an unrecognised browser"),
])
def test_a_browser_is_named_in_the_words_a_person_would_use(ua, expected):
    assert devices.browser_label(ua) == expected


def test_the_sentence_says_how_many_and_says_none_in_words():
    assert devices.devices_sentence(0) == "Not signed in on any device right now"
    assert devices.devices_sentence(1) == "Signed in on 1 device"
    assert devices.devices_sentence(2) == "Signed in on 2 devices"


def test_a_summary_lists_the_live_sessions_newest_first_and_marks_the_callers_own():
    rows = [
        _row(id="a", session_id="old", last_seen_at=(NOW - timedelta(minutes=20)).isoformat(), user_agent=SAFARI_IPHONE),
        _row(id="b", session_id="mine", last_seen_at=(NOW - timedelta(minutes=2)).isoformat()),
        _row(id="c", session_id="gone", ended_at=NOW.isoformat()),
        _row(id="d", session_id="stale", last_seen_at=(NOW - timedelta(hours=5)).isoformat()),
    ]
    out = devices.summarise(rows, NOW, current_session_id="mine")
    assert [d["id"] for d in out["devices"]] == ["b", "a"]
    assert out["count"] == 2 and out["more_than_one"] and out["sentence"] == "Signed in on 2 devices"
    assert [d["is_current"] for d in out["devices"]] == [True, False]
    # the sign-in service's own id is never sent to a screen
    assert all("session_id" not in d for d in out["devices"])
    # a Partner reading somebody else's login has no "current" to mark
    assert all(d["is_current"] is None for d in devices.summarise(rows, NOW)["devices"])


def test_the_notice_says_what_was_recorded_and_does_not_accuse():
    title, body = devices.second_device_notice("Asha Rao", "Safari on iPhone", "203.0.113.9", 1)
    assert title == "Asha Rao is signed in on another device"
    assert "Safari on iPhone" in body and "203.0.113.9" in body and "1 other session " in body
    for accusing in ("stolen", "hacked", "unauthori", "breach", "suspicious"):
        assert accusing not in body.lower()
    assert "from address" not in devices.second_device_notice("A", "Chrome on Windows", None, 2)[1]


def test_the_stored_browser_text_is_capped_and_stripped_of_control_characters():
    assert devices.clean_user_agent(None) is None and devices.clean_user_agent("  ") is None
    assert devices.clean_user_agent("Mozilla\x00\x1b[31m/5.0") == "Mozilla[31m/5.0"
    assert len(devices.clean_user_agent("x" * 5000)) == devices.USER_AGENT_MAX


# ── the mark that ends the OTHER sessions ──────────────────────────────────────────────────────────────────────────────────────

REVOKED = 1_000.0


def _token(sid, iat, began):
    return {"session_id": sid, "iat": iat, "amr": [{"method": "password", "timestamp": began}]}


@pytest.mark.parametrize("name,payload,kept,ended", [
    ("the kept session, renewed after the mark", _token("keep", REVOKED + 50, REVOKED - 500), "keep", False),
    ("another session that began before the mark", _token("other", REVOKED - 100, REVOKED - 500), "keep", True),
    ("another session RENEWED after the mark (a new iat does not make it a new sign-in)",
     _token("other", REVOKED + 50, REVOKED - 500), "keep", True),
    ("a sign-in after the mark", _token("fresh", REVOKED + 50, REVOKED + 40), "keep", False),
    ("a token that names no session, from before the mark", {"iat": REVOKED - 5}, "keep", True),
    ("a token that names no session, from after the mark", {"iat": REVOKED + 5}, "keep", False),
    ("nothing was kept (cannot happen through the route) so nothing is excused",
     _token("any", REVOKED - 100, REVOKED - 500), None, True),
])
def test_other_sessions_sign_out_refuses_the_others_and_not_the_kept_or_a_later_one(name, payload, kept, ended):
    assert auth_time.ended_by_other_sessions_sign_out(payload, REVOKED, kept) is ended, name


def _mark(**kw):
    return {"other_sessions_revoked_at": datetime.fromtimestamp(REVOKED, timezone.utc).isoformat(),
            "other_sessions_kept_session_id": "keep", **kw}


def test_the_dependency_refuses_another_session_and_admits_the_kept_one_and_a_later_sign_in():
    from fastapi import HTTPException
    import core.auth as auth
    with pytest.raises(HTTPException) as e:
        auth._refuse_a_session_signed_out_from_elsewhere(_mark(), _token("other", REVOKED + 50, REVOKED - 500), "a-1")
    assert e.value.status_code == 401 and "signed out from another device" in e.value.detail
    assert auth._refuse_a_session_signed_out_from_elsewhere(_mark(), _token("keep", REVOKED + 50, REVOKED - 500), "a-1") is None
    assert auth._refuse_a_session_signed_out_from_elsewhere(_mark(), _token("fresh", REVOKED + 50, REVOKED + 40), "a-1") is None
    # nobody has signed their others out: nothing is asked of the token at all
    assert auth._refuse_a_session_signed_out_from_elsewhere({}, {"iat": 1}, "a-1") is None


def test_a_mark_nobody_can_read_refuses_the_request_and_is_not_skipped():
    from fastapi import HTTPException
    import core.auth as auth
    with pytest.raises(HTTPException) as e:
        auth._refuse_a_session_signed_out_from_elsewhere(_mark(other_sessions_revoked_at="not a time"), _token("keep", 1, 1), "a-1")
    assert e.value.status_code == 401 and "could not be verified" in e.value.detail


def test_the_dependency_that_every_route_uses_actually_asks_the_check():
    """A helper nobody calls refuses nothing: the check is only as real as the call in `get_current_user`, which asks it through the one
    function that holds the four refusals (POST-A-498), the same one the invitation's repeat-accept asks."""
    import ast
    import core.auth as auth
    tree = ast.parse(Path(auth.__file__).read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def called(name):
        return {c.func.id for c in ast.walk(fns[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_refuse_an_ended_session" in called("get_current_user")
    assert "_refuse_a_session_signed_out_from_elsewhere" in called("_refuse_an_ended_session")
    assert "session_id" in Path(auth.__file__).read_text(encoding="utf-8").split("def get_current_user")[1].split("def get_jwt_user")[0]


# ── the record, the notice and the sign-out, through the router ─────────────────────────────────────────────────────────────────

class _Users:
    def __init__(self):
        self.rows = {
            "p1": {"id": "p1", "firm_id": "F1", "role": "Partner", "email": "p1@f", "full_name": "Priya", "is_active": True,
                   "auth_user_id": "a-p1"},
            "p2": {"id": "p2", "firm_id": "F1", "role": "Partner", "email": "p2@f", "full_name": "Pooja", "is_active": True,
                   "auth_user_id": "a-p2"},
            "p3": {"id": "p3", "firm_id": "F1", "role": "Partner", "email": "p3@f", "full_name": "Gone", "is_active": False,
                   "auth_user_id": "a-p3"},
            "m1": {"id": "m1", "firm_id": "F1", "role": "Manager", "email": "m1@f", "full_name": "Manoj", "is_active": True,
                   "auth_user_id": "a-m1"},
            "x1": {"id": "x1", "firm_id": "F2", "role": "Partner", "email": "x1@g", "full_name": "Elsewhere", "is_active": True,
                   "auth_user_id": "a-x1"},
        }

    def find_by_id(self, uid, *, firm_id):
        u = self.rows.get(uid)
        return u if u and u["firm_id"] == firm_id else None

    def update(self, uid, data, *, firm_id):
        u = self.find_by_id(uid, firm_id=firm_id)
        if u is not None:
            u.update(data)
        return u

    def find_all(self, firm_id=None):
        return [u for u in self.rows.values() if u["firm_id"] == firm_id]


class _Notices:
    def __init__(self):
        self.sent = []
        self.clients = []
        self.read_with = []

    def create(self, data, *, db=None):
        self.sent.append({**data, "id": f"n{len(self.sent)}"})
        self.clients.append(db)
        return data

    def find_all(self, firm_id=None, user_id=None, unread_only=False, archived=False, notification_type=None, limit=50, *, db=None):
        self.read_with.append(db)
        return [n for n in self.sent if n["user_id"] == user_id and (not unread_only or not n.get("is_read"))
                and (notification_type is None or n["type"] == notification_type)]


def _principal(uid="m1", session="s-office", role="Manager", firm="F1"):
    return {"id": uid, "auth_user_id": f"a-{uid}", "firm_id": firm, "role": role, "email": f"{uid}@f",
            "full_name": "Manoj" if uid == "m1" else uid, "session_id": session}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    le._MOCK_EVENTS.clear()
    ls._MOCK_ROWS.clear()
    users, notices = _Users(), _Notices()
    monkeypatch.setattr(idmod, "user_repo", users)
    monkeypatch.setattr(svc, "user_repo", users)
    monkeypatch.setattr(svc, "notifications_repo", notices)
    monkeypatch.setattr(idmod, "log_event", lambda *a, **k: None)
    yield users, notices
    le._MOCK_EVENTS.clear()
    ls._MOCK_ROWS.clear()


def _client(user):
    app = FastAPI()
    app.include_router(identity_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _sign_in(user, *, ua=CHROME_WINDOWS, ip_chain="198.51.100.77, 203.0.113.9", event="login"):
    return _client(user).post("/api/identity/login-event", json={"event": event},
                              headers={"User-Agent": ua, "X-Forwarded-For": ip_chain})


def test_a_sign_in_records_the_address_our_proxy_wrote_the_browser_and_the_session(world):
    r = _sign_in(_principal())
    assert r.status_code == 200
    (event,) = le._MOCK_EVENTS
    # the LAST entry is the one our own proxy wrote; the first is whatever the caller typed
    assert event["ip"] == "203.0.113.9" and event["ip"] != "198.51.100.77"
    assert event["user_agent"] == CHROME_WINDOWS
    assert event["session_id"] == "s-office"
    (row,) = ls._MOCK_ROWS
    assert (row["user_id"], row["session_id"], row["ip"]) == ("m1", "s-office", "203.0.113.9")


def test_a_sign_out_closes_the_session_it_belongs_to_and_only_that_one(world):
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    _sign_in(_principal(session="s-office"), event="logout")
    by = {r["session_id"]: r for r in ls._MOCK_ROWS}
    assert by["s-office"]["ended_at"] and by["s-office"]["ended_how"] == "signed_out"
    assert by["s-phone"]["ended_at"] is None


def test_the_first_session_tells_nobody_and_the_second_tells_each_active_partner_once(world):
    users, notices = world
    _sign_in(_principal(session="s-office"))
    assert notices.sent == []
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    assert sorted(n["user_id"] for n in notices.sent) == ["p1", "p2"], "the two ACTIVE Partners of this firm, no one else"
    n = notices.sent[0]
    assert n["type"] == "second_device" and n["severity"] == "medium" and n["firm_id"] == "F1"
    assert "Safari on iPhone" in n["body"] and "203.0.113.9" in n["body"]
    # the same session announcing itself again, by either door, tells nobody more
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    _client(_principal(session="s-phone")).post("/api/identity/session-seen")
    assert len(notices.sent) == 2


def test_a_session_found_by_the_report_and_not_by_a_sign_in_is_counted_and_tells_the_partners_too(world):
    """An invitation, a reset link or a page refreshed after this shipped records no login event; the tab's own report is how the
    session becomes known, and it is a second device all the same."""
    users, notices = world
    _sign_in(_principal(session="s-office"))
    r = _client(_principal(session="s-link")).post("/api/identity/session-seen", headers={"User-Agent": FIREFOX_LINUX})
    assert r.status_code == 200 and r.json()["data"]["registered"] is True
    assert len(notices.sent) == 2 and "Firefox on Linux" in notices.sent[0]["body"]


def test_a_session_that_has_gone_quiet_or_signed_out_does_not_make_the_next_one_a_second_device(world):
    users, notices = world
    _sign_in(_principal(session="s-old"))
    ls._MOCK_ROWS[0]["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _sign_in(_principal(session="s-new"))
    assert notices.sent == [], "the first session's last sighting is three hours old: nobody is signed in there"
    _sign_in(_principal(session="s-new"), event="logout")
    _sign_in(_principal(session="s-newer"))
    assert notices.sent == []


def test_a_token_with_no_session_id_records_the_sign_in_and_no_session(world):
    users, notices = world
    r = _sign_in(_principal(session=None))
    assert r.status_code == 200 and le._MOCK_EVENTS[0]["session_id"] is None
    assert ls._MOCK_ROWS == [] and notices.sent == []


def test_my_devices_lists_the_callers_live_sessions_and_marks_this_one(world):
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    _sign_in(_principal(uid="p1", role="Partner", session="s-other-person"))
    data = _client(_principal(session="s-phone")).get("/api/identity/my-devices").json()["data"]
    assert data["count"] == 2 and data["sentence"] == "Signed in on 2 devices" and data["can_keep_this_session"] is True
    current = [d for d in data["devices"] if d["is_current"]]
    assert len(current) == 1 and current[0]["browser"] == "Safari on iPhone"
    assert "s-other-person" not in str(data)


def test_a_partner_reads_a_members_devices_and_the_whole_firms_and_not_another_firms(world):
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    partner = _principal(uid="p1", role="Partner", session="s-p")
    one = _client(partner).get("/api/identity/users/m1/devices")
    assert one.status_code == 200 and one.json()["data"]["count"] == 2
    assert all(d["is_current"] is None for d in one.json()["data"]["devices"])
    firm = _client(partner).get("/api/identity/devices").json()["data"]
    assert [(m["user_id"], m["count"]) for m in firm["members"]] == [("m1", 2)]
    assert _client(partner).get("/api/identity/users/x1/devices").status_code == 404, "a member of another firm is not found"


def test_an_executive_cannot_read_a_members_devices_but_reads_their_own(world):
    ex = _principal(uid="e1", role="Executive", session="s-e")
    assert _client(ex).get("/api/identity/users/m1/devices").status_code == 403
    assert _client(ex).get("/api/identity/devices").status_code == 403
    assert _client(ex).get("/api/identity/my-devices").status_code == 200


def test_sign_out_other_sessions_marks_the_person_keeps_this_session_and_closes_the_rest(world):
    users, _ = world
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    r = _client(_principal(session="s-office")).post("/api/identity/sign-out-other-sessions")
    assert r.status_code == 200 and r.json()["data"]["ended"] == 1
    row = users.rows["m1"]
    assert row["other_sessions_kept_session_id"] == "s-office" and row["other_sessions_revoked_at"]
    assert "sessions_revoked_at" not in row, "the mark that ends EVERY session (this one too) is not the one used"
    by = {r["session_id"]: r for r in ls._MOCK_ROWS}
    assert by["s-office"]["ended_at"] is None, "the session that asked stays"
    assert by["s-phone"]["ended_at"] and by["s-phone"]["ended_how"] == "other_sessions"
    left = _client(_principal(session="s-office")).get("/api/identity/my-devices").json()["data"]
    assert left["count"] == 1 and left["devices"][0]["is_current"] is True


def test_sign_out_other_sessions_refuses_in_words_when_the_token_names_no_session(world):
    users, _ = world
    r = _client(_principal(session=None)).post("/api/identity/sign-out-other-sessions")
    assert r.status_code == 409 and "does not say which session it is" in r.json()["detail"]
    assert "other_sessions_revoked_at" not in users.rows["m1"]


def test_suspending_or_forcing_out_a_member_closes_every_session_of_theirs(world):
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    r = _client(_principal(uid="p1", role="Partner", session="s-p")).post("/api/identity/users/m1/force-logout")
    assert r.status_code == 200
    assert {x["ended_how"] for x in ls._MOCK_ROWS} == {"forced"} and all(x["ended_at"] for x in ls._MOCK_ROWS)


def test_the_notice_is_written_with_the_privileged_client_because_the_recipient_is_somebody_else(world, monkeypatch):
    """Migration 084's policy lets only a Partner, or the recipient, write a notification. Written as the signing-in Manager, the notice
    to a Partner is refused by the database and the failure was swallowed: nobody was told. The real-Postgres test proves the refusal;
    this one holds that the write names the privileged client."""
    users, notices = world
    sentinel = object()
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_service_db", lambda: sentinel)
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    assert len(notices.sent) == 2 and all(c is sentinel for c in notices.clients)
    assert notices.read_with and all(c is sentinel for c in notices.read_with), "the 'already told?' read needs it too: a Manager's own client sees none of a Partner's rows"


def test_a_partners_own_second_device_tells_the_other_partners_and_not_themselves(world):
    users, notices = world
    _sign_in(_principal(uid="p1", role="Partner", session="s-office"))
    _sign_in(_principal(uid="p1", role="Partner", session="s-phone"), ua=SAFARI_IPHONE)
    assert [n["user_id"] for n in notices.sent] == ["p2"], "the member's own sessions are on their own Security page"


def test_the_register_answer_says_how_many_partners_were_actually_told(world, monkeypatch):
    users, notices = world
    out = svc.register(_principal(session="s-a"), "203.0.113.9", CHROME_WINDOWS)
    assert out["second_device"] is False
    out = svc.register(_principal(session="s-b"), "203.0.113.9", CHROME_WINDOWS)
    assert out["second_device"] is True and out["partners_told"] == 2


def test_my_devices_says_whether_this_device_is_on_the_list(world):
    _sign_in(_principal(session="s-office"))
    mine = _client(_principal(session="s-office")).get("/api/identity/my-devices").json()["data"]
    assert mine["this_device_listed"] is True and mine["can_keep_this_session"] is True
    # a session the server has not heard of (a sign-in whose record failed): the list leaves it out, and says so
    unheard = _client(_principal(session="s-unknown")).get("/api/identity/my-devices").json()["data"]
    assert unheard["this_device_listed"] is False and unheard["count"] == 1
    # a token that names no session cannot be listed at all
    nameless = _client(_principal(session=None)).get("/api/identity/my-devices").json()["data"]
    assert nameless["this_device_listed"] is False and nameless["can_keep_this_session"] is False


def test_a_read_of_the_devices_writes_nothing(world):
    users, notices = world
    _client(_principal(session="s-new")).get("/api/identity/my-devices")
    assert ls._MOCK_ROWS == [] and notices.sent == []


def test_a_member_who_keeps_signing_in_tells_each_partner_once_until_it_is_read(world):
    """A phone that signs itself out when idle and signs in again must not fill a Partner's bell: one unread notice per member."""
    users, notices = world
    _sign_in(_principal(session="s-office"))
    for n in range(4):
        _sign_in(_principal(session=f"s-phone-{n}"), ua=SAFARI_IPHONE)
    assert sorted(n["user_id"] for n in notices.sent) == ["p1", "p2"], "one each, however many times the second device signed in"
    for n in notices.sent:
        n["is_read"] = True
    _sign_in(_principal(session="s-phone-new"), ua=SAFARI_IPHONE)
    assert len(notices.sent) == 4, "once a notice is read, the next second device is told again"
    _sign_in(_principal(uid="m2", session="s-other-1"))
    _sign_in(_principal(uid="m2", session="s-other-2"))
    assert len(notices.sent) == 6, "another member is another notice"


def test_a_mark_that_could_not_be_written_is_a_503_in_words_and_ends_nothing(world, monkeypatch):
    users, _ = world
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-phone"), ua=SAFARI_IPHONE)
    monkeypatch.setattr(users, "update", lambda *a, **k: None)
    r = _client(_principal(session="s-office")).post("/api/identity/sign-out-other-sessions")
    assert r.status_code == 503 and "nothing was changed" in r.json()["detail"]
    assert all(row["ended_at"] is None for row in ls._MOCK_ROWS), "the rows are not closed when the mark was not written"


def test_no_answer_carries_the_sign_in_services_session_id(world):
    users, _ = world
    _sign_in(_principal(session="s-office"))
    _client(_principal(session="s-office")).post("/api/identity/sign-out-other-sessions")
    partner = _client(_principal(uid="p1", role="Partner", session="s-p"))
    for path in ("/api/identity/login-history", "/api/identity/users/m1/login-history", "/api/identity/users", "/api/identity/devices"):
        body = partner.get(path).text
        assert "s-office" not in body, f"{path} sent a session id"
        assert "other_sessions_kept_session_id" not in body and "other_sessions_revoked_at" not in body, path
    for path in ("/api/identity/users/m1/suspend", "/api/identity/users/m1/reactivate"):
        assert "s-office" not in partner.post(path).text, path


def test_a_session_that_ended_stays_ended_and_silent_when_it_announces_itself_again(world):
    users, notices = world
    _sign_in(_principal(session="s-office"))
    _sign_in(_principal(session="s-office"), event="logout")
    _sign_in(_principal(session="s-other"))
    notices.sent.clear()
    _client(_principal(session="s-office")).post("/api/identity/session-seen")
    by = {r["session_id"]: r for r in ls._MOCK_ROWS}
    assert by["s-office"]["ended_at"], "a late report from an ended session must not reopen it"
    assert notices.sent == []


def test_signing_out_the_others_drops_the_callers_cached_row(world, monkeypatch):
    import core.auth as auth
    users, _ = world
    auth._user_lookup_cache["a-m1"] = (0.0, {}, None)
    auth._user_lookup_cache["a-p1"] = (0.0, {}, None)
    _sign_in(_principal(session="s-office"))
    _client(_principal(session="s-office")).post("/api/identity/sign-out-other-sessions")
    assert "a-m1" not in auth._user_lookup_cache and "a-p1" in auth._user_lookup_cache
    auth._user_lookup_cache.clear()


def test_the_sign_in_record_is_tried_again_without_the_session_id_only_when_the_column_is_missing(monkeypatch):
    """A timeout may have committed the row: a second insert would write it twice. Only an undefined column is retried."""
    import repositories.login_events_repository as repo

    class Missing(Exception):
        code = "42703"

    class Timeout(Exception):
        code = "57014"

    def run(first_error):
        calls = []

        class Query:
            def insert(self, row):
                calls.append(dict(row))
                self.row = row
                return self

            def execute(self):
                if len(calls) == 1 and first_error is not None:
                    raise first_error
                return type("R", (), {"data": [self.row]})()

        class Db:
            def table(self, name):
                return Query()

        monkeypatch.setattr(repo, "_USE_MOCK", False)
        monkeypatch.setattr(repo, "_db", lambda: Db())
        repo.LoginEventsRepository().record("F1", "u1", "u@f", "login", ip="203.0.113.9", user_agent="x", session_id="sess")
        return calls

    calls = run(Missing("no such column"))
    assert len(calls) == 2 and "session_id" in calls[0] and "session_id" not in calls[1]
    calls = run(Timeout("canceling statement due to statement timeout"))
    assert len(calls) == 1, "a timeout is not retried: the first insert may have been written"
    assert len(run(None)) == 1


def test_a_closed_firm_and_a_reset_member_stop_being_listed_as_signed_in():
    import routers.platform as plat
    calls = []

    class Q:
        def __init__(self, name):
            self.name = name

        def update(self, change):
            calls.append((self.name, change))
            return self

        def eq(self, *_):
            return self

        def is_(self, *_):
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": 1}, {"id": 2}]})()

    class Db:
        def table(self, name):
            return Q(name)

    assert plat._end_sessions(Db(), "F1") == 2
    assert [name for name, _ in calls] == ["users", "login_sessions"]
    assert calls[1][1]["ended_how"] == "forced" and calls[1][1]["ended_at"]
    mfa = Path(plat.__file__).resolve().parents[1] / "services" / "mfa_reset_service.py"
    assert "login_devices_service.end_all(" in mfa.read_text(encoding="utf-8")


def test_a_closed_firm_session_rows_failure_does_not_stop_the_closure():
    """Before migration 765 is applied there is no such table: the stamp that ends the sessions must still go through."""
    import routers.platform as plat

    class Q:
        def __init__(self, name):
            self.name = name

        def update(self, change):
            return self

        def eq(self, *_):
            return self

        def is_(self, *_):
            return self

        def execute(self):
            if self.name == "login_sessions":
                raise RuntimeError('relation "login_sessions" does not exist')
            return type("R", (), {"data": [{"id": 1}]})()

    class Db:
        def table(self, name):
            return Q(name)

    assert plat._end_sessions(Db(), "F1") == 1


def test_a_failed_recording_never_blocks_the_sign_in(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database unreachable")
    monkeypatch.setattr(ls.login_sessions_repo, "register", boom)
    assert _sign_in(_principal(session="s-office")).status_code == 200
    assert le._MOCK_EVENTS and le._MOCK_EVENTS[0]["event"] == "login"


def test_a_failed_read_of_the_devices_is_a_503_in_words_and_not_none(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database unreachable")
    monkeypatch.setattr(ls.login_sessions_repo, "open_for_user", boom)
    r = _client(_principal(session="s-office")).get("/api/identity/my-devices")
    assert r.status_code == 503 and "could not be read" in r.json()["detail"]


# ── the auth dependency ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_user_row_is_read_again_without_the_new_columns_only_when_they_are_not_there_yet():
    """The API can be live a few minutes before the migration job has applied 765: that one answer (undefined column) must not lock
    everybody out, and any other failure must still be a failure."""
    import core.auth as auth

    class Undefined(Exception):
        code = "42703"

    class Other(Exception):
        code = "PGRST301"

    class Query:
        def __init__(self, outcomes, log):
            self.outcomes, self.log = outcomes, log

        def select(self, columns):
            self.log.append(columns)
            return self

        def eq(self, *_):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class Client:
        def __init__(self, outcomes):
            self.outcomes, self.log = outcomes, []

        def table(self, name):
            assert name == "users"
            return Query(self.outcomes, self.log)

    ok = type("R", (), {"data": {"id": "u"}})()
    client = Client([Undefined("column does not exist"), ok])
    assert auth._read_user_row(client, "a-1") is ok
    assert "other_sessions_revoked_at" in client.log[0] and "other_sessions_revoked_at" not in client.log[1]

    client = Client([Other("something else")])
    with pytest.raises(Other):
        auth._read_user_row(client, "a-1")
    assert len(client.log) == 1, "any other failure is not retried and not hidden"
