"""
Migration 277 — the SQL cash flow statement must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    Moving the AS-3 classification into the database is what makes the statement
    fast: 32,936 rows over the wire became one. It also creates the thing
    CLAUDE.md warns about — two implementations of a rule, which drift.

    They are safe only while something proves they agree. That is this file.
    builders.cash_flow stays as the no-database fallback for mock mode and local
    dev; public.cash_flow_report is what production runs; and every scenario
    below goes through BOTH and is compared key for key. A divergence fails CI
    rather than reaching a CA.

WHY A REAL DATABASE
    The SQL half cannot be exercised any other way. A double can prove the
    function was called; only Postgres can prove what it computes.

WHAT IS COMPARED
    The whole document, not a summary: every section, every line, every total,
    the reconciliation block, and the two reconciles flags. Account ids are
    mapped back from their seeded UUIDs so the two dicts are directly equal.
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

from domain.reporting import (  # noqa: E402
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)

FIRM = "f7000000-0000-0000-0000-000000000001"
CLIENT = "c7000000-0000-0000-0000-000000000001"
START, END = "2026-04-01", "2027-03-31"
PRE = "2026-03-02"          # before the window → affects opening cash only

# The same chart the Python suite uses (tests/test_cash_flow_statement.py), so
# the two files exercise one shape of client and a scenario can be lifted
# between them without re-deriving what an account means.
ACCOUNTS = [
    Account("bank",   "1000", "Bank — HDFC",             "Asset",     "Bank",            system_key="bank"),
    Account("ar",     "1100", "Trade Receivables",       "Asset",     "Receivable",      system_key="ar"),
    Account("gstout", "2200", "GST Output Payable",      "Liability", "Tax",             system_key="gst_output"),
    Account("ap",     "2150", "Trade Payables",          "Liability", "Payable",         system_key="ap"),
    Account("rev",    "4000", "Professional Fees",       "Revenue",   "Professional Fees"),
    Account("exp",    "5000", "Office Rent",             "Expense",   "Operating Expense"),
    Account("fa",     "1500", "Office Equipment",        "Asset",     "Fixed Asset"),
    Account("accdep", "1599", "Accumulated Depreciation", "Asset",    "Fixed Asset"),
    Account("depexp", "5900", "Depreciation Expense",    "Expense",   "Depreciation"),
    Account("gain",   "4900", "Profit on Asset Disposal", "Revenue",  "Other Income"),
    Account("loss",   "5950", "Loss on Asset Disposal",  "Expense",   "Other Expense"),
    Account("loan",   "2500", "Term Loan",               "Liability", "Loan"),
    Account("cap",    "3000", "Partner Capital Account", "Equity",    "Capital"),
    Account("retd",   "3100", "Retained Earnings",       "Equity",    "Retained"),
    Account("inv",    "1200", "Inventory",               "Asset",     "Inventory"),
    Account("obe",    "3050", "Opening Balance Equity",  "Equity",    "Capital"),
]

# Stable UUID per short id, so a failure names the same account every run.
AID = {a.id: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cfparity.{a.id}")) for a in ACCOUNTS}
BY_UUID = {v: k for k, v in AID.items()}


def je(jid, lines, date="2026-06-01"):
    return JournalEntry(id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM,
                        entry_type="Journal", lines=tuple(JournalLine(*l) for l in lines))


# ── Scenarios ────────────────────────────────────────────────────────────────
# Deliberately the same ground the Python suite covers, because those are the
# behaviours already agreed to be correct. Parity on a scenario nobody has
# reasoned about proves only that two functions are wrong together.

OPENING = je("ob", [("bank", 1000000, 0), ("cap", 0, 1000000)], PRE)

SCENARIOS: list[tuple[str, list]] = [
    ("empty ledger", []),
    ("credit sale only", [je("s1", [("ar", 10000, 0), ("rev", 0, 10000)])]),
    ("cash sale", [je("s2", [("bank", 10000, 0), ("rev", 0, 10000)])]),
    ("receipt against a receivable", [
        je("s3", [("ar", 10000, 0), ("rev", 0, 10000)]),
        je("s4", [("bank", 10000, 0), ("ar", 0, 10000)], "2026-07-01"),
    ]),
    ("depreciation excluded and added back", [
        je("s5", [("bank", 50000, 0), ("rev", 0, 50000)]),
        je("d1", [("depexp", 8000, 0), ("accdep", 0, 8000)], "2027-03-31"),
    ]),
    ("asset purchase — investing outflow", [
        je("a1", [("fa", 60000, 0), ("bank", 0, 60000)]),
    ]),
    ("asset disposal at a gain — full proceeds to investing", [
        je("a2", [("bank", 70000, 0), ("fa", 0, 50000), ("gain", 0, 20000)]),
    ]),
    ("asset disposal at a loss", [
        je("a3", [("bank", 30000, 0), ("loss", 20000, 0), ("fa", 0, 50000)]),
    ]),
    ("loan proceeds — financing inflow", [
        je("l1", [("bank", 200000, 0), ("loan", 0, 200000)]),
    ]),
    ("loan repayment — financing outflow", [
        je("l2", [("loan", 50000, 0), ("bank", 0, 50000)]),
    ]),
    ("capital introduced in cash", [
        je("c1", [("bank", 100000, 0), ("cap", 0, 100000)]),
    ]),
    ("drawings", [je("c2", [("cap", 25000, 0), ("bank", 0, 25000)])]),
    ("GST movements are operating", [
        je("g1", [("ar", 11800, 0), ("rev", 0, 10000), ("gstout", 0, 1800)]),
        je("g2", [("bank", 11800, 0), ("ar", 0, 11800)], "2026-08-01"),
    ]),
    ("year-end close is excluded", [
        je("y1", [("ar", 10000, 0), ("rev", 0, 10000)]),
        je("y2", [("rev", 10000, 0), ("retd", 0, 10000)], "2027-03-31"),
    ]),
    ("opening balances — migration 276's case", [
        je("ob1", [("obe", 103000, 0), ("inv", 0, 99000), ("ap", 0, 4000)], "2026-04-01"),
        je("ob2", [("inv", 99000, 0), ("obe", 0, 99000)], "2026-04-01"),
        je("ob3", [("ar", 10000, 0), ("rev", 0, 10000)]),
    ]),
    ("opening cash carried in from before the window", [
        OPENING,
        je("s6", [("bank", 5000, 0), ("rev", 0, 5000)]),
    ]),
    ("attribution tie — two legs of equal magnitude", [
        # The one behaviour that had no defined answer before 277: both non-bank
        # legs are investing and the same size, so which account the proceeds are
        # shown against came down to row order. Both sides now break on
        # account_id, and this scenario is what proves they break the same way.
        je("t1", [("bank", 100000, 0), ("fa", 0, 50000), ("accdep", 0, 50000)]),
    ]),
    ("combined ledger", [
        OPENING,
        je("m1", [("ar", 118000, 0), ("rev", 0, 100000), ("gstout", 0, 18000)]),
        je("m2", [("bank", 118000, 0), ("ar", 0, 118000)], "2026-07-15"),
        je("m3", [("exp", 20000, 0), ("bank", 0, 20000)], "2026-08-01"),
        je("m4", [("fa", 60000, 0), ("bank", 0, 60000)], "2026-09-01"),
        je("m5", [("bank", 200000, 0), ("loan", 0, 200000)], "2026-10-01"),
        je("m6", [("loan", 50000, 0), ("bank", 0, 50000)], "2026-11-01"),
        je("m7", [("depexp", 8000, 0), ("accdep", 0, 8000)], "2027-03-31"),
        je("m8", [("rev", 100000, 0), ("retd", 0, 100000)], "2027-03-31"),
    ]),
]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _q(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _seed_sql(entries: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Parity', 'p@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Parity Co', 'Proprietorship');
"""]
    for a in ACCOUNTS:
        out.append(
            "INSERT INTO chart_of_accounts "
            "(id, firm_id, client_id, account_code, account_name, account_type, "
            " account_subtype, system_account_key) VALUES ("
            f"'{AID[a.id]}', '{FIRM}', '{CLIENT}', {_q(a.code)}, {_q(a.name)}, "
            f"{_q(a.type)}, {_q(a.subtype)}, {_q(a.system_key)});"
        )
    for i, e in enumerate(entries):
        eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cfparity.entry.{e.id}"))
        out.append(
            "INSERT INTO journal_entries "
            "(id, firm_id, client_id, entry_date, reference_no, narration, entry_type, "
            " is_posted, status) VALUES ("
            f"'{eid}', '{FIRM}', '{CLIENT}', '{e.entry_date}', 'REF-{i}', 'n', 'Journal', "
            "true, 'posted');"
        )
        for ln in e.lines:
            out.append(
                "INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) "
                f"VALUES ('{eid}', '{AID[ln.account_id]}', {ln.debit_paise}, {ln.credit_paise});"
            )
    return "\n".join(out)


def _normalise(doc: dict) -> dict:
    """Map seeded UUIDs back to the short ids the Python side uses, so the two
    documents are directly comparable. Everything else is left untouched — the
    point is to compare the numbers, not to massage them into agreeing."""
    out = json.loads(json.dumps(doc))
    for sec in ("operating", "investing", "financing"):
        for line in out[sec]["lines"]:
            line["account_id"] = BY_UUID.get(line["account_id"], line["account_id"])
    return out


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"cfpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_report(dsn: str, start: str = START, end: str = END) -> dict:
    r = _psql(dsn, f"""
        SELECT public.cash_flow_report(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{start}'::date, '{end}'::date);
    """, tuples=True)
    assert r.returncode == 0, f"cash_flow_report failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _python_report(entries: list, start: str = START, end: str = END) -> dict:
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(entries)))
    return svc.cash_flow_statement(FIRM, CLIENT, start, end)


# ── The parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,entries", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_sql_matches_python(db, name, entries):
    seed = _psql(db, _seed_sql(entries))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"

    sql = _normalise(_sql_report(db))
    py = _python_report(entries)

    assert sql == py, (
        f"SQL and Python disagree on '{name}'.\n"
        f"  SQL:    {json.dumps(sql, indent=2, sort_keys=True)}\n"
        f"  Python: {json.dumps(py, indent=2, sort_keys=True)}"
    )


def test_the_comparison_can_actually_fail(db):
    """Vacuity guard. Every assertion above compares two documents; if either
    side silently returned the same empty shape for every scenario, they would
    agree forever and prove nothing. Two DIFFERENT scenarios must differ."""
    assert _psql(db, _seed_sql(SCENARIOS[5][1])).returncode == 0     # asset purchase
    a = _sql_report(db)
    b = _python_report(SCENARIOS[8][1])                              # loan proceeds
    assert a != b, "two unrelated scenarios produced identical statements"


# ── Sub-annual windows, which is where the quarterly columns live ────────────

@pytest.mark.parametrize("start,end", [
    ("2026-04-01", "2026-06-30"),
    ("2026-07-01", "2026-09-30"),
    ("2026-10-01", "2026-12-31"),
    ("2027-01-01", "2027-03-31"),
])
def test_sql_matches_python_per_quarter(db, start, end):
    """The window boundary is where an off-by-one would hide: opening cash is
    everything strictly BEFORE the start, closing everything up to and including
    the end, and the body is the entries between them."""
    entries = dict(SCENARIOS)["combined ledger"]
    assert _psql(db, _seed_sql(entries)).returncode == 0
    assert _normalise(_sql_report(db, start, end)) == _python_report(entries, start, end)


def test_opening_cash_excludes_the_first_day_itself(db):
    """`entry_date < p_start`, not <=. An entry dated exactly on the start date
    belongs to the period, not to its opening balance — the classic off-by-one,
    and one that would still reconcile, just against the wrong opening figure."""
    entries = [je("edge", [("bank", 12345, 0), ("cap", 0, 12345)], "2026-04-01")]
    assert _psql(db, _seed_sql(entries)).returncode == 0
    doc = _sql_report(db, "2026-04-01", "2027-03-31")
    assert doc["opening_cash_paise"] == 0, "an entry ON the start date leaked into opening cash"
    assert doc["closing_cash_paise"] == 12345
    assert _normalise(doc) == _python_report(entries)


# ── Scope ────────────────────────────────────────────────────────────────────

def test_another_firms_client_returns_an_empty_statement(db):
    assert _psql(db, _seed_sql(SCENARIOS[1][1])).returncode == 0
    r = _psql(db, f"""
        SELECT public.cash_flow_report(
            'f7000000-0000-0000-0000-0000000000ff'::uuid, '{CLIENT}'::uuid,
            '{START}'::date, '{END}'::date);""", tuples=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout.strip())
    assert doc["operating"]["total_paise"] == 0
    assert doc["operating_reconciliation"]["net_profit_paise"] == 0


def test_anon_cannot_execute_it(db):
    r = _psql(db, """
        SELECT has_function_privilege('anon',
            'public.cash_flow_report(uuid,uuid,date,date)', 'EXECUTE');""", tuples=True)
    assert r.stdout.strip() == "f", "anon must not be able to read the ledger"


def test_it_is_security_definer(db):
    """It was INVOKER in 277, and that is what made it fail in production.

    journal_lines' policy is `journal_entry_id IN (SELECT je.id FROM
    journal_entries WHERE firm_id = get_my_firm_id())`, and journal_entries
    carries three more policies calling get_my_firm_id(), can_access_client(),
    get_my_role() and my_internal_client_id(). Under INVOKER the planner cannot
    hoist that out of the aggregate, so a set-based query becomes a per-row
    cascade of function calls and dies on the statement timeout — the report was
    SLOWER than the Python it replaced. Migration 279 restates those checks once,
    in the body."""
    r = _psql(db, """
        SELECT p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname='public' AND p.proname='cash_flow_report';""", tuples=True)
    assert r.stdout.strip() == "t", "cash_flow_report must be SECURITY DEFINER (migration 279)"


# ── As a real caller ─────────────────────────────────────────────────────────
# Everything above runs as the superuser, where RLS does not exist. That is what
# let 277 ship: the statement was proved correct and never once executed the way
# production executes it. These do.

AUTH = "a7000000-0000-0000-0000-000000000001"
USER = "b7000000-0000-0000-0000-000000000001"
OTHER_FIRM = "f7000000-0000-0000-0000-0000000000ff"


def _as_authenticated(dsn: str, sql: str, auth_uid: str = AUTH) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        SET request.jwt.claims = '{{"sub": "{auth_uid}"}}';
        SET ROLE authenticated;
        {sql}""", tuples=True)


def _seed_caller(dsn: str) -> None:
    r = _psql(dsn, f"""
        INSERT INTO auth.users (id) VALUES ('{AUTH}') ON CONFLICT DO NOTHING;
        INSERT INTO users (id, firm_id, full_name, email, role, auth_user_id)
          VALUES ('{USER}','{FIRM}','P','p@parity.in','Partner','{AUTH}');
        INSERT INTO firms (id,name,email) VALUES ('{OTHER_FIRM}','Other','o@t.in');""")
    assert r.returncode == 0, r.stderr


def test_a_real_caller_gets_the_statement(db):
    """The regression in one line: as `authenticated`, over a ledger, it must
    RETURN rather than be cancelled."""
    assert _psql(db, _seed_sql(dict(SCENARIOS)["combined ledger"])).returncode == 0
    _seed_caller(db)
    r = _as_authenticated(db, f"""
        SELECT public.cash_flow_report('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                       '{START}'::date, '{END}'::date) IS NOT NULL;""")
    assert r.returncode == 0, f"the function failed for an authenticated caller: {r.stderr}"
    assert r.stdout.strip().endswith("t")


def test_a_real_caller_gets_the_same_numbers_as_the_superuser(db):
    """SECURITY DEFINER must not change WHAT is computed — only who may ask."""
    assert _psql(db, _seed_sql(dict(SCENARIOS)["combined ledger"])).returncode == 0
    _seed_caller(db)
    r = _as_authenticated(db, f"""
        SELECT public.cash_flow_report('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                       '{START}'::date, '{END}'::date)::text;""")
    assert r.returncode == 0, r.stderr
    body = r.stdout.strip().splitlines()[-1]
    assert _normalise(json.loads(body)) == _python_report(dict(SCENARIOS)["combined ledger"])


def test_another_firm_is_refused_not_served(db):
    """The isolation the policies would have enforced, now enforced once per call
    in the body. DEFINER bypasses RLS, so this check IS the tenancy boundary."""
    assert _psql(db, _seed_sql(SCENARIOS[1][1])).returncode == 0
    _seed_caller(db)
    r = _as_authenticated(db, f"""
        SELECT public.cash_flow_report('{OTHER_FIRM}'::uuid, '{CLIENT}'::uuid,
                                       '{START}'::date, '{END}'::date);""")
    assert r.returncode != 0, "a caller read a statement for a firm that is not theirs"
    assert "not the caller" in r.stderr, r.stderr


def test_a_caller_with_no_user_record_is_refused(db):
    """An auth uid with no row in users has no firm, and must not fall through
    to reading everything."""
    assert _psql(db, _seed_sql(SCENARIOS[1][1])).returncode == 0
    _seed_caller(db)
    stranger = "a7000000-0000-0000-0000-0000000000ff"
    assert _psql(db, f"INSERT INTO auth.users (id) VALUES ('{stranger}') ON CONFLICT DO NOTHING;").returncode == 0
    r = _as_authenticated(db, f"""
        SELECT public.cash_flow_report('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                       '{START}'::date, '{END}'::date);""", auth_uid=stranger)
    assert r.returncode != 0
    assert "no user record" in r.stderr, r.stderr


def test_it_survives_a_real_ledger_under_rls(db):
    """The function works for a real caller over a real ledger.

    WHAT THIS DOES AND DOES NOT PROVE — stated because I checked.
    It does NOT reproduce the production timeout: with the fix reverted to
    SECURITY INVOKER this test still passes, because 12,000 lines on CI hardware
    finishes the per-row policy cascade inside any tolerance worth setting. A
    threshold tuned to fail here would be tuned to this runner's speed, and the
    repo already decided against clocks in CI for exactly that reason (see
    apps/web/scripts/report-period-pickers and the reporting-reads ratchet, which
    count rows rather than milliseconds).

    test_it_is_security_definer is the guard that actually bites. What THIS adds
    is the coverage 277 never had at all: the function executed the way
    production executes it — as `authenticated`, with RLS live, over a ledger
    rather than a handful of rows — returning a real statement. Every other
    assertion in this file runs as the superuser, where RLS does not exist, and
    that is precisely how a function that could not complete in production
    passed 27 scenarios.
    """
    # Firm, client and chart first — _seed_caller only adds the user.
    assert _psql(db, _seed_sql([])).returncode == 0
    _seed_caller(db)
    seed = _psql(db, f"""
        INSERT INTO journal_entries
          (id, firm_id, client_id, entry_date, reference_no, narration, entry_type,
           is_posted, status)
        SELECT gen_random_uuid(), '{FIRM}', '{CLIENT}',
               DATE '2026-04-01' + (g % 300), 'BULK-' || g, 'n', 'Journal', true, 'posted'
          FROM generate_series(1, 4000) g;

        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        SELECT je.id, x.acct, x.dr, x.cr
          FROM (SELECT id FROM journal_entries
                 WHERE client_id = '{CLIENT}' AND reference_no LIKE 'BULK-%') je
         CROSS JOIN LATERAL (VALUES
             ('{AID["ar"]}'::uuid, 11800::bigint, 0::bigint),
             ('{AID["rev"]}'::uuid, 0::bigint, 10000::bigint),
             ('{AID["gstout"]}'::uuid, 0::bigint, 1800::bigint)
         ) AS x(acct, dr, cr);""")
    assert seed.returncode == 0, f"bulk seed failed: {seed.stderr}"

    count = _psql(db, f"""
        SELECT count(*) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
         WHERE je.client_id = '{CLIENT}';""", tuples=True).stdout.strip()
    assert int(count) >= 12000, f"the fixture is too small to mean anything: {count} lines"

    r = _as_authenticated(db, f"""
        SET statement_timeout = '30s';
        SELECT (public.cash_flow_report('{FIRM}'::uuid, '{CLIENT}'::uuid,
                                        '{START}'::date, '{END}'::date)
                ->> 'net_change_paise') IS NOT NULL;""")
    assert r.returncode == 0, (
        f"cash_flow_report did not complete for an authenticated caller over "
        f"{count} lines — this is the production failure:\n{r.stderr}"
    )
    assert r.stdout.strip().endswith("t")
