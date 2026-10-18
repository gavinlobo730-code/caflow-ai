"""A lost authenticator is reset through the approval engine, by a Partner who is not the person who asked (POST-A-006).

THE GAP
    MFA is TOTP only and enrolled in the browser. Nothing let anybody else take a lost authenticator away, so a Partner or
    Manager who lost a phone was locked out until someone with the sign-in service's own dashboard removed the factor.

WHAT IS HELD
    * who may ask: anyone for their OWN authenticator (a locked-out person is at the password level, which is all the
      create route needs), a Partner for anyone's, nobody else for another person's;
    * what is stored is what the SERVER resolved from the member's row, never the browser's name or e-mail, and a person
      of another firm is not found;
    * a reason is required, one request per person waits at a time, and a person with no sign-in has nothing to reset;
    * a request nobody could decide is refused when it is made, in words that say what to do (the only Partner cannot
      reset their own);
    * the asker cannot decide their own request, except the firm's only Partner resetting someone who is not a Partner;
      a request about your own authenticator is never decided by you;
    * approving removes every factor and revokes the person's sessions, and writes both the request's and the person's
      audit entries with the auth id as actor; a failure of the sign-in service leaves the request pending and a retry
      finishes the job; a request older than seven days is refused;
    * the sign-in service is driven for real: the REAL admin class over a stand-in HTTP transport, because the installed
      library builds its delete URL from a key its own type does not declare and validates the factor listing as an
      object while the service sends an array;
    * the review of 18-10-2026: asking for ANOTHER person's reset needs the asker's second factor; the decider is a Partner
      at the second factor; a request about you is never decided by you whoever asked; the asker must still be an active
      member (and a Partner, for a request about someone else) when it is decided; a suspended person is not reset; a
      pending request past its seven days does not block a new one and a long inbox does not hide a pending one; approving
      closes every other pending request for the same person; a partial failure is audited with how many were removed; a
      stamp that could not be written is not reported as revoked, and the member lookup cache is cleared.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import repositories.approval_repository as arepo
import services.approval_service as svc
import services.mfa_reset_service as mfa
import core.auth as core_auth
from core import auth_admin
from core.auth import get_current_user
from routers.approvals import router as approvals_router

FIRM = "F1"


def _member(uid, role, **kw):
    return {"id": uid, "firm_id": kw.pop("firm_id", FIRM), "role": role, "full_name": kw.pop("full_name", uid.upper()),
            "email": f"{uid}@f.in", "auth_user_id": kw.pop("auth_user_id", f"auth-{uid}"), "is_active": True, **kw}


class _Users:
    """Stands in for `user_repo`: the same questions, answered from rows, scoped by firm like the real one."""

    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}
        self.updates = []
        self.asked = []

    def find_by_id(self, id, *, firm_id):
        self.asked.append(id)
        row = self.rows.get(id)
        return row if row and row["firm_id"] == firm_id else None

    def find_all(self, firm_id=None, **_):
        return [r for r in self.rows.values() if r["firm_id"] == firm_id]

    def update(self, id, data, *, firm_id):
        assert self.find_by_id(id, firm_id=firm_id), "an update must name the firm"
        if getattr(self, "vanish", False):
            return None  # the row went between the lookup and the write
        self.updates.append((id, data))
        self.rows[id].update(data)
        return self.rows[id]


class _SignInService:
    """Stands in for the admin API: records what was asked and can be made to fail."""

    def __init__(self):
        self.calls, self.fail = [], False

    def __call__(self, auth_user_id):
        self.calls.append(auth_user_id)
        if self.fail:
            raise auth_admin.AuthAdminError("down", removed=getattr(self, "removed_before_failing", 0))
        return 1


@pytest.fixture
def world(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    audit = []
    for mod in (svc, mfa):
        monkeypatch.setattr(mod, "log_event", lambda *a, **k: audit.append({"a": a, "k": k}))
    users = _Users([
        _member("p1", "Partner"), _member("p2", "Partner"), _member("m1", "Manager"), _member("e1", "Executive"),
        _member("pending", "Manager", auth_user_id=None), _member("far", "Manager", firm_id="F2"),
    ])
    service = _SignInService()
    monkeypatch.setattr(mfa, "user_repo", users)
    monkeypatch.setattr(mfa.auth_admin, "remove_all_authenticators", service)
    yield users, service, audit
    arepo._MOCK_REQUESTS.clear()


def _who(users, uid):
    return {k: users.rows[uid][k] for k in ("id", "role", "email", "auth_user_id")} | {"firm_id": FIRM}


def _ask(users, asker, **payload):
    payload.setdefault("reason", "Dropped the phone in the river on Tuesday")
    return svc.create_request(FIRM, "mfa_reset", payload, _who(users, asker))


def _refused(call, code, *words):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == code, caught.value.detail
    for w in words:
        assert w in caught.value.detail, (w, caught.value.detail)


# ── who may ask, and what is stored ────────────────────────────────────────────────────────────────────

def test_a_partner_asks_for_a_member_and_the_server_writes_what_is_stored(world):
    users, _, audit = world
    row = _ask(users, "p1", user_id="m1", target_name="Somebody Else", target_email="x@evil.example")
    assert row["status"] == "pending" and row["request_type"] == "mfa_reset"
    assert row["payload"] == {"user_id": "m1", "target_name": "M1", "target_email": "m1@f.in",
                              "reason": "Dropped the phone in the river on Tuesday", "self_requested": False,
                              "asker_aal": None}
    assert row["summary"] == "Reset the authenticator app of M1 (m1@f.in)"
    assert "request_created" in [e["a"][3] for e in audit]


def test_a_locked_out_member_asks_for_their_own(world):
    users, _, _ = world
    row = _ask(users, "m1", **{"self": True})
    assert row["payload"]["user_id"] == "m1" and row["payload"]["self_requested"] is True
    assert row["summary"].endswith(", asked for by them")
    row2 = _ask(users, "e1", user_id="e1")
    assert row2["payload"]["self_requested"] is True


@pytest.mark.parametrize("asker, target", [("e1", "p1"), ("m1", "p1"), ("e1", "m1")])
def test_nobody_but_a_partner_asks_for_another_persons(world, asker, target):
    users, _, _ = world
    _refused(lambda: _ask(users, asker, user_id=target), 403, "Only a Partner")


def test_a_person_of_another_firm_is_not_found(world):
    users, _, _ = world
    _refused(lambda: _ask(users, "p1", user_id="far"), 404, "not a member")


def test_a_person_who_never_signed_in_has_nothing_to_reset(world):
    users, _, _ = world
    _refused(lambda: _ask(users, "p1", user_id="pending"), 409, "has not signed in yet")


@pytest.mark.parametrize("reason", [None, "", "   ", "lost"])
def test_a_reason_is_required(world, reason):
    users, _, _ = world
    _refused(lambda: _ask(users, "p1", user_id="m1", reason=reason), 422, "why")


def test_a_reason_is_bounded(world):
    users, _, _ = world
    _refused(lambda: _ask(users, "p1", user_id="m1", reason="x" * (mfa.REASON_MAX + 1)), 422, "under")


def test_the_request_has_to_name_somebody(world):
    users, _, _ = world
    _refused(lambda: _ask(users, "p1"), 422, "whose")
    _refused(lambda: _ask(users, "p1", user_id=None), 422, "whose")
    _refused(lambda: _ask(users, "p1", user_id=["m1"]), 422, "whose")


def test_a_self_flag_that_is_not_true_asks_for_nobody(world):
    """`"self": "yes"` is not the boolean, so it never silently becomes the asker's own."""
    users, _, _ = world
    _refused(lambda: _ask(users, "m1", **{"self": "yes"}), 422, "whose")


def test_one_request_per_person_waits_at_a_time(world):
    users, _, _ = world
    _ask(users, "p1", user_id="m1")
    _refused(lambda: _ask(users, "p2", user_id="m1"), 409, "already waiting")
    _refused(lambda: _ask(users, "m1", **{"self": True}), 409, "already waiting")


# ── a request nobody could decide is refused when it is made ──────────────────────────────────────────

def test_the_only_partner_cannot_ask_for_their_own(world):
    users, _, _ = world
    users.rows["p2"]["is_active"] = False
    _refused(lambda: _ask(users, "p1", **{"self": True}), 409, "only active Partner", "administers")


def test_an_inactive_or_unsigned_partner_does_not_count_as_someone_who_can_decide(world):
    users, _, _ = world
    users.rows["p2"]["auth_user_id"] = None
    _refused(lambda: _ask(users, "p1", **{"self": True}), 409, "only active Partner")


def test_the_only_partner_may_ask_for_a_member_and_decide_it_themselves(world):
    users, service, audit = world
    users.rows["p2"]["is_active"] = False
    row = _ask(users, "p1", user_id="m1")
    done = svc.approve(FIRM, row["id"], _who(users, "p1"))
    assert done["status"] == "approved" and service.calls == ["auth-m1"]
    approved = [e for e in audit if e["a"][3] == "approved"][0]["k"]["metadata"]
    assert approved["decided_by_the_asker"] is True


def test_the_only_partner_may_not_reset_another_partner_that_way(world):
    """Two Partners and nobody else: neither can decide a reset of the other (one is the asker, one the target)."""
    users, _, _ = world
    _refused(lambda: _ask(users, "p1", user_id="p2"), 409, "no other active Partner")


def test_a_member_cannot_ask_when_no_partner_could_decide(world):
    users, _, _ = world
    users.rows["p1"]["is_active"] = False
    users.rows["p2"]["is_active"] = False
    _refused(lambda: _ask(users, "m1", **{"self": True}), 409, "no other active Partner")


# ── who may decide ─────────────────────────────────────────────────────────────────────────────────────

def test_the_asker_cannot_decide_their_own_request_when_another_partner_exists(world):
    users, service, _ = world
    row = _ask(users, "p1", user_id="m1")
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p1")), 403, "different Partner")
    assert service.calls == [] and svc.get_request(FIRM, row["id"])["status"] == "pending"


def test_a_request_about_your_own_authenticator_is_never_decided_by_you(world):
    users, service, _ = world
    row = _ask(users, "p1", **{"self": True})
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p1")), 403, "your own authenticator")
    assert service.calls == []


def test_a_request_somebody_made_about_you_is_never_decided_by_you_even_though_you_did_not_make_it(world):
    """P2 asks for P1's reset: P1 may not decide it (it is about P1's own authenticator) and P2 may not either (P2 made it),
    so it needs a third Partner; and a request nobody could decide is refused when it is made."""
    users, service, _ = world
    _refused(lambda: _ask(users, "p2", user_id="p1"), 409, "no other active Partner")
    users.rows["p3"] = _member("p3", "Partner")
    row = _ask(users, "p2", user_id="p1")
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p1")), 403, "your own authenticator")
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 403, "different Partner")
    assert service.calls == []
    assert svc.approve(FIRM, row["id"], _who(users, "p3"))["status"] == "approved"
    assert service.calls == ["auth-p1"]


# ── what approving does ────────────────────────────────────────────────────────────────────────────────

def test_a_second_partner_approves_and_the_factors_go_and_the_sessions_end(world):
    users, service, audit = world
    row = _ask(users, "m1", **{"self": True})
    done = svc.approve(FIRM, row["id"], _who(users, "p2"))
    assert done["status"] == "approved" and done["decided_by"] == "p2"
    assert done["result"] == {"user_id": "m1", "factors_removed": 1, "sessions_revoked": True}
    assert service.calls == ["auth-m1"]
    assert users.updates and users.updates[0][0] == "m1" and "sessions_revoked_at" in users.updates[0][1]
    assert datetime.fromisoformat(users.rows["m1"]["sessions_revoked_at"]).tzinfo is not None
    actions = [(e["a"][1], e["a"][3]) for e in audit]
    assert ("approval_request", "request_created") in actions
    assert ("approval_request", "approved") in actions
    assert ("user", "mfa_reset") in actions


def test_both_audit_entries_name_the_decider_by_their_auth_id(world):
    users, _, audit = world
    row = _ask(users, "m1", **{"self": True})
    svc.approve(FIRM, row["id"], _who(users, "p2"))
    entries = [e for e in audit if e["a"][3] in ("approved", "mfa_reset")]
    assert len(entries) == 2
    for e in entries:
        assert e["k"]["actor_id"] == "auth-p2", "audit_log.actor_id takes the AUTH id, not the users.id"
        assert e["k"]["metadata"]["target_user_id"] == "m1"
        assert e["k"]["metadata"]["factors_removed"] == 1
        assert e["k"]["metadata"]["asked_by_the_target"] is True
        assert e["k"]["metadata"]["decided_by_the_asker"] is False
    user_event = [e for e in entries if e["a"][1] == "user"][0]
    assert user_event["a"][2] == "m1", "the person's own history is keyed on their users.id"


def test_a_rejected_request_removes_nothing(world):
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    svc.reject(FIRM, row["id"], _who(users, "p2"), reason="Spoke to them: they found it")
    assert service.calls == [] and users.updates == []
    assert svc.get_request(FIRM, row["id"])["status"] == "rejected"


def test_a_sign_in_service_failure_leaves_the_request_pending_and_a_retry_finishes(world):
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    service.fail = True
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 503, "still waiting")
    assert svc.get_request(FIRM, row["id"])["status"] == "pending"
    assert users.updates == [], "the sessions were revoked although the authenticator was not removed"
    service.fail = False
    assert svc.approve(FIRM, row["id"], _who(users, "p2"))["status"] == "approved"
    assert users.updates and "sessions_revoked_at" in users.updates[0][1]


def test_a_request_about_a_person_who_has_gone_is_refused_in_words_and_stays_rejectable(world):
    users, service, _ = world
    row = _ask(users, "p1", user_id="m1")
    del users.rows["m1"]
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "Reject this request")
    assert service.calls == [] and svc.get_request(FIRM, row["id"])["status"] == "pending"
    assert svc.reject(FIRM, row["id"], _who(users, "p2"))["status"] == "rejected"


@pytest.mark.parametrize("stored", [{}, {"user_id": ""}, {"user_id": "  "}, {"user_id": None}, {"user_id": 7}])
def test_a_stored_request_that_names_nobody_is_refused_in_words_and_asks_the_database_nothing(world, stored):
    """A stored row is only as good as what wrote it; an empty or non-text id never reaches a uuid column."""
    users, service, _ = world
    for decider in ("p2", "p1"):
        row = arepo.approval_repo.create({"firm_id": FIRM, "request_type": "mfa_reset", "payload": stored,
                                          "summary": "x", "status": "pending", "requested_by": "p1"})
        users.asked.clear()
        _refused(lambda rid=row["id"], who=decider: svc.approve(FIRM, rid, _who(users, who)), 409, "Reject this request")
        assert users.asked == [], f"the database was asked about {users.asked!r}"
        assert service.calls == [] and svc.get_request(FIRM, row["id"])["status"] == "pending"


def test_a_stale_request_is_refused_and_a_fresh_one_is_not(world):
    users, service, _ = world
    stale = _ask(users, "m1", **{"self": True})
    stale["created_at"] = (datetime.now(timezone.utc) - mfa.VALID_FOR - timedelta(minutes=1)).isoformat()
    _refused(lambda: svc.approve(FIRM, stale["id"], _who(users, "p2")), 409, "more than seven days")
    assert service.calls == []
    stale["created_at"] = (datetime.now(timezone.utc) - mfa.VALID_FOR + timedelta(hours=1)).isoformat()
    assert svc.approve(FIRM, stale["id"], _who(users, "p2"))["status"] == "approved"


def test_a_naive_or_unreadable_creation_stamp_does_not_block_a_decision(world):
    """The stamp comes from the database; an odd one must not lock a Partner out of an approval."""
    users, _, _ = world
    row = _ask(users, "m1", **{"self": True})
    row["created_at"] = "not a date"
    assert svc.approve(FIRM, row["id"], _who(users, "p2"))["status"] == "approved"


# ── the door: the router ───────────────────────────────────────────────────────────────────────────────

def _client(user):
    app = FastAPI()
    app.include_router(approvals_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_lets_a_password_level_member_ask_and_only_a_partner_decide(world):
    users, service, _ = world
    asked = _client(_who(users, "m1")).post("/api/approvals", json={
        "request_type": "mfa_reset", "payload": {"self": True, "reason": "Phone fell in the river"}})
    assert asked.status_code == 200, asked.text
    rid = asked.json()["data"]["id"]
    assert _client(_who(users, "m1")).post(f"/api/approvals/{rid}/approve").status_code == 403
    assert service.calls == []
    assert "mfa_reset" in _client(_who(users, "p1")).get("/api/approvals/types").json()["data"]["request_types"]


def test_the_route_answers_a_refusal_with_its_sentence(world):
    users, _, _ = world
    r = _client(_who(users, "e1")).post("/api/approvals", json={
        "request_type": "mfa_reset", "payload": {"user_id": "p1", "reason": "They asked me to"}})
    assert r.status_code == 403 and "Only a Partner" in r.json()["detail"]


# ── what the review of 18-10-2026 found, held ───────────────────────────────────────────────────────────

@pytest.fixture
def mfa_on(monkeypatch):
    """REQUIRE_MFA on, as in production: the service then asks for the second factor itself."""
    monkeypatch.setattr(mfa, "require_mfa", lambda: True)


def _at(users, uid, aal):
    return {**_who(users, uid), "aal": aal}


def test_asking_for_another_persons_reset_needs_the_askers_second_factor(world, mfa_on):
    users, _, _ = world
    _refused(lambda: svc.create_request(FIRM, "mfa_reset", {"user_id": "m1", "reason": "Dropped the phone in the river"},
                                        _at(users, "p1", "aal1")), 403, "second factor")
    row = svc.create_request(FIRM, "mfa_reset", {"user_id": "m1", "reason": "Dropped the phone in the river"}, _at(users, "p1", "aal2"))
    assert row["payload"]["asker_aal"] == "aal2"


def test_asking_for_your_own_stays_at_the_password_level(world, mfa_on):
    """A locked-out person has nothing stronger, and the stored payload says how the request was made."""
    users, _, _ = world
    row = svc.create_request(FIRM, "mfa_reset", {"self": True, "reason": "Dropped the phone in the river"}, _at(users, "m1", "aal1"))
    assert row["payload"]["self_requested"] is True and row["payload"]["asker_aal"] == "aal1"


def test_without_the_policy_on_asking_for_another_is_not_stopped_at_aal1(world):
    users, _, _ = world
    assert _ask(users, "p1", user_id="m1")["status"] == "pending"


def test_a_decider_who_is_not_a_partner_is_refused_even_with_the_approve_grant(world):
    """`approval:approve` can be granted to one person; that does not make them a Partner for this."""
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "e1")), 403, "Only a Partner")
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "m1")), 403, "Only a Partner")
    assert service.calls == [] and svc.get_request(FIRM, row["id"])["status"] == "pending"


def test_a_decider_needs_their_own_second_factor_whatever_their_role_is_spelt(world, mfa_on):
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    _refused(lambda: svc.approve(FIRM, row["id"], _at(users, "p2", "aal1")), 403, "second factor")
    legacy = {**_at(users, "p2", "aal1"), "role": "owner"}
    _refused(lambda: svc.approve(FIRM, row["id"], legacy), 403, "second factor")
    assert service.calls == []
    assert svc.approve(FIRM, row["id"], _at(users, "p2", "aal2"))["status"] == "approved"


def test_a_suspended_person_is_not_reset_when_asked_and_not_when_decided(world):
    users, service, _ = world
    users.rows["m1"]["is_active"] = False
    _refused(lambda: _ask(users, "p1", user_id="m1"), 409, "suspended")
    users.rows["m1"]["is_active"] = True
    row = _ask(users, "p1", user_id="m1")
    users.rows["m1"]["is_active"] = False
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "suspended since")
    assert service.calls == [] and svc.get_request(FIRM, row["id"])["status"] == "pending"


def test_the_person_who_asked_must_still_be_an_active_member_when_it_is_decided(world):
    users, service, _ = world
    row = _ask(users, "p1", user_id="m1")
    users.rows["p1"]["is_active"] = False
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "no longer an active member")
    users.rows["p1"]["is_active"] = True
    del users.rows["p1"]
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "no longer an active member")
    assert service.calls == []


def test_a_request_about_somebody_else_needs_its_asker_to_still_be_a_partner(world):
    users, service, _ = world
    row = _ask(users, "p1", user_id="m1")
    users.rows["p1"]["role"] = "Executive"
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "no longer a Partner")
    assert service.calls == []


def test_a_self_request_survives_the_asker_being_demoted_because_it_is_the_persons_own(world):
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    users.rows["m1"]["role"] = "Executive"
    assert svc.approve(FIRM, row["id"], _who(users, "p2"))["status"] == "approved"
    assert service.calls == ["auth-m1"]


def test_a_request_older_than_its_seven_days_does_not_block_a_new_one(world):
    users, _, _ = world
    old = _ask(users, "m1", **{"self": True})
    old["created_at"] = (datetime.now(timezone.utc) - mfa.VALID_FOR - timedelta(hours=1)).isoformat()
    again = _ask(users, "m1", **{"self": True})
    assert again["status"] == "pending" and again["id"] != old["id"]
    _refused(lambda: _ask(users, "m1", **{"self": True}), 409, "already waiting")


def test_a_long_inbox_does_not_hide_the_pending_request_for_a_person(world):
    """The duplicate check asks the database for THIS person's pending request; it does not read the firm's latest hundred."""
    users, _, _ = world
    _ask(users, "m1", **{"self": True})
    for i in range(130):
        arepo.approval_repo.create({"firm_id": FIRM, "request_type": "role_change", "payload": {"n": i},
                                    "summary": "x", "status": "pending", "requested_by": "e1"})
    _refused(lambda: _ask(users, "m1", **{"self": True}), 409, "already waiting")


def test_approving_closes_every_other_pending_reset_of_the_same_person(world):
    users, service, audit = world
    first = _ask(users, "m1", **{"self": True})
    # a duplicate that got past the one-per-person check (two requests at the same moment)
    twin = arepo.approval_repo.create({"firm_id": FIRM, "request_type": "mfa_reset", "status": "pending",
                                       "payload": dict(first["payload"]), "summary": first["summary"], "requested_by": "p1"})
    other_person = arepo.approval_repo.create({"firm_id": FIRM, "request_type": "mfa_reset", "status": "pending",
                                               "payload": {**first["payload"], "user_id": "e1"}, "summary": "x",
                                               "requested_by": "p1"})
    svc.approve(FIRM, first["id"], _who(users, "p2"))
    closed = svc.get_request(FIRM, twin["id"])
    assert closed["status"] == "rejected" and "another reset" in closed["reason"] and closed["decided_by"] == "p2"
    assert svc.get_request(FIRM, other_person["id"])["status"] == "pending", "another person's request must stay"
    assert service.calls == ["auth-m1"]


def test_a_partial_failure_is_audited_with_how_many_factors_were_already_gone(world):
    users, service, audit = world
    row = _ask(users, "m1", **{"self": True})
    service.fail, service.removed_before_failing = True, 1
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 503, "still waiting")
    failed = [e for e in audit if e["a"][3] == "mfa_reset_failed"]
    assert len(failed) == 1 and failed[0]["k"]["metadata"]["factors_removed_before_the_failure"] == 1
    assert failed[0]["a"][1] == "user" and failed[0]["a"][2] == "m1"


def test_a_stamp_that_could_not_be_written_is_not_reported_as_revoked(world):
    users, service, _ = world
    row = _ask(users, "m1", **{"self": True})
    users.vanish = True
    _refused(lambda: svc.approve(FIRM, row["id"], _who(users, "p2")), 409, "could not be marked")
    assert svc.get_request(FIRM, row["id"])["status"] == "pending" and svc.get_request(FIRM, row["id"])["result"] is None
    users.vanish = False
    assert svc.approve(FIRM, row["id"], _who(users, "p2"))["result"]["sessions_revoked"] is True


def test_the_members_lookup_cache_is_cleared_so_the_stamp_is_seen_at_once(world):
    users, _, _ = world
    core_auth._user_lookup_cache["auth-m1"] = (10 ** 12, {"id": "m1"}, None)
    core_auth._user_lookup_cache["auth-e1"] = (10 ** 12, {"id": "e1"}, None)
    row = _ask(users, "m1", **{"self": True})
    svc.approve(FIRM, row["id"], _who(users, "p2"))
    assert "auth-m1" not in core_auth._user_lookup_cache and "auth-e1" in core_auth._user_lookup_cache
    core_auth._user_lookup_cache.pop("auth-e1", None)


# ── the sign-in service, driven for real: the REAL admin class over a stand-in HTTP transport ───────────

import httpx  # noqa: E402
from gotrue import SyncGoTrueAdminAPI  # noqa: E402
from gotrue.errors import AuthRetryableError  # noqa: E402
from gotrue._sync.gotrue_base_api import SyncClient  # noqa: E402


class _Service:
    """Stands in for the sign-in service's HTTP layer and records every request the real admin class makes."""

    def __init__(self, factors, *, wrapped=False, delete_reply=b"", fail_on=None, listing=None):
        self.calls, self.fail_on, self.delete_reply = [], fail_on, delete_reply
        rows = [{"id": f, "factor_type": "totp", "status": "verified", "friendly_name": f} for f in factors]
        self.listing = listing if listing is not None else ({"factors": rows} if wrapped else rows)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if self.fail_on and request.url.path.endswith(self.fail_on):
            return httpx.Response(500, json={"msg": "boom"})
        if request.method == "GET":
            return httpx.Response(200, json=self.listing)
        return httpx.Response(200, content=self.delete_reply)


def _real_admin(monkeypatch, service):
    admin = SyncGoTrueAdminAPI(url="http://auth.invalid/auth/v1", headers={"Authorization": "Bearer service"},
                               http_client=SyncClient(transport=httpx.MockTransport(service)))
    client = type("C", (), {"auth": type("A", (), {"admin": admin})()})()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: client)
    return admin


def _paths(service):
    return [(m, p.split("/auth/v1/", 1)[1]) for m, p in service.calls]


def test_the_live_shape_a_bare_array_is_read_and_every_factor_is_deleted_by_its_own_id(monkeypatch):
    service = _Service(["f-a", "f-b"])
    _real_admin(monkeypatch, service)
    assert auth_admin.remove_all_authenticators("u-1") == 2
    assert _paths(service) == [("GET", "admin/users/u-1/factors"), ("DELETE", "admin/users/u-1/factors/f-a"),
                               ("DELETE", "admin/users/u-1/factors/f-b")]


def test_the_wrapped_shape_the_library_expects_is_read_too(monkeypatch):
    service = _Service(["f-a"], wrapped=True)
    _real_admin(monkeypatch, service)
    assert auth_admin.remove_all_authenticators("u-1") == 1


@pytest.mark.parametrize("reply", [b"", b"null", b'{"id": "f-a"}', b"not json at all"])
def test_a_removed_factor_is_judged_by_the_status_and_never_by_the_body(monkeypatch, reply):
    """The library would parse the delete reply as a model; a reply it did not expect must not turn a deleted factor into a failure."""
    service = _Service(["f-a"], delete_reply=reply)
    _real_admin(monkeypatch, service)
    assert auth_admin.remove_all_authenticators("u-1") == 1


@pytest.mark.parametrize("listing", [{"unexpected": []}, {"factors": "nope"}, "text", 7, [{"no_id": 1}], [{"id": ""}], ["f-a"]])
def test_a_listing_nobody_recognises_is_an_error_and_never_zero_factors(monkeypatch, listing):
    service = _Service([], listing=listing)
    _real_admin(monkeypatch, service)
    with pytest.raises(auth_admin.AuthAdminError):
        auth_admin.remove_all_authenticators("u-1")
    assert [m for m, _ in service.calls] == ["GET"], "nothing is deleted from a listing that was not understood"


def test_negative_control_the_librarys_own_listing_parser_rejects_the_bare_array_the_service_sends(monkeypatch):
    """Why the listing is read here and not by the library: this is the call the first version made."""
    admin = _real_admin(monkeypatch, _Service(["f-a"]))
    with pytest.raises(AuthRetryableError, match="validation error"):  # it validates the reply as {"factors": [...]}
        admin.mfa.list_factors({"user_id": "u-1"})


def test_negative_control_the_documented_parameter_name_alone_builds_a_url_for_nothing(monkeypatch):
    """Why the delete is built here and not by the library: with only `id`, as its type declares, the URL ends in None."""
    service = _Service(["f-a"])
    admin = _real_admin(monkeypatch, service)
    try:
        admin.mfa.delete_factor({"user_id": "u-1", "id": "f-a"})
    except Exception:
        pass
    assert service.calls[-1][1].endswith("/factors/None")


def test_the_private_request_method_this_module_relies_on_is_still_there():
    """A library release that renames it must fail HERE, in words, and not at the first real approval."""
    import inspect
    names = set(inspect.signature(SyncGoTrueAdminAPI._request).parameters)
    assert {"method", "path", "no_resolve_json", "xform"} <= names


def test_a_person_with_no_factor_has_zero_removed(monkeypatch):
    service = _Service([])
    _real_admin(monkeypatch, service)
    assert auth_admin.remove_all_authenticators("u-1") == 0
    assert [m for m, _ in service.calls] == ["GET"]


def test_a_failure_part_way_says_how_many_were_removed_and_a_retry_removes_the_rest(monkeypatch):
    first = _Service(["f-a", "f-b"], fail_on="f-b")
    _real_admin(monkeypatch, first)
    with pytest.raises(auth_admin.AuthAdminError) as caught:
        auth_admin.remove_all_authenticators("u-1")
    assert caught.value.removed == 1 and caught.value.__cause__ is not None
    second = _Service(["f-b"])
    _real_admin(monkeypatch, second)
    assert auth_admin.remove_all_authenticators("u-1") == 1


def test_a_failure_to_list_removes_nothing_and_says_zero(monkeypatch):
    service = _Service(["f-a"], fail_on="factors")
    _real_admin(monkeypatch, service)
    with pytest.raises(auth_admin.AuthAdminError) as caught:
        auth_admin.remove_all_authenticators("u-1")
    assert caught.value.removed == 0 and [m for m, _ in service.calls] == ["GET"]


@pytest.mark.parametrize("bad", [None, "", 7])
def test_no_account_id_is_refused_before_anything_is_asked(bad):
    with pytest.raises(auth_admin.AuthAdminError):
        auth_admin.remove_all_authenticators(bad)


def test_an_unconfigured_service_is_an_auth_admin_error_not_a_crash(monkeypatch):
    import core.supabase_client as sc

    def _boom():
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
    monkeypatch.setattr(sc, "get_service_supabase", _boom)
    with pytest.raises(auth_admin.AuthAdminError):
        auth_admin.remove_all_authenticators("u-1")
