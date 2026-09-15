"""Capital work-in-progress — reading, posting and capitalising (FA-11a).

This module FETCHES and WRITES; `domain/fixed_assets/cwip.py` DECIDES. It buckets
nothing, names no refusal and does not know what "overdue" means.

WHAT IT IS RESPONSIBLE FOR THAT THE DOMAIN MODULE IS NOT

  THE LEDGER. Schedule III's ageing schedule has to tie to the capital
  work-in-progress figure in the balance sheet, so the cost cannot live in a
  register alone: every addition posts Dr Capital Work-in-Progress / Cr the
  account the money came from, through the ONE posting kernel
  (`phase2_journal_service._create_journal`) like every other accounting event.

  CAPITALISATION, which is where the whole feature earns its keep. It creates
  the `fixed_assets` row — cost = the accumulated additions, `put_to_use_date` =
  the date the asset became ready — and posts Dr Fixed Asset / Cr Capital
  Work-in-Progress. Depreciation then runs through the register that already
  exists, from the right date, with no second depreciation path anywhere.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from core.db_paging import fetch_all
from domain.accounting import journal_source as JS
from domain.fixed_assets import cwip as cwip_domain

_logger = logging.getLogger("caflow.cwip")

#: The statuses a project may be in and still be capital work-in-progress.
OPEN_STATUSES = (cwip_domain.IN_PROGRESS, cwip_domain.SUSPENDED)

NOT_POSTED = (
    "This cost was recorded but no journal entry was posted for it, so the "
    "capital work-in-progress figure on the balance sheet does not yet include "
    "it and the ageing schedule will not tie. The usual cause is that this "
    "firm has no Capital Work-in-Progress account — create one (asset, subtype "
    "Capital Work-in-Progress) and post the entry, or raise the journal by "
    "hand."
)


def _as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _blocked_tax(row: dict) -> int:
    """The tranche's §17(5)-blocked tax, which is part of what the asset cost.

    AS-10 paragraph 9 puts non-refundable purchase taxes in the cost of an item
    of property, plant and equipment, and credit barred by CGST s.17(5) is
    refundable from nobody — the same sentence AS-2 paragraph 6 applies to
    stock (INV-05a). Eligible tax is a credit and is NOT capitalised.
    """
    if row.get("itc_eligible") is True:
        return 0
    return (int(row.get("igst_paise") or 0)
            + int(row.get("cgst_paise") or 0)
            + int(row.get("sgst_paise") or 0))


def capitalised_cost_of(addition: dict) -> int:
    """What one tranche adds to the cost of the asset."""
    return int(addition.get("amount_paise") or 0) + _blocked_tax(addition)


def _projects(db, *, firm_id: str, client_id: str) -> list:
    return fetch_all(
        lambda: db.table("capital_work_in_progress")
        .select("id, project_code, project_name, asset_category, started_on, "
                "approved_completion_date, approved_cost_paise, "
                "expected_completion_date, status, status_changed_on, "
                "capitalised_on, capitalised_asset_id, notes, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="cwip.projects")


def _additions(db, *, firm_id: str, client_id: str) -> list:
    return fetch_all(
        lambda: db.table("cwip_additions")
        .select("id, cwip_id, incurred_on, description, amount_paise, "
                "igst_paise, cgst_paise, sgst_paise, itc_eligible, "
                "itc_blocked_reason, acquisition_mode, vendor_id, "
                "purchase_bill_id, bank_account_id, payment_mode, "
                "journal_entry_id, notes, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="cwip.additions")


def _live(rows: list) -> list:
    """Soft-deleted rows are excluded IN PYTHON, so a row lacking the key reads
    as live — the same direction every other reader in this codebase takes."""
    return [r for r in rows if not r.get("deleted_at")]


def _to_domain(projects: list, additions: list):
    ps = [
        cwip_domain.Project(
            cwip_id=str(p["id"]),
            name=p.get("project_name") or "",
            status=p.get("status") or cwip_domain.IN_PROGRESS,
            started_on=_as_date(p.get("started_on")) or date.min,
            approved_completion_date=_as_date(p.get("approved_completion_date")),
            approved_cost_paise=(int(p["approved_cost_paise"])
                                 if p.get("approved_cost_paise") is not None else None),
            expected_completion_date=_as_date(p.get("expected_completion_date")),
            capitalised_on=_as_date(p.get("capitalised_on")),
        )
        for p in projects
    ]
    adds = [
        cwip_domain.Addition(
            cwip_id=str(a["cwip_id"]),
            incurred_on=_as_date(a.get("incurred_on")) or date.min,
            # THE CAPITALISED figure, not the bare amount: the balance sheet
            # carries the blocked tax too, so the note must age the same rupees
            # the ledger holds or the two cannot tie.
            amount_paise=capitalised_cost_of(a),
        )
        for a in additions
    ]
    return ps, adds


def schedules(db, *, firm_id: str, client_id: str, as_of: date) -> dict:
    """The Schedule III ageing schedule and completion schedule, as at a date."""
    projects = _live(_projects(db, firm_id=firm_id, client_id=client_id))
    additions = _live(_additions(db, firm_id=firm_id, client_id=client_id))
    ps, adds = _to_domain(projects, additions)
    ageing = cwip_domain.ageing(ps, adds, as_of=as_of)
    completion = cwip_domain.completion_schedule(ps, adds, as_of=as_of)
    return {
        "ageing": ageing.as_dict(),
        "completion_schedule": completion.as_dict(),
        "does_not_depreciate": cwip_domain.CWIP_DOES_NOT_DEPRECIATE,
    }


def register(db, *, firm_id: str, client_id: str) -> dict:
    """Every project with what has been spent on it, for the screen."""
    projects = _live(_projects(db, firm_id=firm_id, client_id=client_id))
    additions = _live(_additions(db, firm_id=firm_id, client_id=client_id))
    spent: dict = {}
    for a in additions:
        spent[str(a["cwip_id"])] = spent.get(str(a["cwip_id"]), 0) + capitalised_cost_of(a)
    return {
        "projects": [
            {**p,
             "incurred_paise": spent.get(str(p["id"]), 0),
             # The over-budget test is the DOMAIN's, asked here per project so
             # the screen renders a fact rather than comparing two numbers.
             "over_approved_cost": (
                 p.get("approved_cost_paise") is not None
                 and spent.get(str(p["id"]), 0) > int(p["approved_cost_paise"])),
             }
            for p in projects
        ],
        "additions": additions,
        "statuses": list(cwip_domain.ROW_LABELS),
        "does_not_depreciate": cwip_domain.CWIP_DOES_NOT_DEPRECIATE,
    }


# ── writing ─────────────────────────────────────────────────────────────────

def create_project(db, *, firm_id: str, client_id: str, project_name: str,
                   started_on: str, project_code: Optional[str],
                   asset_category: Optional[str],
                   approved_completion_date: Optional[str],
                   approved_cost_paise: Optional[int],
                   expected_completion_date: Optional[str],
                   notes: Optional[str], actor_id: Optional[str]) -> dict:
    rows = db.table("capital_work_in_progress").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "project_code": project_code,
        "project_name": project_name,
        "asset_category": asset_category,
        "started_on": started_on,
        "approved_completion_date": approved_completion_date,
        "approved_cost_paise": approved_cost_paise,
        "expected_completion_date": expected_completion_date,
        "status": cwip_domain.IN_PROGRESS,
        "status_changed_on": started_on,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def set_status(db, *, firm_id: str, client_id: str, cwip_id: str,
               status: str, on_date: str) -> dict:
    """Suspend or resume. Capitalisation and abandonment are not this door.

    SUSPENSION IS PRESENTATIONAL, not a removal: the balance stays in capital
    work-in-progress and moves to the "Projects temporarily suspended" row of
    the ageing schedule. Reading it as a removal would take the cost off the
    balance sheet, which is a different and much larger claim.
    """
    if status not in OPEN_STATUSES:
        return {"ok": False, "refusal": (
            "Only 'in_progress' and 'suspended' are set here. Capitalising is "
            "its own action because it creates the asset and posts a journal, "
            "and abandonment is a write-off the CA raises.")}
    rows = (db.table("capital_work_in_progress")
            .select("id, status, capitalised_on")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("id", cwip_id).limit(1).execute().data) or []
    if not rows:
        return {"ok": False, "refusal": "That project is not in this firm."}
    if rows[0].get("status") == "capitalised":
        return {"ok": False, "refusal": (
            "This project has been capitalised — its cost is a fixed asset and "
            "a posted journal, neither of which can be rewritten.")}
    db.table("capital_work_in_progress").update({
        "status": status,
        "status_changed_on": on_date,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("firm_id", firm_id).eq("client_id", client_id).eq("id", cwip_id).execute()
    return {"ok": True, "status": status}


def add_cost(db, *, firm_id: str, client_id: str, cwip_id: str,
             incurred_on: str, description: str, amount_paise: int,
             igst_paise: int = 0, cgst_paise: int = 0, sgst_paise: int = 0,
             itc_eligible: Optional[bool] = None,
             itc_blocked_reason: Optional[str] = None,
             acquisition_mode: Optional[str] = None,
             vendor_id: Optional[str] = None,
             purchase_bill_id: Optional[str] = None,
             bank_account_id: Optional[str] = None,
             payment_mode: Optional[str] = None,
             notes: Optional[str] = None,
             actor_id: Optional[str] = None,
             journal=None) -> dict:
    """Record one tranche of cost and post it."""
    rows = (db.table("capital_work_in_progress")
            .select("id, project_name, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("id", cwip_id).limit(1).execute().data) or []
    if not rows:
        return {"ok": False, "refusal": "That project is not in this firm."}
    if rows[0].get("status") not in OPEN_STATUSES:
        return {"ok": False, "refusal": (
            "This project is no longer capital work-in-progress, so a further "
            "cost belongs on the asset it became — or on a new project.")}

    inserted = db.table("cwip_additions").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "cwip_id": cwip_id,
        "incurred_on": incurred_on,
        "description": description,
        "amount_paise": int(amount_paise),
        "igst_paise": int(igst_paise or 0),
        "cgst_paise": int(cgst_paise or 0),
        "sgst_paise": int(sgst_paise or 0),
        "itc_eligible": itc_eligible,
        "itc_blocked_reason": itc_blocked_reason,
        "acquisition_mode": acquisition_mode,
        "vendor_id": vendor_id,
        "purchase_bill_id": purchase_bill_id,
        "bank_account_id": bank_account_id,
        "payment_mode": payment_mode,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    row = inserted[0] if inserted else {}

    # THE POSTING OUTCOME IS REPORTED, NOT SWALLOWED. The whole point of this
    # feature is that Schedule III's ageing schedule ties to the capital
    # work-in-progress figure ON THE BALANCE SHEET, so a tranche recorded and
    # not posted is exactly the state that breaks it. `_find_account` raises
    # where the firm has no Capital Work-in-Progress account — which is the
    # case for any firm that had no chart of accounts when migration 397 ran —
    # and the journal method turns that into None. Returning a clean success
    # there would leave the CA with a register that does not agree with their
    # own ledger and nothing saying so.
    gaps: list = []
    if journal is not None and row:
        entry_id = journal.journal_for_cwip_addition(
            addition={**row, "project_name": rows[0].get("project_name")},
            firm_id=firm_id, client_id=client_id)
        if entry_id:
            db.table("cwip_additions").update(
                {"journal_entry_id": entry_id}).eq("id", row["id"]).execute()
            row["journal_entry_id"] = entry_id
        else:
            gaps.append(NOT_POSTED)
    return {"ok": True, "addition": row, "gaps": gaps}


def capitalise(db, *, firm_id: str, client_id: str, cwip_id: str,
               put_to_use_date: str, asset_name: Optional[str] = None,
               asset_category: Optional[str] = None,
               useful_life_years: Optional[int] = None,
               depreciation_method: Optional[str] = None,
               actor_id: Optional[str] = None, journal=None) -> dict:
    """The project becomes a fixed asset, and depreciation starts.

    ONE WAY. `fixed_assets` already carries correction and soft-delete paths
    (migration 351) for a mistake; re-opening a capitalised project would need
    the posted journal reversed, which is a decision rather than an undo.
    """
    rows = (db.table("capital_work_in_progress")
            .select("id, project_name, project_code, asset_category, status, "
                    "started_on, capitalised_on")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("id", cwip_id).limit(1).execute().data) or []
    if not rows:
        return {"ok": False, "refusal": "That project is not in this firm."}
    project = rows[0]
    if project.get("status") == "capitalised":
        return {"ok": False, "refusal": "This project has already been capitalised."}
    if project.get("status") == "abandoned":
        return {"ok": False, "refusal": (
            "This project was abandoned. Its cost is written off, not "
            "capitalised.")}

    additions = _live(fetch_all(
        lambda: db.table("cwip_additions")
        .select("id, cwip_id, amount_paise, igst_paise, cgst_paise, sgst_paise, "
                "itc_eligible, incurred_on, deleted_at")
        .eq("firm_id", firm_id).eq("cwip_id", cwip_id),
        key="id", label="cwip.capitalise"))
    cost = sum(capitalised_cost_of(a) for a in additions)
    if cost <= 0:
        return {"ok": False, "refusal": (
            "Nothing has been spent on this project, so there is no cost to "
            "capitalise. An asset with no cost is not an asset.")}

    # THE ASSET'S OWN DATES. `put_to_use_date` is when it became available for
    # use and is what AS-10 paragraph 20 starts depreciation from;
    # `purchase_date` is the same date rather than the project's start, because
    # the register treats it as the acquisition and a three-year-old start
    # would charge three years of depreciation the moment it is capitalised.
    # EVERY COLUMN NAMED AND EVERY ONE OF THEM REAL. `fixed_assets` has no
    # `created_by` — PostgREST rejects the WHOLE insert with PGRST204 on one
    # column that does not exist, so the asset would simply never appear —
    # and `acquisition_mode` is CHECKed to ('paid', 'credit', 'from_bill'),
    # so a fourth value would be refused by the database. Both were caught by
    # tests/production_types.py on the first run.
    #
    # `acquisition_mode` IS DELIBERATELY LEFT NULL, which is also the honest
    # answer rather than a workaround: it records how the asset was PAID FOR,
    # and every payment already happened on the tranches. Migration 343's own
    # header says it is NULL for assets whose journal says so. The link to the
    # project lives on `capital_work_in_progress.capitalised_asset_id`.
    asset_rows = db.table("fixed_assets").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "asset_name": asset_name or project.get("project_name"),
        "asset_category": asset_category or project.get("asset_category"),
        "purchase_date": put_to_use_date,
        "put_to_use_date": put_to_use_date,
        "purchase_cost_paise": cost,
        "current_wdv_paise": cost,
        "accumulated_depreciation_paise": 0,
        "useful_life_years": useful_life_years,
        "depreciation_method": depreciation_method,
        "notes": f"Capitalised from {project.get('project_name') or 'work-in-progress'}",
    }).execute().data or []
    asset = asset_rows[0] if asset_rows else {}

    entry_id = None
    if journal is not None and asset:
        entry_id = journal.journal_for_cwip_capitalisation(
            project={**project, "id": cwip_id}, asset=asset, cost_paise=cost,
            entry_date=put_to_use_date, firm_id=firm_id, client_id=client_id)

    db.table("capital_work_in_progress").update({
        "status": "capitalised",
        "status_changed_on": put_to_use_date,
        "capitalised_on": put_to_use_date,
        "capitalised_asset_id": asset.get("id"),
        "capitalisation_journal_entry_id": entry_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("firm_id", firm_id).eq("client_id", client_id).eq("id", cwip_id).execute()

    return {"ok": True, "asset": asset, "cost_paise": cost,
            "journal_entry_id": entry_id,
            # The asset EXISTS either way — refusing to create it because the
            # transfer entry failed would leave the cost stranded in capital
            # work-in-progress with a finished asset nobody can depreciate.
            # The gap says what is still owed instead.
            "gaps": [] if entry_id or journal is None else [NOT_POSTED]}
