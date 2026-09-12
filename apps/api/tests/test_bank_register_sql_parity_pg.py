"""
Migration 353 — the SQL bank register must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    Moving the running balance into the database is what makes the Bank Book
    fast: every transaction on the account over the wire became one call. It
    also creates the thing CLAUDE.md warns about — two implementations of a
    rule, which drift.

    They are safe only while something proves they agree. That is this file.
    domain/banking/register.py stays as the no-database fallback for mock mode
    and local dev; public.bank_register is what production runs; and every
    scenario below goes through BOTH and is compared key for key.

WHY A REAL DATABASE
    The SQL half cannot be exercised any other way. A double can prove the
    function was called; only Postgres can prove what it computes.

WHAT IS COMPARED
    The whole answer, not a summary: the page of lines, the summary block, the
    first divergence, the view opening balance and both counts — across every
    sort, every direction, every status filter, three date ranges, four search
    needles and three paging windows.

FOUR PLACES THE TWO SIDES COULD DIVERGE, EACH WITH A SCENARIO
    1. ORDER. The register order is (date, created_at, id) and the DISPLAY
       order for sort="date" is (date, id) — created_at is dropped. Two rows
       share a date here, with created_at in the opposite order to their ids,
       so a side that used the wrong key produces a different page.
    2. COLLATION. Python compares strings by code point; a database collation
       does not. The descriptions below mix case and punctuation on purpose.
    3. THE OPENING BALANCE. A row dated before opening_balance_date is already
       inside that figure, so it must not be added again. One row is.
    4. THE SEARCH HAYSTACK. It is joined with a literal space per field and a
       NULL becomes ''. One row has a NULL reference and a NULL category, and
       one needle is a double space, which concat_ws would have collapsed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.banking.register import (  # noqa: E402
    build_register, first_divergence, summarise,
)
from services.bank_register_service import BankRegisterService  # noqa: E402

FIRM = "f8000000-0000-0000-0000-000000000001"
CLIENT = "c8000000-0000-0000-0000-000000000001"
ACCOUNT = "b8000000-0000-0000-0000-000000000001"
STMT = "58000000-0000-0000-0000-000000000001"
RECON_DONE = "a8000000-0000-0000-0000-000000000001"
RECON_OPEN = "a8000000-0000-0000-0000-000000000002"
OPENING_PAISE = 5_000_000
OPENING_DATE = "2026-04-01"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1"]
    cmd += ["-tAc", sql] if tuples else ["-c", sql]
    return subprocess.run(cmd, capture_output=True, text=True)


# (id_suffix, date, created_at, description, debit, credit, stated_balance,
#  reference, category, needs_review, posted_journal, reconciliation)
ROWS = [
    # (3) Dated BEFORE the opening balance: already inside that figure.
    ("01", "2026-03-15", "2026-03-15 10:00+00", "Opening era rent",
     100_000, 0, None, "REF-A", "Expense", False, None, None),
    ("02", "2026-04-02", "2026-04-02 10:00+00", "NEFT from ZENITH SYSTEMS",
     0, 2_500_000, 7_500_000, "REF-B", "Sales Receipt", False,
     "e8000000-0000-0000-0000-000000000001", RECON_DONE),
    # (1) Same date as "04" but created LATER, and its id sorts EARLIER.
    ("04", "2026-04-10", "2026-04-10 09:00+00", "Cheque 4411 SALARY",
     1_200_000, 0, 6_300_000, None, "Salary", True, None, RECON_OPEN),
    # (4) NULL reference AND NULL category — the haystack keeps both spaces.
    ("03", "2026-04-10", "2026-04-10 11:00+00", "UPI  kaveri@okhdfc",
     0, 45_000, 6_345_000, None, None, False, None, None),
    # (2) Case and punctuation that a database collation orders differently.
    ("05", "2026-05-04", "2026-05-04 10:00+00", "atm wdl",
     200_000, 0, 6_145_000, None, None, False, None, None),
    # A statement line that carried NO balance column. It is skipped by the
    # divergence check rather than treated as a disagreement with zero.
    ("06", "2026-05-04", "2026-05-04 12:00+00", "ATM-WDL",
     50_000, 0, None, "REF-F", None, False, None, None),
    # The bank's stated balance is wrong from here: the first divergence, and
    # the only one, because nothing below it is checked once it is found.
    ("07", "2026-06-01", "2026-06-01 10:00+00", "Bank charges",
     5_900, 0, 5_900_000, None, "Other", False, None, None),
]


def _seed_sql() -> str:
    parts = [
        f"""
        INSERT INTO firms (id, name, email)
          VALUES ('{FIRM}', 'Parity Firm', 'parity@test.local');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'Parity Client', 'Private Limited');
        INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no,
                                   opening_balance_paise, opening_balance_date)
          VALUES ('{ACCOUNT}', '{FIRM}', '{CLIENT}', 'HDFC', '000111',
                  {OPENING_PAISE}, '{OPENING_DATE}');
        INSERT INTO bank_statements (id, firm_id, client_id, bank_name,
                                     bank_account_id, statement_from, statement_to)
          VALUES ('{STMT}', '{FIRM}', '{CLIENT}', 'HDFC', '{ACCOUNT}',
                  '2026-03-01', '2026-06-30');
        INSERT INTO bank_reconciliations (id, firm_id, client_id, bank_account_id,
                                          period_start, period_end, status)
          VALUES ('{RECON_DONE}', '{FIRM}', '{CLIENT}', '{ACCOUNT}',
                  '2026-04-01', '2026-04-30', 'completed'),
                 ('{RECON_OPEN}', '{FIRM}', '{CLIENT}', '{ACCOUNT}',
                  '2026-05-01', '2026-05-31', 'in_progress');
        """
    ]
    for (sfx, d, created, desc, dr, cr, bal, ref, cat, review,
         posted, recon) in ROWS:
        def q(v):
            return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"
        parts.append(f"""
        INSERT INTO bank_transactions
          (id, statement_id, firm_id, client_id, transaction_date, description,
           debit_paise, credit_paise, balance_paise, reference_no, category,
           needs_review, posted_journal_id, reconciliation_id, created_at)
          VALUES ('d8000000-0000-0000-0000-0000000000{sfx}', '{STMT}', '{FIRM}',
                  '{CLIENT}', '{d}', {q(desc)}, {dr}, {cr},
                  {'NULL' if bal is None else bal}, {q(ref)}, {q(cat)},
                  {str(review).lower()}, {q(posted)}, {q(recon)}, '{created}');
        """)
    return "\n".join(parts)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"brpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, _seed_sql())
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── The two sides ────────────────────────────────────────────────────────────

_TXN_COLS = ("t.id, t.transaction_date, t.description, t.debit_paise, "
             "t.credit_paise, t.balance_paise, t.reference_no, t.category, "
             "t.match_status, t.needs_review, t.posted_journal_id, "
             "t.reconciliation_id, t.created_at")


def _python_register(dsn: str, **kw) -> dict:
    """The Python twin, over the rows exactly as the service assembles them."""
    r = _psql(dsn, f"SELECT COALESCE(json_agg(row_to_json(x)), '[]') FROM "
                   f"(SELECT {_TXN_COLS} FROM bank_transactions t "
                   f"JOIN bank_statements s ON s.id = t.statement_id "
                   f"WHERE s.bank_account_id = '{ACCOUNT}') AS x;", tuples=True)
    assert r.returncode == 0, r.stderr
    txns = json.loads(r.stdout.strip())
    r = _psql(dsn, "SELECT COALESCE(json_agg(row_to_json(y)), '[]') FROM "
                   "(SELECT id, status FROM bank_reconciliations) y;", tuples=True)
    statuses = {x["id"]: x["status"] for x in json.loads(r.stdout.strip())}

    svc = BankRegisterService()
    all_lines = build_register(txns, opening_balance_paise=OPENING_PAISE,
                               opening_balance_date=OPENING_DATE,
                               reconciliation_statuses=statuses)
    # No underlying-row argument: `_matches` reads the RegisterLine and nothing
    # else since the needs_review filter went (that predicate was the only one
    # needing a column the line does not carry). This mirror has to call it the
    # way the service does, or the parity it proves is against a signature that
    # no longer exists.
    filtered = [l for l in all_lines if svc._matches(
        l, date_from=kw.get("date_from"), date_to=kw.get("date_to"),
        status=kw.get("status", "all"), q=kw.get("q"))]
    ordered = svc._sort(filtered, kw.get("sort", "date"), kw.get("desc", False))
    limit, offset = kw.get("limit", 200), kw.get("offset", 0)
    view_opening = OPENING_PAISE
    if filtered:
        idx = all_lines.index(filtered[0])
        view_opening = all_lines[idx - 1].balance_paise if idx > 0 else OPENING_PAISE
    return {
        "lines": [svc._line_out(l) for l in ordered[offset:offset + limit]],
        "summary": summarise(all_lines, opening_balance_paise=OPENING_PAISE),
        "divergence": first_divergence(all_lines),
        "view_opening_balance_paise": view_opening,
        "filtered_count": len(filtered),
        "total_count": len(all_lines),
    }


def _sql_register(dsn: str, **kw) -> dict:
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    args = ", ".join([
        f"'{FIRM}'::uuid", f"'{ACCOUNT}'::uuid",
        f"{lit(kw.get('date_from'))}::date", f"{lit(kw.get('date_to'))}::date",
        lit(kw.get("status", "all")), lit(kw.get("q")),
        lit(kw.get("sort", "date")), lit(kw.get("desc", False)),
        lit(kw.get("limit", 200)), lit(kw.get("offset", 0)),
    ])
    r = _psql(dsn, f"SELECT public.bank_register({args});", tuples=True)
    assert r.returncode == 0, f"bank_register failed: {r.stderr}"
    return json.loads(r.stdout.strip())


# ── The parity proof ─────────────────────────────────────────────────────────

SCENARIOS: list[tuple[str, dict]] = (
    [(f"sort {s} {'desc' if d else 'asc'}", {"sort": s, "desc": d})
     for s in ("date", "amount", "description", "balance", "cleared")
     for d in (False, True)]
    # "needs_review" was here. It is no longer a filter the product offers —
    # nothing ever set the flag, so the tab always answered zero — and the
    # Python predicate is gone, so there is nothing left to hold in parity.
    # migration 353's SQL branch survives, unreachable, for the exception
    # service that would write the flag; see services/bank_register_service.py.
    + [(f"status {s}", {"status": s})
       for s in ("all", "uncleared", "pending", "reconciled", "unposted")]
    + [
        ("from April", {"date_from": "2026-04-01"}),
        ("to April", {"date_to": "2026-04-30"}),
        ("April to May", {"date_from": "2026-04-01", "date_to": "2026-05-31"}),
        # The needle is a DOUBLE space: it exists only because the haystack
        # keeps one space per field and the description itself has two.
        ("search a double space", {"q": "UPI  kaveri"}),
        ("search case-insensitive", {"q": "salary"}),
        ("search a reference", {"q": "REF-"}),
        ("search nothing", {"q": "no such narration"}),
        ("first page of two", {"limit": 2}),
        ("second page of two", {"limit": 2, "offset": 2}),
        ("offset past the end", {"limit": 3, "offset": 50}),
        ("reconciled by amount desc",
         {"status": "reconciled", "sort": "amount", "desc": True}),
        ("May onwards by balance", {"date_from": "2026-05-01", "sort": "balance"}),
    ]
)


@pytest.mark.parametrize("name,kw", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_sql_matches_python(db, name, kw):
    sql = _sql_register(db, **kw)
    py = _python_register(db, **kw)
    for key in ("lines", "summary", "divergence", "view_opening_balance_paise",
                "filtered_count", "total_count"):
        assert sql[key] == json.loads(json.dumps(py[key])), (
            f"SQL and Python disagree on '{name}' → {key}.\n"
            f"  SQL:    {json.dumps(sql[key], indent=2, sort_keys=True)}\n"
            f"  Python: {json.dumps(py[key], indent=2, sort_keys=True, default=str)}"
        )


def test_the_comparison_can_actually_fail(db):
    """A parity test that cannot fail proves nothing.

    Two DIFFERENT requests must produce different answers; if they did not,
    every assertion above would be comparing one thing to itself.
    """
    a = _sql_register(db, sort="amount")
    b = _sql_register(db, sort="amount", desc=True)
    assert a["lines"] != b["lines"]


def test_a_row_before_the_opening_balance_is_not_added_twice(db):
    """It is already inside opening_balance_paise. Adding it double-counts by
    exactly its own amount, silently."""
    out = _sql_register(db)
    pre = [l for l in out["lines"] if l["precedes_opening"]]
    assert len(pre) == 1
    # Its balance is the opening figure unchanged, not opening - 100000.
    assert pre[0]["balance_paise"] == OPENING_PAISE
    assert out["summary"]["precedes_opening_count"] == 1
    # And it is outside the deposit/withdrawal totals.
    assert out["summary"]["withdrawals_paise"] == 1_200_000 + 200_000 + 50_000 + 5_900


def test_only_the_first_divergence_is_reported(db):
    """Once a line is missing every balance below it is wrong by the same
    amount, so listing them all reports one fault many times."""
    out = _sql_register(db)
    d = out["divergence"]
    assert d is not None
    assert d["description"] == "Bank charges"
    assert d["delta_paise"] == d["statement_balance_paise"] - d["computed_balance_paise"]
    # Every earlier line agrees, and the one carrying no stated balance has no
    # delta rather than a fabricated zero.
    by_desc = {l["description"]: l for l in out["lines"]}
    assert by_desc["atm wdl"]["balance_delta_paise"] == 0
    assert by_desc["ATM-WDL"]["balance_delta_paise"] is None


def test_the_view_opening_balance_makes_a_filtered_page_add_up(db):
    """The balance immediately BEFORE the first row shown. Without it the first
    visible balance looks like it came from nowhere."""
    out = _sql_register(db, date_from="2026-05-01")
    first = out["lines"][0]
    assert (out["view_opening_balance_paise"]
            + first["credit_paise"] - first["debit_paise"]) == first["balance_paise"]
