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
                     _MIG_DIR / "345_the_tds_register_is_role_guarded.sql"]

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
}

# Written from the browser and NOT yet role-guarded. An entry needs a product
# decision — "who may edit this?" — before a rule can be written, because no API
# endpoint exists whose rbac() guard could be copied.
#
# Empty: every table the browser writes now carries a role rule (260 + 261). The
# category stays because the NEXT unguarded direct write should land here, with
# the question it raises, rather than being waved through — which is exactly
# what test_no_unaccounted_direct_write_table_appears enforces.
AWAITING_DECISION: dict[str, str] = {
    # Found by the corrected scan (see _chains). app/accounting/loans/page.tsx
    # inserts both straight over PostgREST, and NO API endpoint writes either
    # one — grep apps/api for table("loans") / table("fixed_deposits") returns
    # nothing outside tests. So there is no rbac() guard to mirror, which is
    # precisely what this category is for: migration 261's header argues that
    # guessing a tier "would silently lock someone out of their job with no
    # error message that explains why".
    "loans": "Who may record or amend a client's borrowing? It is a balance "
             "sheet liability that feeds the cash-flow report and the risk "
             "screen, so it is at least accounting:write (Manager+) — but no "
             "endpoint exists to copy that from, and Executive+ is arguable "
             "since entering one is data entry, not a judgement.",
    "fixed_deposits": "Same question as loans, same screen, same absence of an "
                      "API twin. Decide the pair together — splitting them "
                      "would let a role edit one side of the same page.",
}

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

    Measured against the real file, and against the LONGEST browser write that
    exists rather than a named one. It used to point at app/tds/page.tsx's
    tds_deductions insert (464 characters); Phase 3b deleted that insert, which
    is what the screen rewrite was for, and this test correctly failed rather
    than passing on a premise that had gone. Picking the longest write each time
    is the version of the assertion that survives the next such fix.
    """
    longest = None
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = _strip_comments(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):                 # pragma: no cover
            continue
        for table, tail in _chains(src):
            m = _WRITE.search(tail)
            if m and (longest is None or len(tail) > longest[0]):
                longest = (len(tail), table, path, src, m.start())

    assert longest, "no browser writes found at all — the scan is broken"
    length, table, path, src, verb_at = longest
    assert length > 400, (
        f"the longest browser write is now only {length} characters "
        f"({table} in {path.name}) — every write fits inside the old 400-char "
        "cap, so this test no longer measures anything. That is a GOOD state; "
        "delete this test rather than weakening it.")

    old_chain = re.compile(
        r'\.from\("([a-z_]+)"\)((?:[^;]|\n){0,400}?)(?=\.from\("|;|\Z)', re.S)
    old_writes = {t for t, tail in old_chain.findall(src) if _WRITE.search(tail)}
    new_writes = {t for t, tail in _chains(src) if _WRITE.search(tail)}

    assert table not in old_writes, (
        f"the old regex now sees {table}'s {length}-character write — it should "
        "not be able to reach the statement's ';' within 400 characters")
    assert table in new_writes, "the statement-bounded scan must see it"

    # ...and it is the LENGTH that hid it, not the table or the verb: the write
    # verb itself sits well inside the old cap.
    assert verb_at < 400 < length, (
        f"the write verb is {verb_at} characters in — inside the old 400-char "
        f"cap — but the statement runs {length} characters to its ';', and that "
        "is what the old pattern had to consume before it could match")


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
