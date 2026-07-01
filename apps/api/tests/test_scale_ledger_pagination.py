"""
Production Readiness Phase 3 — ledger scalability (audit C6).

A DB double that reproduces PostgREST's ~1000-row hard cap on un-ranged selects
proves that the paginated fetch in SupabaseLedgerSource returns EVERY journal
entry (so TB/BS/P&L are correct) for a client with far more than 1000 entries —
where the old un-paged fetch silently truncated to 1000.
"""
from domain.reporting import SupabaseLedgerSource, ReportingService

FIRM = "FIRM-A"
CLIENT = "CLI"
CAP = 1000


class _Res:
    def __init__(self, data): self.data = data


class _CapQuery:
    """Simulates PostgREST: an un-ranged select is hard-capped at CAP rows; a
    ranged select returns exactly that slice."""
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []; self._range = None; self._cols = ""
    def select(self, cols="*", **k): self._cols = cols; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, "__null__")); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", set(vals)))); return self
    def or_(self, *_a, **_k): return self
    def ilike(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, a, b): self._range = (a, b); return self

    def _match(self, r):
        for k, v in self.f:
            if v == "__null__":
                if r.get(k) is not None: return False
            elif isinstance(v, tuple) and v[0] == "__in__":
                if r.get(k) not in v[1]: return False
            elif r.get(k) != v:
                return False
        return True

    def execute(self):
        rows = [dict(r) for r in self.store.get(self.t, []) if self._match(r)]
        if self._range is not None:
            a, b = self._range
            return _Res(rows[a:b + 1])
        return _Res(rows[:CAP])          # the silent cap


class _CapDB:
    def __init__(self, store): self.store = store
    def table(self, n): return _CapQuery(self.store, n)


def _build_store(n_entries: int) -> dict:
    accounts = [
        {"id": "bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset",
         "account_subtype": "Bank", "system_account_key": "bank"},
        {"id": "rev", "account_code": "4000", "account_name": "Fees", "account_type": "Revenue",
         "account_subtype": None, "system_account_key": None},
    ]
    entries = []
    for i in range(n_entries):
        entries.append({
            "id": f"je{i:06d}", "entry_date": "2025-06-10", "client_id": CLIENT, "firm_id": FIRM,
            "entry_type": "Receipt", "is_posted": True, "deleted_at": None,
            "reference_no": f"R{i}", "narration": "x", "created_at": "2025-06-10T00:00", "reversal_of": None,
            "journal_lines": [
                {"account_id": "bank", "debit_paise": 100, "credit_paise": 0},
                {"account_id": "rev", "debit_paise": 0, "credit_paise": 100},
            ],
        })
    return {"chart_of_accounts": accounts, "journal_entries": entries,
            "client_sales_invoices": [], "receipts": [], "receipt_allocations": [],
            "credit_notes": [], "purchase_bills": [], "purchase_payments": []}


def test_cap_is_real_unranged_select_truncates():
    # Sanity: the double truncates an un-ranged select at 1000 (models PostgREST).
    db = _CapDB(_build_store(2500))
    raw = db.table("journal_entries").select("*").eq("firm_id", FIRM).execute().data
    assert len(raw) == CAP


def test_entries_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store(2500))
    entries = SupabaseLedgerSource(db)._entries(FIRM, CLIENT)
    assert len(entries) == 2500          # not silently capped at 1000


def test_trial_balance_correct_beyond_cap():
    # 2500 entries × ₹1 each → TB must reflect all of them, not the first 1000.
    db = _CapDB(_build_store(2500))
    svc = ReportingService(SupabaseLedgerSource(db))
    tb = svc.trial_balance(FIRM, CLIENT, "2026-03-31")
    assert tb["is_balanced"]
    assert tb["total_debit_paise"] == 2500 * 100    # would be 100000 if truncated
    assert tb["total_credit_paise"] == 2500 * 100


def test_exactly_cap_boundary():
    # Exactly 1000 then 1001 — the off-by-one the cap hides.
    for n in (1000, 1001):
        db = _CapDB(_build_store(n))
        entries = SupabaseLedgerSource(db)._entries(FIRM, CLIENT)
        assert len(entries) == n
