"""
Client-assignment scope on the document_intelligence_v2 router — AI
government-notice extraction (# CA REVIEW REQUIRED, no government portal is
ever touched here — only Groq extraction + task/notification creation).

extract_notice takes client_id in the body and had no check at all — an
unassigned Executive/Manager could spend the firm's Groq quota extracting and
persisting a notice against another staff member's client. list_notices took
the required client_id from the query string and never checked it.
get_notice/update_notice_status/approve_notice are row-addressed by
notice_id and checked only firm_id; new _assert_notice_scope resolver
closes all three.
"""
import pytest
from fastapi import HTTPException

import routers.document_intelligence_v2 as di

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access/
    can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(di, "assert_client_access", _assert)
    monkeypatch.setattr(di, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# extract_notice — client_id in the body
# ══════════════════════════════════════════════════════════════════════════════

def test_extracting_a_notice_for_another_clients_is_refused(deny, monkeypatch):
    monkeypatch.setattr(di, "_run_notice_extraction", lambda text: (None, None, 200))
    body = di.ExtractNoticeRequest(client_id=THEIRS, document_text="notice text")
    with pytest.raises(HTTPException) as e:
        di.extract_notice(body, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_extracting_a_notice_for_another_clients_never_calls_groq(deny, monkeypatch):
    """Authorization must be checked BEFORE spending the firm's Groq quota."""
    called = []
    monkeypatch.setattr(di, "_run_notice_extraction", lambda text: called.append(text) or (None, None, 200))
    body = di.ExtractNoticeRequest(client_id=THEIRS, document_text="notice text")
    with pytest.raises(HTTPException):
        di.extract_notice(body, current_user=USER)
    assert not called


def test_extracting_a_notice_for_your_own_client_still_works(deny, monkeypatch):
    extracted = {"notice_type": "gst_scrutiny", "authority": "GSTN", "reference_no": "R1"}
    monkeypatch.setattr(di, "_run_notice_extraction", lambda text: (extracted, None, 200))
    body = di.ExtractNoticeRequest(client_id=MINE, document_text="notice text")
    out = di.extract_notice(body, current_user=USER)
    assert out["data"]["client_id"] == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# list_notices — client_id from the query string
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_notices_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        di.list_notices(client_id=THEIRS, status=None, limit=50, offset=0, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_notices_still_works(deny):
    out = di.list_notices(client_id=MINE, status=None, limit=50, offset=0, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_notice_scope + get_notice/update_notice_status/approve_notice
# ══════════════════════════════════════════════════════════════════════════════

def test_notice_scope_refuses_another_clients_record(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": THEIRS}})
    assert di._assert_notice_scope(USER, "N1") is None
    assert deny == [THEIRS]


def test_notice_scope_allows_your_own_record(deny, monkeypatch):
    row = {"id": "N1", "client_id": MINE}
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": row})
    assert di._assert_notice_scope(USER, "N1") == row
    assert deny == [MINE]


def test_notice_scope_returns_none_for_a_missing_row(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {})
    assert di._assert_notice_scope(USER, "nope") is None
    assert deny == []   # can_access_client never reached — nothing to check


def test_getting_another_clients_notice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": THEIRS}})
    out = di.get_notice("N1", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Notice not found"


def test_getting_your_own_notice_still_works(deny, monkeypatch):
    row = {"id": "N1", "client_id": MINE}
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": row})
    out = di.get_notice("N1", current_user=USER)
    assert out["data"]["id"] == "N1"


def test_updating_status_of_another_clients_notice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": THEIRS, "status": "open"}})
    body = di.UpdateNoticeStatusRequest(status="closed")
    out = di.update_notice_status("N1", body, current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Notice not found"


def test_updating_status_of_your_own_notice_still_works(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": MINE, "status": "open"}})
    body = di.UpdateNoticeStatusRequest(status="closed")
    out = di.update_notice_status("N1", body, current_user=USER)
    assert out["data"]["status"] == "closed"


def test_approving_another_clients_notice_is_refused(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": THEIRS}})
    out = di.approve_notice("N1", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Notice not found"


def test_approving_your_own_notice_still_works(deny, monkeypatch):
    monkeypatch.setattr(di, "_MOCK_NOTICES", {"N1": {"id": "N1", "client_id": MINE}})
    out = di.approve_notice("N1", current_user=USER)
    assert out["data"]["ca_approved"] is True
