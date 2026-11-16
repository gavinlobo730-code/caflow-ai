"""The schema as the committed FILES describe it, for the guards that run where no database does (POST-A-038).

WHY THIS EXISTS
    Three guards hold the browser to the schema: the columns it names (`test_frontend_columns_exist_pg.py`), the status values it
    writes or compares (`test_frontend_status_values_match_the_check_pg.py`) and the auth ids it must not write into a key to
    users (`test_frontend_never_writes_an_auth_id_into_a_users_fk_pg.py`). All three read a migration-built Postgres, so they
    skip in the `browser contract` job, which is the only job a frontend-only pull request runs. This module answers the same
    three questions from what is committed, so `test_frontend_schema_guards_read_the_committed_files.py` can ask them there.

WHERE EACH ANSWER COMES FROM
    The migrations are REPLAYED in the order the runner applies them, one statement at a time (comments removed, a `DO $$` block's
    statements read like any other): CREATE TABLE (and nothing at all from a CREATE TABLE IF NOT EXISTS on a table that is already
    there, which is a no-op in Postgres too), ALTER TABLE ... ADD / DROP / RENAME of a column, a constraint or the table, DROP
    TABLE and DROP VIEW, a view's definition, and migration 319's constraints written as data.

    * COLUMNS: the production snapshot (`tests/fixtures/production_schema_*.json`, the newest, through `production_types`) united
      with the columns the replay leaves on each table and view. A view's select list is not parsed: every word of its definition
      stands in for its columns, which knows more names than the view has and never fewer. A name is unknown only when it is in
      NEITHER the snapshot NOR a database the migrations build.
    * STATUS VALUES: for each table that still has a CHECK on `status` once every migration ran, every quoted literal any CHECK on
      its `status` has EVER allowed (a later migration that narrows the CHECK does not narrow this). The guards snapshot
      (`tests/fixtures/production_guards_*.json`) cannot help here: it records a CHECK's kind and a HASH of its expression, never
      the values.
    * KEYS TO USERS: the columns the replay leaves as a foreign key to public.users, by constraint name, through DROP CONSTRAINT,
      DROP COLUMN, DROP TABLE and both RENAMEs (a key to auth.users is not one). The guards snapshot records a foreign key's name
      and never what it references, so it cannot answer this either.

WHAT IT CANNOT SEE, AND WHAT HOLDS IT
    It is a reader of SQL text, not a database. DDL built at run time (`EXECUTE format(...)`, apart from 319's shape), a column a
    view gets by `SELECT *`, a statement after the one that fails in a migration that fails part-way on a fresh database, a
    column or key production has that nothing committed declares, and a column a migration dropped after the snapshot was taken
    (the snapshot still has it). `test_the_schema_read_from_the_committed_files_agrees_with_a_migration_built_database_pg.py`
    holds the reading to a real migration-built database in the real-Postgres job, in the direction each guard needs: every real
    column is known and every real status value allowed (so the mock guards cannot fail where the real ones pass), the tables
    with a status CHECK are the same set, and the keys to users are the same set both ways round.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from tests import production_types

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"

_IDENT = r'"?([a-z_][a-z0-9_]*)"?'
_TABLE = rf'(?:public\.)?{_IDENT}'
_NOT_A_COLUMN = frozenset({"constraint", "primary", "unique", "foreign", "check", "exclude", "like"})
_USERS = re.compile(r'\breferences\s+(?:public\.)?"?users"?(?![a-z0-9_.])', re.I)
_AS_DATA = re.compile(r"\(\s*\$(\w*)\$([a-z_][a-z0-9_]*)\$\1\$\s*,\s*\$\1\$([a-z_][a-z0-9_]*)\$\1\$\s*,\s*\$\1\$(.*?)\$\1\$\s*\)")


def migration_files(directory: Path = MIGRATIONS) -> list[Path]:
    """The migrations in the order the runner applies them: numeric prefix, then name; no rollback, no `_` helper."""
    files = [p for p in directory.glob("*.sql") if p.name[:1].isdigit() and "rollback" not in p.name]
    return sorted(files, key=lambda p: (int(re.match(r"\d+", p.name).group(0)), p.name))


def _quoted_end(sql: str, i: int) -> int:
    """Index just past the single-quoted literal that opens at `i` ('' is an escaped quote; E'..' takes backslashes)."""
    escapes = i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_"))
    j = i + 1
    while j < len(sql):
        if escapes and sql[j] == "\\":
            j += 2
            continue
        if sql[j] == "'":
            if sql.startswith("''", j):
                j += 2
                continue
            return j + 1
        j += 1
    return j


def statements(sql: str) -> list[str]:
    """The file cut at every `;` outside a quoted literal, comments removed, lower-cased outside the literals, and the literals
    kept as written (a CHECK's values are in them, and 'Filed' is not 'filed').

    A dollar-quoted body is NOT skipped: a `DO $$ ... ALTER TABLE ... $$` block is how many migrations add a column or a key
    conditionally, and its statements are read like any other."""
    out, buf, i, n = [], [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = _quoted_end(sql, i)
            buf.append(sql[i:j])
            i = j
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            buf.append(" ")
        elif c == ";":
            out.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(c.lower())                         # an unquoted name is folded to lower case, as Postgres folds it
            i += 1
    out.append("".join(buf))
    return [s for s in (" ".join(x.split()) for x in out) if s]


def _balanced(text: str, open_paren: int) -> str:
    """The text inside the parenthesis that opens at `open_paren` (quotes respected)."""
    depth, i = 0, open_paren
    while i < len(text):
        c = text[i]
        if c == "'":
            i = _quoted_end(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
        i += 1
    return text[open_paren + 1:]


def _top_level_split(text: str) -> list[str]:
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        c = text[i]
        if c == "'":
            i = _quoted_end(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _status_values(clause: str) -> set[str]:
    """The quoted literals of every CHECK in this clause that names the column `status` itself (not `filing_status`)."""
    values: set[str] = set()
    for m in re.finditer(r"\bcheck\s*\(", clause, re.I):
        expr = _balanced(clause, m.end() - 1)
        if re.search(r"(?<![a-z0-9_.])status(?![a-z0-9_])", expr, re.I):
            values |= set(re.findall(r"'((?:[^']|'')*)'", expr))
    return {v.replace("''", "'") for v in values}


class _Replay:
    """Columns, status values and keys to users, as the migrations leave them."""

    def __init__(self):
        self.live: dict[str, set[str]] = {}               # replayed: the columns each table or view has once every migration ran
        self.status: dict[str, set[str]] = {}             # UNION over history: every value a CHECK on `status` ever allowed
        self.status_checks: dict[str, set[str]] = {}      # replayed: table -> the names of the CHECKs on `status` it still has
        self.keys: dict[str, dict[str, str]] = {}         # replayed: table -> {constraint name: column} for keys to users

    def _status_check(self, table: str, clause: str, default_name: str) -> None:
        values = _status_values(clause)
        if values:
            name = re.search(r"\bconstraint\s+" + _IDENT + r"\s+check\b", clause, re.I)
            self.status.setdefault(table, set()).update(values)
            self.status_checks.setdefault(table, set()).add(name.group(1) if name else default_name[:63])

    # ── one clause of a CREATE TABLE body or an ALTER TABLE ... ADD ──
    def _column(self, table: str, column: str, definition: str, *, adding: bool) -> None:
        if adding and column in self.live.setdefault(table, set()):
            return                                        # ADD COLUMN IF NOT EXISTS on a column that is there does nothing
        self.live[table].add(column)
        self._status_check(table, definition, f"{table}_{column}_check")
        if _USERS.search(definition):
            name = re.search(r"\bconstraint\s+" + _IDENT, definition, re.I)
            self.keys.setdefault(table, {})[name.group(1) if name else f"{table}_{column}_fkey"[:63]] = column

    def _constraint(self, table: str, clause: str) -> None:
        self._status_check(table, clause, f"{table}_status_check")
        fk = re.search(r"\bforeign\s+key\s*\(\s*" + _IDENT, clause, re.I)
        if fk and _USERS.search(clause):
            name = re.match(r"constraint\s+" + _IDENT, clause, re.I)
            self.keys.setdefault(table, {})[name.group(1) if name else f"{table}_{fk.group(1)}_fkey"[:63]] = fk.group(1)

    def _create_table(self, stmt: str) -> None:
        m = re.search(r"\bcreate\s+(?:(?:global\s+|local\s+)?(?:temp|temporary|unlogged)\s+)?table\s+"
                      r"(if\s+not\s+exists\s+)?" + _TABLE + r"\s*\(", stmt, re.I)
        if not m:
            return
        table = m.group(2)
        if m.group(1) and table in self.live:
            # CREATE TABLE IF NOT EXISTS on a table that is there does NOTHING, and its column list is not a column list: migration
            # 023 declares `client_documents.label` that way, the table 014 made has `description`, and a page that believed 023
            # could not load (the real guard pins `client_documents.label`). So none of it is read.
            return
        self.live[table] = set()
        self.keys[table] = {}
        self.status_checks[table] = set()
        for part in _top_level_split(_balanced(stmt, m.end() - 1)):
            first = part.split()[0].strip('"').lower()
            if first in _NOT_A_COLUMN:
                self._constraint(table, part)
            else:
                self._column(table, first, part, adding=False)

    def _alter_table(self, stmt: str) -> None:
        m = re.search(r"\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?" + _TABLE + r"\s+(.*)$", stmt, re.I)
        if not m:
            return
        table, rest = m.group(1), m.group(2)
        renamed = re.match(r"rename\s+to\s+" + _TABLE, rest, re.I)
        if renamed:
            new = renamed.group(1)
            for store in (self.status, self.status_checks, self.live, self.keys):
                if table in store:
                    store[new] = store.pop(table)
            return
        for action in _top_level_split(rest):
            self._alter_action(table, action)

    def _alter_action(self, table: str, action: str) -> None:
        low = action.lower()
        if low.startswith("add "):
            body = action[4:].strip()
            first = body.split()[0].lower() if body.split() else ""
            if first in _NOT_A_COLUMN:
                self._constraint(table, body)
                return
            col = re.match(r"(?:column\s+)?(?:if\s+not\s+exists\s+)?" + _IDENT, body, re.I)
            if col:
                self._column(table, col.group(1), body, adding=True)
        elif low.startswith("drop constraint"):
            name = re.match(r"drop\s+constraint\s+(?:if\s+exists\s+)?" + _IDENT, action, re.I)
            if name:
                self.keys.get(table, {}).pop(name.group(1), None)
                self.status_checks.get(table, set()).discard(name.group(1))
        elif low.startswith("drop "):
            col = re.match(r"drop\s+(?:column\s+)?(?:if\s+exists\s+)?" + _IDENT, action, re.I)
            if col:
                self.live.get(table, set()).discard(col.group(1))
                if col.group(1) == "status":
                    self.status_checks.pop(table, None)
                for name, c in list(self.keys.get(table, {}).items()):
                    if c == col.group(1):
                        del self.keys[table][name]
        elif low.startswith("rename "):
            cons = re.match(r"rename\s+constraint\s+" + _IDENT + r"\s+to\s+" + _IDENT, action, re.I)
            col = re.match(r"rename\s+(?:column\s+)?" + _IDENT + r"\s+to\s+" + _IDENT, action, re.I)
            if cons:
                keys = self.keys.get(table, {})
                if cons.group(1) in keys:
                    keys[cons.group(2)] = keys.pop(cons.group(1))
                checks = self.status_checks.get(table, set())
                if cons.group(1) in checks:
                    checks.discard(cons.group(1))
                    checks.add(cons.group(2))
            elif col:
                old, new = col.group(1), col.group(2)
                live = self.live.setdefault(table, set())
                live.discard(old)
                live.add(new)
                for name, c in list(self.keys.get(table, {}).items()):
                    if c == old:
                        self.keys[table][name] = new

    def _drop_table(self, stmt: str) -> None:
        m = re.search(r"\bdrop\s+(?:materialized\s+)?(?:table|view)\s+(?:if\s+exists\s+)?(.*)$", stmt, re.I)
        if not m:
            return
        for name in re.findall(_TABLE, re.sub(r"\b(cascade|restrict)\b", "", m.group(1), flags=re.I)):
            self.live.pop(name, None)
            self.keys.pop(name, None)
            self.status_checks.pop(name, None)

    def _view(self, stmt: str) -> None:
        m = re.search(r"\bcreate\s+(?:or\s+replace\s+)?(?:materialized\s+)?view\s+(?:if\s+not\s+exists\s+)?" + _TABLE,
                      stmt, re.I)
        if m:
            # A view's columns are its select list, which is not parsed: every word of the definition stands in for them,
            # which knows more names than the view has and never fewer. CREATE OR REPLACE replaces them.
            self.live[m.group(1)] = set(re.findall(r"[a-z_][a-z0-9_]*", stmt[m.end():].lower()))

    def _declared_as_data(self, stmt: str) -> None:
        """Migration 319's shape: constraints written as DATA, `($d$table$d$, $d$name$d$, $d$definition$d$)` rows a loop hands to
        `EXECUTE format('ALTER TABLE ... ADD CONSTRAINT ...')` when the table is there and the name is not. Read as the ALTER
        TABLE the loop runs."""
        for _tag, table, name, definition in _AS_DATA.findall(stmt):
            if table in self.live and name not in self.keys.get(table, {}):
                self._constraint(table, f"constraint {name} {definition}")

    def read(self, stmt: str) -> None:
        self._declared_as_data(stmt)
        head = stmt.lower()
        # A statement may follow a `DO $$ BEGIN` or an IF inside a block, so each shape is searched for, not anchored.
        if re.search(r"\bcreate\s+(?:or\s+replace\s+)?(?:materialized\s+)?view\b", head):
            self._view(stmt)
        elif re.search(r"\bcreate\s+(?:(?:global\s+|local\s+)?(?:temp|temporary|unlogged)\s+)?table\b", head):
            self._create_table(stmt)
        elif re.search(r"\balter\s+table\b", head):
            self._alter_table(stmt)
        elif re.search(r"\bdrop\s+(?:materialized\s+)?(?:table|view)\b", head):
            self._drop_table(stmt)


@lru_cache(maxsize=1)
def _replayed() -> _Replay:
    replay = _Replay()
    for path in migration_files():
        for stmt in statements(path.read_text(encoding="utf-8", errors="replace")):
            replay.read(stmt)
    return replay


def snapshot_columns() -> set[str]:
    """{"table.column"} in the newest production schema snapshot."""
    return {f"{t}.{c}" for t, cols in production_types._SCHEMA.items() for c in cols}


def migration_columns() -> set[str]:
    """{"table.column"} a database built from every migration has, as the replay reads it."""
    return {f"{t}.{c}" for t, cols in _replayed().live.items() for c in cols}


@lru_cache(maxsize=1)
def known_columns() -> frozenset[str]:
    """{"table.column"}: in the production snapshot, or in a database built from every migration."""
    return frozenset(snapshot_columns() | migration_columns())


def status_values(replay: "_Replay | None" = None) -> dict[str, set[str]]:
    """table -> every value any migration's CHECK on its `status` has ever allowed, for the tables that still HAVE such a CHECK.

    A table whose CHECK was dropped (or whose table was) is left out, as the real guard leaves it out: a file reading only that
    table has nothing to be measured against, and measuring it against values the database no longer enforces would report
    a write the database accepts."""
    r = replay or _replayed()
    return {t: set(r.status[t]) for t, names in r.status_checks.items() if names and r.status.get(t)}


def users_keys(replay: "_Replay | None" = None) -> dict[str, set[str]]:
    """table -> the columns the migrations leave as a foreign key to public.users."""
    out: dict[str, set[str]] = {}
    for table, keys in (replay or _replayed()).keys.items():
        for column in keys.values():
            out.setdefault(table, set()).add(column)
    return out
