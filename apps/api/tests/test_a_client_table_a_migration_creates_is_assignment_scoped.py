"""A `client_id` table a migration creates carries its assignment scope AT CREATION.

WHY THIS IS A RULE ABOUT MIGRATIONS AND NOT ABOUT WHAT THE BROWSER READS

`test_a_table_the_browser_reads_is_assignment_scoped_pg` holds the line for the
tables the frontend names in a `.from(...)` call, and says in its own header why
it stops there: "nothing reaches the rest from the browser". That premise is the
kind that expires quietly, and migration 455 is the measurement. It created
`income_tax_worksheets` and `ais_computation_decisions` — a client's salary, rent
and interest working papers — with firm-wide RLS, role guards and
`GRANT SELECT, INSERT, UPDATE, DELETE ... TO authenticated`, and its own header
argued the scope policy away ("it would protect a path nothing uses"). The web
app does not read either table, so the browser guard could not fire. But
PostgREST does not ask which tables a screen happens to use: a Manager assigned
to client A, holding the anon key and their own JWT, can query client B's
working papers directly, and so can an Executive write them. On that path RLS is
the only control (CLAUDE.md, "The frontend's second data path"), and the
firm-wide policy scopes to the firm and stops there.

Migration 084's one-shot loop has never run again, so a table is firm-wide
unless the migration that creates it says otherwise. Every `client_id` table
created since migration 370 said so — thirty-nine of them — until this one. The
cheapest place to hold that is the migration text itself, which the required
`pytest — mock mode` check can read with no database, and it does not depend on
whether the table is read from a screen today: Supabase's default privileges
hand `authenticated` every new table in `public` anyway, so "nothing reads it" is
not the same as "nothing can".

WHAT COUNTS AS SCOPED, AND WHAT DOES NOT

A policy that is RESTRICTIVE (a PERMISSIVE one ORs with the others and WIDENS
access), covers FOR ALL (a RESTRICTIVE policy on SELECT alone leaves INSERT,
UPDATE and DELETE open), and asks `can_access_client(client_id::text)` — the one
helper that lets a Partner through and everyone else needs an assignment row.
It may be written out as a `CREATE POLICY ... ON public.<table>` or issued from a
`FOREACH` loop over a list of tables; both shapes are in use since 370 and the
rule is about the effect, not the spelling.

WHAT THIS DELIBERATELY DOES NOT ASSERT

That the policy is correct — `test_income_tax_worksheets_and_ais_decisions_pg`
connects as `authenticated` with a real JWT and attempts the statements. This is
the cheap half, the one that cannot be skipped for want of a Postgres.
"""
from __future__ import annotations

import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"

# Migration 370 is the one that records 084's loop never runs again, so it is
# the first migration whose author could not have assumed the table was scoped
# for them.
FIRST = 370

# A table that is deliberately NOT assignment-scoped, with the reason. Empty:
# every client_id table created since 370 is scoped. A portal-side table whose
# RESTRICTIVE policy would deny a portal principal their own record is the
# legitimate case (see _PORTAL_SIDE in the browser-read guard); an entry goes
# here with its reason, never silently.
EXEMPT: dict[str, str] = {}


# ── reading the migration text ───────────────────────────────────────────────

def _strip_comments(sql: str) -> str:
    """Drop `--` and `/* */` comments, leaving string literals alone.

    A comment may say "RESTRICTIVE" or "can_access_client" — 455's own header
    did, to explain why it had no such policy — and a scan that read comments
    would take an explanation for the thing it explains. Quote-aware, because a
    COMMENT ON string can contain `--` and an apostrophe in a comment ("084's")
    must not open a string that swallows the rest of the file.
    """
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


_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?([a-z0-9_]+)"?\s*\(', re.I)
_CLIENT_ID_COLUMN = re.compile(r'^\s*"?client_id"?\s', re.I)


def client_tables_created_by(sql: str) -> set[str]:
    """Tables this migration creates with a top-level `client_id` column."""
    clean = _strip_comments(sql)
    found: set[str] = set()
    for m in _CREATE_TABLE.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        body = clean[m.end():i - 1]
        if any(_CLIENT_ID_COLUMN.match(item) for item in _top_level_items(body)):
            found.add(m.group(1).lower())
    return found


_POLICY = re.compile(r"CREATE\s+POLICY\b[^;]*;", re.I)
_FOREACH = re.compile(
    r"FOREACH\s+\w+\s+IN\s+ARRAY\s+ARRAY\s*\[(?P<tables>.*?)\]\s*LOOP(?P<body>.*?)END\s+LOOP",
    re.I | re.S)
_NARROWED = re.compile(r"\bFOR\s+(SELECT|INSERT|UPDATE|DELETE)\b", re.I)


def _is_scope_policy(stmt: str) -> bool:
    return (re.search(r"\bRESTRICTIVE\b", stmt, re.I) is not None
            and re.search(r"can_access_client\(\s*client_id::text\s*\)", stmt, re.I) is not None
            and not _NARROWED.search(stmt))


def tables_scoped_by(sql: str) -> set[str]:
    """Tables this text puts a RESTRICTIVE, FOR ALL, can_access_client policy on."""
    clean = _strip_comments(sql)
    scoped: set[str] = set()

    for stmt in _POLICY.findall(clean):
        if not _is_scope_policy(stmt):
            continue
        on = re.search(r'\bON\s+(?:public\.)?"?([a-z0-9_]+)"?', stmt, re.I)
        # `ON public.%I` / `ON public.%1$I` names no table here: the loop form.
        if on and not on.group(1).startswith("%"):
            scoped.add(on.group(1).lower())

    for loop in _FOREACH.finditer(clean):
        if any(_is_scope_policy(stmt) for stmt in _POLICY.findall(loop.group("body"))):
            scoped.update(t.lower() for t in re.findall(r"'([a-z0-9_]+)'", loop.group("tables"), re.I))
    return scoped


def scope_gaps(migrations: dict[str, str]) -> dict[str, str]:
    """{table: migration that created it} for every table never scoped.

    A table counts as scoped if the migration that created it, or any LATER one,
    scopes it — a sweep that closes an earlier table is a legitimate fix, and
    asking only the creating file would call it a gap.
    """
    ordered = sorted(migrations)
    created: dict[str, str] = {}
    for name in ordered:
        for t in client_tables_created_by(migrations[name]):
            created.setdefault(t, name)
    gaps: dict[str, str] = {}
    for t, born in created.items():
        if t in EXEMPT:
            continue
        if not any(t in tables_scoped_by(migrations[n]) for n in ordered if n >= born):
            gaps[t] = born
    return gaps


def _real_migrations() -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(MIGRATIONS.glob("[0-9]*.sql")):
        if f.name.endswith("_rollback.sql"):
            continue
        if int(f.name.split("_", 1)[0]) >= FIRST:
            out[f.name] = f.read_text(errors="ignore")
    return out


# ── the scanners have to actually find something ─────────────────────────────

def test_the_scan_finds_the_client_tables_it_is_supposed_to():
    """An empty result would make the rule below pass against any migration set."""
    created: set[str] = set()
    for sql in _real_migrations().values():
        created |= client_tables_created_by(sql)
    assert len(created) >= 35, f"only found {len(created)}: {sorted(created)}"
    # Named, so a rename or a parser regression shows up here and not as a
    # silently emptier scan.
    for t in ("bills_of_entry", "self_assessment_challans", "sales_quotations",
              "income_tax_worksheets", "ais_computation_decisions"):
        assert t in created, f"{t} is no longer found as a client_id table"


def test_the_scope_reader_finds_both_spellings_in_use():
    """Explicit CREATE POLICY (389) and a FOREACH loop (392) both exist since 370."""
    migs = _real_migrations()
    explicit = next(n for n in migs if n.startswith("389_"))
    looped = next(n for n in migs if n.startswith("392_"))
    assert "bills_of_entry" in tables_scoped_by(migs[explicit])
    assert {"sales_quotations", "delivery_challan_lines"} <= tables_scoped_by(migs[looped])


# ── the rule ─────────────────────────────────────────────────────────────────

def test_every_client_table_a_migration_creates_is_assignment_scoped():
    gaps = scope_gaps(_real_migrations())
    assert not gaps, (
        "These tables carry a client_id and no RESTRICTIVE FOR ALL "
        "can_access_client(client_id::text) policy. Migration 084's loop has "
        "never run again, so a table created now is firm-wide unless its own "
        "migration says otherwise: a Manager, Executive or Reviewer assigned to "
        "NOTHING can read — and, below Partner, write — every client's rows "
        "over PostgREST, where RLS is the only control. Whether a screen reads "
        "the table today is not the question; `authenticated` can.\n"
        "Add the policy (389 and 407 are the pattern), or, if the table is "
        "portal-side and a RESTRICTIVE policy would deny a portal principal "
        "their own record, add it to EXEMPT with the reason.\n  "
        + "\n  ".join(f"{t}  (created in {m})" for t, m in sorted(gaps.items())))


def test_the_two_tables_migration_455_creates_are_scoped():
    """Named, because the rule passes if either stops being created — and a
    table dropping out of the scan is not the same as being scoped."""
    migs = _real_migrations()
    name = next(n for n in migs if n.startswith("455_"))
    assert {"income_tax_worksheets", "ais_computation_decisions"} <= tables_scoped_by(migs[name])


def test_no_exemption_is_kept_without_a_reason_and_a_real_table():
    created: set[str] = set()
    for sql in _real_migrations().values():
        created |= client_tables_created_by(sql)
    for t, why in EXEMPT.items():
        assert t in created, f"{t} is exempted but no migration creates it"
        assert len(why.split()) >= 6, f"{t}: an exemption has to say why"


# ── the checker is not vacuous: each way of getting it wrong is caught ───────

_TABLE = """
CREATE TABLE IF NOT EXISTS public.widgets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id uuid NOT NULL,
  client_id uuid NOT NULL REFERENCES public.clients(id),
  note text CHECK (note ~ '^[a-z]{1,3}$')
);
"""

_SCOPE = """
CREATE POLICY "widgets_assignment_scope" ON public.widgets
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
"""


def _gaps(*texts: str) -> dict[str, str]:
    return scope_gaps({f"{400 + i}_m.sql": t for i, t in enumerate(texts)})


def test_a_table_with_no_scope_policy_is_a_gap():
    assert set(_gaps(_TABLE)) == {"widgets"}


def test_the_explicit_policy_closes_it():
    assert _gaps(_TABLE + _SCOPE) == {}


def test_a_later_migration_may_close_an_earlier_table():
    assert _gaps(_TABLE, _SCOPE) == {}


def test_an_earlier_migration_cannot_close_a_later_table():
    assert set(_gaps(_SCOPE, _TABLE)) == {"widgets"}


def test_a_permissive_policy_widens_access_and_is_not_a_scope():
    assert set(_gaps(_TABLE + _SCOPE.replace("AS RESTRICTIVE ", ""))) == {"widgets"}


def test_a_policy_for_select_alone_leaves_the_writes_open():
    assert set(_gaps(_TABLE + _SCOPE.replace("FOR ALL", "FOR SELECT"))) == {"widgets"}


def test_a_policy_that_does_not_ask_the_assignment_helper_is_not_a_scope():
    firm_only = _SCOPE.replace("public.can_access_client(client_id::text)",
                               "firm_id = public.get_my_firm_id()")
    assert set(_gaps(_TABLE + firm_only)) == {"widgets"}


def test_a_comment_explaining_the_absence_is_not_the_policy():
    """455's own header said so in prose — "the assignment-scope policy ... is
    not added" — and a scan reading comments would have called that scoped."""
    commented = "".join(f"-- {ln}\n" for ln in _SCOPE.strip().splitlines())
    assert set(_gaps(_TABLE + commented)) == {"widgets"}


def test_the_policy_for_another_table_does_not_close_this_one():
    other = _SCOPE.replace("widgets", "gadgets")
    assert set(_gaps(_TABLE + other)) == {"widgets"}


def test_a_loop_closes_every_table_in_its_list_and_only_those():
    loop = """
    DO $$
    DECLARE t text;
    BEGIN
      FOREACH t IN ARRAY ARRAY['widgets'] LOOP
        EXECUTE format(
          'CREATE POLICY "%1$s_assignment_scope" ON public.%1$I '
          'AS RESTRICTIVE FOR ALL '
          'USING (public.can_access_client(client_id::text)) '
          'WITH CHECK (public.can_access_client(client_id::text))', t);
      END LOOP;
    END $$;
    """
    second = _TABLE.replace("widgets", "gadgets")
    assert set(_gaps(_TABLE + second + loop)) == {"gadgets"}


def test_a_loop_that_issues_only_the_role_guards_is_not_a_scope():
    """The exact shape 455 had: a loop over the tables creating firm and role
    policies, none of which is the assignment rule."""
    loop = """
    DO $$
    DECLARE t text;
    BEGIN
      FOREACH t IN ARRAY ARRAY['widgets'] LOOP
        EXECUTE format(
          'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
          'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Executive');
      END LOOP;
    END $$;
    """
    assert set(_gaps(_TABLE + loop)) == {"widgets"}


def test_a_client_id_inside_a_check_is_not_a_client_id_column():
    """`client_id` named in a constraint, not declared as a column, is not a
    client table — a table keyed on something else must not be demanded a scope."""
    no_column = """
    CREATE TABLE public.notes (
      id uuid PRIMARY KEY,
      firm_id uuid NOT NULL,
      CONSTRAINT notes_check CHECK (firm_id IS NOT NULL OR client_id_text IS NULL)
    );
    """
    assert client_tables_created_by(no_column) == set()
