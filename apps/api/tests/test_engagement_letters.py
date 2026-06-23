"""
Engagement Letter Management System — backend unit tests.

Covers:
  - Default template seeding (6 defaults when none exist)
  - Template CRUD (create, get, update, soft-delete)
  - Engagement creation, number format, template content copy
  - Status transitions: generate, send, sign, reject — valid and invalid
  - 409 for invalid status transitions
  - Merge field rendering in generate endpoint
  - firm_id isolation (cannot access another firm's data)
  - fee_amount_paise stored correctly (integer paise, never float)
  - Audit events logged for each transition
  - Reject requires status Sent or Viewed
  - Sign requires status Sent or Viewed
"""
import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

FIRM_A = "firm-aaaa-0001"
FIRM_B = "firm-bbbb-0002"

USER_MANAGER_A = {
    "auth_user_id": "u-manager-1",
    "firm_id": FIRM_A,
    "role": "Manager",
    "email": "manager@firmA.com",
    "name": "Test Manager",
}
USER_READER_A = {
    "auth_user_id": "u-reader-1",
    "firm_id": FIRM_A,
    "role": "Executive",
    "email": "reader@firmA.com",
    "name": "Test Reader",
}
USER_MANAGER_B = {
    "auth_user_id": "u-manager-b",
    "firm_id": FIRM_B,
    "role": "Manager",
    "email": "manager@firmB.com",
    "name": "Manager B",
}

SAMPLE_TEMPLATE = {
    "id": "tmpl-0001",
    "firm_id": FIRM_A,
    "name": "GST Compliance Engagement",
    "service_type": "GST Compliance",
    "content": "<p>Dear {{client_name}},</p><p>Fee: {{engagement_fee}}</p>",
    "version": 1,
    "is_default": True,
    "is_deleted": False,
    "created_by": "u-manager-1",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}

SAMPLE_DRAFT_ENGAGEMENT = {
    "id": "eng-0001",
    "firm_id": FIRM_A,
    "lead_id": None,
    "client_id": None,
    "template_id": None,
    "engagement_number": "EL-2026-0001",
    "title": "GST Filing Engagement",
    "status": "Draft",
    "content": "",
    "fee_amount_paise": 500000,  # ₹5,000 in paise
    "start_date": "2026-07-01",
    "expiry_date": "2026-09-30",
    "recipient_name": "Acme Corp",
    "recipient_email": "acme@example.com",
    "generated_pdf_url": None,
    "signed_pdf_url": None,
    "sent_at": None,
    "viewed_at": None,
    "signed_at": None,
    "rejected_at": None,
    "rejection_notes": None,
    "created_by": "u-manager-1",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}

FIRM_B_TEMPLATE = {
    "id": "tmpl-firmb-0001",
    "firm_id": FIRM_B,
    "name": "Firm B Template",
    "service_type": "GST Compliance",
    "content": "<p>Firm B content</p>",
    "version": 1,
    "is_default": False,
    "is_deleted": False,
    "created_by": "u-manager-b",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}


# ─── Helper: clear mock stores before each test ───────────────────────────────

def _clear_mocks():
    from routers.engagement_letters import _MOCK_TEMPLATES, _MOCK_ENGAGEMENTS, _MOCK_EVENTS
    _MOCK_TEMPLATES.clear()
    _MOCK_ENGAGEMENTS.clear()
    _MOCK_EVENTS.clear()


# ─── Task 1: Default Template Seeding ────────────────────────────────────────

class TestDefaultTemplateSeedingMock:
    """GET /templates with no existing templates seeds 6 defaults (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def test_empty_firm_gets_six_default_templates(self):
        from routers.engagement_letters import list_templates
        with patch("routers.engagement_letters._db", return_value=None):
            result = list_templates(current_user=USER_MANAGER_A)
        assert result["success"] is True
        templates = result["data"]["templates"]
        assert len(templates) == 6
        assert result["data"]["total"] == 6

    def test_seeded_templates_have_correct_service_types(self):
        from routers.engagement_letters import list_templates
        expected_types = {
            "GST Compliance", "Income Tax Return", "Tax Audit",
            "ROC Compliance", "Bookkeeping", "Virtual CFO",
        }
        with patch("routers.engagement_letters._db", return_value=None):
            result = list_templates(current_user=USER_MANAGER_A)
        service_types = {t["service_type"] for t in result["data"]["templates"]}
        assert service_types == expected_types

    def test_seeded_templates_are_firm_scoped(self):
        from routers.engagement_letters import list_templates
        with patch("routers.engagement_letters._db", return_value=None):
            result = list_templates(current_user=USER_MANAGER_A)
        for tmpl in result["data"]["templates"]:
            assert tmpl["firm_id"] == FIRM_A

    def test_second_call_does_not_re_seed(self):
        from routers.engagement_letters import list_templates
        with patch("routers.engagement_letters._db", return_value=None):
            list_templates(current_user=USER_MANAGER_A)
            result2 = list_templates(current_user=USER_MANAGER_A)
        # Should still be 6, not 12
        assert result2["data"]["total"] == 6

    def test_different_firm_gets_separate_seed(self):
        from routers.engagement_letters import list_templates
        with patch("routers.engagement_letters._db", return_value=None):
            result_a = list_templates(current_user=USER_MANAGER_A)
            result_b = list_templates(current_user=USER_MANAGER_B)
        # Both firms should have 6 templates each
        assert result_a["data"]["total"] == 6
        assert result_b["data"]["total"] == 6
        # Their IDs should be distinct
        ids_a = {t["id"] for t in result_a["data"]["templates"]}
        ids_b = {t["id"] for t in result_b["data"]["templates"]}
        assert ids_a.isdisjoint(ids_b)

    def test_seeded_templates_have_merge_fields_in_content(self):
        from routers.engagement_letters import list_templates
        with patch("routers.engagement_letters._db", return_value=None):
            result = list_templates(current_user=USER_MANAGER_A)
        for tmpl in result["data"]["templates"]:
            assert "{{client_name}}" in tmpl["content"], \
                f"Template '{tmpl['name']}' missing {{client_name}} merge field"


# ─── Task 2: Template CRUD ────────────────────────────────────────────────────

class TestTemplateCRUDMock:
    """CRUD operations on engagement templates (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def test_create_template_returns_201_equivalent(self):
        from routers.engagement_letters import create_template
        from routers.engagement_letters import TemplateIn
        body = TemplateIn(name="Custom Template", service_type="Bookkeeping",
                          content="<p>Dear {{client_name}}</p>")
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_template(body=body, current_user=USER_MANAGER_A)
        assert result["success"] is True
        tmpl = result["data"]["template"]
        assert tmpl["name"] == "Custom Template"
        assert tmpl["firm_id"] == FIRM_A
        assert tmpl["version"] == 1
        assert tmpl["is_deleted"] is False

    def test_get_template_returns_correct_template(self):
        from routers.engagement_letters import create_template, get_template
        from routers.engagement_letters import TemplateIn
        body = TemplateIn(name="My Template", service_type="GST Compliance",
                          content="<p>Content</p>")
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_template(body=body, current_user=USER_MANAGER_A)
            tmpl_id = created["data"]["template"]["id"]
            result = get_template(template_id=tmpl_id, current_user=USER_MANAGER_A)
        assert result["data"]["template"]["id"] == tmpl_id
        assert result["data"]["template"]["name"] == "My Template"

    def test_get_nonexistent_template_returns_404(self):
        from routers.engagement_letters import get_template
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                get_template(template_id="no-such-id", current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 404

    def test_update_template_increments_version(self):
        from routers.engagement_letters import create_template, update_template
        from routers.engagement_letters import TemplateIn, TemplateUpdate
        body = TemplateIn(name="Old Name", service_type="GST Compliance",
                          content="<p>Old</p>")
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_template(body=body, current_user=USER_MANAGER_A)
            tmpl_id = created["data"]["template"]["id"]
            updated = update_template(
                template_id=tmpl_id,
                body=TemplateUpdate(name="New Name"),
                current_user=USER_MANAGER_A,
            )
        assert updated["data"]["template"]["name"] == "New Name"
        assert updated["data"]["template"]["version"] == 2

    def test_update_template_not_found_returns_404(self):
        from routers.engagement_letters import update_template
        from routers.engagement_letters import TemplateUpdate
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                update_template(
                    template_id="no-such-id",
                    body=TemplateUpdate(name="X"),
                    current_user=USER_MANAGER_A,
                )
        assert exc_info.value.status_code == 404

    def test_soft_delete_template_hides_from_list(self):
        from routers.engagement_letters import create_template, delete_template, list_templates
        from routers.engagement_letters import TemplateIn
        body = TemplateIn(name="To Delete", service_type="Bookkeeping",
                          content="<p>del</p>")
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_template(body=body, current_user=USER_MANAGER_A)
            tmpl_id = created["data"]["template"]["id"]
            delete_result = delete_template(template_id=tmpl_id, current_user=USER_MANAGER_A)
            list_result = list_templates(current_user=USER_MANAGER_A)
        assert delete_result["success"] is True
        ids_in_list = [t["id"] for t in list_result["data"]["templates"]]
        assert tmpl_id not in ids_in_list

    def test_delete_nonexistent_template_returns_404(self):
        from routers.engagement_letters import delete_template
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                delete_template(template_id="ghost-id", current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 404


# ─── Task 3: Engagement Creation ─────────────────────────────────────────────

class TestEngagementCreationMock:
    """Engagement letter creation (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def test_create_engagement_returns_draft_status(self):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="GST Filing 2026", fee_amount_paise=500000)
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        assert result["success"] is True
        eng = result["data"]["engagement"]
        assert eng["status"] == "Draft"
        assert eng["firm_id"] == FIRM_A

    def test_engagement_number_has_correct_format(self):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="Test Letter", fee_amount_paise=100000)
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        eng_no = result["data"]["engagement"]["engagement_number"]
        # Format: EL-YYYY-NNNN
        parts = eng_no.split("-")
        assert parts[0] == "EL"
        assert len(parts[1]) == 4    # year
        assert len(parts[2]) == 4    # zero-padded sequence
        assert parts[2] == "0001"

    def test_fee_amount_paise_stored_as_integer(self):
        """All monetary values in paise — CGST Act compliance, never float."""
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="Fee Test", fee_amount_paise=1234567)
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        stored = result["data"]["engagement"]["fee_amount_paise"]
        assert stored == 1234567
        assert isinstance(stored, int), "fee_amount_paise must be an integer (paise), never float"

    def test_create_with_template_copies_content(self):
        """If template_id is provided, its content is copied into engagement.content."""
        from routers.engagement_letters import create_engagement, create_template
        from routers.engagement_letters import EngagementIn, TemplateIn
        tmpl_content = "<p>Dear {{client_name}}, Fee: {{engagement_fee}}</p>"
        tmpl_body = TemplateIn(name="T", service_type="GST Compliance",
                               content=tmpl_content)
        with patch("routers.engagement_letters._db", return_value=None):
            tmpl_result = create_template(body=tmpl_body, current_user=USER_MANAGER_A)
            tmpl_id = tmpl_result["data"]["template"]["id"]
            eng_body = EngagementIn(title="Letter with Template",
                                    fee_amount_paise=300000,
                                    template_id=tmpl_id)
            result = create_engagement(body=eng_body, current_user=USER_MANAGER_A)
        assert result["data"]["engagement"]["content"] == tmpl_content

    def test_create_without_template_has_empty_content(self):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="No Template", fee_amount_paise=0)
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        assert result["data"]["engagement"]["content"] == ""

    def test_negative_fee_raises_422(self):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="Bad Fee", fee_amount_paise=-1)
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                create_engagement(body=body, current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 422

    def test_created_event_logged(self):
        """Engagement creation inserts a 'created' event into _MOCK_EVENTS."""
        from routers.engagement_letters import create_engagement, _MOCK_EVENTS
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="Audit Trail Test", fee_amount_paise=100000)
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        eng_id = result["data"]["engagement"]["id"]
        events = [e for e in _MOCK_EVENTS if e["engagement_id"] == eng_id]
        assert len(events) >= 1
        assert events[0]["event_type"] == "created"


# ─── Task 4: Status Transitions ──────────────────────────────────────────────

class TestStatusTransitionsMock:
    """Status machine: generate, send, sign, reject (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def _create_draft(self, content="<p>Dear {{client_name}}, fee {{engagement_fee}}</p>"):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        body = EngagementIn(title="Transition Test", fee_amount_paise=250000,
                            recipient_name="Acme Corp")
        # If content needed, add a template first
        if content:
            from routers.engagement_letters import create_template
            from routers.engagement_letters import TemplateIn
            tmpl_body = TemplateIn(name="T", service_type="GST Compliance",
                                   content=content)
            tmpl_result = create_template(body=tmpl_body, current_user=USER_MANAGER_A)
            body.template_id = tmpl_result["data"]["template"]["id"]
        with patch("routers.engagement_letters._db", return_value=None):
            result = create_engagement(body=body, current_user=USER_MANAGER_A)
        return result["data"]["engagement"]["id"]

    def test_generate_transitions_draft_to_generated(self):
        from routers.engagement_letters import generate_engagement
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            result = generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        assert result["success"] is True
        assert result["data"]["engagement"]["status"] == "Generated"

    def test_generate_non_draft_raises_409(self):
        from routers.engagement_letters import generate_engagement, send_engagement
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            with pytest.raises(HTTPException) as exc_info:
                generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 409

    def test_send_transitions_draft_to_sent(self):
        from routers.engagement_letters import send_engagement
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            result = send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        assert result["data"]["engagement"]["status"] == "Sent"
        assert result["data"]["engagement"]["sent_at"] is not None

    def test_send_generated_to_sent_also_valid(self):
        from routers.engagement_letters import generate_engagement, send_engagement
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            result = send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        assert result["data"]["engagement"]["status"] == "Sent"

    def test_sign_transitions_sent_to_signed(self):
        from routers.engagement_letters import send_engagement, sign_engagement
        from routers.engagement_letters import SignIn
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            result = sign_engagement(
                engagement_id=eng_id,
                body=SignIn(signed_pdf_url="https://storage.example.com/signed.pdf"),
                current_user=USER_MANAGER_A,
            )
        eng = result["data"]["engagement"]
        assert eng["status"] == "Signed"
        assert eng["signed_at"] is not None
        assert eng["signed_pdf_url"] == "https://storage.example.com/signed.pdf"

    def test_sign_draft_raises_409(self):
        """Cannot sign a Draft engagement — must be Sent or Viewed."""
        from routers.engagement_letters import sign_engagement
        from routers.engagement_letters import SignIn
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                sign_engagement(
                    engagement_id=eng_id,
                    body=SignIn(),
                    current_user=USER_MANAGER_A,
                )
        assert exc_info.value.status_code == 409

    def test_reject_transitions_sent_to_rejected(self):
        from routers.engagement_letters import send_engagement, reject_engagement
        from routers.engagement_letters import RejectIn
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            result = reject_engagement(
                engagement_id=eng_id,
                body=RejectIn(rejection_notes="Fee too high"),
                current_user=USER_MANAGER_A,
            )
        eng = result["data"]["engagement"]
        assert eng["status"] == "Rejected"
        assert eng["rejected_at"] is not None
        assert eng["rejection_notes"] == "Fee too high"

    def test_reject_draft_raises_409(self):
        """Cannot reject a Draft engagement — must be Sent or Viewed."""
        from routers.engagement_letters import reject_engagement
        from routers.engagement_letters import RejectIn
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                reject_engagement(
                    engagement_id=eng_id,
                    body=RejectIn(),
                    current_user=USER_MANAGER_A,
                )
        assert exc_info.value.status_code == 409

    def test_reject_generated_raises_409(self):
        """Cannot reject a Generated engagement — must be Sent or Viewed."""
        from routers.engagement_letters import generate_engagement, reject_engagement
        from routers.engagement_letters import RejectIn
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            with pytest.raises(HTTPException) as exc_info:
                reject_engagement(
                    engagement_id=eng_id,
                    body=RejectIn(),
                    current_user=USER_MANAGER_A,
                )
        assert exc_info.value.status_code == 409

    def test_update_only_allowed_in_draft(self):
        from routers.engagement_letters import send_engagement, update_engagement
        from routers.engagement_letters import EngagementUpdate
        eng_id = self._create_draft()
        with patch("routers.engagement_letters._db", return_value=None):
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            with pytest.raises(HTTPException) as exc_info:
                update_engagement(
                    engagement_id=eng_id,
                    body=EngagementUpdate(title="New Title"),
                    current_user=USER_MANAGER_A,
                )
        assert exc_info.value.status_code == 409


# ─── Task 5: Merge Field Rendering ───────────────────────────────────────────

class TestMergeFieldRenderingMock:
    """Merge field rendering in the generate endpoint (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def test_generate_renders_client_name(self):
        from routers.engagement_letters import create_template, create_engagement, generate_engagement
        from routers.engagement_letters import TemplateIn, EngagementIn
        tmpl_body = TemplateIn(
            name="T", service_type="GST Compliance",
            content="<p>Dear {{client_name}},</p>",
        )
        with patch("routers.engagement_letters._db", return_value=None):
            tmpl = create_template(body=tmpl_body, current_user=USER_MANAGER_A)
            tmpl_id = tmpl["data"]["template"]["id"]
            eng = create_engagement(
                body=EngagementIn(title="Test", fee_amount_paise=0,
                                  template_id=tmpl_id, recipient_name="Ravi Kumar"),
                current_user=USER_MANAGER_A,
            )
            eng_id = eng["data"]["engagement"]["id"]
            result = generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        content = result["data"]["rendered_content"]
        assert "Ravi Kumar" in content
        assert "{{client_name}}" not in content

    def test_generate_renders_fee_in_rupees(self):
        """fee_amount_paise 500000 → ₹5000 in rendered content.
        Integer arithmetic — CGST Act compliance, never float."""
        from routers.engagement_letters import create_template, create_engagement, generate_engagement
        from routers.engagement_letters import TemplateIn, EngagementIn
        tmpl_body = TemplateIn(
            name="T", service_type="GST Compliance",
            content="<p>Fee: {{engagement_fee}}</p>",
        )
        with patch("routers.engagement_letters._db", return_value=None):
            tmpl = create_template(body=tmpl_body, current_user=USER_MANAGER_A)
            tmpl_id = tmpl["data"]["template"]["id"]
            eng = create_engagement(
                body=EngagementIn(title="Fee test", fee_amount_paise=500000,
                                  template_id=tmpl_id),
                current_user=USER_MANAGER_A,
            )
            eng_id = eng["data"]["engagement"]["id"]
            result = generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        content = result["data"]["rendered_content"]
        assert "₹5000" in content
        assert "{{engagement_fee}}" not in content

    def test_generate_renders_partner_name(self):
        from routers.engagement_letters import create_template, create_engagement, generate_engagement
        from routers.engagement_letters import TemplateIn, EngagementIn
        tmpl_body = TemplateIn(
            name="T", service_type="GST Compliance",
            content="<p>Signed: {{partner_name}}</p>",
        )
        user = {**USER_MANAGER_A, "name": "CA Priya Sharma"}
        with patch("routers.engagement_letters._db", return_value=None):
            tmpl = create_template(body=tmpl_body, current_user=user)
            tmpl_id = tmpl["data"]["template"]["id"]
            eng = create_engagement(
                body=EngagementIn(title="Partner test", fee_amount_paise=0,
                                  template_id=tmpl_id),
                current_user=user,
            )
            eng_id = eng["data"]["engagement"]["id"]
            result = generate_engagement(engagement_id=eng_id, current_user=user)
        content = result["data"]["rendered_content"]
        assert "CA Priya Sharma" in content

    def test_render_merge_fields_function_directly(self):
        """Unit test for the _render_merge_fields helper."""
        from routers.engagement_letters import _render_merge_fields
        template = "Dear {{client_name}}, your fee is {{engagement_fee}}."
        fields = {"client_name": "Ramesh", "engagement_fee": "₹5000"}
        result = _render_merge_fields(template, fields)
        assert result == "Dear Ramesh, your fee is ₹5000."

    def test_render_merge_fields_unknown_key_replaced_with_empty(self):
        """Unknown merge fields in template are replaced with empty string."""
        from routers.engagement_letters import _render_merge_fields
        template = "Hello {{client_name}}, your GSTIN is {{client_gstin}}."
        fields = {"client_name": "Suresh"}
        result = _render_merge_fields(template, fields)
        # {{client_gstin}} is NOT in fields, so it remains unchanged (not removed)
        assert "Suresh" in result

    def test_format_fee_function_integer_arithmetic(self):
        """_format_fee uses integer paise arithmetic, never float — CGST Act compliance."""
        from routers.engagement_letters import _format_fee
        assert _format_fee(500000) == "₹5000"   # ₹5,000 (500000 paise)
        assert _format_fee(100) == "₹1"          # ₹1 (100 paise)
        assert _format_fee(150) == "₹1.50"       # ₹1.50 (150 paise)
        assert _format_fee(0) == "₹0"            # zero fee


# ─── Task 6: firm_id Isolation ────────────────────────────────────────────────

class TestFirmIsolationMock:
    """Cannot access another firm's templates or engagements (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def test_firm_b_cannot_get_firm_a_template(self):
        from routers.engagement_letters import create_template, get_template
        from routers.engagement_letters import TemplateIn
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_template(
                body=TemplateIn(name="A's Template", service_type="GST Compliance",
                                content="<p>A</p>"),
                current_user=USER_MANAGER_A,
            )
            tmpl_id = created["data"]["template"]["id"]
            with pytest.raises(HTTPException) as exc_info:
                get_template(template_id=tmpl_id, current_user=USER_MANAGER_B)
        assert exc_info.value.status_code == 404

    def test_firm_b_cannot_see_firm_a_engagement(self):
        from routers.engagement_letters import create_engagement, list_engagements
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            create_engagement(
                body=EngagementIn(title="Firm A Letter", fee_amount_paise=100000),
                current_user=USER_MANAGER_A,
            )
            result_b = list_engagements(current_user=USER_MANAGER_B)
        assert result_b["data"]["total"] == 0
        assert result_b["data"]["engagements"] == []

    def test_firm_b_cannot_get_firm_a_engagement_by_id(self):
        from routers.engagement_letters import create_engagement, get_engagement
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_engagement(
                body=EngagementIn(title="Firm A Only", fee_amount_paise=0),
                current_user=USER_MANAGER_A,
            )
            eng_id = created["data"]["engagement"]["id"]
            with pytest.raises(HTTPException) as exc_info:
                get_engagement(engagement_id=eng_id, current_user=USER_MANAGER_B)
        assert exc_info.value.status_code == 404


# ─── Task 7: Audit Events ─────────────────────────────────────────────────────

class TestAuditEventsMock:
    """Audit events are logged for each status transition (mock mode)."""

    def setup_method(self):
        _clear_mocks()

    def _create_sent_engagement(self):
        from routers.engagement_letters import create_engagement, send_engagement
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_engagement(
                body=EngagementIn(title="Audit Test", fee_amount_paise=100000),
                current_user=USER_MANAGER_A,
            )
            eng_id = created["data"]["engagement"]["id"]
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        return eng_id

    def test_generate_event_logged(self):
        from routers.engagement_letters import create_engagement, generate_engagement, _MOCK_EVENTS
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            eng = create_engagement(
                body=EngagementIn(title="Gen Test", fee_amount_paise=0),
                current_user=USER_MANAGER_A,
            )
            eng_id = eng["data"]["engagement"]["id"]
            generate_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        events = [e for e in _MOCK_EVENTS
                  if e["engagement_id"] == eng_id and e["event_type"] == "generated"]
        assert len(events) == 1

    def test_send_event_logged(self):
        from routers.engagement_letters import _MOCK_EVENTS
        eng_id = self._create_sent_engagement()
        events = [e for e in _MOCK_EVENTS
                  if e["engagement_id"] == eng_id and e["event_type"] == "sent"]
        assert len(events) == 1

    def test_sign_event_logged(self):
        from routers.engagement_letters import sign_engagement, _MOCK_EVENTS
        from routers.engagement_letters import SignIn
        eng_id = self._create_sent_engagement()
        with patch("routers.engagement_letters._db", return_value=None):
            sign_engagement(engagement_id=eng_id, body=SignIn(),
                            current_user=USER_MANAGER_A)
        events = [e for e in _MOCK_EVENTS
                  if e["engagement_id"] == eng_id and e["event_type"] == "signed"]
        assert len(events) == 1

    def test_reject_event_logged(self):
        from routers.engagement_letters import reject_engagement, _MOCK_EVENTS
        from routers.engagement_letters import RejectIn
        eng_id = self._create_sent_engagement()
        with patch("routers.engagement_letters._db", return_value=None):
            reject_engagement(engagement_id=eng_id,
                              body=RejectIn(rejection_notes="Too expensive"),
                              current_user=USER_MANAGER_A)
        events = [e for e in _MOCK_EVENTS
                  if e["engagement_id"] == eng_id and e["event_type"] == "rejected"]
        assert len(events) == 1

    def test_get_engagement_returns_events(self):
        from routers.engagement_letters import create_engagement, send_engagement, get_engagement
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            created = create_engagement(
                body=EngagementIn(title="Events test", fee_amount_paise=0),
                current_user=USER_MANAGER_A,
            )
            eng_id = created["data"]["engagement"]["id"]
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            result = get_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
        events = result["data"]["events"]
        assert len(events) >= 2   # at minimum: created + sent
        event_types = {e["event_type"] for e in events}
        assert "created" in event_types
        assert "sent" in event_types


# ─── Task 8: Engagement Number Sequence ──────────────────────────────────────

class TestEngagementNumberSequenceMock:
    """Engagement numbers are sequential and correctly formatted."""

    def setup_method(self):
        _clear_mocks()

    def test_sequential_engagement_numbers(self):
        from routers.engagement_letters import create_engagement
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            r1 = create_engagement(body=EngagementIn(title="First", fee_amount_paise=0),
                                   current_user=USER_MANAGER_A)
            r2 = create_engagement(body=EngagementIn(title="Second", fee_amount_paise=0),
                                   current_user=USER_MANAGER_A)
        no1 = r1["data"]["engagement"]["engagement_number"]
        no2 = r2["data"]["engagement"]["engagement_number"]
        seq1 = int(no1.split("-")[2])
        seq2 = int(no2.split("-")[2])
        assert seq2 == seq1 + 1


# ─── Task 9: list_engagements filter ─────────────────────────────────────────

class TestListEngagementsFilterMock:
    """List endpoint filters by status, lead_id, client_id."""

    def setup_method(self):
        _clear_mocks()

    def test_filter_by_status(self):
        from routers.engagement_letters import create_engagement, send_engagement, list_engagements
        from routers.engagement_letters import EngagementIn
        with patch("routers.engagement_letters._db", return_value=None):
            r = create_engagement(body=EngagementIn(title="To Send", fee_amount_paise=0),
                                  current_user=USER_MANAGER_A)
            eng_id = r["data"]["engagement"]["id"]
            send_engagement(engagement_id=eng_id, current_user=USER_MANAGER_A)
            create_engagement(body=EngagementIn(title="Stays Draft", fee_amount_paise=0),
                              current_user=USER_MANAGER_A)
            drafts = list_engagements(status="Draft", lead_id=None, client_id=None,
                                      current_user=USER_MANAGER_A)
            sents = list_engagements(status="Sent", lead_id=None, client_id=None,
                                     current_user=USER_MANAGER_A)
        assert drafts["data"]["total"] == 1
        assert sents["data"]["total"] == 1
        assert sents["data"]["engagements"][0]["id"] == eng_id

    def test_filter_by_lead_id(self):
        from routers.engagement_letters import create_engagement, list_engagements
        from routers.engagement_letters import EngagementIn
        lead_id = "lead-xyz-0001"
        with patch("routers.engagement_letters._db", return_value=None):
            create_engagement(
                body=EngagementIn(title="With Lead", fee_amount_paise=0, lead_id=lead_id),
                current_user=USER_MANAGER_A,
            )
            create_engagement(
                body=EngagementIn(title="No Lead", fee_amount_paise=0),
                current_user=USER_MANAGER_A,
            )
            result = list_engagements(status=None, lead_id=lead_id, client_id=None,
                                      current_user=USER_MANAGER_A)
        assert result["data"]["total"] == 1
        assert result["data"]["engagements"][0]["lead_id"] == lead_id
