"""
Every table the frontend queries must actually exist.

THE MISTAKE THIS EXISTS TO CATCH
    Four pages queried tables that have never existed in this database:

        /accounting/budget      accounts, journal_entry_lines
        /accounting/recurring   accounts
        /risks                  dsc_tracker
        /portal/employee        salary_slips

    Every one was a naming slip — the real tables are chart_of_accounts,
    journal_lines, dsc_records and payroll_slips. And every one killed the WHOLE
    page, because the query sits inside the page's load() with `if (error)
    throw`, so a missing relation takes down everything after it. On /risks the
    dead query sat partway through a multi-section load, so the sections below
    it never populated either.

    None of it was caught by anything. A PostgREST call against a missing table
    is a runtime error on one page — not a type error, not a build error, not a
    lint error. `tsc` is happy: `.from("dsc_tracker")` is a string.

RELATION TO test_frontend_does_not_read_dropped_tables.py
    That file catches a table the migrations DROPPED. This one catches a table
    that was never CREATED, which is the larger set and the one that bit here —
    none of these four were ever dropped, because none ever existed.
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

_CREATE = re.compile(
    r"CREATE\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-z_0-9]+)",
    re.I)
_DROP = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-z_0-9]+)", re.I)
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
                r"(CREATE\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW)|DROP\s+TABLE|ALTER\s+TABLE)[^;]*;",
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
    """Spot-check the replay against tables known to exist in production. If
    these drop out, the parser has broken and every assertion below is
    worthless — a shrinking `live` set turns this file into a false alarm
    generator, which is how a useful test gets deleted."""
    live = _live_tables()

    for t in ("chart_of_accounts", "journal_lines", "journal_entries",
              "dsc_records", "payroll_slips", "clients", "client_sales_invoices"):
        assert t in live, f"{t} exists in production but not in the migration replay"


def test_the_four_pages_that_broke_now_name_real_tables():
    """Pins the specific fix. A revert would otherwise only be caught by the
    general check below, which reads as a nameless regression."""
    live = _live_tables()
    refs = _frontend_queries()

    for gone in ("accounts", "journal_entry_lines", "dsc_tracker", "salary_slips"):
        assert gone not in refs, (
            f'a page queries "{gone}" again — that table does not exist. '
            f"See this file's docstring for what it should be."
        )
    for real in ("chart_of_accounts", "journal_lines", "dsc_records", "payroll_slips"):
        assert real in live


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
