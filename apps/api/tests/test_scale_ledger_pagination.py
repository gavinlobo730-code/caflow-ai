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
    """Simulates PostgREST: an un-ranged/un-limited select is hard-capped at CAP
    rows; a .limit()/.range() select returns exactly that slice. Supports keyset
    paging (.gt + .limit over an ascending .order)."""
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []; self._range = None; self._cols = ""
        self._order = None; self._limit = None
    def select(self, cols="*", **k): self._cols = cols; return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, "__null__")); return self
    def in_(self, k, vals): self.f.append((k, ("__in__", set(vals)))); return self
    def gt(self, k, v): self.f.append((k, ("__gt__", v))); return self
    def or_(self, *_a, **_k): return self
    def ilike(self, *_a, **_k): return self
    def order(self, col=None, *_a, **_k): self._order = col; return self
    def range(self, a, b): self._range = (a, b); return self
    def limit(self, n): self._limit = n; return self

    def _match(self, r):
        for k, v in self.f:
            if v == "__null__":
                if r.get(k) is not None: return False
            elif isinstance(v, tuple) and v[0] == "__in__":
                if r.get(k) not in v[1]: return False
            elif isinstance(v, tuple) and v[0] == "__gt__":
                if not (r.get(k) is not None and str(r.get(k)) > str(v[1])): return False
            elif r.get(k) != v:
                return False
        return True

    def execute(self):
        rows = [dict(r) for r in self.store.get(self.t, []) if self._match(r)]
        if self._order is not None:
            rows.sort(key=lambda r: str(r.get(self._order)))
        if self._range is not None:
            a, b = self._range
            return _Res(rows[a:b + 1])
        if self._limit is not None:
            return _Res(rows[:self._limit])
        return _Res(rows[:CAP])          # the silent cap (un-limited select)


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


# ── task #221: the other 6 top-level fetches, never exercised at scale ────────
# The money-movement audit found these were never paginated (unlike _entries,
# fixed for audit C6) and never tested beyond an empty fixture — _build_store
# above always seeded them as []. A client with >1000 invoices/receipts/bills/
# payments/credit notes silently dropped rows out of invoice_by_journal etc.,
# misclassifying cash-basis revenue/expense recognition and Cash Flow entries.

def _build_store_with(table: str, n: int) -> dict:
    store = _build_store(0)
    store["journal_entries"] = []
    common = {"firm_id": FIRM, "client_id": CLIENT}
    if table == "client_sales_invoices":
        store[table] = [{"id": f"inv{i:06d}", "total_paise": 100, "journal_entry_id": f"je{i:06d}", **common}
                        for i in range(n)]
    elif table == "receipts":
        store[table] = [{"id": f"r{i:06d}", "amount_paise": 100, "tds_paise": 0,
                         "journal_entry_id": f"je{i:06d}", **common} for i in range(n)]
    elif table == "credit_notes":
        store[table] = [{"id": f"cn{i:06d}", "sales_invoice_id": f"inv{i:06d}",
                         "journal_entry_id": f"jecn{i:06d}", **common} for i in range(n)]
    elif table == "purchase_bills":
        store[table] = [{"id": f"b{i:06d}", "total_paise": 100, "journal_entry_id": f"je{i:06d}", **common}
                        for i in range(n)]
    elif table == "purchase_payments":
        store[table] = [{"id": f"p{i:06d}", "purchase_bill_id": f"b{i:06d}",
                         "amount_paise": 100, "journal_entry_id": f"jep{i:06d}", **common} for i in range(n)]
    return store


def test_invoices_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store_with("client_sales_invoices", 2500))
    invoices = SupabaseLedgerSource(db)._invoices(FIRM, CLIENT)
    assert len(invoices) == 2500


def test_receipts_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store_with("receipts", 2500))
    receipts = SupabaseLedgerSource(db)._receipts(FIRM, CLIENT)
    assert len(receipts) == 2500


def test_credit_notes_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store_with("credit_notes", 2500))
    notes = SupabaseLedgerSource(db)._credit_notes(FIRM, CLIENT)
    assert len(notes) == 2500


def test_bills_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store_with("purchase_bills", 2500))
    bills = SupabaseLedgerSource(db)._bills(FIRM, CLIENT)
    assert len(bills) == 2500


def test_payments_paginated_returns_all_beyond_cap():
    db = _CapDB(_build_store_with("purchase_payments", 2500))
    payments = SupabaseLedgerSource(db)._payments(FIRM, CLIENT)
    assert len(payments) == 2500


def test_allocations_paginated_and_chunked_beyond_cap():
    # 1500 receipts, each with ONE allocation row -> exercises both the >200
    # receipt_ids .in_() chunking AND the >1000-row-per-chunk pagination.
    store = _build_store(0)
    store["journal_entries"] = []
    receipt_ids = [f"r{i:06d}" for i in range(1500)]
    store["receipt_allocations"] = [
        {"id": f"alloc{i:06d}", "receipt_id": rid, "sales_invoice_id": f"inv{i:06d}", "allocated_paise": 50}
        for i, rid in enumerate(receipt_ids)
    ]
    db = _CapDB(store)
    out = SupabaseLedgerSource(db)._allocations(receipt_ids)
    assert sum(len(v) for v in out.values()) == 1500
    assert len(out) == 1500   # one allocation per receipt, distinct receipt_ids


def test_entries_paginated_across_many_keyset_pages():
    # _fetch_all pages by KEYSET (cursor): each page seeks `id > last_id LIMIT
    # _PAGE`. These sizes exercise several pages plus the boundary cases: a short
    # final page (6500 -> 6 full + 1 of 500), an EXACT multiple of the page size
    # (6000 -> 6 full pages, where end-of-data is only learned from a 7th empty
    # page), and one past it (6001 -> a trailing 1-row page).
    for n in (6500, 6000, 6001):
        db = _CapDB(_build_store(n))
        entries = SupabaseLedgerSource(db)._entries(FIRM, CLIENT)
        assert len(entries) == n, f"expected {n} entries, got {len(entries)}"
