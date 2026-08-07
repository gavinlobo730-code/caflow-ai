"""
Tenant and client-assignment scope on the lifecycle router (and one endpoint in
ai_insights that shared its worst bug).

TWO CROSS-TENANT LEAKS — the most serious thing this sweep has turned up.
    Two endpoints accepted a `firm_id` from the CALLER and preferred it over the
    one in the token (`firm_id or current_user["firm_id"]`):

        GET /api/lifecycle/onboarding/checklist/active?firm_id=<any firm>
        GET /api/ai-insights/cross-client?firm_id=<any firm>

    Any authenticated user of any firm could read another **firm's** data by
    supplying its id. That is a tenant boundary, not a client-assignment one —
    different firms are different customers — and the second endpoint's entire
    purpose is to aggregate across a firm's client base.

    Both parameters are GONE rather than validated. There is no legitimate
    caller: a firm's own users get their firm from the token, and cross-firm
    access belongs to the platform-admin surface (routers/platform.py, gated by
    require_platform_admin). A parameter that only an attacker has a use for
    should not exist.

CLIENT SCOPE — the lifecycle runs from before a client exists to after they
renew, so what counts as client data differs per table. See the router's own
header comment; the tests below pin each case, including the ones where the
right answer is "do not guard this".
"""
import inspect

import pytest
from fastapi import HTTPException

import routers.lifecycle as lc
import routers.ai_insights as ai

FIRM, OTHER_FIRM = "firm-1", "firm-2"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "manager"}


# ══════════════════════════════════════════════════════════════════════════════
# Tenant isolation — the firm_id parameter is gone
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("endpoint", [
    pytest.param(lc.list_active_onboardings, id="lifecycle/onboarding/checklist/active"),
    pytest.param(ai.cross_client_patterns, id="ai-insights/cross-client"),
])
def test_no_endpoint_still_accepts_a_firm_id_from_the_caller(endpoint):
    """Signature-level, deliberately: the fix is the ABSENCE of a parameter, and
    the only way to assert an absence is to look at what the endpoint accepts.
    A test that merely called it with the right firm would pass either way."""
    params = inspect.signature(endpoint).parameters
    assert "firm_id" not in params, (
        f"{endpoint.__name__} takes firm_id from the request again — that lets "
        f"any authenticated user read another firm's data by supplying its id.")


def test_the_active_checklist_view_uses_the_callers_own_firm(monkeypatch):
    monkeypatch.setattr(lc, "_db", lambda: None)
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_WORKFLOWS", [
        {"id": "W1", "firm_id": FIRM, "client_id": MINE,
         "status": "in_progress", "entity_type": "client"},
        {"id": "W2", "firm_id": OTHER_FIRM, "client_id": "c-x",
         "status": "in_progress", "entity_type": "client"},
    ])
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_TASKS", [])
    monkeypatch.setattr(lc, "filter_by_client", lambda _u, rows: rows)
    out = lc.list_active_onboardings(current_user=USER)
    assert [w["workflow"]["id"] if "workflow" in w else w["id"] for w in out["data"]] == ["W1"]


def test_cross_client_patterns_uses_the_callers_own_firm(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai, "get_cross_client_patterns",
                        lambda firm_id: seen.setdefault("firm_id", firm_id) or [])
    ai.cross_client_patterns(current_user=USER)
    assert seen == {"firm_id": FIRM}


# ══════════════════════════════════════════════════════════════════════════════
# Client scope
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(lc, "assert_client_access", _check)
    return seen


@pytest.fixture
def seeded(monkeypatch):
    monkeypatch.setattr(lc, "_db", lambda: None)
    monkeypatch.setattr(lc, "_MOCK_PROPOSALS", [
        {"id": "P-MINE", "firm_id": FIRM, "client_id": MINE, "status": "sent"},
        {"id": "P-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "sent"},
        # A proposal to a LEAD: no client yet.
        {"id": "P-LEAD", "firm_id": FIRM, "client_id": None,
         "lead_id": "L1", "status": "draft"},
    ])
    monkeypatch.setattr(lc, "_MOCK_RENEWALS", [
        {"id": "R-MINE", "firm_id": FIRM, "client_id": MINE, "status": "pending"},
        {"id": "R-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "pending"},
    ])
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_WORKFLOWS", [
        {"id": "W-MINE", "firm_id": FIRM, "client_id": MINE,
         "status": "in_progress", "entity_type": "client"},
        {"id": "W-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
         "status": "in_progress", "entity_type": "client"},
    ])
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_TASKS", [])


def test_another_managers_proposal_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        lc._assert_row_scope(None, USER, "proposals", "P-THEIRS", "Proposal",
                             lc._MOCK_PROPOSALS)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_a_proposal_to_a_lead_is_not_404d_for_having_no_client(deny, seeded):
    """proposals.client_id is nullable — a proposal can precede the client.
    Collapsing "no client" into "not found" would 404 the whole pre-sales
    pipeline."""
    assert lc._assert_row_scope(None, USER, "proposals", "P-LEAD", "Proposal",
                                lc._MOCK_PROPOSALS) is None
    assert deny == [None]      # still put to the check, as a firm-level row


def test_another_managers_renewal_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        lc._assert_row_scope(None, USER, "renewals", "R-THEIRS", "Renewal",
                             lc._MOCK_RENEWALS)
    assert e.value.status_code == 404


def test_an_unknown_id_is_the_same_404_as_a_forbidden_one(deny, seeded):
    with pytest.raises(HTTPException) as missing:
        lc._assert_row_scope(None, USER, "renewals", "nope", "Renewal", lc._MOCK_RENEWALS)
    with pytest.raises(HTTPException) as hidden:
        lc._assert_row_scope(None, USER, "renewals", "R-THEIRS", "Renewal", lc._MOCK_RENEWALS)
    assert missing.value.status_code == hidden.value.status_code == 404


def test_the_lookup_is_still_firm_scoped(seeded):
    other = {"id": "u2", "firm_id": OTHER_FIRM, "role": "partner"}
    assert lc._row_owner(None, other, "renewals", "R-MINE", lc._MOCK_RENEWALS) == (False, None)


def test_a_child_row_is_scoped_through_its_parent(deny, seeded):
    """onboarding_checklist_steps and onboarding_tasks carry a workflow_id and no
    client_id — client data in a table with no client column, the same shape as
    workflow_builder's executions and failures."""
    with pytest.raises(HTTPException) as e:
        lc._assert_via_parent(None, USER, "onboarding_workflows", "W-THEIRS",
                              "Onboarding workflow", lc._MOCK_ONBOARDING_WORKFLOWS)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_converting_a_lead_onto_someone_elses_client_is_refused(deny, seeded):
    """LeadConvertIn.client_id is optional: absent means "create a new client",
    present means "attach to an EXISTING one". The second was unchecked, and it
    spawns onboarding workflows and lifecycle events against that client.

    Caught by the exemption-honesty test — this endpoint had been written off as
    "converts a lead, so there is no client yet", which was true of only one of
    its two paths."""
    class _Data:
        client_id = THEIRS

    with pytest.raises(HTTPException) as e:
        lc.convert_lead("L1", _Data(), current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_converting_a_lead_into_a_NEW_client_is_not_blocked(deny, seeded, monkeypatch):
    """client_id=None means the client does not exist yet. There is nothing to
    authorise, and refusing would break the entire conversion flow."""
    monkeypatch.setattr(lc, "_MOCK_LEADS", [])

    class _Data:
        client_id = None

    with pytest.raises(HTTPException) as e:
        lc.convert_lead("no-such-lead", _Data(), current_user=USER)
    assert e.value.status_code == 404          # the LEAD is missing, not a refusal
    assert deny == [None]                      # checked, and passed


def test_the_renewals_list_is_narrowed_to_your_own_book(seeded, monkeypatch):
    """renewals.client_id is NOT NULL, and the endpoint takes no client_id at
    all — so narrowing is the only thing standing between an Executive and every
    client's renewal dates."""
    monkeypatch.setattr(lc, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r.get("client_id") == MINE])
    out = lc.list_renewals(status=None, financial_year=None, limit=50, offset=0,
                           current_user=USER)
    assert [r["id"] for r in out["data"]] == ["R-MINE"]


def test_a_lead_stage_proposal_survives_the_list_narrowing(seeded, monkeypatch):
    """filter_by_client keeps rows with no client_id. Without that, narrowing the
    firm-wide proposal list would delete the pre-client pipeline."""
    monkeypatch.setattr(lc, "filter_by_client",
                        lambda _u, rows: [r for r in rows
                                          if not r.get("client_id") or r["client_id"] == MINE])
    out = lc.list_proposals(lead_id=None, client_id=None, status=None, limit=50,
                            offset=0, current_user=USER)
    assert [p["id"] for p in out["data"]] == ["P-MINE", "P-LEAD"]


def test_naming_a_client_checks_it_instead_of_narrowing(deny, seeded, monkeypatch):
    monkeypatch.setattr(lc, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        lc.list_proposals(lead_id=None, client_id=THEIRS, status=None, limit=50,
                          offset=0, current_user=USER)
    assert deny == [THEIRS]


# ══════════════════════════════════════════════════════════════════════════════
# Leads are firm-level — guarding them would be inventing a client
# ══════════════════════════════════════════════════════════════════════════════

def test_the_leads_endpoints_do_not_consult_client_scope(monkeypatch):
    """`leads` has a firm_id and no client_id (migration 059). A lead is not yet
    a client, so there is no assignment to check. This is the counterweight to
    the sweep: over-guarding would block the whole pre-sales pipeline.

    (Whether leads SHOULD carry a scope of their own is an open product
    question, recorded in the audit doc — not something to invent here.)"""
    for fn in (lc.list_leads, lc.create_lead, lc.update_lead):
        src = inspect.getsource(fn)
        assert "assert_client_access" not in src, f"{fn.__name__} guards a lead"


def test_leads_are_still_firm_scoped(monkeypatch):
    """Exempt from CLIENT scope, not from tenant scope.

    Driven against the REAL query path: the mock branch of list_leads filters on
    stage and assigned_to but not firm_id, which is a dev-mode artifact (mock
    mode runs without a database, so there is no other tenant's data to reach)
    and not what ships. Asserting against the mock would have tested the
    artifact instead of the behaviour."""
    filters = {}

    class _Q:
        def select(self, *_a): return self
        def eq(self, k, v): filters[k] = v; return self
        def neq(self, *_a): return self
        def or_(self, *_a): return self
        def order(self, *_a, **_k): return self
        def range(self, *_a): return self
        def execute(self): return type("R", (), {"data": [{"id": "L1"}]})()

    monkeypatch.setattr(lc, "_db", lambda: type("DB", (), {"table": lambda _s, _n: _Q()})())
    out = lc.list_leads(stage=None, assigned_to=None, limit=50, offset=0,
                        current_user=USER)
    assert filters == {"firm_id": FIRM}
    assert [l["id"] for l in out["data"]] == ["L1"]
