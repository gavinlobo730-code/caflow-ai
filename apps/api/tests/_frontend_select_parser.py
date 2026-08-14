"""Parse PostgREST `.from("t").select("...")` pairs out of apps/web.

Split out of test_frontend_columns_exist_pg.py so the parsing can be tested on
its own, without a database. A checker whose parser is only exercised through
the thing it checks tends to pass by finding nothing — see
test_frontend_select_parser.py for the vacuity guards.
"""
from __future__ import annotations

import re
from pathlib import Path

# `.from("x")` followed, within a short window, by `.select("...")`. The window
# exists because the two are almost always adjacent in a builder chain but are
# usually on different lines, and occasionally have a comment between them.
_FROM = re.compile(r'\.from\("([a-z_0-9]+)"\)')
_SELECT_AFTER = re.compile(r'\A[\s\S]{0,400}?\.select\(\s*"([^"]*)"', re.M)

SKIP_DIRS = {"node_modules", ".next", "out", ".vercel"}


def split_top_level(expr: str) -> list[str]:
    """Split a PostgREST select list on commas that are not inside parens."""
    parts, depth, buf = [], 0, []
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_select(table: str, expr: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(relation, column) pairs the select asks for, plus relations it embeds.

    Handles the four shapes that appear in this codebase:
        col                       plain column
        alias:col                 renamed column
        rel(a, b)                 embed
        alias:rel!inner(a, b)     renamed embed with a join hint

    `*` is skipped rather than expanded — it cannot be wrong.
    """
    cols: list[tuple[str, str]] = []
    rels: list[str] = [table]
    for part in split_top_level(expr):
        if "(" in part:
            head = part[: part.index("(")].strip()
            inner = part[part.index("(") + 1: part.rindex(")")]
            rel = head.split("!", 1)[0]
            if ":" in rel:
                rel = rel.split(":", 1)[1]
            rel = rel.strip()
            if not rel:
                continue
            sub_cols, sub_rels = parse_select(rel, inner)
            cols.extend(sub_cols)
            rels.extend(sub_rels)
            continue

        col = part
        # Cast BEFORE alias, because "::" contains ":" — splitting on the alias
        # separator first turns `amount::text` into `:text` and the column is
        # lost silently, which is a false pass rather than a false alarm.
        col = col.split("::", 1)[0]         # cast
        if ":" in col:                      # alias:column -> the real column
            col = col.split(":", 1)[1]
        col = col.split("->", 1)[0]         # jsonb accessor
        col = col.split(".", 1)[0]          # qualified reference
        col = col.strip()
        if not col or col == "*":
            continue
        if not re.fullmatch(r"[a-z_][a-z_0-9]*", col):
            continue                        # count(), aggregates, oddities
        cols.append((table, col))
    return cols, rels


def scan(web_root: Path) -> tuple[list[tuple[str, str, str]], int]:
    """Every (file, relation, column) the frontend selects, plus a count of
    `.from()` calls whose select could not be read as a plain string literal
    (template literals, variables) — reported so a parser that quietly stops
    finding anything cannot masquerade as a clean result."""
    found: list[tuple[str, str, str]] = []
    unparsed = 0
    for path in sorted(web_root.rglob("*.ts*")):
        if set(path.parts) & SKIP_DIRS:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel_path = path.relative_to(web_root).as_posix()
        for m in _FROM.finditer(src):
            table = m.group(1)
            tail = src[m.end():]
            sel = _SELECT_AFTER.match(tail)
            if not sel:
                unparsed += 1
                continue
            cols, _ = parse_select(table, sel.group(1))
            for rel, col in cols:
                found.append((rel_path, rel, col))
    return found, unparsed
