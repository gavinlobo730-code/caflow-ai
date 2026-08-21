"""A PostgREST-shaped database double that REFUSES columns the real schema
does not have.

WHY THIS EXISTS
    A run of production errors turned out to be one bug repeated: application
    code naming columns no migration ever created. PostgREST rejects those at
    PARSE time (42703) — before a row is considered — and almost every call
    site sits inside `try: ... except Exception: pass`, so the failures were
    silent and total. Whole features had never worked once.

    core/schema_guard.py cannot catch this class. It parses MIGRATIONS for
    ADD COLUMN and checks the database has them, which finds "a migration was
    never applied". These columns were never in a migration at all; they were
    invented in code. That is the opposite direction, and nothing checked it.

    tests/test_frontend_columns_exist_pg.py does check that direction, but only
    for apps/web's select lists. This is the equivalent for backend call sites
    the tests exercise directly.

HOW TO USE IT
    Seed rows, hand it to the production function unchanged, and assert on the
    result. A phantom column raises PhantomColumn — and because there is no
    `except` between the double and the assertion, it cannot pass quietly the
    way it passed in production.

KEEPING REAL_COLUMNS HONEST
    Every entry is copied from production's information_schema. A double that
    lags the real schema is worse than none: it would reject a legitimate new
    query and send someone hunting a bug that is not there. When a migration
    adds a column, add it here.
"""
from __future__ import annotations


class PhantomColumn(Exception):
    """Stands in for PostgREST's 42703, raised at parse time."""


# Verified against production information_schema.
REAL_COLUMNS: dict[str, set[str]] = {
    "advance_tax_payments": {
        "id", "firm_id", "client_id", "financial_year", "installment_number",
        "due_date", "required_percent", "estimated_tax_paise",
        "paid_amount_paise", "paid_date", "challan_number", "created_at",
    },
    "ai_insights": {
        "id", "client_id", "insight_type", "severity", "title", "description",
        "recommended_action", "related_entity_type", "related_entity_id",
        "status", "resolved_by", "resolved_at", "created_at", "updated_at",
        "deleted_at", "firm_id", "category",
    },
    "client_sales_invoice_lines": {
        "id", "sales_invoice_id", "description", "hsn_sac", "quantity", "unit",
        "rate_paise", "taxable_amount_paise", "gst_rate_bps", "cgst_paise",
        "sgst_paise", "igst_paise", "line_total_paise", "sort_order",
        "service_catalogue_id",
    },
    "document_requests": {
        "id", "firm_id", "client_id", "requested_by", "title", "description",
        "is_urgent", "status", "fulfilled_at", "storage_path", "file_name",
        "created_at",
    },
    "entities": {
        "id", "firm_id", "entity_type", "full_name", "pan", "gstin", "email",
        "phone", "address", "notes", "is_active", "created_by", "created_at",
        "updated_at", "date_of_birth",
    },
    "notifications": {
        "id", "firm_id", "user_id", "client_id", "type", "title", "body",
        "severity", "is_read", "action_url", "created_at", "is_archived",
        "metadata",
    },
    "portal_messages": {
        "id", "firm_id", "client_id", "sender_type", "sender_name", "body",
        "is_read", "read_at", "created_at",
    },
    # Migration 273. NOT public.loans — that is a client's own borrowings
    # register (lender_name, account_number, emi_paise) which the browser reads
    # directly. relationships.py wrote its related-party loans there for a long
    # time and never once succeeded.
    "related_party_loans": {
        "id", "firm_id", "client_id", "entity_id", "loan_type",
        "principal_paise", "interest_rate", "sanction_date", "due_date",
        "notes", "section_185_flagged", "section_186_flagged", "created_by",
        "created_at", "updated_at",
    },
    "journal_entries": {
        "id", "firm_id", "client_id", "entry_date", "reference_no", "narration",
        "entry_type", "is_posted", "posted_at", "created_by", "created_at",
        "updated_at", "deleted_at", "status", "reversal_of", "posted_by",
        "source_type", "source_id", "attachments", "rate_selected_by",
        "rate_overridden", "rate_selected_at", "is_reversed",
    },
    # The borrowings register, listed so a test that confuses it with
    # related_party_loans fails here rather than silently passing.
    "loans": {
        "id", "firm_id", "client_id", "loan_type", "lender_name",
        "account_number", "principal_paise", "outstanding_paise",
        "interest_rate_percent", "emi_paise", "disbursement_date",
        "maturity_date", "status", "notes", "created_at",
    },
    "users": {
        "id", "firm_id", "full_name", "email", "role", "is_active",
        "auth_user_id", "sessions_revoked_at", "created_at", "updated_at",
        "deleted_at", "phone",
    },
}

# Values the CHECK constraints actually permit. Filtering on a literal outside
# these matches nothing, which is its own silent failure — the health engine
# filtered ai_insights.severity on 'warning' and document_requests.status on
# 'Pending', neither of which any row can hold.
REAL_CHECK_VALUES: dict[tuple[str, str], set[str]] = {
    ("ai_insights", "severity"): {"critical", "high", "medium", "low", "info"},
    ("ai_insights", "status"): {"open", "acknowledged", "resolved", "dismissed"},
    ("document_requests", "status"): {"pending", "fulfilled"},
    ("notifications", "severity"): {"critical", "high", "medium", "low", "info"},
    ("notifications", "type"): {
        "task_assigned", "risk_detected", "document_processed", "compliance_due",
        "ai_recommendation", "status_changed", "task_reassigned", "due_soon",
        "overdue", "task_overdue", "recurring_generated", "workflow",
    },
    ("portal_messages", "sender_type"): {"ca", "client"},
    ("users", "role"): {"Partner", "Manager", "Executive", "Reviewer", "Client"},
    ("related_party_loans", "loan_type"): {
        "to_director", "from_director", "inter_company", "other"},
    # The borrowings register permits an entirely different set — which is the
    # whole reason these are two tables. `to_director` is not a bank product.
    ("loans", "loan_type"): {
        "term_loan", "overdraft", "cc", "home_loan", "vehicle_loan",
        "personal_loan", "other"},
}


class CheckViolation(Exception):
    """Stands in for Postgres 23514, a CHECK constraint violation."""


class _Query:
    def __init__(self, db: "SchemaCheckedDB", table: str):
        self.db, self.table = db, table
        self._filters: list[tuple[str, str, object]] = []
        self._limit: int | None = None

    # ── column / value validation ────────────────────────────────────────────

    def _check_column(self, col: str) -> None:
        known = self.db.columns.get(self.table)
        if known is None:
            raise PhantomColumn(f"relation {self.table!r} does not exist")
        if col not in known:
            raise PhantomColumn(f"column {self.table}.{col} does not exist")

    def _check_value(self, col: str, val) -> None:
        allowed = REAL_CHECK_VALUES.get((self.table, col))
        if allowed is not None and isinstance(val, str) and val not in allowed:
            raise CheckViolation(
                f"{self.table}.{col} = {val!r} violates its CHECK "
                f"(permitted: {sorted(allowed)})"
            )

    # ── read ─────────────────────────────────────────────────────────────────

    def select(self, expr: str, **kw):
        for col in (c.strip() for c in expr.split(",")):
            if col and col != "*":
                self._check_column(col)
        return self

    def _filter(self, col: str, val, op: str):
        self._check_column(col)
        # A filter value outside the CHECK set matches nothing rather than
        # erroring in real Postgres, so this is not raised here — the tests
        # assert on the empty result instead, which is the real behaviour.
        self._filters.append((op, col, val))
        return self

    def eq(self, col, val):  return self._filter(col, val, "eq")
    def neq(self, col, val): return self._filter(col, val, "neq")
    def lt(self, col, val):  return self._filter(col, val, "lt")
    def lte(self, col, val): return self._filter(col, val, "lte")
    def gt(self, col, val):  return self._filter(col, val, "gt")
    def gte(self, col, val): return self._filter(col, val, "gte")
    def in_(self, col, val): return self._filter(col, val, "in")
    def is_(self, col, val): return self._filter(col, val, "is")

    def order(self, col: str, **kw):
        self._check_column(col)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def single(self):
        # supabase-py's .single() returns the ROW, not a one-element list.
        # Returning a list here let a caller that indexes or .get()s the
        # result pass against the double and fail against the real client.
        self._limit = 1
        self._single = True
        return self

    # ── write ────────────────────────────────────────────────────────────────

    def insert(self, row):
        rows = row if isinstance(row, list) else [row]
        for r in rows:
            for col, val in r.items():
                self._check_column(col)
                self._check_value(col, val)
        self.db.rows.setdefault(self.table, []).extend(rows)
        self._pending = rows
        return self

    def update(self, fields: dict):
        for col, val in fields.items():
            self._check_column(col)
            self._check_value(col, val)
        self._update = fields
        return self

    def delete(self):
        self._delete = True
        return self

    # ── execute ──────────────────────────────────────────────────────────────

    def _matching(self) -> list[dict]:
        rows = list(self.db.rows.get(self.table, []))
        for op, col, val in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif op == "neq":
                rows = [r for r in rows if r.get(col) != val]
            elif op == "lt":
                rows = [r for r in rows if str(r.get(col) or "") < str(val)]
            elif op == "lte":
                rows = [r for r in rows if str(r.get(col) or "") <= str(val)]
            elif op == "gt":
                rows = [r for r in rows if str(r.get(col) or "") > str(val)]
            elif op == "gte":
                rows = [r for r in rows if str(r.get(col) or "") >= str(val)]
            elif op == "in":
                rows = [r for r in rows if r.get(col) in val]
            elif op == "is":
                # supabase-py spells IS NULL as .is_(col, "null"); None is
                # accepted too so a caller using either reads the same.
                want_null = val is None or str(val).lower() == "null"
                rows = [r for r in rows
                        if (r.get(col) is None) == want_null]
        return rows

    def execute(self):
        if getattr(self, "_delete", False):
            doomed = self._matching()
            kept = [r for r in self.db.rows.get(self.table, []) if r not in doomed]
            self.db.rows[self.table] = kept
            return _Result(doomed)
        if getattr(self, "_update", None) is not None:
            hit = self._matching()
            for r in hit:
                r.update(self._update)
            return _Result(hit)
        if getattr(self, "_pending", None) is not None:
            return _Result(self._pending)
        rows = self._matching()[: self._limit]
        if getattr(self, "_single", False):
            return _Result(rows[0] if rows else None)
        return _Result(rows)


class _Result:
    def __init__(self, data):
        self.data = data


class SchemaCheckedDB:
    """PostgREST-shaped double that refuses columns the real schema lacks."""

    def __init__(self, rows: dict[str, list[dict]] | None = None):
        self.rpc_calls: list["_RpcCall"] = []
        self.columns = REAL_COLUMNS
        self.rows = rows or {}

    def rpc(self, fn: str, params: dict | None = None) -> "_RpcCall":
        """Record the call. This double proves COLUMN names, and a SQL
        function's body is beyond what it can model — what a test can assert
        here is that the right function was called with the right arguments,
        and the behaviour itself belongs in a real-Postgres test."""
        call = _RpcCall(fn, params or {})
        self.rpc_calls.append(call)
        return call

    def table(self, name: str) -> _Query:
        return _Query(self, name)


class _RpcCall:
    """A recorded db.rpc(fn, params). raise_with() makes the next execute()
    raise, so a test can exercise the caller's error path; returns() sets the
    payload, for the functions whose RETURN VALUE the caller acts on."""

    def __init__(self, fn: str, params: dict):
        self.fn, self.params = fn, params
        self._raises: Exception | None = None
        self._data: object = []

    def raise_with(self, exc: Exception) -> "_RpcCall":
        self._raises = exc
        return self

    def returns(self, data: object) -> "_RpcCall":
        self._data = data
        return self

    def execute(self):
        if self._raises is not None:
            raise self._raises
        return _Result(self._data)
