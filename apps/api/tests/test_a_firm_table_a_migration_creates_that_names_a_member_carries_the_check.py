"""A table or a column a migration adds that names a member of the row's firm asks for the member check when it is made (POST-A-361).

WHY THIS IS A RULE ABOUT MIGRATIONS
    Migration 566 gave every table that had a uuid `firm_id` and a foreign key to `users` the two triggers that refuse a row naming a
    member of another firm, through one installer, `public.guard_member_firm(table)`. Its closing check covers the tables and columns
    that existed THEN. A table created later, or a member column added later to a table that already has the triggers, has nothing
    until its own migration calls the installer again (the update trigger names its columns, so it does not learn a new one by itself).
    The real-Postgres catalog test (`test_566_..._pg`) only runs where there is a Postgres. This is the half the required mock-mode
    check can read: the migration text.

WHAT COUNTS
    A migration numbered above 566 that creates a table with a top-level `firm_id` and a column or table constraint that references
    `users`, or that adds a column referencing `users` to a table known to carry a `firm_id`, and no call of `guard_member_firm('<table>')`
    in that migration or a LATER one (a sweep that closes an earlier table is a legitimate fix). A call may name the table directly or sit
    in a `FOREACH ... IN ARRAY ARRAY[...] LOOP` over a list of tables.

WHAT IT DOES NOT DO
    It does not say the check is right (the real-Postgres test connects and attempts the statements), it cannot see a table created or
    altered by dynamic SQL (the catalog test finds that), and it does not read a column that names a member WITHOUT a foreign key: the
    installer cannot find one either, which is the limit migration 566 records.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.test_a_client_firm_table_a_migration_creates_carries_the_check import (
    _CREATE_TABLE, _FIRM, _strip_comments, _top_level_items,
)

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"

#: Migration 566 installed the check on every table that existed; a table or column made after it is this rule's.
FIRST_GUARDED = 567

#: A table that deliberately carries no such check, with the reason. Empty: none is known.
EXEMPT: dict[str, str] = {}

_REFERENCES_USERS = re.compile(r'REFERENCES\s+(?:public\.)?"?users"?\b', re.I)
_ALTER = re.compile(r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:public\.)?"?([a-z0-9_]+)"?\s+([^;]*);', re.I | re.S)
_ADD_FIRM = re.compile(r'ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"?firm_id"?\s', re.I)


def tables_created_with_a_member_key(sql: str) -> set[str]:
    """Tables this migration creates with a top-level `firm_id` and a reference to `users`."""
    clean = _strip_comments(sql)
    found: set[str] = set()
    for m in _CREATE_TABLE.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        items = _top_level_items(clean[m.end():i - 1])
        if any(_FIRM.match(it) for it in items) and any(_REFERENCES_USERS.search(it) for it in items):
            found.add(m.group(1).lower())
    return found


def tables_created_with_a_firm(sql: str) -> set[str]:
    clean = _strip_comments(sql)
    found: set[str] = set()
    for m in _CREATE_TABLE.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        if any(_FIRM.match(it) for it in _top_level_items(clean[m.end():i - 1])):
            found.add(m.group(1).lower())
    for m in _ALTER.finditer(clean):
        if _ADD_FIRM.search(m.group(2)):
            found.add(m.group(1).lower())
    return found


def tables_given_a_member_column(sql: str) -> set[str]:
    """Tables this migration ALTERs to add a column that references `users` (whether the table has a firm is the caller's question)."""
    clean = _strip_comments(sql)
    out: set[str] = set()
    for m in _ALTER.finditer(clean):
        for clause in re.split(r",\s*(?=ADD\s)", m.group(2), flags=re.I):
            if re.match(r"\s*ADD\s+COLUMN", clause, re.I) and _REFERENCES_USERS.search(clause):
                out.add(m.group(1).lower())
    return out


_DIRECT = re.compile(r"guard_member_firm\(\s*'(?:public\.)?([a-z0-9_]+)'", re.I)
_FOREACH = re.compile(
    r"FOREACH\s+\w+\s+IN\s+ARRAY\s+ARRAY\s*\[(?P<tables>.*?)\]\s*LOOP(?P<body>.*?)END\s+LOOP", re.I | re.S)


def tables_guarded_by(sql: str) -> set[str]:
    """Tables this text installs the member check on: a direct call naming one, or a loop over a list that calls the installer."""
    clean = _strip_comments(sql)
    guarded = {t.lower() for t in _DIRECT.findall(clean)}
    for loop in _FOREACH.finditer(clean):
        if re.search(r"guard_member_firm\(", loop.group("body"), re.I):
            guarded.update(t.lower() for t in re.findall(r"'(?:public\.)?([a-z0-9_]+)'", loop.group("tables"), re.I))
    return guarded


def guard_gaps(migrations: dict[str, str]) -> dict[str, str]:
    """{table: first migration whose need went unmet} for every table or column made from FIRST_GUARDED on that no call at or after it covers.

    Each creation of a table with a member key, and each member column added to a firm table, is its OWN need: a call that covered the
    table at its creation does not cover a column added two migrations later, because the update trigger names its columns."""
    ordered = sorted(migrations)
    firm_tables: set[str] = set()
    for name in ordered:
        firm_tables |= tables_created_with_a_firm(migrations[name])
    needs: list[tuple[str, str]] = []
    for name in ordered:
        if int(name.split("_", 1)[0]) < FIRST_GUARDED:
            continue
        needs += [(t, name) for t in sorted(tables_created_with_a_member_key(migrations[name]))]
        needs += [(t, name) for t in sorted(tables_given_a_member_column(migrations[name])) if t in firm_tables]
    gaps: dict[str, str] = {}
    for t, born in needs:
        if t in EXEMPT or t in gaps:
            continue
        if not any(t in tables_guarded_by(migrations[n]) for n in ordered if n >= born):
            gaps[t] = born
    return gaps


def _all_migrations() -> dict[str, str]:
    return {f.name: f.read_text(errors="ignore") for f in sorted(MIGRATIONS.glob("[0-9]*.sql"))
            if not f.name.endswith("_rollback.sql")}


# ── the reader has to actually find something ────────────────────────────────────────────────────────────────

def test_the_reader_finds_the_tables_that_have_a_firm_and_a_member_key():
    """An empty result would make the rule below pass against any migration set. Over EVERY migration, not only the guarded ones."""
    found: set[str] = set()
    for sql in _all_migrations().values():
        found |= tables_created_with_a_member_key(sql)
    assert len(found) >= 40, f"only {len(found)} found: the reader has stopped seeing CREATE TABLE ... REFERENCES users"
    for t in ("godowns", "sales_quotations", "stock_count_sessions"):
        assert t in found, f"{t} is no longer found as a firm table with a member key"


def test_the_reader_tells_a_guarded_table_from_an_unguarded_one():
    made = ("CREATE TABLE IF NOT EXISTS public.widgets (id uuid PRIMARY KEY, firm_id uuid NOT NULL, "
            "created_by uuid REFERENCES public.users(id), name text);")
    table_level = ("CREATE TABLE gadgets (id uuid, firm_id uuid, reviewer uuid, "
                   "CONSTRAINT g_fk FOREIGN KEY (reviewer) REFERENCES users (id));")
    no_firm = "CREATE TABLE public.sprockets (id uuid PRIMARY KEY, created_by uuid REFERENCES public.users(id));"
    other_table = "CREATE TABLE public.cogs (id uuid, firm_id uuid, owner uuid REFERENCES public.users_archive(id));"
    assert tables_created_with_a_member_key(made) == {"widgets"}
    assert tables_created_with_a_member_key(table_level) == {"gadgets"}
    assert tables_created_with_a_member_key(no_firm) == set()
    assert tables_created_with_a_member_key(other_table) == set()
    assert tables_created_with_a_member_key("-- CREATE TABLE ghosts (firm_id uuid, by uuid REFERENCES users(id));") == set()
    assert tables_given_a_member_column(
        "ALTER TABLE public.widgets ADD COLUMN IF NOT EXISTS reviewed_by uuid REFERENCES public.users(id), ADD COLUMN note text;") == {"widgets"}
    assert tables_given_a_member_column("ALTER TABLE widgets ADD COLUMN note text;") == set()
    assert tables_given_a_member_column("ALTER TABLE widgets ADD CONSTRAINT k FOREIGN KEY (a) REFERENCES users(id);") == set()
    assert tables_guarded_by("PERFORM public.guard_member_firm('widgets');") == {"widgets"}
    looped = ("DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['widgets','sprockets'] LOOP "
              "PERFORM public.guard_member_firm(t); END LOOP; END $$;")
    assert tables_guarded_by(looped) == {"widgets", "sprockets"}
    assert tables_guarded_by("FOREACH t IN ARRAY ARRAY['widgets'] LOOP PERFORM 1; END LOOP;") == set()


def test_a_synthetic_gap_is_reported_a_later_call_closes_it_and_a_new_column_on_a_firm_table_counts():
    migs = {
        "567_widgets.sql": "CREATE TABLE widgets (id uuid, firm_id uuid, created_by uuid REFERENCES users(id));",
        "568_other.sql": "SELECT 1;",
    }
    assert guard_gaps(migs) == {"widgets": "567_widgets.sql"}
    migs["568_other.sql"] = "SELECT public.guard_member_firm('widgets');"
    assert guard_gaps(migs) == {}
    # A column added later to a table that has a firm: the installer has to be called again, because the trigger names its columns.
    migs["569_more.sql"] = "ALTER TABLE widgets ADD COLUMN reviewed_by uuid REFERENCES users(id);"
    assert guard_gaps(migs) == {"widgets": "569_more.sql"}
    migs["570_again.sql"] = "SELECT public.guard_member_firm('widgets');"
    assert guard_gaps(migs) == {}
    # A column on a table the migrations never gave a firm is not this rule's; one made before the first guarded number is the catalog test's.
    assert guard_gaps({"567_a.sql": "ALTER TABLE nofirm ADD COLUMN x uuid REFERENCES users(id);"}) == {}
    assert guard_gaps({"400_old.sql": "CREATE TABLE old (firm_id uuid, by uuid REFERENCES users(id));"}) == {}


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_table_or_column_a_migration_makes_that_names_a_member_asks_for_the_check():
    gaps = guard_gaps(_all_migrations())
    assert not gaps, (
        "These tables name a member of the row's firm (a foreign key to users) and no later call of "
        "public.guard_member_firm('<table>') makes the database refuse a row naming another firm's member. Add "
        "`SELECT public.guard_member_firm('<table>');` to the migration that creates the table or adds the column (566 is the "
        "pattern; the update trigger names its columns, so a column added later needs the call again).\n  "
        + "\n  ".join(f"{t}  (made in {m})" for t, m in sorted(gaps.items())))


def test_migration_566_installs_the_check_on_every_table_that_has_a_member_key_and_reports_what_it_found():
    sql = _strip_comments((MIGRATIONS / "566_a_row_names_a_member_of_its_own_firm.sql").read_text())
    assert "guard_member_firm(r.t)" in sql, "the catalog loop no longer calls the installer"
    assert "RAISE EXCEPTION 'migration 566: these tables still lack the member-in-firm triggers" in sql, "the closing check is gone"
    assert "RAISE WARNING 'migration 566:" in sql, "the apply report is gone: the runner keeps only a 'migration NNN:' warning"
    for fn in ("guard_member_firm", "member_columns_of", "assert_inserted_rows_name_a_member_of_their_firm",
               "assert_updated_row_names_a_member_of_its_firm"):
        assert fn in sql
    assert re.search(r"REVOKE ALL ON FUNCTION public\.guard_member_firm\(regclass\) FROM authenticated", sql), \
        "a signed-in role may run the installer"
