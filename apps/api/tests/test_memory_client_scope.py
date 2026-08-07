"""
Client-assignment scope on the AI memory router.

`memory_intelligence` imported no authz, so an AI profile of any client — the
firm's accumulated knowledge of how that client behaves, what they repeatedly
get wrong, their cash-flow signals — was readable by anyone in the firm, along
with every trigger, anomaly and year-end readiness report.

TWO SHAPES THAT ARE NOT "RESOLVE AND CHECK"

  * `ai_memory_triggers` and `pattern_anomalies` have a NULLABLE client_id. A
    trigger can be firm-level ("three clients missed the same deadline"), so a
    NULL is a firm-level row and not something to 404 — and it must survive the
    narrowing of a firm-wide list, because it belongs to everyone in the firm.

  * `POST /pipeline/run` and `POST /firm/profile/compute` are firm-WIDE
    computations: the pipeline loops every client in the firm and writes a
    profile, triggers, anomalies and a year-end report for each. There is no
    honest partial version — running it for a subset and reporting it as "the
    firm pipeline" would be worse than refusing — so these are limited to
    firm-wide roles with a **403**, not a 404. Nothing is being hidden; a
    capability is being refused, and the message names the per-client endpoint
    that the caller CAN use.
"""
import pytest
from fastapi import HTTPException

import routers.memory_intelligence as mem

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "role": "executive"}
PARTNER = {"id": "p1", "firm_id": FIRM, "auth_user_id": "ap", "role": "partner"}

TRIGGERS = {
    "TR-MINE": {"id": "TR-MINE", "firm_id": FIRM, "client_id": MINE},
    "TR-THEIRS": {"id": "TR-THEIRS", "firm_id": FIRM, "client_id": THEIRS},
    # Firm-level: no client at all.
    "TR-FIRM": {"id": "TR-FIRM", "firm_id": FIRM, "client_id": None},
}
ANOMALIES = {
    "AN-MINE": {"id": "AN-MINE", "firm_id": FIRM, "client_id": MINE},
    "AN-THEIRS": {"id": "AN-THEIRS", "firm_id": FIRM, "client_id": THEIRS},
}


class _Repo:
    def get_trigger(self, firm_id, tid): return TRIGGERS.get(tid)
    def get_anomaly(self, firm_id, aid): return ANOMALIES.get(aid)
    # These raise when reached, so a guard that ran AFTER the write would fail
    # loudly rather than pass quietly. The envelope test substitutes a
    # permissive subclass, since there the point is that handlers return.
    def acknowledge_trigger(self, *a, **k): raise AssertionError("reached the write")
    def dismiss_trigger(self, *a, **k): raise AssertionError("reached the write")
    def update_anomaly_status(self, *a, **k): raise AssertionError("reached the write")
    def list_triggers(self, *a, **k): return list(TRIGGERS.values())
    def list_anomalies(self, *a, **k): return list(ANOMALIES.values())
    def list_profiles(self, *a, **k): return [{"client_id": MINE}, {"client_id": THEIRS}]
    def list_year_end_reports(self, *a, **k): return [{"client_id": MINE}, {"client_id": THEIRS}]
    def get_current_profile(self, *a, **k): return {"client_id": MINE}
    def get_year_end_report(self, *a, **k): return {}
    def get_firm_profile(self, *a, **k): return {"firm_id": FIRM}


class _Pipeline:
    def run_full_pipeline(self, firm_id): return {}
    def compute_firm_profile(self, firm_id): return {}
    def compute_client_profile(self, firm_id, client_id): return {}
    def detect_repeat_issues(self, *a): return []
    def detect_deadline_at_risk(self, *a): return []
    def detect_cash_flow_warnings(self, *a): return []
    def detect_pattern_anomalies(self, *a): return []
    def detect_year_end_readiness(self, *a): return None


@pytest.fixture(autouse=True)
def repo(monkeypatch):
    monkeypatch.setattr(mem, "_get_repo", lambda: _Repo())


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(mem, "assert_client_access", _check)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Found while writing the tests below: the whole router was returning 500s
# ══════════════════════════════════════════════════════════════════════════════

def test_every_endpoint_returns_the_standard_envelope(monkeypatch):
    """All 14 endpoints called `api_response(data=...)` — without the REQUIRED
    first argument, `success`. Every one raised TypeError at runtime, so the
    entire router was dead. `memory_intelligence` was the only file in the
    codebase doing it, and nothing exercised these handlers until now.

    Asserting the envelope rather than just "it does not raise": the shape is
    the contract every other router keeps ({success, data, error}), and a
    handler that returned something else would be a different bug wearing the
    same disguise."""
    import inspect as _i
    from main import app

    monkeypatch.setattr(mem, "is_firmwide", lambda _u: True)
    monkeypatch.setattr(mem, "_get_pipeline", lambda: _Pipeline())

    # A permissive repo for THIS test only: the shared one raises on the
    # mutators so a late guard fails loudly, which is the right default
    # everywhere except here, where the point is that each handler returns.
    class _Permissive(_Repo):
        def acknowledge_trigger(self, *a, **k): return {}
        def dismiss_trigger(self, *a, **k): return {}
        def update_anomaly_status(self, *a, **k): return {}

    monkeypatch.setattr(mem, "_get_repo", lambda: _Permissive())

    checked = 0
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/memory"):
            continue
        kwargs = {"current_user": PARTNER}
        for name, param in _i.signature(r.endpoint).parameters.items():
            if name == "current_user":
                continue
            if name in ("client_id", "trigger_id", "anomaly_id"):
                kwargs[name] = {"client_id": MINE, "trigger_id": "TR-MINE",
                                "anomaly_id": "AN-MINE"}[name]
            elif name == "body":
                kwargs[name] = {"status": "reviewed"}
            elif param.default is not _i.Parameter.empty:
                kwargs[name] = param.default
            else:
                kwargs[name] = "2025-26"          # financial_year
        out = r.endpoint(**kwargs)
        assert set(out) == {"success", "data", "error"}, path
        assert out["success"] is True, path
        checked += 1
    assert checked >= 14, f"expected every memory endpoint, exercised {checked}"


# ══════════════════════════════════════════════════════════════════════════════
# Client-addressed endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_ai_profile_is_refused(deny):
    """The firm's accumulated knowledge about how a client behaves."""
    with pytest.raises(HTTPException) as e:
        mem.get_client_profile(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_clients_profile_is_returned(deny):
    mem.get_client_profile(MINE, current_user=USER)
    assert deny == [MINE]


def test_running_detection_on_another_clients_data_is_refused(deny, monkeypatch):
    """`/detect` reads the client's issues, deadlines and cash flow and writes
    triggers against them. The refusal has to come first."""
    monkeypatch.setattr(mem, "_get_pipeline",
                        lambda: pytest.fail("the pipeline ran despite the refusal"))
    with pytest.raises(HTTPException) as e:
        mem.detect_client_triggers(THEIRS, current_user=USER)
    assert e.value.status_code == 404


def test_another_clients_year_end_report_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        mem.get_year_end_report(THEIRS, "2025-26", current_user=USER)
    assert e.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Triggers and anomalies — nullable client_id
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_trigger_is_refused_before_the_write(deny):
    """_Repo.acknowledge_trigger raises if reached, so a guard that ran after
    the write would fail loudly rather than pass quietly."""
    with pytest.raises(HTTPException) as e:
        mem.acknowledge_trigger("TR-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_a_firm_level_trigger_is_not_404d_for_having_no_client(deny):
    """"Three clients missed the same deadline" belongs to the firm. Collapsing
    "no client" into "not found" would hide every firm-level trigger."""
    assert mem._assert_trigger_scope(USER, "TR-FIRM") is None
    assert deny == [None]          # still put to the check, as a firm-level row


def test_another_clients_anomaly_is_refused_before_the_write(deny):
    with pytest.raises(HTTPException) as e:
        mem.update_anomaly_status("AN-THEIRS", {"status": "reviewed"}, current_user=USER)
    assert e.value.status_code == 404


def test_an_unknown_trigger_is_the_same_404_as_a_forbidden_one(deny):
    with pytest.raises(HTTPException) as missing:
        mem._assert_trigger_scope(USER, "no-such-trigger")
    with pytest.raises(HTTPException) as hidden:
        mem._assert_trigger_scope(USER, "TR-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Lists
# ══════════════════════════════════════════════════════════════════════════════

def test_the_profile_list_is_narrowed(monkeypatch, deny):
    monkeypatch.setattr(mem, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r.get("client_id") == MINE])
    out = mem.list_profiles(limit=50, current_user=USER)
    assert out["data"]["profiles"] == [{"client_id": MINE}]


def test_the_year_end_report_list_is_narrowed(monkeypatch, deny):
    monkeypatch.setattr(mem, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r.get("client_id") == MINE])
    out = mem.list_year_end_reports(limit=20, current_user=USER)
    assert out["data"]["reports"] == [{"client_id": MINE}]


def test_a_firm_level_trigger_survives_the_list_narrowing(monkeypatch, deny):
    """filter_by_client keeps rows with no client_id. If it did not, narrowing
    the trigger feed would delete exactly the cross-client warnings the feature
    exists to surface."""
    monkeypatch.setattr(mem, "filter_by_client",
                        lambda _u, rows: [r for r in rows
                                          if not r.get("client_id") or r["client_id"] == MINE])
    out = mem.list_triggers(client_id=None, trigger_type=None, status="active",
                            limit=50, current_user=USER)
    assert [t["id"] for t in out["data"]["triggers"]] == ["TR-MINE", "TR-FIRM"]


def test_naming_a_client_checks_it_instead_of_narrowing(deny, monkeypatch):
    monkeypatch.setattr(mem, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        mem.list_anomalies(client_id=THEIRS, status="open", limit=50, current_user=USER)
    assert deny == [THEIRS]


# ══════════════════════════════════════════════════════════════════════════════
# Firm-wide computations — 403, not 404
# ══════════════════════════════════════════════════════════════════════════════

def test_the_full_pipeline_is_refused_to_an_assigned_role(monkeypatch):
    """run_full_pipeline loops EVERY client in the firm and writes a profile,
    triggers, anomalies and a year-end report for each."""
    monkeypatch.setattr(mem, "_get_pipeline",
                        lambda: pytest.fail("the pipeline ran despite the refusal"))
    monkeypatch.setattr(mem, "is_firmwide", lambda _u: False)
    with pytest.raises(HTTPException) as e:
        mem.run_pipeline(current_user=USER)
    assert e.value.status_code == 403


def test_the_refusal_says_what_the_caller_CAN_do(monkeypatch):
    """A bare "forbidden" leaves someone guessing. The message names the
    per-client endpoint that does the same work within their book."""
    monkeypatch.setattr(mem, "is_firmwide", lambda _u: False)
    with pytest.raises(HTTPException) as e:
        mem.run_pipeline(current_user=USER)
    assert "/api/memory/clients/{client_id}/detect" in e.value.detail


def test_403_not_404_because_nothing_is_being_hidden(monkeypatch):
    """Elsewhere in this sweep the answer is 404, so that a status code cannot
    be used to probe which ids exist. Here there is no id and no resource — a
    capability is being refused, and pretending the endpoint does not exist
    would be the misleading answer."""
    monkeypatch.setattr(mem, "is_firmwide", lambda _u: False)
    with pytest.raises(HTTPException) as e:
        mem.compute_firm_profile(current_user=USER)
    assert e.value.status_code == 403


def test_a_firmwide_role_may_still_run_the_pipeline(monkeypatch):
    """Partner and Manager legitimately see every client. Refusing them would
    break the feature rather than secure it."""
    ran = []
    monkeypatch.setattr(mem, "is_firmwide", lambda _u: True)
    monkeypatch.setattr(mem, "_get_pipeline",
                        lambda: type("P", (), {"run_full_pipeline": lambda _s, f: ran.append(f) or {}})())
    mem.run_pipeline(current_user=PARTNER)
    assert ran == [FIRM]


def test_the_firm_profile_READ_stays_open_to_the_whole_firm(monkeypatch):
    """firm_profiles has no client_id. The figures are firm-level and are what
    every member already sees on the dashboards — guarding the read would block
    a legitimate user without protecting anything."""
    monkeypatch.setattr(mem, "is_firmwide",
                        lambda _u: pytest.fail("the READ must not be role-gated"))
    monkeypatch.setattr(mem, "assert_client_access",
                        lambda *_a: pytest.fail("firm_profiles has no client to scope to"))
    mem.get_firm_profile(current_user=USER)
