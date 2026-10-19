"""
Migration 522 — the SQL "TDS deducted and not yet deposited" must equal the Python twin, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    The hub's TDS tile read `tds_deductions.challan_no IS NULL`, a column nothing writes, so it counted every deduction as
    undeposited. The right answer is the challan register's, and a firm-wide tile may not fetch rows proportional to the
    ledger (CLAUDE.md's reporting rule), so `public.tds_undeposited_paise` computes it where the rows are.
    `domain/tds/undeposited.py` has to survive anyway: mock mode, local development and the in-memory suites have no SQL
    functions. Two implementations of one rule drift, and they are safe only while something proves they agree. Every scenario
    below is declared ONCE, as deductions and challans, and fed to both halves.

WHAT ONLY POSTGRES CAN PROVE
      * the SQL groups by a bracket-stripped section and the register (statement, worksheet) by the section registry's
        `parent_of`: every key the registry holds, in both years, is run through the SQL and the twin, and the twin is held to the
        register's own match in the unit file; odd spellings (a non-breaking space, brackets, a tab) are pinned here;
      * the regular expressions, `extract()`, `lpad` and the financial-year label agree with the Python date rules at the
        quarter and year boundaries;
      * `greatest(.., 0)` per row is what `challan_mapping.assign` does with a negative row;
      * the function is SECURITY INVOKER, so a signed-in caller of another firm gets nothing (row security runs), and `anon` and
        PUBLIC cannot execute it.
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

from domain.tds import section_rates  # noqa: E402
from domain.tds.undeposited import undeposited_paise  # noqa: E402

FIRM = "f5220000-0000-0000-0000-000000000001"
OTHER_FIRM = "f5220000-0000-0000-0000-0000000000ff"
A = "c5220000-0000-0000-0000-00000000000a"
B = "c5220000-0000-0000-0000-00000000000b"
OTHER_FIRMS_CLIENT = "c5220000-0000-0000-0000-0000000000ff"
AUTH = "a5220000-0000-0000-0000-000000000001"
USER = "e5220000-0000-0000-0000-000000000001"
AUTH_OTHER = "a5220000-0000-0000-0000-0000000000ff"
USER_OTHER = "e5220000-0000-0000-0000-0000000000ff"


def ded(client=A, section="194C", on="2026-05-10", tds=10_000_00, surcharge=0, cess=0, firm=FIRM):
    return {"firm_id": firm, "client_id": client, "section": section, "transaction_date": on, "tds_paise": tds,
            "surcharge_paise": surcharge, "cess_paise": cess}


def chl(client=A, section="194C", fy="2026-27", quarter="Q1", tds=10_000_00, surcharge=0, firm=FIRM, paid_on="2026-06-07", no=None):
    return {"firm_id": firm, "client_id": client, "section": section, "financial_year": fy, "quarter": quarter, "tds_paise": tds,
            "surcharge_paise": surcharge, "payment_date": paid_on, "challan_no": no or uuid.uuid4().hex[:8]}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _lit(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _seed_sql(deductions: list, challans: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Undeposited Parity', 'a@parity.in'),
                                            ('{OTHER_FIRM}', 'Someone Else', 'b@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{A}', '{FIRM}', 'Client A', 'Private Limited'), ('{B}', '{FIRM}', 'Client B', 'Private Limited'),
  ('{OTHER_FIRMS_CLIENT}', '{OTHER_FIRM}', 'Not Ours', 'Private Limited');
"""]
    for i, d in enumerate(deductions):
        out.append(
            "INSERT INTO tds_deductions (firm_id, client_id, deductee_name, section, transaction_date, tds_paise, surcharge_paise, cess_paise) "
            f"VALUES ('{d['firm_id']}', '{d['client_id']}', 'Deductee {i}', {_lit(d['section'])}, {_lit(d['transaction_date'])}, "
            f"{d['tds_paise']}, {d['surcharge_paise']}, {d['cess_paise']});")
    for c in challans:
        out.append(
            "INSERT INTO tds_challans (firm_id, client_id, challan_no, bsr_code, payment_date, financial_year, quarter, tds_paise, "
            "surcharge_paise, total_paise, section) "
            f"VALUES ('{c['firm_id']}', '{c['client_id']}', {_lit(c['challan_no'])}, '0000000', {_lit(c['payment_date'])}, "
            f"{_lit(c['financial_year'])}, {_lit(c['quarter'])}, {c['tds_paise']}, {c['surcharge_paise']}, "
            f"{c['tds_paise'] + c['surcharge_paise']}, {_lit(c['section'])});")
    return "\n".join(out)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"tdsund_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql(dsn: str, client_ids=None, firm: str = FIRM) -> int:
    arg = "NULL::uuid[]" if client_ids is None else "ARRAY[" + ",".join(f"'{c}'" for c in client_ids) + "]::uuid[]"
    if client_ids is not None and not client_ids:
        arg = "ARRAY[]::uuid[]"
    r = _psql(dsn, f"SELECT public.tds_undeposited_paise('{firm}'::uuid, {arg});", tuples=True)
    assert r.returncode == 0, f"tds_undeposited_paise failed: {r.stderr}"
    return int(r.stdout.strip())


def _python(deductions: list, challans: list, client_ids=None, firm: str = FIRM) -> int:
    return undeposited_paise([d for d in deductions if d["firm_id"] == firm], [c for c in challans if c["firm_id"] == firm],
                             client_ids=client_ids)


def _both(dsn, deductions, challans, **kw):
    assert _psql(dsn, _seed_sql(deductions, challans)).returncode == 0
    return _sql(dsn, **kw), _python(deductions, challans, **kw)


# ── The scenarios, declared once ───────────────────────────────────────────────

SCENARIOS = {
    "nothing at all": ([], []),
    "no challan": ([ded()], []),
    "paid in full": ([ded()], [chl()]),
    "short challan": ([ded()], [chl(tds=6_000_00)]),
    "surplus challan": ([ded()], [chl(tds=25_000_00)]),
    "surplus does not carry to another section or quarter": (
        [ded(section="194C", tds=10_000_00), ded(section="194J", on="2026-05-12", tds=7_500_00),
         ded(section="194C", on="2026-08-02", tds=3_000_00)], [chl(tds=15_000_00)]),
    "other quarter and other year": ([ded()], [chl(quarter="Q2"), chl(fy="2025-26")]),
    "boundaries: 31 March, 1 April, 30 June, 1 July": (
        [ded(on="2027-03-31", tds=1_00), ded(on="2027-04-01", tds=2_00), ded(on="2026-06-30", tds=4_00),
         ded(on="2026-07-01", tds=8_00), ded(on="2026-09-30", tds=16_00), ded(on="2026-10-01", tds=32_00),
         ded(on="2026-12-31", tds=64_00), ded(on="2027-01-01", tds=128_00)],
        [chl(fy="2026-27", quarter="Q4", tds=1_00), chl(fy="2027-28", quarter="Q1", tds=2_00),
         chl(fy="2026-27", quarter="Q1", tds=1_00), chl(fy="2026-27", quarter="Q2", tds=8_00),
         chl(fy="2026-27", quarter="Q3", tds=32_00)]),
    "parent section typed on the challan": (
        [ded(section="194J(B)", tds=2_000_00), ded(section="194I(a)", on="2026-05-11", tds=500_00)],
        [chl(section="194J", tds=2_000_00), chl(section="194I(b)", tds=300_00)]),
    "surcharge and cess": (
        [ded(section="195", tds=10_000_00, surcharge=1_000_00, cess=440_00)],
        [chl(section="195", tds=10_000_00, surcharge=1_000_00)]),
    "salary is in neither side": (
        [ded(section="192", tds=9_00), ded(section="Sec192", tds=9_00), ded(section=" 192 ", tds=9_00), ded(section="194C", tds=1_00)],
        [chl(section="192", tds=9_99)]),
    "a salary challan pays no deduction, even one typed 192(1)": (
        [ded(section="192(1)", tds=7_00)], [chl(section="192", tds=7_00)]),
    "a negative row neither pays nor owes": (
        [ded(tds=-5_00), ded(on="2026-05-11", tds=4_00)], [chl(tds=-3_00)]),
    "blank section on both sides": (
        [ded(section=""), ded(section="  ", on="2026-05-11", tds=1_00)], [chl(section="")]),
    "case and surrounding spaces": (
        [ded(section=" 194j(a) ", tds=1_000_00)], [chl(section="194J", tds=400_00)]),
    "an unknown section is grouped by its bracket-stripped text": (
        [ded(section="194Z(A)", tds=10_00)], [chl(section="194Z", tds=10_00)]),
    "empty brackets, nested brackets and a space before the bracket": (
        [ded(section="194J()", tds=5_00), ded(section="194J(a)(b)", on="2026-05-11", tds=7_00),
         ded(section="194J (B)", on="2026-05-12", tds=6_00)], [chl(section="194J", tds=12_00)]),
    "a non-breaking space is part of the text, a tab and a newline are not": (
        [ded(section="\u00a0194C", tds=10_000_00), ded(section="\t194C\n", on="2026-05-11", tds=4_00)], [chl(section="194C", tds=4_00)]),
    "a challan typed with surrounding whitespace and a lower-case limb still pays": (
        [ded(section="194C", tds=3_00), ded(section="194J(B)", on="2026-05-11", tds=4_00)],
        [chl(section=" \t194c\n", tds=3_00), chl(section="\t194j ", tds=4_00, no="2")]),
    "two clients and a challan of one": ([ded(client=A), ded(client=B, tds=20_00)], [chl(client=A)]),
    "another firm's deduction carrying this client's id owes nothing here": (
        [ded(firm=OTHER_FIRM, client=A, tds=99_000_00), ded(tds=1_00)], []),
    "another firm's challan carrying this client's id pays nothing": (
        [ded()], [chl(firm=OTHER_FIRM, client=A)]),
    "another firm is not in the answer": (
        [ded(), ded(client=OTHER_FIRMS_CLIENT, firm=OTHER_FIRM, tds=99_000_00)], [chl(client=OTHER_FIRMS_CLIENT, firm=OTHER_FIRM, tds=1_00)]),
    "an old and a new year together": (
        [ded(on="2025-05-10", tds=3_00), ded(on="2026-05-10", tds=5_00)], [chl(fy="2025-26", tds=1_00), chl(fy="2026-27", tds=1_00)]),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_gives_the_same_answer_on_both_halves(db, name):
    deductions, challans = SCENARIOS[name]
    sql, py = _both(db, deductions, challans)
    assert sql == py, name


@pytest.mark.parametrize("scope,want", [
    (None, 20_00), ([A], 0), ([B], 20_00), ([A, B], 20_00), ([], 0), ([OTHER_FIRMS_CLIENT], 0)])
def test_the_clients_asked_for_decide_the_answer_the_same_way_on_both_halves(db, scope, want):
    """None is every client of the firm, a list is those clients, an EMPTY list is nobody. A's tax is paid by its challan; B's is not."""
    deductions, challans = SCENARIOS["two clients and a challan of one"]
    sql, py = _both(db, deductions, challans, client_ids=scope)
    assert (sql, py) == (want, want)


# Two halves that agree on a wrong answer pass a parity test, so these are the figures the RULE gives.
@pytest.mark.parametrize("name,want", [
    ("nothing at all", 0),
    ("no challan", 10_000_00), ("paid in full", 0), ("short challan", 4_000_00), ("surplus challan", 0),
    ("surplus does not carry to another section or quarter", 7_500_00 + 3_000_00),
    ("other quarter and other year", 10_000_00),
    ("parent section typed on the challan", 200_00),
    ("surcharge and cess", 440_00),
    ("salary is in neither side", 1_00),
    ("a negative row neither pays nor owes", 4_00),
    ("a salary challan pays no deduction, even one typed 192(1)", 7_00),
    ("blank section on both sides", 10_000_00 + 1_00),
    ("a challan typed with surrounding whitespace and a lower-case limb still pays", 0),
    ("an unknown section is grouped by its bracket-stripped text", 0),
    ("empty brackets, nested brackets and a space before the bracket", 6_00),
    ("a non-breaking space is part of the text, a tab and a newline are not", 10_000_00),
    ("case and surrounding spaces", 600_00),
    ("another firm's deduction carrying this client's id owes nothing here", 1_00),
    ("another firm's challan carrying this client's id pays nothing", 10_000_00),
    ("another firm is not in the answer", 10_000_00),
    ("an old and a new year together", 2_00 + 4_00),
])
def test_the_figure_is_what_the_rule_says_and_not_merely_what_the_two_halves_share(db, name, want):
    deductions, challans = SCENARIOS[name]
    sql, py = _both(db, deductions, challans)
    assert (sql, py) == (want, want), name


# A boundary moved by a day only shifts tax BETWEEN quarter groups, and in a total that cancels unless a challan sits on one side of
# it. So each date below is a deduction with a challan for exactly its own quarter and year (nothing outstanding), and the same date
# with a challan of the neighbouring quarter or year (everything outstanding).
BOUNDARIES = [
    ("2026-04-01", "2026-27", "Q1", "2025-26", "Q4"), ("2026-06-30", "2026-27", "Q1", "2026-27", "Q2"),
    ("2026-07-01", "2026-27", "Q2", "2026-27", "Q1"), ("2026-09-30", "2026-27", "Q2", "2026-27", "Q3"),
    ("2026-10-01", "2026-27", "Q3", "2026-27", "Q2"), ("2026-12-31", "2026-27", "Q3", "2026-27", "Q4"),
    ("2027-01-01", "2026-27", "Q4", "2026-27", "Q3"), ("2027-03-31", "2026-27", "Q4", "2027-28", "Q1"),
    ("2027-04-01", "2027-28", "Q1", "2026-27", "Q4"),
]


@pytest.mark.parametrize("on,fy,quarter,other_fy,other_quarter", BOUNDARIES)
def test_a_deduction_on_a_boundary_date_is_paid_by_a_challan_of_its_own_quarter_and_year_on_both_halves(
        db, on, fy, quarter, other_fy, other_quarter):
    deductions = [ded(on=on, tds=5_00)]
    own, py_own = _both(db, deductions, [chl(fy=fy, quarter=quarter, tds=5_00)])
    assert (own, py_own) == (0, 0), (on, fy, quarter)
    _psql(db, "DELETE FROM tds_challans; DELETE FROM tds_deductions; DELETE FROM clients; DELETE FROM firms;")
    neighbour, py_neighbour = _both(db, deductions, [chl(fy=other_fy, quarter=other_quarter, tds=5_00)])
    assert (neighbour, py_neighbour) == (5_00, 5_00), (on, other_fy, other_quarter)


# ── The registry, key by key ───────────────────────────────────────────────────

def test_every_section_the_registry_holds_is_grouped_the_same_way_by_both_halves(db):
    """The SQL strips a trailing bracketed limb; Python asks `section_rates.parent_of`, which reads the registry. They agree on
    every key of both years, which is what the SQL comment claims: a deduction under any key is paid by a challan typed with its
    parent, and is NOT paid by one typed with another section."""
    deductions, challans = [], []
    for fy, rates in sorted(section_rates.TDS_RATES_BY_FY.items()):
        year = int(fy[:4])
        for key in sorted(rates.sections):
            deductions.append(ded(section=key, on=f"{year}-05-10", tds=1_00 + len(deductions)))
            # pay half of the keys by their parent, the rest not at all
            if len(deductions) % 2 == 0:
                challans.append(chl(section=section_rates.parent_of(key, fy), fy=fy, tds=1_00 + len(deductions) - 1, quarter="Q1"))
    assert len(deductions) >= 40, "the registry shrank or this loop went blind"
    sql, py = _both(db, deductions, challans)
    assert sql == py
    assert sql > 0


def test_a_challan_typed_with_another_section_pays_nothing_on_both_halves(db):
    sql, py = _both(db, [ded(section="194J(B)")], [chl(section="194C")])
    assert (sql, py) == (10_000_00, 10_000_00)


# ── Who may ask ────────────────────────────────────────────────────────────────

def _seed_caller(dsn: str, auth: str, user: str, firm: str, role: str = "Partner") -> None:
    r = _psql(dsn, f"""
        INSERT INTO auth.users (id) VALUES ('{auth}') ON CONFLICT DO NOTHING;
        INSERT INTO users (id, firm_id, full_name, email, role, auth_user_id)
          VALUES ('{user}','{firm}','P','{user[:8]}@parity.in','{role}','{auth}');""")
    assert r.returncode == 0, r.stderr


def _as(dsn: str, auth: str, firm: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        BEGIN;
        SET LOCAL ROLE authenticated;
        SET LOCAL request.jwt.claims = '{{"sub":"{auth}"}}';
        SELECT public.tds_undeposited_paise('{firm}'::uuid, NULL::uuid[]);
        COMMIT;""", tuples=True)


def _figure(proc: subprocess.CompletedProcess) -> int:
    assert proc.returncode == 0, proc.stderr
    lines = [l.strip() for l in proc.stdout.split("\n") if l.strip().lstrip("-").isdigit()]
    assert len(lines) == 1, proc.stdout
    return int(lines[0])


def test_it_runs_as_the_caller_so_row_security_still_applies(db):
    """SECURITY INVOKER: a signed-in partner of another firm who passes THIS firm's id reads none of its rows, and this firm's own
    partner reads what the service role reads. The function states no firm check of its own; the policies are the lock."""
    deductions, challans = SCENARIOS["short challan"]
    assert _psql(db, _seed_sql(deductions, challans)).returncode == 0
    _seed_caller(db, AUTH, USER, FIRM)
    _seed_caller(db, AUTH_OTHER, USER_OTHER, OTHER_FIRM)
    assert _sql(db) == 4_000_00
    assert _figure(_as(db, AUTH, FIRM)) == 4_000_00
    assert _figure(_as(db, AUTH_OTHER, FIRM)) == 0


def test_it_is_security_invoker_and_read_only(db):
    r = _psql(db, """
        SELECT p.prosecdef, p.provolatile FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname='public' AND p.proname='tds_undeposited_paise';""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f|s"


def test_anon_and_public_cannot_execute_it_and_the_service_and_signed_in_roles_can(db):
    for role, want in (("anon", "f"), ("authenticated", "t"), ("service_role", "t")):
        r = _psql(db, f"SELECT has_function_privilege('{role}', 'public.tds_undeposited_paise(uuid,uuid[])', 'EXECUTE');",
                  tuples=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == want, role
    r = _psql(db, """
        SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace,
             LATERAL aclexplode(p.proacl) a
        WHERE n.nspname='public' AND p.proname='tds_undeposited_paise' AND a.grantee = 0;""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0", "PUBLIC holds EXECUTE"


def test_anon_cannot_execute_it_even_where_the_platform_grants_new_functions_to_anon(db):
    """Supabase's default privileges give `anon` EXECUTE on every function created in `public`; the template database does not,
    so the plain check above cannot tell whether the migration's own REVOKE FROM anon is doing anything. Here the platform's
    default is switched on, the function is dropped and the migration applied again."""
    path = API_ROOT / "migrations" / "522_tds_deducted_and_not_yet_deposited_from_the_challan_register.sql"
    assert _psql(db, "DROP FUNCTION public.tds_undeposited_paise(uuid, uuid[]);"
                     " ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon;").returncode == 0
    assert _psql(db, path.read_text(encoding="utf-8")).returncode == 0
    r = _psql(db, "SELECT has_function_privilege('anon', 'public.tds_undeposited_paise(uuid,uuid[])', 'EXECUTE');", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f"


def test_the_rollback_drops_the_function(db):
    path = API_ROOT / "migrations" / "522_tds_deducted_and_not_yet_deposited_from_the_challan_register_rollback.sql"
    assert _psql(db, path.read_text(encoding="utf-8")).returncode == 0
    r = _psql(db, "SELECT count(*) FROM pg_proc WHERE proname='tds_undeposited_paise';", tuples=True)
    assert r.stdout.strip() == "0"
