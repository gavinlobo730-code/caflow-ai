"""
Migration 416 — the SQL worklist must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    `public.hub_client_worklist` aggregates where the rows already are: the
    answer is one line per CLIENT and the input is one row per statement line,
    per bill, per asset, per engagement, for years — so CLAUDE.md's reporting
    rule puts the GROUP BY in the database.
    `services/hub_worklist_service._python_twin` has to survive anyway, because
    mock mode, local dev and the in-memory suite have no SQL functions at all,
    which creates the thing CLAUDE.md warns about: two implementations of one
    rule, which drift.

    They are safe only while something proves they agree. Every scenario below
    is declared ONCE and fed to both halves — Postgres over real rows, and the
    twin over `tests/_hub_worklist_double`, the same double the mock suite
    uses.

WHAT ONLY POSTGRES CAN PROVE
      * `purchase_bills.outstanding_paise` is a GENERATED column (migration
        278), so the twin's `> 0` filter and the SQL's `SUM` are both reading
        an expression no fixture can fake. A scenario here sets the PARTS —
        net payable, credit notes, paid, debited — and lets the database
        derive it, which is the only way to find out that the two halves agree
        about a bill settled by a credit note rather than by cash.
      * `SUM(...)::bigint` over an empty group and `COUNT(*)` over one are SQL
        semantics, not Python ones.
      * the function is SECURITY DEFINER with the firm check restated in its
        body (migration 279's lesson), and that can only be exercised against
        a real `authenticated` caller.
      * a tile with no worklist RAISES rather than answering an empty set, and
        an exception is not something a Python double can stand in for.
"""
from __future__ import annotations

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

from services import hub_worklist_service  # noqa: E402
from tests._hub_worklist_double import Double  # noqa: E402

FIRM = "f4160000-0000-0000-0000-000000000001"
OTHER_FIRM = "f4160000-0000-0000-0000-0000000000ff"
A = "c4160000-0000-0000-0000-00000000000a"
B = "c4160000-0000-0000-0000-00000000000b"
C = "c4160000-0000-0000-0000-00000000000c"
USER = "e4160000-0000-0000-0000-000000000001"
VENDOR = "74160000-0000-0000-0000-000000000001"
STMT = "54160000-0000-0000-0000-000000000001"
ACCT = "b4160000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


# ── One declaration, two consumers ──────────────────────────────────────────
#
# Each scenario is a list of plain dicts. `_seed` turns them into INSERTs and
# `_double` hands the SAME dicts to the twin, so nothing can agree by being
# written twice.

# ⚠️ `entry_state` IS TRIGGER-MAINTAINED (migration 322) AND CANNOT BE SEEDED.
# The first draft of this file set it directly, the BEFORE trigger recomputed
# every row from its own fields, and the two halves disagreed — the SQL saw
# what the trigger decided and the twin saw what the fixture claimed. So each
# row declares the DRIVERS instead (`domain/banking/entry.entry_state`'s own
# branches: match_status posted → passed, draft_grade → ready / proposed,
# nothing → needs_you) and the double is built by READING THE ROWS BACK, which
# is what makes this a parity test rather than two fixtures agreeing.
#
# `draft_source` travels with `draft_grade` because migration 322 CHECKs them
# as a pair — a grade with no source is refused, which is the constraint
# saying a draft has to come from somewhere.
BANK = [
    {"id": "14160000-0000-0000-0000-000000000001", "firm_id": FIRM, "client_id": A,
     "drivers": {}},                                            # → needs_you
    {"id": "14160000-0000-0000-0000-000000000002", "firm_id": FIRM, "client_id": A,
     "drivers": {"draft_source": "rule", "draft_grade": "ready"}},   # → ready
    {"id": "14160000-0000-0000-0000-000000000003", "firm_id": FIRM, "client_id": A,
     "drivers": {"draft_source": "rule", "draft_grade": "proposed"}},  # → proposed
    {"id": "14160000-0000-0000-0000-000000000004", "firm_id": FIRM, "client_id": B,
     "drivers": {"draft_source": "rule", "draft_grade": "ready"}},   # → ready
    # Posted: done, and the one state that must NOT be counted.
    {"id": "14160000-0000-0000-0000-000000000005", "firm_id": FIRM, "client_id": B,
     "drivers": {"match_status": "posted"}},                     # → passed
    # Client C has nothing open — it must produce NO ROW, not a zero.
    {"id": "14160000-0000-0000-0000-000000000006", "firm_id": FIRM, "client_id": C,
     "drivers": {"match_status": "posted"}},                     # → passed
    # Another firm entirely.
    {"id": "14160000-0000-0000-0000-000000000007", "firm_id": OTHER_FIRM, "client_id": A,
     "drivers": {}},                                             # → needs_you
]

# The parts, not the total: `outstanding_paise` is GENERATED and the database
# derives it. The second bill is settled by a CREDIT NOTE rather than by cash,
# which is the case a hand-written `total - paid` would get wrong (migration
# 210 made the note columns' signs differ between the two tables).
BILLS = [
    {"id": "24160000-0000-0000-0000-000000000001", "firm_id": FIRM, "client_id": A,
     "net_payable_paise": 118000, "credit_note_paise": 0, "paid_paise": 0,
     "debited_paise": 0},
    {"id": "24160000-0000-0000-0000-000000000002", "firm_id": FIRM, "client_id": A,
     "net_payable_paise": 100000, "credit_note_paise": 0, "paid_paise": 40000,
     "debited_paise": 0},
    # Fully settled by a debit note: outstanding is nil, so no row for B.
    {"id": "24160000-0000-0000-0000-000000000003", "firm_id": FIRM, "client_id": B,
     "net_payable_paise": 50000, "credit_note_paise": 0, "paid_paise": 0,
     "debited_paise": 50000},
]

ASSETS = [
    {"id": "34160000-0000-0000-0000-000000000001", "firm_id": FIRM, "client_id": B,
     "depreciation_posted_through": None},
    {"id": "34160000-0000-0000-0000-000000000002", "firm_id": FIRM, "client_id": B,
     "depreciation_posted_through": None},
    {"id": "34160000-0000-0000-0000-000000000003", "firm_id": FIRM, "client_id": B,
     "depreciation_posted_through": "2026-03-31"},
    {"id": "34160000-0000-0000-0000-000000000004", "firm_id": OTHER_FIRM, "client_id": A,
     "depreciation_posted_through": None},
]

# ⚠️ ONE ENGAGEMENT PER (firm, client, FINANCIAL YEAR) — migration 319's unique
# key. A client with three open engagements therefore has three YEARS open,
# which is the real shape anyway: a practice carrying a client's 2023-24
# finalisation into September is exactly what this queue is for.
ENGAGEMENTS = [
    {"id": "44160000-0000-0000-0000-000000000001", "firm_id": FIRM, "client_id": A,
     "fy": "2025-26", "status": "draft"},
    {"id": "44160000-0000-0000-0000-000000000002", "firm_id": FIRM, "client_id": C,
     "fy": "2023-24", "status": "in_review"},
    {"id": "44160000-0000-0000-0000-000000000003", "firm_id": FIRM, "client_id": C,
     "fy": "2024-25", "status": "approved"},
    {"id": "44160000-0000-0000-0000-000000000004", "firm_id": FIRM, "client_id": C,
     "fy": "2025-26", "status": "locked"},
]


def _seed_sql() -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES
  ('{FIRM}', 'Worklist Parity', 'a@parity.in'),
  ('{OTHER_FIRM}', 'Someone Else', 'b@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{A}', '{FIRM}', 'Acme', 'LLP'),
  ('{B}', '{FIRM}', 'Bharat', 'Private Limited'),
  ('{C}', '{FIRM}', 'Chandra', 'Partnership');
INSERT INTO users (id, firm_id, email, full_name, role)
  VALUES ('{USER}', '{FIRM}', 'p@parity.in', 'Partner', 'Partner');
INSERT INTO vendors (id, firm_id, client_id, name)
  VALUES ('{VENDOR}', '{FIRM}', '{A}', 'A Supplier');
INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no)
  VALUES ('{ACCT}', '{FIRM}', '{A}', 'Cosmos', '000111222');
INSERT INTO bank_statements
  (id, firm_id, client_id, bank_account_id, bank_name, statement_from, statement_to)
  VALUES ('{STMT}', '{FIRM}', '{A}', '{ACCT}', 'Cosmos',
          DATE '2026-06-01', DATE '2026-06-30');
"""]
    for r in BANK:
        cols = ", ".join(r["drivers"])
        vals = ", ".join(f"'{v}'" for v in r["drivers"].values())
        extra_c = f", {cols}" if cols else ""
        extra_v = f", {vals}" if vals else ""
        out.append(f"""
INSERT INTO bank_transactions
  (id, firm_id, client_id, statement_id, transaction_date, description{extra_c})
VALUES ('{r["id"]}', '{r["firm_id"]}', '{r["client_id"]}', '{STMT}',
        DATE '2026-06-01', 'line'{extra_v});""")
    for r in BILLS:
        out.append(f"""
INSERT INTO purchase_bills
  (id, firm_id, client_id, vendor_id, bill_date,
   net_payable_paise, credit_note_paise, paid_paise, debited_paise)
VALUES ('{r["id"]}', '{r["firm_id"]}', '{r["client_id"]}', '{VENDOR}', DATE '2026-05-01',
        {r["net_payable_paise"]}, {r["credit_note_paise"]},
        {r["paid_paise"]}, {r["debited_paise"]});""")
    for r in ASSETS:
        through = "NULL" if r["depreciation_posted_through"] is None \
            else f"DATE '{r['depreciation_posted_through']}'"
        out.append(f"""
INSERT INTO fixed_assets
  (id, firm_id, client_id, asset_name, asset_category, purchase_date,
   purchase_cost_paise, depreciation_posted_through)
VALUES ('{r["id"]}', '{r["firm_id"]}', '{r["client_id"]}', 'Plant', 'Plant and Machinery',
        DATE '2025-04-01', 100000, {through});""")
    for r in ENGAGEMENTS:
        out.append(f"""
INSERT INTO year_end_engagements
  (id, firm_id, client_id, created_by, financial_year, fy_start, fy_end, status)
VALUES ('{r["id"]}', '{r["firm_id"]}', '{r["client_id"]}', '{USER}', '{r["fy"]}',
        DATE '2025-04-01', DATE '2026-03-31', '{r["status"]}');""")
    return "\n".join(out)


#: What the twin is fed, read back OUT OF POSTGRES rather than restated here.
#: Two columns make that necessary and both would otherwise be silent: the
#: trigger-maintained `bank_transactions.entry_state` (migration 322) and the
#: GENERATED `purchase_bills.outstanding_paise` (migration 278). Restating
#: either is a second fixture, and two fixtures can agree with each other while
#: both disagree with the database.
_READ_BACK = {
    "bank_transactions": "id, firm_id, client_id, entry_state",
    "purchase_bills": "id, firm_id, client_id, outstanding_paise",
    "fixed_assets": "id, firm_id, client_id, depreciation_posted_through",
    "year_end_engagements": "id, firm_id, client_id, status",
    "clients": "id, firm_id, client_name, legal_name, entity_type",
}


def _double(dsn: str) -> Double:
    tables: dict[str, list[dict]] = {}
    for table, cols in _READ_BACK.items():
        names = [c.strip() for c in cols.split(",")]
        r = _psql(dsn, f"SELECT {cols} FROM public.{table} ORDER BY id;", tuples=True)
        assert r.returncode == 0, f"read-back of {table} failed: {r.stderr}"
        rows = []
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            row = {}
            for k, v in zip(names, parts):
                if v == "":
                    row[k] = None
                elif k.endswith("_paise"):
                    row[k] = int(v)
                else:
                    row[k] = v
            rows.append(row)
        tables[table] = rows
    return Double(tables)


@pytest.fixture(scope="module")
def db(pg_template):
    """⚠️ MODULE-SCOPED, AND THAT IS A COST DECISION AS WELL AS A CORRECT ONE.

    Every test here is READ-ONLY — it calls the function, reads the rows back
    and compares — so there is no state for one to leak into the next, and a
    per-test fixture would clone the migrated template FOURTEEN TIMES for one
    seed. On a CI runner a clone of a 416-migration template is not free, and
    the real-Postgres job is already the long pole of the backend workflow.
    One clone, one seed, fourteen assertions.

    If a test here ever WRITES, it takes its own function-scoped database
    rather than quietly making this one dirty for the thirteen after it.
    """
    admin = _ADMIN.strip()
    name = f"hubwl_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    seeded = _psql(dsn, _seed_sql())
    assert seeded.returncode == 0, f"seed failed: {seeded.stderr}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql(dsn: str, tile: str, firm: str = FIRM,
         clients: list[str] | None = None) -> list[tuple[str, int]]:
    arg = ("NULL::uuid[]" if clients is None
           else "ARRAY[" + ",".join(f"'{c}'::uuid" for c in clients) + "]")
    r = _psql(dsn, f"""
        SELECT client_id::text || '|' || signal::text
          FROM public.hub_client_worklist('{firm}'::uuid, '{tile}', {arg})
         ORDER BY signal DESC, client_id;
    """, tuples=True)
    assert r.returncode == 0, f"hub_client_worklist({tile}) failed: {r.stderr}"
    return [(ln.split("|")[0], int(ln.split("|")[1]))
            for ln in r.stdout.strip().splitlines() if ln.strip()]


def _twin(dsn, monkeypatch, tile: str, firm: str = FIRM,
          clients: list[str] | None = None) -> list[tuple[str, int]]:
    d = _double(dsn)
    monkeypatch.setattr(hub_worklist_service, "_db", lambda: d)
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids",
                        lambda u: None if clients is None else set(clients))
    out = hub_worklist_service.worklist({"firm_id": firm}, tile)
    return sorted(((r["client_id"], r["signal"]) for r in out["rows"]),
                  key=lambda t: (-t[1], t[0]))


@pytest.mark.parametrize("tile", ["banking", "purchases", "fixed_assets", "year_end"])
def test_the_sql_and_the_python_twin_agree(db, monkeypatch, tile):
    assert _sql(db, tile) == _twin(db, monkeypatch, tile), (
        f"{tile}: migration 416 and hub_worklist_service._python_twin disagree")


@pytest.mark.parametrize("tile", ["banking", "purchases", "fixed_assets", "year_end"])
def test_they_agree_when_the_caller_is_assignment_scoped(db, monkeypatch, tile):
    """An Executive's own book. `p_client_ids` is the whole scope mechanism and
    a filter applied in one half only is a cross-client read in the other."""
    assert _sql(db, tile, clients=[B, C]) == _twin(db, monkeypatch, tile, clients=[B, C])


def test_a_client_with_nothing_outstanding_produces_no_row(db):
    """A queue is work, not a position — the opposite of
    `stock_position_as_at`'s rule and deliberately so. `C` has a passed bank
    line and nothing else, so it must not appear with a zero."""
    assert C not in {cid for cid, _ in _sql(db, "banking")}
    # And it DOES appear where it has work, so its absence above means
    # something.
    assert C in {cid for cid, _ in _sql(db, "year_end")}


def test_the_generated_outstanding_column_is_what_is_summed(db, monkeypatch):
    """Bill 2 is part-paid and bill 3 is fully settled by a DEBIT NOTE. A
    `total - paid` reading would put 50,000 against B; migration 278's
    expression puts nil, and both halves have to take the column."""
    rows = dict(_sql(db, "purchases"))
    assert rows == {A: 178000}
    assert dict(_twin(db, monkeypatch, "purchases")) == rows


def test_another_firms_rows_are_never_counted(db):
    """The app-layer firm filter is the primary isolation control — the service
    key bypasses RLS — so the function must carry it in every branch."""
    assert _sql(db, "banking", firm=OTHER_FIRM) == [(A, 1)]
    assert _sql(db, "fixed_assets", firm=OTHER_FIRM) == [(A, 1)]


def test_an_empty_scope_means_nothing_not_everything(db):
    """`p_client_ids = '{}'` must match no client. The Python side short-circuits
    before the query; this proves the SQL would agree if it did not."""
    r = _psql(db, f"""
        SELECT count(*) FROM public.hub_client_worklist(
            '{FIRM}'::uuid, 'banking', ARRAY[]::uuid[]);
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0"


def test_a_tile_with_no_worklist_raises_rather_than_answering_empty(db):
    """A nil meaning *no client needs work* and a nil meaning *this tile has no
    worklist* are different facts."""
    r = _psql(db, f"SELECT * FROM public.hub_client_worklist('{FIRM}'::uuid, 'inventory');")
    assert r.returncode != 0
    assert "has no firm-level worklist" in (r.stderr or "")


def test_the_function_is_granted_to_the_two_roles_and_no_others(db):
    r = _psql(db, """
        SELECT has_function_privilege('authenticated',
                 'public.hub_client_worklist(uuid, text, uuid[])', 'EXECUTE')::text
            || ',' ||
               has_function_privilege('anon',
                 'public.hub_client_worklist(uuid, text, uuid[])', 'EXECUTE')::text;
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true,false"
