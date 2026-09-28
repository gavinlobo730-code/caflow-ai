"""
Schedule III "All Clients" — sweep-accounting-hub-2-06.

THE BUG THIS PINS
    GET /api/accounting/schedule-iii with no client_id ("All Clients") called
    ReportingService.schedule_iii, which runs profit_loss/balance_sheet FOUR
    times (current + prior period). _passbook_applicable required a concrete
    client_id (see test_passbook_firm_wide_scope.py), so every one of those
    four calls fell back to the legacy path — a full-history replay of EVERY
    posted entry of EVERY client the caller may read, four times over. That is
    exactly the "read proportional to transaction volume" CLAUDE.md's
    Reporting Performance section forbids, and it routinely exceeded the
    frontend's request timeout.

WHAT THE FIX IS
    profit_loss/balance_sheet gained a SEPARATE firm-wide path
    (_firm_wide_passbook_applicable / _firm_wide_buckets), used only when
    client_id is None: it sums account_period_balances across every client the
    caller may read — a firm-wide role sees the whole firm's buckets, an
    assigned Executive/Manager sees only their assigned clients' — instead of
    replaying raw journal lines. _passbook_applicable itself is UNCHANGED, so
    trial_balance / period_net_by_account / cash_flow / multi_year_trend still
    fall back to the replay for "All Clients", exactly as
    test_passbook_firm_wide_scope.py already pins.
"""
from __future__ import annotations

import pytest

from domain.reporting.balance_cache import build_buckets
from domain.reporting.service import ReportingService
from domain.reporting.sources import SupabaseLedgerSource
from tests.test_passbook_read_path import _DB

FIRM = "firm-1"
CLIENT_A = "client-a"
CLIENT_B = "client-b"
FY = ("2026-04-01", "2027-03-31")   # month-aligned: no edge-month replay needed
AS_OF = "2027-03-31"


def _entry(eid, date, client_id, lines):
    return {
        "id": eid, "entry_date": date, "client_id": client_id, "firm_id": FIRM,
        "entry_type": "X", "is_posted": True, "deleted_at": None,
        "reference_no": eid, "narration": "", "created_at": date + "T00:00", "reversal_of": None,
        "journal_lines": [{"account_id": a, "debit_paise": d, "credit_paise": c} for (a, d, c) in lines],
    }


# "bank" is a FIRM-LEVEL account (client_id None) both clients post to — the
# case _firm_wide_buckets's docstring calls out: two clients' buckets for the
# same account and month must be SUMMED, never one overwriting the other.
ACCOUNTS = [
    {"id": "bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset",
     "account_subtype": "Bank", "system_account_key": "bank", "firm_id": FIRM, "client_id": None, "is_active": True},
    {"id": "rev_a", "account_code": "4000", "account_name": "Sales A", "account_type": "Revenue",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": CLIENT_A, "is_active": True},
    {"id": "exp_a", "account_code": "5000", "account_name": "Rent A", "account_type": "Expense",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": CLIENT_A, "is_active": True},
    {"id": "rev_b", "account_code": "4001", "account_name": "Sales B", "account_type": "Revenue",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": CLIENT_B, "is_active": True},
    {"id": "exp_b", "account_code": "5001", "account_name": "Rent B", "account_type": "Expense",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": CLIENT_B, "is_active": True},
]

ENTRIES = [
    _entry("a1", "2026-04-10", CLIENT_A, [("bank", 50000, 0), ("rev_a", 0, 50000)]),
    _entry("a2", "2026-05-05", CLIENT_A, [("exp_a", 10000, 0), ("bank", 0, 10000)]),
    _entry("b1", "2026-04-15", CLIENT_B, [("bank", 30000, 0), ("rev_b", 0, 30000)]),
    _entry("b2", "2026-06-01", CLIENT_B, [("exp_b", 5000, 0), ("bank", 0, 5000)]),
]

# Client A: revenue 50,000 / expense 10,000 / net 40,000.
# Client B: revenue 30,000 / expense  5,000 / net 25,000.
# Combined: revenue 80,000 / expense 15,000 / net 65,000 — and the whole of it
# sits in the ONE shared "bank" account, which is the SUM invariant this file
# exists to pin.


def _seed_store() -> dict:
    """journal_entries + chart_of_accounts + per-client account_period_balances
    rows built from the same entries — one client's bucket rows are what a real
    account_period_balances table would hold (migration 227:
    UNIQUE(firm_id, client_id, account_id, period_month))."""
    apb: list[dict] = []
    i = 0
    for client_id in (CLIENT_A, CLIENT_B):
        parsed = SupabaseLedgerSource(_DB({"journal_entries": ENTRIES}))._entries(FIRM, client_id)
        for (aid, month), (dr, cr) in build_buckets(parsed.values()).items():
            apb.append({"id": f"b{i:04d}", "firm_id": FIRM, "client_id": client_id,
                       "account_id": aid, "period_month": month,
                       "debit_paise": dr, "credit_paise": cr})
            i += 1
    return {"journal_entries": ENTRIES, "chart_of_accounts": ACCOUNTS, "account_period_balances": apb}


class _RecordingDB(_DB):
    """Records which tables were queried and the filters applied to each, so a
    test can prove the fast path reads buckets (not raw entries) and that a
    firm-wide read applies no client_id filter while a scoped one does."""

    def __init__(self, store):
        super().__init__(store)
        self.tables: list[str] = []
        self.bucket_filters: list[list] = []

    def table(self, name):
        self.tables.append(name)
        q = super().table(name)
        if name == "account_period_balances":
            self.bucket_filters.append(q.f)   # same list object the query mutates
        return q


def _svc(allowed=None, db=None) -> ReportingService:
    return ReportingService(SupabaseLedgerSource(db or _DB(_seed_store()), allowed))


@pytest.mark.parametrize("call", [
    lambda s: s.profit_loss(FIRM, None, *FY),
    lambda s: s.balance_sheet(FIRM, None, AS_OF),
], ids=["profit_loss", "balance_sheet"])
def test_all_clients_fast_path_matches_legacy(monkeypatch, call):
    """The bug in one assertion: for a firm-wide (client_id=None) read, the fast
    path must equal the legacy replay — and, unlike the pre-fix state pinned by
    test_passbook_firm_wide_scope.py, it must reach that answer by actually
    summing the passbook, not merely by falling back to the replay."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = call(_svc())
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    fast = call(_svc())
    assert fast == legacy


def test_all_clients_profit_loss_sums_every_clients_revenue_and_expense(monkeypatch):
    """The actual figures, not just equality with a slow path nobody wants:
    Client A and Client B's revenue and expense must both land in the total."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    out = _svc().profit_loss(FIRM, None, *FY)
    assert out["revenue"]["total_paise"] == 80_000       # 50,000 (A) + 30,000 (B)
    assert out["operating_expenses"]["total_paise"] == 15_000   # 10,000 (A) + 5,000 (B)
    assert out["net_profit_paise"] == 65_000


def test_all_clients_balance_sheet_sums_the_shared_bank_account(monkeypatch):
    """"bank" is a single FIRM-LEVEL account both clients post to. If the fix
    merged buckets by (account_id, period_month) instead of summing them, one
    client's activity on this account would silently overwrite the other's."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    out = _svc().balance_sheet(FIRM, None, AS_OF)
    assert out["total_assets_paise"] == 65_000   # 50,000 - 10,000 + 30,000 - 5,000
    assert out["is_balanced"] is True


def test_a_scoped_caller_sees_only_their_assigned_clients(monkeypatch):
    """An Executive/Manager assigned only Client A must not see Client B's
    figures folded into their own "All Clients" screen — the assignment-scope
    bug ACC-17 already fixed for the legacy path must hold on the fast one too."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    scoped = _svc(allowed={CLIENT_A}).profit_loss(FIRM, None, *FY)
    assert scoped["revenue"]["total_paise"] == 50_000
    assert scoped["operating_expenses"]["total_paise"] == 10_000
    assert scoped["net_profit_paise"] == 40_000


def test_the_fast_path_reads_buckets_not_an_unbounded_ledger_replay(monkeypatch):
    """The other half of the fix: for a firm-wide, month-aligned window the fast
    path must not touch journal_entries at all (build_edge_month_entries has
    nothing to replay), and its account_period_balances read must carry no
    client_id filter — a Partner's "All Clients" is every client's own bucket,
    not one client's repeated four times."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    db = _RecordingDB(_seed_store())
    _svc(db=db).profit_loss(FIRM, None, *FY)

    assert "account_period_balances" in db.tables, "the passbook was never consulted"
    assert "journal_entries" not in db.tables, (
        "a month-aligned firm-wide read still replayed raw journal entries")
    for filters in db.bucket_filters:
        ops = {k for k, _ in filters}
        assert "client_id" not in ops, (
            f"a firm-wide (unrestricted) read filtered account_period_balances "
            f"on client_id: {filters}")


def test_a_scoped_callers_bucket_read_does_filter_on_client_id(monkeypatch):
    """Control for the assertion above: an assignment-scoped caller's read of
    the SAME table must carry the client_id restriction, or the "no filter"
    check above would pass for the wrong reason."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    db = _RecordingDB(_seed_store())
    _svc(allowed={CLIENT_A}, db=db).profit_loss(FIRM, None, *FY)

    assert db.bucket_filters, "no account_period_balances query was made at all"
    assert any(k == "client_id" for filters in db.bucket_filters for k, _ in filters), (
        "a scoped caller's firm-wide read applied no client_id restriction at all")


def test_the_legacy_path_is_the_thing_being_avoided(monkeypatch):
    """Control for the two tests above: with the passbook off, the fast path's
    absence of an unbounded journal_entries read would prove nothing if the
    legacy path never made one either."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    db = _RecordingDB(_seed_store())
    _svc(db=db).profit_loss(FIRM, None, *FY)

    assert "journal_entries" in db.tables, (
        "the legacy path stopped reading journal_entries — this control is stale")


def test_the_gate_only_applies_to_the_firm_wide_case(monkeypatch):
    """_firm_wide_passbook_applicable must not quietly widen the existing,
    single-client gate — trial_balance and cash_flow's own "All Clients" still
    fall back to the legacy replay exactly as
    test_passbook_firm_wide_scope.py pins."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    svc = _svc()
    assert svc._passbook_applicable("accrual", None) is False
    assert svc._firm_wide_passbook_applicable("accrual") is True
    assert svc._firm_wide_passbook_applicable("cash") is False
