"""
DSC (Digital Signature Certificate) tracker — backend unit tests.

Covers:
  - Create valid DSC (200, returns record, real DB column names)
  - Validation: invalid PAN (422), issued_date after expiry_date (422)
  - Duplicate prevention (same pan + dsc_type + expiry_date → 409)
  - List scoped to firm
  - Update changes a field
  - Renew extends expiry_date
  - Soft-delete (subsequent list excludes it)
  - firm_id isolation (firm B cannot see firm A's DSC record)

Runs in mock mode: the router's dsc_repo uses the in-memory _MOCK_DSC store.
Endpoint functions are called directly with current_user (same style as the
sibling test_client_lifecycle / test_engagement_letters suites).
"""
import pytest
from fastapi import HTTPException

from routers.dsc import (
    create_dsc, list_dsc, update_dsc, renew_dsc, delete_dsc,
    DSCCreate, DSCUpdate, DSCRenew,
)
from repositories.dsc_repository import _MOCK_DSC

FIRM_A = "firm-aaaa-0001"
FIRM_B = "firm-bbbb-0002"

USER_MANAGER_A = {
    "auth_user_id": "u-manager-a",
    "firm_id": FIRM_A,
    "role": "Manager",
    "email": "manager@firmA.com",
}
USER_PARTNER_A = {
    "auth_user_id": "u-partner-a",
    "firm_id": FIRM_A,
    "role": "Partner",
    "email": "partner@firmA.com",
}
USER_MANAGER_B = {
    "auth_user_id": "u-manager-b",
    "firm_id": FIRM_B,
    "role": "Manager",
    "email": "manager@firmB.com",
}


def _clear():
    _MOCK_DSC.clear()


def _valid_body(**overrides):
    base = dict(
        holder_name="CA Ramesh Kumar",
        pan="ABCDE1234F",
        dsc_type="Class 3",
        purpose="Income Tax",
        issued_date="2026-01-01",
        expiry_date="2028-01-01",
        issued_by="eMudhra",
        token_no="TKN-001",
    )
    base.update(overrides)
    return DSCCreate(**base)


# ─── Create ───────────────────────────────────────────────────────────────────

class TestCreateDSC:

    def setup_method(self):
        _clear()

    def test_create_valid_returns_record(self):
        result = create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        assert result["success"] is True
        assert result["error"] is None
        rec = result["data"]["dsc_record"]
        assert rec["holder_name"] == "CA Ramesh Kumar"
        assert rec["firm_id"] == FIRM_A
        # Real DB column names — never issue_date / issuing_ca.
        assert rec["issued_date"] == "2026-01-01"
        assert rec["issued_by"] == "eMudhra"
        assert rec["pan"] == "ABCDE1234F"
        assert "id" in rec

    def test_pan_uppercased(self):
        result = create_dsc(body=_valid_body(pan="abcde1234f"), current_user=USER_MANAGER_A)
        assert result["data"]["dsc_record"]["pan"] == "ABCDE1234F"

    def test_create_without_pan_allowed(self):
        result = create_dsc(body=_valid_body(pan=None), current_user=USER_MANAGER_A)
        assert result["data"]["dsc_record"]["pan"] is None

    def test_invalid_pan_returns_422(self):
        with pytest.raises(HTTPException) as exc:
            create_dsc(body=_valid_body(pan="INVALID"), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422
        assert "PAN" in exc.value.detail

    def test_empty_holder_name_returns_422(self):
        with pytest.raises(HTTPException) as exc:
            create_dsc(body=_valid_body(holder_name="   "), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_bad_dsc_type_returns_422(self):
        with pytest.raises(HTTPException) as exc:
            create_dsc(body=_valid_body(dsc_type="Class 1"), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_issued_after_expiry_returns_422(self):
        with pytest.raises(HTTPException) as exc:
            create_dsc(
                body=_valid_body(issued_date="2028-06-01", expiry_date="2028-01-01"),
                current_user=USER_MANAGER_A,
            )
        assert exc.value.status_code == 422

    def test_unparseable_expiry_returns_422(self):
        with pytest.raises(HTTPException) as exc:
            create_dsc(body=_valid_body(expiry_date="not-a-date"), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_duplicate_returns_409(self):
        create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        with pytest.raises(HTTPException) as exc:
            # Same pan + dsc_type + expiry_date → duplicate.
            create_dsc(body=_valid_body(holder_name="Someone Else"), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 409

    def test_different_expiry_not_duplicate(self):
        create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        result = create_dsc(body=_valid_body(expiry_date="2029-01-01"), current_user=USER_MANAGER_A)
        assert result["success"] is True


# ─── List ─────────────────────────────────────────────────────────────────────

class TestListDSC:

    def setup_method(self):
        _clear()

    def test_list_returns_created_records(self):
        create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        create_dsc(body=_valid_body(pan="PQRSX6789L", expiry_date="2027-03-01"),
                   current_user=USER_MANAGER_A)
        result = list_dsc(current_user=USER_MANAGER_A)
        assert result["data"]["total"] == 2
        assert len(result["data"]["dsc_records"]) == 2

    def test_list_ordered_by_expiry(self):
        create_dsc(body=_valid_body(pan="AAAAA1111A", expiry_date="2029-01-01"),
                   current_user=USER_MANAGER_A)
        create_dsc(body=_valid_body(pan="BBBBB2222B", expiry_date="2027-01-01"),
                   current_user=USER_MANAGER_A)
        rows = list_dsc(current_user=USER_MANAGER_A)["data"]["dsc_records"]
        assert rows[0]["expiry_date"] == "2027-01-01"
        assert rows[1]["expiry_date"] == "2029-01-01"

    def test_empty_firm_returns_empty(self):
        result = list_dsc(current_user=USER_MANAGER_A)
        assert result["data"]["total"] == 0
        assert result["data"]["dsc_records"] == []


# ─── Update ───────────────────────────────────────────────────────────────────

class TestUpdateDSC:

    def setup_method(self):
        _clear()

    def _created_id(self):
        return create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)["data"]["dsc_record"]["id"]

    def test_update_changes_field(self):
        dsc_id = self._created_id()
        result = update_dsc(dsc_id=dsc_id, body=DSCUpdate(holder_name="CA New Name"),
                            current_user=USER_MANAGER_A)
        assert result["data"]["dsc_record"]["holder_name"] == "CA New Name"

    def test_update_issued_by(self):
        dsc_id = self._created_id()
        result = update_dsc(dsc_id=dsc_id, body=DSCUpdate(issued_by="NSDL e-Governance"),
                            current_user=USER_MANAGER_A)
        assert result["data"]["dsc_record"]["issued_by"] == "NSDL e-Governance"

    def test_update_invalid_pan_returns_422(self):
        dsc_id = self._created_id()
        with pytest.raises(HTTPException) as exc:
            update_dsc(dsc_id=dsc_id, body=DSCUpdate(pan="BAD"), current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_update_issued_after_expiry_returns_422(self):
        dsc_id = self._created_id()
        with pytest.raises(HTTPException) as exc:
            update_dsc(dsc_id=dsc_id, body=DSCUpdate(issued_date="2030-01-01"),
                       current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_update_missing_returns_404(self):
        with pytest.raises(HTTPException) as exc:
            update_dsc(dsc_id="no-such-id", body=DSCUpdate(holder_name="X"),
                       current_user=USER_MANAGER_A)
        assert exc.value.status_code == 404


# ─── Renew ────────────────────────────────────────────────────────────────────

class TestRenewDSC:

    def setup_method(self):
        _clear()

    def _created_id(self):
        return create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)["data"]["dsc_record"]["id"]

    def test_renew_extends_expiry(self):
        dsc_id = self._created_id()
        result = renew_dsc(dsc_id=dsc_id, body=DSCRenew(new_expiry_date="2030-01-01"),
                           current_user=USER_MANAGER_A)
        assert result["data"]["dsc_record"]["expiry_date"] == "2030-01-01"

    def test_renew_updates_issued_and_token(self):
        dsc_id = self._created_id()
        result = renew_dsc(
            dsc_id=dsc_id,
            body=DSCRenew(new_expiry_date="2030-01-01", new_issued_date="2028-01-01", token_no="TKN-NEW"),
            current_user=USER_MANAGER_A,
        )
        rec = result["data"]["dsc_record"]
        assert rec["issued_date"] == "2028-01-01"
        assert rec["token_no"] == "TKN-NEW"

    def test_renew_issued_after_expiry_returns_422(self):
        dsc_id = self._created_id()
        with pytest.raises(HTTPException) as exc:
            renew_dsc(dsc_id=dsc_id,
                      body=DSCRenew(new_expiry_date="2029-01-01", new_issued_date="2030-01-01"),
                      current_user=USER_MANAGER_A)
        assert exc.value.status_code == 422

    def test_renew_missing_returns_404(self):
        with pytest.raises(HTTPException) as exc:
            renew_dsc(dsc_id="ghost", body=DSCRenew(new_expiry_date="2030-01-01"),
                      current_user=USER_MANAGER_A)
        assert exc.value.status_code == 404


# ─── Delete (soft) ────────────────────────────────────────────────────────────

class TestDeleteDSC:

    def setup_method(self):
        _clear()

    def test_delete_soft_deletes_and_hides_from_list(self):
        dsc_id = create_dsc(body=_valid_body(), current_user=USER_PARTNER_A)["data"]["dsc_record"]["id"]
        result = delete_dsc(dsc_id=dsc_id, current_user=USER_PARTNER_A)
        assert result["success"] is True
        assert result["data"]["deleted"] is True
        # Subsequent list excludes it.
        listing = list_dsc(current_user=USER_PARTNER_A)
        assert listing["data"]["total"] == 0
        ids = [r["id"] for r in listing["data"]["dsc_records"]]
        assert dsc_id not in ids

    def test_delete_missing_returns_404(self):
        with pytest.raises(HTTPException) as exc:
            delete_dsc(dsc_id="no-such-id", current_user=USER_PARTNER_A)
        assert exc.value.status_code == 404

    def test_deleted_record_cannot_be_updated(self):
        dsc_id = create_dsc(body=_valid_body(), current_user=USER_PARTNER_A)["data"]["dsc_record"]["id"]
        delete_dsc(dsc_id=dsc_id, current_user=USER_PARTNER_A)
        with pytest.raises(HTTPException) as exc:
            update_dsc(dsc_id=dsc_id, body=DSCUpdate(holder_name="X"), current_user=USER_PARTNER_A)
        assert exc.value.status_code == 404


# ─── Firm isolation ───────────────────────────────────────────────────────────

class TestFirmIsolation:

    def setup_method(self):
        _clear()

    def test_firm_b_cannot_see_firm_a_record(self):
        create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        result_b = list_dsc(current_user=USER_MANAGER_B)
        assert result_b["data"]["total"] == 0
        assert result_b["data"]["dsc_records"] == []

    def test_firm_b_cannot_update_firm_a_record(self):
        dsc_id = create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)["data"]["dsc_record"]["id"]
        with pytest.raises(HTTPException) as exc:
            update_dsc(dsc_id=dsc_id, body=DSCUpdate(holder_name="Hacked"),
                       current_user=USER_MANAGER_B)
        assert exc.value.status_code == 404

    def test_firm_b_cannot_delete_firm_a_record(self):
        dsc_id = create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)["data"]["dsc_record"]["id"]
        with pytest.raises(HTTPException) as exc:
            delete_dsc(dsc_id=dsc_id, current_user=USER_MANAGER_B)
        assert exc.value.status_code == 404

    def test_duplicate_check_scoped_to_firm(self):
        # Same pan+type+expiry in a different firm is NOT a duplicate.
        create_dsc(body=_valid_body(), current_user=USER_MANAGER_A)
        result_b = create_dsc(body=_valid_body(), current_user=USER_MANAGER_B)
        assert result_b["success"] is True
