"""
Balance-cache service — round-trip + auditor (reporting passbook, Phase 1).

Uses an in-memory DB double (no network) to prove:
  1. recompute_client reads the raw posted ledger and stores exactly the right
     monthly buckets — excluding drafts and soft-deleted entries.
  2. audit_client reports "ok" when the store matches the ledger.
  3. audit_client DETECTS drift — the whole point of the safety net: if the
     stored buckets ever disagree with a fresh recompute by even one paise, it
     is flagged rather than silently trusted.
"""
from __future__ import annotations

from services import balance_cache_service as svc


class _Res:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.filters = []
        self._range = None
        self._mode = "select"
        self._rows = None

    # read builders
    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters.append((k, v)); return self
    def is_(self, k, _v): self.filters.append((k, "__null__")); return self
    def or_(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, a, b): self._range = (a, b); return self
    def in_(self, k, vals): self.filters.append((k, ("__in__", set(vals)))); return self

    # write builders
    def insert(self, rows):
        self._mode = "insert"
        self._rows = rows if isinstance(rows, list) else [rows]
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def _match(self, r):
        for k, v in self.filters:
            if v == "__null__":
                if r.get(k) is not None:
                    return False
            elif isinstance(v, tuple) and v[0] == "__in__":
                if r.get(k) not in v[1]:
                    return False
            elif r.get(k) != v:
                return False
        return True

    def execute(self):
        table = self.store.setdefault(self.t, [])
        if self._mode == "insert":
            table.extend(self._rows)
            return _Res(list(self._rows))
        if self._mode == "delete":
            self.store[self.t] = [r for r in table if not self._match(r)]
            return _Res([])
        rows = [dict(r) for r in table if self._match(r)]
        if self._range is not None:
            a, b = self._range
            rows = rows[a:b + 1]
        return _Res(rows)


class _DB:
    def __init__(self, store): self.store = store
    def table(self, n): return _Query(self.store, n)


F, C = "firm-1", "client-1"


def _entry(eid, date, lines, *, posted=True, deleted=None):
    return {
        "id": eid, "entry_date": date, "client_id": C, "firm_id": F,
        "entry_type": "X", "reference_no": eid, "narration": "", "created_at": date + "T00:00",
        "reversal_of": None, "is_posted": posted, "deleted_at": deleted,
        "journal_lines": [
            {"account_id": a, "debit_paise": d, "credit_paise": c} for (a, d, c) in lines
        ],
    }


def _store():
    return {
        "journal_entries": [
            _entry("e1", "2025-06-15", [("ar", 11800, 0), ("rev", 0, 10000), ("gst", 0, 1800)]),
            _entry("e2", "2025-07-20", [("bank", 11800, 0), ("ar", 0, 11800)]),
            _entry("draft", "2025-07-22", [("bank", 999, 0), ("rev", 0, 999)], posted=False),
            _entry("gone", "2025-07-23", [("bank", 500, 0), ("rev", 0, 500)], deleted="2025-07-24T00:00"),
        ],
        "account_period_balances": [],
    }


def test_recompute_stores_exactly_the_right_buckets():
    db = _DB(_store())
    out = svc.recompute_client(db, F, C)
    assert out["buckets_written"] == 5      # ar/rev/gst in June, bank/ar in July

    stored = {(r["account_id"], r["period_month"]): (r["debit_paise"], r["credit_paise"])
              for r in db.store["account_period_balances"]}
    assert stored[("ar", "2025-06-01")] == (11800, 0)
    assert stored[("rev", "2025-06-01")] == (0, 10000)
    assert stored[("gst", "2025-06-01")] == (0, 1800)
    assert stored[("bank", "2025-07-01")] == (11800, 0)
    assert stored[("ar", "2025-07-01")] == (0, 11800)
    # the draft and the soft-deleted entry must NOT appear anywhere
    assert ("rev", "2025-07-01") not in stored


def test_recompute_is_idempotent():
    db = _DB(_store())
    svc.recompute_client(db, F, C)
    svc.recompute_client(db, F, C)     # second run must not duplicate rows
    assert len(db.store["account_period_balances"]) == 5


def test_audit_ok_when_store_matches_ledger():
    db = _DB(_store())
    svc.recompute_client(db, F, C)
    res = svc.audit_client(db, F, C)
    assert res["ok"] is True
    assert res["discrepancy_count"] == 0


def test_audit_detects_drift():
    db = _DB(_store())
    svc.recompute_client(db, F, C)
    # Corrupt one stored bucket by a single paise — the auditor must catch it.
    for r in db.store["account_period_balances"]:
        if r["account_id"] == "ar" and r["period_month"] == "2025-06-01":
            r["debit_paise"] = 11801
    res = svc.audit_client(db, F, C)
    assert res["ok"] is False
    assert res["discrepancy_count"] == 1
    d = res["discrepancies"][0]
    assert d["account_id"] == "ar" and d["period_month"] == "2025-06-01"
    assert d["stored_debit"] == 11801 and d["computed_debit"] == 11800
