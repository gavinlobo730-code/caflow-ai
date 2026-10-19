"""
Migrations 522 and 523 — the SQL "TDS deducted and not yet deposited" and "not recorded" must equal the Python twin, exactly.

MIGRATION 523 SPLIT THE ANSWER IN TWO. 522 counted every quarter, so a client with NO challan recorded (a firm that keeps its deposits
in Tally) showed all of its tax as undeposited. `public.tds_deposit_position` returns the shortfall in quarters for which at least one
non-salary challan is recorded, and, apart, the tax deducted in quarters for which none is (NOT RECORDED: the books cannot say).
Every figure below is therefore a PAIR, and `tds_undeposited_paise` is held equal to the pair's first.

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
import re
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
from domain.tds.undeposited import position  # noqa: E402

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


def _scope_arg(client_ids) -> str:
    if client_ids is None:
        return "NULL::uuid[]"
    if not client_ids:
        return "ARRAY[]::uuid[]"
    return "ARRAY[" + ",".join(f"'{c}'" for c in client_ids) + "]::uuid[]"


def _sql(dsn: str, client_ids=None, firm: str = FIRM) -> tuple[int, int]:
    r = _psql(dsn, f"SELECT undeposited_paise, not_recorded_paise FROM public.tds_deposit_position('{firm}'::uuid, "
                   f"{_scope_arg(client_ids)});", tuples=True)
    assert r.returncode == 0, f"tds_deposit_position failed: {r.stderr}"
    a, b = r.stdout.strip().split("|")
    return int(a), int(b)


def _wrapper(dsn: str, client_ids=None, firm: str = FIRM) -> int:
    r = _psql(dsn, f"SELECT public.tds_undeposited_paise('{firm}'::uuid, {_scope_arg(client_ids)});", tuples=True)
    assert r.returncode == 0, f"tds_undeposited_paise failed: {r.stderr}"
    return int(r.stdout.strip())


#: The clients each firm has in the seeded `clients` table. `p_client_ids` NULL means THESE in the SQL (`clients WHERE firm_id = ...`),
#: not "every client named by a row": the foreign keys name the client id only, so a row stamped with this firm that names another
#: firm's client is possible, and the SQL leaves it out. The twin is handed the same set so that case is held too.
FIRMS_CLIENTS = {FIRM: [A, B], OTHER_FIRM: [OTHER_FIRMS_CLIENT]}


def _python(deductions: list, challans: list, client_ids=None, firm: str = FIRM) -> tuple[int, int]:
    if client_ids is None:
        client_ids = FIRMS_CLIENTS.get(firm, [])
    return tuple(position([d for d in deductions if d["firm_id"] == firm], [c for c in challans if c["firm_id"] == firm],
                          client_ids=client_ids))


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
    "a challan of another section records the quarter": ([ded(section="194C")], [chl(section="194J", tds=1_00)]),
    "a salary challan does not record the quarter": ([ded()], [chl(section="192")]),
    "a nil challan records the quarter": ([ded()], [chl(tds=0)]),
    "a deduction stamped with this firm that names another firm's client is outside the firm's clients": (
        [ded(client=OTHER_FIRMS_CLIENT, tds=70_00), ded(tds=1_00)], [chl(client=OTHER_FIRMS_CLIENT, tds=70_00)]),
    "each quarter and client is judged by its own challans": (
        [ded(client=A, on="2026-05-10", tds=10_00), ded(client=A, on="2026-08-10", tds=20_00),
         ded(client=A, on="2027-05-10", tds=40_00), ded(client=B, on="2026-05-10", tds=80_00)],
        [chl(client=A, tds=3_00)]),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_gives_the_same_answer_on_both_halves(db, name):
    deductions, challans = SCENARIOS[name]
    sql, py = _both(db, deductions, challans)
    assert sql == py, name


@pytest.mark.parametrize("scope,want", [
    (None, (0, 20_00)), ([A], (0, 0)), ([B], (0, 20_00)), ([A, B], (0, 20_00)), ([], (0, 0)), ([OTHER_FIRMS_CLIENT], (0, 0))])
def test_the_clients_asked_for_decide_the_answer_the_same_way_on_both_halves(db, scope, want):
    """None is every client of the firm, a list is those clients, an EMPTY list is nobody. A's tax is paid by its challan; B has no
    challan recorded for its quarter, so its tax is NOT RECORDED."""
    deductions, challans = SCENARIOS["two clients and a challan of one"]
    sql, py = _both(db, deductions, challans, client_ids=scope)
    assert (sql, py) == (want, want)
    assert _wrapper(db, client_ids=scope) == want[0]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_wrapper_the_previous_api_calls_is_the_first_figure_for_every_scenario(db, name):
    """The migration applies before the API that calls the new function is deployed; the previous API calls the old name."""
    deductions, challans = SCENARIOS[name]
    sql, _ = _both(db, deductions, challans)
    assert _wrapper(db) == sql[0], name


# Two halves that agree on a wrong answer pass a parity test, so these are the figures the RULE gives: (undeposited, not recorded).
@pytest.mark.parametrize("name,want", [
    ("nothing at all", (0, 0)),
    ("no challan", (0, 10_000_00)), ("paid in full", (0, 0)), ("short challan", (4_000_00, 0)), ("surplus challan", (0, 0)),
    ("surplus does not carry to another section or quarter", (7_500_00, 3_000_00)),
    ("other quarter and other year", (0, 10_000_00)),
    ("boundaries: 31 March, 1 April, 30 June, 1 July", (3_00 + 16_00 + 64_00 + 128_00, 0)),
    ("parent section typed on the challan", (200_00, 0)),
    ("surcharge and cess", (440_00, 0)),
    ("salary is in neither side", (0, 1_00)),
    ("a negative row neither pays nor owes", (4_00, 0)),
    ("a salary challan pays no deduction, even one typed 192(1)", (0, 7_00)),
    ("blank section on both sides", (10_000_00 + 1_00, 0)),
    ("a challan typed with surrounding whitespace and a lower-case limb still pays", (0, 0)),
    ("an unknown section is grouped by its bracket-stripped text", (0, 0)),
    ("empty brackets, nested brackets and a space before the bracket", (6_00, 0)),
    ("a non-breaking space is part of the text, a tab and a newline are not", (10_000_00, 0)),
    ("case and surrounding spaces", (600_00, 0)),
    ("two clients and a challan of one", (0, 20_00)),
    ("another firm's deduction carrying this client's id owes nothing here", (0, 1_00)),
    ("another firm's challan carrying this client's id pays nothing", (0, 10_000_00)),
    ("another firm is not in the answer", (0, 10_000_00)),
    ("an old and a new year together", (2_00 + 4_00, 0)),
    ("a challan of another section records the quarter", (10_000_00, 0)),
    ("a salary challan does not record the quarter", (0, 10_000_00)),
    ("a nil challan records the quarter", (10_000_00, 0)),
    ("a deduction stamped with this firm that names another firm's client is outside the firm's clients", (0, 1_00)),
    ("each quarter and client is judged by its own challans", (7_00, 20_00 + 40_00 + 80_00)),
])
def test_the_figures_are_what_the_rule_says_and_not_merely_what_the_two_halves_share(db, name, want):
    deductions, challans = SCENARIOS[name]
    sql, py = _both(db, deductions, challans)
    assert (sql, py) == (want, want), name


def test_every_scenario_has_a_figure_the_rule_gives():
    """The table above is not allowed to fall behind the scenarios: a scenario added without its expected pair would pass on parity
    alone, and two halves that agree on a wrong answer are the failure this file exists for."""
    import re
    src = Path(__file__).read_text(encoding="utf-8")
    named = set(re.findall(r'\("([^"]+)", \(\d', src))
    assert set(SCENARIOS) <= named, sorted(set(SCENARIOS) - named)


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
    assert (own, py_own) == ((0, 0), (0, 0)), (on, fy, quarter)
    _psql(db, "DELETE FROM tds_challans; DELETE FROM tds_deductions; DELETE FROM clients; DELETE FROM firms;")
    # A challan of the neighbouring quarter or year neither pays the deduction nor records its quarter: NOT RECORDED.
    neighbour, py_neighbour = _both(db, deductions, [chl(fy=other_fy, quarter=other_quarter, tds=5_00)])
    assert (neighbour, py_neighbour) == ((0, 5_00), (0, 5_00)), (on, other_fy, other_quarter)


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
    assert sql[0] > 0 and sql[1] == 0, "every year here has a challan, so no quarter is unrecorded"


def test_a_challan_typed_with_another_section_pays_nothing_and_records_the_quarter_on_both_halves(db):
    sql, py = _both(db, [ded(section="194J(B)")], [chl(section="194C")])
    assert (sql, py) == ((10_000_00, 0), (10_000_00, 0))


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
        SELECT undeposited_paise, not_recorded_paise FROM public.tds_deposit_position('{firm}'::uuid, NULL::uuid[]);
        COMMIT;""", tuples=True)


def _figure(proc: subprocess.CompletedProcess) -> tuple[int, int]:
    assert proc.returncode == 0, proc.stderr
    lines = [l.strip() for l in proc.stdout.split("\n") if re.fullmatch(r"-?\d+\|-?\d+", l.strip())]
    assert len(lines) == 1, proc.stdout
    a, b = lines[0].split("|")
    return int(a), int(b)


def test_it_runs_as_the_caller_so_row_security_still_applies(db):
    """SECURITY INVOKER: a signed-in partner of another firm who passes THIS firm's id reads none of its rows, and this firm's own
    partner reads what the service role reads. The function states no firm check of its own; the policies are the lock."""
    deductions, challans = SCENARIOS["short challan"]
    assert _psql(db, _seed_sql(deductions, challans)).returncode == 0
    _seed_caller(db, AUTH, USER, FIRM)
    _seed_caller(db, AUTH_OTHER, USER_OTHER, OTHER_FIRM)
    assert _sql(db) == (4_000_00, 0)
    assert _figure(_as(db, AUTH, FIRM)) == (4_000_00, 0)
    assert _figure(_as(db, AUTH_OTHER, FIRM)) == (0, 0)


FUNCTIONS = ("tds_deposit_position", "tds_undeposited_paise")


@pytest.mark.parametrize("name", FUNCTIONS)
def test_it_is_security_invoker_and_read_only(db, name):
    r = _psql(db, f"""
        SELECT p.prosecdef, p.provolatile FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname='public' AND p.proname='{name}';""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f|s"


@pytest.mark.parametrize("name", FUNCTIONS)
def test_anon_and_public_cannot_execute_it_and_the_service_and_signed_in_roles_can(db, name):
    for role, want in (("anon", "f"), ("authenticated", "t"), ("service_role", "t")):
        r = _psql(db, f"SELECT has_function_privilege('{role}', 'public.{name}(uuid,uuid[])', 'EXECUTE');", tuples=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == want, (name, role)
    r = _psql(db, f"""
        SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace,
             LATERAL aclexplode(p.proacl) a
        WHERE n.nspname='public' AND p.proname='{name}' AND a.grantee = 0;""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0", f"PUBLIC holds EXECUTE on {name}"


def test_anon_cannot_execute_either_function_even_where_the_platform_grants_new_functions_to_anon(db):
    """Supabase's default privileges give `anon` EXECUTE on every function created in `public`; the template database does not,
    so the plain check above cannot tell whether the migration's own REVOKE FROM anon is doing anything. Here the platform's
    default is switched on, both functions are dropped and the migration applied again."""
    path = API_ROOT / "migrations" / "523_tds_not_yet_deposited_ignores_a_quarter_with_no_challan_recorded.sql"
    assert _psql(db, "DROP FUNCTION public.tds_undeposited_paise(uuid, uuid[]); DROP FUNCTION public.tds_deposit_position(uuid, uuid[]);"
                     " ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon;").returncode == 0
    assert _psql(db, path.read_text(encoding="utf-8")).returncode == 0
    for name in FUNCTIONS:
        r = _psql(db, f"SELECT has_function_privilege('anon', 'public.{name}(uuid,uuid[])', 'EXECUTE');", tuples=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "f", name


def test_the_rollback_restores_migration_522s_every_quarter_reading_and_drops_the_new_function(db):
    """For fidelity with the previous schema, not for use: the wrapper counts every quarter again, recorded or not."""
    assert _psql(db, _seed_sql(*SCENARIOS["no challan"])).returncode == 0
    assert _wrapper(db) == 0, "migration 523 counts a quarter with no challan recorded as not recorded"
    path = API_ROOT / "migrations" / "523_tds_not_yet_deposited_ignores_a_quarter_with_no_challan_recorded_rollback.sql"
    assert _psql(db, path.read_text(encoding="utf-8")).returncode == 0
    assert _psql(db, "SELECT count(*) FROM pg_proc WHERE proname='tds_deposit_position';", tuples=True).stdout.strip() == "0"
    assert _wrapper(db) == 10_000_00, "the rollback brings back 522's reading: every quarter is counted"
    for role, want in (("anon", "f"), ("authenticated", "t"), ("service_role", "t")):
        r = _psql(db, f"SELECT has_function_privilege('{role}', 'public.tds_undeposited_paise(uuid,uuid[])', 'EXECUTE');", tuples=True)
        assert r.stdout.strip() == want, role
