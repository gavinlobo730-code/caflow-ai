"""
Fee engagement management tests.
Covers: create, list, update, delete (soft-delete), and RBAC.
"""
import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

FIRM_A = "firm-aaa"
FIRM_B = "firm-bbb"

USER_PARTNER_A = {"auth_user_id": "u1", "firm_id": FIRM_A, "role": "Partner"}
USER_MANAGER_A = {"auth_user_id": "u2", "firm_id": FIRM_A, "role": "Manager"}
USER_MANAGER_B = {"auth_user_id": "u3", "firm_id": FIRM_B, "role": "Manager"}

CLIENT_A = {
    "id": "c-a", "firm_id": FIRM_A, "client_name": "Client A",
}
CLIENT_B = {
    "id": "c-b", "firm_id": FIRM_B, "client_name": "Client B",
}

ENGAGEMENT_A = {
    "id": "eng-a",
    "firm_id": FIRM_A,
    "client_id": "c-a",
    "service_type": "Monthly Bookkeeping",
    "fee_paise": 500000,
    "billing_cycle": "Monthly",
    "start_date": "2026-01-01",
    "end_date": None,
    "status": "Active",
    "notes": "Test engagement",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}


class TestListEngagements:

    def test_list_engagements_by_firm(self):
        from routers.engagements import list_engagements
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_all.return_value = [ENGAGEMENT_A]
            result = list_engagements(current_user=USER_MANAGER_A)
        assert result["success"] is True
        assert len(result["data"]["engagements"]) == 1
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status=None)

    def test_list_engagements_with_client_filter(self):
        from routers.engagements import list_engagements
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_all.return_value = [ENGAGEMENT_A]
            result = list_engagements(client_id="c-a", current_user=USER_MANAGER_A)
        assert result["success"] is True
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id="c-a", status=None)

    def test_list_engagements_with_status_filter(self):
        from routers.engagements import list_engagements
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_all.return_value = [ENGAGEMENT_A]
            result = list_engagements(status="Active", current_user=USER_MANAGER_A)
        assert result["success"] is True
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status="Active")


class TestGetEngagement:

    def test_get_engagement_succeeds(self):
        from routers.engagements import get_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ENGAGEMENT_A
            result = get_engagement(engagement_id="eng-a", current_user=USER_MANAGER_A)
        assert result["success"] is True
        assert result["data"]["engagement"]["id"] == "eng-a"

    def test_get_engagement_not_found(self):
        from routers.engagements import get_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                get_engagement(engagement_id="eng-missing", current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 404

    def test_get_engagement_tenant_isolation(self):
        from routers.engagements import get_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {**ENGAGEMENT_A, "firm_id": FIRM_B}
            with pytest.raises(HTTPException) as exc_info:
                get_engagement(engagement_id="eng-a", current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 404


class TestCreateEngagement:

    def test_create_engagement_succeeds(self):
        from routers.engagements import create_engagement
        from routers.engagements import EngagementCreate
        body = EngagementCreate(
            client_id="c-a",
            service_type="Monthly Bookkeeping",
            fee_paise=500000,
            billing_cycle="Monthly",
            start_date="2026-01-01",
        )
        with patch("routers.engagements.client_repo") as mock_client_repo, \
             patch("routers.engagements.engagement_repo") as mock_eng_repo:
            mock_client_repo.find_by_id.return_value = CLIENT_A
            mock_eng_repo.create.return_value = ENGAGEMENT_A
            result = create_engagement(body=body, current_user=USER_PARTNER_A)
        assert result["success"] is True
        assert result["data"]["engagement"]["id"] == "eng-a"

    def test_create_engagement_client_not_found(self):
        from routers.engagements import create_engagement
        from routers.engagements import EngagementCreate
        body = EngagementCreate(
            client_id="c-missing",
            service_type="Monthly Bookkeeping",
            fee_paise=500000,
            billing_cycle="Monthly",
            start_date="2026-01-01",
        )
        with patch("routers.engagements.client_repo") as mock_client_repo:
            mock_client_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                create_engagement(body=body, current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_create_engagement_tenant_isolation(self):
        from routers.engagements import create_engagement
        from routers.engagements import EngagementCreate
        body = EngagementCreate(
            client_id="c-b",
            service_type="Monthly Bookkeeping",
            fee_paise=500000,
            billing_cycle="Monthly",
            start_date="2026-01-01",
        )
        with patch("routers.engagements.client_repo") as mock_client_repo:
            mock_client_repo.find_by_id.return_value = CLIENT_B
            with pytest.raises(HTTPException) as exc_info:
                create_engagement(body=body, current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_create_engagement_invalid_fee(self):
        from routers.engagements import create_engagement
        from routers.engagements import EngagementCreate
        with pytest.raises(ValueError):
            EngagementCreate(
                client_id="c-a",
                service_type="Monthly Bookkeeping",
                fee_paise=0,
                billing_cycle="Monthly",
                start_date="2026-01-01",
            )


class TestUpdateEngagement:

    def test_update_engagement_succeeds(self):
        from routers.engagements import update_engagement
        from routers.engagements import EngagementUpdate
        body = EngagementUpdate(service_type="GST Compliance")
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ENGAGEMENT_A
            mock_repo.update.return_value = {**ENGAGEMENT_A, "service_type": "GST Compliance"}
            result = update_engagement(engagement_id="eng-a", body=body, current_user=USER_PARTNER_A)
        assert result["success"] is True

    def test_update_engagement_invalid_fee(self):
        from routers.engagements import update_engagement
        from routers.engagements import EngagementUpdate
        body = EngagementUpdate(fee_paise=0)
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ENGAGEMENT_A
            with pytest.raises(HTTPException) as exc_info:
                update_engagement(engagement_id="eng-a", body=body, current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 400

    def test_update_engagement_tenant_isolation(self):
        from routers.engagements import update_engagement
        from routers.engagements import EngagementUpdate
        body = EngagementUpdate(status="Inactive")
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {**ENGAGEMENT_A, "firm_id": FIRM_B}
            with pytest.raises(HTTPException) as exc_info:
                update_engagement(engagement_id="eng-a", body=body, current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404


class TestDeleteEngagement:

    def test_delete_engagement_succeeds(self):
        from routers.engagements import delete_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ENGAGEMENT_A
            mock_repo.update.return_value = {**ENGAGEMENT_A, "status": "Inactive"}
            result = delete_engagement(engagement_id="eng-a", current_user=USER_PARTNER_A)
        assert result["success"] is True
        mock_repo.update.assert_called_once_with("eng-a", {"status": "Inactive"})

    def test_delete_engagement_not_found(self):
        from routers.engagements import delete_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                delete_engagement(engagement_id="eng-missing", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_delete_engagement_tenant_isolation(self):
        from routers.engagements import delete_engagement
        with patch("routers.engagements.engagement_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {**ENGAGEMENT_A, "firm_id": FIRM_B}
            with pytest.raises(HTTPException) as exc_info:
                delete_engagement(engagement_id="eng-a", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404
