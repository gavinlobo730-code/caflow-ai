"""
The backlog, kept honest: which tables the browser writes directly, and which of
those the database still lets any role write.

Some screens talk to PostgREST rather than the API. For those, rbac() never
runs, so the only role check that can happen is the one in RLS. Migration 260
added that check to the nine tables where an existing API rule could be copied
verbatim. The rest are still open — not because they are safe, but because
nobody has decided who may edit them, and a guess would silently lock someone
out of their job with no error message that explains why.

This test does two jobs:

  1. It stops the guarded nine from quietly regressing — if a frontend write
     appears against a table migration 260 covers, that is fine; if migration
     260 stops covering one, the list below no longer matches and it fails.
  2. It makes the remainder VISIBLE and COUNTED, so "we'll do the rest later"
     cannot decay into "we forgot". Adding a new direct-write table without a
     decision fails this test rather than passing unnoticed.

It is a source scan, not a database check — the live policies are proved in
test_role_write_policies_pg.py, which needs PostgreSQL. This one runs always.
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_MIG_DIR = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_SOURCES = [_MIG_DIR / "260_role_aware_write_policies.sql",
                     _MIG_DIR / "261_role_aware_write_policies_part2.sql",
                     _MIG_DIR / "296_employee_income_tax_declarations.sql",
                     _MIG_DIR / "297_let_an_employee_file_their_own_declaration.sql",
                     _MIG_DIR / "345_the_tds_register_is_role_guarded.sql",
                     _MIG_DIR / "346_loans_and_deposits_carry_a_role_rule.sql",
                     _MIG_DIR / "359_a_certificate_is_not_a_rate.sql"]

# Covered by migration 260 — each mirrors a live rbac() guard on an endpoint
# that writes the same table.
GUARDED = {
    # migration 260 — mirrored an existing endpoint's rbac() guard
    "chart_of_accounts", "clients", "customers", "tasks", "documents",
    "fee_invoices", "fee_engagements", "mca_filings", "firms",
    # migration 261 — no endpoint existed; each rule argued in that file's header
    "attendance", "leave_balances", "compliance_calendar", "it_notices",
    "tax_audits", "tax_planning_records", "shared_reports", "scheduled_reports",
    "client_documents", "document_requests", "suppliers", "msme_payments",
    "client_timeline_events",
    # migrations 296 + 297 — the §192 declaration tables. Guarded differently
    # from everything above, and deliberately: staff need Manager (payroll:write),
    # but Rule 26C makes Form 12BB the EMPLOYEE's own statement, so 297 also
    # admits an employee to their own unverified declaration and nothing else.
    # The boundary is proved against real Postgres in
    # tests/test_297_employee_declaration_rls_pg.py — row scope, column scope
    # (an employee may declare an amount but never verify it) and time scope
    # (verified is final as far as the employee is concerned).
    "payroll_it_declarations", "payroll_it_declaration_items",
    # migration 345 — the four TDS tables. Each mirrors the tier its own
    # endpoint already enforces: routers/tds_workspace.py guards every write
    # with rbac("tds", "compute") = Executive+. They were invisible to this
    # scan until _chains stopped capping the tail at 400 characters.
    "tds_deductions", "tds_returns", "tds_challans", "tds_certificates",
    # migration 346 — the two the corrected scan found. No endpoint writes
    # either, so the tier is an OWNER decision of 2026-09-09 rather than a
    # mirrored one: Executive for insert, update and delete alike, because a
    # client handed to an Executive is theirs to run and a rule that makes them
    # fetch a Manager to fix their own typo gets worked around. The assignment
    # rule (loans_assignment_scope) was already in force and is untouched; what
    # 346 adds is that a REVIEWER assigned to the client can no longer write.
    "loans", "fixed_deposits",
    # migration 359 — the §197 lower-deduction certificate master. No endpoint
    # writes it, so the tier is argued in that file rather than mirrored: a
    # certificate LOWERS what is withheld from a real supplier, and an invented
    # one under-deducts and makes the deductor an assessee in default under
    # §201(1). Executive+ to write, Manager+ to delete — the same shape
    # migration 357 used for an opening written-down value, and for the same
    # reason: a figure one person records and everybody else's numbers rest on.
    "tds_lower_deduction_certificates",
}

# Written from the browser and NOT yet role-guarded. An entry needs a product
# decision — "who may edit this?" — before a rule can be written, because no API
# endpoint exists whose rbac() guard could be copied.
#
# Empty again: loans and fixed_deposits sat here from the moment the corrected
# scan found them until the owner answered the question on 2026-09-09, and
# migration 346 moved them to GUARDED. The category stays because the NEXT
# unguarded direct write should land here, with the question it raises, rather
# than being waved through — which is exactly what
# test_no_unaccounted_direct_write_table_appears enforces.
AWAITING_DECISION: dict[str, str] = {}

# Direct writes that CANNOT succeed, so no role policy would add anything. Kept
# as a third category rather than lumped in above, because "already impossible"
# and "undecided" need different follow-up: these two are broken features to fix
# or delete, not permission questions to answer.
#
# Both were found by this scan and confirmed against the production database.
# Both original entries have since been fixed, so the set is empty. It stays
# because the third category is still the right home for a direct write that
# cannot land — an empty dict here is a statement that none currently exist, and
# test_no_unaccounted_direct_write_table_appears will demand a decision the
# moment one does.
#
#   * `users` — settings/page.tsx wrote full_name directly while migration 153
#     had revoked the grant, so saving a display name answered "permission
#     denied for table users". Replaced by PATCH /api/identity/me.
#   * `transactions` — lib/data/gst.ts updated gst_invoice_category on a table
#     migration 139 dropped. That whole path is gone; the GST screens now use
#     the API's from-books endpoints. Reads of the dropped table that remain
#     elsewhere are tracked in test_frontend_does_not_read_dropped_tables.py.
CANNOT_SUCCEED: dict[str, str] = {}

_FROM = re.compile(r'\.from\(\s*"([a-z_]+)"\s*\)')
_WRITE = re.compile(r'\.\s*(insert|upsert|update|delete)\s*\(')


def _chains(src: str):
    r"""(table, the rest of that PostgREST statement) for every .from("x").

    A CHAIN RUNS TO ITS STATEMENT'S END, and that is the rule — not a window.

    This used to be one regex with a 400-character cap:

        r'\.from\("([a-z_]+)"\)((?:[^;]|\n){0,400}?)(?=\.from\("|;|\Z)'

    which cannot match a chain whose statement is longer than 400 characters at
    all: `[^;]` forbids the tail from stopping early, so the lookahead is
    unreachable and the whole match fails. The failure is silent AND it is
    worse than a miss — the same table usually appears elsewhere in a SHORT
    read chain, which does match, so the table is seen, `_WRITE` never fires on
    it, and it is filed as read-only. It looks accounted for.

    Four tables were hidden that way, and two of them are not TDS:

        tds_deductions   app/tds/page.tsx        insert, 464 chars to its ';'
        tds_returns      lib/data/tds.ts         upsert
        loans            app/accounting/loans/   insert
        fixed_deposits   app/accounting/loans/   insert

    Same lesson as the money-parser guard in CLAUDE.md and as the frontend
    filing sweep: a guard that names a SPELLING (here, "within 400 characters")
    misses every spelling it did not think of. A statement boundary is the
    thing that is actually true about a PostgREST chain.
    """
    for m in _FROM.finditer(src):
        semi = src.find(";", m.end())
        nxt = src.find('.from("', m.end())
        stop = min(semi if semi != -1 else len(src),
                   nxt if nxt != -1 else len(src))
        yield m.group(1), src[m.end():stop]


def _strip_comments(src: str) -> str:
    """Comments are prose, not calls.

    Two files explain a PostgREST write they no longer do, quoting the call —
    settings/page.tsx on `users` and lib/data/gst.ts on `transactions`, both
    recorded in CANNOT_SUCCEED's comment above. Scanning the prose re-reports
    them as live holes.
    """
    src = re.sub(r'/\*[\s\S]*?\*/', '', src)
    return re.sub(r'^\s*//.*$', '', src, flags=re.M)


def _direct_write_tables() -> dict[str, set[str]]:
    """table -> the frontend files that write it via PostgREST."""
    found: dict[str, set[str]] = {}
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for table, tail in _chains(_strip_comments(src)):
            if _WRITE.search(tail):
                found.setdefault(table, set()).add(path.relative_to(WEB).as_posix())
    return found


pytestmark = pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")


def test_the_scan_finds_direct_writes_at_all():
    """Vacuity guard — if the PostgREST call shape changes, every assertion
    below would iterate an empty set and pass."""
    found = _direct_write_tables()

    assert len(found) >= 15, (
        f"only {len(found)} direct-write tables found; the .from(...).insert() "
        "pattern this scan depends on has probably changed"
    )


def test_no_unaccounted_direct_write_table_appears():
    """A direct write to a table in neither set is a new hole nobody decided on.

    Fix it by guarding the table in a migration (move it to GUARDED), or by
    recording the open question in AWAITING_DECISION — but not by ignoring it.
    """
    unaccounted = sorted(set(_direct_write_tables())
                         - GUARDED - set(AWAITING_DECISION) - set(CANNOT_SUCCEED))

    assert not unaccounted, (
        "these tables are written straight from the browser and no role rule "
        "covers them:\n  "
        + "\n  ".join(f"{t}  ({', '.join(sorted(_direct_write_tables()[t])[:2])})"
                      for t in unaccounted)
        + "\n\nGuard the table in a migration, add it to AWAITING_DECISION with "
          "the question that needs answering, or to CANNOT_SUCCEED if the write "
          "can never land anyway."
    )


def test_guarded_tables_are_actually_in_the_migration():
    """GUARDED is a claim about the migrations. Hold it to the files, so removing
    a table from one cannot leave this test asserting protection that no longer
    exists.

    The table may be named in a loop's array (260/261 build their policies that
    way) or spelled out in a CREATE POLICY (296/297 do, because the employee
    branch differs per table). Either counts; what must not pass is a table
    named in NEITHER.
    """
    src = "\n".join(m.read_text(encoding="utf-8") for m in MIGRATION_SOURCES)

    for table in sorted(GUARDED):
        in_loop_array = re.search(rf"[\[,]\s*'{table}'\s*[,\]]", src)
        in_named_policy = re.search(
            rf"CREATE POLICY[^;]*?AS RESTRICTIVE[^;]*?ON public\.{table}\b", src,
            re.IGNORECASE | re.DOTALL)
        in_named_policy_alt = re.search(
            rf"ON public\.{table}\s+AS RESTRICTIVE", src, re.IGNORECASE)
        assert in_loop_array or in_named_policy or in_named_policy_alt, (
            f"{table} is listed as guarded but no migration covers it"
        )


def test_the_three_sets_do_not_overlap():
    """A table belongs in exactly one category; an overlap would hide a resolved
    question or claim a false one."""
    assert not (GUARDED & set(AWAITING_DECISION))
    assert not (GUARDED & set(CANNOT_SUCCEED))
    assert not (set(AWAITING_DECISION) & set(CANNOT_SUCCEED))


def test_every_open_table_carries_the_question_that_blocks_it():
    """An entry with no reason is a TODO, and TODOs are how a backlog stops
    being actionable. Each needs the actual decision spelled out."""
    for table, why in {**AWAITING_DECISION, **CANNOT_SUCCEED}.items():
        assert len(why) > 25, f"{table}: say what needs deciding, not just that it does"


# ── the blind spot itself, pinned ────────────────────────────────────────────

def test_the_old_windowed_scan_could_not_see_a_long_write():
    """The bug this file had, kept as a test so it cannot come back.

    The previous scan capped a chain's tail at 400 characters. `[^;]` forbids
    the tail from ending anywhere but the statement's `;`, so a statement longer
    than that cannot match AT ALL — and the table then usually still appears via
    some shorter READ chain elsewhere in the file, which is why it looked
    accounted for rather than missing.

    Measured against the real tree, and against a browser write that ACTUALLY
    ESCAPES the old cap, rather than a named one.

    It has now gone stale twice, and the second time is why the rule below is
    what it is. It first pointed at app/tds/page.tsx's tds_deductions insert
    (464 characters); Phase 3b deleted that insert, which is what the screen
    rewrite was for, and the test correctly failed rather than passing on a
    premise that had gone. It was re-pointed at "the LONGEST write anywhere",
    and that held until lib/data/tds.ts's tds_returns upsert was deleted too —
    at which point the longest became mca_filings at 624 characters, which the
    old regex CAN see, because that table also appears in a SHORT write chain
    elsewhere in the same file and `old_writes` is a set of tables.

    So "longest" was never the property. The property is "a write whose
    statement runs past the old cap AND which the old scan therefore misses" —
    six of those exist today, `loans` at 559 characters being the longest. Ask
    for that directly, and the test survives any of them being fixed until
    none is left, which is the state its own failure message describes.
    """
    old_chain = re.compile(
        r'\.from\("([a-z_]+)"\)((?:[^;]|\n){0,400}?)(?=\.from\("|;|\Z)', re.S)

    hidden = []   # (length, table, path, verb offset) — seen by the new scan only
    any_write = False
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = _strip_comments(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):                 # pragma: no cover
            continue
        # PER FILE, because both scans answer per file: a table counts as seen
        # by the old regex if ANY chain in the file matched with a write verb,
        # which is exactly how the four originals looked accounted for.
        old_writes = {t for t, tail in old_chain.findall(src) if _WRITE.search(tail)}
        new_writes = {t for t, tail in _chains(src) if _WRITE.search(tail)}
        for table, tail in _chains(src):
            m = _WRITE.search(tail)
            if not m:
                continue
            any_write = True
            if (table not in old_writes and table in new_writes
                    and m.start() < 400 < len(tail)):
                hidden.append((len(tail), table, path, m.start()))

    assert any_write, "no browser writes found at all — the scan is broken"
    assert hidden, (
        "every browser write is now visible to the old 400-character scan, so "
        "this test no longer measures anything. That is a GOOD state; delete "
        "this test rather than weakening it.")

    length, table, path, verb_at = max(hidden)
    # ...and it is the LENGTH that hid it, not the table or the verb: the write
    # verb itself sits well inside the old cap, so a scan that stopped at the
    # verb would have found it and a scan that had to reach the ';' did not.
    assert verb_at < 400 < length, (
        f"{table} in {path.name}: the write verb is {verb_at} characters in — "
        f"inside the old 400-char cap — but the statement runs {length} "
        "characters to its ';', and that is what the old pattern had to "
        "consume before it could match")


def test_the_tds_tier_matches_the_endpoints_it_mirrors():
    """A policy tier invented rather than copied is a guess, and a guess either
    locks a CA out of their job or lets a Reviewer edit a statutory register.

    Every write route in routers/tds_workspace.py is rbac("tds","compute").
    core/permissions.py puts tds:compute at Executive and tds:write at Manager,
    and migration 345 uses Executive for insert/update, Manager for delete.
    """
    ws = (Path(__file__).resolve().parents[1] / "routers" / "tds_workspace.py").read_text()
    write_routes = re.findall(r'@router\.(post|patch|put|delete)\([^)]*\)\s*\ndef \w+\('
                              r'(?:[^)]|\n)*?rbac\("tds",\s*"(\w+)"\)', ws)
    assert write_routes, "no TDS write routes found — has the router moved?"

    # PER VERB, because the two tiers are different on purpose and asserting
    # one tier for everything hides that. INSERT and UPDATE are tds:compute
    # (Executive); DELETE is tds:write (Manager), because removing a statutory
    # register row is not data entry — the same split migration 345 encodes.
    expected = {"post": "compute", "patch": "compute",
                "put": "compute", "delete": "write"}
    for verb, action in write_routes:
        assert action == expected[verb], (
            f"@router.{verb} is guarded rbac(\"tds\", \"{action}\") but "
            f"migration 345's policy for that command mirrors tds:{expected[verb]}. "
            "One of the two has moved; they have to agree or the app-layer check "
            "and the RLS check disagree about who may write.")

    # ...and the tiers those actions resolve to are the ones in the migration.
    from core.permissions import PERMISSIONS
    assert PERMISSIONS["tds"]["compute"] is not None
    mig = (_MIG_DIR / "345_the_tds_register_is_role_guarded.sql").read_text()
    for table in ("tds_deductions", "tds_returns", "tds_challans", "tds_certificates"):
        assert re.search(rf"\['{table}',\s*'Executive',\s*'Manager'\]", mig), table
