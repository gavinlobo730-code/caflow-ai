"""
Passbook read path (reporting perf, Phase 2) — the fast accrual path served
through ReportingService must equal the legacy full-history path, and the
rollout modes (off / shadow / on) must route correctly.

The equivalence of buckets->builders vs raw->builders is proven in
test_passbook_equivalence; this test proves the SERVICE PLUMBING that wires the
stored buckets + partial-edge-month replay into that path: fetch_buckets parsing,
fetch_edge_month_entries month selection, and _serve mode routing.
"""
from __future__ import annotations

import pytest

from domain.reporting.balance_cache import build_buckets
from domain.reporting.service import ReportingService
from domain.reporting.sources import InMemoryLedgerSource, SupabaseLedgerSource

FIRM, CLIENT = "firm-1", "client-1"


# ── a tiny Supabase-shaped fake DB (adds gte/lte to the pagination test's shape)

class _Res:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.store, self.t, self.f, self._range = store, table, [], None
        self._order: str | None = None
        self._limit: int | None = None
    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append((k, ("eq", v))); return self
    def is_(self, k, _v): self.f.append((k, ("null", None))); return self
    def or_(self, *_a, **_k): return self
    def ilike(self, *_a, **_k): return self
    def gt(self, k, v): self.f.append((k, ("gt", v))); return self
    def gte(self, k, v): self.f.append((k, ("gte", v))); return self
    def lte(self, k, v): self.f.append((k, ("lte", v))); return self
    def in_(self, k, vals): self.f.append((k, ("in", set(vals)))); return self
    def order(self, col=None, *_a, **_k): self._order = col; return self
    def range(self, a, b): self._range = (a, b); return self
    def limit(self, n): self._limit = n; return self

    def _match(self, r):
        for k, (op, v) in self.f:
            rv = r.get(k)
            if op == "eq" and rv != v: return False
            if op == "null" and rv is not None: return False
            if op == "gt" and not (rv is not None and str(rv) > str(v)): return False
            if op == "gte" and not (rv is not None and str(rv) >= v): return False
            if op == "lte" and not (rv is not None and str(rv) <= v): return False
            if op == "in" and rv not in v: return False
        return True

    def execute(self):
        rows = [dict(r) for r in self.store.get(self.t, []) if self._match(r)]
        if self._order is not None:                      # keyset paging needs stable ascending order
            rows.sort(key=lambda r: str(r.get(self._order)))
        if self._range is not None:
            a, b = self._range
            rows = rows[a:b + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        return _Res(rows)


class _DB:
    def __init__(self, store): self.store = store
    def table(self, n): return _Q(self.store, n)

    def rpc(self, fn, params=None):
        """This double models PostgREST's TABLE surface, not the SQL functions
        behind it. Cash Flow asks for public.cash_flow_report first (migration
        277); refusing here is what routes these tests down the passbook path
        they exist to exercise, and says so rather than failing on a missing
        attribute."""
        raise NotImplementedError(f"{fn}: this fake DB has no SQL functions")


def _entry(eid, date, lines):
    return {
        "id": eid, "entry_date": date, "client_id": CLIENT, "firm_id": FIRM,
        "entry_type": "X", "is_posted": True, "deleted_at": None,
        "reference_no": eid, "narration": "", "created_at": date + "T00:00", "reversal_of": None,
        "journal_lines": [{"account_id": a, "debit_paise": d, "credit_paise": c} for (a, d, c) in lines],
    }


ACCOUNTS = [
    {"id": "bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset",
     "account_subtype": "Bank", "system_account_key": "bank", "firm_id": FIRM, "client_id": None, "is_active": True},
    {"id": "rev", "account_code": "4000", "account_name": "Sales", "account_type": "Revenue",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": None, "is_active": True},
    {"id": "exp", "account_code": "5000", "account_name": "Rent", "account_type": "Expense",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": None, "is_active": True},
    {"id": "cap", "account_code": "3000", "account_name": "Capital", "account_type": "Equity",
     "account_subtype": None, "system_account_key": None, "firm_id": FIRM, "client_id": None, "is_active": True},
]

ENTRIES_RAW = [
    _entry("e1", "2025-05-10", [("bank", 100000, 0), ("cap", 0, 100000)]),
    _entry("e2", "2025-06-15", [("bank", 20000, 0), ("rev", 0, 20000)]),
    _entry("e3", "2026-04-05", [("exp", 5000, 0), ("bank", 0, 5000)]),
    _entry("e4", "2026-07-10", [("exp", 2000, 0), ("bank", 0, 2000)]),
    _entry("e5", "2026-07-25", [("exp", 3000, 0), ("bank", 0, 3000)]),
]


def _model_entries():
    # Build domain JournalEntry objects for build_buckets, via the source parser.
    src = SupabaseLedgerSource(_DB({"journal_entries": ENTRIES_RAW}))
    return src._entries(FIRM, CLIENT)


def _seed_store():
    buckets = build_buckets(_model_entries().values())
    apb_rows = []
    for i, ((aid, month), (dr, cr)) in enumerate(buckets.items()):
        apb_rows.append({
            "id": f"b{i:04d}", "firm_id": FIRM, "client_id": CLIENT, "account_id": aid,
            "period_month": month, "debit_paise": dr, "credit_paise": cr,
        })
    return {"journal_entries": ENTRIES_RAW, "chart_of_accounts": ACCOUNTS,
            "account_period_balances": apb_rows}


WINDOWS_TB = ["2026-03-31", "2026-07-18", "2027-03-31"]           # as-of dates (TB / BS)
WINDOWS_PL = [("2025-04-01", "2026-03-31"), ("2026-04-01", "2027-03-31"),
              ("2026-07-05", "2026-07-20")]                        # P&L [start,end]


def test_fast_trial_balance_equals_legacy(monkeypatch):
    svc = ReportingService(SupabaseLedgerSource(_DB(_seed_store())))
    for as_of in WINDOWS_TB:
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
        legacy = svc.trial_balance(FIRM, CLIENT, as_of)
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
        fast = svc.trial_balance(FIRM, CLIENT, as_of)
        assert fast == legacy, f"TB mismatch as_of={as_of}"


def test_fast_profit_loss_equals_legacy(monkeypatch):
    svc = ReportingService(SupabaseLedgerSource(_DB(_seed_store())))
    for start, end in WINDOWS_PL:
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
        legacy = svc.profit_loss(FIRM, CLIENT, start, end)
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
        fast = svc.profit_loss(FIRM, CLIENT, start, end)
        assert fast == legacy, f"P&L mismatch {start}..{end}"


def test_fast_balance_sheet_equals_legacy(monkeypatch):
    svc = ReportingService(SupabaseLedgerSource(_DB(_seed_store())))
    for as_of in WINDOWS_TB:
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
        legacy = svc.balance_sheet(FIRM, CLIENT, as_of)
        monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
        fast = svc.balance_sheet(FIRM, CLIENT, as_of)
        assert fast == legacy, f"BS mismatch as_of={as_of}"


def test_cash_basis_never_uses_passbook(monkeypatch):
    # Cash basis must always go legacy even in 'on' mode (passbook is accrual-only).
    svc = ReportingService(SupabaseLedgerSource(_DB(_seed_store())))
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    # Should not raise and should return a cash-tagged report (legacy path).
    out = svc.trial_balance(FIRM, CLIENT, "2027-03-31", basis="cash")
    assert out.get("basis") == "cash"


def test_serve_routing(monkeypatch):
    svc = ReportingService(InMemoryLedgerSource(accounts=[], entries=[]))
    ctx = ("t", FIRM, CLIENT)
    fast = lambda: {"total_debit_paise": 1}
    legacy = lambda: {"total_debit_paise": 2}
    def boom(): raise RuntimeError("fast broke")

    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    assert svc._serve(ctx, fast, legacy)["total_debit_paise"] == 1        # on -> fast
    assert svc._serve(ctx, boom, legacy)["total_debit_paise"] == 2        # on + fast error -> legacy

    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "shadow")
    assert svc._serve(ctx, fast, legacy)["total_debit_paise"] == 2        # shadow -> legacy served
    assert svc._serve(ctx, boom, legacy)["total_debit_paise"] == 2        # shadow + fast error -> legacy
