"""A SECURITY DEFINER function a signed-in user can call, and that takes arguments, must ask who is calling.

WHY THIS IS A RULE AND NOT A LIST OF EIGHT
    Row security does not run inside a function that runs as its owner. Migration 486 closed eight functions that
    were executable by every signed-in user and checked nothing about their arguments (one of them took the table
    to write to as a parameter), after migration 272 had closed only the published `anon` key and called the rest
    "the next piece of work". The access matrix could not see them: it tries table writes, and these are function
    calls. Naming the eight would pass forever the moment they were fixed; this asserts the SHAPE, so the next
    migration that creates such a function without a guard fails the build.

THE RULE
    For every function in `public` that is SECURITY DEFINER, is not a trigger, has at least one parameter and is
    executable by `authenticated`: its body must reference a caller check (`assert_caller_acts_for`,
    `get_my_firm_id`, `get_my_role`, `get_my_user_id`, `auth.uid`/`auth.jwt`, `can_access_client`, `my_permission`, `my_role_at_least`) or the
    function is on the frozen list below with the reason. The frozen list only shrinks. A function with no
    parameters is a caller-identity helper (it answers about the caller by construction) and is outside the rule.

WHAT THE LIST IS
    `is_fy_locked` answers a yes/no (has this firm locked this year) for any firm id. Its one caller is the period
    validator, on the caller's own sign-in and failing closed in about sixty-seven places, and it was not traced for
    every kind of caller, so it is left and recorded (ledger POST-A-221). It leaks one bit.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the definer-function shape proof requires HARNESS_PG + psql",
)

#: FROZEN. Only shrinks. name -> why it is allowed to take arguments and ask nobody.
UNGUARDED = {
    # DECIDED 17-10-2026 (POST-A-221): stays. A guard that answers false for a firm that is not the caller's would answer
    # "open" for a portal contact or an employee about their OWN firm (no `users` row, so get_my_firm_id() is NULL), which
    # is worse than the one bit it closes; the id of the firm asked about must already be known to the caller.
    "is_fy_locked": "one bit (has this firm locked this year); one caller, on the caller's own sign-in, fail-closed",
}

CALLER_CHECKS = re.compile(
    r"assert_caller_acts_for|get_my_firm_id|get_my_role|get_my_user_id|staff_session_is_live|auth\.uid|auth\.jwt"
    r"|can_access_client|my_permission|my_role_at_least",
    re.I)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-F", "\x1f", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\x1f") for line in r.stdout.splitlines() if line]


@pytest.fixture(scope="module")
def functions(pg_template):
    dsn = f"{_ADMIN.strip()} dbname={pg_template.name}"
    return _rows(dsn, """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid), p.pronargs::text,
               replace(p.prosrc, E'\\n', ' ')
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.prosecdef
           AND p.prorettype <> 'trigger'::regtype
           AND has_function_privilege('authenticated', p.oid, 'EXECUTE')
         ORDER BY 1, 2;""")


def test_the_scan_finds_the_definer_functions_at_all(functions):
    names = {f[0] for f in functions}
    assert len(functions) >= 25, f"only {len(functions)} functions found: the scan stopped seeing them"
    for must in ("post_journal_atomic", "settle_receipt_atomic", "numbered_document_atomic",
                 "assert_caller_acts_for", "get_my_firm_id"):
        assert must in names, must


def test_every_definer_function_with_arguments_that_a_signed_in_user_can_call_asks_who_is_calling(functions):
    unguarded = sorted(f"{name}({args})" for name, args, nargs, body in functions
                       if int(nargs) > 0 and not CALLER_CHECKS.search(body) and name not in UNGUARDED)
    assert not unguarded, (
        "these functions run as their owner (row security does not apply inside them), take arguments, are "
        "executable by every signed-in user and never ask who is calling: " + ", ".join(unguarded) + ". Rename the "
        "function to <name>__unguarded, take EXECUTE from authenticated and create a wrapper that calls "
        "public.assert_caller_acts_for (migration 486 is the pattern), or revoke EXECUTE from authenticated.")


def test_the_frozen_list_only_names_functions_that_still_exist_and_still_need_it(functions):
    by_name = {f[0]: f for f in functions}
    for name in UNGUARDED:
        assert name in by_name, f"{name} is on the frozen list but is no longer an authenticated-callable definer function: delete the line"
        assert not CALLER_CHECKS.search(by_name[name][3]), f"{name} now asks who is calling: delete it from the frozen list"


def test_the_guard_would_have_caught_the_hole(functions):
    """The negative control, on the rule rather than on a database: the body of the function as it stood before
    migration 486 (no caller check anywhere) fails the same pattern the real functions are held to."""
    old_numbered = "DECLARE v_keys text; v_row RECORD; BEGIN SELECT string_agg(quote_ident(k), ', ') INTO v_keys FROM jsonb_object_keys(p_header) AS k; EXECUTE format('INSERT INTO public.%1$I (%2$s) ...', p_header_table, v_keys); RETURN to_jsonb(v_row); END"
    assert not CALLER_CHECKS.search(old_numbered)
