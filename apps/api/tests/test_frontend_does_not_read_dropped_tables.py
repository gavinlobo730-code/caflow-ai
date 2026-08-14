"""
No frontend code may query a table the migrations have dropped.

THE MISTAKE THIS EXISTS TO CATCH
    Migration 139 dropped `transactions`, `transaction_lines` and `invoice_lines`,
    stating: "0 rows; no code reads or writes it ... Verified before drop: all
    three tables empty; no application code references them."

    That was true of the backend and false of the frontend. Four screens queried
    those tables straight from the browser, and every one of them has failed on a
    missing relation ever since — GSTR-1, GSTR-3B, Reports and the client portal.
    Nothing failed at deploy time, because a PostgREST call against a missing
    table is a runtime error on one page, not a build error.

    The verification wasn't wrong to be attempted; it was wrong to stop at the
    Python. This test is that same check, done across the repository and kept.

WHAT IT DOES NOT DO
    It does not know whether a table SHOULD be dropped, or whether the frontend
    is right to want it. It only refuses to let the two drift apart silently.
"""
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
WEB = API_ROOT.parents[1] / "apps" / "web"

# Frontend reads of a dropped table that are KNOWN broken and not yet repaired.
# Each entry is a promise to come back, not permission to forget: the test still
# fails for any dropped table referenced from a file not listed here.
#
# The GSTR-1 and GSTR-3B screens were repaired by moving to the API's from-books
# endpoints, which read the live tables server-side. These two need more than a
# rewire — `getTransactions` has no single live equivalent, and deciding what it
# should return (posted sales invoices? plus purchase bills? which statuses?) is
# a product question about what those screens show, not a mechanical swap. Doing
# it by guess would put wrong figures on a financial report, which is worse than
# the current honest failure.
KNOWN_BROKEN = {
    "lib/data/transactions.ts": "getTransactions / getGSTSummary still read the "
                                "dropped `transactions` table; they feed /reports "
                                "and /client-portal, which need a decision about "
                                "what a 'transaction' is now that the live model "
                                "is client_sales_invoices + purchase_bills",
}

_DROP = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-z_]+)", re.I)
_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-z_]+)", re.I)


def _migration_files():
    return sorted(p for p in MIGRATIONS.glob("*.sql") if "rollback" not in p.name)


def _dropped_tables() -> set[str]:
    """Tables dropped and never re-created by a LATER migration.

    Order matters: a table dropped in 139 and re-created in 200 is alive. The
    numeric prefix gives the order, and sorted() on the filename reproduces the
    runner's own sequence.
    """
    alive: set[str] = set()
    dropped: set[str] = set()
    for path in _migration_files():
        src = path.read_text(encoding="utf-8", errors="replace")
        # Within one file, process creates and drops in the order they appear.
        for m in re.finditer(r"(CREATE\s+TABLE|DROP\s+TABLE)[^;]*;", src, re.I | re.S):
            stmt = m.group(0)
            if stmt.upper().lstrip().startswith("CREATE"):
                found = _CREATE.search(stmt)
                if found:
                    alive.add(found.group(1).lower())
                    dropped.discard(found.group(1).lower())
            else:
                found = _DROP.search(stmt)
                if found:
                    dropped.add(found.group(1).lower())
                    alive.discard(found.group(1).lower())
    return dropped


def _frontend_table_refs() -> dict[str, set[str]]:
    """table -> frontend files querying it via PostgREST (.from("table"))."""
    refs: dict[str, set[str]] = {}
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for table in re.findall(r'\.from\("([a-z_]+)"\)', src):
            refs.setdefault(table, set()).add(path.relative_to(WEB).as_posix())
    return refs


pytestmark = pytest.mark.skipif(
    not WEB.is_dir() or not MIGRATIONS.is_dir(),
    reason="needs both apps/web and apps/api/migrations in the checkout",
)


def test_the_scan_finds_drops_and_frontend_queries():
    """Vacuity guard. Both halves have to be non-empty or the check below is an
    assertion about nothing."""
    assert len(_dropped_tables()) >= 3, "no dropped tables parsed from migrations"
    assert len(_frontend_table_refs()) >= 20, "no PostgREST queries found in apps/web"


def test_migration_139_really_did_drop_the_transaction_model():
    """Anchors the parser to the specific case that motivated this file. If this
    stops holding, the parser has broken rather than the world having changed."""
    dropped = _dropped_tables()

    for table in ("transactions", "transaction_lines", "invoice_lines"):
        assert table in dropped, f"{table} no longer parses as dropped"


def test_no_unlisted_frontend_code_queries_a_dropped_table():
    offenders = []
    refs = _frontend_table_refs()
    for table in sorted(_dropped_tables()):
        for file in sorted(refs.get(table, ())):
            if file not in KNOWN_BROKEN:
                offenders.append(f"{file} queries `{table}`")

    assert not offenders, (
        "these frontend files query tables the migrations have dropped, so they "
        "fail at runtime on a missing relation:\n  "
        + "\n  ".join(offenders)
        + "\n\nPoint the code at the live tables (usually via an API endpoint), "
          "or add the file to KNOWN_BROKEN with what still has to be decided."
    )


def test_known_broken_entries_still_apply():
    """Stops the allowlist outliving the problem. Once a listed file no longer
    touches a dropped table, its entry has to go, or the next real breakage in
    that file is silently permitted."""
    refs = _frontend_table_refs()
    dropped = _dropped_tables()
    still_broken = {f for t in dropped for f in refs.get(t, ())}

    stale = sorted(set(KNOWN_BROKEN) - still_broken)
    assert not stale, f"KNOWN_BROKEN lists files that are now clean: {stale}"


def test_each_known_broken_entry_says_what_is_undecided():
    for file, why in KNOWN_BROKEN.items():
        assert len(why) > 40, f"{file}: record the decision needed, not just a TODO"
