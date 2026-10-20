"""Migration 526, its rollback and the guard snapshot's second fold describe one expression (mock-mode companion of the _pg module).

The rewrite writes `COALESCE(<c>::text IS NULL OR (SELECT get_my_role()) = 'Partner' OR <c>::text IN (SELECT
my_assigned_client_ids()), false)` in place of `can_access_client((<c>)::text)`; the rollback recognises exactly what Postgres
deparses it to and writes the call back; the guard snapshot folds the same deparsed text back to the call before hashing, so
the production snapshot (which holds the call) does not read the rewrite as drift. Three regular expressions over one
shape: if one is edited and the others are not, the guard reports drift in 221 policies or the rollback silently does
nothing. The real-Postgres module proves them against the database; this holds that they name the same pieces.
"""
import re
from pathlib import Path

from scripts.db.guard_snapshot import GUARD_SQL

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION = next(p for p in MIGRATIONS.glob("526_the_assignment_scope_reads_the_callers_clients_once_per_query*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("526_the_assignment_scope_reads_the_callers_clients_once_per_query*_rollback.sql"))

#: What Postgres deparses a policy written by 526 to (copied from a migrated database), and what the fold must make of it.
DEPARSED = ("COALESCE((((client_id)::text IS NULL) OR (( SELECT get_my_role() AS get_my_role) = 'Partner'::text) OR "
            "((client_id)::text IN ( SELECT my_assigned_client_ids() AS my_assigned_client_ids))), false)")


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("--"))


def test_the_rollback_recognises_what_postgres_deparses_the_rewrite_to_and_writes_the_call_back():
    literal = re.search(r"pat constant text := '(.*)';", _code(ROLLBACK)).group(1).replace("''", "'")
    got = re.sub(literal, r"can_access_client((\1)::text)", DEPARSED)
    assert got == "can_access_client((client_id)::text)", got
    qualified = DEPARSED.replace("(client_id)::text", "(e.client_id)::text")
    assert re.sub(literal, r"can_access_client((\1)::text)", qualified) == "can_access_client((e.client_id)::text)"


def test_the_guard_snapshots_second_fold_maps_the_folded_deparse_back_to_the_call():
    # the second regexp_replace's pattern, taken from the SQL text (a Python string with single backslashes by now)
    found = re.findall(r"'(COALESCE\\\(.*?false\\\))',\s*'can_access_client\(\(\\1\)::text\)'", GUARD_SQL, re.S)
    assert len(found) == 1, "the guard snapshot carries no fold for the assignment-scope rewrite"
    pattern = found[0].replace("''", "'")
    first_fold_applied = DEPARSED.replace("( SELECT get_my_role() AS get_my_role)", "get_my_role()")
    assert re.sub(pattern, r"can_access_client((\1)::text)", first_fold_applied) == "can_access_client((client_id)::text)"
    composite = "(" + first_fold_applied + " OR (id IN ( SELECT my_payroll_run_ids() AS my_payroll_run_ids)))"
    assert re.sub(pattern, r"can_access_client((\1)::text)", composite) == (
        "(can_access_client((client_id)::text) OR (id IN ( SELECT my_payroll_run_ids() AS my_payroll_run_ids)))")


def test_the_rewrite_keeps_the_functions_three_branches_and_its_never_null_answer():
    code = _code(MIGRATION)
    rep = re.search(r"rep constant text := '(.*)';", code).group(1).replace("''", "'")
    assert rep.startswith("COALESCE(") and rep.endswith(", false)"), "the answer must stay a plain true or false, as the function's was"
    for piece in (r"\1)::text IS NULL", "(SELECT public.get_my_role()) = 'Partner'::text", r"(\1)::text IN (SELECT public.my_assigned_client_ids())"):
        assert piece in rep, f"the rewrite lost a branch of can_access_client: {piece}"
    assert "ALTER POLICY" in code and "DROP POLICY" not in code and "CREATE POLICY" not in code
    assert "RAISE EXCEPTION" in code, "the migration does not check its own work"
    assert "ns.nspname = 'public'" in code, "the storage schema belongs to the Storage service"


def test_the_helper_is_a_definer_function_with_no_argument_and_every_role_may_call_it():
    """Executable by anon too, on purpose: an RLS predicate helper (migration 337's class) sits in policies with no TO
    clause, and a role without EXECUTE gets a permission error out of what was a quiet denial. The real-Postgres module
    scans every table for that; this holds the migration's text to it."""
    code = _code(MIGRATION)
    assert "FUNCTION public.my_assigned_client_ids()" in code and "SECURITY DEFINER" in code
    assert "GRANT EXECUTE ON FUNCTION public.my_assigned_client_ids() TO PUBLIC, anon, authenticated;" in code
    assert not re.search(r"REVOKE\s+EXECUTE\s+ON\s+FUNCTION\s+public\.my_assigned_client_ids", code, re.I), (
        "revoking the helper from anon makes an anonymous read of 44 tables a permission error instead of no rows")
    assert "public.get_my_user_id()" in code, "the helper must answer nothing for a member who is no longer live"
