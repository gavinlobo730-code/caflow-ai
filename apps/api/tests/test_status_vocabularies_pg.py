"""
Every literal status the code writes must be one the database admits.

THE BUG CLASS

A CHECK constraint of the form `status = ANY (ARRAY[...])` is a vocabulary.
Code that writes a word outside it is rejected at runtime — and because these
writes are usually in an error path or a background task, the rejection is
often swallowed and the feature simply stops working, with nothing in the logs
that names the cause.

Two live instances, both found by the guard comparison added in migration 316
and fixed in 318:

  * `gst_sync_jobs.status = 'partial_failure'` — added deliberately, with a
    display branch and three tests, to a table whose production CHECK predates
    it. Every partially-failed portal sync 500'd with a raw database error in
    production while the tests passed, because they run against an in-memory
    FakeDB.

  * `tally_migration_jobs.status = 'failed'` — written by the detached
    import's exception handler, which production refuses; the inner `except`
    logged and moved on, so a crashed import sat at 'importing' for ever. That
    is precisely what the handler exists to prevent.

Neither could be caught by a mock-mode test: mock mode has no constraints. And
neither could be caught by comparing the migrations against production, because
in both cases the migrations never declared the constraint at all.

HOW THIS WORKS

Read every enum-shaped CHECK out of the migration-built template, then scan the
backend for literal writes to those columns and assert each literal is admitted.
The vocabulary comes from the database, so it cannot drift from what is
enforced; the literals come from the source, so a new status added in code
fails here rather than in production.

WHAT IT CANNOT SEE, AND WHY THAT IS ACCEPTABLE

A write whose value is a variable, and a write whose payload is built in one
file while the table is named in another (the repository pattern). Both are
invisible to a textual scan. The check is therefore a floor, not a ceiling: it
catches the shape that has actually bitten twice — a literal written a few
lines from the table it is written to — and says nothing about the rest.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

# Enum-shaped CHECKs, as `table|column|value` rows — one row per admitted value.
_VOCAB_SQL = r"""
SELECT json_agg(x) FROM (
  SELECT t.relname::text AS tbl,
         a.attname::text AS col,
         v.val[1]::text  AS val
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
  CROSS JOIN LATERAL regexp_matches(
      pg_get_constraintdef(c.oid), '''([a-z0-9_]+)''::text', 'g') AS v(val)
  WHERE c.contype = 'c'
    AND t.relnamespace = 'public'::regnamespace
    AND array_length(c.conkey, 1) = 1
    AND pg_get_constraintdef(c.oid) LIKE '%= ANY (ARRAY[%'
) x;
"""

_SCAN_DIRS = ("routers", "services", "domain", "jobs", "repositories")


@pytest.fixture(scope="module")
def vocabularies(pg_template):
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={pg_template.name}",
         "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _VOCAB_SQL],
        capture_output=True, text=True, check=True)
    rows = json.loads(out.stdout.strip() or "null") or []
    vocab: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        vocab.setdefault((r["tbl"], r["col"]), set()).add(r["val"])
    return vocab


def _payload_spans(src: str):
    """(table, start, end) for every `.table("t") … .insert({…})` / `.update({…})`
    payload in a source file, using balanced braces to find the payload's end.

    Scanning a WINDOW of text after the table call instead — the obvious first
    cut — reads dicts that are not writes at all. gst_exception_service.py
    returns `{"status": "not_filed", …}` a few lines after a select; that is the
    function's own response contract, not a column value, and a window-based
    scan reported it as writing a status gstr1_returns does not admit.
    """
    for m in re.finditer(r'\.table\(\s*["\'](?P<t>[a-z_0-9]+)["\']\s*\)', src):
        tail = src[m.end(): m.end() + 200]
        # Stop at the next .table() call: chained statements sit line after
        # line, and without this bound a `.insert(rows)` that takes a variable
        # falls through to the NEXT statement's `.update({…})` and attributes
        # its payload to this table.
        nxt = re.search(r'\.table\(', tail)
        if nxt:
            tail = tail[:nxt.start()]
        op = re.search(r'\.(insert|update|upsert)\(\s*\{', tail)
        if not op:
            continue
        i = m.end() + op.end() - 1          # the opening brace
        depth, j = 0, i
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group("t"), i, j


def _literal_writes():
    """(file, line, table, column, value) for every literal in a write payload."""
    for d in _SCAN_DIRS:
        for path in sorted((_API / d).rglob("*.py")):
            src = path.read_text(encoding="utf-8")
            for tbl, i, j in _payload_spans(src):
                for w in re.finditer(
                        r'["\'](?P<col>[a-z_0-9]+)["\']\s*:\s*["\'](?P<val>[a-z0-9_]+)["\']',
                        src[i:j]):
                    yield (path.relative_to(_API),
                           src[:i + w.start()].count("\n") + 1,
                           tbl, w.group("col"), w.group("val"))


@_NEEDS_PG
def test_every_literal_status_the_code_writes_is_admitted(vocabularies):
    offenders = []
    for rel, line, tbl, col, val in _literal_writes():
        allowed = vocabularies.get((tbl, col))
        if allowed and val not in allowed:
            offenders.append(
                f"{rel}:{line}  {tbl}.{col} = '{val}'   admitted: "
                + ", ".join(sorted(allowed)))
    assert not offenders, (
        "These writes put a value into a column whose CHECK constraint does not "
        "admit it. Postgres rejects the statement; in an error path or a "
        "background task the rejection is usually swallowed and the feature "
        "silently stops working — that is how a partially-failed GST sync 500'd "
        "and a crashed Tally import sat at 'importing' for ever.\n"
        "Either write a value the column admits, or widen the constraint in a "
        "migration (318 is the pattern, and widening production is a real DDL "
        "change that needs its own argument).\n  " + "\n  ".join(offenders))


@_NEEDS_PG
def test_the_vocabularies_were_actually_read(vocabularies):
    """A regex that stopped matching would make the assertion above vacuous."""
    assert len(vocabularies) > 40, (
        f"only {len(vocabularies)} enum-shaped CHECKs found — the introspection "
        "is wrong and the scan above is checking almost nothing")
    assert vocabularies[("tally_migration_jobs", "status")] >= {
        "uploaded", "importing", "completed", "error"}


@_NEEDS_PG
def test_the_scan_finds_real_writes():
    """A regex that matched nothing would also pass vacuously."""
    found = list(_literal_writes())
    assert len(found) > 60, (
        f"the source scan found only {len(found)} literal writes — it is not "
        "reading the code it claims to")
    # An anchor, so a regex that still matches SOMETHING but no longer matches
    # the shape this test exists for cannot pass. This is the exact write
    # migration 318 fixed: the detached Tally import's failure handler.
    assert any(t == "tally_migration_jobs" and c == "status" and v == "error"
               for _, _, t, c, v in found), (
        "the scan no longer sees the write this test was built around — "
        "domain/tally/migration_service.py's detached-import failure handler")


@_NEEDS_PG
def test_a_planted_offender_would_be_caught(vocabularies):
    """Prove the assertion has teeth: 'failed' was the real Tally bug."""
    allowed = vocabularies[("tally_migration_jobs", "status")]
    assert "failed" not in allowed, (
        "production admits ten statuses for a migration job and 'failed' is not "
        "one of them; if that changed, the negative control below is moot")
    assert "error" in allowed
