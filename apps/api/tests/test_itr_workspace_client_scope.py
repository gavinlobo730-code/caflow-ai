"""
Client-assignment scope on the ITR preparation workspace router.

create_snapshot, create_filing, create_disallowance, auto_detect_40a3,
create_deduction and create_bf_loss already guarded their body.client_id
before this phase — the classic "guards the body, not the record" shape
this whole sweep exists to close. Every OTHER endpoint didn't: five
query-param list endpoints (list_snapshots/list_filings/list_disallowances/
list_deductions/list_bf_losses) took a REQUIRED client_id with no check at
all, and six row-addressed endpoints (review_snapshot, transition_filing,
save_version, record_acknowledgement, update_disallowance_status,
utilize_loss) had no client check whatsoever — not even a firm check in
several of the underlying domain functions' mock branches.

Four new resolvers, one per client-bearing table (tax_computation_snapshots,
itr_filings, tax_disallowances, brought_forward_losses), each backed by a
new get_X(firm_id, x_id) domain function added specifically for this fix —
deliberately NOT using .single() (see get_bf_loss's docstring: Supabase's
real .single() raises on zero rows rather than returning None, the same bug
the year_end_adjustments.py phase found and fixed in that file).
"""
import pytest
from fastapi import HTTPException

import routers.itr_workspace as itr
from domain.income_tax.computation_workspace import (
    _MOCK_SNAPSHOTS, _MOCK_DISALLOWANCES, _MOCK_LOSSES,
)
from domain.income_tax.itr_workflow import _MOCK_FILINGS

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(itr, "assert_client_access", _assert)
    monkeypatch.setattr(itr, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    _MOCK_SNAPSHOTS.clear()
    _MOCK_DISALLOWANCES.clear()
    _MOCK_LOSSES.clear()
    _MOCK_FILINGS.clear()
    yield
    _MOCK_SNAPSHOTS.clear()
    _MOCK_DISALLOWANCES.clear()
    _MOCK_LOSSES.clear()
    _MOCK_FILINGS.clear()


def _seed(store, row_id, client_id, firm_id=FIRM, **extra):
    store[row_id] = {"id": row_id, "firm_id": firm_id, "client_id": client_id, **extra}


# ══════════════════════════════════════════════════════════════════════════════
# list_snapshots / _assert_snapshot_scope / review_snapshot
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_snapshots_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        itr.list_snapshots(client_id=THEIRS, financial_year="2025-26", current_user=EXEC_USER)


def test_listing_snapshots_for_your_own_client_still_works(deny):
    out = itr.list_snapshots(client_id=MINE, financial_year="2025-26", current_user=EXEC_USER)
    assert out["success"] is True
    assert deny == [MINE]


def test_snapshot_scope_refuses_another_clients_snapshot(deny):
    _seed(_MOCK_SNAPSHOTS, "S-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as e:
        itr._assert_snapshot_scope(EXEC_USER, "S-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_snapshot_scope_returns_your_own_snapshot(deny):
    _seed(_MOCK_SNAPSHOTS, "S-MINE", MINE)
    row = itr._assert_snapshot_scope(EXEC_USER, "S-MINE")
    assert row["id"] == "S-MINE"
    assert deny == [MINE]


def test_snapshot_scope_refuses_another_firms_snapshot_before_the_client_check(deny):
    _seed(_MOCK_SNAPSHOTS, "S-ALIEN", "c-x", firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        itr._assert_snapshot_scope(EXEC_USER, "S-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_snapshots_use_the_identical_message(deny):
    _seed(_MOCK_SNAPSHOTS, "S-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as missing:
        itr._assert_snapshot_scope(EXEC_USER, "S-NOPE")
    with pytest.raises(HTTPException) as hidden:
        itr._assert_snapshot_scope(EXEC_USER, "S-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Snapshot not found"


def test_reviewing_another_clients_snapshot_is_refused(deny):
    _seed(_MOCK_SNAPSHOTS, "S-THEIRS", THEIRS, status="draft")
    with pytest.raises(HTTPException):
        itr.review_snapshot("S-THEIRS", current_user=MANAGER_USER)
    assert _MOCK_SNAPSHOTS["S-THEIRS"]["status"] == "draft"


def test_reviewing_your_own_snapshot_still_works(deny):
    _seed(_MOCK_SNAPSHOTS, "S-MINE", MINE, status="draft")
    out = itr.review_snapshot("S-MINE", current_user=MANAGER_USER)
    assert out["data"]["status"] == "reviewed"


# ══════════════════════════════════════════════════════════════════════════════
# list_filings / _assert_filing_scope / transition_filing / save_version /
# record_acknowledgement — all three row-addressed endpoints share one table
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_filings_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        itr.list_filings(client_id=THEIRS, current_user=EXEC_USER)


def test_listing_filings_for_your_own_client_still_works(deny):
    out = itr.list_filings(client_id=MINE, current_user=EXEC_USER)
    assert out["success"] is True


def test_filing_scope_refuses_another_clients_filing(deny):
    _seed(_MOCK_FILINGS, "F-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as e:
        itr._assert_filing_scope(EXEC_USER, "F-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_filing_scope_returns_your_own_filing(deny):
    _seed(_MOCK_FILINGS, "F-MINE", MINE)
    row = itr._assert_filing_scope(EXEC_USER, "F-MINE")
    assert row["id"] == "F-MINE"


def test_filing_scope_refuses_another_firms_filing_before_the_client_check(deny):
    _seed(_MOCK_FILINGS, "F-ALIEN", "c-x", firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        itr._assert_filing_scope(EXEC_USER, "F-ALIEN")
    assert e.value.status_code == 404
    assert deny == []


def test_missing_and_hidden_filings_use_the_identical_message(deny):
    _seed(_MOCK_FILINGS, "F-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as missing:
        itr._assert_filing_scope(EXEC_USER, "F-NOPE")
    with pytest.raises(HTTPException) as hidden:
        itr._assert_filing_scope(EXEC_USER, "F-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Filing not found"


def test_transitioning_another_clients_filing_is_refused(deny):
    _seed(_MOCK_FILINGS, "F-THEIRS", THEIRS, status="draft")
    with pytest.raises(HTTPException):
        itr.transition_filing("F-THEIRS", itr.TransitionFilingRequest(new_status="review"),
                              current_user=MANAGER_USER)
    assert _MOCK_FILINGS["F-THEIRS"]["status"] == "draft"


def test_saving_a_version_on_another_clients_filing_is_refused(deny):
    _seed(_MOCK_FILINGS, "F-THEIRS", THEIRS)
    with pytest.raises(HTTPException):
        itr.save_version("F-THEIRS", itr.SaveVersionRequest(json_payload={}),
                         current_user=EXEC_USER)
    assert "F-THEIRS" not in _MOCK_VERSIONS_after_seed()


def _MOCK_VERSIONS_after_seed():
    from domain.income_tax.itr_workflow import _MOCK_VERSIONS
    return _MOCK_VERSIONS


def test_saving_a_version_on_your_own_filing_still_works(deny):
    _seed(_MOCK_FILINGS, "F-MINE", MINE)
    out = itr.save_version("F-MINE", itr.SaveVersionRequest(json_payload={"a": 1}),
                           current_user=EXEC_USER)
    assert out["data"]["json_payload"] == {"a": 1}


def test_acknowledging_another_clients_filing_is_refused(deny):
    _seed(_MOCK_FILINGS, "F-THEIRS", THEIRS, status="ready_for_filing")
    with pytest.raises(HTTPException):
        itr.record_acknowledgement(
            "F-THEIRS", itr.AcknowledgementRequest(acknowledgement_number="ACK1", filing_date="2026-07-31"),
            current_user=MANAGER_USER)
    assert _MOCK_FILINGS["F-THEIRS"]["status"] == "ready_for_filing"


def test_acknowledging_your_own_filing_still_works(deny):
    _seed(_MOCK_FILINGS, "F-MINE", MINE, status="ready_for_filing")
    out = itr.record_acknowledgement(
        "F-MINE", itr.AcknowledgementRequest(acknowledgement_number="ACK1", filing_date="2026-07-31"),
        current_user=MANAGER_USER)
    assert out["data"]["status"] == "filed"


# ══════════════════════════════════════════════════════════════════════════════
# list_disallowances / _assert_disallowance_scope / update_disallowance_status
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_disallowances_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        itr.list_disallowances(client_id=THEIRS, financial_year="2025-26", current_user=EXEC_USER)


def test_listing_disallowances_for_your_own_client_still_works(deny):
    out = itr.list_disallowances(client_id=MINE, financial_year="2025-26", current_user=EXEC_USER)
    assert out["success"] is True


def test_disallowance_scope_refuses_another_clients_row(deny):
    _seed(_MOCK_DISALLOWANCES, "D-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as e:
        itr._assert_disallowance_scope(EXEC_USER, "D-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_disallowance_scope_refuses_another_firms_row_before_the_client_check(deny):
    _seed(_MOCK_DISALLOWANCES, "D-ALIEN", "c-x", firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        itr._assert_disallowance_scope(EXEC_USER, "D-ALIEN")
    assert e.value.status_code == 404
    assert deny == []


def test_missing_and_hidden_disallowances_use_the_identical_message(deny):
    _seed(_MOCK_DISALLOWANCES, "D-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as missing:
        itr._assert_disallowance_scope(EXEC_USER, "D-NOPE")
    with pytest.raises(HTTPException) as hidden:
        itr._assert_disallowance_scope(EXEC_USER, "D-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Disallowance not found"


def test_updating_another_clients_disallowance_status_is_refused(deny):
    _seed(_MOCK_DISALLOWANCES, "D-THEIRS", THEIRS, status="pending")
    with pytest.raises(HTTPException):
        itr.update_disallowance_status("D-THEIRS", itr.DisallowanceStatusRequest(status="accepted"),
                                       current_user=MANAGER_USER)
    assert _MOCK_DISALLOWANCES["D-THEIRS"]["status"] == "pending"


def test_updating_your_own_disallowance_status_still_works(deny):
    _seed(_MOCK_DISALLOWANCES, "D-MINE", MINE, status="pending")
    out = itr.update_disallowance_status("D-MINE", itr.DisallowanceStatusRequest(status="accepted"),
                                         current_user=MANAGER_USER)
    assert out["data"]["status"] == "accepted"


# ══════════════════════════════════════════════════════════════════════════════
# list_deductions
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_deductions_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        itr.list_deductions(client_id=THEIRS, financial_year="2025-26", current_user=EXEC_USER)


def test_listing_deductions_for_your_own_client_still_works(deny):
    out = itr.list_deductions(client_id=MINE, financial_year="2025-26", current_user=EXEC_USER)
    assert out["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# list_bf_losses / _assert_bf_loss_scope / utilize_loss
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_bf_losses_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        itr.list_bf_losses(client_id=THEIRS, current_user=EXEC_USER)


def test_listing_bf_losses_for_your_own_client_still_works(deny):
    out = itr.list_bf_losses(client_id=MINE, current_user=EXEC_USER)
    assert out["success"] is True


def test_bf_loss_scope_refuses_another_clients_row(deny):
    _seed(_MOCK_LOSSES, "L-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as e:
        itr._assert_bf_loss_scope(EXEC_USER, "L-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_bf_loss_scope_refuses_another_firms_row_before_the_client_check(deny):
    _seed(_MOCK_LOSSES, "L-ALIEN", "c-x", firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        itr._assert_bf_loss_scope(EXEC_USER, "L-ALIEN")
    assert e.value.status_code == 404
    assert deny == []


def test_missing_and_hidden_bf_losses_use_the_identical_message(deny):
    _seed(_MOCK_LOSSES, "L-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as missing:
        itr._assert_bf_loss_scope(EXEC_USER, "L-NOPE")
    with pytest.raises(HTTPException) as hidden:
        itr._assert_bf_loss_scope(EXEC_USER, "L-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Loss record not found"


def test_utilizing_another_clients_loss_is_refused(deny):
    _seed(_MOCK_LOSSES, "L-THEIRS", THEIRS,
         utilized_amount_paise=0, original_amount_paise=100000)
    with pytest.raises(HTTPException):
        itr.utilize_loss("L-THEIRS", itr.UtilizeLossRequest(utilization_paise=5000),
                         current_user=EXEC_USER)
    assert _MOCK_LOSSES["L-THEIRS"]["utilized_amount_paise"] == 0


def test_utilizing_your_own_loss_still_works(deny):
    _seed(_MOCK_LOSSES, "L-MINE", MINE,
         utilized_amount_paise=0, original_amount_paise=100000)
    out = itr.utilize_loss("L-MINE", itr.UtilizeLossRequest(utilization_paise=5000),
                           current_user=EXEC_USER)
    assert out["data"]["utilized_amount_paise"] == 5000
