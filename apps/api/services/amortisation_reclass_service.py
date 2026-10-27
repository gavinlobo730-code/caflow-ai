"""The reclassification of an intangible asset's accumulated amortisation into the ledger of its own: prepared here, posted by a Partner
(POST-A-345, stage 3).

WHAT IT IS FOR. Until this change an intangible asset's amortisation was credited to the one shared Accumulated Depreciation ledger,
which Schedule III places on the TANGIBLE line (migration 553 has the whole account). New assets are born pointing at their own ledger
(`fixed_asset_accumulated_ledger.birth_pointer`); this moves the history of those that were not. It is a POSTING THE PRODUCT PREPARES
AND A PARTNER MAKES: posted history is the CA's entry and not a migration's rewrite, and nothing here runs by itself.

PREPARE, THEN POST, AND THE POST ASKS AGAIN. `preview` reads the books and writes nothing; `post` re-reads them, refuses if the total
the Partner saw is no longer the total, and moves each asset by this sequence, which is the one `dispose_asset` uses for the same
reason (a failure must never leave the books moved and the register not, or the other way round):

    1. CLAIM the asset by compare-and-set: `UPDATE fixed_assets SET accumulated_account_id = <own> WHERE id = .. AND pointer IS NULL AND
       accumulated_depreciation_paise = <the figure previewed> AND NOT disposed AND NOT deleted`. A row that changed since the preview
       claims nothing and is skipped by name; two Partners posting at once claim each asset once. The claim comes FIRST because the
       depreciation, disposal and month-reversal routes compare-and-set on the pointer they used, so a request already in flight on the
       old pointer finds it moved, undoes its own journal and answers 409, rather than crediting the shared ledger for a month the
       pointer says belongs to the new one.
    2. POST one journal per date (`Phase2JournalService.journal_for_amortisation_reclass`); the kernel asks the closure lock.
    3. If a journal fails, find what is LIVE for the asset in the ledger (not what this process remembers: a call that timed out may
       have committed) and reverse it. Only when everything is reversed is the claim undone. If a reversal fails too, the claim STAYS,
       because a pointer taken back over a live entry is the half-in-each-ledger state this change exists to prevent: the asset is
       reported as PARTLY MOVED with its live entries, and the undo, which works from the ledger and not from the pointer, finishes it.

THE UNDO works from evidence. It is allowed while no LIVE depreciation or disposal of the asset touches the new ledger (a month posted
and since reversed does not count), it takes the pointer back with the same compare-and-set (so a disposal or a month that landed
first stops it, and a second undo finds the pointer already gone), it NEVER puts the pointer back, and it can be run again: with the
pointer gone and an entry still live it reverses what is left.

WHAT IT REFUSES, AND WHY EACH IS A REFUSAL AND NOT A WARNING (the arithmetic is `domain/fixed_assets/amortisation_reclass`): a date that
is not a month end or is in the future; a shared ledger that holds less for this client than would leave it AS AT THE DATE OF EACH ENTRY
(the tangible line's contra would go to a debit balance on that day's balance sheet); an Accumulated Amortisation ledger that carries
a credit nothing explains, or less than the assets pointed at it account for; a ledger named for the carried-over part that is the new
ledger itself or sits on the same line; an asset whose register figure and ledger history disagree; a closed year at ANY date of an
entry. Nothing is netted: which of two disagreeing figures is the mistake is the Partner's answer.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import fy_bounds, ist_fy_label, ist_today
from domain.accounting.journal_source import AMORTISATION_RECLASS, ASSET_DISPOSAL, DEPRECIATION
from domain.fixed_assets import amortisation_reclass as arc
from domain.fixed_assets.asset_ledger import accumulated_account_pointer
from domain.money_sentence import rupee_text
from services import fixed_asset_accumulated_ledger as fal
from services import period_lock_service

_logger = logging.getLogger("caflow.amortisation_reclass")


ledger_credit_balance = fal.ledger_credit_balance


def say_date(iso: str) -> str:
    """30 Sep 2025: a date in a sentence for a person."""
    return date.fromisoformat(str(iso)[:10]).strftime("%d %b %Y")


def _fy_end_of(iso: str) -> str:
    return fy_bounds(ist_fy_label(iso))[1]


# ── what the ledger says ────────────────────────────────────────────────────

def depreciation_positions(db, firm_id: str, client_id: str, asset_ids: list[str], shared_account_id: str,
                           as_at: str, today: str) -> dict[str, tuple[int, tuple]]:
    """{asset id: (net credit to the shared ledger dated on or before `as_at`, ((entry date, net credit), ...) for the months dated
    after it, grouped by the date the entry that will move them is dated)} from the asset's own depreciation journals. A reversal
    carries its original's source (`reverse_entry`), so the sums are net of any reversal.

    Rows read are the asset's depreciation entries and their lines on ONE ledger: assets times months, not the ledger's volume."""
    if not asset_ids:
        return {}
    entries = fetch_all_in(
        lambda: (db.table("journal_entries").select("id,entry_date,source_id")
                 .eq("firm_id", firm_id).eq("client_id", client_id).eq("source_type", DEPRECIATION)),
        "source_id", asset_ids, label="amortisation_reclass.depreciation_entries")
    by_id = {e["id"]: e for e in entries}
    lines = fetch_all_in(
        lambda: (db.table("journal_lines").select("id,journal_entry_id,debit_paise,credit_paise")
                 .eq("account_id", shared_account_id)),
        "journal_entry_id", list(by_id), label="amortisation_reclass.depreciation_lines")
    to_as_at: dict[str, int] = {a: 0 for a in asset_ids}
    later: dict[str, dict[str, int]] = {a: {} for a in asset_ids}
    latest: dict[str, dict[str, str]] = {a: {} for a in asset_ids}
    for line in lines:
        entry = by_id.get(line["journal_entry_id"])
        if entry is None:
            continue
        net = int(line.get("credit_paise") or 0) - int(line.get("debit_paise") or 0)
        day = str(entry["entry_date"])[:10]
        if day <= as_at:
            to_as_at[entry["source_id"]] += net
        else:
            when = arc.later_entry_date(day, today, fy_end_of=_fy_end_of)
            later[entry["source_id"]][when] = later[entry["source_id"]].get(when, 0) + net
            latest[entry["source_id"]][when] = max(day, latest[entry["source_id"]].get(when, ""))
    return {a: (to_as_at[a], _dated_at_the_latest_month(later[a], latest[a])) for a in asset_ids}


def _dated_at_the_latest_month(amounts: dict[str, int], latest_day: dict[str, str]) -> tuple:
    """The year that has not ended is moved in an entry dated today, and a month of it can be dated AFTER today (this month's charge is
    dated its month end; a depreciation run ahead is dated later still). An entry dated today would debit the ledger before that
    month's credit exists in it, so the entry is dated at the latest month it holds when that is after today."""
    merged: dict[str, int] = {}
    for when, amount in amounts.items():
        dated = max(when, latest_day.get(when, when))
        merged[dated] = merged.get(dated, 0) + amount
    return tuple(sorted(merged.items()))


def _parse_as_at(as_at: str, today: str) -> str:
    text = str(as_at).strip()
    try:
        # A typed date, not a stored stamp: exactly YYYY-MM-DD, so "2025-09-30T23:00:00Z" is refused rather than cut to a day.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError(text)
        d = date.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=422, detail="Say the date the reclassification is as at, as YYYY-MM-DD.") from None
    if d.isoformat() > today:
        raise HTTPException(status_code=422, detail="The date it is as at cannot be in the future: an entry is dated as at that "
                                                    "date, and the months posted since are moved in entries dated each year end and today.")
    problem = arc.month_end_problem(d.isoformat())
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    return d.isoformat()


def live_entries(db, firm_id: str, client_id: str, asset_ids: list[str]) -> list[dict]:
    """The asset's LIVE reclassification entries (not deleted, not reversed, not itself a reversal), from the ledger: what the undo acts
    on, and what an asset created pointing at its own ledger does not have."""
    if not asset_ids:
        return []
    return fetch_all_in(
        lambda: (db.table("journal_entries").select("id,source_id,entry_date,reference_no")
                 .eq("firm_id", firm_id).eq("client_id", client_id).eq("source_type", AMORTISATION_RECLASS)
                 .is_("deleted_at", "null").eq("is_reversed", False).is_("reversal_of", "null")),
        "source_id", asset_ids, label="amortisation_reclass.live_entries")


def _later_postings_touching(db, firm_id: str, client_id: str, asset_id: str, ledger_id: str) -> list[dict]:
    """LIVE depreciation and disposal entries of this asset that have a line on this ledger. A month posted after the move credits the
    new ledger, and a disposal debits it; a month posted and then reversed is a reversed entry and its reversal, neither live."""
    entries = fetch_all(
        lambda: (db.table("journal_entries").select("id,entry_date")
                 .eq("firm_id", firm_id).eq("client_id", client_id).in_("source_type", [DEPRECIATION, ASSET_DISPOSAL])
                 .eq("source_id", asset_id).is_("deleted_at", "null").eq("is_reversed", False).is_("reversal_of", "null")),
        label="amortisation_reclass.later_entries")
    if not entries:
        return []
    touching = fetch_all_in(
        lambda: db.table("journal_lines").select("id,journal_entry_id").eq("account_id", ledger_id),
        "journal_entry_id", [e["id"] for e in entries], label="amortisation_reclass.later_lines")
    ids = {ln["journal_entry_id"] for ln in touching}
    return [e for e in entries if e["id"] in ids]


def own_ledger_credit_by_asset(db, firm_id: str, client_id: str, own_id: str, asset_ids: list[str]) -> dict[str, int]:
    """What each asset's LIVE entries (depreciation, reclassification, disposal) have net credited to the new ledger. For an asset whose
    move is complete this equals the register's accumulated figure; for one claimed and not moved, or moved in part, it is less. This is
    the ledger's own evidence of how far an asset got, and it is what tells a half-moved asset from a clean one: the pointer alone says
    only where the NEXT month goes."""
    if not asset_ids:
        return {}
    entries = fetch_all_in(
        lambda: (db.table("journal_entries").select("id,source_id")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .in_("source_type", [DEPRECIATION, AMORTISATION_RECLASS, ASSET_DISPOSAL])
                 .is_("deleted_at", "null").eq("is_reversed", False).is_("reversal_of", "null")),
        "source_id", asset_ids, label="amortisation_reclass.own_credit_entries")
    by_id = {e["id"]: e["source_id"] for e in entries}
    lines = fetch_all_in(
        lambda: db.table("journal_lines").select("id,journal_entry_id,debit_paise,credit_paise").eq("account_id", own_id),
        "journal_entry_id", list(by_id), label="amortisation_reclass.own_credit_lines") if by_id else []
    credit: dict[str, int] = {a: 0 for a in asset_ids}
    for line in lines:
        asset = by_id.get(line["journal_entry_id"])
        if asset is not None:
            credit[asset] += int(line.get("credit_paise") or 0) - int(line.get("debit_paise") or 0)
    return credit


def _has_a_live_entry(db, firm_id: str, client_id: str, asset_id: str) -> bool:
    """Whether ONE asset has any live reclassification entry: an existence question, so one row at most is asked for."""
    rows = (db.table("journal_entries").select("id").eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("source_type", AMORTISATION_RECLASS).eq("source_id", asset_id)
            .is_("deleted_at", "null").eq("is_reversed", False).is_("reversal_of", "null").limit(1).execute().data) or []
    return bool(rows)


def unfinished_move_reason(db, firm_id: str, client_id: str, asset: dict) -> Optional[str]:
    """A sentence if this asset's reclassification did not finish, else None. Disposing of or deleting such an asset strands its entries:
    the disposal debits whichever ledger the pointer names for the WHOLE register figure while the ledgers hold the asset in part
    each, and the undo then refuses a disposed asset. Two states: no pointer but an entry of the reclassification still live (an Undo
    took the pointer back and could not reverse everything), and a pointer whose new-ledger credit is not the register's figure (a
    claim with nothing or only part posted)."""
    pointer = accumulated_account_pointer(asset)
    if pointer is None and not _has_a_live_entry(db, firm_id, client_id, asset["id"]):
        return None
    if pointer is not None:
        register = int(asset.get("accumulated_depreciation_paise") or 0)
        if own_ledger_credit_by_asset(db, firm_id, client_id, pointer, [asset["id"]]).get(asset["id"], 0) == register:
            return None
    return ("This asset's move into the Accumulated Amortisation ledger did not finish: part of its accumulated amortisation is in "
            "each ledger. Finish undoing it first (Depreciation tab, \"Moved by a reclassification\"), because a disposal or a deletion "
            "now would leave both ledgers wrong and the undo refuses a disposed asset.")


def _classify_assets(db, firm_id: str, client_id: str, own_row: dict) -> tuple[list[dict], int, list[dict], list[dict]]:
    """The client's live, undisposed assets sorted into: (those the reclassification would move, the register figure of those already
    pointed at the new ledger, those with a reclassification behind them, those left out with the reason in words). An asset of another
    kind (its cost ledger is on the tangible line) is none of these: it is not this change's business and is not listed.

    The third list is read from the LEDGER as well as from the pointer. `moved_by_reclassification` says a live reclassification entry
    exists for the asset (false for an asset created pointing at its own ledger: it has no move to undo). `unfinished` is an asset whose
    move did not finish: its pointer is gone and an entry is still live (an Undo took it back and could not reverse everything), or it
    points at the new ledger and the ledger holds a different amount for it from the register's (a claim with nothing, or only part,
    posted). It must not be
    offered as a candidate (its history is half in each ledger, and moving it again would move it twice) and it stays on the list so that
    the Undo that finishes it is still there."""
    assets = fetch_all(
        lambda: (db.table("fixed_assets").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
                 .eq("is_disposed", False).is_("deleted_at", "null")),
        label="amortisation_reclass.assets")
    live = {e["source_id"] for e in live_entries(db, firm_id, client_id, [a["id"] for a in assets])}
    pointed = [a["id"] for a in assets if a.get("accumulated_account_id") == own_row["id"]]
    credit = own_ledger_credit_by_asset(db, firm_id, client_id, own_row["id"], pointed)
    cost_cache: dict = {}
    candidates: list[dict] = []
    reclassified: list[dict] = []
    excluded: list[dict] = []
    in_own = 0
    for a in assets:
        row = {"asset_id": a["id"], "asset_code": a.get("asset_code"), "asset_name": a.get("asset_name"),
               "moved_by_reclassification": a["id"] in live, "unfinished": False}
        if a.get("accumulated_account_id"):
            if a["accumulated_account_id"] == own_row["id"]:
                register = int(a.get("accumulated_depreciation_paise") or 0)
                in_own += register
                reclassified.append({**row, "unfinished": register != credit.get(a["id"], 0)})
            continue
        if a["id"] in live:
            reclassified.append({**row, "unfinished": True})
            continue
        cat = a.get("asset_category")
        if cat not in cost_cache:
            cost_cache[cat] = fal.cost_ledger(db, firm_id, client_id, cat)
        ok, why = fal.belongs_in_own_ledger(own_row, cost_cache[cat])
        if ok:
            candidates.append(a)
        elif cost_cache[cat] is None or fal.line_of(cost_cache[cat]) == fal.line_of(own_row):
            excluded.append({"asset_id": a["id"], "asset_code": a.get("asset_code"), "reason": f"Not moved: {why}."})
    return candidates, in_own, reclassified, excluded


_ACCUMULATED_WORDS = ("accumulated", "deprec", "amortis")


def _looks_like_accumulated(row: dict) -> bool:
    """A ledger that could hold depreciation: a fixed-asset family subtype (the one the cash-flow statement already reads as
    "fixed"), or a name that says accumulated, depreciation or amortisation. A bank account in overdraft also has a credit balance and
    is not one."""
    name = str(row.get("account_name") or "").lower()
    return "fixed" in str(row.get("account_subtype") or "").lower() or any(w in name for w in _ACCUMULATED_WORDS)


def _carried_over_candidates(db, firm_id: str, client_id: str, own_row: dict, shared_row: dict) -> list[dict]:
    """The ledgers the Partner may name for the part of the depreciation an asset brought over with it: active Asset ledgers of the
    practice (firm-level or this client's) that hold a CREDIT balance for this client and look like an accumulated-depreciation ledger,
    other than the two this change is about and any on the new ledger's Schedule III line. Offered by the server so that the screen
    never lists Cash in Hand or a bank account in overdraft."""
    chart = fetch_all(
        lambda: fal.asset_ledgers_query(db, firm_id, client_id),
        label="amortisation_reclass.asset_ledgers")
    balances = fetch_all(
        lambda: (db.table("account_period_balances").select("id,account_id,debit_paise,credit_paise")
                 .eq("firm_id", firm_id).eq("client_id", client_id)),
        label="amortisation_reclass.balances") if chart else []
    net: dict[str, int] = {}
    for b in balances:
        net[str(b["account_id"])] = net.get(str(b["account_id"]), 0) + int(b.get("credit_paise") or 0) - int(b.get("debit_paise") or 0)
    skip = {str(own_row["id"]), str(shared_row["id"])}
    own_line = fal.line_of(own_row)
    return [{"id": r["id"], "code": r.get("account_code"), "name": r.get("account_name"), "credit_paise": net[str(r["id"])]}
            for r in sorted(chart, key=lambda r: str(r.get("account_code") or ""))
            if str(r["id"]) not in skip and net.get(str(r["id"]), 0) > 0 and fal.line_of(r) != own_line and _looks_like_accumulated(r)]


# ── prepare ─────────────────────────────────────────────────────────────────

def _check_named_ledger(db, firm_id: str, client_id: str, own_row: dict, shared_row: dict, account_id: str, out: dict):
    """The ledger the Partner named for the carried-over part: an active Asset ledger of this practice and this client, and not the new
    ledger or one on its Schedule III line (a move between two ledgers on one line fixes nothing). Returns the row or None."""
    row = fal.chart_row(db, firm_id, account_id)
    if row is None or row.get("is_active") is not True or row.get("account_type") != "Asset" \
            or row.get("client_id") not in (None, client_id):
        out["refusals"].append("The ledger named for the carried-over part is not an active asset ledger of this practice.")
        return None
    if str(row["id"]) == str(own_row["id"]) or fal.line_of(row) == fal.line_of(own_row):
        out["refusals"].append("The ledger named for the carried-over part is the Accumulated Amortisation ledger itself, or presents on "
                               "the same Schedule III line. Moving from it to the new ledger changes nothing; name the ledger the "
                               "depreciation really sits in.")
        return None
    return row


def _dated_before_it_existed(candidates: list[dict], plans: list, as_at: str) -> list[str]:
    """An entry that takes brought-over depreciation out of a ledger on a date before the asset was on the books would debit that ledger
    before the asset's depreciation was ever in it."""
    refusals: list[str] = []
    by_id = {p.asset_id: p for p in plans}
    for a in candidates:
        plan = by_id.get(a["id"])
        began = max(str(a.get("opening_position_date") or "")[:10], str(a.get("purchase_date") or "")[:10])
        if plan is not None and plan.outcome == arc.MOVES and plan.from_carried_paise and began and as_at < began:
            refusals.append(
                f"{plan.asset_code} brought {rupee_text(plan.from_carried_paise)} of depreciation with it, but it is only on the books from "
                f"{say_date(began)}: an entry dated {say_date(as_at)} would debit the ledger it sits in before this asset existed. State "
                f"a date on or after {say_date(began)}.")
    return refusals


def prepare(db, firm_id: str, client_id: str, as_at: str, carried_over_from_account_id: Optional[str] = None) -> dict:
    """Everything the preview shows and the post acts on: facts read, plans made, refusals decided. Writes nothing."""
    today = ist_today().isoformat()
    as_at = _parse_as_at(as_at, today)
    out: dict = {"as_at": as_at, "today": today, "ready": False, "refusals": [], "assets": [], "excluded": [],
                 "reclassified": [], "own_ledger": None, "shared_ledger": None, "carried_over_ledger": None,
                 "carried_over_candidates": [], "entry_dates": [], "later_dates": [], "carried_over_total_paise": 0, "journals_to_post": 0, "moves_count": 0, "pointed_only_count": 0,
                 "total_to_move_paise": 0, "financial_years": []}

    own = fal.own_ledger(db, firm_id, client_id)
    if own.row is None:
        out["refusals"].append(own.problem)
        return out
    shared = fal.shared_ledger(db, firm_id, client_id)
    if shared is None:
        out["refusals"].append("This practice's chart has no shared Accumulated Depreciation ledger to move amortisation out of.")
        return out
    out["own_ledger"] = {"id": own.row["id"], "code": own.row.get("account_code"), "name": own.row.get("account_name")}
    out["shared_ledger"] = {"id": shared["id"], "code": shared.get("account_code"), "name": shared.get("account_name")}
    if fal.line_of(shared) == fal.line_of(own.row):
        out["refusals"].append("The shared Accumulated Depreciation ledger already presents on the same Schedule III line as the "
                               "Accumulated Amortisation ledger, so there is nothing to separate.")
        return out
    out["carried_over_candidates"] = _carried_over_candidates(db, firm_id, client_id, own.row, shared)

    named = bool(carried_over_from_account_id)
    carried_is_shared = not named or carried_over_from_account_id == shared["id"]
    carried_row = shared
    if not carried_is_shared:
        carried_row = _check_named_ledger(db, firm_id, client_id, own.row, shared, carried_over_from_account_id, out)
        if carried_row is None:
            return out
        out["carried_over_ledger"] = {"id": carried_row["id"], "code": carried_row.get("account_code"),
                                      "name": carried_row.get("account_name")}

    candidates, in_own, out["reclassified"], excluded_now = _classify_assets(db, firm_id, client_id, own.row)
    out["excluded"].extend(excluded_now)
    unfinished = [r for r in out["reclassified"] if r["unfinished"]]
    if unfinished:
        out["refusals"].append(
            f"{', '.join(str(r['asset_code'] or r['asset_name']) for r in unfinished)} has a reclassification that did not finish (a move "
            "that stopped part way, or an Undo that could not reverse everything), so part of its amortisation is in each ledger. Run "
            "Undo on it to finish, then prepare this again: moving it now would move it twice.")

    positions = depreciation_positions(db, firm_id, client_id, [a["id"] for a in candidates], shared["id"], as_at, today) if candidates else {}
    plans: list[arc.AssetPlan] = []
    for a in sorted(candidates, key=lambda x: (str(x.get("asset_code") or ""), str(x["id"]))):
        to_as_at, later = positions.get(a["id"], (0, ()))
        plans.append(arc.plan_asset(arc.AssetPosition(
            asset_id=a["id"], asset_code=str(a.get("asset_code") or ""), asset_name=str(a.get("asset_name") or ""),
            register_paise=int(a.get("accumulated_depreciation_paise") or 0),
            posted_to_as_at_paise=to_as_at, posted_later=later), says_rupees=rupee_text))
    for p in plans:
        if p.outcome == arc.EXCLUDED:
            out["excluded"].append({"asset_id": p.asset_id, "asset_code": p.asset_code, "reason": p.reason})
        else:
            out["assets"].append({
                "asset_id": p.asset_id, "asset_code": p.asset_code, "asset_name": p.asset_name, "outcome": p.outcome,
                "register_paise": p.register_paise,
                "posted_by_depreciation_paise": p.from_shared_to_as_at_paise + p.from_shared_after_as_at_paise,
                "carried_over_paise": p.from_carried_paise,
                "moves_as_at_paise": p.from_shared_to_as_at_paise + p.from_carried_paise,
                "moves_later_paise": p.from_shared_after_as_at_paise,
                "journal_count": (1 if p.from_shared_to_as_at_paise or p.from_carried_paise else 0) + len(p.later)})

    out["refusals"].extend(_dated_before_it_existed(candidates, plans, as_at))
    carried_total = sum(p.from_carried_paise for p in plans if p.outcome == arc.MOVES)
    out["carried_over_total_paise"] = carried_total
    out["journals_to_post"] = sum(a["journal_count"] for a in out["assets"])
    out["moves_count"] = sum(1 for p in plans if p.outcome == arc.MOVES)
    out["pointed_only_count"] = sum(1 for p in plans if p.outcome == arc.POINTED_ONLY)
    if carried_total and not named:
        # NEVER BY DEFAULT. The shared ledger usually holds the depreciation of the tangible assets too, so a blank that meant "the shared
        # ledger" would pass the balance check and take the tangible assets' credit, leaving the tangible line too high. The Partner
        # says where it sits, and choosing the shared ledger is a choice they make on purpose.
        out["refusals"].append(
            f"{sum(1 for p in plans if p.outcome == arc.MOVES and p.from_carried_paise)} asset(s) brought {rupee_text(carried_total)} of "
            "depreciation with them from other books, and this product cannot tell which ledger it sits in. Choose the ledger it sits in "
            "(an imported trial balance often puts it in a ledger of its own), or choose the shared Accumulated Depreciation ledger "
            "if that is where it really is. Nothing is moved until you say.")
    dates = arc.entry_dates(plans, as_at)
    out["entry_dates"] = list(dates)
    out["later_dates"] = [d for d in dates if d != as_at]
    shared_monthly = fal.ledger_monthly_credit(db, firm_id, client_id, shared["id"])
    carried_monthly = None if carried_is_shared else fal.ledger_monthly_credit(db, firm_id, client_id, carried_row["id"])
    points = arc.check_dates(dates, today)
    check = arc.check_batch(
        plans, as_at=as_at, shared_balance_at={d: fal.balance_as_at(shared_monthly, d) for d in points},
        carried_source_is_shared=carried_is_shared,
        carried_balance_at=None if carried_is_shared else {d: fal.balance_as_at(carried_monthly, d) for d in points if d >= as_at},
        own_credit_paise=fal.ledger_credit_balance(db, firm_id, client_id, own.row["id"]),
        already_in_own_ledger_paise=in_own, says_rupees=rupee_text, says_date=say_date)
    out["total_to_move_paise"] = check.total_paise
    out["refusals"].extend(check.refusals)

    moving = [p for p in plans if p.outcome == arc.MOVES]
    if moving:
        for d in dates:
            reason = period_lock_service.closure_reason(db, firm_id, client_id, d)
            if reason:
                out["refusals"].append(f"An entry of this move is dated {say_date(d)}: {reason}")
                break
    out["financial_years"] = arc.financial_years_fixed(say_date(as_at), say_date(today), [say_date(d) for d in out["later_dates"]])
    out["ready"] = not out["refusals"] and bool(plans) and any(p.outcome in (arc.MOVES, arc.POINTED_ONLY) for p in plans)
    out["_plans"] = plans
    out["_dates"] = dates
    out["_own"] = own.row
    out["_shared"] = shared
    out["_carried_row"] = carried_row
    out["_carried_is_shared"] = carried_is_shared
    return out


def _client_has_an_intangible_asset(db, firm_id: str, client_id: str) -> bool:
    """Whether any live asset of the client has its cost on the intangible line, which is when a missing Accumulated Amortisation
    ledger is the client's business. A firm whose chart has none says nothing on a client that holds no intangible asset."""
    assets = fetch_all(
        lambda: (db.table("fixed_assets").select("id,asset_category").eq("firm_id", firm_id).eq("client_id", client_id)
                 .eq("is_disposed", False).is_("deleted_at", "null")),
        label="amortisation_reclass.summary_assets")
    for category in {a.get("asset_category") for a in assets}:
        cost = fal.cost_ledger(db, firm_id, client_id, category)
        if cost is not None and fal.line_of(cost) == "intangible_assets":
            return True
    return False


def summary(db, firm_id: str, client_id: str) -> dict:
    """What the screen needs to decide whether to show itself and what to offer an Undo on, from the register, the chart and the
    reclassification entries (no balance sheet figure). `unmoved` = intangible assets still in the shared ledger, `moved_assets` =
    those an Undo can act on (a reclassification entry is live for them, or their move did not finish; `unfinished` marks the
    second), `refusal` = why the feature cannot work for this client's practice (no Accumulated Amortisation ledger, or two), said
    only where the client holds an intangible asset, in words and not by vanishing."""
    own = fal.own_ledger(db, firm_id, client_id)
    nothing = {"unmoved": 0, "moved": 0, "unfinished": 0, "excluded": 0, "moved_assets": []}
    if own.row is None:
        has = _client_has_an_intangible_asset(db, firm_id, client_id)
        return {**nothing, "refusal": own.problem if has else None, "own_ledger": None}
    shared = fal.shared_ledger(db, firm_id, client_id)
    own_ledger = {"id": own.row["id"], "name": own.row.get("account_name")}
    if shared is None or fal.line_of(shared) == fal.line_of(own.row):
        return {**nothing, "refusal": None, "own_ledger": own_ledger}
    candidates, _in_own, reclassified, excluded = _classify_assets(db, firm_id, client_id, own.row)
    moved_assets = [r for r in reclassified if r["moved_by_reclassification"] or r["unfinished"]]
    return {"unmoved": len(candidates), "moved": len(moved_assets), "unfinished": sum(1 for r in moved_assets if r["unfinished"]),
            "excluded": len(excluded), "moved_assets": moved_assets, "refusal": None, "own_ledger": own_ledger}


def preview(db, firm_id: str, client_id: str, as_at: str, carried_over_from_account_id: Optional[str] = None) -> dict:
    out = prepare(db, firm_id, client_id, as_at, carried_over_from_account_id)
    return {k: v for k, v in out.items() if not k.startswith("_")}


# ── post ────────────────────────────────────────────────────────────────────

def _claim(db, firm_id: str, client_id: str, plan: arc.AssetPlan, own_id: str) -> bool:
    rows = (db.table("fixed_assets").update({"accumulated_account_id": own_id})
            .eq("id", plan.asset_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .is_("accumulated_account_id", "null").eq("accumulated_depreciation_paise", plan.register_paise)
            .eq("is_disposed", False).is_("deleted_at", "null").execute().data) or []
    return bool(rows)


def _unclaim(db, firm_id: str, client_id: str, asset_id: str, own_id: str, register_paise: int) -> bool:
    """Take the pointer back with the SAME compare-and-set that gave it: only while the asset still points at the new ledger, still
    carries the figure it had, and is not disposed. A month or a disposal that landed first makes it miss, and the caller says so."""
    rows = (db.table("fixed_assets").update({"accumulated_account_id": None})
            .eq("id", asset_id).eq("firm_id", firm_id).eq("client_id", client_id).eq("accumulated_account_id", own_id)
            .eq("accumulated_depreciation_paise", register_paise).eq("is_disposed", False).is_("deleted_at", "null")
            .execute().data) or []
    return bool(rows)


def _reverse_all(svc, db, firm_id: str, entries: list[dict], narration: str, user: dict) -> tuple[list[str], list[tuple[dict, Exception]]]:
    """Reverse each entry on the day it is dated (so no balance sheet cut between shows the move half undone), latest first, treating
    "already reversed" as done. Returns (the reversal ids, the entries that could not be reversed with why)."""
    done: list[str] = []
    failed: list[tuple[dict, Exception]] = []
    for e in sorted(entries, key=lambda x: str(x["entry_date"]), reverse=True):
        try:
            rid = svc.reverse_entry(db, firm_id, e["id"], str(e["entry_date"])[:10], narration, created_by=user.get("id"))
            if rid:
                done.append(rid)
        except HTTPException as exc:
            if exc.status_code == 409 and "already been reversed" in str(exc.detail):
                continue
            failed.append((e, exc))
        except Exception as exc:                                           # noqa: BLE001 — named in the reply, never swallowed
            failed.append((e, exc))
    return done, failed


def why(exc: Exception) -> str:
    """A failure in words for the browser. Our own refusals (an HTTPException's detail, the kernel's ValueError) are already sentences;
    anything else goes through the one speaker for database refusals, and an exception it cannot honestly word is not shown raw."""
    from core.exceptions import unhandled_failure
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(exc, ValueError) and str(exc):
        return str(exc)
    spoken = unhandled_failure(exc)
    return spoken[1] if spoken else "an unexpected error, which has been logged"


def post(db, firm_id: str, client_id: str, as_at: str, asset_ids: list[str], expected_total_paise: int,
         carried_over_from_account_id: Optional[str], user: dict) -> dict:
    """Post the reclassification for the named assets. A Partner's act (the route asks `accounting`/`approve`)."""
    from services.audit_service import log_event
    from services.phase2_journal_service import phase2_journal_service as svc

    prep = prepare(db, firm_id, client_id, as_at, carried_over_from_account_id)
    if prep["refusals"]:
        raise HTTPException(status_code=422, detail=" ".join(prep["refusals"]))
    plans = {p.asset_id: p for p in prep["_plans"] if p.outcome in (arc.MOVES, arc.POINTED_ONLY)}
    wanted = [a for a in dict.fromkeys(asset_ids)]
    unknown = [a for a in wanted if a not in plans]
    if not wanted or unknown:
        raise HTTPException(status_code=409, detail=(
            "Some of the assets named are not in the reclassification as it stands now (" + ", ".join(unknown or ["none named"]) +
            "). Preview it again."))
    total = sum(plans[a].credit_to_own_ledger_paise for a in wanted)
    if total != int(expected_total_paise):
        raise HTTPException(status_code=409, detail=(
            f"The total has changed since you looked at it: it was {rupee_text(int(expected_total_paise))} and is now "
            f"{rupee_text(total)}. A depreciation was probably posted or reversed in between. Preview it again."))

    own, shared, carried_row = prep["_own"], prep["_shared"], prep["_carried_row"]
    carried_is_shared = prep["_carried_is_shared"]
    moved, skipped, failed = [], [], []
    for asset_id in sorted(wanted, key=lambda a: plans[a].asset_code):
        plan = plans[asset_id]
        if not _claim(db, firm_id, client_id, plan, own["id"]):
            skipped.append({"asset_id": asset_id, "asset_code": plan.asset_code,
                            "reason": "It changed since you looked (a depreciation was posted, or it was disposed or edited). Preview again."})
            continue
        posted: list[str] = []
        try:
            asset = (db.table("fixed_assets").select("*").eq("id", asset_id).eq("firm_id", firm_id).limit(1).execute().data or [{}])[0]
            tranches: list[tuple[str, list[tuple[str, int]]]] = []
            first: list[tuple[str, int]] = []
            if plan.from_shared_to_as_at_paise:
                first.append((shared["id"], plan.from_shared_to_as_at_paise))
            if plan.from_carried_paise:
                if carried_is_shared and first:
                    first[0] = (shared["id"], first[0][1] + plan.from_carried_paise)
                else:
                    first.append((carried_row["id"], plan.from_carried_paise))
            if first:
                tranches.append((prep["as_at"], first))
            tranches.extend((d, [(shared["id"], amount)]) for d, amount in plan.later)
            for number, (when, from_accounts) in enumerate(tranches, start=1):
                posted.append(_post_journal(svc, asset, when, number, from_accounts, own["id"], firm_id, client_id, user))
        except Exception as exc:                                           # noqa: BLE001 — compensated below, then reported by name
            _logger.error("amortisation reclassification failed for %s: %s", plan.asset_code or plan.asset_name, exc, exc_info=True)
            failed.append(_recover(db, svc, firm_id, client_id, plan, own["id"], exc, user))
            continue
        log_event(firm_id, "fixed_asset", asset_id, "amortisation_reclassified",
                  actor_id=user.get("auth_user_id"), actor_email=user.get("email"),
                  new_data={"as_at": prep["as_at"], "moved_paise": plan.credit_to_own_ledger_paise,
                            "carried_over_paise": plan.from_carried_paise, "journals": posted, "own_ledger_id": own["id"]})
        moved.append({"asset_id": asset_id, "asset_code": plan.asset_code, "moved_paise": plan.credit_to_own_ledger_paise,
                      "journal_entry_ids": posted})
    return {"as_at": prep["as_at"], "moved": moved, "skipped": skipped, "failed": failed,
            "total_moved_paise": sum(m["moved_paise"] for m in moved)}


def _recover(db, svc, firm_id: str, client_id: str, plan: arc.AssetPlan, own_id: str, cause: Exception, user: dict) -> dict:
    """A journal failed after the claim. Reverse what is LIVE for the asset in the ledger (found by asking the ledger, so a journal whose
    call timed out after it committed is found too), and take the claim back only when nothing is left live. If a reversal fails the
    claim STAYS: the asset is reported as partly moved, with the entries still live, for the undo to finish."""
    from core.observability import capture_posting_failure
    base = {"asset_id": plan.asset_id, "asset_code": plan.asset_code, "reason": why(cause)}
    try:
        live = live_entries(db, firm_id, client_id, [plan.asset_id])
    except Exception as exc:                                               # noqa: BLE001 — cannot see the ledger: keep the claim
        capture_posting_failure(exc, operation="amortisation_reclass.recover_read", firm_id=firm_id, client_id=client_id,
                                asset_id=plan.asset_id)
        return {**base, "partly_moved": True, "live_entry_ids": [],
                "reason": base["reason"] + " The ledger could not be read afterwards, so the asset stays pointed at the new ledger "
                                           "and the move is unconfirmed: use Undo on this asset, which works from the ledger."}
    _done, still = _reverse_all(svc, db, firm_id, live, "Reclassification undone: a later step failed", user)
    if still:
        for entry, exc in still:
            capture_posting_failure(exc, operation="amortisation_reclass.compensate", firm_id=firm_id, client_id=client_id,
                                    asset_id=plan.asset_id, entry_id=entry["id"])
        return {**base, "partly_moved": True, "live_entry_ids": [e["id"] for e, _x in still],
                "reason": base["reason"] + " What had been posted could not be reversed (" + why(still[0][1]) + "), so the asset "
                                           "stays pointed at the new ledger with the entries below still posted: use Undo on this "
                                           "asset to finish taking it back."}
    try:
        unclaimed = _unclaim(db, firm_id, client_id, plan.asset_id, own_id, plan.register_paise)
    except Exception as exc:                                               # noqa: BLE001 — reported; the asset stays pointed, and says so
        capture_posting_failure(exc, operation="amortisation_reclass.unclaim", firm_id=firm_id, client_id=client_id,
                                asset_id=plan.asset_id)
        unclaimed = False
    if not unclaimed:
        return {**base, "partly_moved": True, "live_entry_ids": [],
                "reason": base["reason"] + " The entries were reversed, but the asset changed meanwhile and could not be taken off "
                                           "the new ledger: use Undo on this asset."}
    return base


def _post_journal(svc, asset: dict, entry_date: str, tranche: int, from_accounts: list[tuple[str, int]], to_id: str,
                  firm_id: str, client_id: str, user: dict) -> str:
    entry_id = svc.journal_for_amortisation_reclass(
        asset, entry_date=entry_date, tranche=tranche, from_accounts=from_accounts, to_account_id=to_id,
        firm_id=firm_id, client_id=client_id, created_by=user.get("id"))
    if not entry_id:
        raise RuntimeError("The reclassification journal was not posted.")
    return entry_id


# ── undo ────────────────────────────────────────────────────────────────────

def undo(db, firm_id: str, asset_id: str, user: dict) -> dict:
    """Undo one asset's reclassification, working from the LEDGER: its live reclassification entries are reversed, each on its own day,
    and the pointer is taken back with a compare-and-set. Allowed while no live depreciation or disposal of the asset touches the new
    ledger. Safe to run again after a failure: with the pointer already gone and an entry still live it reverses what is left, and it
    never puts the pointer back."""
    from services.audit_service import log_event
    from services.phase2_journal_service import phase2_journal_service as svc

    rows = (db.table("fixed_assets").select("*").eq("id", asset_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset = rows[0]
    client_id = asset["client_id"]
    own_id = accumulated_account_pointer(asset)
    if asset.get("is_disposed") or asset.get("deleted_at"):
        raise HTTPException(status_code=409, detail="A disposed or deleted asset's reclassification cannot be undone: its disposal "
                                                    "cleared the ledger the asset points at.")
    live = live_entries(db, firm_id, client_id, [asset_id])
    register = int(asset.get("accumulated_depreciation_paise") or 0)
    if not live:
        if own_id is None:
            raise HTTPException(status_code=409, detail="This asset's accumulated depreciation is in the shared ledger; there is nothing to undo.")
        # A pointer with no entry behind it: an asset created pointing at its own ledger (its months credit that ledger), or one claimed
        # by a reclassification that stopped before posting anything (nothing credits that ledger, and the register carries a figure).
        if register > 0 and not _later_postings_touching(db, firm_id, client_id, asset_id, own_id):
            if not _unclaim(db, firm_id, client_id, asset_id, own_id, register):
                raise HTTPException(status_code=409, detail="The asset changed while this was being undone, and nothing was changed. Try again.")
            log_event(firm_id, "fixed_asset", asset_id, "amortisation_reclassification_undone",
                      actor_id=user.get("auth_user_id"), actor_email=user.get("email"),
                      new_data={"reversal_entry_ids": [], "own_ledger_id": own_id, "note": "pointer with no entry behind it"})
            return {"asset_id": asset_id, "reversal_entry_ids": []}
        if own_ledger_credit_by_asset(db, firm_id, client_id, own_id, [asset_id]).get(asset_id, 0) != register:
            raise HTTPException(status_code=409, detail=(
                "A reclassification of this asset was started and did not post, and depreciation has been posted on the new ledger since: "
                "taking it back now would leave those months there. Reverse the months posted since (latest first), then undo again."))
        raise HTTPException(status_code=409, detail=(
            "No reclassification entry is recorded for this asset: it was created pointing at its own ledger, so there is no move to "
            "undo. Its depreciation is credited to that ledger from the start."))
    if own_id is not None:
        later = _later_postings_touching(db, firm_id, client_id, asset_id, own_id)
        if later:
            raise HTTPException(status_code=409, detail=(
                "Depreciation has been posted on this asset since it was reclassified, or it has been disposed of, and that is in the new "
                "ledger: undoing now would leave it there with its history moved back. Reverse those months first (latest first), then "
                "undo the reclassification."))
    today = ist_today().isoformat()
    for e in live:
        reason = period_lock_service.closure_reason(db, firm_id, client_id, str(e["entry_date"])[:10])
        if reason:
            raise HTTPException(status_code=422, detail=f"The entry dated {say_date(e['entry_date'])} cannot be reversed: {reason}")
    # Take the pointer back FIRST, so a depreciation in flight on the new pointer finds it moved (it compares and sets on the pointer it
    # used). It is NEVER put back: if a reversal below fails, the entries still live are reversed by running this again.
    if own_id is not None and not _unclaim(db, firm_id, client_id, asset_id, own_id, register):
        fresh = (db.table("fixed_assets").select("accumulated_account_id,is_disposed")
                 .eq("id", asset_id).eq("firm_id", firm_id).limit(1).execute().data) or [{}]
        if accumulated_account_pointer(fresh[0]) is not None or fresh[0].get("is_disposed"):
            raise HTTPException(status_code=409, detail=(
                "The asset changed while this was being undone (a month was posted, or it was disposed of), and nothing was changed. "
                "Look at it again."))
    done, still = _reverse_all(svc, db, firm_id, live, "Reclassification of accumulated amortisation undone", user)
    if still:
        raise HTTPException(status_code=502, detail=(
            f"The asset is back on the shared ledger, but {len(still)} of its {len(live)} reclassification entries could not be "
            f"reversed yet ({why(still[0][1])}). Nothing else was changed; run Undo again to finish."))
    log_event(firm_id, "fixed_asset", asset_id, "amortisation_reclassification_undone",
              actor_id=user.get("auth_user_id"), actor_email=user.get("email"),
              new_data={"reversal_entry_ids": done, "own_ledger_id": own_id, "on": today})
    return {"asset_id": asset_id, "reversal_entry_ids": done}
