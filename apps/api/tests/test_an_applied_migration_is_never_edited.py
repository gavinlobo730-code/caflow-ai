"""A migration production has applied is never edited, not even a comment (ledger POST-A-583).

WHAT WAS WRONG
    The runner (`scripts/db/apply_migrations.py`) runs a migration again when the file's checksum is not the one the database
    recorded. That is how a fix to a file that failed is retried, and the deploy document says in three places what it means for
    a file that did NOT fail: never edit it. Nothing held that rule. On 27-11-2026 a sweep that renamed sixty-five test files also
    rewrote the old test names where they stood in the comments of eight migrations (245, 269, 274, 306, 318, 440, 442, 443). The
    next push to main ran six of them a second time on production and failed on two. A second run puts back what a file defined
    and undoes every later change to the same object: production's `post_journal_atomic` went back to migration 274's body (no
    question of who is calling, executable by any signed-in session), `my_portal_client_ids()` lost migration 768's test for a
    deleted client, and four policies lost migration 526's rewrite. Migration 786 is the repair. Every check was green throughout,
    because a database built from the migrations in order never runs one twice.

THE RULE
    Every migration the runner would apply has one line in `tests/fixtures/migration_checksums.txt`, written by
    `scripts/db/freeze_migration_checksums.py` when the migration is new, and the file's checksum (the runner's own: sha256 of its
    bytes) is that line's. A changed file, an unlisted file and a listed file that is gone each fail with a sentence that says
    what to do. The script adds lines and never rewrites one by itself.

WHAT THIS DOES NOT SEE
    Whether a line was re-recorded on purpose (`--replace`): that is a diff a reviewer reads, and the reason the script makes it
    a separate, named act. The runner itself still runs a changed file again; refusing that at the door is ledger POST-A-584.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
SCRIPTS = API_ROOT / "scripts" / "db"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load("apply_migrations")
fz = _load("freeze_migration_checksums")

F786 = MIGRATIONS / "786_the_definitions_a_rerun_of_six_old_migrations_reverted_are_restored.sql"

#: The first twelve characters of what production's own record of applied migrations held on 28-11-2026 (read-only). The six
#: that ran again on 27-11-2026 are recorded there at their NEW bytes, so they stay as they are now: putting their comments
#: back would run them a third time. The two that failed are recorded at their bytes of 29-09-2026, so those were put back.
PRODUCTION_RECORDED = {
    "245_fix_194_grant_regression.sql": "ca9e676d36d8",
    "269_service_role_grant_gap.sql": "15653805f850",
    "274_reversal_stamps_its_original_atomically.sql": "fc003ed5fae9",
    "306_service_role_can_write_the_money_documents.sql": "2a56ad4f7df4",
    "318_status_vocabularies_the_code_and_production_disagree_on.sql": "a764d5e5e957",
    "440_a_portal_client_may_post_their_own_message.sql": "25d934516200",
    "442_a_portal_client_may_read_their_own_fee_scope_link.sql": "e2939e312204",
    "443_a_portal_client_may_read_their_own_fee_documents.sql": "f6d863a58544",
}


# ── the rule, over the real directory ──────────────────────────────────────────────────────────────────────────────────────────

def test_every_migration_matches_its_recorded_checksum():
    wrong = fz.problems(fz.current(), fz.read_manifest())
    assert wrong == [], "\n\n".join(wrong)


def test_the_list_is_not_empty_and_covers_every_file_the_runner_would_apply():
    recorded, applied = fz.read_manifest(), [m.name for m in runner.discover_migrations()]
    assert len(applied) > 600 and set(recorded) == set(applied)
    assert not any("rollback" in n or n.startswith("_") for n in recorded), "a rollback or helper file is never applied, so it is not listed"


def test_the_checksum_is_the_one_the_runner_compares_in_production():
    recorded = fz.read_manifest()
    for mig in runner.discover_migrations()[:5] + runner.discover_migrations()[-5:]:
        assert recorded[mig.name] == mig.checksum() == hashlib.sha256(mig.path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name,prefix", sorted(PRODUCTION_RECORDED.items()))
def test_the_eight_files_of_27_november_are_the_bytes_production_recorded(name, prefix):
    assert fz.read_manifest()[name].startswith(prefix), (
        f"{name} is not the file production recorded. The runner would run it again there on the next push to main.")


# ── the rule bites: each way of breaking it, on a copy ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def copy(tmp_path):
    """Three real migrations and a list frozen from them."""
    src = [m.path for m in runner.discover_migrations()][-3:]
    d = tmp_path / "migrations"
    d.mkdir()
    for p in src:
        shutil.copy(p, d / p.name)
    manifest = tmp_path / "migration_checksums.txt"
    added, wrong = fz.freeze(d, manifest)
    assert len(added) == 3 and wrong == []
    return d, manifest, [p.name for p in src]


def _problems(d: Path, manifest: Path) -> list[str]:
    return fz.problems(fz.current(d), fz.read_manifest(manifest))


def test_one_changed_character_of_a_comment_is_found(copy):
    d, manifest, names = copy
    target = d / names[0]
    text = target.read_text(encoding="utf-8")
    assert "--" in text, "the control needs a comment to edit"
    target.write_text(text.replace("--", "-- ", 1), encoding="utf-8")       # a comment: nothing the database would see
    (found,) = _problems(d, manifest)
    assert names[0] in found and "never edited, not even a comment" in found and "runs a changed file again" in found


def test_freezing_again_does_not_quietly_accept_the_edit(copy):
    d, manifest, names = copy
    before = manifest.read_text(encoding="utf-8")
    (d / names[1]).write_text((d / names[1]).read_text(encoding="utf-8") + "\n-- a late thought\n", encoding="utf-8")
    added, wrong = fz.freeze(d, manifest)
    assert added == [] and len(wrong) == 1 and names[1] in wrong[0]
    assert manifest.read_text(encoding="utf-8") == before, "the script rewrote the line of a file that changed"


def test_a_new_migration_is_named_until_it_is_recorded_and_recording_adds_one_line(copy):
    d, manifest, names = copy
    (d / "999_a_new_one.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (found,) = _problems(d, manifest)
    assert "999_a_new_one.sql" in found and "freeze_migration_checksums.py" in found
    lines_before = manifest.read_text(encoding="utf-8").splitlines()
    added, wrong = fz.freeze(d, manifest)
    assert added == ["999_a_new_one.sql"] and wrong == [] and _problems(d, manifest) == []
    lines_after = manifest.read_text(encoding="utf-8").splitlines()
    assert lines_after[:-1] == lines_before and lines_after[-1].endswith("  999_a_new_one.sql")


def test_a_listed_migration_that_is_gone_is_named(copy):
    d, manifest, names = copy
    (d / names[2]).unlink()
    (found,) = _problems(d, manifest)
    assert names[2] in found and "not" in found and "deleted or renamed" in found


def test_replace_is_a_separate_named_act_for_an_unmerged_file(copy):
    d, manifest, names = copy
    (d / names[0]).write_text("SELECT 2;\n", encoding="utf-8")
    assert len(_problems(d, manifest)) == 1
    added, wrong = fz.freeze(d, manifest, replace=(names[0],))
    assert added == [] and wrong == [] and _problems(d, manifest) == []


def test_a_rollback_file_and_a_helper_are_not_held(copy):
    """They are never applied by the runner, so editing one runs nothing anywhere."""
    d, manifest, names = copy
    (d / names[0].replace(".sql", "_rollback.sql")).write_text("SELECT 1;\n", encoding="utf-8")
    (d / "_helper.sql").write_text("SELECT 1;\n", encoding="utf-8")
    assert _problems(d, manifest) == []


# ── migration 786, read as text (the real-Postgres half is test_786_..._pg.py) ─────────────────────────────────────────────────

def _statement(sql: str, start: str, end: str) -> str:
    i = sql.index(start)
    return sql[i:sql.index(end, i) + len(end)]


def _last_definer_before(number: int, start: str) -> Path:
    """The migration that LAST defined a function before `number`, found by number over the directory (never from memory)."""
    found = [m for m in runner.discover_migrations() if m.number < number and start in m.path.read_text(encoding="utf-8")]
    assert found, f"no migration before {number} holds {start!r}"
    return found[-1].path


@pytest.mark.parametrize("start,end,expected_number", [
    ("CREATE OR REPLACE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)", "\n$fn$;", 546),
    ("CREATE OR REPLACE FUNCTION public.my_portal_client_ids()", "\n$$;", 768),
])
def test_786_restates_each_function_byte_for_byte_as_the_migration_that_last_defined_it(start, end, expected_number):
    ancestor = _last_definer_before(786, start)
    assert int(ancestor.name[:3]) == expected_number, (
        f"{ancestor.name} defines this function and is numbered below 786: on a database built in order, 786 would now undo it")
    assert _statement(F786.read_text(encoding="utf-8"), start, end) == _statement(ancestor.read_text(encoding="utf-8"), start, end)


def test_786_rewrites_the_policies_by_the_pattern_and_the_replacement_of_migration_526():
    (f526,) = [m.path for m in runner.discover_migrations() if m.number == 526]
    lines = lambda text: [ln for ln in text.splitlines() if re.match(r"\s*(pat|rep) constant text := ", ln)]        # noqa: E731
    assert len(lines(f526.read_text(encoding="utf-8"))) == 2
    assert lines(F786.read_text(encoding="utf-8")) == lines(f526.read_text(encoding="utf-8"))


def test_786_takes_execute_from_every_signed_in_and_anonymous_role_and_checks_its_own_work():
    sql = F786.read_text(encoding="utf-8")
    assert "REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated" not in sql
    for refusal in ("is not the wrapper that asks who is calling", "can still execute post_journal_atomic",
                    "does not leave out a deleted client", "still call can_access_client once per row"):
        assert "RAISE EXCEPTION 'migration 786: " in sql and refusal in sql, refusal


def test_786_runs_inside_one_transaction():
    plan = runner.transaction_plan(F786.name, F786.read_text(encoding="utf-8"))
    assert plan.wrap, f"786 would run without a wrapping transaction: {plan.reason}"
