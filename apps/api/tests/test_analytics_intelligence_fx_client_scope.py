"""
Client-assignment scope on the analytics / intelligence / hsn / fx-reports /
currencies cluster.

Two distinct shapes here.

1. NAMED per-client aggregates read firm-wide. analytics.profitability and
   analytics.revenue-vs-effort each build a by_client list carrying
   client_name alongside revenue, cost, margin and a health status — the
   commercial position of the firm's entire book. intelligence's
   compliance-risk / relationship-health / recommendations emit one row PER
   CLIENT with client_name, and none of the three services had a narrowing
   parameter at all. analytics.clients was already narrowed by the M6 #6 fix
   and is pinned here so it stays that way.

   Firm-level TOTALS are handled per endpoint rather than by one blanket rule,
   and both directions are pinned by a test so neither reads as an oversight:
   analytics.clients keeps its firm-wide total_minutes (a SEPARATE firm-wide
   query, naming no client), while analytics.profitability's firm_metrics
   narrow with the book — they are summed from the very per-client dicts being
   filtered, so leaving them wide would derive them from rows the caller cannot
   see and would let an Executive recover the firm's position by subtraction.

2. Mount-guard-covered reads that named no guard of their own: fx-reports (5),
   currencies/policy, hsn/search. Each now calls assert_client_access where the
   read happens.
"""
import pytest
from fastapi import HTTPException

import routers.analytics as an
import routers.intelligence as intel
import services.intelligence_service as isvc

FIRM, OTHER = "firm-1", "firm-2"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}


@pytest.fixture
def only_mine(monkeypatch):
    """effective_client_ids -> {MINE}. Patched on core.authz, which every
    module under test imports from at call time."""
    import core.authz as authz
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: {MINE})
    monkeypatch.setattr(intel, "effective_client_ids", lambda user: {MINE})
    return {MINE}


# ══════════════════════════════════════════════════════════════════════════════
# intelligence_service — the three per-client scorers
# ══════════════════════════════════════════════════════════════════════════════

def _patch_clients(monkeypatch, rows):
    import repositories.client_repository as cr
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: rows)


CLIENTS = [
    {"id": MINE, "client_name": "Mine Ltd"},
    {"id": THEIRS, "client_name": "Theirs Ltd"},
]


def test_compliance_risk_narrows_to_assigned_clients(monkeypatch):
    _patch_clients(monkeypatch, CLIENTS)
    import repositories.compliance_records_repository as rr
    monkeypatch.setattr(rr.compliance_records_repo, "find_all", lambda **kw: [])

    out = isvc.compute_compliance_risk(FIRM, {MINE})
    names = {c["client_name"] for c in out["clients"]}
    assert names == {"Mine Ltd"}


def test_compliance_risk_none_means_firm_wide(monkeypatch):
    """None is the Partner/Manager case — the F2 convention, not 'deny all'."""
    _patch_clients(monkeypatch, CLIENTS)
    import repositories.compliance_records_repository as rr
    monkeypatch.setattr(rr.compliance_records_repo, "find_all", lambda **kw: [])

    out = isvc.compute_compliance_risk(FIRM, None)
    assert {c["client_name"] for c in out["clients"]} == {"Mine Ltd", "Theirs Ltd"}


def test_relationship_health_narrows_to_assigned_clients(monkeypatch):
    _patch_clients(monkeypatch, CLIENTS)
    import repositories.task_repository as tr
    import repositories.invoice_repository as ir
    monkeypatch.setattr(tr.task_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(ir.invoice_repo, "find_all", lambda **kw: [])

    out = isvc.compute_relationship_health(FIRM, {MINE})
    assert {c["client_name"] for c in out["clients"]} == {"Mine Ltd"}


def test_recommendations_never_names_an_unassigned_client(monkeypatch):
    """compute_recommendations is built entirely from the other three, so
    narrowing at the source has to cover it — it interpolates client_name
    straight into user-facing recommendation titles."""
    monkeypatch.setattr(
        isvc, "compute_compliance_risk",
        lambda firm_id, allowed=None: {"clients": [
            {"client_id": THEIRS, "client_name": "Theirs Ltd", "risk_level": "critical",
             "overdue_count": 3, "due_soon_count": 1, "risk_score": 90},
        ] if allowed is None else []},
    )
    # Must also honour `allowed`, or the pass-through into this call is not
    # load-bearing and stripping it survives mutation (it did, first time round).
    monkeypatch.setattr(
        isvc, "compute_relationship_health",
        lambda firm_id, allowed=None: {"clients": [
            {"client_id": THEIRS, "client_name": "Theirs Ltd", "health_level": "critical",
             "health_score": 10, "overdue_tasks": 2, "overdue_invoices": 1,
             "outstanding_paise": 500_00},
        ] if allowed is None else []},
    )
    monkeypatch.setattr(isvc, "compute_journal_suggestions",
                        lambda firm_id, client_id=None, allowed_client_ids=None:
                        {"suggestions": [], "month": "2026-08"})

    out = isvc.compute_recommendations(FIRM, {MINE})
    assert all("Theirs Ltd" not in r["title"] for r in out["recommendations"])
    assert all(r.get("client_id") != THEIRS for r in out["recommendations"])


def test_journal_suggestions_narrows_when_no_client_id_given(monkeypatch):
    """The default (client_id=None) read spans the whole firm, and every
    suggestion carries the client_id it came from."""
    import domain.accounting_service as acc
    entries = [
        {"id": f"e{i}", "client_id": cid, "status": "posted",
         "narration": "Rent", "entry_type": "Journal",
         "entry_date": f"2026-0{m}-01", "lines": [{"account_id": "a1"}]}
        for cid in (MINE, THEIRS) for i, m in enumerate((5, 6), start=1)
    ]
    monkeypatch.setattr(acc.accounting_service, "list_journal_entries",
                        lambda **kw: entries)

    out = isvc.compute_journal_suggestions(FIRM, None, {MINE})
    assert {s["client_id"] for s in out["suggestions"]} <= {MINE}


# ══════════════════════════════════════════════════════════════════════════════
# intelligence router — the explicit checks
# ══════════════════════════════════════════════════════════════════════════════

def test_journal_suggestions_endpoint_denies_unassigned_client_id(monkeypatch, only_mine):
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    with pytest.raises(HTTPException) as exc:
        intel.journal_suggestions(client_id=THEIRS, current_user=USER)
    assert exc.value.status_code == 404


def test_approve_journal_suggestion_denies_unassigned_client(monkeypatch, only_mine):
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    monkeypatch.setattr(
        isvc, "approve_journal_suggestion",
        lambda **kw: (_ for _ in ()).throw(AssertionError("draft entry created despite denial")),
    )

    body = intel.JournalSuggestionApproval(
        client_id=THEIRS, narration="Rent", lines=[{"account_id": "a1"}])
    with pytest.raises(HTTPException) as exc:
        intel.approve_journal_suggestion_endpoint(body, USER)
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# analytics — profitability and revenue-vs-effort
# ══════════════════════════════════════════════════════════════════════════════

def _patch_profitability(monkeypatch):
    import repositories.client_repository as cr
    import repositories.user_repository as ur
    import repositories.engagement_repository as er
    import repositories.invoice_repository as ir
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: CLIENTS)
    monkeypatch.setattr(ur.user_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(er.engagement_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(ir.invoice_repo, "get_revenue_by_client",
                        lambda *a, **k: {MINE: 100_00, THEIRS: 900_00})
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_cost_by_client",
                        lambda *a, **k: {MINE: 40_00, THEIRS: 300_00})
    monkeypatch.setattr(an, "_get_db", lambda: None)


def test_profitability_narrows_by_client_to_the_assigned_book(monkeypatch, only_mine):
    _patch_profitability(monkeypatch)
    resp = an.profitability_analytics(period="month", current_user=USER)
    by_client = resp["data"]["by_client"]
    assert {c["client_id"] for c in by_client} == {MINE}
    assert all(c["client_name"] != "Theirs Ltd" for c in by_client)


def test_profitability_totals_narrow_with_the_book(monkeypatch, only_mine):
    """Pinned as a DECISION, not an accident. On this endpoint the totals are
    summed from the very per-client dicts being filtered, so they narrow too.
    That differs from analytics.clients, whose total_minutes comes from a
    separate firm-wide query — and it is the safer direction: leaving these
    firm-wide would derive them from rows the caller cannot see, and would let
    an Executive recover the firm's aggregate position by subtracting their own
    book."""
    _patch_profitability(monkeypatch)
    resp = an.profitability_analytics(period="month", current_user=USER)
    assert resp["data"]["firm_metrics"]["total_revenue_paise"] == 100_00


def test_profitability_is_unfiltered_for_a_firmwide_role(monkeypatch):
    import core.authz as authz
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
    _patch_profitability(monkeypatch)
    resp = an.profitability_analytics(period="month", current_user=USER)
    assert {c["client_id"] for c in resp["data"]["by_client"]} == {MINE, THEIRS}


# ══════════════════════════════════════════════════════════════════════════════
# fx_reports / currencies / hsn — the explicit checks
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fn_name", [
    "realized_fx", "unrealized_fx", "currency_exposure",
    "exchange_rate_audit", "open_foreign_balances",
])
def test_fx_reports_deny_unassigned_client(monkeypatch, fn_name):
    import routers.fx_reports as fx
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    monkeypatch.setattr(
        fx, "_run",
        lambda fn, empty: (_ for _ in ()).throw(AssertionError("report ran despite denial")),
    )
    fn = getattr(fx, fn_name)
    with pytest.raises(HTTPException) as exc:
        fn(client_id=THEIRS, current_user=USER)
    assert exc.value.status_code == 404


def test_currency_policy_denies_unassigned_client_before_the_mock_shortcircuit(monkeypatch):
    """The check sits ahead of the _USE_MOCK early return, which would
    otherwise hand back a policy for any client_id without consulting scope."""
    import routers.currencies as cur
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    monkeypatch.setattr(cur, "_USE_MOCK", True)

    with pytest.raises(HTTPException) as exc:
        cur.get_currency_policy(client_id=THEIRS, current_user=USER)
    assert exc.value.status_code == 404


def test_hsn_search_denies_unassigned_client(monkeypatch):
    """hsn_sac_preferences is per-client usage history. Driven through
    asyncio.run rather than a marker — pytest-asyncio is not installed, and a
    bare `async def` test would be silently SKIPPED, i.e. green for free."""
    import asyncio
    import routers.hsn as hsn
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    monkeypatch.setattr(hsn, "_USE_MOCK", True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(hsn.search_hsn(q="1234", client_id=THEIRS, current_user=USER))
    assert exc.value.status_code == 404
