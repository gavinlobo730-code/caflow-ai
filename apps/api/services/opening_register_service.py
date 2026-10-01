"""Fetch for, and write, the fixed-asset register import (accounting-18).

`domain/fixed_assets/opening_register.py` carries every rule — which row is a new
asset, which is one the register already holds, which is refused and why. This
module is the part that needs a database: it reads the codes already on the
register, writes the new assets and says what became of each row.

NO JOURNAL IS POSTED AND NOTHING GOES THROUGH THE POSTING KERNEL, which is the
design (migration 456, and 391's reasoning for documents): the ledger's Fixed
Assets and Accumulated Depreciation balances arrive through the opening balances
or an imported trial balance, and these rows are their breakup. A second posting
path is exactly what CLAUDE.md forbids, and an acquisition per asset on top of
the trial balance would count the cost twice.

ATOMIC PER CHUNK, NAMED PER ROW. Up to `_INSERT_CHUNK` assets go in one statement,
so a chunk is all-or-nothing in the database; if one is refused (a race with
another upload on migration 351's unique index is the realistic way) it is
retried one asset at a time, so the failure is attributed to the row that caused
it and its neighbours still land.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.fixed_assets import opening_register as reg

_logger = logging.getLogger("caflow.opening_register")

#: Assets to an INSERT. A hundred rows of this table is a few kilobytes; the bound
#: is what keeps a refused chunk's per-row retry from being a thousand requests.
_INSERT_CHUNK = 100

#: Codes to one `.in_()`, because PostgREST builds a URL and has a length limit.
_CODE_CHUNK = 150


def _existing(db, firm_id: str, client_id: str, codes: list[str]) -> dict[str, dict]:
    """The register rows already holding one of these codes, keyed by the code
    casefolded — INCLUDING a soft-deleted row, which keeps its code for good
    (migration 351's unique index is not partial), so there is NO `deleted_at`
    filter and the plan decides what a deleted holder means."""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), _CODE_CHUNK):
        chunk = codes[i:i + _CODE_CHUNK]
        for row in fetch_all(
                lambda chunk=chunk: db.table("fixed_assets")
                .select("id, asset_code, asset_name, asset_category, purchase_date, "
                        "purchase_cost_paise, opening_position_date, deleted_at")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("asset_code", chunk),
                key="id", label="opening_register_existing"):
            out[str(row.get("asset_code") or "").casefold()] = row
    return out


def _write(db, firm_id: str, client_id: str, planned: list) -> list[dict]:
    """INSERT the assets in ONE statement, so the chunk is atomic.

    The columns are written out LITERALLY, here, rather than through
    `PlannedAsset.as_row`: a payload built in a function the schema scanner cannot
    see makes the write invisible to `test_backend_columns_exist_pg` and to its
    NOT NULL check, and both budgets say to write the payload inline rather than
    raise them. `as_row` stays the definition —
    `tests/test_opening_register_import.py` asserts these keys are exactly its
    keys plus the two ownership columns, so the two cannot drift.

    `journal_entry_id` and `acquisition_mode` are deliberately ABSENT: NULL is the
    truth (no acquisition journal of this product's ever existed for the asset),
    and `opening_position_date` is what says so to the readers that care.
    """
    return (db.table("fixed_assets").insert([
        {
            "firm_id": firm_id,
            "client_id": client_id,
            "asset_code": p.asset_code,
            "asset_name": p.asset_name,
            "asset_category": p.asset_category,
            "purchase_date": p.purchase_date,
            "purchase_cost_paise": p.purchase_cost_paise,
            "salvage_value_paise": p.salvage_value_paise,
            "useful_life_years": p.useful_life_years,
            "depreciation_method": p.depreciation_method,
            "wdv_rate_percent": p.wdv_rate_percent,
            "accumulated_depreciation_paise": p.accumulated_depreciation_paise,
            "current_wdv_paise": p.current_wdv_paise,
            "depreciation_posted_through": p.opening_position_date,
            "opening_position_date": p.opening_position_date,
            "put_to_use_date": p.put_to_use_date,
            "it_block_key": p.it_block_key,
            "location": p.location,
            "notes": p.notes,
        } for p in planned]).execute().data) or []


def import_register(db, firm_id: str, client_id: str, *, as_at: Optional[str],
                    rows: list, dry_run: bool = False) -> dict:
    """Judge every row, write the new assets, and say what happened to each.

    `dry_run` runs the whole judgement and writes nothing; its totals are what the
    register WOULD hold, so the CA can compare them with the ledger first.
    """
    position, why = reg.position_problem(as_at, ist_today())
    if why:
        raise HTTPException(status_code=422, detail=why)
    if not rows:
        raise HTTPException(status_code=422, detail="The file has no rows to import.")
    if len(rows) > reg.MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(f"{len(rows)} rows is more than one import takes ({reg.MAX_ROWS}). "
                    f"Split the file by asset class and upload the parts — a re-upload "
                    f"skips every asset already on the register."))

    codes = sorted({(r.asset_code or "").strip() for r in rows if (r.asset_code or "").strip()})
    existing = _existing(db, firm_id, client_id, codes)
    verdicts = reg.plan(rows, existing, as_at=position)

    new = [v for v in verdicts if v.status == reg.NEW]
    written: dict[int, str] = {}
    failed: dict[int, str] = {}
    if new and not dry_run:
        from core.exceptions import document_failure_detail
        for i in range(0, len(new), _INSERT_CHUNK):
            chunk = new[i:i + _INSERT_CHUNK]
            try:
                got = _write(db, firm_id, client_id, [v.planned for v in chunk])
                for v, row in zip(chunk, got):
                    written[v.row] = str(row.get("id") or "")
                continue
            except Exception as chunk_error:                      # noqa: BLE001
                _logger.warning("opening-register chunk of %d refused (%s); "
                                "retrying one asset at a time", len(chunk),
                                type(chunk_error).__name__)
            for v in chunk:
                try:
                    got = _write(db, firm_id, client_id, [v.planned])
                    written[v.row] = str((got[0] if got else {}).get("id") or "")
                except Exception as one_error:                    # noqa: BLE001
                    failed[v.row] = document_failure_detail(
                        one_error, action="record this asset")

    final: list[reg.AssetVerdict] = []
    results = []
    for v in verdicts:
        shown = v
        if v.row in failed:
            shown = reg.AssetVerdict(row=v.row, asset_code=v.asset_code,
                                     status=reg.REJECTED, problems=(failed[v.row],))
        final.append(shown)
        results.append({
            "row": shown.row,
            "asset_code": shown.asset_code,
            "status": "would_create" if dry_run and shown.status == reg.NEW else shown.status,
            "problems": list(shown.problems),
            "warnings": list(shown.warnings),
            "id": written.get(v.row) or shown.existing_id,
        })
    summary = reg.summarise(final)

    return {
        "as_at": position.isoformat(),
        "dry_run": dry_run,
        "received": summary.received,
        "created": 0 if dry_run else summary.new,
        "would_create": summary.new if dry_run else 0,
        "already_recorded": summary.already_recorded,
        "rejected": summary.rejected,
        "cost_paise": summary.cost_paise,
        "accumulated_paise": summary.accumulated_paise,
        "net_paise": summary.net_paise,
        "by_category": summary.by_category,
        "gaps": summary.gaps,
        "next_depreciation_month": reg.next_depreciation_month(position),
        "ledger_note": reg.NOTHING_IS_POSTED,
        "rows": results,
    }
