"""
Client-assignment scope on the year-end REVIEWS router (year_end_reviews.py).

Every one of its 5 endpoints resolved its engagement by firm_id alone
(_get_mock_engagement/_get_db_engagement, both removed by this fix) and
never checked the caller's assignment to its client — a Manager or
Executive could submit, approve, send back for revision, or FINAL-APPROVE
(an irreversible lock — "approved" -> "locked" has no outgoing transition)
another staff member's client's engagement.

Fixed by delegating to year_end.py's own _assert_engagement_scope rather
than duplicating the check in a second file against the same table —
tested here at the year_end_reviews.py call sites, not re-tested at the
resolver's own internals (already covered by
test_year_end_engagements_client_scope.py).
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_reviews as yer

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}
PARTNER_USER = {"id": "u3", "firm_id": FIRM, "auth_user_id": "u3", "role": "Partner"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest. can_access_client is patched on
    routers.year_end (where _assert_engagement_scope actually calls it) —
    year_end_reviews.py itself never imports core.authz directly, it only
    imports the resolver by name."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ye, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_store():
    ye._MOCK_ENGAGEMENTS.clear()


def _seed(engagement_id, client_id, status, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "status": status, **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# submit_for_review
# ══════════════════════════════════════════════════════════════════════════

def test_submitting_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, "draft")
    with pytest.raises(HTTPException) as exc:
        yer.submit_for_review("E-THEIRS", yer.ReviewActionIn(),
                               current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert ye._MOCK_ENGAGEMENTS["E-THEIRS"]["status"] == "draft"


def test_submitting_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE, "draft")
    resp = yer.submit_for_review("E-MINE", yer.ReviewActionIn(),
                                  current_user=EXEC_USER)
    assert resp["data"]["status"] == "in_review"


# ══════════════════════════════════════════════════════════════════════════
# approve_review
# ══════════════════════════════════════════════════════════════════════════

def test_approving_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, "in_review")
    with pytest.raises(HTTPException) as exc:
        yer.approve_review("E-THEIRS", yer.ReviewActionIn(),
                            current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert ye._MOCK_ENGAGEMENTS["E-THEIRS"]["status"] == "in_review"


def test_approving_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE, "in_review")
    resp = yer.approve_review("E-MINE", yer.ReviewActionIn(),
                               current_user=MANAGER_USER)
    assert resp["data"]["status"] == "approved"


# ══════════════════════════════════════════════════════════════════════════
# request_revision
# ══════════════════════════════════════════════════════════════════════════

def test_requesting_revision_on_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, "in_review")
    with pytest.raises(HTTPException) as exc:
        yer.request_revision("E-THEIRS", yer.ReviewActionIn(),
                              current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert ye._MOCK_ENGAGEMENTS["E-THEIRS"]["status"] == "in_review"


def test_requesting_revision_on_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE, "in_review")
    resp = yer.request_revision("E-MINE", yer.ReviewActionIn(),
                                 current_user=MANAGER_USER)
    assert resp["data"]["status"] == "draft"


# ══════════════════════════════════════════════════════════════════════════
# final_approve — the irreversible lock
# ══════════════════════════════════════════════════════════════════════════

def test_final_approving_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, "approved")
    with pytest.raises(HTTPException) as exc:
        yer.final_approve("E-THEIRS", yer.ReviewActionIn(),
                           current_user=PARTNER_USER)
    assert exc.value.status_code == 404
    assert ye._MOCK_ENGAGEMENTS["E-THEIRS"]["status"] == "approved"


def test_final_approving_an_own_clients_engagement_is_allowed(deny, monkeypatch):
    monkeypatch.setattr(
        "services.year_end_workflow_service.lock_year_if_completing",
        lambda *a, **k: None,
    )
    _seed("E-MINE", MINE, "approved")
    resp = yer.final_approve("E-MINE", yer.ReviewActionIn(),
                              current_user=PARTNER_USER)
    assert resp["data"]["status"] == "locked"


# ══════════════════════════════════════════════════════════════════════════
# get_review_state
# ══════════════════════════════════════════════════════════════════════════

def test_getting_review_state_for_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, "in_review")
    with pytest.raises(HTTPException) as exc:
        yer.get_review_state("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_review_state_for_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE, "in_review")
    resp = yer.get_review_state("E-MINE", current_user=EXEC_USER)
    assert "steps" in resp["data"]


def test_getting_review_state_for_a_missing_engagement_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        yer.get_review_state("does-not-exist", current_user=EXEC_USER)
    _seed("E-THEIRS", THEIRS, "in_review")
    with pytest.raises(HTTPException) as exc_hidden:
        yer.get_review_state("E-THEIRS", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail
