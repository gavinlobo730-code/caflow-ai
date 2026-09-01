"""
Migration 303 — the SQL ageing schedule must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    public.schedule_iii_ageing computes the two Schedule III ageing schedules
    where the rows already are: the answer is twenty-four numbers and the input
    is every open document the client has, so CLAUDE.md's reporting rule puts
    the aggregation in the database. domain/reporting/ageing.py has to survive
    anyway — mock mode and local dev have no DATABASE_URL and no SQL functions —
    which creates the thing CLAUDE.md warns about: two implementations of one
    rule, which drift.

    They are safe only while something proves they agree. That is this file.
    Every scenario below is declared ONCE, as a list of documents, and fed to
    both halves: seeded into Postgres for the function, and turned into
    Receivable/Payable records for the Python. A divergence fails CI rather
    than reaching a signed balance sheet.

WHAT IS COMPARED
    The whole document — both tables, every row, every column, the column
    totals, the unclassified vendor list and the gaps. Not a summary.

WHAT ONLY POSTGRES CAN PROVE
    Three things, and they are why this cannot be a unit test:
      * `date - interval '6 months'` clamps to a real date, and the Python
        minus_months has to clamp the same way. Month-end and leap-day as-of
        dates are in the scenarios for this.
      * outstanding_paise is a GENERATED column (migration 278). The Python
        half is handed the number; only the database computes it, so only here
        is it proved that the schedule ages the same figure the AR/AP ledger
        shows.
      * the function is SECURITY DEFINER with the RLS restated in its body
        (migration 279's lesson), and access control can only be exercised
        against a real `authenticated` caller.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.reporting import ageing  # noqa: E402

FIRM = "f3030000-0000-0000-0000-000000000001"
CLIENT = "c3030000-0000-0000-0000-000000000001"
OTHER_FIRM = "f3030000-0000-0000-0000-0000000000ff"

AS_OF = date(2026, 3, 31)          # a month end, and a financial year end


# ── One declaration per document, consumed by both halves ────────────────────

class Inv:
    """A sales invoice. `paid` drives the GENERATED outstanding_paise, so the
    Python half is only ever handed a figure Postgres computed."""

    def __init__(self, ref: str, total: int, invoice_date: str,
                 due_date: str | None = None, paid: int = 0,
                 disputed: bool = False, doubtful: bool = False,
                 status: str = "issued", deleted: bool = False):
        self.ref, self.total, self.invoice_date, self.due_date = ref, total, invoice_date, due_date
        self.paid, self.disputed, self.doubtful = paid, disputed, doubtful
        self.status, self.deleted = status, deleted

    @property
    def live(self) -> bool:
        return (not self.deleted and self.status not in ("draft", "cancelled")
                and self.total - self.paid > 0
                and date.fromisoformat(self.invoice_date) <= AS_OF)

    def to_python(self) -> ageing.Receivable:
        ref = self.due_date or self.invoice_date
        return ageing.Receivable(
            outstanding_paise=self.total - self.paid,
            ref_date=date.fromisoformat(ref) if ref else None,
            disputed=self.disputed, doubtful=self.doubtful,
        )


class Bill:
    def __init__(self, ref: str, vendor: str, total: int, bill_date: str,
                 due_date: str | None = None, paid: int = 0,
                 disputed: bool = False, status: str = "received",
                 deleted: bool = False):
        self.ref, self.vendor, self.total, self.bill_date = ref, vendor, total, bill_date
        self.due_date, self.paid, self.disputed = due_date, paid, disputed
        self.status, self.deleted = status, deleted

    @property
    def live(self) -> bool:
        return (not self.deleted and self.status not in ("draft", "cancelled")
                and self.total - self.paid > 0
                and date.fromisoformat(self.bill_date) <= AS_OF)

    def to_python(self, vendors: dict[str, tuple[str, str | None]]) -> ageing.Payable:
        ref = self.due_date or self.bill_date
        vid, status = vendors[self.vendor]
        return ageing.Payable(
            outstanding_paise=self.total - self.paid,
            ref_date=date.fromisoformat(ref) if ref else None,
            disputed=self.disputed, msme_status=status,
            vendor_id=vid, vendor_name=self.vendor,
        )


# Vendors: name -> MSMED classification. None means nobody has classified them,
# which must produce a gap and never an "Others" row.
VENDORS: dict[str, str | None] = {
    "Alpha Micro Traders":   "micro",
    "Beta Small Works":      "small",
    "Gamma Medium Industries": "medium",
    "Delta Unregistered Ltd": "not_registered",
    "Epsilon Unknown":       None,
    "Zeta Unknown":          None,
}
VENDOR_IDS = {n: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ageparity.vendor.{n}"))
              for n in VENDORS}
CUSTOMER = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ageparity.customer"))

# Cut-offs relative to AS_OF = 2026-03-31, computed the way Postgres does:
#   6 months -> 2025-09-30    1 year -> 2025-03-31
#   2 years  -> 2024-03-31    3 years -> 2023-03-31
# A document due EXACTLY on a cut-off is NOT in the younger bucket.
SCENARIOS: list[tuple[str, list, list]] = [
    ("empty client", [], []),

    ("receivables — one in every column", [
        Inv("R-not-due", 100_00, "2026-03-01", "2026-04-30"),
        Inv("R-lt6m",    200_00, "2026-01-01", "2026-01-31"),
        Inv("R-on-6m",   300_00, "2025-09-01", "2025-09-30"),   # exactly 6m -> m6_y1
        Inv("R-m6y1",    400_00, "2025-06-01", "2025-06-30"),
        Inv("R-y1y2",    500_00, "2024-06-01", "2024-06-30"),
        Inv("R-y2y3",    600_00, "2023-06-01", "2023-06-30"),
        Inv("R-gty3",    700_00, "2022-06-01", "2022-06-30"),
        Inv("R-on-3y",   800_00, "2023-03-01", "2023-03-31"),   # exactly 3y -> gt_y3
    ], []),

    ("receivables — all four rows", [
        Inv("R-ug", 111_00, "2025-12-01", "2025-12-31"),
        Inv("R-ud", 222_00, "2025-12-01", "2025-12-31", doubtful=True),
        Inv("R-dg", 333_00, "2024-12-01", "2024-12-31", disputed=True),
        Inv("R-dd", 444_00, "2022-12-01", "2022-12-31", disputed=True, doubtful=True),
    ], []),

    ("receivables — excluded documents", [
        Inv("R-live",      100_00, "2025-12-01", "2025-12-31"),
        Inv("R-draft",     900_00, "2025-12-01", "2025-12-31", status="draft"),
        Inv("R-cancelled", 900_00, "2025-12-01", "2025-12-31", status="cancelled"),
        Inv("R-deleted",   900_00, "2025-12-01", "2025-12-31", deleted=True),
        Inv("R-settled",   900_00, "2025-12-01", "2025-12-31", paid=900_00),
        Inv("R-part-paid", 900_00, "2025-12-01", "2025-12-31", paid=850_00),
        Inv("R-after",     900_00, "2026-05-01", "2026-05-31"),   # raised after as_of
    ], []),

    ("receivables — no due date ages from the invoice date", [
        Inv("R-nodue-old", 100_00, "2023-01-15", None),
        Inv("R-nodue-new", 200_00, "2026-02-15", None),
    ], []),

    ("payables — one in every column, four rows", [], [
        Bill("P-not-due", "Alpha Micro Traders",     100_00, "2026-03-01", "2026-04-30"),
        Bill("P-lty1",    "Alpha Micro Traders",     200_00, "2025-06-01", "2025-06-30"),
        Bill("P-on-1y",   "Beta Small Works",        300_00, "2025-03-01", "2025-03-31"),  # exactly 1y
        Bill("P-y1y2",    "Gamma Medium Industries", 400_00, "2024-06-01", "2024-06-30"),
        Bill("P-y2y3",    "Delta Unregistered Ltd",  500_00, "2023-06-01", "2023-06-30"),
        Bill("P-gty3",    "Alpha Micro Traders",     600_00, "2022-06-01", "2022-06-30"),
        Bill("P-disp-m",  "Beta Small Works",        700_00, "2024-01-01", "2024-01-31", disputed=True),
        Bill("P-disp-o",  "Gamma Medium Industries", 800_00, "2024-01-01", "2024-01-31", disputed=True),
    ]),

    ("payables — medium is Others, not MSME", [], [
        Bill("P-micro",  "Alpha Micro Traders",     100_00, "2025-12-01", "2025-12-31"),
        Bill("P-small",  "Beta Small Works",        200_00, "2025-12-01", "2025-12-31"),
        Bill("P-medium", "Gamma Medium Industries", 400_00, "2025-12-01", "2025-12-31"),
        Bill("P-none",   "Delta Unregistered Ltd",  800_00, "2025-12-01", "2025-12-31"),
    ]),

    ("payables — an unclassified vendor is a gap, never an Other", [], [
        Bill("P-known",  "Alpha Micro Traders", 100_00, "2025-12-01", "2025-12-31"),
        Bill("P-unk-1a", "Epsilon Unknown",     300_00, "2025-12-01", "2025-12-31"),
        Bill("P-unk-1b", "Epsilon Unknown",     400_00, "2024-12-01", "2024-12-31"),
        Bill("P-unk-2",  "Zeta Unknown",        900_00, "2025-12-01", "2025-12-31"),
    ]),

    ("payables — excluded documents", [], [
        Bill("P-live",      "Alpha Micro Traders", 100_00, "2025-12-01", "2025-12-31"),
        Bill("P-draft",     "Alpha Micro Traders", 900_00, "2025-12-01", "2025-12-31", status="draft"),
        Bill("P-cancelled", "Alpha Micro Traders", 900_00, "2025-12-01", "2025-12-31", status="cancelled"),
        Bill("P-deleted",   "Alpha Micro Traders", 900_00, "2025-12-01", "2025-12-31", deleted=True),
        Bill("P-settled",   "Alpha Micro Traders", 900_00, "2025-12-01", "2025-12-31", paid=900_00),
        Bill("P-after",     "Alpha Micro Traders", 900_00, "2026-05-01", "2026-05-31"),
        Bill("P-nodue",     "Beta Small Works",    250_00, "2022-01-01", None),
    ]),

    ("both tables at once", [
        Inv("B-r1", 100_00, "2025-12-01", "2025-12-31"),
        Inv("B-r2", 200_00, "2023-12-01", "2023-12-31", disputed=True),
    ], [
        Bill("B-p1", "Alpha Micro Traders", 300_00, "2025-12-01", "2025-12-31"),
        Bill("B-p2", "Epsilon Unknown",     400_00, "2025-12-01", "2025-12-31"),
    ]),
]

# Month-end and leap-day as-of dates, where `date - interval 'N months'` clamps
# and a day-count implementation would disagree with Postgres.
CLAMP_DATES = ["2026-03-31", "2026-02-28", "2024-02-29", "2026-08-31", "2026-01-31"]


def _boundary_probes() -> tuple[list, list]:
    """A document on each side of EVERY cut-off, for every as-of date the suite
    uses.

    This scenario exists because of a negative control that PASSED. Replacing
    minus_months with `d - timedelta(days=months*30)` — the obvious wrong
    implementation, and the one a reader is most likely to "simplify" it into —
    changed no bucket in any hand-written scenario, because those documents all
    sit comfortably inside a bucket. Six calendar months back from 2026-03-31 is
    2025-09-30; 180 days back is 2025-10-02; only a document due in that two-day
    window tells the two implementations apart. The suite was proving the halves
    agreed without probing the boundary they could disagree at.

    So the boundaries are generated rather than chosen: for each as-of date and
    each cut-off, a document at the cut-off and at two days either side. That
    covers the day-count divergence AND the clamp itself — six months back from
    2026-08-31 is 2026-02-28, a day an implementation that keeps the day number
    cannot produce at all.
    """
    days: set[str] = set()
    for as_of in CLAMP_DATES:
        d = date.fromisoformat(as_of)
        for months in (6, 12, 24, 36):
            cut = ageing.minus_months(d, months)
            for delta in (-2, -1, 0, 1, 2):
                days.add((cut + timedelta(days=delta)).isoformat())
    invoices, bills = [], []
    for n, day in enumerate(sorted(days)):
        # invoice_date == due_date, so the document is in scope for every as-of
        # date whose window it was generated for.
        invoices.append(Inv(f"R-bound-{n:03d}", 1_00 + n, day, day))
        bills.append(Bill(f"P-bound-{n:03d}", "Alpha Micro Traders", 1_00 + n, day, day))
    return invoices, bills


SCENARIOS.append(("cut-off boundaries, two days either side", *_boundary_probes()))


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _q(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _seed_sql(invoices: list, bills: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES
  ('{FIRM}', 'Ageing Parity', 'a@parity.in'),
  ('{OTHER_FIRM}', 'Someone Else', 'b@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Ageing Co', 'Private Limited');
INSERT INTO customers (id, firm_id, client_id, name)
  VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'The Customer');
"""]
    for name, status in VENDORS.items():
        out.append(
            "INSERT INTO vendors (id, firm_id, client_id, name, msme_status) VALUES ("
            f"'{VENDOR_IDS[name]}', '{FIRM}', '{CLIENT}', {_q(name)}, {_q(status)});")
    for i in invoices:
        out.append(
            "INSERT INTO client_sales_invoices (firm_id, client_id, customer_id, invoice_no, "
            " invoice_date, due_date, total_paise, paid_paise, status, is_disputed, "
            " considered_doubtful, deleted_at) VALUES ("
            f"'{FIRM}', '{CLIENT}', '{CUSTOMER}', {_q(i.ref)}, {_q(i.invoice_date)}, "
            f"{_q(i.due_date)}, {i.total}, {i.paid}, {_q(i.status)}, "
            f"{str(i.disputed).lower()}, {str(i.doubtful).lower()}, "
            f"{'now()' if i.deleted else 'NULL'});")
    for b in bills:
        out.append(
            "INSERT INTO purchase_bills (firm_id, client_id, vendor_id, bill_no, bill_date, "
            " due_date, total_paise, net_payable_paise, paid_paise, status, is_disputed, "
            " deleted_at) VALUES ("
            f"'{FIRM}', '{CLIENT}', '{VENDOR_IDS[b.vendor]}', {_q(b.ref)}, {_q(b.bill_date)}, "
            f"{_q(b.due_date)}, {b.total}, {b.total}, {b.paid}, {_q(b.status)}, "
            f"{str(b.disputed).lower()}, {'now()' if b.deleted else 'NULL'});")
    return "\n".join(out)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"agepar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_schedule(dsn: str, as_of: str = "2026-03-31", client: str = CLIENT,
                  firm: str = FIRM) -> dict:
    r = _psql(dsn, f"""
        SELECT public.schedule_iii_ageing(
            '{firm}'::uuid, '{client}'::uuid, '{as_of}'::date);
    """, tuples=True)
    assert r.returncode == 0, f"schedule_iii_ageing failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _db_today(dsn: str) -> date:
    """The database's CURRENT_DATE, not Python's. The SQL half decides the
    as-at gap from its own clock; passing it to the Python half is what stops
    this suite flaking across midnight or a container timezone difference."""
    r = _psql(dsn, "SELECT CURRENT_DATE;", tuples=True)
    assert r.returncode == 0, r.stderr
    return date.fromisoformat(r.stdout.strip())


def _python_schedule(invoices: list, bills: list, as_of: date, today: date) -> dict:
    vendors = {n: (VENDOR_IDS[n], VENDORS[n]) for n in VENDORS}
    return ageing.build(
        [i.to_python() for i in invoices if i.live],
        [b.to_python(vendors) for b in bills if b.live],
        as_of, today,
    )


# ── The parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,invoices,bills", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_sql_matches_python(db, name, invoices, bills):
    seed = _psql(db, _seed_sql(invoices, bills))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"

    sql = _sql_schedule(db)
    py = _python_schedule(invoices, bills, AS_OF, _db_today(db))

    assert sql == py, (
        f"SQL and Python disagree on '{name}'.\n"
        f"  SQL:    {json.dumps(sql, indent=2, sort_keys=True)}\n"
        f"  Python: {json.dumps(py, indent=2, sort_keys=True)}"
    )


@pytest.mark.parametrize("as_of", CLAMP_DATES)
def test_month_end_and_leap_day_cutoffs_agree(db, as_of):
    """`date - interval '6 months'` clamps to a real date and minus_months has
    to clamp identically. Every scenario's documents at once, so a divergence in
    any bucket boundary shows up."""
    invoices = [i for _n, invs, _b in SCENARIOS for i in invs]
    bills = [b for _n, _i, bs in SCENARIOS for b in bs]
    # Invoice numbers are UNIQUE (firm_id, invoice_no) and the scenarios reuse
    # none, so the whole corpus seeds in one go.
    seed = _psql(db, _seed_sql(invoices, bills))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"

    d = date.fromisoformat(as_of)
    sql = _sql_schedule(db, as_of)

    def live_at(doc, doc_date):
        return (not doc.deleted and doc.status not in ("draft", "cancelled")
                and doc.total - doc.paid > 0 and date.fromisoformat(doc_date) <= d)

    vendors = {n: (VENDOR_IDS[n], VENDORS[n]) for n in VENDORS}
    py = ageing.build(
        [i.to_python() for i in invoices if live_at(i, i.invoice_date)],
        [b.to_python(vendors) for b in bills if live_at(b, b.bill_date)],
        d, _db_today(db),
    )
    assert sql == py, f"cut-offs disagree at as_of={as_of}"


def test_the_comparison_can_actually_fail(db):
    """Vacuity guard. Both halves are compared as whole documents; if either
    could return something empty and equal, every assertion above would pass
    while proving nothing."""
    _name, invoices, bills = SCENARIOS[5]
    assert _psql(db, _seed_sql(invoices, bills)).returncode == 0
    sql = _sql_schedule(db)
    assert sql["payables"]["total_paise"] > 0, "the fixture produced no payables at all"
    assert sql != _python_schedule(invoices, bills, date(2020, 1, 1), _db_today(db)), (
        "the same documents aged against a different date produced an identical "
        "document — the comparison cannot detect a difference")


# ── Scope and access control ─────────────────────────────────────────────────
# Everything above runs as the superuser, where RLS does not exist — which is
# exactly how migration 277 shipped a function that was proved correct and never
# once executed the way production executes it. These run it as a real caller.

AUTH = "a3030000-0000-0000-0000-000000000001"
USER = "b3030000-0000-0000-0000-000000000001"


def _as_authenticated(dsn: str, sql: str, auth_uid: str = AUTH) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        SET request.jwt.claims = '{{"sub": "{auth_uid}"}}';
        SET ROLE authenticated;
        {sql}""", tuples=True)


def _seed_caller(dsn: str) -> None:
    # OTHER_FIRM is already seeded by _seed_sql, so this adds only the caller.
    r = _psql(dsn, f"""
        INSERT INTO auth.users (id) VALUES ('{AUTH}') ON CONFLICT DO NOTHING;
        INSERT INTO users (id, firm_id, full_name, email, role, auth_user_id)
          VALUES ('{USER}','{FIRM}','P','p@parity.in','Partner','{AUTH}');""")
    assert r.returncode == 0, r.stderr


def test_it_is_security_definer(db):
    """Migration 279's lesson, applied at the start rather than after an outage.
    This function reads five policy-carrying tables; as INVOKER the per-row
    policy cascade is what made cash_flow_report hit the statement timeout."""
    r = _psql(db, """
        SELECT p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname='public' AND p.proname='schedule_iii_ageing';""", tuples=True)
    assert r.stdout.strip() == "t", "schedule_iii_ageing must be SECURITY DEFINER"


def test_anon_cannot_execute_it(db):
    r = _psql(db, """
        SELECT has_function_privilege('anon',
            'public.schedule_iii_ageing(uuid,uuid,date)', 'EXECUTE');""", tuples=True)
    assert r.stdout.strip() == "f", "anon must not be able to read a client's ledger"


def test_a_real_caller_gets_the_same_numbers_as_the_superuser(db):
    """SECURITY DEFINER must change who may ask, never what is computed."""
    _name, invoices, bills = SCENARIOS[9]           # "both tables at once"
    assert _psql(db, _seed_sql(invoices, bills)).returncode == 0
    _seed_caller(db)
    r = _as_authenticated(db, f"""
        SELECT public.schedule_iii_ageing('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                          '2026-03-31'::date)::text;""")
    assert r.returncode == 0, f"the function failed for an authenticated caller: {r.stderr}"
    body = json.loads(r.stdout.strip().splitlines()[-1])
    assert body == _python_schedule(invoices, bills, AS_OF, _db_today(db))


def test_another_firm_is_refused_not_served(db):
    """DEFINER bypasses RLS, so the check restated in the body IS the tenancy
    boundary — there is nothing behind it."""
    _name, invoices, bills = SCENARIOS[9]
    assert _psql(db, _seed_sql(invoices, bills)).returncode == 0
    _seed_caller(db)
    r = _as_authenticated(db, f"""
        SELECT public.schedule_iii_ageing('{OTHER_FIRM}'::uuid, '{CLIENT}'::uuid,
                                          '2026-03-31'::date);""")
    assert r.returncode != 0, "a caller read an ageing schedule for a firm that is not theirs"
    assert "not the caller" in r.stderr, r.stderr


def test_a_caller_with_no_user_record_is_refused(db):
    """An auth uid with no row in users has no firm, and must not fall through
    to reading everything."""
    _name, invoices, bills = SCENARIOS[9]
    assert _psql(db, _seed_sql(invoices, bills)).returncode == 0
    _seed_caller(db)
    stray = "a3030000-0000-0000-0000-0000000000ff"
    assert _psql(db, f"INSERT INTO auth.users (id) VALUES ('{stray}');").returncode == 0
    r = _as_authenticated(db, f"""
        SELECT public.schedule_iii_ageing('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                          '2026-03-31'::date);""", auth_uid=stray)
    assert r.returncode != 0, "a caller with no user record was served"


def test_another_firms_client_is_empty_for_the_service_role(db):
    """auth.uid() is NULL for the service role, so the body's checks are skipped
    and the WHERE clauses are the only isolation left. They must be enough."""
    _name, invoices, bills = SCENARIOS[9]
    assert _psql(db, _seed_sql(invoices, bills)).returncode == 0
    doc = _sql_schedule(db, firm=OTHER_FIRM)
    assert doc["receivables"]["total_paise"] == 0
    assert doc["payables"]["total_paise"] == 0
    assert doc["payables"]["unclassified_paise"] == 0


# ── The classification columns ───────────────────────────────────────────────

def test_msme_status_is_constrained_and_has_no_default(db):
    """The one column here that must never acquire a default: IT Act s.43B(h)
    makes micro/small a taxable-income question, so an unclassified vendor has
    to stay unclassified rather than become an 'Other'."""
    r = _psql(db, """
        SELECT COALESCE(column_default, 'NONE'), is_nullable
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='vendors'
           AND column_name='msme_status';""", tuples=True)
    assert r.stdout.strip() == "NONE|YES", r.stdout

    assert _psql(db, f"""
        INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'x', 'x@y.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'x', 'Private Limited');""").returncode == 0
    r = _psql(db, f"""
        INSERT INTO vendors (firm_id, client_id, name, msme_status)
          VALUES ('{FIRM}', '{CLIENT}', 'Nope', 'large');""")
    assert r.returncode != 0, "any string was accepted as an MSMED classification"
    assert "vendors_msme_status_check" in r.stderr, r.stderr


def test_disputed_and_doubtful_default_to_false(db):
    """These two DO default, and that is a claim rather than an absence: a
    dispute and a doubt are affirmative positions somebody records, so an
    unmarked receivable is exactly row (i) — undisputed, considered good."""
    r = _psql(db, """
        SELECT table_name || '.' || column_name || '=' || column_default
          FROM information_schema.columns
         WHERE table_schema='public'
           AND (table_name, column_name) IN
               (('client_sales_invoices','is_disputed'),
                ('client_sales_invoices','considered_doubtful'),
                ('purchase_bills','is_disputed'))
         ORDER BY 1;""", tuples=True)
    assert r.stdout.split() == [
        "client_sales_invoices.considered_doubtful=false",
        "client_sales_invoices.is_disputed=false",
        "purchase_bills.is_disputed=false",
    ], r.stdout


def test_a_vendor_belonging_to_another_client_does_not_classify_the_bill(db):
    """purchase_bills.vendor_id has an FK to vendors but nothing enforces that
    the vendor is the SAME client's. If one ever isn't, the classification is
    not this client's to borrow: the balance has to come back unclassified, so
    the CA is told rather than shown a row built from somebody else's vendor
    master. The Python half scopes its vendor fetch by firm AND client, so this
    is also what keeps the two in step."""
    other_client = "c3030000-0000-0000-0000-0000000000aa"
    stray_vendor = "d3030000-0000-0000-0000-0000000000aa"
    assert _psql(db, _seed_sql([], [])).returncode == 0
    r = _psql(db, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{other_client}', '{FIRM}', 'Another Co', 'Private Limited');
        INSERT INTO vendors (id, firm_id, client_id, name, msme_status)
          VALUES ('{stray_vendor}', '{FIRM}', '{other_client}', 'Someone Elses Micro', 'micro');
        INSERT INTO purchase_bills (firm_id, client_id, vendor_id, bill_no, bill_date,
                                    due_date, total_paise, net_payable_paise, paid_paise, status)
          VALUES ('{FIRM}', '{CLIENT}', '{stray_vendor}', 'X-1', '2025-12-01',
                  '2025-12-31', 500000, 500000, 0, 'received');""")
    assert r.returncode == 0, r.stderr

    doc = _sql_schedule(db)
    assert doc["payables"]["total_paise"] == 0, (
        "another client's vendor classified this client's bill")
    assert doc["payables"]["unclassified_paise"] == 500000
    assert "vendors_unclassified" in [g["code"] for g in doc["gaps"]]
