"""
Client-assignment scope on the health (client health scoring) router.

get_client_health, get_dimension_detail, list_scores, get_score,
get_score_history and list_overrides already guarded before this phase
(assert_client_access or filter_by_client). This phase closes the rest:
calculate_score and create_override are row-addressed by client_id with NO
guard at all; deactivate_override and resolve_alert are row-addressed by
their own id, firm-scoped only in live mode and not even that in mock mode
(health_overrides.client_id / health_alerts.client_id are both NOT NULL,
migration 059); recalculate_all is a firm-wide WRITE now confined to the
caller's own book (rbac("client","write") admits Manager, assignment-scoped
under M3, not just Partner); health_dashboard returned NAMED critical/
at-risk client rows and alerts firm-wide, unfiltered — a bigger leak than a
count, closed with the same filter_by_client already used by list_scores/
list_alerts in this same file, plus a pre-existing firm-boundary gap in its
mock branch (_MOCK_SCORES is one process-wide store with no firm filter).
"""
import pytest
from fastapi import HTTPException

import routers.health as hl

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest. Patches assert_client_access and
    can_access_client on the router module. Also forces mock mode
    (_db() -> None) unless a test overrides it for the live-mode path."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(hl, "assert_client_access", _assert)
    monkeypatch.setattr(hl, "can_access_client", _can)
    monkeypatch.setattr(hl, "_db", lambda: None)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    hl._MOCK_SCORES.clear()
    hl._MOCK_OVERRIDES.clear()
    hl._MOCK_ALERTS.clear()
    yield
    hl._MOCK_SCORES.clear()
    hl._MOCK_OVERRIDES.clear()
    hl._MOCK_ALERTS.clear()


# ══════════════════════════════════════════════════════════════════════════════
# calculate_score
# ══════════════════════════════════════════════════════════════════════════════

def test_calculating_another_clients_score_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        hl.calculate_score(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]
    assert THEIRS not in hl._MOCK_SCORES


def test_calculating_your_own_clients_score_still_works(deny):
    out = hl.calculate_score(MINE, current_user=USER)
    assert out["data"]["client_id"] == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# create_override
# ══════════════════════════════════════════════════════════════════════════════

def _override_body():
    return hl.OverrideIn(override_score=75, reason="manual review")


def test_creating_an_override_for_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        hl.create_override(THEIRS, _override_body(), current_user=USER)
    assert hl._MOCK_OVERRIDES == []


def test_creating_an_override_for_your_own_client_still_works(deny):
    out = hl.create_override(MINE, _override_body(), current_user=USER)
    assert out["data"]["client_id"] == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_override_scope + deactivate_override
# ══════════════════════════════════════════════════════════════════════════════

def _seed_overrides():
    hl._MOCK_OVERRIDES.extend([
        {"id": "O-MINE", "firm_id": FIRM, "client_id": MINE, "is_active": True},
        {"id": "O-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "is_active": True},
        {"id": "O-ALIEN", "firm_id": "firm-2", "client_id": "c-x", "is_active": True},
    ])


def test_override_scope_refuses_another_clients_override(deny):
    _seed_overrides()
    with pytest.raises(HTTPException) as e:
        hl._assert_override_scope(USER, "O-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_override_scope_returns_your_own_override(deny):
    _seed_overrides()
    row = hl._assert_override_scope(USER, "O-MINE")
    assert row["id"] == "O-MINE"
    assert deny == [MINE]


def test_override_scope_refuses_another_firms_override_before_the_client_check(deny):
    _seed_overrides()
    with pytest.raises(HTTPException) as e:
        hl._assert_override_scope(USER, "O-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_overrides_use_the_identical_message(deny):
    _seed_overrides()
    with pytest.raises(HTTPException) as missing:
        hl._assert_override_scope(USER, "O-NOPE")
    with pytest.raises(HTTPException) as hidden:
        hl._assert_override_scope(USER, "O-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Override not found"


def test_deactivating_another_clients_override_is_refused(deny):
    _seed_overrides()
    with pytest.raises(HTTPException):
        hl.deactivate_override("O-THEIRS", current_user=USER)
    assert [o["is_active"] for o in hl._MOCK_OVERRIDES if o["id"] == "O-THEIRS"] == [True]


def test_deactivating_your_own_override_still_works(deny):
    _seed_overrides()
    out = hl.deactivate_override("O-MINE", current_user=USER)
    assert out["data"]["is_active"] is False


# ══════════════════════════════════════════════════════════════════════════════
# _assert_alert_scope + resolve_alert
# ══════════════════════════════════════════════════════════════════════════════

def _seed_alerts():
    hl._MOCK_ALERTS.extend([
        {"id": "A-MINE", "firm_id": FIRM, "client_id": MINE, "is_resolved": False, "severity": "warning"},
        {"id": "A-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "is_resolved": False, "severity": "critical"},
        {"id": "A-ALIEN", "firm_id": "firm-2", "client_id": "c-x", "is_resolved": False, "severity": "critical"},
    ])


def test_alert_scope_refuses_another_clients_alert(deny):
    _seed_alerts()
    with pytest.raises(HTTPException) as e:
        hl._assert_alert_scope(USER, "A-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_alert_scope_returns_your_own_alert(deny):
    _seed_alerts()
    row = hl._assert_alert_scope(USER, "A-MINE")
    assert row["id"] == "A-MINE"
    assert deny == [MINE]


def test_alert_scope_refuses_another_firms_alert_before_the_client_check(deny):
    _seed_alerts()
    with pytest.raises(HTTPException) as e:
        hl._assert_alert_scope(USER, "A-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_alerts_use_the_identical_message(deny):
    _seed_alerts()
    with pytest.raises(HTTPException) as missing:
        hl._assert_alert_scope(USER, "A-NOPE")
    with pytest.raises(HTTPException) as hidden:
        hl._assert_alert_scope(USER, "A-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Alert not found"


def test_resolving_another_clients_alert_is_refused(deny):
    _seed_alerts()
    with pytest.raises(HTTPException):
        hl.resolve_alert("A-THEIRS", hl.AlertResolveIn(), current_user=USER)
    assert [a["is_resolved"] for a in hl._MOCK_ALERTS if a["id"] == "A-THEIRS"] == [False]


def test_resolving_your_own_alert_still_works(deny):
    _seed_alerts()
    out = hl.resolve_alert("A-MINE", hl.AlertResolveIn(), current_user=USER)
    assert out["data"]["is_resolved"] is True


# ══════════════════════════════════════════════════════════════════════════════
# recalculate_all — confine-the-run, not a list to narrow
# ══════════════════════════════════════════════════════════════════════════════

class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def upsert(self, *_a, **_k): return self
    def insert(self, *_a, **_k): return self
    def execute(self):
        class _R: pass
        r = _R(); r.data = self.rows
        return r


class _FakeDb:
    def __init__(self, clients):
        self.clients = clients
        self.recalculated = []
    def table(self, name):
        if name == "clients":
            return _FakeQuery(self.clients)
        return _FakeQuery([])
    def rpc(self, *a, **k):
        return _FakeQuery([])


def test_recalculate_all_runs_firm_wide_for_a_firmwide_caller(monkeypatch):
    db = _FakeDb([{"id": "c-a"}, {"id": "c-b"}, {"id": "c-c"}])
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: None)
    recalculated = []
    monkeypatch.setattr(hl, "_calculate_scores_db",
                        lambda db, client_id, firm_id: recalculated.append(client_id) or {
                            "overall_score": 80, "health_grade": "Good",
                        })
    partner = {**USER, "role": "Partner"}
    out = hl.recalculate_all(current_user=partner)
    assert sorted(recalculated) == ["c-a", "c-b", "c-c"]
    assert out["data"]["updated"] == 3


def test_recalculate_all_confines_to_assigned_clients_for_a_scoped_caller(monkeypatch):
    db = _FakeDb([{"id": "c-a"}, {"id": "c-b"}, {"id": "c-c"}])
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: {"c-a", "c-b"})
    recalculated = []
    monkeypatch.setattr(hl, "_calculate_scores_db",
                        lambda db, client_id, firm_id: recalculated.append(client_id) or {
                            "overall_score": 80, "health_grade": "Good",
                        })
    out = hl.recalculate_all(current_user=USER)
    assert sorted(recalculated) == ["c-a", "c-b"]
    assert "c-c" not in recalculated
    assert out["data"]["updated"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# health_dashboard
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard_narrows_critical_and_at_risk_clients(deny, monkeypatch):
    hl._MOCK_SCORES.update({
        MINE: {"client_id": MINE, "firm_id": FIRM, "overall_score": 20,
               "grade": "Critical", "is_critical": True, "is_at_risk": False},
        THEIRS: {"client_id": THEIRS, "firm_id": FIRM, "overall_score": 25,
                 "grade": "Critical", "is_critical": True, "is_at_risk": False},
    })
    monkeypatch.setattr(hl, "filter_by_client",
                        lambda user, rows, key="client_id": [r for r in rows if r.get(key) != THEIRS])
    out = hl.health_dashboard(current_user=USER)
    ids = {c["client_id"] for c in out["data"]["critical_clients"]}
    assert ids == {MINE}


class _DashboardFakeQuery(_FakeQuery):
    def order(self, *_a, **_k): return self


class _DashboardFakeDb:
    """Returns controlled rows per table, mirroring health_dashboard's live
    branch — MINE and THEIRS both critical, so a dropped filter_by_client
    call would let THEIRS leak through undetected by the mock-mode tests
    above (which never reach this branch at all)."""
    def __init__(self):
        self.tables = {
            "health_scores": [
                {"client_id": MINE, "overall_score": 20, "grade": "Critical",
                 "is_critical": True, "is_at_risk": False},
                {"client_id": THEIRS, "overall_score": 15, "grade": "Critical",
                 "is_critical": True, "is_at_risk": False},
            ],
            "health_alerts": [
                {"id": "A-MINE", "client_id": MINE, "severity": "critical"},
                {"id": "A-THEIRS", "client_id": THEIRS, "severity": "critical"},
            ],
        }
    def table(self, name):
        return _DashboardFakeQuery(self.tables.get(name, []))


def test_dashboard_narrows_the_live_mode_branch_too(monkeypatch):
    monkeypatch.setattr(hl, "_db", lambda: _DashboardFakeDb())
    monkeypatch.setattr(hl, "filter_by_client",
                        lambda user, rows, key="client_id": [r for r in rows if r.get(key) != THEIRS])
    out = hl.health_dashboard(current_user=USER)
    ids = {c["client_id"] for c in out["data"]["critical_clients"]}
    assert ids == {MINE}
    alert_ids = {a["id"] for a in out["data"]["top_alerts"]}
    assert alert_ids == {"A-MINE"}


def test_dashboard_excludes_scores_from_another_firm_in_mock_mode(deny, monkeypatch):
    """Pre-existing firm-boundary gap: _MOCK_SCORES had no firm filter at
    all in this endpoint, unlike every other endpoint in this router."""
    hl._MOCK_SCORES.update({
        MINE: {"client_id": MINE, "firm_id": FIRM, "overall_score": 90,
               "grade": "Healthy", "is_critical": False, "is_at_risk": False},
        "alien": {"client_id": "alien", "firm_id": "firm-2", "overall_score": 10,
                  "grade": "Critical", "is_critical": True, "is_at_risk": False},
    })
    monkeypatch.setattr(hl, "filter_by_client", lambda user, rows, key="client_id": rows)
    out = hl.health_dashboard(current_user=USER)
    assert out["data"]["critical_clients"] == []
    assert out["data"]["average_score"] == 90
