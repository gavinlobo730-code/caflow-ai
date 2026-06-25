"""
Regression tests for the Lead → Engagement → Client workflow integrity sprint.

Covers:
  • engagement create / send / sign auto-advance the linked lead's pipeline stage
  • rejected engagements do NOT advance the lead — they revert it (never orphaned)
  • advancement is forward-only (a new draft never regresses a signed lead)
  • converted / missing leads are never touched and never crash
  • multiple signed engagements → the most recently signed is authoritative
  • conversion populates fee_engagements from the REAL signed-letter data
  • every automatic stage change is audit-logged
"""
from contextlib import contextmanager
from unittest.mock import patch

import routers.lifecycle as lc
import routers.engagement_letters as el
from routers.lifecycle import convert_lead, LeadConvertIn, _pick_signed_engagement
from routers.engagement_letters import (
    create_engagement, send_engagement, sign_engagement, reject_engagement,
    EngagementIn, SignIn, RejectIn,
)

FIRM = "firm-aaa"
USER = {"auth_user_id": "u-mgr", "firm_id": FIRM, "role": "Manager", "email": "mgr@firm.in"}


@contextmanager
def mock_world(leads, engagements):
    """Patch both routers into mock mode with the given in-memory stores.
    Yields the lifecycle.log_event mock so audit assertions are possible."""
    with patch.object(lc, "_MOCK_LEADS", leads), \
         patch.object(el, "_MOCK_ENGAGEMENTS", engagements), \
         patch.object(el, "_MOCK_EVENTS", []), \
         patch.object(el, "_MOCK_TEMPLATES", []), \
         patch("routers.engagement_letters._db", return_value=None), \
         patch("routers.lifecycle._db", return_value=None), \
         patch("routers.lifecycle.timeline_service"), \
         patch("routers.engagement_letters.log_event"), \
         patch("routers.lifecycle.log_event") as mock_log:
        yield mock_log


def _lead(stage="Lead", **over):
    base = {"id": "L1", "firm_id": FIRM, "stage": stage, "is_converted": False}
    base.update(over)
    return base


def _eng(status="Draft", **over):
    base = {"id": "E1", "firm_id": FIRM, "lead_id": "L1", "status": status}
    base.update(over)
    return base


# ── Objective 1 & 2: engagement actions auto-advance the lead ─────────────────

class TestEngagementAdvancesLead:

    def test_create_advances_to_engagement_drafted(self):
        lead = _lead("Lead")
        with mock_world([lead], []):
            res = create_engagement(EngagementIn(title="GST FY26", lead_id="L1"), current_user=USER)
        assert res["success"] is True
        assert lead["stage"] == "Engagement Drafted"

    def test_send_advances_to_engagement_sent(self):
        lead = _lead("Engagement Drafted")
        eng = _eng("Draft")
        with mock_world([lead], [eng]):
            res = send_engagement("E1", current_user=USER)
        assert res["success"] is True
        assert eng["status"] == "Sent"
        assert lead["stage"] == "Engagement Sent"

    def test_sign_advances_to_engagement_signed(self):
        lead = _lead("Engagement Sent")
        eng = _eng("Sent")
        with mock_world([lead], [eng]):
            res = sign_engagement("E1", SignIn(), current_user=USER)
        assert res["success"] is True
        assert eng["status"] == "Signed"
        assert lead["stage"] == "Engagement Signed"

    def test_reject_does_not_advance_but_reverts(self):
        # Rejecting must never ADVANCE the lead; and (rejection workflow fix) it
        # now REVERTS the lead so it is not orphaned mid-engagement. With no other
        # live letter, the lead returns to "Lead" to be re-engaged.
        lead = _lead("Engagement Sent")
        eng = _eng("Sent")
        with mock_world([lead], [eng]):
            res = reject_engagement("E1", RejectIn(), current_user=USER)
        assert res["success"] is True
        assert eng["status"] == "Rejected"
        assert lead["stage"] == "Lead"


# ── Objective 2: safety — forward-only, converted, missing ────────────────────

class TestAdvanceSafety:

    def test_forward_only_does_not_regress_signed_lead(self):
        # A lead already at "Engagement Signed" must not be pulled back to
        # "Engagement Drafted" when a second draft is created.
        lead = _lead("Engagement Signed")
        with mock_world([lead], []):
            create_engagement(EngagementIn(title="Revised", lead_id="L1"), current_user=USER)
        assert lead["stage"] == "Engagement Signed"

    def test_converted_lead_is_never_advanced(self):
        lead = _lead("Active", is_converted=True)
        with mock_world([lead], []):
            create_engagement(EngagementIn(title="X", lead_id="L1"), current_user=USER)
        assert lead["stage"] == "Active"

    def test_missing_lead_does_not_crash(self):
        # lead_id points at a lead that does not exist — must not raise.
        with mock_world([], []):
            res = create_engagement(EngagementIn(title="X", lead_id="ghost"), current_user=USER)
        assert res["success"] is True

    def test_no_lead_id_is_noop(self):
        with mock_world([_lead()], []):
            res = create_engagement(EngagementIn(title="X"), current_user=USER)
        assert res["success"] is True


# ── Objective 8: audit logging of automatic stage changes ─────────────────────

class TestAutoStageChangeAudited:

    def test_sign_logs_automatic_stage_change(self):
        lead = _lead("Engagement Sent")
        eng = _eng("Sent")
        with mock_world([lead], [eng]) as mock_log:
            sign_engagement("E1", SignIn(), current_user=USER)
        assert lead["stage"] == "Engagement Signed"
        assert mock_log.called
        _, kwargs = mock_log.call_args
        assert kwargs.get("metadata", {}).get("automatic") is True
        assert kwargs.get("new_data", {}).get("stage") == "Engagement Signed"


# ── Objective 5: multiple signed engagement selection ─────────────────────────

class TestPickSignedEngagement:

    def test_latest_signed_wins(self):
        rows = [
            {"id": "old", "signed_at": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "new", "signed_at": "2026-03-01T00:00:00Z", "created_at": "2026-02-01T00:00:00Z"},
        ]
        assert _pick_signed_engagement(rows)["id"] == "new"

    def test_empty_returns_none(self):
        assert _pick_signed_engagement([]) is None

    def test_missing_signed_at_falls_back_to_created(self):
        rows = [
            {"id": "a", "signed_at": None, "created_at": "2026-01-01T00:00:00Z"},
            {"id": "b", "signed_at": None, "created_at": "2026-05-01T00:00:00Z"},
        ]
        assert _pick_signed_engagement(rows)["id"] == "b"


# ── FakeDB integration: convert_lead DB path (Objectives 3, 4, 5) ─────────────

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.t = table
        self._op = None
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        self.db.inserts.setdefault(self.t, []).append(payload)
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        self.db.updates.setdefault(self.t, []).append(payload)
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._op == "select":
            rows = self.db.selects.get(self.t, [])
            if self._single:
                return _FakeResult(rows[0] if rows else None)
            return _FakeResult(list(rows))
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            return _FakeResult(payload)
        if self._op == "update":
            return _FakeResult([self._payload])
        return _FakeResult(None)


class FakeDB:
    def __init__(self):
        self.selects = {}
        self.inserts = {}
        self.updates = {}

    def table(self, name):
        return _FakeQuery(self, name)


class TestConvertLeadIntegrity:

    def _base_db(self):
        db = FakeDB()
        db.selects["leads"] = [{
            "id": "L1", "firm_id": FIRM, "is_converted": False,
            "company_name": "Sharma & Co", "contact_name": "Rahul",
            "email": "r@x.in", "phone": "9", "stage": "Onboarding",
        }]
        db.selects["engagement_templates"] = [{"service_type": "GST Compliance"}]
        return db

    def _convert(self, db):
        with patch("routers.lifecycle._db", return_value=db), \
             patch("routers.lifecycle.timeline_service"), \
             patch("routers.lifecycle.log_event"):
            return convert_lead("L1", LeadConvertIn(create_onboarding=True), current_user=USER)

    def test_fee_engagement_uses_real_signed_data(self):
        db = self._base_db()
        db.selects["engagements"] = [{
            "id": "eng-new", "fee_amount_paise": 900000, "template_id": "tmpl-1",
            "title": "GST Compliance — FY26", "start_date": "2026-04-01",
            "engagement_number": "EL-2026-0002",
            "signed_at": "2026-03-01T00:00:00Z", "created_at": "2026-02-01T00:00:00Z",
        }]
        res = self._convert(db)
        assert res["success"] is True
        fe = db.inserts["fee_engagements"][0]
        assert fe["fee_paise"] == 900000              # real fee, not 0
        assert fe["service_type"] == "GST Compliance"  # from the template, not "General"
        assert "EL-2026-0002" in fe["notes"]           # traceable to the letter
        # lead marked converted
        assert any(u.get("is_converted") for u in db.updates["leads"])

    def test_multiple_signed_picks_latest_and_warns(self):
        db = self._base_db()
        db.selects["engagements"] = [
            {"id": "old", "fee_amount_paise": 100000, "template_id": None,
             "title": "Old terms", "start_date": "2026-01-01",
             "engagement_number": "EL-2026-0001",
             "signed_at": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "new", "fee_amount_paise": 500000, "template_id": None,
             "title": "Revised terms", "start_date": "2026-04-01",
             "engagement_number": "EL-2026-0002",
             "signed_at": "2026-03-01T00:00:00Z", "created_at": "2026-02-01T00:00:00Z"},
        ]
        res = self._convert(db)
        assert res["success"] is True
        fe = db.inserts["fee_engagements"][0]
        assert fe["fee_paise"] == 500000  # latest signed engagement's fee
        # no template → service_type falls back to the chosen letter's title
        assert fe["service_type"] == "Revised terms"
        warnings = res["data"]["warnings"]
        assert any("signed engagement letters exist" in w for w in warnings)

    def test_no_signed_engagement_blocks_conversion(self):
        import pytest
        from fastapi import HTTPException
        db = self._base_db()
        db.selects["engagements"] = []
        with pytest.raises(HTTPException) as exc:
            self._convert(db)
        assert exc.value.status_code == 409
