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

import contextlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from services.numbering import NUMBER_SERIES as _NUMBER_SERIES


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
#
# The document-number keys are DERIVED from services.numbering.NUMBER_SERIES —
# the same declaration next_sequence checks a caller's scope against — so the
# harness enforces exactly the scope the sequence is computed over. Getting the
# two out of step is the bug migration 151 fixed for invoices and credit notes,
# 159 for debit notes and receipts, and 350 for sales debit notes and purchase
# credit notes: the number is per client, the constraint was per firm, and the
# firm's second client could never insert.
_UNIQUE: dict[str, list[tuple[str, ...]]] = {
    "chart_of_accounts": [("firm_id", "account_code"), ("firm_id", "account_name")],
    # Migration 461's uq_late_interest_charges_invoice_period_to. It covers EVERY
    # row, so a charge whose draft was cancelled or deleted still occupies its
    # key — the very thing `late_interest_service` has to release before the same
    # period can be taken up again. A double that does not enforce it cannot see
    # that (accounting-22), and a test pins this tuple to the migration.
    "late_interest_charges": [("sales_invoice_id", "period_to")],
    **{table: [tuple(scope) + (field,)]
       for table, (field, scope) in _NUMBER_SERIES.items()},
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
    # NOT NULL DEFAULT false / 0 in the real schema (migrations 025, 351).
    # create_asset omits them, and post_depreciation reads asset["is_disposed"]
    # by subscript — a row inserted without it KeyErrors here where Postgres
    # would have supplied false.
    "fixed_assets": {"is_disposed": False, "accumulated_depreciation_paise": 0,
                     "corrections_count": 0},
    # NOT NULL DEFAULT 'moving_average' (migration 394). A writer that omits the stamp gets the weighted
    # average whatever the client's policy is, and the Significant Accounting Policies note counts that column
    # to say which formula priced the year: the godown transfer omitted it, and a FIFO client with one transfer
    # was told it had changed its accounting policy. Fixtures that stamp every row by hand cannot see that, so
    # the double supplies what Postgres would (the suite's own `_moved` helper seeds, and seeding is untouched).
    "inventory_stock_ledger": {"costing_method": "moving_average"},
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
# --------------------------------------------------------------------------- #
#  Writes are checked against production's own column types
# --------------------------------------------------------------------------- #
# The mock suite runs against an in-memory dict, which accepts anything — so a
# write that Postgres rejects passes here and fails only in production, usually
# silently, because the failing statement sits inside a broad try/except or a
# background job. Five defects in the 7 September 2026 audit were that shape;
# the worst wrote the string '2026-04' into a DATE column, which makes Postgres
# reject the WHOLE update and leave every other column as it was.
#
# tests/production_types.py reads the schema snapshot the drift tests already
# maintain, so this costs no Postgres and no new fixture.
#
# THE ESCAPE HATCH IS FOR ONE CASE ONLY: a test that is deliberately about how
# the code behaves when the database refuses. Turning it off to make a failure
# go away is turning off the finding.
#
# It is a CONTEXT MANAGER rather than a setter on purpose. A plain
# `enforce(False)` that a test forgets to undo disarms the guard for every test
# after it in the same process, silently — which is precisely the class of
# failure this whole module exists to catch, and it would be catching it in
# itself. `with production_types_unenforced():` cannot leak.
_ENFORCE_PRODUCTION_TYPES = True


@contextlib.contextmanager
def production_types_unenforced():
    """Suspend the write-type check for one block. See above before using it."""
    global _ENFORCE_PRODUCTION_TYPES
    previous = _ENFORCE_PRODUCTION_TYPES
    _ENFORCE_PRODUCTION_TYPES = False
    try:
        yield
    finally:
        _ENFORCE_PRODUCTION_TYPES = previous


def _check_write(table: str, payload) -> None:
    if not _ENFORCE_PRODUCTION_TYPES:
        return
    from tests.production_types import assert_write_fits_production_types
    assert_write_fits_production_types(table, payload)


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
        self._op = "insert"; self._payload = payload
        _check_write(self.table, payload)
        return self

    def update(self, payload, **_k):
        self._op = "update"; self._payload = payload
        _check_write(self.table, payload)
        return self

    def upsert(self, payload, **kw):
        self._op = "upsert"
        self._payload = payload
        _check_write(self.table, payload)
        # on_conflict is what makes an upsert an UPSERT rather than an insert.
        # It was discarded, so every upsert appended a second row and the read
        # afterwards found the STALE one — a second "switch payroll off" left
        # the "on" row in front of it and the write it should have refused went
        # through. In Postgres the UNIQUE index behind on_conflict makes that
        # impossible; the double has to behave the same way or it hides exactly
        # the bugs it exists to catch.
        self._on_conflict = [c.strip() for c in str(kw.get("on_conflict") or "").split(",")
                             if c.strip()]
        return self

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
        if kind == "not_is":
            # `.not_.is_(col, "null")` — how the real code asks for "this
            # column is filled in" (ageing_schedule_service,
            # bank_matching_service, msme_43bh_service, and the bank-GST fetch
            # in gst_return_service). Unimplemented, it raised — but the
            # DANGEROUS shape is the opposite one: a fake that answered a
            # negated filter as a passthrough would return every row and the
            # test would pass on data the database never would have sent.
            return not cls._term(row, "is", col, val)
        if kind == "like":  return cls._ilike(rv, val)  # case-sensitive in PG; ok for tests
        if kind == "ilike": return cls._ilike(rv, val)
        if kind == "not_eq": return rv != val
        if kind == "or":    return cls._or_expr(row, val)
        raise NotImplementedError(f"FakeDB filter not implemented: {kind}")

    _OR_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "is", "ilike", "like"}

    @staticmethod
    def _split_top(expr: str) -> list[str]:
        """Split on commas at paren depth 0.

        `expr.split(",")` tore `and(a.gte.1,a.lte.9)` into `and(a.gte.1` and
        `a.lte.9)`, whose column names are `and(a` and whose value is `9)` —
        neither matches anything, so the group silently evaluated to False
        instead of raising. A band filter that quietly matches nothing looks
        exactly like "there were no candidates"."""
        out, depth, cur = [], 0, []
        for ch in expr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                out.append("".join(cur)); cur = []
            else:
                cur.append(ch)
        if cur:
            out.append("".join(cur))
        return [t.strip() for t in out if t.strip()]

    @classmethod
    def _coerce(cls, v: str) -> Any:
        if v == "null":
            return None
        if v.lstrip("-").isdigit():
            return int(v)
        return v

    @classmethod
    def _or_term(cls, row: dict, term: str) -> bool:
        """One disjunct: a `col.op.val`, or a nested and(…)/or(…) group."""
        if term.startswith("and(") and term.endswith(")"):
            inner = cls._split_top(term[4:-1])
            return all(cls._or_term(row, t) for t in inner)
        if term.startswith("or(") and term.endswith(")"):
            inner = cls._split_top(term[3:-1])
            return any(cls._or_term(row, t) for t in inner)
        parts = term.split(".", 2)
        if len(parts) != 3:
            # Not a comparison and not a group we know — refuse rather than
            # silently drop it, which is how a wrong filter passes as a pass.
            raise NotImplementedError(f"FakeDB or() term not understood: {term!r}")
        c, op, v = parts
        if op == "in":
            # `col.in.("a","b")` — PostgREST's in-list inside an or(). The
            # commas sit inside the parens, so _split_top has already kept the
            # whole thing as ONE term. Each element may be quoted (which is how
            # a value containing a comma is escaped) and is coerced the same
            # way a scalar is, so `id.in.(1,2)` compares as ints.
            if not (v.startswith("(") and v.endswith(")")):
                raise NotImplementedError(f"FakeDB or() in-list not understood: {v!r}")
            vals = [cls._coerce(e.strip().strip('"')) for e in v[1:-1].split(",") if e.strip()]
            return row.get(c) in vals
        if op not in cls._OR_OPS:
            raise NotImplementedError(f"FakeDB or() operator not implemented: {op!r}")
        return cls._term(row, op, c, cls._coerce(v))

    @classmethod
    def _or_expr(cls, row: dict, expr: str) -> bool:
        """A PostgREST or() expression: comma-separated disjuncts, each either
        `col.op.val` or a nested and(…)/or(…) group."""
        return any(cls._or_term(row, t) for t in cls._split_top(expr))

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
            conflict = getattr(self, "_on_conflict", []) if self._op == "upsert" else []
            inserted = []
            appended_before = len(rows)
            for p in payload:
                r = dict(p)
                if conflict and all(c in r for c in conflict):
                    key = tuple(r[c] for c in conflict)
                    existing = next(
                        (x for x in rows
                         if tuple(x.get(c) for c in conflict) == key), None)
                    if existing is not None:
                        # ON CONFLICT DO UPDATE: the row is AMENDED in place,
                        # keeping its id and every column the payload omits.
                        existing.update(r)
                        inserted.append(existing)
                        continue
                r.setdefault("id", str(uuid.uuid4()))
                _apply_defaults(self.table, r)
                try:
                    _enforce_unique(self.table, rows, r)
                except Exception:
                    # ONE INSERT STATEMENT IS ALL-OR-NOTHING IN POSTGRES: a
                    # multi-row insert that hits a unique index leaves none of
                    # its rows behind, and a double that kept the first few
                    # would let a test pass on a half-written claim.
                    del rows[appended_before:]
                    raise
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


# The line table and the foreign key to the header, per kind of document (the issue routes read them: POST-A-335).
_LINE_TABLE = {
    "sales_invoice": ("client_sales_invoice_lines", "sales_invoice_id"),
    "purchase_bill": ("purchase_bill_lines", "bill_id"),
    "credit_note": ("credit_note_lines", "credit_note_id"),
    "debit_note": ("debit_note_lines", "debit_note_id"),
    "purchase_credit_note": ("purchase_credit_note_lines", "credit_note_id"),
    "sales_debit_note": ("sales_debit_note_lines", "debit_note_id"),
}


def with_lines(db: "FakeDB", kind: str, header: dict) -> dict:
    """Make a document seeded straight into its table the way the API leaves a draft: GST column set from the three heads, a
    bill's net payable set from its total, and ONE line carrying the header's figures. An issue route asks a draft whether it adds
    up to its lines before it posts it (POST-A-335), and a bare header is exactly what that question refuses. `header` is the dict
    `db.seed` returned (the stored row), and it is returned again changed in place."""
    heads = [int(header.get(k) or 0) for k in ("cgst_paise", "sgst_paise", "igst_paise")]
    header.setdefault("total_gst_paise", sum(heads))
    if kind == "purchase_bill":
        header.setdefault("net_payable_paise", int(header.get("total_paise") or 0) - int(header.get("tds_paise") or 0))
    table, fk = _LINE_TABLE[kind]
    db.seed(table, {
        fk: header["id"],
        "taxable_amount_paise": int(header.get("taxable_amount_paise") or 0),
        "cgst_paise": heads[0], "sgst_paise": heads[1], "igst_paise": heads[2],
        "cess_paise": int(header.get("cess_paise") or 0), "discount_paise": int(header.get("discount_paise") or 0),
        "itc_eligible": True,
    })
    return header


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

    def _fn_replace_draft_document_lines(self):
        """Mirror migration 560: the header is looked up for the firm and must be a draft, the old lines go and the new ones are
        stored with the document's own id as their foreign key (trivially atomic in memory). The two refusals carry the words
        the real function raises, which `services/draft_document_lines` reads."""
        headers = {"sales_invoice": "client_sales_invoices", "purchase_bill": "purchase_bills", "credit_note": "credit_notes",
                   "debit_note": "debit_notes", "sales_debit_note": "sales_debit_notes",
                   "purchase_credit_note": "purchase_credit_notes"}
        kind, doc_id, firm = self.params["p_document"], self.params["p_document_id"], self.params["p_firm_id"]
        header = next((r for r in self.db.rows(headers[kind]) if r.get("id") == doc_id and r.get("firm_id") == firm), None)
        if header is None:
            raise Exception("document_not_found")
        if header.get("status") != "draft":
            raise Exception("document_not_draft")
        table, fk = _LINE_TABLE[kind]
        store = self.db._tables.setdefault(table, [])
        store[:] = [r for r in store if r.get(fk) != doc_id]
        for ln in self.params["p_lines"]:
            row = {**ln, fk: doc_id}
            row.setdefault("id", str(uuid.uuid4()))
            store.append(row)
        return len(self.params["p_lines"])

    def _fn_tds_deposit_position(self):
        """DELEGATES to domain.tds.undeposited, the Python twin of migration 523's SQL function (the challan register's answer):
        one row of the two figures, as PostgREST returns a function that RETURNS TABLE."""
        from domain.tds.undeposited import position
        firm, ids = self.params.get("p_firm_id"), self.params.get("p_client_ids")
        got = position(
            [r for r in self.db.rows("tds_deductions") if r.get("firm_id") == firm],
            [r for r in self.db.rows("tds_challans") if r.get("firm_id") == firm], client_ids=ids)
        return [{"undeposited_paise": got.undeposited_paise, "not_recorded_paise": got.not_recorded_paise}]

    def _fn_period_lock_reason(self):
        """DELEGATES to services.period_lock_service.reason_from_tables.

        This used to be a third hand-written copy of migration 267's logic, and
        migration 361 proved why that is untenable: it added a branch — the
        client's own finalised year — and this copy silently did not have it, so
        every test using the harness reported an open period where the database
        reports a closed one.

        There are now TWO implementations of "is this period closed", which is
        the number CLAUDE.md allows: the SQL function, and the Python twin that
        exists because mock mode and the in-memory sources have no SQL
        functions at all. They are pinned to each other by
        tests/test_period_lock_reason_parity_pg.py. A double that answers the
        question its own third way is a double that will eventually disagree
        with both.
        """
        from services.period_lock_service import reason_from_tables
        return reason_from_tables(
            self.db, self.params.get("p_firm"), self.params.get("p_client"),
            self.params.get("p_date"))

    # journal_period_lock_reason is migration 267's delegate to the same
    # function, kept because edit_posted_journal calls it by that name.
    _fn_journal_period_lock_reason = _fn_period_lock_reason

    def _fn_period_closure_reason(self):
        """Migration 361's other entry point — the DELIBERATE closures only,
        which is what the posting kernel asks. Delegates for the same reason."""
        from services.period_lock_service import _closure_from_tables
        return _closure_from_tables(
            self.db, self.params.get("p_firm"), self.params.get("p_client"),
            self.params.get("p_date"))

    def _fn_stock_position_as_at(self):
        """Migration 363. DELEGATES to the same Python twin production falls
        back to, for the same reason the two above do: a double that answers
        the question its own third way is a double that will disagree with
        both. tests/test_stock_position_parity_pg.py pins the twin to the SQL.
        """
        from domain.reporting import stock_position
        firm = self.params.get("p_firm")
        client = self.params.get("p_client")
        item = self.params.get("p_item")
        rows = [r for r in self.db.rows("inventory_stock_ledger")
                if str(r.get("firm_id")) == str(firm)
                and str(r.get("client_id")) == str(client)
                and (item is None or str(r.get("service_catalogue_id")) == str(item))]
        names = {str(c["id"]): c
                 for c in self.db.rows("service_catalogue")
                 if str(c.get("firm_id")) == str(firm)
                 and str(c.get("client_id")) == str(client)}
        return stock_position.position(rows, str(self.params.get("p_as_of"))[:10], names)

    def _fn_post_journal_atomic(self):
        """Mirror migrations/152 post_journal_atomic: insert header + lines
        atomically (trivially atomic in-memory), with (firm, client, reference_no,
        entry_date) idempotency. Returns the entry id."""
        entry = {k: v for k, v in self.params["p_entry"].items() if k != "audit_actor"}     # migration 545 removes it first
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
        store = self.db._tables.setdefault(header_table, [])
        # The real RPC inserts into a real table, so the unique index applies —
        # this is how a numbering collision reaches services/numbering.py's retry.
        _enforce_unique(header_table, store, header)
        store.append(header)

        line_store = self.db._tables.setdefault(lines_table, [])
        for l in lines:
            lr = dict(l)
            lr[fk_column] = header["id"]
            lr.setdefault("id", str(uuid.uuid4()))
            line_store.append(lr)
        return header

    def _fn_settle_receipt_atomic(self):
        """Mirror migrations/160+162+235+574 settle_receipt_atomic: insert the journal
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
        # The real function stores the columns of ITS INSERT INTO receipts and nothing else (migration 574 added id, bank_account_id and the three
        # Table 11A columns to a list that had dropped them for months while this double stored the whole payload, so no mock test could see it).
        # The list is read from the last migration that defines the function's body, so a key the service sends that the function drops is dropped
        # here too and a test reading it fails the way production would.
        from tests import _receipt_function_source
        stored_columns = set(_receipt_function_source.current_columns()[1])
        receipt = {k: v for k, v in self.params["p_receipt"].items() if k in stored_columns}
        entry = {k: v for k, v in self.params["p_journal_entry"].items() if k != "audit_actor"}     # migration 545 removes it first
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

    def _fn_file_it_declaration(self):
        """Mirror migration 548 `file_it_declaration`: ONE filing of an employee's Form 12BB, returning the declaration's id.

        The SQL runs in one transaction under a row lock; in memory that is trivially true, EXCEPT that a refusal must leave
        nothing behind, so every check is made before anything is written. The refusals carry the SQLSTATE and the message the
        database sends, as the client's `APIError` shape (`message`, `code`), because the service maps them by those two."""
        from postgrest.exceptions import APIError

        def refuse(code, message):
            raise APIError({"message": message, "code": code, "hint": None, "details": None})

        decl = dict(self.params.get("p_declaration") or {})
        items = self.params.get("p_items")
        items = [] if items is None else items
        refuse_verified = bool(self.params.get("p_refuse_verified"))
        firm, client = decl.get("firm_id") or None, decl.get("client_id") or None
        employee, fy = decl.get("employee_id") or None, decl.get("fy") or None
        if not (firm and client and employee and fy):
            refuse("22023", "file_it_declaration: a declaration names its firm, client, employee and year")
        if not isinstance(items, list):
            refuse("22023", "file_it_declaration: the lines must be a JSON array")
        if not any(str(e.get("id")) == str(employee) and str(e.get("firm_id")) == str(firm) and str(e.get("client_id")) == str(client)
                   for e in self.db.rows("payroll_employees")):
            refuse("42501", f"file_it_declaration: employee {employee} is not an employee of client {client} of firm {firm}")
        for it in items:
            if not it.get("section"):
                refuse("23502", 'null value in column "section" of relation "payroll_it_declaration_items" violates not-null constraint')

        now = datetime.now(timezone.utc).isoformat()
        heads = self.db.rows("payroll_it_declarations")
        head = next((h for h in heads if str(h.get("employee_id")) == str(employee) and h.get("fy") == fy
                     and str(h.get("firm_id")) == str(firm)), None)
        if head is not None and head.get("proofs_verified") and refuse_verified:
            refuse("P0001", f"declaration_verified: the declaration for {fy} is verified and is not the employee's to change")

        fields = {
            "regime": decl.get("regime") or "new", "status": "submitted",
            "rent_paid_declared_paise": int(decl.get("rent_paid_declared_paise") or 0), "rent_paid_verified_paise": 0,
            "landlord_name": decl.get("landlord_name") or "", "landlord_address": decl.get("landlord_address") or "",
            "landlord_pan": decl.get("landlord_pan") or "", "rent_is_metro": bool(decl.get("rent_is_metro")),
            "lta_declared_paise": int(decl.get("lta_declared_paise") or 0), "lta_verified_paise": 0,
            "home_loan_interest_declared_paise": int(decl.get("home_loan_interest_declared_paise") or 0),
            "home_loan_interest_verified_paise": 0,
            "lender_name": decl.get("lender_name") or "", "lender_pan": decl.get("lender_pan") or "",
            "other_income_declared_paise": int(decl.get("other_income_declared_paise") or 0),
            "house_property_loss_declared_paise": int(decl.get("house_property_loss_declared_paise") or 0),
            "proofs_verified": False, "verified_at": None, "verified_by": None, "submitted_at": now, "updated_at": now,
        }
        if head is None:
            head = self.db.seed("payroll_it_declarations", {"firm_id": firm, "client_id": client, "employee_id": employee,
                                                           "fy": fy, **fields})
        else:
            head.update(fields)
        declaration_id = head["id"]

        # The lines are replaced wholesale: whatever the declaration held is gone, the lines given are all it holds.
        self.db._tables["payroll_it_declaration_items"] = [
            r for r in self.db.rows("payroll_it_declaration_items")
            if not (str(r.get("declaration_id")) == str(declaration_id) and str(r.get("firm_id")) == str(firm))]
        for it in items:
            self.db.seed("payroll_it_declaration_items", {
                "firm_id": firm, "declaration_id": declaration_id, "section": it["section"], "label": it.get("label") or "",
                "amount_declared_paise": int(it.get("amount_declared_paise") or 0), "amount_verified_paise": 0,
                "status": "declared", "proof_reference": it.get("proof_reference") or "",
                "proof_attachments": it.get("proof_attachments") or []})
        return declaration_id


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
