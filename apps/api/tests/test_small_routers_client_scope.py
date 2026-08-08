"""
Client-assignment scope on the small-router batch: reminders, engagements,
compliance_records, task_templates.

The tail of the "guards the body, not the record" list, taken together because
each is small enough that a phase apiece would be ceremony. What each needed:

  reminders (3)           one gap — PATCH /{id}/sent checked only the firm.
  engagements (7)         five gaps — every row-addressed endpoint was firm-only,
                          and update's destination-client check was firm-only.
  compliance_records (6)  already fully guarded (task #238); the list/get/create/
                          update guards were already tested elsewhere. The two
                          router guards nothing pinned — /firm/summary's
                          narrowing and /client/{id}/health — are pinned here.
  task_templates (6)      the firm-template pattern: five EXEMPT template routes
                          (firm_id nullable, no client_id — migration 063), and
                          /instantiate, the one route that names a client.
"""
import pytest
from fastapi import HTTPException

import routers.reminders as rm
import routers.engagements as eng
import routers.compliance_records as cr
import routers.task_templates as tt

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest. Patches BOTH core.authz and each
    router's module-level name: reminders and engagements.create import the
    guard inside the function body, which re-resolves from core.authz at call
    time, while the module-level guards bind at import."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr("core.authz.assert_client_access", _assert)
    monkeypatch.setattr("core.authz.can_access_client", _can)
    monkeypatch.setattr(eng, "can_access_client", _can)
    for mod in (eng, cr, tt):
        monkeypatch.setattr(mod, "assert_client_access", _assert)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# reminders — the one gap
# ══════════════════════════════════════════════════════════════════════════════

REMINDERS = {
    "REM-MINE": {"id": "REM-MINE", "firm_id": FIRM, "client_id": MINE,
                 "status": "pending"},
    "REM-THEIRS": {"id": "REM-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                   "status": "pending"},
}


@pytest.fixture
def reminders(monkeypatch):
    monkeypatch.setattr(rm.reminders_repo, "find_by_id",
                        lambda rid: REMINDERS.get(rid))
    written = []
    monkeypatch.setattr(rm.reminders_repo, "update",
                        lambda rid, u: written.append(rid) or {**REMINDERS[rid], **u})
    return written


def test_marking_another_clients_reminder_sent_is_refused(deny, reminders):
    with pytest.raises(HTTPException) as e:
        rm.mark_reminder_sent("REM-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert reminders == [], "the reminder was updated despite the refusal"


def test_marking_your_own_reminder_sent_still_works(deny, reminders):
    out = rm.mark_reminder_sent("REM-MINE", current_user=USER)
    assert out["success"] is True
    assert reminders == ["REM-MINE"]


def test_an_unknown_reminder_and_a_hidden_one_are_the_same_404(deny, reminders):
    with pytest.raises(HTTPException) as missing:
        rm.mark_reminder_sent("REM-NOPE", current_user=USER)
    with pytest.raises(HTTPException) as hidden:
        rm.mark_reminder_sent("REM-THEIRS", current_user=USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail


def test_creating_a_reminder_for_another_client_is_refused(deny, monkeypatch):
    created = []
    monkeypatch.setattr(rm.reminders_repo, "create",
                        lambda d: created.append(d) or d)
    with pytest.raises(HTTPException):
        rm.create_reminder_endpoint(
            rm.ReminderCreate(client_id=THEIRS, reminder_type="gst_due",
                              scheduled_for="2026-09-01"),
            current_user=USER)
    assert created == []


# ══════════════════════════════════════════════════════════════════════════════
# engagements — every row-addressed endpoint, and both ends of a move
# ══════════════════════════════════════════════════════════════════════════════

ENGAGEMENTS = {
    "E-MINE": {"id": "E-MINE", "firm_id": FIRM, "client_id": MINE,
               "status": "Active", "service_type": "GST Filing"},
    "E-THEIRS": {"id": "E-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                 "status": "Active", "service_type": "Audit"},
    "E-ALIEN": {"id": "E-ALIEN", "firm_id": "firm-2", "client_id": "c-x",
                "status": "Active", "service_type": "Audit"},
}


@pytest.fixture
def engagements(monkeypatch):
    monkeypatch.setattr(eng.engagement_repo, "find_by_id",
                        lambda eid: ENGAGEMENTS.get(eid))
    written = []
    monkeypatch.setattr(eng.engagement_repo, "update",
                        lambda eid, u: written.append(eid) or {**ENGAGEMENTS[eid], **u})
    return written


@pytest.mark.parametrize("call", [
    lambda: eng.get_engagement("E-THEIRS", current_user=USER),
    lambda: eng.update_engagement("E-THEIRS", eng.EngagementUpdate(notes="x"),
                                  current_user=USER),
    lambda: eng.delete_engagement("E-THEIRS", current_user=USER),
    lambda: eng.transition_engagement("E-THEIRS",
                                      eng.EngagementTransition(status="In Progress"),
                                      current_user=USER),
], ids=["get", "update", "delete", "transition"])
def test_every_row_endpoint_refuses_another_clients_engagement(call, deny,
                                                               engagements):
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 404
    assert e.value.detail == "Engagement not found", \
        "a distinct refusal message is an oracle for which ids exist"
    assert engagements == [], "the engagement was written despite the refusal"


def test_generating_obligations_for_another_clients_engagement_is_refused(
        deny, engagements, monkeypatch):
    """This one WRITES draft statutory obligations into the client's
    compliance records — the heaviest consequence in the router."""
    ran = []
    monkeypatch.setattr("services.compliance_obligation_service.generate_for_engagement",
                        lambda *a, **k: ran.append(a) or {})
    with pytest.raises(HTTPException) as e:
        eng.generate_engagement_obligations("E-THEIRS", financial_year="2025-26",
                                            current_user=USER)
    assert e.value.status_code == 404
    assert ran == [], "obligations were generated despite the refusal"


def test_another_firms_engagement_never_reaches_the_client_guard(deny, engagements):
    """Tenancy first: the firm check and the client check share one 404, and a
    foreign firm's row must be refused without its client ever being looked at."""
    with pytest.raises(HTTPException) as e:
        eng.get_engagement("E-ALIEN", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_your_own_engagement_still_reads_and_transitions(deny, engagements,
                                                         monkeypatch):
    out = eng.get_engagement("E-MINE", current_user=USER)
    assert out["data"]["engagement"]["id"] == "E-MINE"
    out = eng.transition_engagement("E-MINE",
                                    eng.EngagementTransition(status="In Progress"),
                                    current_user=USER)
    assert out["success"] is True
    assert engagements == ["E-MINE"]


def test_moving_an_engagement_to_a_client_you_are_not_on_is_refused(deny,
                                                                    engagements,
                                                                    monkeypatch):
    """Both ends. The engagement is mine; the DESTINATION is not. The old check
    only verified the destination belonged to the firm."""
    monkeypatch.setattr(eng.client_repo, "find_by_id",
                        lambda cid, *a, **k: {"id": cid, "firm_id": FIRM})
    with pytest.raises(HTTPException) as e:
        eng.update_engagement("E-MINE", eng.EngagementUpdate(client_id=THEIRS),
                              current_user=USER)
    assert e.value.status_code == 404
    assert deny == [MINE, THEIRS], "the destination client was never checked"
    assert engagements == []


def test_moving_between_your_own_clients_still_works(deny, engagements, monkeypatch):
    monkeypatch.setattr(eng.client_repo, "find_by_id",
                        lambda cid, *a, **k: {"id": cid, "firm_id": FIRM})
    out = eng.update_engagement("E-MINE",
                                eng.EngagementUpdate(client_id="client-also-mine"),
                                current_user=USER)
    assert out["success"] is True
    assert engagements == ["E-MINE"]


def test_creating_an_engagement_for_another_client_is_refused(deny, monkeypatch):
    created = []
    monkeypatch.setattr(eng.engagement_repo, "create",
                        lambda d: created.append(d) or d)
    with pytest.raises(HTTPException):
        eng.create_engagement(
            eng.EngagementCreate(client_id=THEIRS, service_type="Audit",
                                 fee_paise=100000, billing_cycle="Monthly",
                                 start_date="2026-04-01"),
            current_user=USER)
    assert created == []


# ══════════════════════════════════════════════════════════════════════════════
# compliance_records — the two guards nothing pinned
# ══════════════════════════════════════════════════════════════════════════════

def test_the_firm_summary_is_narrowed_to_the_callers_clients(monkeypatch):
    """/firm/summary hands effective_client_ids into the service (the F2 fix).
    The list/get/create/update guards are pinned in test_audit_remediation_5_1a
    and test_r238; this one and /health had no router-level test."""
    captured = {}
    monkeypatch.setattr(cr.compliance_record_service, "get_firm_summary",
                        lambda firm_id, allowed_client_ids: captured.update(
                            {"firm": firm_id, "allowed": allowed_client_ids}) or {})
    monkeypatch.setattr(cr, "effective_client_ids", lambda _u: {MINE})
    cr.get_firm_summary(current_user=USER)
    assert captured == {"firm": FIRM, "allowed": {MINE}}


def test_the_firm_summary_stays_unscoped_for_a_firmwide_role(monkeypatch):
    captured = {}
    monkeypatch.setattr(cr.compliance_record_service, "get_firm_summary",
                        lambda firm_id, allowed_client_ids: captured.update(
                            {"allowed": allowed_client_ids}) or {})
    monkeypatch.setattr(cr, "effective_client_ids", lambda _u: None)
    cr.get_firm_summary(current_user={"id": "p", "firm_id": FIRM, "role": "Partner"})
    assert captured == {"allowed": None}


def test_another_clients_health_score_is_refused(deny, monkeypatch):
    reached = []
    monkeypatch.setattr(cr.compliance_record_service, "get_client_health_score",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException) as e:
        cr.get_client_health(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert reached == []


def test_your_own_clients_health_score_still_loads(deny, monkeypatch):
    monkeypatch.setattr(cr.compliance_record_service, "get_client_health_score",
                        lambda *a, **k: {"score": 87})
    out = cr.get_client_health(MINE, current_user=USER)
    assert out["data"] == {"score": 87}


# ══════════════════════════════════════════════════════════════════════════════
# task_templates — the exemption's edge is /instantiate
# ══════════════════════════════════════════════════════════════════════════════

def test_instantiating_a_template_into_another_clients_book_is_refused(deny,
                                                                       monkeypatch):
    """The template is firm property; the TASK it creates lands in a named
    client's book. The guard runs before the template is even loaded."""
    loaded = []
    monkeypatch.setattr(tt.task_template_repo, "find_by_id",
                        lambda *a, **k: loaded.append(a) or {"name": "T"})
    with pytest.raises(HTTPException) as e:
        tt.instantiate_template("TPL-1",
                                tt.InstantiateRequest(client_id=THEIRS),
                                current_user=USER)
    assert e.value.status_code == 404
    assert loaded == [], "the template was loaded despite the refusal"


def test_the_template_register_is_not_client_scoped(deny, monkeypatch):
    """Over-guarding is a real failure mode: templates are the firm's reusable
    task definitions (firm_id nullable, no client_id — migration 063), the same
    pattern as engagement and workflow templates. This fails if somebody
    'fixes' the exemption."""
    monkeypatch.setattr(tt.task_template_repo, "find_all",
                        lambda firm_id: [{"id": "TPL-1", "name": "T"}])
    out = tt.list_templates(current_user=USER)
    assert out["data"]["total"] == 1
    assert deny == [], "the template list asked about a client"
