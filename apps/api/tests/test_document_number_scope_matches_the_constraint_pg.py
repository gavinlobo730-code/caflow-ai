"""The scope a document series is numbered over must be the scope its UNIQUE
constraint covers — checked against a database built from the migrations.

This is the half of SALES-04 the mock suite cannot see. The in-memory harness
derives its unique indexes from services.numbering.NUMBER_SERIES, so it agrees
with the declaration by construction; only real Postgres can say whether the
MIGRATIONS agree with it too.

They did not, twice. Migration 151 found client_sales_invoices and credit_notes
numbered per (firm, client, FY) behind a UNIQUE (firm_id, number); migration 159
found debit_notes and receipts the same. Migration 210 then created
sales_debit_notes and purchase_credit_notes with the old per-firm key, and the
blocker was live again on both: the firm's SECOND client computes 0001, the
constraint rejects it, services/numbering.py recomputes the same 0001 six times,
and the request 500s. Migration 350 widens them.

Without 350 this test names both tables. With it, it passes and stays passing —
a seventh series added with the wrong key fails here rather than in a CA's face.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from services.numbering import NUMBER_SERIES

_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

_UNIQUE_KEYS_SQL = """
SELECT c.relname,
       (SELECT string_agg(a.attname, ',' ORDER BY a.attname)
        FROM unnest(i.indkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum)
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
JOIN pg_class c  ON c.oid  = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE i.indisunique AND n.nspname = 'public'
"""


def _unique_keys(dsn: str) -> dict[str, set[frozenset]]:
    out: dict[str, set[frozenset]] = {}
    proc = subprocess.run(
        ["psql", dsn, "-X", "-q", "-t", "-A", "-F", "|", "-v", "ON_ERROR_STOP=1",
         "-c", _UNIQUE_KEYS_SQL],
        capture_output=True, text=True, check=True)
    for line in proc.stdout.splitlines():
        if "|" not in line:
            continue
        table, cols = line.split("|", 1)
        if not cols.strip():
            continue
        out.setdefault(table.strip(), set()).add(frozenset(c.strip() for c in cols.split(",")))
    return out


@pytest.fixture()
def _keys(pg_template):
    admin = _HARNESS_PG.strip()
    name = f"caflow_numbering_{uuid.uuid4().hex[:12]}"
    subprocess.run(["psql", f"{admin} dbname=postgres", "-v", "ON_ERROR_STOP=1", "-X", "-q",
                    "-c", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";'],
                   capture_output=True, text=True, check=True)
    try:
        yield _unique_keys(f"{admin} dbname={name}")
    finally:
        subprocess.run(["psql", f"{admin} dbname=postgres", "-X", "-q", "-c",
                        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);'],
                       capture_output=True, text=True)


@_NEEDS_PG
def test_every_series_is_unique_over_exactly_the_scope_it_is_numbered_over(_keys):
    wrong = []
    for table, (field, scope) in NUMBER_SERIES.items():
        declared = frozenset(scope) | {field}
        found = _keys.get(table, set())
        if declared not in found:
            wrong.append(f"{table}: numbered per {sorted(declared)}, "
                         f"unique keys are {[sorted(k) for k in found] or 'none'}")
    assert not wrong, (
        "a sequence computed over a narrower scope than the constraint hands the "
        "same number to two rows the database will not accept, and the retry "
        f"recomputes it: {wrong}")


@_NEEDS_PG
def test_no_narrower_key_survives_beside_the_right_one(_keys):
    """Widening is done by DROPping the old key, not by adding a second one —
    a leftover UNIQUE (firm_id, number) rejects the second client exactly as
    before, however correct the wider key beside it is."""
    leftovers = []
    for table, (field, scope) in NUMBER_SERIES.items():
        declared = frozenset(scope) | {field}
        for key in _keys.get(table, set()):
            if field in key and key < declared:
                leftovers.append(f"{table}: {sorted(key)} is narrower than {sorted(declared)}")
    assert not leftovers, leftovers
