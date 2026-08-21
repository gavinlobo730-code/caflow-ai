"""Pull every column name the BACKEND writes into a PostgREST query.

The counterpart to _frontend_select_parser.py, for `db.table("x")…` chains in
apps/api. That file has to model TypeScript with regexes; this one does not —
the backend is Python, so it uses `ast`, which reads multi-line chains,
comments and odd formatting exactly and cannot be fooled by any of them.

WHAT IT READS

    db.table("t").select("a, b").eq("c", v).order("d").execute()
                  ^^^^^^^^^^^^^  ^^^^^^^^^  ^^^^^^^^^
    db.table("t").insert({"a": 1, "b": 2}).execute()
                         ^^^^^^^^^^^^^^^^
    db.table("t").or_("a.eq.true,b.eq.false")
                      ^^^^^^^^^^^^^^^^^^^^^

The .or_() arm exists because of a live miss. A one-off sweep that read only
.eq()-style filters passed relationships.py clean while it filtered on
section_186_flagged — a column that did not exist — because the name was buried
in an or_() string. Anything that reads only the obvious call shapes will keep
missing that one.

WHAT IT CANNOT READ, AND WHY THAT IS TRACKED
    A table or column that arrives as a variable, an f-string or a constant
    (`db.table(TABLE)`, `.select(cols)`). Those are counted and returned, not
    ignored: test_backend_columns_exist_pg.py budgets them, so the blind spot
    has a number on it and cannot quietly grow. A parser that silently stops
    matching is the main way a check like this rots — it keeps passing while
    checking nothing.

    Embedded resources (`.select("id, lines(amount)")`) name a RELATION, not a
    column, so the embedded head is skipped rather than reported as a phantom.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Filters whose FIRST argument is a column name.
FILTER_METHODS = frozenset({
    "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is_", "in_",
    "contains", "contained_by", "range_gt", "range_gte", "range_lt",
    "range_lte", "overlaps", "text_search", "not_", "order",
})
WRITE_METHODS = frozenset({"insert", "update", "upsert"})


def _relation_of(node: ast.Call) -> str | None:
    """The table a chain is rooted at, or None if it is not a PostgREST chain.

    Walks .func.value inward until it finds .table("literal"). A chain rooted
    at a non-literal (`db.table(SOME_CONST)`) returns None and is counted as
    unreadable by the caller rather than guessed at.
    """
    cur: ast.AST = node
    while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
        if cur.func.attr == "table" and cur.args:
            arg = cur.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
            return None
        cur = cur.func.value
    return None


def _is_dynamic_table(node: ast.Call) -> bool:
    """True when the chain IS a .table(...) chain but the name is not literal."""
    cur: ast.AST = node
    while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
        if cur.func.attr == "table" and cur.args:
            arg = cur.args[0]
            return not (isinstance(arg, ast.Constant) and isinstance(arg.value, str))
        cur = cur.func.value
    return False


def split_select(expr: str) -> tuple[list[str], int]:
    """Column names in a select list, plus a count of embedded resources.

    Handles `a, b`, `alias:col`, `*`, and skips `lines(amount)` — an embedded
    RELATION, whose head is not a column of this table.
    """
    cols: list[str] = []
    embeds = 0
    depth = 0
    part = ""
    for ch in expr:
        if ch == "(":
            depth += 1
            part += ch
        elif ch == ")":
            depth -= 1
            part += ch
        elif ch == "," and depth == 0:
            cols.append(part)
            part = ""
        else:
            part += ch
    cols.append(part)

    out: list[str] = []
    for raw in cols:
        c = raw.strip()
        if not c or c == "*":
            continue
        if "(" in c:           # embedded resource — a relation, not our column
            embeds += 1
            continue
        if ":" in c:           # alias:real_column
            c = c.split(":", 1)[1].strip()
        c = c.split("::", 1)[0].strip()   # a cast, if one ever appears
        if c and c != "*" and c.replace("_", "").replace("0123456789", "").isalnum():
            out.append(c)
    return out, embeds


def split_or_clause(expr: str) -> list[str]:
    """Column names out of an .or_() / .not_() PostgREST filter string.

    "a.eq.true,b.is.null" -> ["a", "b"]. Commas inside parentheses (an in.(…)
    list) do not separate clauses.
    """
    clauses: list[str] = []
    depth = 0
    part = ""
    for ch in expr:
        if ch == "(":
            depth += 1
            part += ch
        elif ch == ")":
            depth -= 1
            part += ch
        elif ch == "," and depth == 0:
            clauses.append(part)
            part = ""
        else:
            part += ch
    clauses.append(part)

    cols: list[str] = []
    for raw in clauses:
        c = raw.strip()
        if not c:
            continue
        # `and(a.eq.1,b.eq.2)` nests. Test the PREFIX, not the dot-split head:
        # splitting first yields "and(a", which matches nothing and silently
        # drops both real column names.
        low = c.lower()
        if (low.startswith("and(") or low.startswith("or(")) and c.endswith(")"):
            cols.extend(split_or_clause(c[c.index("(") + 1: c.rindex(")")]))
            continue
        if "." not in c:
            continue
        head = c.split(".", 1)[0].strip()
        if head and head.replace("_", "").isalnum():
            cols.append(head)
    return cols


def _string_arg(node: ast.Call, index: int = 0) -> str | None:
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def scan_file(path: Path) -> tuple[list[tuple[str, str, str]], int]:
    """[(relpath, relation, column)] and a count of unreadable references."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return [], 1

    found: list[tuple[str, str, str]] = []
    unreadable = 0
    name = str(path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr

        if method not in FILTER_METHODS and method not in WRITE_METHODS and method not in ("select", "or_"):
            continue

        rel = _relation_of(node)
        if rel is None:
            if _is_dynamic_table(node):
                unreadable += 1
            continue

        if method == "select":
            expr = _string_arg(node)
            if expr is None:
                unreadable += 1
                continue
            cols, _embeds = split_select(expr)
            found.extend((name, rel, c) for c in cols)

        elif method == "or_":
            expr = _string_arg(node)
            if expr is None:
                unreadable += 1
                continue
            found.extend((name, rel, c) for c in split_or_clause(expr))

        elif method in FILTER_METHODS:
            col = _string_arg(node)
            if col is None:
                unreadable += 1
                continue
            # A dotted filter names an EMBEDDED resource, not this table:
            #   .select("id, journal_entries!inner(client_id)")
            #   .eq("journal_entries.client_id", x)
            # PostgREST supports that, and reading the head as a column of the
            # outer table reports a phantom that is not one. Attribute it to
            # the embedded relation instead, so the reference is still CHECKED
            # rather than skipped — against the table it actually belongs to.
            if "." in col:
                head, tail = col.split(".", 1)
                found.append((name, head.strip(), tail.split(".", 1)[0].strip()))
            else:
                found.append((name, rel, col.strip()))

        elif method in WRITE_METHODS:
            if not node.args:
                continue
            payload = node.args[0]
            dicts = [payload] if isinstance(payload, ast.Dict) else (
                [e for e in payload.elts if isinstance(e, ast.Dict)]
                if isinstance(payload, (ast.List, ast.Tuple)) else []
            )
            if not dicts:
                unreadable += 1
                continue
            for d in dicts:
                for k in d.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        found.append((name, rel, k.value))
                    else:
                        unreadable += 1   # **spread or a computed key
    return found, unreadable


# Directories whose queries are not production call sites.
_SKIP_DIRS = {"tests", "__pycache__", "venv", ".venv", "migrations"}


def scan(api_root: Path) -> tuple[list[tuple[str, str, str]], int]:
    found: list[tuple[str, str, str]] = []
    unreadable = 0
    for path in sorted(api_root.rglob("*.py")):
        if _SKIP_DIRS & set(path.relative_to(api_root).parts):
            continue
        f, u = scan_file(path)
        found.extend(f)
        unreadable += u
    return found, unreadable


# ── Columns the LOCAL template cannot vouch for ──────────────────────────────
#
# scripts/db/apply_migrations.py builds the CI template with
# --continue-on-error, so the migrations on test_migrations_apply.py's
# EXPECTED_MIGRATION_FAILURES baseline never run. Their columns are absent
# LOCALLY while being present in production — 070_ai_memory.sql alone accounts
# for five (client_profiles.is_current, .profile_version, .compliance_score,
# firm_profiles.is_current, .last_computed_at).
#
# Reporting those as phantoms would be the check crying wolf on its first run,
# which is how a ratchet gets deleted. They are derived from the baseline
# rather than hand-listed, so when a migration is repaired and drops off it,
# its columns become checkable again with no second list to remember.

import re

_ADD_COLUMN = re.compile(
    r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?"?([a-z_0-9]+)"?'
    r'[\s\S]*?ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"?([a-z_0-9]+)"?',
    re.I)
_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?([a-z_0-9]+)"?\s*\(',
    re.I)
_NOT_A_COLUMN = frozenset({
    "constraint", "primary", "unique", "foreign", "check", "exclude", "like",
})


def _table_body(sql: str, open_paren: int) -> str:
    depth, i = 0, open_paren
    while i < len(sql):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[open_paren + 1:i]
        i += 1
    return ""


def columns_declared_in(sql: str) -> set[str]:
    """{'table.column'} a migration file would create, if it ran."""
    out: set[str] = set()
    for m in _ADD_COLUMN.finditer(sql):
        out.add(f"{m.group(1).lower()}.{m.group(2).lower()}")
    for m in _CREATE_TABLE.finditer(sql):
        table = m.group(1).lower()
        body = _table_body(sql, m.end() - 1)
        depth, item = 0, ""
        items = []
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                items.append(item)
                item = ""
            else:
                item += ch
        items.append(item)
        for raw in items:
            line = raw.strip().lstrip("-").strip()
            if not line:
                continue
            first = line.split()[0].strip('"').lower() if line.split() else ""
            if first and first not in _NOT_A_COLUMN and re.fullmatch(r"[a-z_0-9]+", first):
                out.add(f"{table}.{first}")
    return out


def unverifiable_columns(migrations_dir: Path, failed: set[str]) -> set[str]:
    seen: set[str] = set()
    for name in failed:
        path = migrations_dir / name
        if path.exists():
            seen |= columns_declared_in(path.read_text(encoding="utf-8"))
    return seen
