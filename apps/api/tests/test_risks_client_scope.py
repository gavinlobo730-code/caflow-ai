"""
Client-assignment scope on the risks router — the risk register
(document_risks.client_id NOT NULL, migration 004, plus risks derived from
compliance_records).

list_risks took client_id from the query string and only ever narrowed it INTO
the firm-scoped query, never checking it — and with client_id omitted, the
default the UI actually uses, it returned every client's risks in the firm,
each row carrying client_id AND client_name. client_risks is addressed directly
by client_id and had no check at all. update_risk_status is row-addressed by
risk_id — so main.py's mount-level client guard never fires on it — and
domain/risk_engine.update_risk scopes its UPDATE by id+firm_id only; the new
get_risk lookup plus the _assert_risk_scope resolver close it.
"""
import pytest
from fastapi import HTTPException

import domain.risk_engine as engine
import routers.risks as rk

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

    monkeypatch.setattr(rk, "assert_client_access", _assert)
    monkeypatch.setattr(rk, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_risks — client_id from the query string, AND the omitted case
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_risks_is_refused(deny, monkeypatch):
    called = []
    monkeypatch.setattr(rk, "get_all_risks", lambda **kw: called.append(kw) or [])
    with pytest.raises(HTTPException) as e:
        rk.list_risks(severity=None, client_id=THEIRS, status="open", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]
    assert not called   # refused before the engine ever ran


def test_listing_your_own_clients_risks_still_works(deny, monkeypatch):
    rows = [{"id": "R1", "client_id": MINE}]
    monkeypatch.setattr(rk, "get_all_risks", lambda **kw: rows)
    monkeypatch.setattr(rk, "filter_by_client", lambda user, items, key="client_id": items)
    out = rk.list_risks(severity=None, client_id=MINE, status="open", current_user=USER)
    assert out["data"] == rows
    assert deny == [MINE]


def test_omitting_client_id_no_longer_returns_the_whole_firms_risks(deny, monkeypatch):
    """The default call — no client_id at all — previously returned every
    client's risks in the firm, named. filter_by_client covers that case."""
    rows = [{"id": "R1", "client_id": MINE}, {"id": "R2", "client_id": THEIRS}]
    monkeypatch.setattr(rk, "get_all_risks", lambda **kw: rows)
    monkeypatch.setattr(rk, "filter_by_client",
                        lambda user, items, key="client_id":
                        [r for r in items if r.get(key) != THEIRS])
    out = rk.list_risks(severity=None, client_id=None, status="open", current_user=USER)
    assert [r["id"] for r in out["data"]] == ["R1"]
    assert deny == []   # nothing named to assert on; the narrowing does the work


# ══════════════════════════════════════════════════════════════════════════════
# client_risks — client_id in the path
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_risk_summary_is_refused(deny, monkeypatch):
    called = []
    monkeypatch.setattr(rk, "get_client_risk_summary",
                        lambda cid, **kw: called.append(cid) or {})
    with pytest.raises(HTTPException) as e:
        rk.client_risks(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert not called


def test_reading_your_own_clients_risk_summary_still_works(deny, monkeypatch):
    monkeypatch.setattr(rk, "get_client_risk_summary", lambda cid, **kw: {"risk_score": 42})
    out = rk.client_risks(MINE, current_user=USER)
    assert out["data"]["risk_score"] == 42
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_risk_scope + update_risk_status
# ══════════════════════════════════════════════════════════════════════════════

def test_risk_scope_refuses_another_clients_record(deny, monkeypatch):
    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: {"id": rid, "client_id": THEIRS})
    assert rk._assert_risk_scope(USER, "R1") is None
    assert deny == [THEIRS]


def test_risk_scope_allows_your_own_record(deny, monkeypatch):
    row = {"id": "R1", "client_id": MINE}
    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: row)
    assert rk._assert_risk_scope(USER, "R1") == row
    assert deny == [MINE]


def test_risk_scope_returns_none_for_a_missing_row(deny, monkeypatch):
    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: None)
    assert rk._assert_risk_scope(USER, "nope") is None
    assert deny == []


def test_updating_another_clients_risk_is_refused(deny, monkeypatch):
    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: {"id": rid, "client_id": THEIRS})
    written = []
    monkeypatch.setattr(rk, "update_risk", lambda *a, **kw: written.append(a) or {"id": "R1"})
    out = rk.update_risk_status("R1", resolution_status="resolved", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Risk not found"
    assert not written   # refused BEFORE the update ever ran


def test_updating_your_own_risk_still_works(deny, monkeypatch):
    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: {"id": rid, "client_id": MINE})
    monkeypatch.setattr(rk, "update_risk",
                        lambda *a, **kw: {"id": "R1", "resolution_status": "resolved"})
    out = rk.update_risk_status("R1", resolution_status="resolved", current_user=USER)
    assert out["data"]["resolution_status"] == "resolved"


def test_a_missing_risk_and_a_hidden_one_read_identically(deny, monkeypatch):
    monkeypatch.setattr(rk, "update_risk", lambda *a, **kw: None)

    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: None)
    missing = rk.update_risk_status("R1", resolution_status="resolved", current_user=USER)

    monkeypatch.setattr(rk, "get_risk", lambda rid, firm_id=None: {"id": rid, "client_id": THEIRS})
    hidden = rk.update_risk_status("R1", resolution_status="resolved", current_user=USER)

    assert missing == hidden
    assert missing["error"] == "Risk not found"


# ══════════════════════════════════════════════════════════════════════════════
# domain/risk_engine.get_risk — the new lookup half of the resolver
# ══════════════════════════════════════════════════════════════════════════════

def test_get_risk_finds_a_mock_engine_risk():
    """Mock mode must resolve from the SAME source set update_risk writes to,
    otherwise a risk could be updatable but not resolvable to its owner."""
    known = engine.MOCK_RISKS[0]
    assert engine.get_risk(known["id"], firm_id=FIRM) == known


def test_get_risk_finds_a_mock_document_risk():
    from domain.document_intelligence_service import MOCK_DOCUMENT_RISKS
    engine_ids = {r["id"] for r in engine.MOCK_RISKS}
    extra = next(r for r in MOCK_DOCUMENT_RISKS if r["id"] not in engine_ids)
    assert engine.get_risk(extra["id"], firm_id=FIRM) == extra


def test_get_risk_returns_none_for_an_unknown_id():
    assert engine.get_risk("no-such-risk", firm_id=FIRM) is None


def test_every_updatable_mock_risk_is_also_resolvable():
    """The invariant the resolver depends on: anything update_risk can write,
    get_risk can first attribute to a client."""
    from domain.document_intelligence_service import MOCK_DOCUMENT_RISKS
    for risk in list(engine.MOCK_RISKS) + list(MOCK_DOCUMENT_RISKS):
        assert engine.get_risk(risk["id"], firm_id=FIRM) is not None, risk["id"]
