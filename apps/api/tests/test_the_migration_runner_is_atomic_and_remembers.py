"""A migration applies whole or not at all, and a failure the runner remembers keeps the pipeline red (ops-16).

THE TWO DEFECTS
    1. `apply_migrations` ran psql with ON_ERROR_STOP but not --single-transaction,
       so a file that failed on its third statement had already COMMITTED the first
       two. The runner's own docstring records this for migration 055. On the live
       database that is a half-applied change that stays, because a failure is
       remembered and not retried.
    2. `RunReport.ok` was `not failed`. A failure remembered from an earlier run is
       reported in `skipped_failed_before`, which `ok` ignored, so after one red run
       the NEXT push skipped the broken file, applied the rest and exited 0 -- the
       change still unapplied in production and the pipeline green.

WHAT THIS PINS, WITHOUT A DATABASE
    The runner is driven against tests/_fake_psql.py, which records how psql was
    CALLED and models what a real one does about a transaction. The real-Postgres
    half -- that the server really rolls the file back -- is
    tests/test_a_migration_is_atomic_pg.py and runs where HARNESS_PG is set.

    And the scanner that decides whether a file may be wrapped is checked against
    every real migration, with an independent line-start regular expression as the
    cross-check, because a lexer that is wrong in the lenient direction wraps a
    file that carries its own COMMIT and ends the transaction early.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from tests import _fake_psql

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"


def _load():
    spec = importlib.util.spec_from_file_location("apply_migrations_under_test", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apply_migrations_under_test"] = mod        # @dataclass resolves its module by name
    spec.loader.exec_module(mod)
    return mod


am = _load()


# ── the scanner ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "CREATE TABLE a (id int);\nINSERT INTO a VALUES (1);\n",
    # A plpgsql body is full of BEGIN ... END; and none of it is transaction control.
    "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$\nBEGIN\n  PERFORM 1;\nEND;\n$$;\n",
    "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $body$ BEGIN COMMIT; END; $body$;",
    "DO $$ BEGIN PERFORM 1; END $$;",
    # The words inside a string, an identifier or a comment are not statements.
    "INSERT INTO log(msg) VALUES ('BEGIN; COMMIT;');",
    "INSERT INTO log(msg) VALUES (E'it''s \\'; COMMIT; --');",
    'CREATE TABLE "begin;commit;" (id int);',
    "-- BEGIN;\n-- COMMIT;\nCREATE TABLE a (id int);",
    "/* BEGIN; /* nested COMMIT; */ still a comment COMMIT; */\nCREATE TABLE a (id int);",
    # The word is a prefix of something else.
    "CREATE TABLE ended (id int);\nSELECT 1 AS beginning;",
    "COMMENT ON TABLE a IS 'COMMIT;';",
])
def test_a_plain_file_is_wrapped(sql):
    plan = am.transaction_plan("900_plain.sql", sql)
    assert plan.wrap, plan.reason


@pytest.mark.parametrize("sql, why", [
    ("BEGIN;\nCREATE TABLE a (id int);\nCOMMIT;\n", "own transaction"),
    ("begin;\nCREATE TABLE a (id int);\ncommit;\n", "own transaction"),
    ("BEGIN TRANSACTION;\nCREATE TABLE a (id int);\nEND;\n", "own transaction"),
    ("START TRANSACTION;\nCREATE TABLE a (id int);\nCOMMIT;\n", "own transaction"),
    ("CREATE TABLE a (id int);\nCOMMIT;\n", "own transaction"),
    ("CREATE TABLE a (id int);\nROLLBACK;\n", "own transaction"),
    ("CREATE TABLE a (id int);\nCREATE INDEX CONCURRENTLY a_i ON a (id);\n", "CONCURRENTLY"),
    ("DROP INDEX CONCURRENTLY IF EXISTS a_i;\n", "CONCURRENTLY"),
    ("VACUUM a;\n", "refuses inside a transaction"),
    ("ALTER TYPE mood ADD VALUE 'ok';\n", "ADD VALUE"),
    ("CREATE FUNCTION f() RETURNS int LANGUAGE sql BEGIN ATOMIC SELECT 1; END;\n", "BEGIN ATOMIC"),
    ("-- migration: no-transaction - a DO block commits in batches\nDO $$ BEGIN PERFORM 1; END $$;\n",
     "no-transaction"),
])
def test_a_file_that_cannot_or_should_not_be_wrapped_says_why(sql, why):
    plan = am.transaction_plan("900_x.sql", sql)
    assert not plan.wrap
    assert why in plan.reason, plan.reason


def test_a_marker_in_a_comment_is_the_opt_out_and_nothing_else_is():
    sql = "-- migration: no-transaction\nCREATE TABLE a (id int);\n"
    assert not am.transaction_plan("900_x.sql", sql).wrap
    # a mention that is not the marker line
    assert am.transaction_plan("900_x.sql", "-- we do not use a no-transaction marker here\nSELECT 1;").wrap


def test_the_words_inside_a_dollar_quote_do_not_hide_a_real_statement_after_it():
    sql = "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN NULL; END; $$;\nCOMMIT;\n"
    assert not am.transaction_plan("900_x.sql", sql).wrap


def test_a_positional_parameter_is_not_a_dollar_quote():
    sql = "PREPARE p AS SELECT $1, $2;\nCOMMIT;\n"
    assert not am.transaction_plan("900_x.sql", sql).wrap


# ── the scanner against every real migration ───────────────────────────────────

_FORWARD = [p for p in sorted(MIGRATIONS.glob("*.sql")) if "rollback" not in p.name and not p.name.startswith("_")]
_OWN_TX_LINE = re.compile(r"^[ \t]*(BEGIN|COMMIT|ROLLBACK|START[ \t]+TRANSACTION)([ \t]+(TRANSACTION|WORK))?[ \t]*;", re.I | re.M)


def test_the_scan_found_the_migrations():
    assert len(_FORWARD) > 400, "the glob found almost nothing - this test would pass over an empty set"


def test_the_scanner_and_an_independent_line_search_agree_on_which_files_run_their_own_transaction():
    """The lexer strips strings, comments and function bodies; a line-start regex does not. They must give the
    same answer on every file, once the baseline files (classified by name before any scan) are set aside."""
    disagree = []
    for path in _FORWARD:
        if path.name in am.BASELINE_FAILURES:
            continue
        text = path.read_text(encoding="utf-8")
        plan = am.transaction_plan(path.name, text)
        scanner_says_own = (not plan.wrap) and "own transaction" in plan.reason
        # A line-start BEGIN; / COMMIT; inside a $$ body would make this fire without a real statement, so the
        # cross-check only has to hold in one direction strictly and in the other for files that are not bodies.
        line_says_own = bool(_OWN_TX_LINE.search(text))
        if scanner_says_own and not line_says_own:
            disagree.append((path.name, "scanner sees transaction control the lines do not"))
        if line_says_own and not scanner_says_own and plan.wrap:
            disagree.append((path.name, "a line-start BEGIN/COMMIT the scanner wrapped around"))
    assert not disagree, disagree


def test_no_existing_migration_needs_the_marker_or_trips_a_hazard():
    """Every forward file is run by the runner as one of three things: wrapped, own transaction, or a baseline
    failure. If a fourth reason appears for an EXISTING file, wrapping would have changed a migration that
    production already applied - which is the thing this change must not do."""
    reasons = {}
    for path in _FORWARD:
        plan = am.transaction_plan(path.name, path.read_text(encoding="utf-8"))
        if not plan.wrap:
            reasons.setdefault(plan.reason, []).append(path.name)
    assert set(reasons) <= {
        "a baseline failure keeps its legacy partial-apply behaviour",
        "it carries its own transaction control (BEGIN/COMMIT)",
    }, {r: names[:3] for r, names in reasons.items()}


def test_the_count_of_files_that_run_their_own_transaction_is_what_the_grep_said():
    own = [p.name for p in _FORWARD
           if "own transaction" in am.transaction_plan(p.name, p.read_text(encoding="utf-8")).reason]
    baseline_own = [n for n in am.BASELINE_FAILURES
                    if _OWN_TX_LINE.search((MIGRATIONS / n).read_text(encoding="utf-8"))]
    # Counted 1-10-2026: 109 files carry a line-start BEGIN;/COMMIT;. Some baseline files are among them and are
    # classified by NAME first, so the two sets overlap and the union is what the grep counted.
    assert len(set(own) | set(baseline_own)) >= 100
    assert len(own) >= 90


# ── the baseline ───────────────────────────────────────────────────────────────

# Frozen, and it may only SHRINK. Written out here rather than imported so that adding a name to the runner's
# set cannot also move this ceiling.
_THE_TEN = {
    "008_linter_fixes.sql", "045_assignment_rules.sql", "053_hardening.sql",
    "054_v13_payroll_assets_banking.sql", "055_v131_hardening.sql", "068_workflow_engine.sql",
    "070_ai_memory.sql", "071_rls_policies.sql", "095_grant_reconciliation.sql",
    "144_security_search_path_and_rls.sql",
}


def test_the_baseline_may_only_shrink():
    assert set(am.BASELINE_FAILURES) <= _THE_TEN, (
        f"a name was ADDED to BASELINE_FAILURES: {sorted(set(am.BASELINE_FAILURES) - _THE_TEN)}. A file that "
        "fails is a defect to fix, not a debt to take on.")


def test_the_runners_baseline_is_the_harness_baseline():
    """One list in two places. The harness test (real Postgres) ratchets the actual failures against its own set;
    the runner uses the same names to tolerate a remembered failure and to keep the legacy behaviour."""
    from tests.test_migrations_apply import EXPECTED_MIGRATION_FAILURES
    assert set(am.BASELINE_FAILURES) == set(EXPECTED_MIGRATION_FAILURES)


def test_every_baseline_file_exists():
    for name in am.BASELINE_FAILURES:
        assert (MIGRATIONS / name).is_file(), f"{name} is in the baseline but is not a migration"


# ── the runner, against a psql that records how it was called ──────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = _fake_psql.install(tmp_path / "bin")
    monkeypatch.setenv("PATH", e["PATH"])
    monkeypatch.setenv("FAKE_PSQL_STATE", e["FAKE_PSQL_STATE"])
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return e


def _dir(tmp_path, files: dict) -> Path:
    d = tmp_path / "migrations"
    d.mkdir(exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def _migration_calls(env):
    return [c for c in _fake_psql.read(env)["calls"] if "-f" in c["argv"]]


def test_a_plain_migration_is_applied_in_one_transaction(env, tmp_path):
    d = _dir(tmp_path, {"900_a.sql": "CREATE TABLE a (id int);\n"})
    report = am.run(None, migrations_dir=d)
    assert report.ok and report.applied == ["900_a.sql"]
    (call,) = _migration_calls(env)
    assert "--single-transaction" in call["argv"]
    assert report.not_atomic == {}


def test_a_file_with_its_own_begin_is_not_wrapped_a_second_time(env, tmp_path):
    d = _dir(tmp_path, {"900_own.sql": "BEGIN;\nCREATE TABLE a (id int);\nCOMMIT;\n"})
    report = am.run(None, migrations_dir=d)
    assert report.ok
    (call,) = _migration_calls(env)
    assert "--single-transaction" not in call["argv"]
    assert "own transaction" in report.not_atomic["900_own.sql"]


def test_a_file_that_fails_on_its_third_statement_leaves_nothing_behind(env, tmp_path):
    """The headline. Without the wrapper the first two statements are committed."""
    d = _dir(tmp_path, {"900_bad.sql": "CREATE TABLE one (id int);\nINSERT INTO one VALUES (1);\nFAIL_HERE;\n"})
    report = am.run(None, migrations_dir=d)
    assert not report.ok and [f["file"] for f in report.failed] == ["900_bad.sql"]
    state = _fake_psql.read(env)
    assert state["committed"] == [], f"a failed migration left {state['committed']} behind"
    assert "900_bad.sql" not in state["applied"]
    assert "900_bad.sql" in state["failed"], "the failure must be remembered"


def test_a_baseline_file_keeps_the_legacy_partial_apply(env, tmp_path):
    """The ten are exempt BY NAME, because the rest of the schema build was written against what they leave."""
    d = _dir(tmp_path, {"055_v131_hardening.sql": "CREATE TABLE one (id int);\nINSERT INTO one VALUES (1);\nFAIL_HERE;\n"})
    report = am.run(None, migrations_dir=d)
    assert [f["file"] for f in report.failed] == ["055_v131_hardening.sql"]
    state = _fake_psql.read(env)
    assert state["committed"] == ["CREATE TABLE one (id int)", "INSERT INTO one VALUES (1)"]
    (call,) = _migration_calls(env)
    assert "--single-transaction" not in call["argv"]


def test_the_second_run_over_the_same_broken_file_fails_and_does_not_retry_it(env, tmp_path, capsys):
    d = _dir(tmp_path, {"900_bad.sql": "CREATE TABLE one (id int);\nFAIL_HERE;\n"})
    first = am.run(None, migrations_dir=d, continue_on_error=True)
    assert not first.ok
    second = am.run(None, migrations_dir=d, continue_on_error=True)
    assert second.skipped_failed_before == ["900_bad.sql"]
    assert second.failed == [], "a remembered failure is not retried"
    assert second.unresolved_failures == ["900_bad.sql"]
    assert not second.ok, "a second run that skips a broken file and exits 0 is the defect"
    assert _fake_psql.read(env)["failed"]["900_bad.sql"]["attempts"] == 1
    assert "FAILS" in capsys.readouterr().err


def test_the_cli_exit_code_is_non_zero_for_a_remembered_failure(env, tmp_path):
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    assert am.main(["--migrations-dir", str(d)]) == 1                 # the run that fails
    assert am.main(["--migrations-dir", str(d)]) == 1                 # the NEXT push: skipped, still red


def test_a_remembered_failure_does_not_stop_a_later_migration_applying(env, tmp_path):
    """Red, not blocked: stopping would hold every later migration hostage to one broken file."""
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    am.run(None, migrations_dir=d, continue_on_error=True)
    (d / "901_good.sql").write_text("CREATE TABLE good (id int);\n")
    report = am.run(None, migrations_dir=d)
    assert report.applied == ["901_good.sql"] and report.skipped_failed_before == ["900_bad.sql"]
    assert not report.ok


def test_a_remembered_baseline_failure_does_not_turn_the_pipeline_red(env, tmp_path):
    d = _dir(tmp_path, {"008_linter_fixes.sql": "FAIL_HERE;\n"})
    am.run(None, migrations_dir=d, continue_on_error=True)
    again = am.run(None, migrations_dir=d)
    assert again.skipped_failed_before == ["008_linter_fixes.sql"]
    assert again.unresolved_failures == []
    assert again.ok, "the ten are tolerated by name; production must not start failing on them"


def test_editing_the_broken_file_runs_it_again_and_clears_the_memory(env, tmp_path):
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    am.run(None, migrations_dir=d, continue_on_error=True)
    (d / "900_bad.sql").write_text("CREATE TABLE fixed (id int);\n")
    report = am.run(None, migrations_dir=d)
    assert report.ok and report.applied == ["900_bad.sql"]
    assert _fake_psql.read(env)["failed"] == {}


def test_retry_failed_attempts_a_remembered_failure_once_more(env, tmp_path):
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    am.run(None, migrations_dir=d, continue_on_error=True)
    report = am.run(None, migrations_dir=d, retry_failed=True, continue_on_error=True)
    assert [f["file"] for f in report.failed] == ["900_bad.sql"]
    assert _fake_psql.read(env)["failed"]["900_bad.sql"]["attempts"] == 2


def test_an_error_annotation_names_the_file_under_actions_and_goes_to_stderr(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    am.main(["--migrations-dir", str(d), "--json"])
    am.main(["--migrations-dir", str(d), "--json"])                    # the remembered one
    out = capsys.readouterr()
    assert out.err.count("::error title=Migration failed::") == 1
    assert "::error title=Migration failed earlier and is still unapplied::" in out.err
    assert "900_bad.sql" in out.err
    # stdout is the JSON document and nothing else, or the harness cannot parse it.
    assert "::error" not in out.out
    docs = out.out.replace("}\n{", "}\x00{").split("\x00")
    assert [json.loads(d)["ok"] for d in docs] == [False, False]
    assert json.loads(docs[1])["unresolved_failures"] == ["900_bad.sql"]


def test_no_annotation_outside_actions(env, tmp_path, capsys):
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    am.main(["--migrations-dir", str(d)])
    assert "::error" not in capsys.readouterr().err


def test_a_dry_run_says_how_each_file_would_run(env, tmp_path):
    d = _dir(tmp_path, {
        "900_plain.sql": "CREATE TABLE a (id int);\n",
        "901_own.sql": "BEGIN;\nCREATE TABLE b (id int);\nCOMMIT;\n",
        "902_marked.sql": "-- migration: no-transaction - a DO block\nSELECT 1;\n",
    })
    report = am.run(None, migrations_dir=d, dry_run=True)
    assert sorted(report.not_atomic) == ["901_own.sql", "902_marked.sql"]


def test_the_annotation_text_cannot_end_the_command_early():
    assert "\n" not in am._annotation_text("a\nb\r%")
    assert am._annotation_text("100%") == "100%25"
