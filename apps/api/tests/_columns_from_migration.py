"""The columns a migration declares, read out of the migration FILE.

WHY THIS EXISTS
    `tests/_schema_checked_db.py` refuses a column production lacks, and its own
    header says to add a column to REAL_COLUMNS when a migration adds one. That
    is a hand-copied list, and a hand-copied list of a migration's columns is how
    a test and the SQL it is about drift apart without anyone changing either on
    purpose. A test for a NEW table or column can read the declaration instead,
    so it cannot disagree with the migration it is proving.

    It is a plain-text reader for the two shapes this repository's migrations
    use — `CREATE TABLE IF NOT EXISTS public.t ( ... );` and
    `ALTER TABLE public.t ADD COLUMN IF NOT EXISTS c ...;` — not a SQL parser,
    and it refuses (raises) rather than guessing when the table is not there.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

_SKIP_FIRST_WORDS = {"constraint", "primary", "unique", "foreign", "check", "like", "exclude"}


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _create_table_body(sql: str, table: str) -> str | None:
    m = re.search(
        rf"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{re.escape(table)}\s*\(",
        sql, re.I)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(sql) and depth:
        depth += {"(": 1, ")": -1}.get(sql[i], 0)
        i += 1
    return sql[m.end():i - 1]


def table_columns(migration: str, table: str) -> set[str]:
    """Columns `migration` gives `table`, from CREATE TABLE and ADD COLUMN."""
    sql = _strip_comments((MIGRATIONS / migration).read_text(encoding="utf-8"))
    cols: set[str] = set()
    body = _create_table_body(sql, table)
    if body is not None:
        depth, start, parts = 0, 0, []
        for i, ch in enumerate(body):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(body[start:i])
                start = i + 1
        parts.append(body[start:])
        for part in parts:
            words = part.strip().split()
            if words and words[0].lower() not in _SKIP_FIRST_WORDS:
                cols.add(words[0].strip('"'))
    for m in re.finditer(
            rf"alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{re.escape(table)}\s+"
            rf"add\s+column\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)", sql, re.I):
        cols.add(m.group(1))
    if not cols:
        raise LookupError(f"{migration} declares no columns for {table!r}")
    return cols
