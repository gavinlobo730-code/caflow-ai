"""What the receipt-recording database function stores, read from the migrations (found by number).

`settle_receipt_atomic` posts a receipt's journal, the receipt row and its allocations in one transaction; its body is `settle_receipt_atomic__unguarded`
since migration 486 (before that, the function itself). `CREATE OR REPLACE` replaces the whole body, so the columns it stores are the columns of the
INSERT INTO receipts in the LAST migration that defines the body. This module finds that migration and reads that INSERT, for the guard that compares
it with what the service sends (`test_every_key_the_receipt_payload_sends_is_stored_by_the_function_that_records_it.py`) and for the test double
(`tests/e2e_harness.py`), which must store no more than the real function does.

It is deliberately strict: a definition of the body whose INSERT it cannot read is an ERROR, never a reason to keep trusting an earlier definition.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

_HEADER = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?\"?(settle_receipt_atomic(?:__unguarded)?)\"?\s*\(", re.I)
_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")
_INSERT = re.compile(r"INSERT\s+INTO\s+(?:public\.)?\"?receipts\"?(?:\s+AS\s+\w+)?\s*\((.*?)\)\s*(?:VALUES|SELECT|OVERRIDING)\b", re.I | re.S)


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def definitions(files: dict[str, str]) -> list[tuple[str, str, str]]:
    """(file, function name, body) of every definition of the receipt function or its unguarded body, in file order then position."""
    out: list[tuple[str, str, str]] = []
    for name in sorted(files):
        text = strip_comments(files[name])
        for header in _HEADER.finditer(text):
            opening = _DOLLAR.search(text, header.end())
            if not opening:
                continue
            tag = opening.group(0)
            close = text.find(tag, opening.end())
            if close < 0:
                continue
            out.append((name, header.group(1).lower(), text[opening.end():close]))
    return out


def body_definitions(files: dict[str, str]) -> list[tuple[str, str]]:
    """(file, body) of every definition that is the BODY: the unguarded function, or the plain function before it was renamed. The wrapper
    (migrations 533, 545, 546) calls the unguarded one and holds no INSERT of its own."""
    return [(f, b) for f, n, b in definitions(files)
            if n == "settle_receipt_atomic__unguarded" or (n == "settle_receipt_atomic" and "settle_receipt_atomic__unguarded" not in b.lower())]


def last_body_columns(files: dict[str, str]) -> tuple[str, list[str]]:
    """(the migration, the columns) of the INSERT INTO receipts in the last definition of the body. Raises AssertionError when there is none or
    the last definition's INSERT cannot be read."""
    bodies = body_definitions(files)
    assert bodies, "no migration defines the receipt function's body"
    name, body = bodies[-1]
    inserts = list(_INSERT.finditer(body))
    assert inserts, (f"the last definition of the receipt function's body ({name}) holds no INSERT INTO receipts this guard can read: either the "
                     "function no longer stores the receipt row itself, or it is spelled in a way this reader does not know; make the reader know it")
    raw = inserts[-1].group(1)
    return name, [c for c in re.split(r"[,\s]+", raw) if c]


def migration_files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")) if not p.name.endswith("_rollback.sql")}


def current_columns() -> tuple[str, list[str]]:
    return last_body_columns(migration_files())
