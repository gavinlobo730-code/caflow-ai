"""
The health engine queried columns that do not exist, and said nothing.

WHAT WAS WRONG
    routers/health.py asked PostgREST for four columns that have never existed
    in any migration:

        advance_tax_payments.instalment_number   (real: installment_number)
        advance_tax_payments.paid                (no such column at all)
        ai_insights.acknowledged                 (real: status)
        document_requests.document_name          (real: title)

    plus two literals no row can hold: severity 'warning' (the CHECK permits
    critical/high/medium/low/info) and status 'Pending' (the CHECK permits
    lowercase 'pending'/'fulfilled').

    PostgREST rejects an unknown column at PARSE time — 42703, before a single
    row is considered — and every one of these calls sits inside
    `try: ... except Exception: pass`. So the failures were completely silent:

      * `advance_tax_2_consecutive` and `critical_ai_insight_14d` could never
        fire, for any client, ever;
      * `_dim_ai_risk_signals_db` scored a flat 100 for every client, because
        both of its queries raised and both `except` branches left the score
        untouched.

    schema_guard.py could not catch this: it parses MIGRATIONS for ADD COLUMN
    and checks the database has them. It finds "a migration was never applied".
    These columns were never in a migration at all — they were invented in
    application code, which is the opposite direction.

HOW THIS PINS IT
    A database double that behaves like PostgREST: it knows the real column
    list (taken from production's information_schema) and RAISES on any column
    outside it, exactly as 42703 does. The production code is then run against
    it unchanged. A phantom column cannot pass this test quietly the way it
    passed in production, because there is no `except` between the double and
    the assertion.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import routers.health as health


# Real columns, read from production information_schema. If a migration adds
# one, add it here — a double that lags the schema would reject a legitimate
# new query and send someone hunting for a bug that is not there.
REAL_COLUMNS = {
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
    "document_requests": {
        "id", "firm_id", "client_id", "requested_by", "title", "description",
        "is_urgent", "status", "fulfilled_at", "storage_path", "file_name",
        "created_at",
    },
}

FIRM = "firm-1"
CLIENT = "client-1"


class PhantomColumn(Exception):
    """Stands in for PostgREST's 42703, raised at parse time."""


class _Query:
    def __init__(self, db: "SchemaCheckedDB", table: str):
        self.db, self.table = db, table
        self._filters: list[tuple[str, str, object]] = []

    def _check(self, col: str) -> None:
        known = self.db.columns.get(self.table)
        if known is None:
            raise PhantomColumn(f"relation {self.table!r} does not exist")
        if col not in known:
            raise PhantomColumn(f"column {self.table}.{col} does not exist")

    def select(self, expr: str):
        for col in (c.strip() for c in expr.split(",")):
            if col and col != "*":
                self._check(col)
        return self

    def _filter(self, col: str, val, op: str):
        self._check(col)
        self._filters.append((op, col, val))
        return self

    def eq(self, col, val):   return self._filter(col, val, "eq")
    def lt(self, col, val):   return self._filter(col, val, "lt")
    def gt(self, col, val):   return self._filter(col, val, "gt")
    def lte(self, col, val):  return self._filter(col, val, "lte")
    def gte(self, col, val):  return self._filter(col, val, "gte")
    def in_(self, col, val):  return self._filter(col, val, "in")
    def order(self, col, **kw):
        self._check(col)
        return self
    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = list(self.db.rows.get(self.table, []))
        for op, col, val in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif op == "lt":
                rows = [r for r in rows if str(r.get(col) or "") < str(val)]
            elif op == "gt":
                rows = [r for r in rows if str(r.get(col) or "") > str(val)]
            elif op == "in":
                rows = [r for r in rows if r.get(col) in val]
        return type("Result", (), {"data": rows[: getattr(self, "_limit", None)]})()


class SchemaCheckedDB:
    """PostgREST-shaped double that refuses columns the real schema lacks."""

    def __init__(self, rows=None):
        self.columns = REAL_COLUMNS
        self.rows = rows or {}

    def table(self, name: str) -> _Query:
        return _Query(self, name)


def _atp(fy: str, number: int, due: str, paid_paise: int | None) -> dict:
    return {"firm_id": FIRM, "client_id": CLIENT, "financial_year": fy,
            "installment_number": number, "due_date": due,
            "paid_amount_paise": paid_paise, "paid_date": None}


# Derived from today rather than hardcoded: a fixed "past" date stops being
# past, and the first draft of this test used 2026-09-15, which had not yet
# arrived. Relative dates cannot rot that way.
PAST_A = (date.today() - timedelta(days=120)).isoformat()
PAST_B = (date.today() - timedelta(days=30)).isoformat()


# ── The queries must use real columns at all ─────────────────────────────────

def test_advance_tax_override_does_not_ask_for_phantom_columns():
    """Against the previous code this raises PhantomColumn on `paid` /
    `instalment_number` — which in production was swallowed by `except`."""
    db = SchemaCheckedDB({"advance_tax_payments": [
        _atp("2026-27", 1, PAST_A, 0), _atp("2026-27", 2, PAST_B, 0)]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) == "advance_tax_2_consecutive"


def test_ai_insight_override_does_not_ask_for_phantom_columns():
    old = (date.today() - timedelta(days=30)).isoformat()
    db = SchemaCheckedDB({"ai_insights": [
        {"id": "i1", "firm_id": FIRM, "client_id": CLIENT,
         "severity": "critical", "status": "open", "created_at": old}]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) == "critical_ai_insight_14d"


def test_ai_risk_dimension_does_not_ask_for_phantom_columns():
    """This dimension scored a flat 100 for every client because both of its
    queries raised and both except branches left the score alone."""
    db = SchemaCheckedDB({"ai_insights": [
        {"id": "a", "firm_id": FIRM, "client_id": CLIENT, "severity": "critical", "status": "open"},
        {"id": "b", "firm_id": FIRM, "client_id": CLIENT, "severity": health._WARNING_SEVERITY, "status": "open"},
    ]})
    assert health._dim_ai_risk_signals_db(db, CLIENT, FIRM) == 70  # 100 - 20 - 10


# ── The semantics, not just the column names ─────────────────────────────────

def test_only_unpaid_and_overdue_instalments_count_as_missed():
    """A paid instalment is not missed; a future one is not yet missable."""
    future = (date.today() + timedelta(days=90)).isoformat()
    db = SchemaCheckedDB({"advance_tax_payments": [
        _atp("2026-27", 1, PAST_A, 5000000),   # paid
        _atp("2026-27", 2, PAST_B, 0),         # missed
        _atp("2026-27", 3, future, 0),         # not due yet
    ]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) is None


def test_misses_in_two_different_years_are_not_consecutive():
    """Instalment numbers restart at 1 every financial year. Pooling them read
    FY25-26 #1 and FY26-27 #2 as a consecutive pair and flagged a client who
    missed a single instalment in each of two separate years."""
    db = SchemaCheckedDB({"advance_tax_payments": [
        _atp("2025-26", 1, (date.today() - timedelta(days=400)).isoformat(), 0),
        _atp("2026-27", 2, PAST_B, 0),
    ]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) is None


def test_two_consecutive_misses_within_one_year_do_fire():
    db = SchemaCheckedDB({"advance_tax_payments": [
        _atp("2026-27", 2, PAST_A, 0),
        _atp("2026-27", 3, PAST_B, None),   # NULL, not 0
    ]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) == "advance_tax_2_consecutive"


def test_non_consecutive_misses_in_one_year_do_not_fire():
    db = SchemaCheckedDB({"advance_tax_payments": [
        _atp("2026-27", 1, PAST_A, 0),
        _atp("2026-27", 3, PAST_B, 0),
    ]})
    assert health._detect_hard_override_db(db, CLIENT, FIRM) is None


# ── The literals the CHECK constraints actually permit ───────────────────────

def test_warning_severity_is_one_the_check_constraint_permits():
    """ai_insights.severity CHECK is (critical|high|medium|low|info). The code
    filtered on 'warning', which no row can hold, so the -10 branch matched
    nothing even once the column name was fixed."""
    assert health._WARNING_SEVERITY in {"critical", "high", "medium", "low", "info"}
    assert health._WARNING_SEVERITY != "critical", "the -10 tier must not double-count criticals"


def test_document_request_factors_use_title_and_lowercase_status():
    db = SchemaCheckedDB({"document_requests": [
        {"id": "d1", "firm_id": FIRM, "client_id": CLIENT,
         "title": "Bank statement April", "status": "pending", "created_at": "2026-08-01"}]})
    factors = health._dimension_detail_db(db, CLIENT, FIRM, "document_health")
    assert any("Bank statement April" in f["label"] for f in factors), (
        "the request did not come back — either the column is wrong or the "
        "status filter is the wrong case"
    )


def test_a_fulfilled_request_is_not_outstanding():
    db = SchemaCheckedDB({"document_requests": [
        {"id": "d1", "firm_id": FIRM, "client_id": CLIENT,
         "title": "Already provided", "status": "fulfilled", "created_at": "2026-08-01"}]})
    assert health._dimension_detail_db(db, CLIENT, FIRM, "document_health") == []


# ── Vacuity guard ────────────────────────────────────────────────────────────

def test_the_double_actually_rejects_a_phantom_column():
    """If the double stopped checking, every test above would pass while
    asserting nothing about column names."""
    db = SchemaCheckedDB({"ai_insights": []})
    with pytest.raises(PhantomColumn):
        db.table("ai_insights").select("id").eq("acknowledged", False).execute()
