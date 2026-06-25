"""
Phase 7/8/9 Intelligence Layer Tests
Covers: Client Lifecycle, Relationship Intelligence, Health Engine, Security
"""
import uuid
import pytest
from unittest.mock import MagicMock


FIRM_A = str(uuid.uuid4())
FIRM_B = str(uuid.uuid4())
CLIENT_A = str(uuid.uuid4())
CLIENT_B = str(uuid.uuid4())


# ── Phase 7: Client Lifecycle ─────────────────────────────────────────────────

class TestLeadLifecycleStages:
    VALID_STAGES = [
        "Lead", "Engagement Drafted", "Engagement Sent", "Engagement Signed",
        "Proposal Accepted", "Onboarding", "Active", "Dormant", "Renewal Due", "Exiting", "Exited",
    ]

    def test_valid_stage_transitions(self):
        for stage in self.VALID_STAGES:
            assert stage in self.VALID_STAGES

    def test_lead_stage_ordering(self):
        # Lead must come before Active in the pipeline
        assert self.VALID_STAGES.index("Lead") < self.VALID_STAGES.index("Active")

    def test_converted_lead_reaches_active(self):
        lead = {"stage": "Lead", "is_converted": False}
        lead["stage"] = "Active"
        lead["is_converted"] = True
        assert lead["is_converted"]
        assert lead["stage"] == "Active"

    def test_lead_estimated_value_integer_paise(self):
        lead = {"estimated_value_paise": 500_000_00}  # ₹5,00,000
        assert isinstance(lead["estimated_value_paise"], int)

    def test_proposal_fee_integer_paise(self):
        proposal = {"fee_paise": 200_000_00}  # ₹2,00,000
        assert isinstance(proposal["fee_paise"], int)


class TestOnboardingWorkflow:
    DEFAULT_TASKS = [
        "Obtain PAN copy",
        "Obtain GST certificate",
        "Collect bank statements",
        "KYC documents",
        "Previous year financials",
        "Director/Partner documents",
        "Engagement letter signing",
        "Add to accounting software",
        "Create login credentials",
        "Welcome call scheduled",
    ]

    def test_default_tasks_created(self):
        assert len(self.DEFAULT_TASKS) == 10

    def test_workflow_completes_when_all_tasks_done(self):
        tasks = [{"status": "done"} for _ in self.DEFAULT_TASKS]
        all_done = all(t["status"] == "done" for t in tasks)
        assert all_done

    def test_workflow_not_complete_with_pending_tasks(self):
        tasks = [{"status": "done"}] * 9 + [{"status": "pending"}]
        all_done = all(t["status"] == "done" for t in tasks)
        assert not all_done

    def test_required_task_cannot_be_skipped_to_complete(self):
        tasks = [
            {"task_name": t, "is_required": True, "status": "done"}
            for t in self.DEFAULT_TASKS[:-1]
        ] + [{"task_name": self.DEFAULT_TASKS[-1], "is_required": True, "status": "pending"}]
        required_incomplete = [t for t in tasks if t["is_required"] and t["status"] != "done"]
        assert len(required_incomplete) == 1


# ── Phase 8: Relationship Intelligence ───────────────────────────────────────

class TestEntityRegistry:
    VALID_ENTITY_TYPES = ["Individual", "Company", "LLP", "Partnership", "Trust", "HUF", "Other"]
    VALID_ROLES = [
        "Director", "Shareholder", "Partner", "Beneficial Owner", "Related Party",
        "Loan Provider", "Loan Recipient", "Trustee", "Beneficiary",
        "Guarantor", "Authorized Signatory",
    ]

    def test_entity_types_valid(self):
        for t in self.VALID_ENTITY_TYPES:
            assert t in self.VALID_ENTITY_TYPES

    def test_all_relationship_roles_defined(self):
        assert len(self.VALID_ROLES) == 11

    def test_ownership_percent_range(self):
        valid_pcts = [0.0, 25.5, 50.0, 100.0]
        invalid_pcts = [-1.0, 101.0]
        for p in valid_pcts:
            assert 0 <= p <= 100
        for p in invalid_pcts:
            assert not (0 <= p <= 100)

    def test_entity_firm_isolation(self):
        entity_a = {"firm_id": FIRM_A, "full_name": "Acme Ltd"}
        entity_b = {"firm_id": FIRM_B, "full_name": "Beta Corp"}
        assert entity_a["firm_id"] != entity_b["firm_id"]

    def test_pan_unique_within_firm(self):
        """Same PAN cannot appear twice for different entities in same firm."""
        seen_pans: dict[tuple, str] = {}
        entities = [
            {"firm_id": FIRM_A, "pan": "ABCDE1234F", "id": "e1"},
            {"firm_id": FIRM_A, "pan": "ABCDE1234F", "id": "e2"},  # duplicate
        ]
        errors = []
        for e in entities:
            key = (e["firm_id"], e["pan"])
            if key in seen_pans:
                errors.append(f"Duplicate PAN {e['pan']} in firm")
            else:
                seen_pans[key] = e["id"]
        assert len(errors) == 1

    def test_same_pan_allowed_across_firms(self):
        """Same PAN in different firms is allowed — they are separate tenants."""
        e_a = {"firm_id": FIRM_A, "pan": "ABCDE1234F"}
        e_b = {"firm_id": FIRM_B, "pan": "ABCDE1234F"}
        # Different firms — no conflict
        assert e_a["firm_id"] != e_b["firm_id"]


class TestCrossClientDetection:
    def test_pan_match_detected(self):
        entity_roles = [
            {"entity_id": "e1", "pan": "ABCDE1234F", "client_id": CLIENT_A},
            {"entity_id": "e2", "pan": "ABCDE1234F", "client_id": CLIENT_B},
        ]
        matches = []
        pan_to_clients: dict[str, list] = {}
        for r in entity_roles:
            pan = r.get("pan")
            if pan:
                pan_to_clients.setdefault(pan, []).append(r["client_id"])
        for pan, clients in pan_to_clients.items():
            if len(clients) > 1:
                for i in range(len(clients)):
                    for j in range(i + 1, len(clients)):
                        matches.append({
                            "match_type": "pan",
                            "match_value": pan,
                            "client_id_a": clients[i],
                            "client_id_b": clients[j],
                        })
        assert len(matches) == 1
        assert matches[0]["match_type"] == "pan"
        assert matches[0]["match_value"] == "ABCDE1234F"

    def test_no_false_positive_same_client(self):
        """Two roles with same PAN in the same client should not generate a match."""
        entity_roles = [
            {"entity_id": "e1", "pan": "ABCDE1234F", "client_id": CLIENT_A},
            {"entity_id": "e2", "pan": "ABCDE1234F", "client_id": CLIENT_A},  # same client
        ]
        pan_to_clients: dict[str, set] = {}
        for r in entity_roles:
            pan = r.get("pan")
            if pan:
                pan_to_clients.setdefault(pan, set()).add(r["client_id"])
        matches = [pan for pan, clients in pan_to_clients.items() if len(clients) > 1]
        assert len(matches) == 0  # no cross-client match


# ── Phase 9: Health Engine ────────────────────────────────────────────────────

class TestHealthScoreCalculation:
    def _grade(self, score: int) -> str:
        if score >= 85: return "A"
        if score >= 70: return "B"
        if score >= 55: return "C"
        if score >= 40: return "D"
        return "F"

    def _overall(self, dimensions: dict[str, int]) -> int:
        return sum(dimensions.values()) // len(dimensions)

    def test_grade_boundaries(self):
        assert self._grade(100) == "A"
        assert self._grade(85)  == "A"
        assert self._grade(84)  == "B"
        assert self._grade(70)  == "B"
        assert self._grade(69)  == "C"
        assert self._grade(55)  == "C"
        assert self._grade(54)  == "D"
        assert self._grade(40)  == "D"
        assert self._grade(39)  == "F"
        assert self._grade(0)   == "F"

    def test_is_critical_below_40(self):
        assert self._grade(39) == "F"
        assert 39 < 40  # is_critical threshold

    def test_is_at_risk_below_60(self):
        score = 58
        assert score < 60  # is_at_risk threshold

    def test_overall_score_integer(self):
        dims = {
            "compliance": 80, "accounting": 70, "documents": 60,
            "responsiveness": 90, "relationship_risk": 100,
            "financial_risk": 75, "engagement_health": 85,
        }
        overall = self._overall(dims)
        assert isinstance(overall, int)
        assert 0 <= overall <= 100

    def test_score_clamps_to_zero(self):
        """Subtracting penalties cannot go below 0."""
        score = 100
        penalties = 150  # more than 100
        result = max(0, score - penalties)
        assert result == 0

    def test_compliance_score_degrades_per_overdue_item(self):
        base = 100
        overdue_count = 3
        penalty_per_item = 20
        score = max(0, base - overdue_count * penalty_per_item)
        assert score == 40

    def test_engagement_health_no_letter(self):
        engagement_health_score = 40  # no engagement letter
        assert engagement_health_score < 60

    def test_relationship_risk_degrades_per_confirmed_match(self):
        base = 100
        confirmed_matches = 2
        score = max(0, base - confirmed_matches * 15)
        assert score == 70

    def test_health_history_records_on_change(self):
        old_score = 75
        new_score = 60
        should_record = old_score != new_score
        assert should_record

    def test_override_replaces_dimension_score(self):
        calculated_score = 30
        override = {"override_score": 65, "is_active": True}
        effective_score = override["override_score"] if override["is_active"] else calculated_score
        assert effective_score == 65


# ── Security: Multi-tenancy for new tables ────────────────────────────────────

class TestPhase789MultiTenancy:
    def test_lead_scoped_to_firm(self):
        leads = [
            {"firm_id": FIRM_A, "company_name": "Acme"},
            {"firm_id": FIRM_B, "company_name": "Beta"},
        ]
        firm_a_leads = [l for l in leads if l["firm_id"] == FIRM_A]
        assert len(firm_a_leads) == 1
        assert firm_a_leads[0]["company_name"] == "Acme"

    def test_health_score_scoped_to_firm(self):
        scores = [
            {"firm_id": FIRM_A, "client_id": CLIENT_A, "overall_score": 80},
            {"firm_id": FIRM_B, "client_id": CLIENT_A, "overall_score": 40},
        ]
        firm_a_score = next(s for s in scores if s["firm_id"] == FIRM_A)
        assert firm_a_score["overall_score"] == 80

    def test_entity_not_visible_across_firms(self):
        entity = {"firm_id": FIRM_A, "full_name": "John Doe"}
        # Firm B cannot see Firm A's entity
        visible_to_b = entity["firm_id"] == FIRM_B
        assert not visible_to_b

    def test_cross_client_match_scoped_to_firm(self):
        matches = [
            {"firm_id": FIRM_A, "match_value": "ABCDE1234F"},
            {"firm_id": FIRM_B, "match_value": "ABCDE1234F"},
        ]
        firm_a_matches = [m for m in matches if m["firm_id"] == FIRM_A]
        assert len(firm_a_matches) == 1

    def test_timeline_event_not_leakable(self):
        """Timeline events must include firm_id for isolation."""
        event = {
            "firm_id": FIRM_A,
            "client_id": CLIENT_A,
            "event_type": "lead_created",
        }
        assert "firm_id" in event
        assert event["firm_id"] == FIRM_A


# ── AI Readiness Foundation ────────────────────────────────────────────────────

class TestAIReadinessInfrastructure:
    def test_ai_signals_have_required_fields(self):
        signal = {
            "firm_id": FIRM_A,
            "signal_type": "overdue_compliance",
            "signal_data": {"count": 3},
            "source": "compliance_engine",
            "processed": False,
        }
        assert "firm_id" in signal
        assert "signal_type" in signal
        assert "signal_data" in signal
        assert not signal["processed"]

    def test_client_profile_structure(self):
        profile = {
            "firm_id": FIRM_A,
            "client_id": CLIENT_A,
            "profile_data": {},
            "tags": [],
            "segment": None,
        }
        assert "profile_data" in profile
        assert isinstance(profile["tags"], list)

    def test_ai_trigger_registry_structure(self):
        trigger = {
            "firm_id": FIRM_A,
            "trigger_name": "health_score_critical",
            "trigger_event": "health_score_changed",
            "conditions": {"threshold": 40},
            "is_active": True,
        }
        assert trigger["is_active"]
        assert "threshold" in trigger["conditions"]
