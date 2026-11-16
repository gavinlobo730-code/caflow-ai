"""A staff invitation is sent by the server, names the practice and the Partner, can be sent again, and its link
signs the invitee in for as long as the invitation lasts, without becoming anybody else's key (POST-A-445).

WHAT WAS WRONG. Invite Member created the row with a token and an expiry and handed the token back to the Partner's
browser, which asked Supabase to mail an ordinary sign-in link: it named neither the practice nor the Partner, it
lasted only as long as Supabase keeps a one-time code, and nothing could send it again. A lost or expired invitation
left a member who could not get in and a Partner who could not tell why (the owner, 15-11-2026).

WHAT THE INDEPENDENT REVIEW FOUND IN THE FIRST VERSION OF THE FIX. The join page turns a token into a sign-in, and the
token still came back on the team list (to anyone who may read the team) and on a role change, an activation and a
forced sign-out. A Manager could have joined as a pending Partner, and a stranger who founded a practice could have
invited somebody else's address, read the token back and signed in as that person's existing account. So the token is
kept as a hash, no row but `find_by_invite_token`'s carries it, the sign-in opens only for an invitation the server
mailed and never for an address that already has a sign-in, and a sign-in that already belongs to a practice cannot
accept a second one.

These run on the REAL repository in mock mode (its store swapped for an empty list), so the stripping and the hashing
they hold are the code's, not a fake's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import repositories.user_repository as user_repository
import routers.identity as idmod
import routers.team as team_router
from core.auth import get_current_user, get_jwt_user
from core.urls import frontend_base
from domain.firm.invite_token import stored_form
from middleware.public_rate_limit import reset as reset_public_limits
from services import email_service, practice_mail_service, staff_invite_service

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "gita@gupta-co.in",
           "full_name": "Gita Gupta", "auth_user_id": "auth-p"}
MANAGER = {"id": "m", "firm_id": "F1", "role": "Manager", "email": "m@gupta-co.in", "auth_user_id": "auth-m"}
OTHER_FIRMS_PARTNER = {**PARTNER, "id": "p2", "firm_id": "F2"}


@pytest.fixture()
def world(monkeypatch):
    rows: list[dict] = []
    issued: list[str] = []
    audit: list[tuple] = []
    mails: list[dict] = []
    monkeypatch.setattr(user_repository, "MOCK_TEAM_MEMBERS", rows)
    monkeypatch.setattr(idmod, "log_event", lambda *a, **k: audit.append((a[3], k)))
    monkeypatch.setattr(practice_mail_service, "practice_sender", lambda firm_id: ("Gupta & Co", "office@gupta-co.in"))

    def _issue():
        issued.append(f"tok-{len(issued) + 1:02d}-" + "z" * 36)
        return issued[-1]
    monkeypatch.setattr(staff_invite_service, "_new_token", _issue)

    def _send(to, **kwargs):
        mails.append({"to": to, **kwargs})
        return world.answer

    world = SimpleNamespace(rows=rows, issued=issued, audit=audit, mails=mails, answer=True)
    monkeypatch.setattr(email_service, "send_firm_invite", _send)
    reset_public_limits()
    yield world
    reset_public_limits()


def _client(user=PARTNER, jwt_user=None):
    app = FastAPI()
    app.include_router(idmod.router)
    app.include_router(idmod.invite_router)
    app.include_router(team_router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if jwt_user:
        app.dependency_overrides[get_jwt_user] = lambda: jwt_user
    return TestClient(app, raise_server_exceptions=False)


def _invite(email="new@hire.in", role="Manager"):
    r = _client().post("/api/identity/users", json={"full_name": "New Hire", "email": email, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _row(world, uid):
    return next(r for r in world.rows if r["id"] == uid)


def _accept(token, email="new@hire.in", auth="auth-new"):
    return _client(jwt_user={"auth_user_id": auth, "email": email}).post(
        "/api/identity/accept-invite", json={"token": token})


# ── the first invitation ─────────────────────────────────────────────────────

def test_inviting_sends_one_mail_naming_the_practice_and_the_partner_with_the_token_it_issued(world):
    made = _invite()
    stored = _row(world, made["id"])
    assert len(world.mails) == 1
    mail = world.mails[0]
    assert mail["to"] == "new@hire.in"
    assert mail["practice_name"] == "Gupta & Co" and mail["inviter_name"] == "Gita Gupta"
    assert mail["reply_to"] == "gita@gupta-co.in", "a reply reaches the Partner who invited"
    assert mail["role"] == "Manager"
    assert mail["invite_link"] == f"{frontend_base()}/join?token={world.issued[0]}"
    assert mail["valid_until"] == staff_invite_service.valid_until_words(stored["invite_expires_at"])


def test_only_the_tokens_hash_is_stored(world):
    made = _invite()
    stored = _row(world, made["id"])["invite_token"]
    assert stored == stored_form(world.issued[0]) and stored.startswith("sha256:")
    assert world.issued[0] not in stored


def test_the_answer_to_the_partner_carries_no_token_and_says_the_mail_went(world):
    made = _invite()
    assert "invite_token" not in made
    assert made["invite_mail"] == {"sent": True, "problem": None}
    assert made["member_state"] == "invited" and made["invite_expires_at"]


def test_the_invitation_lasts_seven_days(world):
    before = datetime.now(timezone.utc)
    made = _invite()
    expires = datetime.fromisoformat(_row(world, made["id"])["invite_expires_at"])
    assert timedelta(days=7) - timedelta(minutes=1) < expires - before <= timedelta(days=7, minutes=1)


def test_a_mail_the_service_refused_is_said_and_the_member_is_still_invited(world):
    world.answer = False
    made = _invite()
    assert made["invite_mail"] == {"sent": False, "problem": staff_invite_service.MAIL_NOT_SENT}
    assert made["member_state"] == "invited"


def test_a_mail_that_raised_is_said_as_not_sent_and_never_a_500(world, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("the mail service is down")
    monkeypatch.setattr(email_service, "send_firm_invite", _boom)
    made = _invite()
    assert made["invite_mail"]["sent"] is False


# ── the token is on no response ──────────────────────────────────────────────

def test_no_route_that_answers_with_a_member_carries_the_token_or_its_hash(world):
    """The review found it on the team list and on three identity answers: each is asked here, by its route."""
    made = _invite()
    uid = made["id"]
    answers = {
        "team list": _client().get("/api/team").json(),
        "team list (Manager)": _client(MANAGER).get("/api/team").json(),
        "identity list": _client().get("/api/identity/users").json(),
        "role change": _client().patch(f"/api/identity/users/{uid}/role", json={"role": "Manager"}).json(),
        "force sign-out": _client().post(f"/api/identity/users/{uid}/force-logout").json(),
        "resend": _client().post(f"/api/identity/users/{uid}/resend-invite").json(),
        "withdraw": _client().post(f"/api/identity/users/{uid}/suspend").json(),
        "activate": _client().post(f"/api/identity/users/{uid}/reactivate").json(),
    }
    secrets_seen = world.issued + [stored_form(t) for t in world.issued]
    for name, body in answers.items():
        text = str(body)
        assert "invite_token" not in text, f"the {name} answer names invite_token"
        for value in secrets_seen:
            assert value not in text, f"the {name} answer carries an invitation's token or its hash"


def test_the_repository_returns_the_token_only_through_find_by_invite_token(world):
    repo = user_repository.user_repo
    made = repo.create({"firm_id": "F1", "full_name": "R", "email": "r@hire.in", "role": "Executive",
                        "status": "invited", "is_active": True, "invite_token": stored_form("secret-r"),
                        "invite_expires_at": "2099-01-01T00:00:00+00:00"})
    uid = made["id"]
    for name, row in {
        "create": made,
        "find_by_id": repo.find_by_id(uid, firm_id="F1"),
        "find_by_email": repo.find_by_email("r@hire.in", firm_id="F1"),
        "update": repo.update(uid, {"role": "Manager"}, firm_id="F1"),
        **{f"find_all[{i}]": r for i, r in enumerate(repo.find_all(firm_id="F1"))},
    }.items():
        assert "invite_token" not in row, name
        assert row["invite_outstanding"] is True, f"{name} must still say an invitation is outstanding"
    assert repo.find_by_invite_token("secret-r")["invite_token"] == stored_form("secret-r")
    assert repo.find_by_invite_token(stored_form("secret-r")) is None, \
        "a stored hash presented as though it were the token opens nothing"


# ── sending it again ─────────────────────────────────────────────────────────

def test_resending_replaces_the_token_so_the_earlier_link_stops_working(world):
    made = _invite()
    again = _client().post(f"/api/identity/users/{made['id']}/resend-invite")
    assert again.status_code == 200, again.text
    first, second = world.issued
    assert _row(world, made["id"])["invite_token"] == stored_form(second)
    assert again.json()["data"]["invite_mail"] == {"sent": True, "problem": None}
    assert world.mails[-1]["invite_link"].endswith(f"?token={second}")
    assert world.audit[-1][0] == "invite_resent"
    assert _accept(first).status_code == 404, "the link in the earlier mail must stop working"
    assert _accept(second).status_code == 200


def test_a_resend_whose_mail_did_not_go_keeps_the_earlier_link(world):
    made = _invite()
    world.answer = False
    again = _client().post(f"/api/identity/users/{made['id']}/resend-invite").json()["data"]
    assert again["invite_mail"]["sent"] is False and again["invite_mail"]["kept_previous"] is True
    assert _row(world, made["id"])["invite_token"] == stored_form(world.issued[0])
    assert world.audit[-1][0] == "invite_resend_not_sent"
    assert _accept(world.issued[1]).status_code == 404, "the token of a mail that never went opens nothing"
    assert _accept(world.issued[0]).status_code == 200, "the earlier link still works"


def test_a_failed_resend_puts_back_only_an_invitation_whose_link_still_worked(world):
    """An expired invitation's link had already stopped working, so a resend whose mail fails keeps the fresh token
    and says the earlier link no longer works, never that it still does."""
    made = _invite()
    _row(world, made["id"])["invite_expires_at"] = "2020-01-01T00:00:00+00:00"
    world.answer = False
    again = _client().post(f"/api/identity/users/{made['id']}/resend-invite").json()["data"]
    assert again["invite_mail"]["kept_previous"] is False
    assert _row(world, made["id"])["invite_token"] == stored_form(world.issued[1])


def test_putting_an_invitation_back_writes_the_invitation_and_nothing_else(world):
    """The restore writes the two invitation columns by name: whatever else the dict it is handed carries (a role, a
    sign-in) is not written, and the database path names the same columns so the schema check can read them."""
    made = _invite()
    uid = made["id"]
    stored = _row(world, uid)["invite_token"]
    previous = {"invite_token": "earlier-hash", "invite_expires_at": "2030-01-01T00:00:00+00:00",
                "role": "Partner", "auth_user_id": "auth-intruder"}
    out = user_repository.user_repo.restore_invitation(uid, previous, replacing=stored, firm_id="F1")
    row = _row(world, uid)
    assert out is not None and row["invite_token"] == "earlier-hash"
    assert row["invite_expires_at"] == "2030-01-01T00:00:00+00:00"
    assert row["role"] == "Manager" and row.get("auth_user_id") is None


def test_a_failed_resend_never_undoes_a_withdraw_that_landed_while_the_mail_was_being_sent(world, monkeypatch):
    made = _invite()
    uid = made["id"]

    def _slow_failing_send(to, **kwargs):
        # Another Partner withdraws the invitation while this resend's mail is on its way, and the mail then fails.
        _client().post(f"/api/identity/users/{uid}/suspend")
        return False
    monkeypatch.setattr(email_service, "send_firm_invite", _slow_failing_send)
    again = _client().post(f"/api/identity/users/{uid}/resend-invite").json()["data"]
    assert again["invite_mail"]["kept_previous"] is False
    row = _row(world, uid)
    assert row["invite_token"] is None and row["is_active"] is False, "the withdrawal must stand"
    assert _accept(world.issued[0]).status_code == 404


def test_resending_an_expired_invitation_makes_it_live_for_another_seven_days(world):
    made = _invite()
    _row(world, made["id"])["invite_expires_at"] = "2020-01-01T00:00:00+00:00"
    again = _client().post(f"/api/identity/users/{made['id']}/resend-invite").json()["data"]
    assert again["member_state"] == "invited"
    expires = datetime.fromisoformat(_row(world, made["id"])["invite_expires_at"])
    assert expires > datetime.now(timezone.utc) + timedelta(days=6)


def test_resending_is_refused_in_words_for_a_member_who_joined_or_whose_invitation_was_withdrawn(world):
    joined = _invite(email="j@hire.in")
    _row(world, joined["id"]).update({"auth_user_id": "auth-j", "invite_token": None})
    r = _client().post(f"/api/identity/users/{joined['id']}/resend-invite")
    assert r.status_code == 409 and "already joined" in r.json()["detail"]

    withdrawn = _invite(email="w@hire.in")
    assert _client().post(f"/api/identity/users/{withdrawn['id']}/suspend").status_code == 200
    r = _client().post(f"/api/identity/users/{withdrawn['id']}/resend-invite")
    assert r.status_code == 409 and "withdrawn" in r.json()["detail"]
    assert len(world.mails) == 2, "a refused resend sends nothing"


def test_resending_is_a_partners_act_and_never_reaches_another_firm(world):
    made = _invite()
    assert _client(MANAGER).post(f"/api/identity/users/{made['id']}/resend-invite").status_code == 403
    assert _client(OTHER_FIRMS_PARTNER).post(f"/api/identity/users/{made['id']}/resend-invite").status_code == 404


def test_reactivating_a_withdrawn_invitation_then_resending_it_works(world):
    made = _invite()
    _client().post(f"/api/identity/users/{made['id']}/suspend")
    assert _client().post(f"/api/identity/users/{made['id']}/reactivate").status_code == 200
    r = _client().post(f"/api/identity/users/{made['id']}/resend-invite")
    assert r.status_code == 200 and r.json()["data"]["member_state"] == "invited"


# ── accepting ────────────────────────────────────────────────────────────────

def test_a_sign_in_that_already_belongs_to_a_practice_cannot_accept_a_second(world):
    """Two member rows on one sign-in lock its owner out of both practices (core/auth reads it with maybe_single)."""
    world.rows.append({"id": "elsewhere", "firm_id": "F9", "email": "new@hire.in", "auth_user_id": "auth-new",
                       "is_active": True, "status": "active"})
    _invite()
    r = _accept(world.issued[0])
    assert r.status_code == 409 and r.json()["detail"] == idmod.ALREADY_A_MEMBER
    assert sum(1 for row in world.rows if row.get("auth_user_id") == "auth-new") == 1


def test_an_invitation_stored_before_the_change_is_still_accepted_by_its_own_signed_in_address(world):
    world.rows.append({"id": "old", "firm_id": "F1", "email": "old@hire.in", "role": "Executive",
                       "status": "invited", "is_active": True, "auth_user_id": None,
                       "invite_token": "legacy-plain-token-" + "q" * 30,
                       "invite_expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()})
    assert _accept("legacy-plain-token-" + "q" * 30, email="old@hire.in", auth="auth-old").status_code == 200


# ── the sign-in the join page opens from the link ────────────────────────────

class _Admin:
    def __init__(self, invite_fails=None):
        self.calls: list[dict] = []
        self.invite_fails = invite_fails

    def generate_link(self, params):
        self.calls.append(dict(params))
        if params["type"] == "invite" and self.invite_fails:
            raise self.invite_fails
        return SimpleNamespace(properties=SimpleNamespace(hashed_token=f"th-{params['type']}",
                                                          verification_type=params["type"]))


class _AlreadyRegistered(Exception):
    code = "email_exists"


def _live_supabase(monkeypatch, admin):
    monkeypatch.setattr(staff_invite_service, "_USE_MOCK", False)
    monkeypatch.setattr(staff_invite_service.db_provider, "service_db",
                        lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)))


def _session(token):
    return _client().post("/api/identity/accept-invite/session", json={"token": token})


def test_a_live_invitation_opens_a_sign_in_for_its_own_address_only(world, monkeypatch):
    admin = _Admin()
    _live_supabase(monkeypatch, admin)
    _invite(email="New@Hire.in")
    r = _session(world.issued[0])
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"token_hash": "th-invite", "verification_type": "invite", "email": "New@Hire.in"}
    assert admin.calls == [{"type": "invite", "email": "New@Hire.in"}]


def test_an_address_that_already_signs_in_is_never_given_a_sign_in_and_is_told_to_sign_in_first(world, monkeypatch):
    """The review's account-takeover path: a link that could sign its holder in as an existing account would make
    whoever held the link that person, in whatever practice or portal the account belongs to."""
    _invite()
    admin = _Admin(invite_fails=_AlreadyRegistered("A user with this email address has already been registered"))
    _live_supabase(monkeypatch, admin)
    r = _session(world.issued[0])
    assert r.status_code == 409 and r.json()["detail"] == staff_invite_service.EXISTING_ACCOUNT
    assert [c["type"] for c in admin.calls] == ["invite"], "never retried as a magic link"


def test_a_supabase_that_answers_neither_way_is_a_503_in_words(world, monkeypatch):
    _invite()
    admin = _Admin(invite_fails=RuntimeError("Supabase Auth is unreachable"))
    _live_supabase(monkeypatch, admin)
    r = _session(world.issued[0])
    assert r.status_code == 503 and r.json()["detail"] == staff_invite_service.SIGN_IN_REFUSAL
    assert [c["type"] for c in admin.calls] == ["invite"]


@pytest.mark.parametrize("spoil", ["unknown", "expired", "withdrawn", "accepted", "stored-before-the-change",
                                   "the-hash-itself"])
def test_no_sign_in_opens_for_an_invitation_that_cannot_open_one_and_every_refusal_says_the_same(
        world, monkeypatch, spoil):
    admin = _Admin()
    _live_supabase(monkeypatch, admin)
    made = _invite()
    row = _row(world, made["id"])
    token = world.issued[0]
    if spoil == "unknown":
        token = "x" * 43
    elif spoil == "expired":
        row["invite_expires_at"] = "2020-01-01T00:00:00+00:00"
    elif spoil == "withdrawn":
        _client().post(f"/api/identity/users/{made['id']}/suspend")
    elif spoil == "accepted":
        row["auth_user_id"] = "auth-someone"
    elif spoil == "stored-before-the-change":
        row["invite_token"] = token  # the plain secret, as an invitation issued before POST-A-445 kept it
    elif spoil == "the-hash-itself":
        token = row["invite_token"]
    r = _session(token)
    assert r.status_code == 404 and r.json()["detail"] == "Invalid or expired invite."
    assert admin.calls == [], "Supabase is never asked for a sign-in for an invitation that cannot open one"


def test_asking_whose_invitation_it_is_opens_no_sign_in(world, monkeypatch):
    admin = _Admin()
    _live_supabase(monkeypatch, admin)
    _invite(email="New@Hire.in")
    r = _client().post("/api/identity/accept-invite/session",
                       json={"token": world.issued[0], "open_sign_in": False})
    assert r.status_code == 200 and r.json()["data"] == {"email": "New@Hire.in"}
    assert admin.calls == [], "merely looking must create nothing at Supabase"
    gone = _client().post("/api/identity/accept-invite/session", json={"token": "x" * 43, "open_sign_in": False})
    assert gone.status_code == 404, "the address of an invitation that cannot be used is not given out"


def test_opening_the_sign_in_does_not_use_the_invitation_up(world):
    _invite()
    token = world.issued[0]
    assert _session(token).status_code == 200
    assert _session(token).status_code == 200, "a second open of the link still works until it is accepted"
    assert _accept(token).status_code == 200
    assert _session(token).status_code == 404, "once accepted, the link opens nothing"


def test_the_sign_in_route_needs_no_login_and_is_rate_limited_per_address():
    import main
    from tests.test_every_public_route_is_rate_limited import _bucket_of
    route = next(r for r in main.app.routes if getattr(r, "path", "") == "/api/identity/accept-invite/session")
    assert _bucket_of(route) == "invite"
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/identity/accept-invite/session", json={"token": "y" * 43})
    assert r.status_code == 404, f"reachable with no login at all, and refuses an unknown token: {r.status_code}"


# ── what the mail says ───────────────────────────────────────────────────────

def test_the_expiry_is_worded_in_indias_time():
    assert staff_invite_service.valid_until_words("2026-11-22T18:48:00+00:00") == "23 November 2026, 12:18 am IST"
    assert staff_invite_service.valid_until_words("2026-11-23T07:30:00Z") == "23 November 2026, 1:00 pm IST"


def test_the_mail_escapes_what_was_typed_and_keeps_the_subject_on_one_line(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(email_service, "_send", lambda to, subject, html, **k: sent.append((subject, html, k)) or True)
    email_service.send_firm_invite("n@hire.in", practice_name="Gupta <script>x</script>",
                                   inviter_name="Gita\nBcc: evil@x.in", role="Manager",
                                   invite_link="https://app.test/join?token=a&b", valid_until="23 November 2026")
    subject, html, kwargs = sent[0]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "\n" not in subject
    assert "token=a&amp;b" in html
    assert "Gupta" in subject and "Gita" in subject
    assert kwargs["sender_name"] == "Gupta <script>x</script>", "from_header makes the display name safe itself"


def test_a_practice_or_partner_with_no_name_is_left_out_and_never_invented(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(email_service, "_send", lambda to, subject, html, **k: sent.append((subject, html)) or True)
    email_service.send_firm_invite("n@hire.in", practice_name=None, inviter_name=None, role="Executive",
                                   invite_link="https://app.test/join?token=a", valid_until="23 November 2026")
    subject, html = sent[0]
    assert subject == "You are invited to join a practice on PracticeSync AI"
    assert "You have been invited" in html and "ask the practice" in html
