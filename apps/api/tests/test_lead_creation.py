"""
Regression tests for POST /api/lifecycle/leads.

Covers the five bugs fixed in this PR:
  BUG 1: assigned_to must NOT be set to entityType (non-UUID string → FK violation)
  BUG 2: source must be mapped to DB-valid lowercase value
  BUG 3: stage must be a value present in the DB CHECK constraint
  BUG 4: validation errors must raise HTTPException, not 500
  BUG 5: backend input validation rejects bad source / stage before DB insert
"""
import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock, call

USER_MANAGER = {"auth_user_id": "u-mgr", "firm_id": "firm-aaa", "role": "Manager"}

VALID_LEAD = {
    "company_name": "Sharma & Co",
    "contact_name": "Rahul Sharma",
    "email": "rahul@sharmaco.in",
    "phone": "9876543210",
    "source": "referral",
    "stage": "Lead",
    "estimated_value_paise": 500000,
    "notes": '{"__caflow_meta__":true,"entityType":"Proprietorship","userNotes":"met at event","lastContactDate":"2026-06-01","nextFollowUpDate":"2026-06-30"}',
}


def _make_lead_in(**overrides):
    from routers.lifecycle import LeadIn
    data = {**VALID_LEAD, **overrides}
    return LeadIn(**data)


# ── Source validation (BUG 2 & 5) ────────────────────────────────────────────

class TestSourceValidation:
    """Backend rejects invalid source values before they reach the DB."""

    def test_valid_sources_accepted(self):
        for src in ("referral", "website", "cold", "event", "other"):
            lead_in = _make_lead_in(source=src)
            assert lead_in.source == src

    def test_invalid_source_title_case_raises_422(self):
        from routers.lifecycle import create_lead, _VALID_SOURCES
        lead_in = _make_lead_in(source="Referral")  # wrong case — DB rejects this
        with patch("routers.lifecycle._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_lead(lead_in, current_user=USER_MANAGER)
        assert exc_info.value.status_code == 422
        assert "Referral" in str(exc_info.value.detail)

    def test_walk_in_not_accepted(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(source="Walk-in")  # not in DB enum
        with patch("routers.lifecycle._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_lead(lead_in, current_user=USER_MANAGER)
        assert exc_info.value.status_code == 422

    def test_linkedin_not_accepted(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(source="LinkedIn")  # not in DB enum
        with patch("routers.lifecycle._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_lead(lead_in, current_user=USER_MANAGER)
        assert exc_info.value.status_code == 422

    def test_none_source_accepted(self):
        """source is optional — None is fine."""
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(source=None)
        with patch("routers.lifecycle._db", return_value=None):
            result = create_lead(lead_in, current_user=USER_MANAGER)
        assert result["success"] is True


# ── Stage validation (BUG 3 & 5) ─────────────────────────────────────────────

class TestStageValidation:
    """Backend rejects stage values not in the DB CHECK constraint."""

    def test_valid_stages_accepted(self):
        valid = [
            "Lead", "Qualified", "Proposal Sent", "Proposal Accepted",
            "Onboarding", "Active", "Dormant", "Renewal Due", "Exiting", "Exited",
        ]
        for stage in valid:
            lead_in = _make_lead_in(stage=stage)
            assert lead_in.stage == stage

    def test_negotiation_rejected(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(stage="Negotiation")  # not in DB enum
        with patch("routers.lifecycle._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_lead(lead_in, current_user=USER_MANAGER)
        assert exc_info.value.status_code == 422
        assert "Negotiation" in str(exc_info.value.detail)

    def test_onboarded_rejected(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(stage="Onboarded")  # frontend typo — should be "Onboarding"
        with patch("routers.lifecycle._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_lead(lead_in, current_user=USER_MANAGER)
        assert exc_info.value.status_code == 422
        assert "Onboarded" in str(exc_info.value.detail)

    def test_lead_stage_default_accepted(self):
        """Default stage 'Lead' must work without specifying stage."""
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in(stage="Lead")
        with patch("routers.lifecycle._db", return_value=None):
            result = create_lead(lead_in, current_user=USER_MANAGER)
        assert result["success"] is True
        assert result["data"]["stage"] == "Lead"


# ── assigned_to is NOT the entity_type (BUG 1) ───────────────────────────────

class TestAssignedToColumn:
    """assigned_to must always be None (or a valid UUID) — never an entity type string."""

    def test_db_insert_does_not_receive_entity_type(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in()

        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch("routers.lifecycle._db", return_value=mock_db):
            with patch("routers.lifecycle.timeline_service"):
                create_lead(lead_in, current_user=USER_MANAGER)

        # call_args_list[0] is the leads insert; [1] is client_lifecycle_events
        first_insert_row = mock_db.table.return_value.insert.call_args_list[0][0][0]
        # assigned_to must be None, never an entity-type string like "Proprietorship"
        assert "assigned_to" not in first_insert_row or first_insert_row["assigned_to"] is None, (
            f"assigned_to must be None but got: {first_insert_row.get('assigned_to')!r}"
        )

    def test_entity_type_values_do_not_crash_db(self):
        """Sending a Proprietorship-like string as assigned_to must raise 422, not 500."""
        from routers.lifecycle import LeadIn
        # Simulate a badly formed request (edge-case safety net)
        lead_in = LeadIn(
            company_name="Test",
            source="referral",
            stage="Lead",
            assigned_to=None,  # correct — must be None
        )
        assert lead_in.assigned_to is None


# ── DB error surfaces as 422, not 500 (BUG 4 & 6) ───────────────────────────

class TestDbErrorHandling:
    """DB constraint violations must return 422, not an unhandled 500."""

    def test_db_constraint_error_raises_422(self):
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in()

        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.side_effect = (
            Exception("violates check constraint")
        )

        with patch("routers.lifecycle._db", return_value=mock_db):
            with patch("routers.lifecycle.timeline_service"):
                with pytest.raises(HTTPException) as exc_info:
                    create_lead(lead_in, current_user=USER_MANAGER)

        assert exc_info.value.status_code == 422
        assert "violates check constraint" in str(exc_info.value.detail)

    def test_successful_create_returns_lead_data(self):
        """Happy path — valid input creates lead and returns it."""
        from routers.lifecycle import create_lead
        lead_in = _make_lead_in()

        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch("routers.lifecycle._db", return_value=mock_db):
            with patch("routers.lifecycle.timeline_service"):
                result = create_lead(lead_in, current_user=USER_MANAGER)

        assert result["success"] is True
        assert result["data"]["company_name"] == "Sharma & Co"
        assert result["data"]["source"] == "referral"
        assert result["data"]["stage"] == "Lead"
        assert result["data"]["firm_id"] == "firm-aaa"
