"""Migration 392 — the four pre-invoice documents, on real PostgreSQL (SALES-21).

WHY THIS NEEDS A REAL DATABASE. Five of the design decisions are CONSTRAINTS
rather than code, and none of them is observable in mock mode, where the
in-memory double accepts anything:

  * `goods_kind` nullable with NO default, and CHECKed to CGST s.143's three
    answers — the third state that makes a job-work clock refusable;
  * two CHECKs that keep a kind of goods and a Commissioner's extension on a
    JOB-WORK movement only, because s.143 reaches no other;
  * Rule 55(1)'s sixteen characters, and Rule 46(b)'s on the two documents
    that become an invoice;
  * uniqueness per client PER KIND for the quotations, so a quotation and a
    proforma may share a number and two quotations may not;
  * the grant model — these six tables are READ from the browser and written
    only through `rbac()`.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CUSTOMER = "33333333-3333-3333-3333-333333333333"

TABLES = ("sales_quotations", "sales_quotation_lines", "sales_orders",
          "sales_order_lines", "delivery_challans", "delivery_challan_lines")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"salescycle_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn,
             f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO customers (id, firm_id, client_id, name)
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Buyer Ltd');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _quote(dsn, *, kind="quotation", no="QT/1", date="2026-04-01"):
    return _psql(dsn, f"""
        INSERT INTO sales_quotations
          (firm_id, client_id, customer_id, kind, document_no, document_date)
        VALUES ('{FIRM}', '{CLIENT}', '{CUSTOMER}', '{kind}', '{no}', DATE '{date}');
    """)


def _order(dsn, *, no="SO/1", date="2026-04-01"):
    return _psql(dsn, f"""
        INSERT INTO sales_orders
          (firm_id, client_id, customer_id, document_no, document_date)
        VALUES ('{FIRM}', '{CLIENT}', '{CUSTOMER}', '{no}', DATE '{date}');
    """)


def _challan(dsn, *, no="DC/1", reason="job_work", goods_kind="NULL",
             extended="NULL", date="2026-04-01", status="draft"):
    return _psql(dsn, f"""
        INSERT INTO delivery_challans
          (firm_id, client_id, document_no, document_date, reason, status,
           goods_kind, extended_to)
        VALUES ('{FIRM}', '{CLIENT}', '{no}', DATE '{date}', '{reason}',
                '{status}', {goods_kind}, {extended});
    """)


# ── the tables exist and carry what the domain modules expect ───────────────

@pytest.mark.parametrize("table", TABLES)
def test_the_table_exists(db, table):
    assert _rows(db, f"SELECT to_regclass('public.{table}');") == [f"{table}"]


@pytest.mark.parametrize("table", TABLES)
def test_row_level_security_is_on(db, table):
    assert _rows(db,
        f"SELECT relrowsecurity FROM pg_class "
        f"WHERE oid = 'public.{table}'::regclass;") == ["t"]


@pytest.mark.parametrize("table", TABLES)
def test_the_browser_may_read_and_may_not_write(db, table):
    """These six are read straight from the browser. A write must go through
    `rbac()`, which only the service role reaches."""
    granted = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{table}'
           AND grantee = 'authenticated';"""))
    assert granted == {"SELECT"}, granted
    service = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{table}'
           AND grantee = 'service_role';"""))
    assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= service


@pytest.mark.parametrize("table", TABLES)
def test_the_table_is_assignment_scoped(db, table):
    """Migration 084's loop has never run again (see 370), so a table created
    now is firm-wide unless it says otherwise. Six tables the browser reads
    without one is six clients an unassigned Executive can see."""
    policies = _rows(db, f"""
        SELECT polname FROM pg_policy
         WHERE polrelid = 'public.{table}'::regclass
           AND polpermissive = false;""")
    assert f"{table}_assignment_scope" in policies, policies


# ── CGST s.143's third state ────────────────────────────────────────────────

def test_goods_kind_is_nullable_with_no_default(db):
    """One year for inputs, three for capital goods, none for moulds and dies.
    A DEFAULT would be wrong for two of the three, and NOT NULL would refuse a
    challan raised before the CA knows."""
    row = _rows(db, """
        SELECT is_nullable, coalesce(column_default, '-')
          FROM information_schema.columns
         WHERE table_name = 'delivery_challans' AND column_name = 'goods_kind';""")
    assert row == ["YES|-"]
    assert _challan(db, goods_kind="NULL").returncode == 0


@pytest.mark.parametrize("kind", ["inputs", "capital_goods",
                                  "moulds_dies_jigs_fixtures_tools"])
def test_every_kind_the_engine_knows_is_accepted(db, kind):
    assert _challan(db, no=f"DC/{kind[:4]}", goods_kind=f"'{kind}'").returncode == 0


@pytest.mark.parametrize("kind", ["input", "INPUTS", "capital", ""])
def test_a_kind_the_engine_does_not_know_is_refused(db, kind):
    assert _challan(db, goods_kind=f"'{kind}'").returncode != 0


def test_the_goods_kind_check_speaks_the_engines_vocabulary(db):
    from domain.gst import delivery_challan as dc
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.delivery_challans'::regclass
           AND conname = 'delivery_challans_goods_kind_check';""")
    assert definition, "the goods_kind CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(dc.GOODS_KINDS)


def test_the_reason_check_speaks_the_engines_vocabulary(db):
    """NAMED, not matched by content. Three constraints on this table mention
    both `reason` and `job_work` — the column's own CHECK and the two that
    keep a kind of goods and an extension on a job-work movement — so a
    content match picks up whichever Postgres returns first and then asserts
    that the ENUM has one member. That is a green test about the wrong
    constraint, which is the failure shape this whole file exists to catch."""
    from domain.gst import delivery_challan as dc
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.delivery_challans'::regclass
           AND conname = 'delivery_challans_reason_check';""")
    assert definition, "the reason CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(dc.REASONS)


@pytest.mark.parametrize("reason", ["other_than_supply", "sale_on_approval",
                                    "supply_invoice_to_follow",
                                    "skd_ckd_or_lots",
                                    "liquid_gas_quantity_unknown"])
def test_only_a_job_work_movement_may_carry_a_kind_of_goods(db, reason):
    """CGST s.143 reaches goods sent to a job worker and nothing else, so a
    kind recorded on any other movement asserts a clock that does not run."""
    assert _challan(db, no=f"DC/{reason[:6]}", reason=reason,
                    goods_kind="'inputs'").returncode != 0
    assert _challan(db, no=f"DC2/{reason[:5]}", reason=reason).returncode == 0


@pytest.mark.parametrize("reason", ["other_than_supply", "sale_on_approval"])
def test_only_a_job_work_movement_may_carry_an_extension(db, reason):
    """The proviso to s.143(1) extends a job-work period; nothing else has one."""
    assert _challan(db, no=f"DCX/{reason[:5]}", reason=reason,
                    extended="DATE '2027-01-01'").returncode != 0


# ── the serial number ───────────────────────────────────────────────────────

@pytest.mark.parametrize("maker,table", [
    (_quote, "sales_quotations"), (_order, "sales_orders"),
    (_challan, "delivery_challans")])
def test_a_number_over_sixteen_characters_is_refused(db, maker, table):
    """Rule 55(1) says "not exceeding sixteen characters" for a challan; Rule
    46(b) says the same for a tax invoice, which the other two become."""
    assert maker(db, no="A" * 16).returncode == 0
    assert maker(db, no="B" * 17).returncode != 0


@pytest.mark.parametrize("maker", [_quote, _order, _challan])
def test_a_blank_number_is_refused(db, maker):
    assert maker(db, no="   ").returncode != 0


def test_two_quotations_may_not_share_a_number(db):
    assert _quote(db, no="QT/9").returncode == 0
    assert _quote(db, no="QT/9").returncode != 0
    # Case is not a second document either — the index is on upper().
    assert _quote(db, no="qt/9").returncode != 0


def test_a_quotation_and_a_proforma_MAY_share_a_number(db):
    """Different series. Rule 46(b) reaches neither, and the only rule this
    product imposes is uniqueness per client PER KIND."""
    assert _quote(db, kind="quotation", no="D/1").returncode == 0
    assert _quote(db, kind="proforma", no="D/1").returncode == 0


def test_two_orders_and_two_challans_may_not_share_a_number(db):
    assert _order(db, no="SO/9").returncode == 0
    assert _order(db, no="SO/9").returncode != 0
    assert _challan(db, no="DC/9").returncode == 0
    assert _challan(db, no="DC/9").returncode != 0


@pytest.mark.parametrize("kind", ["quotation", "proforma"])
def test_every_quote_kind_the_engine_knows_is_accepted(db, kind):
    assert _quote(db, kind=kind, no=f"Q/{kind[:4]}").returncode == 0


@pytest.mark.parametrize("kind", ["estimate", "invoice", "QUOTATION"])
def test_a_quote_kind_the_engine_does_not_know_is_refused(db, kind):
    assert _quote(db, kind=kind).returncode != 0


# ── what is deliberately NOT here ───────────────────────────────────────────

def test_no_order_line_stores_a_delivered_or_invoiced_quantity(db):
    """Migration 278's reasoning applied to a quantity: what is left to
    deliver is a FUNCTION of the challans raised, so a stored figure is wrong
    the moment one is cancelled."""
    cols = set(_rows(db, """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'sales_order_lines';"""))
    assert "delivered_qty" not in cols
    assert "invoiced_qty" not in cols
    assert "quantity" in cols


@pytest.mark.parametrize("table", TABLES)
def test_no_pre_invoice_table_carries_a_journal(db, table):
    """No revenue is earned on an offer and no receivable exists. A
    `journal_entry_id` here would invite a posting path, and the one thing
    that must stay true of all six is that none of them touches the ledger."""
    cols = set(_rows(db, f"""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = '{table}';"""))
    assert not {c for c in cols if "journal" in c}, cols


def test_a_quotation_does_not_store_whether_it_has_expired(db):
    """It does not become expired by anyone DOING anything, so a column would
    need a nightly job to stay true and would be wrong between runs."""
    cols = set(_rows(db, """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'sales_quotations';"""))
    assert "is_expired" not in cols
    assert "valid_until" in cols


# ── the rollback refuses while a clock is running ───────────────────────────

def test_the_rollback_refuses_an_outstanding_job_work_challan(db):
    """Dropping the table loses the only record s.143's period can be run
    against, and the deemed supply it hides falls due on the challan date — in
    a return already filed."""
    import pathlib
    rollback = (pathlib.Path(__file__).resolve().parent.parent / "migrations"
                / "392_the_sales_cycle_before_the_tax_invoice_rollback.sql"
                ).read_text(encoding="utf-8")
    assert _challan(db, no="DC/OUT", reason="job_work", status="issued",
                    goods_kind="'inputs'").returncode == 0
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=rollback, capture_output=True, text=True)
    assert r.returncode != 0, "the rollback ran with a clock still going"
    assert "Refusing to roll back 392" in r.stderr
    # The tables are still there.
    assert _rows(db, "SELECT to_regclass('public.delivery_challans');") \
        == ["delivery_challans"]


def test_the_rollback_runs_once_the_goods_are_back(db):
    import pathlib
    rollback = (pathlib.Path(__file__).resolve().parent.parent / "migrations"
                / "392_the_sales_cycle_before_the_tax_invoice_rollback.sql"
                ).read_text(encoding="utf-8")
    assert _challan(db, no="DC/BACK", reason="job_work", status="issued",
                    goods_kind="'inputs'").returncode == 0
    assert _psql(db, """
        UPDATE delivery_challans SET received_back_on = DATE '2026-06-01',
               status = 'received_back';""").returncode == 0
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=rollback, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for table in TABLES:
        assert _rows(db, f"SELECT to_regclass('public.{table}');") in ([], [""])


def test_the_migration_is_rerunnable(db):
    """Every migration in this repo runs twice without complaint — the applier
    has no ledger of what it has already done for a re-run of a branch."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parent.parent / "migrations"
           / "392_the_sales_cycle_before_the_tax_invoice.sql"
           ).read_text(encoding="utf-8")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=sql, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
