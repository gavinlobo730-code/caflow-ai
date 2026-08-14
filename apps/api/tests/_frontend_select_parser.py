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


# ── filter-argument columns ─────────────────────────────────────────────────
#
# `.select()` is not the only place a column name is written. Every filter takes
# one as its first argument, and getting it wrong fails exactly the same way —
# PostgREST rejects the request. /reports/cash-flow filtered
# `.in("filing_type", ...)` on compliance_calendar, where the column is
# compliance_type; the select-only checker could not see it and it was found by
# hand.
#
# Methods whose FIRST argument is a bare column name. `match()` takes an object
# and `or()` takes an expression string — both handled separately below.
_FILTER_METHODS = {
    "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in",
    "contains", "containedBy", "overlaps", "order", "not", "filter",
    "textSearch", "likeAllOf", "likeAnyOf", "ilikeAllOf", "ilikeAnyOf",
    "rangeGt", "rangeGte", "rangeLt", "rangeLte", "rangeAdjacent",
}

# A chain step: optional whitespace/comments, then `.method(`.
# NOTE: no \A here. Pattern.match(s, pos) anchors at pos, but \A asserts the
# absolute start of the string, so with \A the walk matched only its first step
# and silently found nothing from the second call onward.
_STEP = re.compile(r'(?:\s|//[^\n]*\n|/\*[\s\S]*?\*/)*\.([A-Za-z_][A-Za-z_0-9]*)\(')
# First argument as a plain string literal. Template literals and variables are
# deliberately not matched — their value is not knowable here.
_FIRST_STR_ARG = re.compile(r'\A\s*(["\'])([^"\']*)\1')
# One clause of an `.or("a.eq.1,b.is.null")` expression: the column is the
# identifier at the start of the string or just after a comma. Anchoring this
# way keeps values that contain dots from being read as columns.
_OR_CLAUSE = re.compile(r'(?:\A|,)\s*([a-z_][a-z_0-9]*)\.'
                        r'(?:eq|neq|gt|gte|lt|lte|like|ilike|is|in|cs|cd|fts|plfts|phfts|wfts|not)\.')


def _skip_args(src: str, open_paren: int) -> int:
    """Index just past the `)` matching the `(` at `open_paren`.

    Quote-aware, because an argument like `"a)b"` or a template literal would
    otherwise close the call early and desynchronise the whole walk."""
    depth, i, n = 0, open_paren, len(src)
    quote = None
    while i < n:
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def parse_chain_filters(table: str, tail: str) -> list[tuple[str, str]]:
    """(relation, column) pairs named by the filter calls of ONE builder chain.

    `tail` is the source immediately after `.from("table")`. The chain is walked
    step by step and stops at the first thing that is not another `.method(`
    call, so a filter belonging to a later, unrelated query is never attributed
    to this one — which a fixed-size character window would do.

    A dotted first argument (`"payroll_runs.month"`) is PostgREST's syntax for
    filtering on an embedded resource, so it is attributed to that relation
    rather than the base table."""
    out: list[tuple[str, str]] = []
    pos = 0
    while True:
        m = _STEP.match(tail, pos)
        if not m:
            return out
        method = m.group(1)
        open_paren = m.end() - 1
        close = _skip_args(tail, open_paren)
        if close < 0:
            return out
        args = tail[open_paren + 1: close - 1]

        if method in _FILTER_METHODS:
            a = _FIRST_STR_ARG.match(args)
            if a:
                name = a.group(2).strip()
                # `.order("col", { ascending })` and `.not("col", "is", null)`
                # both put the column first, so one shape covers them.
                rel, col = table, name
                if "." in name:
                    rel, col = name.split(".", 1)
                col = col.split("->", 1)[0].strip()      # jsonb accessor
                col = col.split("::", 1)[0].strip()      # cast
                if re.fullmatch(r"[a-z_][a-z_0-9]*", col) and re.fullmatch(r"[a-z_][a-z_0-9]*", rel):
                    out.append((rel, col))
        elif method == "or":
            a = _FIRST_STR_ARG.match(args)
            if a:
                for col in _OR_CLAUSE.findall(a.group(2)):
                    out.append((table, col))

        pos = close


# ── write-payload columns ───────────────────────────────────────────────────
#
# The third place a column name is written: the object passed to .insert(),
# .update() or .upsert(). A wrong key here fails the WRITE, which is worse than
# a failed read — /tds records a TDS deduction with six keys the table does not
# have, so nothing has ever been saved from that form.
_WRITE_METHODS = {"insert", "update", "upsert"}

# A top-level key: `col:` or the shorthand `col,` / `col}`. The shorthand form
# matters — an early version of this checker required the colon and so missed
# `category,` in the client-documents upload entirely.
_OBJ_KEY = re.compile(r'([A-Za-z_][A-Za-z_0-9]*)\s*(?=[,:}])')


_LINE_COMMENT = re.compile(r'//[^\n]*')
_BLOCK_COMMENT = re.compile(r'/\*[\s\S]*?\*/')


def first_argument(args: str) -> str:
    """The first argument of a call, given everything between its parentheses.

    `.upsert({...}, { onConflict: "firm_id,account_name" })` passes OPTIONS as a
    second argument, and reading the whole arg list turned `onConflict` into a
    phantom column on six different tables. Only the payload is a payload."""
    depth, i, n = 0, 0, len(args)
    quote = None
    while i < n:
        ch = args[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == "," and depth == 0:
            return args[:i]
        i += 1
    return args


def parse_write_keys(payload: str) -> list[str]:
    """Top-level keys of an object literal, ignoring nested objects.

    Depth-tracked so a nested value (`extracted_json: { foo: 1 }`) contributes
    nothing, quote-aware so a key-like substring inside a string value is not
    read as a key, comment-stripped (a `// CA REVIEW REQUIRED — DO NOT
    AUTO-SUBMIT` line inside a payload produced a phantom `DB` column), and
    spread-aware (`{ ...input, x }` names `x`, not `input`)."""
    payload = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", payload))
    keys: list[str] = []
    i, n, depth = 0, len(payload), 0
    quote = None
    start_of_value = False
    while i < n:
        ch = payload[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif depth == 1 and ch == ":":
            start_of_value = True
        elif depth == 1 and ch == ",":
            start_of_value = False
        elif depth == 1 and payload.startswith("...", i):
            # A spread contributes whatever that object holds, which is not
            # knowable here. Skip the identifier so it is not read as a key.
            i += 3
            while i < n and (payload[i].isalnum() or payload[i] in "_."):
                i += 1
            continue
        elif depth == 1 and not start_of_value and (ch.isalpha() or ch == "_"):
            m = _OBJ_KEY.match(payload, i)
            if m:
                keys.append(m.group(1))
                i = m.end()
                continue
        i += 1
    return keys


def scan_writes(web_root: Path) -> list[tuple[str, str, str]]:
    """Every (file, relation, column) named as a key of an insert/update payload."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(web_root.rglob("*.ts*")):
        if set(path.parts) & SKIP_DIRS:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel_path = path.relative_to(web_root).as_posix()
        for m in _FROM.finditer(src):
            table, tail, pos = m.group(1), src[m.end():], 0
            while True:
                step = _STEP.match(tail, pos)
                if not step:
                    break
                open_paren = step.end() - 1
                close = _skip_args(tail, open_paren)
                if close < 0:
                    break
                if step.group(1) in _WRITE_METHODS:
                    args = first_argument(tail[open_paren + 1: close - 1]).lstrip()
                    # Only a literal object can be read; `.insert(payload)` and
                    # `.insert([...])` are skipped rather than guessed at.
                    if args.startswith("{"):
                        for key in parse_write_keys(args):
                            found.append((rel_path, table, key))
                pos = close
    return found


def scan_filters(web_root: Path) -> list[tuple[str, str, str]]:
    """Every (file, relation, column) the frontend names in a FILTER argument.

    Separate from scan() rather than folded into it: the two find different
    kinds of reference, and keeping them apart means a change to one cannot
    quietly move the other's vacuity numbers."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(web_root.rglob("*.ts*")):
        if set(path.parts) & SKIP_DIRS:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel_path = path.relative_to(web_root).as_posix()
        for m in _FROM.finditer(src):
            for rel, col in parse_chain_filters(m.group(1), src[m.end():]):
                found.append((rel_path, rel, col))
    return found


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
