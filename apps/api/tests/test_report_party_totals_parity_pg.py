"""
Migration 745 — the P&L Statement's sums by party in SQL must equal the Python rule, exactly (POST-A-469).

public.report_party_totals adds the taxable value of the counted documents where they are;
domain/reporting/party_totals.py is the same rule for mock mode and for the minutes the API runs before the migration.
Every scenario is declared once and fed to both halves: the SQL half reads the seeded tables, the Python half is handed
the rows the service's own paged read (`report_transactions_service._counted_rows`) returns from the same database
through a PostgREST-shaped double, so the documents each half counts are decided by its own code, not by the test.

What only Postgres can prove: the function's own filters (status, deletion, firm, client list, both bounds of the
window) agree with the feed's; a document of another firm, or naming another firm's customer, never reaches an answer;
and a signed-in session cannot call the function at all.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from tests._cross_tenant_rows import LEGACY_ROWS_ALLOWED

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.reporting import party_totals as rule  # noqa: E402
from services import report_transactions_service as svc  # noqa: E402

FIRM = "f7450000-0000-0000-0000-000000000001"
OTHER_FIRM = "f7450000-0000-0000-0000-0000000000ff"
CLIENT = "c7450000-0000-0000-0000-000000000001"
CLIENT_B = "c7450000-0000-0000-0000-000000000002"
OTHER_CLIENT = "c7450000-0000-0000-0000-0000000000ff"
CUST_1 = "a7450000-0000-0000-0000-000000000001"
CUST_2 = "a7450000-0000-0000-0000-000000000002"     # the same name as CUST_1: two lines, not one
CUST_B = "a7450000-0000-0000-0000-000000000003"
CUST_NONAME = "a7450000-0000-0000-0000-000000000004"
CUST_OTHER = "a7450000-0000-0000-0000-0000000000ff"
VEND_1 = "b7450000-0000-0000-0000-000000000001"
VEND_2 = "b7450000-0000-0000-0000-000000000002"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


_n = 0


def _sale(client, customer, day, taxable, status="issued", *, firm=FIRM, deleted=False):
    global _n
    _n += 1
    cust = f"'{customer}'" if customer else "NULL"
    gone = "NOW()" if deleted else "NULL"
    return (f"INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, "
            f"taxable_amount_paise, total_paise, status, paid_paise, credited_paise, deleted_at) VALUES "
            f"('{uuid.uuid4()}', '{firm}', '{client}', {cust}, 'S-{_n:04d}', '{day}', {taxable}, {taxable}, "
            f"'{status}', 0, 0, {gone});")


def _bill(client, vendor, day, taxable, status="received", *, firm=FIRM, deleted=False):
    global _n
    _n += 1
    vend = f"'{vendor}'" if vendor else "NULL"
    gone = "NOW()" if deleted else "NULL"
    return (f"INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, "
            f"taxable_amount_paise, total_paise, status, deleted_at) VALUES "
            f"('{uuid.uuid4()}', '{firm}', '{client}', {vend}, 'B-{_n:04d}', '{day}', {taxable}, {taxable}, "
            f"'{status}', {gone});")


# A stray id naming another firm's customer is planted the way tests/_cross_tenant_rows.py plants a legacy row.
SEED = LEGACY_ROWS_ALLOWED + "\n".join([
    f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Party Totals', 'a@p.in'), ('{OTHER_FIRM}', 'Else', 'b@p.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT}', '{FIRM}', 'A Co', 'Private Limited'), ('{CLIENT_B}', '{FIRM}', 'B Co', 'Private Limited'),
  ('{OTHER_CLIENT}', '{OTHER_FIRM}', 'Else Co', 'Private Limited');
INSERT INTO customers (id, firm_id, client_id, name) VALUES
  ('{CUST_1}', '{FIRM}', '{CLIENT}', 'Same Name'), ('{CUST_2}', '{FIRM}', '{CLIENT}', 'Same Name'),
  ('{CUST_B}', '{FIRM}', '{CLIENT_B}', 'B Customer'), ('{CUST_NONAME}', '{FIRM}', '{CLIENT}', ''),
  ('{CUST_OTHER}', '{OTHER_FIRM}', '{OTHER_CLIENT}', 'Not Ours');
INSERT INTO vendors (id, firm_id, client_id, name) VALUES
  ('{VEND_1}', '{FIRM}', '{CLIENT}', 'Vendor One'), ('{VEND_2}', '{FIRM}', '{CLIENT_B}', 'Vendor Two');
""",
    _sale(CLIENT, CUST_1, "2026-04-01", 100_00),
    _sale(CLIENT, CUST_1, "2026-05-15", 250_50, "partially_paid"),
    _sale(CLIENT, CUST_2, "2026-05-31", 250_50, "paid"),          # ties CUST_1's second: order falls to the id
    _sale(CLIENT, CUST_NONAME, "2026-06-30", 7),
    _sale(CLIENT, CUST_OTHER, "2026-06-01", 999),                  # names another firm's customer (a stray id)
    _sale(CLIENT, CUST_1, "2026-06-01", 1_000_000, "draft"),       # not counted
    _sale(CLIENT, CUST_1, "2026-06-01", 2_000_000, "cancelled"),   # not counted
    _sale(CLIENT, CUST_1, "2026-06-01", 3_000_000, deleted=True),  # not counted
    _sale(CLIENT_B, CUST_B, "2026-04-30", 40_000),
    _sale(OTHER_CLIENT, CUST_OTHER, "2026-05-01", 5_000_000, firm=OTHER_FIRM),
    _bill(CLIENT, VEND_1, "2026-04-02", 30_000),
    _bill(CLIENT, VEND_1, "2026-07-01", 12_345, "paid"),
    _bill(CLIENT_B, VEND_2, "2026-05-05", 60_000, "partially_paid"),
    _bill(CLIENT, VEND_1, "2026-05-05", 7_000_000, "draft"),
    _bill(CLIENT, VEND_1, "2026-05-05", 8_000_000, "cancelled"),
])


@pytest.fixture(scope="module")
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"ptot_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    d = f"{admin} dbname={name}"
    try:
        seeded = _psql(d, SEED)
        assert seeded.returncode == 0, seeded.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql(dsn, client_ids=None, date_from=None, date_to=None, firm=FIRM) -> dict:
    ids = "NULL::uuid[]" if client_ids is None else "ARRAY[" + ",".join(f"'{c}'" for c in client_ids) + "]::uuid[]"
    lo = f"'{date_from}'::date" if date_from else "NULL::date"
    hi = f"'{date_to}'::date" if date_to else "NULL::date"
    r = _psql(dsn, f"SELECT public.report_party_totals('{firm}'::uuid, {ids}, {lo}, {hi});", tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


class _PgQuery:
    """Just enough of a PostgREST builder to run the service's own paged reads against the seeded database."""

    def __init__(self, dsn, table):
        self.dsn, self.table, self.cols, self.where, self.order_by, self.lim = dsn, table, "*", [], None, None

    def select(self, cols, *_a, **_k):
        self.cols = cols
        return self

    def _q(self, v):
        return "'" + str(v).replace("'", "''") + "'"

    def eq(self, k, v):
        self.where.append(f"{k} = {self._q(v)}")
        return self

    def is_(self, k, v):
        self.where.append(f"{k} IS NULL" if v == "null" else f"{k} IS NOT NULL")
        return self

    def in_(self, k, vs):
        vs = list(vs)
        self.where.append(f"{k}::text IN ({','.join(self._q(v) for v in vs)})" if vs else "false")
        return self

    def gte(self, k, v):
        self.where.append(f"{k} >= {self._q(v)}")
        return self

    def gt(self, k, v):
        self.where.append(f"{k} > {self._q(v)}")
        return self

    def lte(self, k, v):
        self.where.append(f"{k} <= {self._q(v)}")
        return self

    def order(self, k, *_a, desc=False, **_k):
        self.order_by = f"{k} {'DESC' if desc else 'ASC'}"
        return self

    def limit(self, n):
        self.lim = n
        return self

    def range(self, a, b):
        self.lim = b - a + 1
        self.where_offset = a
        return self

    def execute(self):
        sql = f"SELECT coalesce(json_agg(t), '[]') FROM (SELECT {self.cols} FROM {self.table}"
        if self.where:
            sql += " WHERE " + " AND ".join(self.where)
        if self.order_by:
            sql += f" ORDER BY {self.order_by}"
        if self.lim is not None:
            sql += f" LIMIT {self.lim}"
        if getattr(self, "where_offset", None):
            sql += f" OFFSET {self.where_offset}"
        sql += ") t;"
        r = _psql(self.dsn, sql, tuples=True)
        assert r.returncode == 0, r.stderr

        class _R:
            data = json.loads(r.stdout.strip())
        return _R()


class _PgDb:
    """No `rpc`, so the service answers through its Python rule."""

    def __init__(self, dsn):
        self.dsn = dsn

    def table(self, name):
        return _PgQuery(self.dsn, name)


def _py(dsn, client_ids=None, date_from=None, date_to=None, firm=FIRM) -> dict:
    return svc.party_totals(_PgDb(dsn), firm, client_ids=client_ids, date_from=date_from, date_to=date_to)


WINDOWS = [
    (None, None), ("2026-04-01", "2026-04-30"), ("2026-05-01", "2026-05-31"), ("2026-05-31", "2026-06-30"),
    ("2026-07-01", "2026-07-01"), ("2027-01-01", "2027-03-31"), (None, "2026-05-15"), ("2026-05-15", None),
]
SCOPES = [None, [CLIENT], [CLIENT_B], [CLIENT, CLIENT_B], [OTHER_CLIENT]]


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("scope", SCOPES)
def test_both_halves_give_the_same_answer(dsn, window, scope):
    assert _sql(dsn, scope, *window) == _py(dsn, scope, *window)


def test_the_whole_firm_is_what_the_old_browser_arithmetic_gave_on_the_feeds_rows(dsn):
    """The totals equal what /reports used to compute in the browser from GET /api/reports/transactions: the sum
    of `taxable_amount_paise` over the sales rows and over the purchase rows of the same window."""
    feed = svc.list_transactions(_PgDb(dsn), FIRM, client_ids=None, date_from="2026-04-01", date_to="2026-06-30")
    revenue = sum(t["taxable_amount_paise"] for t in feed if t["transaction_type"] == "sales_invoice")
    expense = sum(t["taxable_amount_paise"] for t in feed if t["transaction_type"] == "purchase_invoice")
    answer = _sql(dsn, None, "2026-04-01", "2026-06-30")
    assert (answer["revenue_total_paise"], answer["expense_total_paise"]) == (revenue, expense)
    assert answer["net_paise"] == revenue - expense
    assert answer["sales_documents"] + answer["purchase_documents"] == len(feed)


def test_two_customers_of_one_name_are_two_lines_and_a_name_that_is_not_the_firms_is_not_shown(dsn):
    answer = _sql(dsn, [CLIENT], "2026-05-01", "2026-06-30")
    ids = [line["party_id"] for line in answer["revenue"]]
    assert CUST_1 in ids and CUST_2 in ids
    stray = next(line for line in answer["revenue"] if line["party_id"] == CUST_OTHER)
    assert stray["party_name"] is None and stray["total_paise"] == 999
    blank = next(line for line in answer["revenue"] if line["party_id"] == CUST_NONAME)
    assert blank["party_name"] is None


def test_another_firms_documents_never_reach_the_answer(dsn):
    answer = _sql(dsn, [OTHER_CLIENT])
    assert answer["revenue"] == [] and answer["revenue_total_paise"] == 0
    other = _sql(dsn, None, firm=OTHER_FIRM)
    assert other["revenue_total_paise"] == 5_000_000          # its own firm reads it; ours never does


def test_a_signed_in_session_cannot_call_it(dsn):
    r = _psql(dsn, "SELECT has_function_privilege('authenticated', "
                   "'public.report_party_totals(uuid, uuid[], date, date)', 'EXECUTE'), "
                   "has_function_privilege('anon', 'public.report_party_totals(uuid, uuid[], date, date)', 'EXECUTE'), "
                   "has_function_privilege('service_role', "
                   "'public.report_party_totals(uuid, uuid[], date, date)', 'EXECUTE');", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f|f|t"


def test_the_rule_on_its_own():
    out = rule.party_totals(
        [{"customer_id": "x", "taxable_amount_paise": "5"}, {"customer_id": None, "taxable_amount_paise": 2}],
        [], customer_names={"x": "X"}, vendor_names={})
    assert out["revenue_total_paise"] == 7 and out["revenue"][0]["party_name"] == "X"
