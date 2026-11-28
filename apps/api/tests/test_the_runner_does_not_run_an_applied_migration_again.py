"""The migration runner does not run a migration again because its bytes changed after it applied (ledger POST-A-584).

WHAT WAS WRONG
    `apply_migrations.run` fed psql every file whose checksum was not the one recorded for it. For a file that FAILED that is the
    retry: the fix has a new checksum. For a file that APPLIED it is a second run of old SQL over a database every later migration
    has changed. On 27-11-2026 a rename sweep rewrote the comments of eight applied migrations and the next push to main ran six
    of them again in production, which put the ledger posting function back to its September body (POST-A-583; migration 786
    repaired it). `tests/test_an_applied_migration_is_never_edited.py` stops such an edit before it merges. This is the second
    lock, in the runner, for the edit that gets through anyway.

WHAT THIS HOLDS, WITHOUT A DATABASE (the runner against tests/_fake_psql.py, which records how psql was called)
    * a file recorded as applied at another checksum is NOT handed to psql, is named in `changed_after_apply`, on stderr and in
      the JSON, and the run is not ok; the command exits 1 and, under Actions, an error annotation names the file;
    * the run continues past it: a new migration behind it still applies;
    * putting the file back makes the next run green with nothing run;
    * one named file can be run again on purpose (`--reapply-changed`), which records its new checksum, and naming one file
      does not let another through;
    * a file that applied, was edited and would now FAIL (442 and 443 on that day) is this case and not a failure: it is not
      run and nothing is remembered as failed;
    * a file that FAILED keeps the old rule: its fix has a new checksum and runs.
    Every test here fails against the runner as it was, where the edited file is run.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests import _fake_psql

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"


def _load():
    spec = importlib.util.spec_from_file_location("apply_migrations_for_the_changed_file_tests", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apply_migrations_for_the_changed_file_tests"] = mod        # @dataclass resolves its module by name
    spec.loader.exec_module(mod)
    return mod


am = _load()

FIRST = "CREATE TABLE a (id int);\n"
EDITED = "-- a renamed test, in a comment\nCREATE TABLE a (id int);\n"        # nothing the database would see differs


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


def _runs_of(env, name: str) -> int:
    """How many times psql was handed this migration (its tracking INSERT names the file)."""
    return sum(1 for c in _fake_psql.read(env)["calls"] if "-f" in c["argv"] and f"('{name}'" in (c["stdin"] or ""))


@pytest.fixture()
def applied_then_edited(env, tmp_path):
    d = _dir(tmp_path, {"900_a.sql": FIRST})
    assert am.run(None, migrations_dir=d).applied == ["900_a.sql"]
    recorded = _fake_psql.read(env)["applied"]["900_a.sql"]
    (d / "900_a.sql").write_text(EDITED)
    return d, recorded


def test_a_file_edited_after_it_applied_is_not_run_and_the_run_is_red(env, applied_then_edited, capsys):
    d, recorded = applied_then_edited
    report = am.run(None, migrations_dir=d)
    assert report.changed_after_apply == ["900_a.sql"] and report.applied == [] and report.failed == []
    assert not report.ok
    assert _runs_of(env, "900_a.sql") == 1, "the edited file was handed to psql a second time"
    assert _fake_psql.read(env)["applied"]["900_a.sql"] == recorded, "the recorded checksum moved without a run"
    said = capsys.readouterr().err
    assert "NOT running 900_a.sql again" in said and "never edited" in said and "--reapply-changed 900_a.sql" in said


def test_the_run_continues_past_it_and_a_new_migration_still_applies(env, applied_then_edited):
    d, _ = applied_then_edited
    (d / "901_new.sql").write_text("CREATE TABLE b (id int);\n")
    report = am.run(None, migrations_dir=d)
    assert report.applied == ["901_new.sql"] and report.changed_after_apply == ["900_a.sql"] and not report.ok
    # ... and it stays red on the next run too, the way a remembered failure does
    again = am.run(None, migrations_dir=d)
    assert again.applied == [] and again.changed_after_apply == ["900_a.sql"] and not again.ok


def test_putting_the_file_back_is_the_remedy(env, applied_then_edited):
    d, _ = applied_then_edited
    assert not am.run(None, migrations_dir=d).ok
    (d / "900_a.sql").write_text(FIRST)
    report = am.run(None, migrations_dir=d)
    assert report.ok and report.skipped_already == ["900_a.sql"] and report.changed_after_apply == []
    assert _runs_of(env, "900_a.sql") == 1


def test_one_named_file_can_be_run_again_on_purpose_and_its_new_checksum_is_recorded(env, applied_then_edited):
    d, recorded = applied_then_edited
    report = am.run(None, migrations_dir=d, reapply_changed=frozenset({"900_a.sql"}))
    assert report.ok and report.applied == ["900_a.sql"] and report.changed_after_apply == []
    assert _runs_of(env, "900_a.sql") == 2
    assert _fake_psql.read(env)["applied"]["900_a.sql"] != recorded
    after = am.run(None, migrations_dir=d)
    assert after.ok and after.skipped_already == ["900_a.sql"]


def test_naming_one_file_does_not_let_another_through(env, tmp_path):
    d = _dir(tmp_path, {"900_a.sql": FIRST, "901_b.sql": "CREATE TABLE b (id int);\n"})
    am.run(None, migrations_dir=d)
    (d / "900_a.sql").write_text(EDITED)
    (d / "901_b.sql").write_text("-- edited too\nCREATE TABLE b (id int);\n")
    report = am.run(None, migrations_dir=d, reapply_changed=frozenset({"900_a.sql"}))
    assert report.applied == ["900_a.sql"] and report.changed_after_apply == ["901_b.sql"] and not report.ok
    assert _runs_of(env, "901_b.sql") == 1


def test_an_applied_file_edited_into_one_that_would_fail_is_not_run_and_not_remembered_as_a_failure(env, tmp_path):
    """442 and 443 on 27-11-2026: applied in September, edited, and their second run failed on a policy that already existed."""
    d = _dir(tmp_path, {"900_a.sql": FIRST})
    am.run(None, migrations_dir=d)
    (d / "900_a.sql").write_text("FAIL_HERE;\n")
    report = am.run(None, migrations_dir=d, continue_on_error=True)
    assert report.changed_after_apply == ["900_a.sql"] and report.failed == [] and report.skipped_failed_before == []
    assert _fake_psql.read(env)["failed"] == {} and _runs_of(env, "900_a.sql") == 1


def test_an_applied_file_with_a_failure_remembered_at_its_edited_bytes_is_still_not_run(env, tmp_path):
    """Production on 28-11-2026 held exactly this for 442 and 443: applied at one checksum, a failure remembered at another.
    The file is the edited one in both runs; neither a retry flag nor the memory of the failure may run it."""
    d = _dir(tmp_path, {"900_a.sql": FIRST})
    am.run(None, migrations_dir=d)
    (d / "900_a.sql").write_text("FAIL_HERE;\n")
    state = _fake_psql.read(env)
    state["failed"]["900_a.sql"] = {"checksum": am.discover_migrations(d)[0].checksum(), "attempts": 1}
    Path(env["FAKE_PSQL_STATE"]).write_text(json.dumps(state))
    for retry in (False, True):
        report = am.run(None, migrations_dir=d, retry_failed=retry, continue_on_error=True)
        assert report.changed_after_apply == ["900_a.sql"] and report.failed == [] and not report.ok
    assert _runs_of(env, "900_a.sql") == 1


def test_a_file_that_failed_keeps_the_old_rule_its_fix_runs(env, tmp_path):
    d = _dir(tmp_path, {"900_bad.sql": "FAIL_HERE;\n"})
    assert not am.run(None, migrations_dir=d, continue_on_error=True).ok
    (d / "900_bad.sql").write_text("CREATE TABLE fixed (id int);\n")
    report = am.run(None, migrations_dir=d)
    assert report.ok and report.applied == ["900_bad.sql"] and report.changed_after_apply == []


def test_a_first_run_and_a_dry_run_are_unchanged(env, tmp_path):
    d = _dir(tmp_path, {"900_a.sql": FIRST, "901_b.sql": "CREATE TABLE b (id int);\n"})
    dry = am.run(None, migrations_dir=d, dry_run=True)
    assert dry.applied == ["900_a.sql", "901_b.sql"] and dry.changed_after_apply == [] and dry.ok
    first = am.run(None, migrations_dir=d)
    assert first.ok and first.applied == ["900_a.sql", "901_b.sql"] and first.changed_after_apply == []


def test_the_command_exits_1_names_the_file_in_the_json_and_takes_the_flag(env, applied_then_edited, capsys):
    d, _ = applied_then_edited
    assert am.main(["--migrations-dir", str(d), "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["changed_after_apply"] == ["900_a.sql"] and doc["ok"] is False and doc["applied"] == []
    assert am.main(["--migrations-dir", str(d)]) == 1
    assert "EDITED AFTER IT APPLIED, NOT RUN AGAIN 900_a.sql" in capsys.readouterr().out
    assert am.main(["--migrations-dir", str(d), "--json", "--reapply-changed", "900_a.sql"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["applied"] == ["900_a.sql"] and doc["changed_after_apply"] == [] and doc["ok"] is True


def test_under_actions_an_error_annotation_names_the_file_and_stdout_stays_json(env, applied_then_edited, monkeypatch, capsys):
    d, _ = applied_then_edited
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    am.main(["--migrations-dir", str(d), "--json"])
    out = capsys.readouterr()
    assert "::error title=An applied migration was edited and was NOT run again::900_a.sql" in out.err
    assert "::error" not in out.out and json.loads(out.out)["ok"] is False
