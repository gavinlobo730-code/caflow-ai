"""Migration 481 on real PostgreSQL — a workflow template can be archived, and a
starter, a run and a step's task are each made once (POST-A-200, POST-A-204;
schema only).

WHAT IS PROVEN HERE
    * the four new columns exist, are NULLABLE with NO DEFAULT, and the migration
      rewrites no row that already exists (checked by the row's own contents and
      by its transaction id, which an UPDATE would move);
    * `starter_key` is unique per firm and a firm-made template (NULL) never
      collides; archiving does not free a starter's key; the key may not be blank
      or padded; and `ON CONFLICT (firm_id, starter_key) DO NOTHING` works, which
      is why that index is not partial;
    * the instance index is STATUS-AWARE: two live runs cannot share a key, a
      failed or cancelled run does not hold it (so an explicit retry is possible),
      a completed run does (so the same event is never processed twice), and a
      run with no key is outside it;
    * a step makes its task once per run, soft-deleted tasks included, and one
      firm's task cannot take another firm's slot;
    * deleting a run leaves its tasks and clears the link;
    * the migration REFUSES, naming the count, a database that already holds
      duplicate live keys, and changes nothing when it does;
    * a signed-in browser session can still create a task (no required field);
    * the file applies twice and the rollback removes everything, refusing while
      any of the four columns holds a value.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM1 = "81000000-0000-0000-0000-0000000000f1"
FIRM2 = "81000000-0000-0000-0000-0000000000f2"
CLIENT1 = "81000000-0000-0000-0000-0000000000c1"
CLIENT2 = "81000000-0000-0000-0000-0000000000c2"
PARTNER_ID = "81000000-0000-0000-0000-00000000b001"
PARTNER_AUTH = "81000000-0000-0000-0000-00000000a001"

_MIGRATIONS = os.path.join(os.path.dirname(__file__), "..", "migrations")
_STEM = "481_a_workflow_can_be_archived_and_its_starter_run_and_task_are_made_once"
_FILE = os.path.join(_MIGRATIONS, f"{_STEM}.sql")
_ROLLBACK = os.path.join(_MIGRATIONS, f"{_STEM}_rollback.sql")


def _run(dsn: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-X", "-q", *args],
                          capture_output=True, text=True)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return _run(dsn, "-c", sql)


def _file(dsn: str, path: str) -> subprocess.CompletedProcess:
    return _run(dsn, "-f", path)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, f"{sql}\n{r.stderr}"


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, "-tA", "-c", sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _refused(dsn: str, sql: str, *needles: str) -> subprocess.CompletedProcess:
    """The statement fails, and says every needle (a SQLSTATE, an index name)."""
    r = _psql(dsn, sql)
    assert r.returncode != 0, f"expected a refusal, but this was accepted:\n{sql}"
    for needle in needles:
        assert needle in r.stderr, f"{needle!r} not in:\n{r.stderr}"
    return r


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m481_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'p@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM1}', 'F1', 'f1@t.in'), ('{FIRM2}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
              VALUES ('{PARTNER_ID}', '{FIRM1}', '{PARTNER_AUTH}', 'p@t.in', 'Partner', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
              VALUES ('{CLIENT1}', '{FIRM1}', 'C1', 'Private Limited', 'AAACA1234A'),
                     ('{CLIENT2}', '{FIRM2}', 'C2', 'Private Limited', 'AAACB1234B');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ─── helpers that make the rows the tests are about ─────────────────────────

def _template(dsn: str, firm: str = FIRM1, *, starter_key: str | None = None, name: str = "T",
              before_481: bool = False) -> str:
    if before_481:     # the table as it stood: no starter_key column to name
        return _scalar(dsn, f"INSERT INTO workflow_templates (firm_id, name, trigger_type) "
                            f"VALUES ('{firm}', '{name}', 'manual') RETURNING id")
    key = "NULL" if starter_key is None else f"'{starter_key}'"
    return _scalar(dsn, f"INSERT INTO workflow_templates (firm_id, name, trigger_type, starter_key) "
                        f"VALUES ('{firm}', '{name}', 'manual', {key}) RETURNING id")


def _run_row(dsn: str, template: str, firm: str = FIRM1, *, key: str | None = "K1", status: str = "pending") -> str:
    k = "NULL" if key is None else f"'{key}'"
    return _scalar(dsn, f"INSERT INTO workflow_instances (firm_id, template_id, trigger_event, idempotency_key, status) "
                        f"VALUES ('{firm}', '{template}', 'manual', {k}, '{status}') RETURNING id")


def _task_sql(firm: str = FIRM1, client: str = CLIENT1, *, run: str | None = None, step: str | None = None,
              title: str = "T") -> str:
    cols, vals = "", ""
    if run is not None:
        cols += ", workflow_instance_id"
        vals += f", '{run}'"
    if step is not None:
        cols += ", workflow_step_ref"
        vals += f", '{step}'"
    return f"INSERT INTO tasks (firm_id, client_id, title{cols}) VALUES ('{firm}', '{client}', '{title}'{vals}) RETURNING id"


# ─── the columns ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,column", [
    ("workflow_templates", "archived_at"),
    ("workflow_templates", "starter_key"),
    ("tasks", "workflow_instance_id"),
    ("tasks", "workflow_step_ref"),
])
def test_each_new_column_is_nullable_with_no_default(db, table, column):
    row = _scalar(db, f"SELECT is_nullable || '|' || coalesce(column_default, 'none') FROM information_schema.columns "
                      f"WHERE table_schema='public' AND table_name='{table}' AND column_name='{column}'")
    assert row == "YES|none", (f"{table}.{column} must be nullable with no default: NULL is 'this is not a starter', "
                               f"'this is not archived', 'no run made this' — never a value nobody chose. Got {row!r}")


def test_a_template_task_and_run_made_the_old_way_carry_none_of_it(db):
    t = _template(db)
    _run_row(db, t, key=None)
    _ok(db, _task_sql())
    assert _scalar(db, "SELECT count(*) FROM workflow_templates WHERE archived_at IS NOT NULL "
                       "OR starter_key IS NOT NULL") == "0"
    assert _scalar(db, "SELECT count(*) FROM tasks WHERE workflow_instance_id IS NOT NULL "
                       "OR workflow_step_ref IS NOT NULL") == "0"


# ─── the migration rewrites nothing that exists ─────────────────────────────

_OLD_COLUMNS = {
    "workflow_templates": "id, firm_id, name, description, category, trigger_type, trigger_config, conditions, "
                          "is_active, is_system, version, execution_count, success_count, failure_count, "
                          "created_at, updated_at",
    "workflow_instances": "id, firm_id, template_id, client_id, trigger_event, trigger_data, status, current_step_id, "
                          "context_data, idempotency_key, started_at, completed_at, failed_at, error_message, "
                          "created_at, updated_at",
    "tasks": "id, firm_id, client_id, title, description, status, priority, due_date, estimated_minutes, "
             "workflow_id, workflow_step_id, created_at, updated_at",
}


def _fingerprint(dsn: str) -> dict[str, str]:
    """For each table: a digest of every pre-481 column of every row, AND the
    transaction id that last wrote each row. An UPDATE — even one that sets a
    column to the value it already had — moves xmin, so equality of both is the
    measured meaning of 'no row was rewritten'."""
    out = {}
    for table, cols in _OLD_COLUMNS.items():
        out[table] = _scalar(
            dsn,
            f"SELECT count(*) || '|' || coalesce(md5(string_agg(t::text || xmin::text, ',' ORDER BY id)), 'empty') "
            f"FROM (SELECT {cols}, xmin FROM public.{table}) t")
    return out


def test_it_rewrites_no_existing_row_and_gives_none_a_value(db):
    """Roll 481 back on the clone, put rows in the tables as they stood before it
    (live and ended runs sharing a key among them), apply it, and compare."""
    assert _file(db, _ROLLBACK).returncode == 0
    t1 = _template(db, before_481=True)
    t2 = _template(db, FIRM2, name="T2", before_481=True)
    _run_row(db, t1, key="dup", status="failed")
    _run_row(db, t1, key="dup", status="cancelled")
    _run_row(db, t1, key="dup", status="running")      # one live run beside ended ones is legal
    _run_row(db, t1, key=None, status="pending")
    _run_row(db, t1, key=None, status="pending")        # keyless rows may repeat
    _run_row(db, t2, FIRM2, key="dup", status="completed")
    run = _run_row(db, t1, key="solo", status="completed")
    _ok(db, _task_sql(title="a"))
    _ok(db, _task_sql(FIRM2, CLIENT2, title="b"))
    before = _fingerprint(db)
    assert all(not v.startswith("0|") for v in before.values()), before

    r = _file(db, _FILE)
    assert r.returncode == 0, r.stderr

    assert _fingerprint(db) == before, "the migration changed (or re-wrote) a row that already existed"
    assert _scalar(db, "SELECT count(*) FROM workflow_templates WHERE archived_at IS NOT NULL "
                       "OR starter_key IS NOT NULL") == "0"
    assert _scalar(db, "SELECT count(*) FROM tasks WHERE workflow_instance_id IS NOT NULL "
                       "OR workflow_step_ref IS NOT NULL") == "0"
    assert run  # the completed run still holds its key afterwards
    _refused(db, f"INSERT INTO workflow_instances (firm_id, template_id, trigger_event, idempotency_key, status) "
                 f"VALUES ('{FIRM1}', '{t1}', 'manual', 'solo', 'pending')", "23505", "uq_wf_instances_live_idempotency")


def test_it_applies_twice(db):
    assert _file(db, _FILE).returncode == 0
    assert _file(db, _FILE).returncode == 0
    for index in ("uq_wf_templates_firm_starter_key", "uq_wf_instances_live_idempotency", "uq_tasks_workflow_step_once"):
        assert _scalar(db, f"SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname='{index}'") == "1"


# ─── a starter is installed once per firm ───────────────────────────────────

def test_a_starter_is_installed_once_per_firm(db):
    _template(db, FIRM1, starter_key="gst_monthly")
    _refused(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type, starter_key) "
                 f"VALUES ('{FIRM1}', 'again', 'manual', 'gst_monthly')", "23505", "uq_wf_templates_firm_starter_key")


def test_two_firms_may_each_install_the_same_starter(db):
    _template(db, FIRM1, starter_key="gst_monthly")
    _template(db, FIRM2, starter_key="gst_monthly")
    assert _scalar(db, "SELECT count(*) FROM workflow_templates WHERE starter_key = 'gst_monthly'") == "2"


def test_a_firm_makes_as_many_templates_of_its_own_as_it_likes(db):
    """NULL is 'not a starter' and NULLs are distinct in a unique index."""
    for i in range(3):
        _template(db, FIRM1, name=f"mine {i}")
    assert _scalar(db, f"SELECT count(*) FROM workflow_templates WHERE firm_id='{FIRM1}' AND starter_key IS NULL") == "3"


def test_archiving_a_starter_does_not_free_its_key(db):
    """Restoring it is the way back; installing the six again must not make a second GST filing beside it."""
    t = _template(db, FIRM1, starter_key="gst_monthly")
    _ok(db, f"UPDATE workflow_templates SET archived_at = now(), is_active = false WHERE id = '{t}'")
    _refused(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type, starter_key) "
                 f"VALUES ('{FIRM1}', 'again', 'manual', 'gst_monthly')", "23505", "uq_wf_templates_firm_starter_key")


def test_the_installer_may_upsert_and_ignore_duplicates(db):
    """The reason the index is not partial: PostgREST's ignore-duplicates upsert is
    `ON CONFLICT (firm_id, starter_key) DO NOTHING`, which Postgres accepts only
    against an index it can infer WITHOUT a predicate."""
    _template(db, FIRM1, starter_key="gst_monthly")
    _ok(db, f"""INSERT INTO workflow_templates (firm_id, name, trigger_type, starter_key) VALUES
                  ('{FIRM1}', 'a', 'manual', 'gst_monthly'), ('{FIRM1}', 'b', 'manual', 'itr')
                ON CONFLICT (firm_id, starter_key) DO NOTHING""")
    assert _scalar(db, f"SELECT count(*) FROM workflow_templates WHERE firm_id='{FIRM1}' AND starter_key IS NOT NULL") == "2"
    assert _scalar(db, "SELECT name FROM workflow_templates WHERE starter_key = 'gst_monthly'") == "T"


@pytest.mark.parametrize("bad", ["", " ", " gst", "gst ", "x" * 101])
def test_a_blank_padded_or_overlong_starter_key_is_refused(db, bad):
    _refused(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type, starter_key) "
                 f"VALUES ('{FIRM1}', 'x', 'manual', '{bad}')", "23514", "workflow_templates_starter_key_check")


def test_the_longest_allowed_starter_key_is_accepted(db):
    _template(db, FIRM1, starter_key="x" * 100)


def test_a_template_can_be_archived_and_restored(db):
    t = _template(db)
    _ok(db, f"UPDATE workflow_templates SET archived_at = now() WHERE id = '{t}'")
    assert _scalar(db, f"SELECT archived_at IS NOT NULL FROM workflow_templates WHERE id = '{t}'") == "t"
    _ok(db, f"UPDATE workflow_templates SET archived_at = NULL WHERE id = '{t}'")
    assert _scalar(db, f"SELECT archived_at IS NULL FROM workflow_templates WHERE id = '{t}'") == "t"


def test_an_archived_template_that_has_run_is_still_not_deletable_so_archive_exists(db):
    """The reason for the column: DELETE of a template with a run is an FK error, not a 500 to be handled."""
    t = _template(db)
    _run_row(db, t, key=None)
    _refused(db, f"DELETE FROM workflow_templates WHERE id = '{t}'", "23503", "workflow_instances_template_id_fkey")


# ─── a run is started once ──────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["pending", "running", "waiting_approval", "completed", "waiting", "anything_new"])
def test_a_live_or_finished_run_holds_its_key(db, status):
    """Only 'failed' and 'cancelled' release a key. A status word added later holds it: the safe direction."""
    t = _template(db)
    _run_row(db, t, status=status)
    _refused(db, f"INSERT INTO workflow_instances (firm_id, template_id, trigger_event, idempotency_key, status) "
                 f"VALUES ('{FIRM1}', '{t}', 'manual', 'K1', 'pending')", "23505", "uq_wf_instances_live_idempotency")


@pytest.mark.parametrize("ended", ["failed", "cancelled"])
def test_a_failed_or_cancelled_run_does_not_hold_its_key(db, ended):
    """So the explicit retry — a new run with the same key — is possible, and is not a silent re-fire."""
    t = _template(db)
    _run_row(db, t, status=ended)
    retry = _run_row(db, t, status="pending")
    assert retry
    assert _scalar(db, f"SELECT count(*) FROM workflow_instances WHERE template_id='{t}' AND idempotency_key='K1'") == "2"


def test_many_ended_runs_may_share_a_key_beside_one_live_one(db):
    t = _template(db)
    for status in ("failed", "failed", "cancelled", "cancelled", "failed"):
        _run_row(db, t, status=status)
    _run_row(db, t, status="running")
    assert _scalar(db, f"SELECT count(*) FROM workflow_instances WHERE template_id='{t}'") == "6"


def test_putting_a_failed_run_back_in_play_is_refused_while_another_run_holds_the_key(db):
    """The one way the index can bite a retry: flipping the SAME failed row back to pending."""
    t = _template(db)
    failed = _run_row(db, t, status="failed")
    _run_row(db, t, status="running")
    _refused(db, f"UPDATE workflow_instances SET status = 'pending' WHERE id = '{failed}'",
             "23505", "uq_wf_instances_live_idempotency")


def test_a_failed_run_goes_back_in_play_when_nothing_else_holds_the_key(db):
    t = _template(db)
    failed = _run_row(db, t, status="failed")
    _ok(db, f"UPDATE workflow_instances SET status = 'pending' WHERE id = '{failed}'")


def test_a_run_with_no_key_is_outside_the_index(db):
    t = _template(db)
    for _ in range(3):
        _run_row(db, t, key=None)
    assert _scalar(db, f"SELECT count(*) FROM workflow_instances WHERE template_id='{t}'") == "3"


def test_the_key_is_per_firm_and_per_template(db):
    t1, t1b, t2 = _template(db, name="a"), _template(db, name="b"), _template(db, FIRM2, name="c")
    _run_row(db, t1, key="same")
    _run_row(db, t1b, key="same")            # another template of the same firm
    _run_row(db, t2, FIRM2, key="same")      # another firm
    assert _scalar(db, "SELECT count(*) FROM workflow_instances WHERE idempotency_key = 'same'") == "3"


def test_the_instance_index_is_not_an_on_conflict_arbiter_so_the_code_reads_23505(db):
    """Documents why the header says a duplicate start is read from SQLSTATE 23505: a PARTIAL
    index cannot be named in ON CONFLICT without its predicate, and PostgREST cannot send one."""
    t = _template(db)
    _refused(db, f"INSERT INTO workflow_instances (firm_id, template_id, trigger_event, idempotency_key) "
                 f"VALUES ('{FIRM1}', '{t}', 'manual', 'K9') "
                 f"ON CONFLICT (firm_id, template_id, idempotency_key) DO NOTHING", "42P10")


def test_the_instance_index_is_what_the_header_says_it_is(db):
    definition = _scalar(db, "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_wf_instances_live_idempotency'")
    assert definition.startswith("CREATE UNIQUE INDEX")
    assert "(firm_id, template_id, idempotency_key)" in definition
    assert "idempotency_key IS NOT NULL" in definition
    assert "'failed'" in definition and "'cancelled'" in definition
    assert "'completed'" not in definition, "a completed run must keep its key"


# ─── the migration refuses a database that already holds duplicates ─────────

def test_it_refuses_duplicate_live_keys_by_name_and_changes_nothing(db):
    assert _file(db, _ROLLBACK).returncode == 0
    t = _template(db, before_481=True)
    _run_row(db, t, key="dup", status="running")
    _run_row(db, t, key="dup", status="pending")
    _run_row(db, t, key="fine", status="running")
    before = _fingerprint(db)

    r = _file(db, _FILE)
    assert r.returncode != 0
    assert "migration 481" in r.stderr and "1 (firm, template, idempotency key)" in r.stderr, r.stderr
    assert "Nothing was changed" in r.stderr

    # all-or-nothing: the columns it would have added are not there, and no row moved
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='workflow_templates' "
                       "AND column_name IN ('archived_at', 'starter_key')") == "0"
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='tasks' "
                       "AND column_name IN ('workflow_instance_id', 'workflow_step_ref')") == "0"
    assert _fingerprint(db) == before

    # a person decides which run keeps the key; then it applies
    _ok(db, "UPDATE workflow_instances SET idempotency_key = NULL "
            "WHERE idempotency_key = 'dup' AND status = 'pending'")
    r = _file(db, _FILE)
    assert r.returncode == 0, r.stderr


def test_duplicates_among_ended_runs_do_not_stop_it(db):
    assert _file(db, _ROLLBACK).returncode == 0
    t = _template(db, before_481=True)
    for status in ("failed", "failed", "cancelled"):
        _run_row(db, t, key="dup", status=status)
    r = _file(db, _FILE)
    assert r.returncode == 0, r.stderr


# ─── a step makes its task once per run ─────────────────────────────────────

def test_a_step_makes_one_task_per_run(db):
    run = _run_row(db, _template(db), key=None)
    _ok(db, _task_sql(run=run, step="collect-documents"))
    _refused(db, _task_sql(run=run, step="collect-documents", title="again"), "23505", "uq_tasks_workflow_step_once")


def test_a_run_makes_a_task_for_each_of_its_steps(db):
    run = _run_row(db, _template(db), key=None)
    for step in ("collect-documents", "prepare", "ca-review"):
        _ok(db, _task_sql(run=run, step=step))
    assert _scalar(db, f"SELECT count(*) FROM tasks WHERE workflow_instance_id = '{run}'") == "3"


def test_the_same_step_of_another_run_is_another_task(db):
    t = _template(db)
    r1, r2 = _run_row(db, t, key="a"), _run_row(db, t, key="b")
    _ok(db, _task_sql(run=r1, step="prepare"))
    _ok(db, _task_sql(run=r2, step="prepare"))


def test_a_soft_deleted_task_still_holds_its_slot(db):
    """So a retry after somebody deleted the task finds it, instead of re-creating work a person removed."""
    run = _run_row(db, _template(db), key=None)
    task = _scalar(db, _task_sql(run=run, step="prepare"))
    _ok(db, f"UPDATE tasks SET deleted_at = now() WHERE id = '{task}'")
    _refused(db, _task_sql(run=run, step="prepare"), "23505", "uq_tasks_workflow_step_once")


def test_another_firms_task_cannot_take_this_firms_slot(db):
    """The key leads with the TASK's own firm: a row naming a run that is not its own firm's
    lands in its own firm's key space and collides with nothing."""
    run = _run_row(db, _template(db), key=None)
    _ok(db, _task_sql(FIRM2, CLIENT2, run=run, step="prepare", title="foreign"))
    _ok(db, _task_sql(FIRM1, CLIENT1, run=run, step="prepare", title="own"))


def test_a_task_naming_a_run_but_no_step_is_not_constrained(db):
    run = _run_row(db, _template(db), key=None)
    _ok(db, _task_sql(run=run))
    _ok(db, _task_sql(run=run))


def test_a_task_naming_a_step_but_no_run_is_not_constrained(db):
    _ok(db, _task_sql(step="prepare"))
    _ok(db, _task_sql(step="prepare"))


def test_a_task_naming_a_run_that_does_not_exist_is_refused(db):
    _refused(db, _task_sql(run=str(uuid.uuid4()), step="prepare"), "23503", "tasks_workflow_instance_id_fkey")


@pytest.mark.parametrize("bad", ["", " ", " prepare", "prepare ", "x" * 201])
def test_a_blank_padded_or_overlong_step_ref_is_refused(db, bad):
    run = _run_row(db, _template(db), key=None)
    _refused(db, _task_sql(run=run, step=bad), "23514", "tasks_workflow_step_ref_check")


def test_deleting_a_run_keeps_its_tasks_and_clears_the_link(db):
    """ON DELETE SET NULL: removing a run never removes, nor blocks on, the work it created."""
    run = _run_row(db, _template(db), key=None)
    task = _scalar(db, _task_sql(run=run, step="prepare"))
    _ok(db, f"DELETE FROM workflow_instances WHERE id = '{run}'")
    assert _scalar(db, f"SELECT workflow_instance_id IS NULL FROM tasks WHERE id = '{task}'") == "t"
    assert _scalar(db, f"SELECT workflow_step_ref FROM tasks WHERE id = '{task}'") == "prepare"
    # and the slot is free again for a run that is made afterwards
    _ok(db, _task_sql(run=_run_row(db, _template(db, name="n"), key=None), step="prepare"))


def test_a_template_edit_does_not_have_to_touch_a_task(db):
    """workflow_step_ref is text, not a foreign key to workflow_steps: the edit that deletes and
    re-inserts a template's steps is not blocked by a task that names one."""
    t = _template(db)
    run = _run_row(db, t, key=None)
    step = _scalar(db, f"INSERT INTO workflow_steps (template_id, step_order, step_type, name) "
                       f"VALUES ('{t}', 1, 'action', 's') RETURNING id")
    _ok(db, _task_sql(run=run, step=step))
    _ok(db, f"DELETE FROM workflow_steps WHERE template_id = '{t}'")
    assert _scalar(db, f"SELECT count(*) FROM tasks WHERE workflow_step_ref = '{step}'") == "1"


def test_a_signed_in_session_can_still_create_a_task_without_the_link_and_read_it_back(db):
    """No required field was added: the browser's own `createTask` insert names neither column."""
    claims = f"SET request.jwt.claims = '{{\"sub\": \"{PARTNER_AUTH}\"}}'; SET ROLE authenticated; "
    r = _psql(db, claims + f"INSERT INTO tasks (firm_id, client_id, title) VALUES ('{FIRM1}', '{CLIENT1}', 'browser');")
    assert r.returncode == 0, r.stderr
    seen = _scalar(db, claims + "SELECT count(*) FROM tasks WHERE title = 'browser' AND workflow_instance_id IS NULL "
                                "AND workflow_step_ref IS NULL")
    assert seen == "1"


# ─── the rollback ───────────────────────────────────────────────────────────

def test_the_rollback_removes_everything_and_it_can_be_re_applied(db):
    r = _file(db, _ROLLBACK)
    assert r.returncode == 0, r.stderr
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE "
                       "(table_name='workflow_templates' AND column_name IN ('archived_at','starter_key')) OR "
                       "(table_name='tasks' AND column_name IN ('workflow_instance_id','workflow_step_ref'))") == "0"
    assert _scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname IN ('uq_wf_templates_firm_starter_key', "
                       "'uq_wf_instances_live_idempotency', 'uq_tasks_workflow_step_once')") == "0"
    assert _scalar(db, "SELECT count(*) FROM pg_constraint WHERE conname IN ('workflow_templates_starter_key_check', "
                       "'tasks_workflow_step_ref_check', 'tasks_workflow_instance_id_fkey')") == "0"
    assert _file(db, _ROLLBACK).returncode == 0, "and rolling back twice is harmless"
    assert _file(db, _FILE).returncode == 0, "and it can be re-applied after a rollback"


def test_the_rollback_leaves_the_older_indexes_alone(db):
    assert _file(db, _ROLLBACK).returncode == 0
    assert _scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname IN ('idx_wf_instances_idem', "
                       "'idx_wf_templates_active', 'idx_tasks_workflow')") == "3"


@pytest.mark.parametrize("what,setup,named", [
    ("an archived template", lambda d: _ok(d, f"UPDATE workflow_templates SET archived_at = now() WHERE id = '{_template(d)}'"),
     "1 archived template"),
    ("an installed starter", lambda d: _template(d, starter_key="gst_monthly"), "1 installed starter"),
    ("a task naming its run", lambda d: _ok(d, _task_sql(run=_run_row(d, _template(d), key=None)).replace(" RETURNING id", "")),
     "1 task(s) naming the run"),
    ("a task naming its step", lambda d: _ok(d, _task_sql(step="prepare").replace(" RETURNING id", "")),
     "1 task(s) naming the step"),
])
def test_the_rollback_refuses_while_a_column_holds_a_value(db, what, setup, named):
    setup(db)
    r = _file(db, _ROLLBACK)
    assert r.returncode != 0, f"rolled back over {what}"
    assert "Refusing to roll back 481" in r.stderr and named in r.stderr, r.stderr
    # and it left everything in place
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='tasks' "
                       "AND column_name IN ('workflow_instance_id', 'workflow_step_ref')") == "2"
    assert _scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_wf_instances_live_idempotency'") == "1"


def test_the_rollback_works_once_the_values_are_cleared(db):
    t = _template(db, starter_key="gst_monthly")
    _ok(db, f"UPDATE workflow_templates SET archived_at = now() WHERE id = '{t}'")
    assert _file(db, _ROLLBACK).returncode != 0
    _ok(db, "UPDATE workflow_templates SET starter_key = NULL, archived_at = NULL")
    assert _file(db, _ROLLBACK).returncode == 0
