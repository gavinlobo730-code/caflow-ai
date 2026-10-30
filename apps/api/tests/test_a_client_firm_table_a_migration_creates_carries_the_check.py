"""A table a migration creates with a `client_id` and a `firm_id` asks for the client-belongs-to-firm check at creation (POST-A-304).

WHY THIS IS A RULE ABOUT MIGRATIONS
    Migration 565 gave every table that had both columns the triggers that refuse a row naming a client of another firm (and a
    customer or vendor of another client), through one installer, `public.guard_client_firm(table)`. Its closing check covers the
    tables that existed THEN. A table created later has nothing unless its own migration calls the installer, and the real-Postgres
    catalog test (`test_565_..._pg`) only runs where there is a Postgres. This is the half the required mock-mode check can read:
    the migration text.

WHAT COUNTS
    A migration numbered above 565 that creates a table with a top-level `client_id` and `firm_id`, and no call of
    `guard_client_firm('<table>')` in that migration or a LATER one (a sweep that closes an earlier table is a legitimate fix).
    A call may name the table directly or sit in a `FOREACH ... IN ARRAY ARRAY[...] LOOP` over a list of tables.

WHAT IT DOES NOT DO
    It does not say the check is right (the real-Postgres test connects and attempts the statements), and it cannot see a table
    created by dynamic SQL; a table made that way is found by the catalog test instead.
"""
from __future__ import annotations

import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"

#: Migration 565 installed the check on every table that existed; a table created after it is this rule's.
FIRST_GUARDED = 566

#: A table that deliberately carries no such check, with the reason. Empty: none is known.
EXEMPT: dict[str, str] = {}


def _strip_comments(sql: str) -> str:
    out: list[str] = []
    i, n, in_str = 0, len(sql), False
    while i < n:
        c = sql[i]
        if in_str:
            out.append(c)
            if c == "'":
                in_str = False
            i += 1
        elif c == "'":
            in_str = True
            out.append(c)
            i += 1
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _top_level_items(body: str) -> list[str]:
    items, depth, cur, in_str = [], 0, [], False
    for c in body:
        if in_str:
            cur.append(c)
            in_str = c != "'"
            continue
        if c == "'":
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            items.append("".join(cur))
            cur = []
            continue
        cur.append(c)
    items.append("".join(cur))
    return items


_CREATE_TABLE = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?([a-z0-9_]+)"?\s*\(', re.I)
_CLIENT = re.compile(r'^\s*"?client_id"?\s', re.I)
_FIRM = re.compile(r'^\s*"?firm_id"?\s', re.I)


def client_firm_tables_created_by(sql: str) -> set[str]:
    """Tables this migration creates with BOTH a top-level `client_id` and a top-level `firm_id`."""
    clean = _strip_comments(sql)
    found: set[str] = set()
    for m in _CREATE_TABLE.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        items = _top_level_items(clean[m.end():i - 1])
        if any(_CLIENT.match(it) for it in items) and any(_FIRM.match(it) for it in items):
            found.add(m.group(1).lower())
    return found


_DIRECT = re.compile(r"guard_client_firm\(\s*'(?:public\.)?([a-z0-9_]+)'", re.I)
_FOREACH = re.compile(
    r"FOREACH\s+\w+\s+IN\s+ARRAY\s+ARRAY\s*\[(?P<tables>.*?)\]\s*LOOP(?P<body>.*?)END\s+LOOP", re.I | re.S)


def tables_guarded_by(sql: str) -> set[str]:
    """Tables this text installs the check on: a direct call naming one, or a loop over a list that calls the installer."""
    clean = _strip_comments(sql)
    guarded = {t.lower() for t in _DIRECT.findall(clean)}
    for loop in _FOREACH.finditer(clean):
        if re.search(r"guard_client_firm\(", loop.group("body"), re.I):
            guarded.update(t.lower() for t in re.findall(r"'(?:public\.)?([a-z0-9_]+)'", loop.group("tables"), re.I))
    return guarded


def guard_gaps(migrations: dict[str, str]) -> dict[str, str]:
    """{table: migration that created it} for every table created from FIRST_GUARDED on and never guarded afterwards."""
    ordered = sorted(migrations)
    created: dict[str, str] = {}
    for name in ordered:
        if int(name.split("_", 1)[0]) < FIRST_GUARDED:
            continue
        for t in client_firm_tables_created_by(migrations[name]):
            created.setdefault(t, name)
    return {t: born for t, born in created.items()
            if t not in EXEMPT and not any(t in tables_guarded_by(migrations[n]) for n in ordered if n >= born)}


def _all_migrations() -> dict[str, str]:
    return {f.name: f.read_text(errors="ignore") for f in sorted(MIGRATIONS.glob("[0-9]*.sql"))
            if not f.name.endswith("_rollback.sql")}


# ── the reader has to actually find something ────────────────────────────────────────────────────────────────

def test_the_reader_finds_the_tables_that_have_both_columns():
    """An empty result would make the rule below pass against any migration set. Over EVERY migration, not only the guarded ones."""
    created: set[str] = set()
    for sql in _all_migrations().values():
        created |= client_firm_tables_created_by(sql)
    assert len(created) >= 120, f"only {len(created)} found: the reader has stopped seeing CREATE TABLE"
    for t in ("sales_quotations", "bills_of_entry", "income_tax_worksheets", "self_assessment_challans"):
        assert t in created, f"{t} is no longer found as a client and firm table"


def test_the_reader_tells_a_guarded_table_from_an_unguarded_one():
    made = ("CREATE TABLE IF NOT EXISTS public.widgets (id uuid PRIMARY KEY, firm_id uuid NOT NULL, client_id uuid NOT NULL, "
            "name text);")
    only_client = "CREATE TABLE public.gadgets (id uuid PRIMARY KEY, client_id uuid NOT NULL);"
    assert client_firm_tables_created_by(made) == {"widgets"}
    assert client_firm_tables_created_by(only_client) == set()
    assert client_firm_tables_created_by("-- CREATE TABLE ghosts (firm_id uuid, client_id uuid);") == set()
    assert tables_guarded_by("PERFORM public.guard_client_firm('widgets');") == {"widgets"}
    assert tables_guarded_by("PERFORM public.guard_client_firm('public.widgets'::regclass);") == {"widgets"}
    looped = "DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['widgets','sprockets'] LOOP PERFORM public.guard_client_firm(t); END LOOP; END $$;"
    assert tables_guarded_by(looped) == {"widgets", "sprockets"}
    assert tables_guarded_by("FOREACH t IN ARRAY ARRAY['widgets'] LOOP PERFORM 1; END LOOP;") == set()


def test_a_synthetic_gap_is_reported_and_a_later_sweep_closes_it():
    migs = {
        "566_widgets.sql": "CREATE TABLE widgets (id uuid, firm_id uuid, client_id uuid);",
        "567_other.sql": "SELECT 1;",
    }
    assert guard_gaps(migs) == {"widgets": "566_widgets.sql"}
    migs["567_other.sql"] = "SELECT public.guard_client_firm('widgets');"
    assert guard_gaps(migs) == {}
    # A table created before the first guarded number is the catalog test's, not this rule's.
    assert guard_gaps({"400_old.sql": "CREATE TABLE old (firm_id uuid, client_id uuid);"}) == {}


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_client_and_firm_table_a_migration_creates_asks_for_the_check():
    gaps = guard_gaps(_all_migrations())
    assert not gaps, (
        "These tables carry a client_id and a firm_id and no call of public.guard_client_firm('<table>'). Without it the database "
        "stores a row of one firm naming a client of another (the signed-in Partner branch of the assignment scope short-circuits, "
        "the firm policy asks firm_id alone, and a foreign key bypasses row security). Add `SELECT public.guard_client_firm('<table>');` "
        "to the migration that creates the table (565 is the pattern).\n  "
        + "\n  ".join(f"{t}  (created in {m})" for t, m in sorted(gaps.items())))


def test_migration_565_installs_the_check_on_every_table_that_has_both_columns_and_reports_what_it_found():
    sql = _strip_comments((MIGRATIONS / "565_a_row_names_a_client_of_its_own_firm_and_a_party_of_its_own_client.sql").read_text())
    assert "guard_client_firm(r.t)" in sql, "the catalog loop no longer calls the installer"
    assert "RAISE EXCEPTION 'migration 565: these tables still lack the client-in-firm triggers" in sql, "the closing check is gone"
    assert "RAISE WARNING 'migration 565:" in sql, "the apply report is gone: the runner keeps only a 'migration NNN:' warning"
    for fn in ("guard_client_firm", "assert_inserted_rows_name_a_client_of_their_firm", "assert_updated_row_names_a_client_of_its_firm"):
        assert fn in sql
    assert re.search(r"REVOKE ALL ON FUNCTION public\.guard_client_firm\(regclass\) FROM authenticated", sql), \
        "a signed-in role may run the installer"
