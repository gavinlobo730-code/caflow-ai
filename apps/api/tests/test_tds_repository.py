"""
Tests for TDS repository dual-mode pattern and router endpoints.

Verifies that:
- get_returns and get_deductions work in mock mode (no Supabase needed)
- Router endpoints return success responses (no 500s)
- Tenant isolation: firm B cannot see firm A's data
"""
import pytest

FIRM_A = "firm-001"
FIRM_B = "firm-999"
CLIENT_A = "c-001"

USER_A = {"auth_user_id": "dev-user", "firm_id": FIRM_A, "role": "Partner"}
USER_B = {"auth_user_id": "dev-user2", "firm_id": FIRM_B, "role": "Partner"}


# ─── Repository mock-mode tests ───────────────────────────────────────────────

class TestTDSRepositoryMockMode:
    def setup_method(self):
        from repositories.tds_repository import MOCK_TDS_RETURNS, MOCK_TDS_DEDUCTIONS
        MOCK_TDS_RETURNS.clear()
        MOCK_TDS_DEDUCTIONS.clear()

    def test_get_returns_empty_by_default(self):
        from repositories.tds_repository import tds_repo
        result = tds_repo.get_returns(client_id=CLIENT_A, firm_id=FIRM_A)
        assert result == []

    def test_get_returns_filters_by_client_and_firm(self):
        from repositories.tds_repository import tds_repo, MOCK_TDS_RETURNS
        MOCK_TDS_RETURNS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q1",
        })
        MOCK_TDS_RETURNS.append({
            "client_id": "c-002", "firm_id": FIRM_A,
            "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q1",
        })
        result = tds_repo.get_returns(client_id=CLIENT_A, firm_id=FIRM_A)
        assert len(result) == 1
        assert result[0]["client_id"] == CLIENT_A

    def test_get_returns_tenant_isolation(self):
        from repositories.tds_repository import tds_repo, MOCK_TDS_RETURNS
        MOCK_TDS_RETURNS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q1",
        })
        result = tds_repo.get_returns(client_id=CLIENT_A, firm_id=FIRM_B)
        assert result == []

    def test_get_deductions_empty_by_default(self):
        from repositories.tds_repository import tds_repo
        result = tds_repo.get_deductions(client_id=CLIENT_A, firm_id=FIRM_A)
        assert result == []

    def test_get_deductions_filters_by_financial_year(self):
        from repositories.tds_repository import tds_repo, MOCK_TDS_DEDUCTIONS
        MOCK_TDS_DEDUCTIONS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "financial_year": "2025-26", "quarter": "Q1", "section": "194J",
        })
        MOCK_TDS_DEDUCTIONS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "financial_year": "2024-25", "quarter": "Q4", "section": "194J",
        })
        result = tds_repo.get_deductions(client_id=CLIENT_A, firm_id=FIRM_A, financial_year="2025-26")
        assert len(result) == 1
        assert result[0]["financial_year"] == "2025-26"

    def test_get_deductions_filters_by_quarter(self):
        from repositories.tds_repository import tds_repo, MOCK_TDS_DEDUCTIONS
        MOCK_TDS_DEDUCTIONS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "financial_year": "2025-26", "quarter": "Q1", "section": "194C",
        })
        MOCK_TDS_DEDUCTIONS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "financial_year": "2025-26", "quarter": "Q2", "section": "194C",
        })
        result = tds_repo.get_deductions(client_id=CLIENT_A, firm_id=FIRM_A, quarter="Q1")
        assert len(result) == 1
        assert result[0]["quarter"] == "Q1"

    def test_get_deductions_tenant_isolation(self):
        from repositories.tds_repository import tds_repo, MOCK_TDS_DEDUCTIONS
        MOCK_TDS_DEDUCTIONS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "financial_year": "2025-26", "quarter": "Q1", "section": "194J",
        })
        result = tds_repo.get_deductions(client_id=CLIENT_A, firm_id=FIRM_B)
        assert result == []


# ─── Router endpoint tests (no 500s) ─────────────────────────────────────────

class TestTDSRouterEndpoints:
    def setup_method(self):
        from repositories.tds_repository import MOCK_TDS_RETURNS, MOCK_TDS_DEDUCTIONS
        MOCK_TDS_RETURNS.clear()
        MOCK_TDS_DEDUCTIONS.clear()

    def test_get_returns_endpoint_returns_200(self):
        from routers.tds import get_tds_returns
        result = get_tds_returns(client_id=CLIENT_A, user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"], list)
        assert result["error"] is None

    def test_get_deductions_endpoint_returns_200(self):
        from routers.tds import get_tds_deductions
        result = get_tds_deductions(client_id=CLIENT_A, user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"], list)
        assert result["error"] is None

    def test_get_deductions_with_fy_filter(self):
        from routers.tds import get_tds_deductions
        result = get_tds_deductions(
            client_id=CLIENT_A, financial_year="2025-26", quarter=None, user=USER_A
        )
        assert result["success"] is True
        assert isinstance(result["data"], list)

    def test_get_deductions_with_quarter_filter(self):
        from routers.tds import get_tds_deductions
        result = get_tds_deductions(
            client_id=CLIENT_A, financial_year=None, quarter="Q1", user=USER_A
        )
        assert result["success"] is True
        assert isinstance(result["data"], list)

    def test_returns_tenant_isolation_via_router(self):
        from routers.tds import get_tds_returns
        from repositories.tds_repository import MOCK_TDS_RETURNS
        MOCK_TDS_RETURNS.append({
            "client_id": CLIENT_A, "firm_id": FIRM_A,
            "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q1",
        })
        result_a = get_tds_returns(client_id=CLIENT_A, user=USER_A)
        result_b = get_tds_returns(client_id=CLIENT_A, user=USER_B)
        assert len(result_a["data"]) == 1
        assert len(result_b["data"]) == 0
