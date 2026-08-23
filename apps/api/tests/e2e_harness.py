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
from datetime import datetime
import re
from typing import Any, Optional


# --------------------------------------------------------------------------- #
#  Result envelope (mimics supabase-py's APIResponse: .data, .count)
# --------------------------------------------------------------------------- #

# ── Generated columns (migration 278) ────────────────────────────────────────
# Postgres maintains these; an in-memory double has to, or every test that seeds
# an invoice sees outstanding_paise missing and AR/AP aging — which now FILTERS
# on it — reports the client owes nothing. The formulas are the column
# definitions in migration 278, and they are here rather than in each test so
# there is one place to keep in step with the schema.
# {table: {generated column: how Postgres computes it}}. Transcribed from the
# migrations that define them, because the services now FILTER on these columns:
# a double that does not carry them hands back an empty result where Postgres
# would have returned the answer, which looks exactly like a broken report.
#   outstanding_paise — migration 278 (base currency)
#   txn_outstanding   — migration 280 (transaction currency, minor units)
_GENERATED = {
    "client_sales_invoices": {
        "outstanding_paise": lambda r: (
            int(r.get("total_paise") or 0) + int(r.get("debit_note_paise") or 0)
            - int(r.get("paid_paise") or 0) - int(r.get("credited_paise") or 0)),
        "txn_outstanding": lambda r: (
            int(r.get("txn_total") or 0) - int(r.get("paid_txn") or 0)),
    },
    "purchase_bills": {
        "outstanding_paise": lambda r: (
            int(r.get("net_payable_paise") or 0) + int(r.get("credit_note_paise") or 0)
            - int(r.get("paid_paise") or 0) - int(r.get("debited_paise") or 0)),
        "txn_outstanding": lambda r: (
            int(r.get("txn_net_payable") or 0) - int(r.get("paid_txn") or 0)),
    },
}


# Unique indexes an INSERT would hit in Postgres. Only the ones production code
# actually reaches: chart_of_accounts is firm-wide unique on BOTH code and name,
# which is why creating a per-bank ledger has to disambiguate — two clients of one
# firm banking at the same branch produce the same "HDFC Bank — 7890".
#
# Enforced on insert() only, NOT on seed(). Fixtures seed the same standard chart
# for several clients of one firm, which real Postgres would reject; correcting
# that is a much larger job than this, and seeding is not the path under test.
_UNIQUE: dict[str, list[tuple[str, ...]]] = {
    "chart_of_accounts": [("firm_id", "account_code"), ("firm_id", "account_name")],
}


# Column DEFAULTS the production schema applies and an insert therefore omits.
# Only the ones a code path actually depends on. bank_accounts.is_active is the
# worked example: BankAccountIn has no is_active field, so a created account
# reaches the double without one — and `.eq("is_active", True)` then filtered out
# every freshly created account. A test asserting a DEACTIVATED account is hidden
# passed for the wrong reason, because the ACTIVE one was hidden too.
_DEFAULTS: dict[str, dict] = {
    "bank_accounts": {"is_active": True},
    # NOT NULL DEFAULT 'unmatched' / DEFAULT false in the real schema. The
    # queue's view filter is SQL now, so a row inserted without them must land
    # in the same view here as it would in Postgres.
    "bank_transactions": {"match_status": "unmatched", "needs_review": False},
    "chart_of_accounts": {"is_active": True},
}


def _apply_defaults(table: str, row: dict) -> None:
    for col, val in _DEFAULTS.get(table, {}).items():
        row.setdefault(col, val)


def _enforce_unique(table: str, rows: list, new_row: dict) -> None:
    """Raise the way Postgres would when an insert violates a unique index."""
    for cols in _UNIQUE.get(table, []):
        if any(new_row.get(c) is None for c in cols):
            continue
        key = tuple(new_row.get(c) for c in cols)
        if any(tuple(r.get(c) for c in cols) == key for r in rows):
            raise Exception(
                f'duplicate key value violates unique constraint '
                f'"{table}_{"_".join(cols)}_key" — key ({", ".join(cols)})=({key})')


def _apply_generated(table: str, rows: list) -> None:
    """Recompute the generated columns for a table's rows, in place."""
    cols = _GENERATED.get(table)
    if not cols:
        return
    for r in rows:
        for name, fn in cols.items():
            try:
                r[name] = fn(r)
            except (TypeError, ValueError):
                r[name] = 0


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
        self._order: list[tuple[str, bool]] = []
        self._limit: Optional[int] = None
        self._range: Optional[tuple[int, int]] = None
        self._single = False
        self._maybe_single = False
        self._negate = False
        self._count_mode: Optional[str] = None
        self._cols: str = "*"

    # -- operation selectors -------------------------------------------------
    def select(self, cols: str = "*", count: Optional[str] = None, **_k):
        self._op = "select"; self._count_mode = count
        self._cols = cols
        return self

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
        # ACCUMULATES, as PostgREST does: `.order("a").order("b")` is
        # `ORDER BY a, b`. It used to overwrite, which silently threw away the
        # tiebreak — and a paged read whose sort key has ties cannot be paged
        # correctly without one (rows repeat on one page and vanish from the
        # next). The double has to have the tiebreak for the test to be able
        # to catch its absence.
        self._order.append((col, desc)); return self

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
        # Applied last key first — a stable sort then leaves the earlier keys
        # dominant, which is what ORDER BY a, b means.
        out = rows
        for col, desc in reversed(self._order):
            out = sorted(out, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        return out

    # -- execution -----------------------------------------------------------
    def _project(self, row: dict) -> dict:
        """Return only the columns the caller actually selected.

        PostgREST does this; FakeDB did not, and the difference hides a real
        class of bug: a guard that reads `row["client_id"]` keeps working in
        tests after somebody narrows the SELECT to `"id"`, and only fails
        against a live database. Embeds (`a(b,c)`), `*` and aggregate selects
        are passed through untouched — this only narrows a plain column list.
        """
        cols = self._cols
        if cols == "*" or "(" in cols or ":" in cols:
            return dict(row)
        wanted = {c.strip() for c in cols.split(",") if c.strip()}
        if not wanted or "*" in wanted:
            return dict(row)
        return {k: v for k, v in row.items() if k in wanted}

    def execute(self) -> _Result:
        rows = self.db._tables.setdefault(self.table, [])
        # Before anything reads or filters: rows seeded straight into
        # _tables never went through insert(), and a stored generated column
        # is not optional in Postgres.
        _apply_generated(self.table, rows)

        if self._op in ("insert", "upsert"):
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                r = dict(p)
                r.setdefault("id", str(uuid.uuid4()))
                _apply_defaults(self.table, r)
                _enforce_unique(self.table, rows, r)
                rows.append(r)
                inserted.append(r)
            _apply_generated(self.table, rows)
            return _Result([dict(r) for r in inserted])

        if self._op == "update":
            matched = [r for r in rows if self._match(r)]
            for r in matched:
                r.update(self._payload)
            _apply_generated(self.table, rows)   # a payment changes what is outstanding
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
        # Projection LAST: PostgREST orders, ranges and limits server-side, so
        # an ORDER BY column does not have to appear in the SELECT list.
        # Projecting first made `.order("created_at")` a no-op whenever
        # created_at was not selected — which is not how the real thing behaves.
        out = [self._project(r) for r in out]
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

    def _fn_period_lock_reason(self):
        """Mirror migration 267's period_lock_reason.

        Faithful rather than stubbed, because it is now consulted on every
        sales-invoice and purchase-bill write: a stub returning "open" would
        make every lock test vacuous, and one returning "closed" would fail
        every test that is not about locking. With no locked years and no
        filings seeded — the state most tests are in — it returns None, which
        is what a real database with those tables empty returns.
        """
        p_firm = self.params.get("p_firm")
        p_client = self.params.get("p_client")
        p_date = self.params.get("p_date")
        if not p_date:
            return None

        year, month = int(str(p_date)[:4]), int(str(p_date)[5:7])
        fy_start = year if month >= 4 else year - 1
        fy_label = f"{fy_start}-{str(fy_start + 1)[-2:]}"

        firm = next((f for f in self.db._tables.get("firms", [])
                     if f.get("id") == p_firm), None)
        if fy_label in ((firm or {}).get("locked_financial_years") or []):
            return (f"Financial year {fy_label} is locked. Unlock it, or post a "
                    "reversal in an open year.")

        covering = [f for f in self.db._tables.get("filings", [])
                    if f.get("client_id") == p_client
                    and not f.get("deleted_at")
                    and f.get("filed_date")
                    and str(f.get("period_start") or "") <= str(p_date) <= str(f.get("period_end") or "")]
        if covering:
            covering.sort(key=lambda f: str(f.get("filed_date")))
            hit = covering[0]
            when = datetime.strptime(str(hit["filed_date"])[:10], "%Y-%m-%d").strftime("%d %b %Y")
            return (f"{hit.get('filing_type')} covering this date was filed on {when}. "
                    "Correct it with a reversal and an amendment in the next return.")
        return None

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
                        and not r.get("deleted_at")
                        and not r.get("is_reversed")):
                    return r["id"]  # dedup: return the existing (live, unreversed) winner
        entry.setdefault("id", str(uuid.uuid4()))
        entries.append(entry)
        line_store = self.db._tables.setdefault("journal_lines", [])
        for l in lines:
            lr = dict(l)
            lr["journal_entry_id"] = entry["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            line_store.append(lr)

        # Migration 274: when the entry IS a reversal, the real function stamps
        # the original in the SAME transaction. It moved in there from a
        # separate PostgREST UPDATE, which fails with 42501 whenever the API
        # runs as `authenticated` — journal_entries grants that role SELECT and
        # nothing else.
        #
        # Mirrored here rather than left out: the dedup loop above SKIPS a
        # reversed entry, so a fake that never sets the flag would let a re-post
        # match a dead entry and hand back its id — the exact production bug,
        # invisible in mock mode. The guard matches the real UPDATE's
        # COALESCE(is_reversed,false) = false predicate.
        reversal_of = entry.get("reversal_of")
        if reversal_of:
            for r in entries:
                if (r.get("id") == reversal_of
                        and r.get("firm_id") == entry.get("firm_id")
                        and not r.get("is_reversed")):
                    r["is_reversed"] = True
        return entry["id"]

    def _fn_numbered_document_atomic(self):
        """Mirror migration 167 numbered_document_atomic: insert a numbered
        header + its lines atomically (trivially atomic in-memory). Returns
        the header row (dict), matching the real RPC's scalar jsonb return."""
        header_table = self.params["p_header_table"]
        header = dict(self.params["p_header"])
        lines_table = self.params["p_lines_table"]
        lines = self.params["p_lines"]
        fk_column = self.params["p_lines_fk_column"]

        header.setdefault("id", str(uuid.uuid4()))
        self.db._tables.setdefault(header_table, []).append(header)

        line_store = self.db._tables.setdefault(lines_table, [])
        for l in lines:
            lr = dict(l)
            lr[fk_column] = header["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            line_store.append(lr)
        return header

    def _fn_settle_receipt_atomic(self):
        """Mirror migrations/160+162 settle_receipt_atomic: insert the journal
        header+lines, the receipt row, and every allocation's invoice update
        (trivially atomic in-memory — a real exception here would need to undo
        prior appends to be a faithful mirror, but no test exercises a
        mid-function failure path against this fake; that's proven for real
        against Postgres in test_r2_12_atomic_receipt_settlement_pg.py).
        Unlike post_journal_atomic, this does NOT dedupe/return-existing on a
        matching reference — the real function doesn't either (R2.12: a
        genuine collision must roll back and surface as an error, not silently
        attribute the request to someone else's committed row). Mirrors 162's
        balance/zero guard and per-invoice allocation aggregation too."""
        receipt = dict(self.params["p_receipt"])
        entry = dict(self.params["p_journal_entry"])
        lines = self.params["p_journal_lines"]
        allocations = self.params["p_allocations"]

        total_debit = sum(int(l.get("debit_paise") or 0) for l in lines)
        total_credit = sum(int(l.get("credit_paise") or 0) for l in lines)
        if total_debit != total_credit:
            raise Exception(f"settle_receipt_atomic: journal imbalance debit={total_debit} credit={total_credit}")
        if total_debit == 0:
            raise Exception("settle_receipt_atomic: refusing to post a zero-value journal entry")

        entry.setdefault("id", str(uuid.uuid4()))
        self.db._tables.setdefault("journal_entries", []).append(entry)
        line_store = self.db._tables.setdefault("journal_lines", [])
        for l in lines:
            lr = dict(l)
            lr["journal_entry_id"] = entry["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            line_store.append(lr)

        receipt["journal_entry_id"] = entry["id"]
        receipt.setdefault("id", str(uuid.uuid4()))
        self.db._tables.setdefault("receipts", []).append(receipt)

        invoices = self.db._tables.setdefault("client_sales_invoices", [])
        alloc_store = self.db._tables.setdefault("receipt_allocations", [])
        alloc_results = []
        by_invoice: dict = {}
        for a in allocations:
            allocated_paise = int(a.get("allocated_paise") or 0)
            if allocated_paise <= 0:
                continue
            inv_id = a.get("sales_invoice_id")
            by_invoice[inv_id] = by_invoice.get(inv_id, 0) + allocated_paise

        for inv_id, allocated_paise in by_invoice.items():
            inv = next(
                (r for r in invoices
                 if r.get("id") == inv_id
                 and r.get("firm_id") == receipt.get("firm_id")
                 and r.get("client_id") == receipt.get("client_id")),
                None,
            )
            if inv is None:
                raise Exception(f"settle_receipt_atomic: invoice {inv_id} is not part of this client's books")
            # task #227 / migration 235: a draft invoice was never issued (no AR
            # journal exists to settle) and a cancelled one is terminal.
            if inv.get("status") in ("draft", "cancelled"):
                raise Exception(f"settle_receipt_atomic: invoice {inv_id} is {inv.get('status')} and cannot receive a payment")
            # A sales debit note (CGST Act §34(3)) increases what's collectible —
            # mirrors migration 211's patch to the real settle_receipt_atomic.
            total = int(inv.get("total_paise", 0)) + int(inv.get("debit_note_paise", 0) or 0)
            credited = int(inv.get("credited_paise", 0) or 0)
            new_paid = int(inv.get("paid_paise", 0) or 0) + allocated_paise
            if new_paid + credited > total:
                raise Exception(f"settle_receipt_atomic: allocation to invoice {inv_id} exceeds its outstanding")
            new_status = "paid" if new_paid + credited >= total else "partially_paid"
            inv["paid_paise"] = new_paid
            inv["status"] = new_status
            alloc_row = {
                "id": str(uuid.uuid4()), "receipt_id": receipt["id"],
                "sales_invoice_id": inv_id, "allocated_paise": allocated_paise,
            }
            alloc_store.append(alloc_row)
            alloc_results.append({
                "sales_invoice_id": inv_id, "allocated_paise": allocated_paise,
                "new_paid_paise": new_paid, "new_status": new_status,
            })

        return {
            "receipt_id": receipt["id"],
            "journal_entry_id": entry["id"],
            "receipt": dict(receipt),
            "allocations": alloc_results,
        }


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
