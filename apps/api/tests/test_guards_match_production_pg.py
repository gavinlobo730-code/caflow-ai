"""
The migrations must not declare a guard that production does not enforce.

WHY THIS EXISTS BESIDE test_schema_matches_production_pg.py

That test compares COLUMNS, and its docstring records why it compares nothing
else. This is the other half. Two databases can agree on every column and
still disagree on WHO may read a row and WHAT a row may contain:

  * migration 293 found production had no client_timeline_events_client_id_fkey
    and that both RESTRICTIVE policies on the table had drifted from their
    declared form — a tenancy check not being applied;
  * the first run of this comparison (2026-09-03) found clients_status_check
    still reading ('active', 'inactive') in production. Migration 042 added
    'archived' in the repository; production never got it; archiving a client
    failed there while the whole suite passed here.

Both are the same failure as the column drift: the CI template is built FROM
the migrations, so every test only ever sees what the migrations say.

WHAT IS ASSERTED

The four directions that break something, each at zero after migration 316:

  rls_off_in_live                          a policy on a table with RLS off is
                                           decoration, and the direct PostgREST
                                           path sees every firm's rows
  rls_off_in_the_migrations                the same, pointed at every NEW
                                           environment instead of at production
  restrictive_policies_missing_from_live   a check every row must pass is absent
  tables_left_without_a_policy_in_live     RLS on and no policy is fail-closed,
                                           so the frontend's direct reads of
                                           the table silently return nothing
  check_constraints_differ                 production rejects a value the
                                           migrations accept — the 'archived'
                                           failure, and the class it belongs to

WHAT IS DELIBERATELY NOT ASSERTED, AND WHERE IT IS RECORDED

unique_constraints_missing_from_live is reported, not asserted:
client_profiles_firm_id_client_id_key is declared by the migrations and
violated by production on purpose — repositories/memory_repository.py
VERSIONS profiles, so the declaration is what is wrong, and nothing upserts
against it. The remaining 270-odd differences — policies present on one side
only, constraints only production has, ON DELETE behaviour that differs — are
real and are worked through in docs/audits/2026-09-03-guard-drift-first-run.md.
Asserting on all of them would make this a permanent triple-figure complaint
that somebody turns off.

IN-FLIGHT EXCLUSION

The fixture is production on one day. The repository is legitimately ahead of
it by the migrations that have not merged yet, so a guard those migrations
NAME is excused — otherwise adding a constraint would fail its own PR. The
high-water mark is in the fixture's .meta.json, and only names that actually
appear in a migration above it are excused, which is the safe direction.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "production_guards_2026-09-03.json"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / "db" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard_drift = _load_script("guard_drift")
guard_snapshot = _load_script("guard_snapshot")

_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")


def _declared_snapshot(template_name: str) -> dict:
    """Introspect a clone of the migration-built template with the SAME query
    the fixture was captured with — guard_snapshot.GUARD_SQL — so the diff is
    of the guards and not of the questions."""
    admin = _HARNESS_PG.strip()
    name = f"caflow_guards_{uuid.uuid4().hex[:12]}"
    subprocess.run(["psql", f"{admin} dbname=postgres", "-v", "ON_ERROR_STOP=1",
                    "-X", "-q", "-c", f'CREATE DATABASE "{name}" TEMPLATE "{template_name}";'],
                   capture_output=True, text=True, check=True)
    try:
        return guard_snapshot.normalise(
            guard_snapshot.snapshot_via_psql(f"{admin} dbname={name}"))
    finally:
        subprocess.run(["psql", f"{admin} dbname=postgres", "-X", "-q", "-c",
                        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);'],
                       capture_output=True, text=True)


#: What an in-flight migration must actually DO to an object before a finding
#: about that object is excused. Each pattern's first group is the name.
#:
#: THIS USED TO BE EVERY LOWERCASE IDENTIFIER IN THE FILE, and that was the
#: real weakness rather than the cap below it. A migration that merely
#: MENTIONED `journal_entries` — in a comment, in a `REFERENCES` clause, in an
#: unrelated `UPDATE` — excused every guard finding about that table, and an
#: in-flight set touches the busiest tables in the schema by construction. So
#: the exclusion widened with every migration on a branch while the thing it
#: was meant to excuse (an object production has not seen yet) did not.
#:
#: Narrow now: the object has to be CREATED, ADDED or have its RLS switched on
#: by a migration production has not applied. Being under-generous fails a
#: legitimate PR loudly and is fixed by adding the shape here; being
#: over-generous is silent and was excusing real drift.
_CREATES_IN_FLIGHT = (
    re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?([a-z_][a-z0-9_]*)"),
    re.compile(r"create\s+policy\s+\"?([a-z_][a-z0-9_]*)\"?"),
    re.compile(r"add\s+constraint\s+([a-z_][a-z0-9_]*)"),
    re.compile(r"add\s+column\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)"),
    re.compile(r"alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?([a-z_][a-z0-9_]*)\s+"
               r"enable\s+row\s+level\s+security"),
    # A CHECK written inline on ADD COLUMN is named `<table>_<column>_check` by
    # Postgres, and the finding carries that generated name rather than
    # anything spelled in the file.
    re.compile(r"alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?[a-z_][a-z0-9_]*\s+"
               r"add\s+column\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)"),
)


def _names_in_migrations_after_the_snapshot() -> set:
    """Every object CREATED by a migration numbered above the fixture's
    high-water mark — not every identifier those migrations mention."""
    meta_path = _FIXTURE.with_suffix(".meta.json")
    if not meta_path.exists():
        return set()
    through = json.loads(meta_path.read_text(encoding="utf-8"))["applied_through_migration"]
    names: set = set()
    for sql in sorted((_ROOT / "migrations").glob("*.sql")):
        head = sql.name.split("_", 1)[0]
        if not head.isdigit() or int(head) <= through:
            continue
        body = sql.read_text(encoding="utf-8").lower()
        for pattern in _CREATES_IN_FLIGHT:
            names |= set(pattern.findall(body))
        # `<table>_<column>_check` for an inline CHECK on a new column.
        for table, column in re.findall(
                r"alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?([a-z_][a-z0-9_]*)\s+"
                r"add\s+column\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)", body):
            names.add(f"{table}_{column}_check")
    return names


def _not_in_flight(items: list, in_flight: set) -> list:
    """Drop entries whose object name (or table, for table-level findings) a
    pending migration mentions. Entries look like 'table.name  [detail]',
    'table.name: …' or bare 'table'."""
    out = []
    for item in items:
        key = item.split("  ")[0].split(":")[0]
        table, _, name = key.partition(".")
        if (name or table) in in_flight or table in in_flight:
            continue
        out.append(item)
    return out


@pytest.fixture(scope="module")
def report(pg_template):
    declared = _declared_snapshot(pg_template.name)
    live = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return guard_drift.diff_guards(declared, live)


@pytest.fixture(scope="module")
def in_flight():
    return _names_in_migrations_after_the_snapshot()


# ── The assertions ────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_no_table_has_row_level_security_switched_off_in_production(report):
    assert not report["rls_off_in_live"], (
        "RLS is OFF in production on these tables. Every policy on them is "
        "decoration, and the frontend's direct PostgREST reads see every firm's "
        "rows.\n  " + "\n  ".join(report["rls_off_in_live"]))


@_NEEDS_PG
def test_no_table_has_row_level_security_switched_off_in_the_migrations(report, in_flight):
    """The mirror of the test above, and the one that actually bit.

    Production had RLS on for all eight tables migration 317 fixes, so nothing
    was exposed there and no assertion pointed at the live database could see
    it. The migrations had RLS OFF on them, and migrations 095 and 287 had
    granted `authenticated` full DML — so the CI template, and any new
    environment, enforced nothing at all on those tables.
    """
    offenders = _not_in_flight(report["rls_off_in_the_migrations"], in_flight)
    assert not offenders, (
        "Row-level security is OFF in the migrations on these tables and ON in "
        "production. Production is safe; every NEW environment built from these "
        "migrations is not, and neither is the CI template that every other test "
        "in this suite runs against.\n"
        "Enable it and declare the policy production already has (migration 317 "
        "is the pattern).\n  " + "\n  ".join(offenders))


@_NEEDS_PG
def test_no_restrictive_policy_is_missing_from_production(report, in_flight):
    offenders = _not_in_flight(report["restrictive_policies_missing_from_live"], in_flight)
    assert not offenders, (
        "These RESTRICTIVE policies are declared by the migrations and absent in "
        "production. A restrictive policy is a check every row must pass; its "
        "absence widens what a caller can reach — migration 293 found exactly "
        "this on client_timeline_events.\n  " + "\n  ".join(offenders))


@_NEEDS_PG
def test_no_table_with_declared_policies_has_none_in_production(report, in_flight):
    offenders = _not_in_flight(report["tables_left_without_a_policy_in_live"], in_flight)
    assert not offenders, (
        "These tables have policies in the migrations and NONE in production. "
        "RLS is on, so the direct PostgREST path is fail-closed: every read "
        "returns nothing and no error says why.\n  " + "\n  ".join(offenders))


@_NEEDS_PG
def test_no_check_constraint_admits_different_values_in_production(report, in_flight):
    offenders = _not_in_flight(report["check_constraints_differ"], in_flight)
    assert not offenders, (
        "These CHECK constraints have one expression in the migrations and "
        "another in production. A value the migrations accept may be REJECTED "
        "there while every test here passes — that is how archiving a client "
        "failed in production (clients_status_check, fixed by migration 316).\n"
        "Decide which side is right, then re-create the constraint on both sides "
        "in a migration so the two hash the same; 316 is the pattern.\n  "
        + "\n  ".join(offenders))


# ── Guard the guard ───────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_comparison_actually_ran(report):
    """A fixture that failed to load, or an empty template, would pass every
    assertion above by comparing nothing to nothing."""
    assert sum(len(v) for v in report.values()) > 0, (
        "The comparison found NO differences at all, which is not plausible — "
        "the first real run found 276. Something compared nothing.")


@_NEEDS_PG
def test_the_fixture_describes_a_real_set_of_guards():
    live = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert len(live["rls"]) > 200, "the production guards snapshot looks truncated"
    assert live["rls"]["journal_entries"]["detail"] == "on"
    # A RESTRICTIVE policy this product certainly has: the assignment-scope
    # policies of migrations 260/261 are the reason the guard diff exists.
    restrictive = [k for k, v in live["policy"].items() if v["detail"].startswith("RESTRICTIVE")]
    assert restrictive, "no RESTRICTIVE policy in the fixture — the wrong query was captured"


#: The most of production's OWN tables the in-flight exclusion may shield
#: before it stops being narrow enough to trust.
#:
#: THIS REPLACES A COUNT OF UNMERGED MIGRATIONS (10 -> 12 -> gone), and the
#: replacement is a strengthening rather than a relaxation. That count was a
#: PROXY for the thing that actually matters — how wide the exclusion is — and
#: it was a proxy because the exclusion used to be every lowercase identifier
#: in every in-flight migration, which does widen with the count. It no longer
#: is (see `_CREATES_IN_FLIGHT`): a finding is excused only where an unapplied
#: migration CREATES the object, so the exclusion covers new tables, new
#: columns, new constraints and new policies however many migrations are in
#: flight.
#:
#: That makes the property measurable directly, which is what this asserts. It
#: is strictly stronger than the count was: a mark of 0 would put every
#: CREATE TABLE in the whole set in flight and shield essentially all 279 of
#: production's tables, failing here by a couple of hundred — where the old
#: count test would have failed by 394 and the old EXCLUSION would meanwhile
#: have been excusing real drift on `journal_entries` because some in-flight
#: migration happened to write the name in a comment.
#:
#: Against the branch as it stands the figure is ZERO: every in-flight
#: migration creates tables production has never seen and adds columns to
#: tables whose existing guards are still compared in full.
MAX_LIVE_TABLES_THE_EXCLUSION_MAY_SHIELD = 8


@_NEEDS_PG
def test_the_in_flight_exclusion_cannot_excuse_everything(in_flight):
    """If the high-water mark were wrong — say 0 — every migration would be
    'in flight' and every finding excused. Measured on what the exclusion
    actually shields, not on how far behind the mark is."""
    meta = json.loads(_FIXTURE.with_suffix(".meta.json").read_text(encoding="utf-8"))
    numbers = sorted(int(p.name.split("_", 1)[0]) for p in (_ROOT / "migrations").glob("*.sql")
                     if p.name.split("_", 1)[0].isdigit())
    through = meta["applied_through_migration"]
    assert through in numbers, (
        f"the fixture says production has applied through migration {through}, "
        f"which is not a migration in this tree — the mark is wrong, and every "
        f"migration above it is being treated as in flight.")

    live = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    tables = set(live["rls"])
    shielded = sorted(tables & in_flight)
    assert len(shielded) <= MAX_LIVE_TABLES_THE_EXCLUSION_MAY_SHIELD, (
        f"the in-flight exclusion shields {len(shielded)} of production's "
        f"{len(tables)} own tables, which is wide enough to excuse a real "
        f"regression. A table production ALREADY HAS is not in flight: its "
        f"guards are comparable and must be compared. Either the fixture's "
        f"high-water mark ({through}) is wrong, or a migration above it is "
        f"re-creating a table that already exists.\n  "
        + "\n  ".join(shielded))


def test_a_planted_offender_would_be_caught():
    """Prove the assertion has teeth without waiting for a real regression.
    Mock-mode: it exercises the diff, not the database."""
    declared = {"rls": {"t": {"detail": "on", "expr_md5": ""}},
                "policy": {"t.scope": {"detail": "RESTRICTIVE cmd=* roles=PUBLIC", "expr_md5": "a"}},
                "constraint": {"t.t_status_check": {"detail": "c", "expr_md5": "with"}}}
    live = {"rls": {"t": {"detail": "OFF", "expr_md5": ""}},
            "policy": {},
            "constraint": {"t.t_status_check": {"detail": "c", "expr_md5": "without"}}}
    report = guard_drift.diff_guards(declared, live)
    assert report["rls_off_in_live"] == ["t"]
    assert report["restrictive_policies_missing_from_live"] == ["t.scope"]
    assert report["tables_left_without_a_policy_in_live"] == ["t"]
    assert report["check_constraints_differ"] == ["t.t_status_check"]
    assert _not_in_flight(report["check_constraints_differ"], {"t_status_check"}) == []
    assert _not_in_flight(report["check_constraints_differ"], set()) == ["t.t_status_check"]
