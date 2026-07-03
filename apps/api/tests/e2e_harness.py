"""
Phase 5.2 WS-1 — shared E2E harness.

A faithful-enough in-memory Supabase/PostgREST double so the REAL routers and
services can be driven through full business-cycle lifecycles against shared
state, with accounting reconciliation (journals, AR/AP, trial balance) actually
computed — not mocked.

Why a shared DB (not the per-router _USE_MOCK stores): the mock stores are
per-module and never post journals, so cross-module reconciliation (invoice ⇒
journal ⇒ trial balance) cannot be asserted. This harness wires every involved
router/service module to ONE FakeDB and flips their module-level `_USE_MOCK` to
False, so the production code paths run.

Query-builder coverage (PostgREST surface used across the cycles):
  select/insert/update/delete/upsert, eq/neq/gt/gte/lt/lte, in_, not_.in_,
  is_, like/ilike (with %wildcards%), or_("col.op.val,col.op.val"),
  order, limit, range, single, maybe_single, and select(count="exact").

Integer paise only; the double never coerces to float.
"""
from __future__ import annotations

import uuid
import re
from typing import Any, Optional


# --------------------------------------------------------------------------- #
#  Result envelope (mimics supabase-py's APIResponse: .data, .count)
# --------------------------------------------------------------------------- #
class _Result:
    def __init__(self, data: Any, count: Optional[int] = None):
        self.data = data
        self.count = count


# --------------------------------------------------------------------------- #
#  Query builder
# --------------------------------------------------------------------------- #
class _Query:
    def __init__(self, db: "FakeDB", table: str):
        self.db = db
        self.table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, Optional[str], Any]] = []
        self._order: Optional[tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._range: Optional[tuple[int, int]] = None
        self._single = False
        self._maybe_single = False
        self._negate = False
        self._count_mode: Optional[str] = None

    # -- operation selectors -------------------------------------------------
    def select(self, cols: str = "*", count: Optional[str] = None, **_k):
        self._op = "select"; self._count_mode = count; return self

    def insert(self, payload, **_k):
        self._op = "insert"; self._payload = payload; return self

    def update(self, payload, **_k):
        self._op = "update"; self._payload = payload; return self

    def upsert(self, payload, **_k):
        self._op = "upsert"; self._payload = payload; return self

    def delete(self, **_k):
        self._op = "delete"; return self

    # -- filters -------------------------------------------------------------
    def eq(self, col, val): return self._add("eq", col, val)
    def neq(self, col, val): return self._add("neq", col, val)
    def gt(self, col, val): return self._add("gt", col, val)
    def gte(self, col, val): return self._add("gte", col, val)
    def lt(self, col, val): return self._add("lt", col, val)
    def lte(self, col, val): return self._add("lte", col, val)
    def in_(self, col, vals): return self._add("in", col, list(vals))
    def is_(self, col, val): return self._add("is", col, val)
    def like(self, col, pat): return self._add("like", col, pat)
    def ilike(self, col, pat): return self._add("ilike", col, pat)
    def or_(self, expr): return self._add("or", None, expr)

    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, kind, col, val):
        if self._negate:
            kind = "not_" + kind
            self._negate = False
        self._filters.append((kind, col, val))
        return self

    # -- modifiers -----------------------------------------------------------
    def order(self, col, desc: bool = False, **_k):
        self._order = (col, desc); return self

    def limit(self, n): self._limit = n; return self
    def range(self, a, b): self._range = (a, b); return self
    def single(self): self._single = True; return self
    def maybe_single(self): self._maybe_single = True; return self

    # -- matching ------------------------------------------------------------
    @staticmethod
    def _ilike(value: Any, pattern: str) -> bool:
        if value is None:
            return False
        rx = "^" + re.escape(str(pattern)).replace("%", ".*").replace("_", ".") + "$"
        return re.match(rx, str(value), re.IGNORECASE) is not None

    @classmethod
    def _term(cls, row: dict, kind: str, col: Optional[str], val: Any) -> bool:
        rv = row.get(col) if col is not None else None
        if kind == "eq":   return rv == val
        if kind == "neq":  return rv != val
        if kind == "gt":   return rv is not None and rv > val
        if kind == "gte":  return rv is not None and rv >= val
        if kind == "lt":   return rv is not None and rv < val
        if kind == "lte":  return rv is not None and rv <= val
        if kind == "in":   return rv in val
        if kind == "not_in": return rv not in val
        if kind == "is":   # is null / is true / is false
            if val in (None, "null"): return rv is None
            if val in (True, "true"): return rv is True
            if val in (False, "false"): return rv is False
            return rv == val
        if kind == "like":  return cls._ilike(rv, val)  # case-sensitive in PG; ok for tests
        if kind == "ilike": return cls._ilike(rv, val)
        if kind == "not_eq": return rv != val
        if kind == "or":    return cls._or_expr(row, val)
        raise NotImplementedError(f"FakeDB filter not implemented: {kind}")

    @classmethod
    def _or_expr(cls, row: dict, expr: str) -> bool:
        """Parse a PostgREST or() expression: 'col.op.val,col.op.val'."""
        for term in expr.split(","):
            parts = term.strip().split(".", 2)
            if len(parts) != 3:
                continue
            c, op, v = parts
            if v == "null":
                vv: Any = None
            elif v.lstrip("-").isdigit():
                vv = int(v)
            else:
                vv = v
            op_map = {"eq": "eq", "neq": "neq", "gt": "gt", "gte": "gte",
                      "lt": "lt", "lte": "lte", "is": "is", "ilike": "ilike",
                      "like": "like"}
            if op in op_map and cls._term(row, op_map[op], c, vv):
                return True
        return False

    def _match(self, row: dict) -> bool:
        return all(self._term(row, k, c, v) for (k, c, v) in self._filters)

    def _apply_order(self, rows: list) -> list:
        if not self._order:
            return rows
        col, desc = self._order
        return sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)

    # -- execution -----------------------------------------------------------
    def execute(self) -> _Result:
        rows = self.db._tables.setdefault(self.table, [])

        if self._op in ("insert", "upsert"):
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                r = dict(p)
                r.setdefault("id", str(uuid.uuid4()))
                rows.append(r)
                inserted.append(dict(r))
            return _Result(inserted)

        if self._op == "update":
            matched = [r for r in rows if self._match(r)]
            for r in matched:
                r.update(self._payload)
            return _Result([dict(r) for r in matched])

        if self._op == "delete":
            matched = [r for r in rows if self._match(r)]
            self.db._tables[self.table] = [r for r in rows if not self._match(r)]
            return _Result([dict(r) for r in matched])

        # select
        out = [r for r in rows if self._match(r)]
        out = self._apply_order(out)
        total = len(out)
        if self._range is not None:
            out = out[self._range[0]: self._range[1] + 1]
        if self._limit is not None:
            out = out[: self._limit]
        out = [dict(r) for r in out]
        if self._single:
            if len(out) != 1:
                raise Exception("PGRST116: single row not found")  # mimic supabase
            return _Result(out[0], count=total)
        if self._maybe_single:
            return _Result(out[0] if out else None, count=total)
        return _Result(out, count=(total if self._count_mode else None))


# --------------------------------------------------------------------------- #
#  FakeDB
# --------------------------------------------------------------------------- #
class FakeDB:
    """In-memory Supabase client double. `.table(name)` returns a fresh query."""

    def __init__(self):
        self._tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, fn: str, params: Optional[dict] = None) -> "_Rpc":
        return _Rpc(self, fn, params or {})

    # convenience for tests/harness
    def seed(self, table: str, row: dict) -> dict:
        r = dict(row)
        r.setdefault("id", str(uuid.uuid4()))
        self._tables.setdefault(table, []).append(r)
        return r

    def rows(self, table: str) -> list[dict]:
        return self._tables.setdefault(table, [])


# --------------------------------------------------------------------------- #
#  RPC double — mirrors the SQL functions the kernel calls
# --------------------------------------------------------------------------- #
class _Rpc:
    def __init__(self, db: "FakeDB", fn: str, params: dict):
        self.db = db
        self.fn = fn
        self.params = params

    def execute(self) -> _Result:
        handler = getattr(self, f"_fn_{self.fn}", None)
        if handler is None:
            raise Exception(f"FakeDB: unsupported rpc {self.fn!r}")
        return _Result(handler())

    def _fn_post_journal_atomic(self):
        """Mirror migrations/152 post_journal_atomic: insert header + lines
        atomically (trivially atomic in-memory), with (firm, client, reference_no,
        entry_date) idempotency. Returns the entry id."""
        entry = dict(self.params["p_entry"])
        lines = self.params["p_lines"]
        entries = self.db._tables.setdefault("journal_entries", [])
        ref = entry.get("reference_no")
        if ref is not None:
            for r in entries:
                if (r.get("firm_id") == entry.get("firm_id")
                        and r.get("client_id") == entry.get("client_id")
                        and r.get("reference_no") == ref
                        and r.get("entry_date") == entry.get("entry_date")
                        and not r.get("deleted_at")):
                    return r["id"]  # dedup: return the existing winner
        entry.setdefault("id", str(uuid.uuid4()))
        entries.append(entry)
        line_store = self.db._tables.setdefault("journal_lines", [])
        for l in lines:
            lr = dict(l)
            lr["journal_entry_id"] = entry["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            line_store.append(lr)
        return entry["id"]


# --------------------------------------------------------------------------- #
#  Standard chart of accounts (system keys the journal service resolves)
# --------------------------------------------------------------------------- #
# phase2_journal_service._find_account resolves by system_account_key first,
# then by account_name ILIKE. Seed both so either resolution path works.
STANDARD_COA: list[tuple[str, str]] = [
    ("ar",             "Trade Receivables"),
    ("ap",             "Trade Payables"),
    ("revenue",        "Sales Revenue"),
    ("bank",           "Bank Account"),
    ("gst_cgst",       "GST Output - CGST"),
    ("gst_sgst",       "GST Output - SGST"),
    ("gst_igst",       "GST Output - IGST"),
    ("gst_input",      "GST Input Tax Credit"),
    ("tds_receivable", "TDS Receivable"),
    ("tds_payable",    "TDS Payable"),
    ("fx_realized",    "Foreign Exchange Gain/Loss (Realized)"),
    ("fx_unrealized",  "Foreign Exchange Gain/Loss (Unrealized)"),
    (None,             "Purchases"),
    (None,             "Professional Fees Expense"),
]


def seed_standard_coa(db: FakeDB, firm_id: str, client_id: str) -> dict[str, str]:
    """Seed a standard COA for (firm, client). Returns {system_key_or_name: id}."""
    ids: dict[str, str] = {}
    for key, name in STANDARD_COA:
        row = db.seed("chart_of_accounts", {
            "firm_id": firm_id,
            "client_id": client_id,
            "system_account_key": key,
            "account_name": name,
            "is_active": True,
        })
        ids[key or name] = row["id"]
    return ids


def trial_balance(db: FakeDB, firm_id: str, client_id: str) -> dict[str, int]:
    """
    Sum posted journal_lines for (firm, client) into total debit / credit (paise).
    A correct double-entry ledger must have total_debit == total_credit.
    """
    entry_ids = {
        e["id"] for e in db.rows("journal_entries")
        if e.get("firm_id") == firm_id and e.get("client_id") == client_id
        and e.get("is_posted", True)
    }
    total_debit = sum(
        int(l.get("debit_paise", 0)) for l in db.rows("journal_lines")
        if l.get("journal_entry_id") in entry_ids
    )
    total_credit = sum(
        int(l.get("credit_paise", 0)) for l in db.rows("journal_lines")
        if l.get("journal_entry_id") in entry_ids
    )
    return {"total_debit_paise": total_debit, "total_credit_paise": total_credit}


def account_balance(db: FakeDB, account_id: str) -> int:
    """Net (debit - credit) paise posted to a single account across all entries."""
    return sum(
        int(l.get("debit_paise", 0)) - int(l.get("credit_paise", 0))
        for l in db.rows("journal_lines")
        if l.get("account_id") == account_id
    )


def coa_id(db: FakeDB, firm_id: str, system_key: str) -> Optional[str]:
    """Look up a seeded COA account id by system_account_key (for balance asserts)."""
    for r in db.rows("chart_of_accounts"):
        if r.get("firm_id") == firm_id and r.get("system_account_key") == system_key:
            return r["id"]
    return None


def _noop(*_a, **_k):
    return None


def wire_e2e(monkeypatch, db: FakeDB, router_modules: list) -> None:
    """
    Route the real code paths at `router_modules` to the shared FakeDB and flip
    them out of mock mode, then neutralise incidental side-effects (audit log,
    timeline, locked-period validation, HSN-preference learning) so the cycle
    asserts ACCOUNTING state, not I/O plumbing. Journals DO post for real.
    """
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)

    # Journals must actually post (else reconciliation can't be asserted).
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pjs, "_USE_MOCK", False)

    for mod in router_modules:
        if hasattr(mod, "_USE_MOCK"):
            monkeypatch.setattr(mod, "_USE_MOCK", False)
        if hasattr(mod, "log_event"):
            monkeypatch.setattr(mod, "log_event", _noop)
        if hasattr(mod, "_record_hsn_preferences"):
            monkeypatch.setattr(mod, "_record_hsn_preferences", _noop)
        # Side-effect singletons: patch the methods on the shared object so every
        # module that imported the same singleton is covered.
        if hasattr(mod, "timeline_service"):
            for m in ("log", "log_timeline_event"):
                if hasattr(mod.timeline_service, m):
                    monkeypatch.setattr(mod.timeline_service, m, _noop)
        if hasattr(mod, "period_validation_service"):
            if hasattr(mod.period_validation_service, "validate_posting_date"):
                monkeypatch.setattr(
                    mod.period_validation_service, "validate_posting_date", _noop
                )
