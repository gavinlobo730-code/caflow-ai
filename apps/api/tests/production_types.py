"""Refuse, in mock mode, a write Postgres would refuse in production.

WHY THIS EXISTS
    The mock suite runs against an in-memory dict, which accepts anything. Five
    of the defects in the 7 September 2026 audit were the same shape: code that
    writes a value or a column the real database does not have, so every test
    passes and the write fails only against Postgres — usually silently, because
    the failing statement is inside a broad try/except or a background job.

    The worst of them: routers/fixed_assets.py wrote `'2026-04'` into
    `fixed_assets.depreciation_posted_through`, which is DATE. Postgres answers
    22007 and rejects the WHOLE update, so every other column in it stays as it
    was. Posting depreciation had never worked against the real database, and
    10,000 passing tests said otherwise.

    `tests/fixtures/production_schema_*.json` already records every column and
    its type — it was built for the drift tests. This reads it on the write
    path instead, which costs nothing and needs no Postgres.

WHAT IS CHECKED, AND WHAT IS NOT
    Checked: a column production does not have (PostgREST rejects the whole
    write with PGRST204), and the types that actually reject an insert — date,
    timestamp, the integer family, boolean, numeric.

    NOT checked: uuid and text. Fixtures use synthetic ids ("client-1",
    "FIRM-A") throughout, which is the tests' own business and not a claim about
    production; and every Python value has a text rendering, so a text column
    rejects nothing.

    A table the snapshot predates is skipped rather than failed. The snapshot
    goes stale by design (docs/schema-drift.md) and a test that fails because a
    NEW table is new would be noise, not a finding.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The newest production_schema_*.json in the fixtures directory, so refreshing
# the snapshot (its README says how) does not need an edit here. The sibling
# *.meta.json is excluded by name: it describes the snapshot rather than being
# one, and picking it up silently gives six "tables" and checks nothing.
_SNAPSHOTS = sorted(f for f in _FIXTURES.glob("production_schema_*.json")
                    if not f.name.endswith(".meta.json"))
SCHEMA_FILE = _SNAPSHOTS[-1] if _SNAPSHOTS else None
_SCHEMA: dict[str, dict] = (
    json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) if SCHEMA_FILE else {}
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_NUMERIC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


# ── Columns the snapshot predates ──────────────────────────────────────────
#
# The snapshot is a point-in-time copy (see its README and docs/schema-drift.md)
# and goes stale by design. A column added by a migration AFTER that date is not
# drift and must not fail here — but "not in the snapshot" and "not in
# production" look identical from inside a test, which is exactly the confusion
# this module exists to remove. So each one is named with the migration that
# added it, and the entry becomes provably removable the moment the snapshot is
# refreshed: if the column is in the new snapshot, delete the line.
#
# Keep this SHORT. A long list means the snapshot needs refreshing, not that the
# list needs another entry.
ADDED_AFTER_THE_SNAPSHOT: dict[tuple[str, str], str] = {
    # Migrations 374-381 were all HERE until the pair of fixtures was refreshed
    # to production's mark of 381 on the evening of 13 September 2026 — the
    # SECOND refresh that day, and this list is why: nineteen entries over six
    # migrations, and the other half of the ratchet
    # (test_guards_match_production_pg's ten-migration limit) had already
    # fired. Both fixtures now match production row for row (schema md5
    # e764f1bd44aa5cafe1c2e4eaa1fd8dda over 4,237 columns in 284 tables;
    # guards md5 111977fa54589d4f31096fd92a2223ee over 2,356 rows), so the
    # only entries left are the migrations this branch has not merged yet.
    ("bank_transactions", "gst_rate_bps"): "migration 382",
    ("bank_transactions", "gst_is_interstate"): "migration 382",
    ("fixed_assets", "disposal_is_supply"): "migration 383",
    ("fixed_assets", "disposal_gst_rate_bps"): "migration 383",
    ("fixed_assets", "disposal_is_interstate"): "migration 383",
    ("journal_lines", "line_order"): "migration 384",
    ("capital_gains", "transferred_asset_nature"): "migration 385",
    ("vendors", "gst_registration_status"): "migration 388",
    ("client_sales_invoices", "is_opening"): "migration 391",
    ("purchase_bills", "is_opening"): "migration 391",
    ("clients", "inventory_costing_method"): "migration 394",
    ("inventory_stock_ledger", "costing_method"): "migration 394",
    ("clients", "landed_cost_basis"): "migration 396",
    ("purchase_bills", "landed_cost_basis"): "migration 396",
    ("inventory_stock_ledger", "godown_id"): "migration 398",
    ("inventory_stock_ledger", "batch_id"): "migration 398",
    ("capital_gains", "is_listed_security"): "migration 402",
    ("capital_gains", "fmv_31_01_2018_paise"): "migration 402",
    ("clients", "section_32_1_iia_business"): "migration 406",
    ("fixed_assets", "additional_depreciation_eligible"): "migration 406",
    ("service_catalogue", "alternate_unit"): "migration 409",
    ("service_catalogue", "units_per_alternate"): "migration 409",
    ("service_catalogue", "reorder_level_units"): "migration 409",
    ("payroll_it_declaration_items", "proof_attachments"): "migration 410",
    # public.capital_gain_reinvestments (385), public.stock_count_sessions and
    # public.stock_count_lines (387), public.rcm_documents (388),
    # public.bills_of_entry (389), public.client_gst_registrations (390) and
    # the sales/purchase pre-document tables (392, 393),
    # public.purchase_bill_landed_costs (396),
    # public.capital_work_in_progress and public.cwip_additions (397),
    # and public.godowns and public.inventory_batches (398),
    # and public.self_assessment_challans (407)
    # are WHOLE new tables
    # and need no entry: a table the snapshot predates is skipped.
}


def known_table(table: str) -> bool:
    """Whether the snapshot has anything to say about this table."""
    return table in _SCHEMA


def assert_write_fits_production_types(table: str, payload) -> None:
    """Fail on a value production's column type would reject.

    `payload` may be one row or a list of them, matching PostgREST's insert.
    """
    columns = _SCHEMA.get(table)
    if columns is None:
        return
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            spec = columns.get(key)
            if spec is None and (table, key) in ADDED_AFTER_THE_SNAPSHOT:
                continue
            assert spec is not None, (
                f"{table}.{key} is not a column in production — PostgREST rejects "
                f"the WHOLE write with PGRST204, so every other column in it is "
                f"never written either. Either the migration adding it is missing, "
                f"or the snapshot in {SCHEMA_FILE.name if SCHEMA_FILE else '?'} is "
                f"stale (docs/schema-drift.md says how to refresh it). If a "
                f"migration after the snapshot's date added it, name it in "
                f"ADDED_AFTER_THE_SNAPSHOT above rather than widening the check."
            )
            kind = spec["type"] if isinstance(spec, dict) else str(spec)
            if value is None:
                continue
            if kind == "date":
                ok = isinstance(value, date) or (
                    isinstance(value, str) and _DATE_RE.match(value))
                assert ok, (
                    f"{table}.{key} is a DATE and this write gives it {value!r}. "
                    f"Postgres answers 22007 invalid_input_syntax_for_type_date and "
                    f"rejects the WHOLE update — every other column in it silently "
                    f"stays as it was."
                )
            elif kind.startswith("timestamp"):
                # A bare date is the interesting failure here, and it is NOT a
                # rejected write: Postgres parses '2026-09-08' as midnight in
                # the session's timezone, so the column quietly records an
                # instant nobody chose. That is harder to find than an error,
                # which is why it is refused rather than allowed.
                ok = isinstance(value, datetime) or (
                    isinstance(value, str) and _TIMESTAMP_RE.match(value))
                assert ok, (
                    f"{table}.{key} is {kind} and this write gives it {value!r}. "
                    f"Postgres will ACCEPT a bare date and store midnight in the "
                    f"session's timezone — an instant nobody chose. Pass a real "
                    f"timestamp (core.ist_clock.ist_now())."
                )
            elif kind in ("bigint", "integer", "smallint"):
                assert isinstance(value, int) and not isinstance(value, bool), (
                    f"{table}.{key} is {kind} and this write gives it {value!r}. "
                    f"Money crosses this boundary as integer paise (CLAUDE.md); a "
                    f"float here is both a type error and a rounding one."
                )
            elif kind == "boolean":
                assert isinstance(value, bool), (
                    f"{table}.{key} is boolean and this write gives it {value!r}.")
            elif kind == "numeric":
                # A STRING IS FINE HERE and is not a defect: Postgres parses a
                # numeric literal out of it on input, and the codebase sends
                # exchange rates that way on purpose — a rate is decimal and a
                # float round-trip is what the money rules forbid. What is
                # refused is a string that is not a number, and a bool.
                ok = (isinstance(value, (int, float, Decimal))
                      and not isinstance(value, bool))
                if isinstance(value, str):
                    ok = _NUMERIC_RE.match(value.strip()) is not None
                assert ok, (
                    f"{table}.{key} is numeric and this write gives it {value!r}, "
                    f"which Postgres cannot parse as a number.")
