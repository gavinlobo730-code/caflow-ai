"""
Regression tests for the engagement rejection/deletion → lead-revert workflow.

When an engagement letter is rejected or soft-deleted, the linked lead must never
be orphaned mid-engagement: its stage is recomputed from the lead's remaining
LIVE letters, falling back to "Lead" so a fresh engagement can be drafted. CRM
data is preserved and no duplicate leads are created.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import routers.lifecycle as lc
import routers.engagement_letters as el
from routers.engagement_letters import (
    reject_engagement, delete_engagement, list_engagements, RejectIn,
)
from routers.lifecycle import revert_lead_after_engagement_closed

FIRM = "firm-aaa"
USER = {"auth_user_id": "u-mgr", "firm_id": FIRM, "role": "Manager", "email": "mgr@firm.in"}


@contextmanager
def mock_world(leads, engagements):
    with patch.object(lc, "_MOCK_LEADS", leads), \
         patch.object(el, "_MOCK_ENGAGEMENTS", engagements), \
         patch.object(el, "_MOCK_EVENTS", []), \
         patch.object(el, "_MOCK_TEMPLATES", []), \
         patch("routers.engagement_letters._db", return_value=None), \
         patch("routers.lifecycle._db", return_value=None), \
         patch("routers.lifecycle.timeline_service"), \
         patch("routers.engagement_letters.log_event"), \
         patch("routers.lifecycle.log_event"):
        yield


def _lead(stage="Engagement Sent", **o):
    b = {"id": "L1", "firm_id": FIRM, "stage": stage, "is_converted": False,
         "company_name": "Patel Foods", "email": "owner@patelfoods.in", "notes": "hot lead"}
    b.update(o)
    return b


def _eng(eid="E1", status="Sent", **o):
    b = {"id": eid, "firm_id": FIRM, "lead_id": "L1", "status": status, "is_deleted": False}
    b.update(o)
    return b


# ── reject reverts the lead ───────────────────────────────────────────────────

class TestRejectRevertsLead:

    def test_reject_returns_lead_to_lead_stage(self):
        lead = _lead("Engagement Sent")
        eng = _eng(status="Sent")
        with mock_world([lead], [eng]):
            res = reject_engagement("E1", RejectIn(), current_user=USER)
        assert res["success"] is True
        assert eng["status"] == "Rejected"
        assert lead["stage"] == "Lead"            # no longer orphaned
        # CRM data preserved; no duplicate lead created.
        assert lead["company_name"] == "Patel Foods"
        assert lead["notes"] == "hot lead"

    def test_reject_recomputes_to_other_live_engagement(self):
        # A second, still-live draft exists → lead drops to Engagement Drafted, not Lead.
        lead = _lead("Engagement Sent")
        e1 = _eng("E1", status="Sent")
        e2 = _eng("E2", status="Draft")
        with mock_world([lead], [e1, e2]):
            reject_engagement("E1", RejectIn(), current_user=USER)
        assert e1["status"] == "Rejected"
        assert lead["stage"] == "Engagement Drafted"

    def test_reject_does_not_pull_back_a_signed_lead(self):
        # Lead already Signed via E2; rejecting an older Sent E1 must not regress it.
        lead = _lead("Engagement Signed")
        e1 = _eng("E1", status="Sent")
        e2 = _eng("E2", status="Signed")
        with mock_world([lead], [e1, e2]):
            reject_engagement("E1", RejectIn(), current_user=USER)
        assert lead["stage"] == "Engagement Signed"

    def test_reject_does_not_touch_converted_lead(self):
        lead = _lead("Active", is_converted=True)
        eng = _eng(status="Sent")
        with mock_world([lead], [eng]):
            reject_engagement("E1", RejectIn(), current_user=USER)
        assert lead["stage"] == "Active"


# ── delete reverts the lead ───────────────────────────────────────────────────

class TestDeleteRevertsLead:

    def test_delete_draft_returns_lead_to_lead(self):
        lead = _lead("Engagement Drafted")
        eng = _eng(status="Draft")
        with mock_world([lead], [eng]):
            res = delete_engagement("E1", current_user=USER)
        assert res["success"] is True
        assert eng["is_deleted"] is True
        assert lead["stage"] == "Lead"

    def test_delete_excludes_letter_from_list(self):
        lead = _lead("Engagement Drafted")
        eng = _eng(status="Draft")
        with mock_world([lead], [eng]):
            delete_engagement("E1", current_user=USER)
            res = list_engagements(current_user=USER)
        assert res["data"]["total"] == 0

    def test_cannot_delete_a_signed_letter(self):
        from fastapi import HTTPException
        lead = _lead("Engagement Signed")
        eng = _eng(status="Signed")
        with mock_world([lead], [eng]):
            with pytest.raises(HTTPException) as exc:
                delete_engagement("E1", current_user=USER)
        assert exc.value.status_code == 409
        assert eng["is_deleted"] is False         # untouched
        assert lead["stage"] == "Engagement Signed"

    def test_delete_recomputes_to_remaining_live(self):
        lead = _lead("Engagement Sent")
        e1 = _eng("E1", status="Sent")
        e2 = _eng("E2", status="Draft")
        with mock_world([lead], [e1, e2]):
            delete_engagement("E1", current_user=USER)
        assert e1["is_deleted"] is True
        assert lead["stage"] == "Engagement Drafted"


# ── revert helper safety ──────────────────────────────────────────────────────

class TestRevertSafety:

    def test_missing_lead_does_not_raise(self):
        with mock_world([], []):
            assert revert_lead_after_engagement_closed("ghost", FIRM) is False

    def test_no_lead_id_is_noop(self):
        with mock_world([_lead()], []):
            assert revert_lead_after_engagement_closed(None, FIRM) is False

    def test_lead_not_in_engagement_phase_is_noop(self):
        # An Onboarding lead is never pulled back by an engagement closure.
        lead = _lead("Onboarding")
        with mock_world([lead], []):
            changed = revert_lead_after_engagement_closed("L1", FIRM)
        assert changed is False
        assert lead["stage"] == "Onboarding"

    def test_idempotent_when_stage_already_correct(self):
        # Lead at Engagement Drafted with a live Draft letter → no change, no error.
        lead = _lead("Engagement Drafted")
        eng = _eng(status="Draft")
        with mock_world([lead], [eng]):
            changed = revert_lead_after_engagement_closed("L1", FIRM)
        assert changed is False
        assert lead["stage"] == "Engagement Drafted"
