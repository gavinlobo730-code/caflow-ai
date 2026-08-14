"""
Every relation the frontend queries must actually exist.

THE MISTAKE THIS EXISTS TO CATCH
    /risks queried `dsc_tracker`. No such relation has ever existed — the table
    is dsc_records. The query sat partway through a multi-section load() behind
    `if (error) throw`, so it did not break one widget: every risk section below
    it was left empty too.

    Nothing caught it. A PostgREST call against a missing relation is a runtime
    error on one page — not a type error, not a build error, not a lint error.
    `tsc` is happy, because `.from("dsc_tracker")` is just a string.

A CORRECTION, KEPT HERE ON PURPOSE
    This file originally claimed FOUR pages were broken this way, naming
    `accounts`, `journal_entry_lines` and `salary_slips` alongside dsc_tracker.
    That was wrong. All three are real relations in production — compatibility
    VIEWS created by migrations 016 and 072 — and the pages querying them
    worked. Only dsc_tracker was ever a missing relation.

    The claim was never checked against this file's own replay, which said
    plainly that `accounts` and `journal_entry_lines` were live. The assertion
    written to "pin the fix" only checked that the frontend had STOPPED naming
    them, which is true of any name nobody uses and proves nothing about
    whether it exists. An assertion that cannot fail for the stated reason is
    worse than no assertion: it reads as evidence.

    `salary_slips` was invisible for a second, duller reason — the replay's
    CREATE pattern did not match `CREATE OR REPLACE VIEW`, and DROP VIEW was
    not handled at all. Both are fixed below, and
    test_the_migration_replay_agrees_with_the_real_schema now spot-checks views
    as well as tables so the same blind spot cannot come back quietly.

RELATION TO test_frontend_does_not_read_dropped_tables.py
    That file catches a relation the migrations DROPPED. This one catches a
    relation that was never CREATED, which is the larger set and the one that
    bit here — dsc_tracker was never dropped, because it never existed.

RELATION TO test_frontend_columns_exist_pg.py
    That file checks the COLUMNS inside each .select() against a real Postgres
    with every migration applied, and is strictly more accurate than this
    regex replay. It only runs where HARNESS_PG is set. This file stays because
    it runs everywhere, including the mock-mode CI job.
"""
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
WEB = API_ROOT.parents[1] / "apps" / "web"

# Names the frontend may query that no migration creates. Each needs a reason:
# a view, an external schema, or something created outside the migration files.
# Empty today — every table apps/web touches is created by a migration.
EXEMPT: dict[str, str] = {}

# "OR REPLACE" is optional and was the gap that hid salary_slips: migration 072
# writes CREATE OR REPLACE VIEW, which the original pattern did not match, so a
# view that plainly exists looked missing.
_CREATE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?(?:TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-z_0-9]+)",
    re.I)
# DROP VIEW matters as much as DROP TABLE: migration 016 drops the three compat
# views and recreates them. Ignoring the drop happened to give the right answer
# there (dropped then recreated), but a drop that is NOT followed by a recreate
# would leave a dead name looking live.
_DROP = re.compile(
    r"DROP\s+(?:MATERIALIZED\s+)?(?:TABLE|VIEW)\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-z_0-9]+)",
    re.I)
_RENAME = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-z_0-9]+)\s+RENAME\s+TO\s+(?:public\.)?([a-z_0-9]+)",
    re.I)

pytestmark = pytest.mark.skipif(
    not WEB.is_dir() or not MIGRATIONS.is_dir(),
    reason="needs both apps/web and apps/api/migrations in the checkout")


def _live_tables() -> set[str]:
    """Tables that exist after replaying every migration in order.

    Order matters and so does RENAME: a table created as `x` and renamed to `y`
    is live as `y` and gone as `x`. Handling creates, drops and renames in the
    order they appear is what makes this match the real database rather than a
    union of everything ever mentioned.
    """
    live: set[str] = set()
    for path in sorted(p for p in MIGRATIONS.glob("*.sql") if "rollback" not in p.name):
        src = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r"(CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?(?:TABLE|VIEW)"
                r"|DROP\s+(?:MATERIALIZED\s+)?(?:TABLE|VIEW)|ALTER\s+TABLE)[^;]*;",
                src, re.I | re.S):
            stmt = m.group(0)
            head = stmt.upper().lstrip()
            if head.startswith("CREATE"):
                found = _CREATE.search(stmt)
                if found:
                    live.add(found.group(1).lower())
            elif head.startswith("DROP"):
                found = _DROP.search(stmt)
                if found:
                    live.discard(found.group(1).lower())
            else:
                found = _RENAME.search(stmt)
                if found:
                    live.discard(found.group(1).lower())
                    live.add(found.group(2).lower())
    return live


def _frontend_queries() -> dict[str, set[str]]:
    """table -> frontend files querying it via PostgREST."""
    refs: dict[str, set[str]] = {}
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for table in re.findall(r'\.from\("([a-z_0-9]+)"\)', src):
            refs.setdefault(table, set()).add(path.relative_to(WEB).as_posix())
    return refs


def test_the_scan_finds_both_sides():
    """Vacuity guard: a parser that finds nothing passes the check below for
    any repository state at all."""
    assert len(_live_tables()) >= 150, "migrations did not parse into a table list"
    assert len(_frontend_queries()) >= 20, "no PostgREST queries found in apps/web"


def test_the_migration_replay_agrees_with_the_real_schema():
    """Spot-check the replay against relations known to exist in production. If
    these drop out, the parser has broken and every assertion below is
    worthless — a shrinking `live` set turns this file into a false alarm
    generator, which is how a useful test gets deleted."""
    live = _live_tables()

    for t in ("chart_of_accounts", "journal_lines", "journal_entries",
              "dsc_records", "payroll_slips", "clients", "client_sales_invoices"):
        assert t in live, f"{t} exists in production but not in the migration replay"


def test_the_replay_sees_views_and_not_just_tables():
    """The blind spot that produced this file's original false claim.

    These five are VIEWS in production — confirmed against the live database —
    and three of them are written as CREATE OR REPLACE VIEW, which the first
    version of the CREATE pattern silently skipped. A relation missing from the
    replay reads as "this page queries something that does not exist", which is
    exactly the wrong conclusion to hand someone.
    """
    live = _live_tables()
    for v in ("accounts", "journal_entry_lines", "compliance_entries",
              "salary_slips", "clients_external"):
        assert v in live, (
            f"{v} is a view in production but the migration replay does not see "
            f"it — check the CREATE/DROP patterns before trusting any failure "
            f"this file reports.")


def test_dsc_tracker_stays_gone():
    """Pins the one real fix. Deliberately asserts BOTH halves: that nothing
    queries the name, AND that the name genuinely does not exist. The original
    version of this test checked only the first, which is true of every string
    nobody has typed and so could not fail for the reason it claimed."""
    assert "dsc_tracker" not in _live_tables(), (
        "dsc_tracker now exists — if a migration created it, this test's "
        "premise is gone and it should be deleted, not worked around.")
    assert "dsc_tracker" not in _frontend_queries(), (
        'a page queries "dsc_tracker" again — the table is dsc_records.')


def test_no_frontend_code_queries_a_table_that_does_not_exist():
    live = _live_tables()
    refs = _frontend_queries()

    offenders = []
    for table in sorted(set(refs) - live - set(EXEMPT)):
        for f in sorted(refs[table]):
            offenders.append(f"{f} queries `{table}`")

    assert not offenders, (
        "these frontend files query tables no migration creates, so they fail "
        "at runtime on a missing relation — and because the query sits inside "
        "the page's load(), the whole page dies, not just one widget:\n  "
        + "\n  ".join(offenders)
        + "\n\nPoint the code at the real table, or add the name to EXEMPT with "
          "the reason it legitimately lives outside the migrations."
    )


def test_every_exemption_states_a_reason():
    for name, why in EXEMPT.items():
        assert len(why) > 40, f"{name}: say why it is not in the migrations"


def test_no_exemption_is_stale():
    """An exemption for a table nothing queries any more is a hole: the name can
    come back into use later and skip the check entirely."""
    refs = _frontend_queries()
    stale = sorted(set(EXEMPT) - set(refs))

    assert not stale, f"EXEMPT lists tables the frontend no longer queries: {stale}"
