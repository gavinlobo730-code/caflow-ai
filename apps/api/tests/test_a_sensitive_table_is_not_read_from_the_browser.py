"""
POST-A-010. The sensitive tables are asked of the API, not of PostgREST from the browser.

About three hundred `.from("...")` calls in `apps/web` read and write tables straight
over PostgREST with the signed-in user's token, so every control the API applies
(`rbac()`, the per-person grid, the client assignment, MFA, the upload bounds, the read
log) has to be said a second time as database policy, and for the groups below it was
not: a Partner who unticks Payroll, Documents or Banking for a Manager on the Team
screen blocks the API route and leaves the same data readable from the browser.

Three groups are moved behind the API and kept there:

  * PAYROLL: every table named `payroll_*`, plus the leave, attendance and salary tables
    that hang from an employee;
  * BANK: every table named `bank_*` (accounts, statements, lines, matches, rules);
  * DOCUMENTS AND STORAGE: the document tables and EVERY use of Supabase Storage from
    the browser (an upload, a signed URL, a delete), because the bucket is shared by
    three resources and its policies are not per person.

THE RULE is that none of them is reached from `apps/web`, and since 25-10-2026 (the last step of POST-A-010: the employee
portal and its tax-declaration tab) it is ABSOLUTE: THE LIST below is empty. The list was how the item was moved in steps. It
could only SHRINK: a new reach failed as "new", a line whose reach had been moved failed as "stale" and had to be deleted (so a
reach that comes back could not hide behind a line nobody removed). It is kept, empty, with its checks, because the day a screen
reaches one of these tables again the person adding it must either move it behind the API or add a line here and say why. It is
a source scan of the browser's own files, so it is the half of the rule that the database cannot see.

WHAT IT SEES: a `.from("<table>")` with a literal name (spread over lines or not),
a call of `deleteRowAndConfirm(client, "<table>", id)` (the one generic helper that
takes the table as an argument), and any `.storage` use. WHAT IT DOES NOT: a table
named by a variable; a `.from(` whose argument is a template literal with an
interpolation is therefore REFUSED outright (there is none today), so a table name
cannot be assembled out of the scanner's sight. A comment is prose and is not scanned.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_API = Path(__file__).resolve().parents[1]

#: Whole-name prefixes: a table created next month under one of them is covered with no edit.
SENSITIVE_PREFIXES = ("payroll_", "bank_")

#: Exact names the prefixes do not cover.
SENSITIVE_TABLES = frozenset({
    # payroll: hangs from an employee
    "leave_balances", "attendance", "salary_structures", "salary_slips",
    # documents
    "client_documents", "documents", "document_requests",
    "document_extractions", "document_risks", "entity_documents",
})

#: Not a table: Supabase Storage, every use of it.
STORAGE = "storage"

#: The directories of `apps/web` whose files are the product. `scripts` holds the web's
#: own guards, which quote these names inside strings.
_SKIP_DIRS = {"node_modules", ".next", "out", ".vercel", "scripts", "public"}


def is_sensitive(table: str) -> bool:
    return table in SENSITIVE_TABLES or table.startswith(SENSITIVE_PREFIXES)


#: (file relative to apps/web, table or "storage") -> how many reaches the file still makes.
#: SHRINK-ONLY. Delete a line, or lower its number, in the commit that moves the reach.
REMAINING: dict[tuple[str, str], int] = {}


# ── the scanner ──────────────────────────────────────────────────────────────

_FROM_LITERAL = re.compile(r"""\.from\(\s*(["'`])([A-Za-z0-9_]+)\1\s*\)""")
_FROM_INTERPOLATED = re.compile(r"""\.from\(\s*`[^`]*\$\{""")
_DELETE_HELPER = re.compile(r"""\bdeleteRowAndConfirm\(\s*[^,()]+(?:\([^()]*\))?\s*,\s*(["'`])([A-Za-z0-9_]+)\1""")
_STORAGE = re.compile(r"""\.storage\b""")


def _code(src: str) -> str:
    """Comments are prose, not calls (two screens explain a call they no longer make)."""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def reaches(src: str) -> Counter:
    """name -> number of times this source reaches a sensitive table or Storage."""
    code = _code(src)
    found: Counter = Counter()
    for _, table in _FROM_LITERAL.findall(code):
        if is_sensitive(table):
            found[table] += 1
    for _, table in _DELETE_HELPER.findall(code):
        if is_sensitive(table):
            found[table] += 1
    found[STORAGE] += len(_STORAGE.findall(code))
    if not found[STORAGE]:
        del found[STORAGE]
    return found


def _files():
    for path in sorted(WEB.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or path.name.endswith(".d.ts"):
            continue
        rel = path.relative_to(WEB)
        if set(rel.parts) & _SKIP_DIRS or re.search(r"\.test\.tsx?$", path.name):
            continue
        yield rel.as_posix(), path


def _scan() -> tuple[dict[tuple[str, str], int], list[str]]:
    found: dict[tuple[str, str], int] = {}
    interpolated: list[str] = []
    for rel, path in _files():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - a binary file named .ts
            continue
        for name, n in reaches(src).items():
            found[(rel, name)] = n
        if _FROM_INTERPOLATED.search(_code(src)):
            interpolated.append(rel)
    return found, interpolated


# ── the rule ─────────────────────────────────────────────────────────────────

def test_the_browser_reaches_no_more_of_the_sensitive_tables_than_the_list_says():
    found, _ = _scan()
    new = {k: n for k, n in found.items() if n > REMAINING.get(k, 0)}
    assert not new, (
        "A screen in apps/web reaches a payroll, bank or document table, or Supabase Storage, "
        "straight from the browser (POST-A-010). Ask the API for it: the route applies the role, "
        "the per-person grid and the client assignment once. NEW (file, name): count:\n  "
        + "\n  ".join(f"{k}: {n}" for k, n in sorted(new.items())))


def test_the_browser_makes_no_use_of_storage_at_all():
    """Every Storage call of the browser is a route now (POST-A-010): an upload, a signed link and a delete each ask the
    server, which asks the Documents, Income-tax or Report permission and the client assignment first. Unlike the tables,
    this part of the rule is finished, so it is absolute and the list may not hold a Storage line."""
    found, _ = _scan()
    assert not [k for k in found if k[1] == STORAGE], (
        "apps/web uses Supabase Storage again: " + ", ".join(sorted(f for f, n in found if n == STORAGE)))
    assert not [k for k in REMAINING if k[1] == STORAGE], "REMAINING lists a Storage use; the list may not"


def test_the_list_holds_nothing_that_has_been_moved():
    found, _ = _scan()
    stale = {k: (n, found.get(k, 0)) for k, n in REMAINING.items() if found.get(k, 0) < n}
    assert not stale, (
        "REMAINING names a reach the browser no longer makes. The list only shrinks: lower or delete "
        "the line, in the commit that moved the reach. (file, name): (listed, found):\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sorted(stale.items())))


def test_a_table_name_is_never_assembled_out_of_the_scanners_sight():
    _, interpolated = _scan()
    assert not interpolated, (
        ".from(`...${x}...`) names a table the scan cannot read; write the table as a literal: "
        + ", ".join(interpolated))


def test_every_listed_file_exists_and_every_listed_name_is_sensitive():
    for (rel, name), n in REMAINING.items():
        assert (WEB / rel).is_file(), f"{rel} is not a file under apps/web"
        assert name == STORAGE or is_sensitive(name), f"{name} is not a sensitive table"
        assert n >= 1, f"{(rel, name)} lists {n} reaches"


def test_the_exact_names_are_real_tables():
    """A typo in SENSITIVE_TABLES would guard nothing and read as if it did."""
    snapshot = json.loads((_API / "tests" / "fixtures" / "production_schema_2026-09-03.json")
                          .read_text(encoding="utf-8"))
    tables = snapshot.get("tables") or snapshot
    names = set(tables) if isinstance(tables, dict) else {t.get("table_name") for t in tables}
    for sql in (_API / "migrations").glob("[0-9][0-9][0-9]_*.sql"):
        names.update(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? (?:public\.)?([a-z_0-9]+)",
                                sql.read_text(encoding="utf-8")))
    missing = sorted(t for t in SENSITIVE_TABLES if t not in names)
    assert not missing, f"not tables in the schema: {missing}"


def test_the_prefixes_cover_every_payroll_and_bank_table_in_the_schema():
    names: set[str] = set()
    for sql in (_API / "migrations").glob("[0-9][0-9][0-9]_*.sql"):
        names.update(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? (?:public\.)?([a-z_0-9]+)",
                                sql.read_text(encoding="utf-8")))
    assert {n for n in names if n.startswith(("payroll_", "bank_"))}, "the schema scan found nothing"
    assert all(is_sensitive(n) for n in names if n.startswith(("payroll_", "bank_")))


# ── the scanner, proved on text it must and must not flag ────────────────────

@pytest.mark.parametrize("src, expected", [
    ('sb.from("payroll_runs").select("*")', {"payroll_runs": 1}),
    ("sb.from('bank_accounts').select('id')", {"bank_accounts": 1}),
    ('sb\n  .from(\n    "client_documents"\n  )\n  .select("id")', {"client_documents": 1}),
    ("sb.from(`documents`)", {"documents": 1}),
    ('await deleteRowAndConfirm(getSupabaseClient(), "document_requests", id)', {"document_requests": 1}),
    ('await deleteRowAndConfirm(sb, "it_notices", id)', {}),
    ('sb.storage.from("Documents").remove([p])', {"storage": 1}),
    ('const { data } = await supabase.storage\n  .from(BUCKET)\n  .createSignedUrl(p, 60)', {"storage": 1}),
    ('sb.from("customers").select("id")', {}),
    ('localStorage.getItem("x")', {}),
    ('// sb.from("payroll_runs") was read here\nsb.from("vendors")', {}),
    ('/* sb.from("bank_accounts") */ sb.from("vendors")', {}),
    ('sb.from("payroll_runs"); sb.from("payroll_runs")', {"payroll_runs": 2}),
])
def test_the_scanner_flags_what_it_must_and_nothing_else(src, expected):
    assert dict(reaches(src)) == expected


def test_the_scanner_reads_an_interpolated_name_as_one_to_refuse():
    assert _FROM_INTERPOLATED.search(_code("sb.from(`payroll_${kind}`)"))
    assert not _FROM_INTERPOLATED.search(_code('sb.from("vendors")'))
