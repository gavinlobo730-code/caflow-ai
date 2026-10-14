"""What an engagement SAYS about the work is read apart from what it CHARGES (POST-B-024, stage one).

WHAT WAS WRONG
    `fee_engagements` is one table holding two things: the scope of the work (which client, which service, whether the
    engagement is live) and the practice's fees (amount, billing cycle, notes). core/permissions reserves the second to
    a Partner (`billing:read`), and the audit of 14-10-2026 found the database does not enforce that: an assigned
    Manager, Executive or Reviewer reads the fee rows of their clients. Closing that is a Partner-only read policy, and
    the same audit found why it could not simply be added: five places ask the table the OTHER question, the scope, as
    the caller, and a rule on who reads fees would have answered them with an empty list and no error:

      * the Compliance tab said "No active service engagement is recorded... Add an engagement" to a Manager about a
        client who has one, and a Manager cannot add one;
      * `generate_due`, run from the same tab and from the GST filing-frequency edit, generated only the GST baseline
        and never the ITR, TDS or MCA obligations, and the response looked like success;
      * `itr_profile_for` could not see an audit engagement, so an audit client of a non-company type was given
        31 July instead of 31 October, with the wrong cause named;
      * the generate-obligations route answered 404 for an engagement that exists.

    This change moves every one of those off the caller's own read of the table and onto
    `EngagementRepository.find_scope`, which returns the four scope columns with the privileged client and the firm's
    own scope (the callers are authorised by rbac and `assert_client_access` first). Nothing about who may read fees
    changes yet: that is the migration that follows, and it lands only after this is merged and live.

WHAT IS ASSERTED
    * the scope read asks for the four scope columns and no fee column, is scoped to the firm, and uses the privileged
      client;
    * the three readers in the obligation service answer from it, and answer correctly when the caller's own read of the
      table would have been empty (the behaviour a Partner-only rule produces);
    * the obligation service reads engagements nowhere else (a rule over the whole module, not over three spellings);
    * the generate-obligations route and the new engagement-status route answer from it.

NEGATIVE CONTROL (each of these fails against the previous code)
    * test_the_ITR_profile_sees_an_audit_engagement_when_the_callers_own_read_is_empty
    * test_the_calendar_generator_reads_engagements_without_the_callers_row_security
    * test_the_obligation_service_reads_engagements_through_the_scope_read_only
    * test_generate_obligations_finds_the_engagement_the_caller_cannot_read_fees_of
    * test_the_engagement_status_route_exists_and_answers_from_the_scope
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from repositories import engagement_repository as er
from services import compliance_obligation_service as ob

API = Path(__file__).resolve().parents[1]
FIRM = "firm-001"
CLIENT = "c-001"
FEE_COLUMNS = ("fee_paise", "billing_cycle", "notes", "start_date", "assigned_to", "deadline")


# ── the scope read ─────────────────────────────────────────────────────────────────────────────────────────────────

class _Recorder:
    """A chainable stand-in for the privileged client that remembers what it was asked."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, cols):
        self.calls.append(("select", cols))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        class R:  # noqa: D401 - a result carrying .data
            data = self.rows
        return R()


def test_the_scope_read_asks_for_the_scope_columns_and_no_fee_column(monkeypatch):
    rec = _Recorder([{"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "Audit", "status": "Active"}])
    monkeypatch.setattr(er, "_USE_MOCK", False)
    monkeypatch.setattr(er.db_provider, "service_db", lambda: rec)
    out = er.engagement_repo.find_scope(FIRM, CLIENT)
    assert out and out[0]["service_type"] == "Audit"
    selects = [c[1] for c in rec.calls if c[0] == "select"]
    assert selects == [", ".join(er.SCOPE_COLUMNS)]
    assert not any(col in selects[0] for col in FEE_COLUMNS), "the scope read must never carry the practice's fees"
    assert ("table", "fee_engagements") in rec.calls
    assert ("eq", "firm_id", FIRM) in rec.calls, "the privileged client bypasses row security: the firm scope is the control"
    assert ("eq", "client_id", CLIENT) in rec.calls


def test_the_scope_read_by_id_is_confined_to_the_firm(monkeypatch):
    rec = _Recorder([])
    monkeypatch.setattr(er, "_USE_MOCK", False)
    monkeypatch.setattr(er.db_provider, "service_db", lambda: rec)
    assert er.engagement_repo.find_scope_by_id("e1", FIRM) is None
    assert ("eq", "id", "e1") in rec.calls and ("eq", "firm_id", FIRM) in rec.calls


def test_the_scope_columns_are_the_ones_the_generator_reads():
    """generate_for_engagement reads id, client_id and service_type off the row, and generate_due filters on status;
    a column dropped from the scope read would turn into a KeyError or a silent skip."""
    assert set(er.SCOPE_COLUMNS) >= {"id", "firm_id", "client_id", "service_type", "status"}
    assert not set(er.SCOPE_COLUMNS) & set(FEE_COLUMNS)


# ── the readers ────────────────────────────────────────────────────────────────────────────────────────────────────

class _Client:
    @staticmethod
    def find_by_id(client_id, firm_id=None):
        return {"id": client_id, "entity_type": "Partnership"}


def _the_caller_cannot_read_fee_rows(monkeypatch, scope_rows):
    """What a Partner-only read policy does to the caller's own query: an empty list, no error."""
    monkeypatch.setattr(ob.engagement_repo, "find_all", lambda *a, **k: [])
    monkeypatch.setattr(ob.engagement_repo, "find_by_id", lambda *a, **k: None)
    # raising=False so that against the previous code, which has no scope read, the test still fails on what it
    # ASSERTS (the wrong date, the wrong calendar) and not on a missing attribute.
    monkeypatch.setattr(ob.engagement_repo, "find_scope", lambda *a, **k: list(scope_rows), raising=False)


def test_the_ITR_profile_sees_an_audit_engagement_when_the_callers_own_read_is_empty(monkeypatch):
    _the_caller_cannot_read_fee_rows(monkeypatch, [
        {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "Tax Audit", "status": "Active"}])
    monkeypatch.setattr(ob, "client_repo", _Client)
    entity_type, has_audit = ob.itr_profile_for(CLIENT, FIRM)
    assert (entity_type, has_audit) == ("Partnership", True), (
        "an audit client of a non-company type is 31 October; read through the caller's own view of the fee table it "
        "was 31 July with the cause misnamed")


def test_a_lapsed_audit_engagement_is_still_not_evidence(monkeypatch):
    _the_caller_cannot_read_fee_rows(monkeypatch, [
        {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "Tax Audit", "status": "Closed"}])
    monkeypatch.setattr(ob, "client_repo", _Client)
    assert ob.itr_profile_for(CLIENT, FIRM)[1] is False


def test_the_calendar_generator_reads_engagements_without_the_callers_row_security(monkeypatch):
    seen = []
    _the_caller_cannot_read_fee_rows(monkeypatch, [
        {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "Income Tax Return", "status": "Active"}])
    monkeypatch.setattr(ob, "generate_for_engagement",
                        lambda firm, e, fy, actor=None: seen.append(e["id"]) or {"generated": 4, "skipped": 0})
    monkeypatch.setattr(ob, "generate_default_for_client",
                        lambda *a, **k: pytest.fail("a client WITH a live engagement must not be given the no-engagement fallback"))
    out = ob.generate_due(FIRM, client_id=CLIENT, financial_year="2025-26")
    assert seen == ["e1"] and out["generated"] == 4, (
        "the engagement was invisible to the caller's own read, so only the GST baseline was generated and the response "
        "still looked like success")


def test_has_active_engagement_answers_from_the_scope_and_does_not_swallow_an_outage(monkeypatch):
    _the_caller_cannot_read_fee_rows(monkeypatch, [
        {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "GST", "status": "In Progress"}])
    assert ob.has_active_engagement(CLIENT, FIRM) is True
    monkeypatch.setattr(ob.engagement_repo, "find_scope",
                        lambda *a, **k: [{"id": "e2", "service_type": "GST", "status": "Closed"}])
    assert ob.has_active_engagement(CLIENT, FIRM) is False

    def _down(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(ob.engagement_repo, "find_scope", _down)
    with pytest.raises(RuntimeError):
        ob.has_active_engagement(CLIENT, FIRM)  # an outage is an error, never "no engagement is recorded"


# ── the rule, not three spellings ──────────────────────────────────────────────────────────────────────────────────

def _calls_on(path: Path, repo_name: str, methods: set[str], inside: str | None = None):
    tree = ast.parse(path.read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and (inside is None or n.name == inside)]
    hits = []
    for fn in nodes:
        for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
            f = call.func
            if isinstance(f, ast.Attribute) and f.attr in methods and isinstance(f.value, ast.Name) and f.value.id == repo_name:
                hits.append((fn.name, f.attr))
    return hits


def test_the_obligation_service_reads_engagements_through_the_scope_read_only():
    path = API / "services" / "compliance_obligation_service.py"
    assert not _calls_on(path, "engagement_repo", {"find_all", "find_by_id", "list_by_status", "get_or_raise"}), (
        "an engagement read in this module answers for the CALLER's row security; once the fee tables are a Partner's "
        "to read it would return nothing to everyone else and the obligation calendar would shrink without an error")
    assert _calls_on(path, "engagement_repo", {"find_scope"}), "vacuity: the scope read must actually be used here"


def test_the_generate_obligations_route_reads_the_engagement_through_the_scope_read():
    path = API / "routers" / "engagements.py"
    assert not _calls_on(path, "engagement_repo", {"find_by_id"}, inside="generate_engagement_obligations")
    assert _calls_on(path, "engagement_repo", {"find_scope_by_id"}, inside="generate_engagement_obligations")


# ── the routes ─────────────────────────────────────────────────────────────────────────────────────────────────────

client = TestClient(app)
PARTNER = {"X-User-Role": "partner", "X-Firm-Id": FIRM, "X-User-Id": "user-001"}


@pytest.mark.usefixtures("dev_header_auth")
def test_generate_obligations_finds_the_engagement_the_caller_cannot_read_fees_of(monkeypatch):
    from routers import engagements as routes
    monkeypatch.setattr(routes.engagement_repo, "find_by_id", lambda *a, **k: None)  # the caller's own, blind read
    monkeypatch.setattr(routes.engagement_repo, "find_scope_by_id",
                        lambda i, firm: {"id": i, "firm_id": firm, "client_id": CLIENT,
                                         "service_type": "Monthly Bookkeeping", "status": "Active"})
    seen = []
    monkeypatch.setattr(ob, "generate_for_engagement",
                        lambda firm, e, fy, actor=None: seen.append(e["id"]) or {"generated": 1, "skipped": 0})
    res = client.post("/api/engagements/eng-001/generate-obligations", headers=PARTNER)
    assert res.status_code == 200, res.text
    assert seen == ["eng-001"]


@pytest.mark.usefixtures("dev_header_auth")
def test_generate_obligations_still_refuses_another_firms_engagement(monkeypatch):
    from routers import engagements as routes
    monkeypatch.setattr(routes.engagement_repo, "find_scope_by_id",
                        lambda i, firm: {"id": i, "firm_id": "firm-other", "client_id": CLIENT,
                                         "service_type": "Audit", "status": "Active"})
    res = client.post("/api/engagements/eng-001/generate-obligations", headers=PARTNER)
    assert res.status_code == 404, res.text


@pytest.mark.usefixtures("dev_header_auth")
def test_the_engagement_status_route_exists_and_answers_from_the_scope(monkeypatch):
    monkeypatch.setattr(ob.engagement_repo, "find_scope",
                        lambda firm, cid=None: [{"id": "e1", "firm_id": firm, "client_id": cid,
                                                 "service_type": "GST", "status": "Active"}])
    res = client.get(f"/api/compliance/engagement-status?client_id={CLIENT}", headers=PARTNER)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data == {"client_id": CLIENT, "has_active_engagement": True}

    monkeypatch.setattr(ob.engagement_repo, "find_scope", lambda firm, cid=None: [])
    res = client.get(f"/api/compliance/engagement-status?client_id={CLIENT}", headers=PARTNER)
    assert res.json()["data"]["has_active_engagement"] is False


@pytest.mark.usefixtures("dev_header_auth")
def test_the_engagement_status_route_needs_a_client():
    res = client.get("/api/compliance/engagement-status", headers=PARTNER)
    assert res.status_code == 422
