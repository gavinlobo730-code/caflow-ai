"""The cross-item NRV review (POST-A-111): the sheet, read in one question, and the batch, posted one line at a time through the
single-item door's own function.

The rule is `domain/inventory/nrv_review.py`. This module reads its inputs and posts its answer:

* the sheet reads the client's goods once (`service_catalogue`, every page, in the register's own name order) and every good's latest
  stock-ledger row in ONE question (`stock_latest_rows_service.latest_rows_for`, the register's own read), so what crosses the wire is
  one row per item and never the ledger;
* the batch calls `domain.inventory_service.apply_nrv_writedown` once per line, exactly as `POST /items/{id}/writedown` calls it, under
  one reference, with the client's cost formula read once. The batch is not atomic and cannot be (each write-down is its own journal
  through the posting kernel), so a line that could not be recorded is NAMED, and posting the same sheet again is safe: a line already
  written down to the value entered is no longer above it, so it is left alone.

# CA REVIEW REQUIRED — every NRV on the sheet is the CA's own estimate, and the batch posts only after the CA confirms it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_ordered
from core.observability import capture_posting_failure, capture_soft_failure
from domain.inventory import nrv_review


def _review_goods(db, firm_id: str, client_id: str) -> list[dict]:
    """Every stock-tracked product of the client, in the register's order (name, then id)."""
    return fetch_all_ordered(
        lambda: (db.table("service_catalogue")
                 .select("id, name, unit, kind")
                 .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")),
        ("name",), label="inventory.nrv_review_items")


def _refuse_review_lines(item_ids: list[str], goods: list[dict], *, allow_empty: bool, capped: bool) -> None:
    """Refuse the request's lines before anything is read: an empty batch (where one is not allowed), more lines than one posting
    carries (where `capped`), an item named twice, or a line that is not one of this client's goods."""
    if not (allow_empty and not item_ids):
        problem = nrv_review.lines_problem(item_ids, capped=capped)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
    problem = nrv_review.unknown_items_problem(item_ids, [g["id"] for g in goods])
    if problem:
        raise HTTPException(status_code=422, detail=problem)


def review_sheet(db, *, firm_id: str, client_id: str, lines: list[dict]) -> dict:
    """The review sheet with the CA's typed NRVs applied: every good that holds stock now, what it holds, and what each typed NRV
    would write down. Reads only: no ledger row, no journal, no audit entry. An empty `lines` is the sheet as it stands.

    NOT CAPPED AT `MAX_LINES`: the screen asks for every typed line at once, the register is read in one question whatever is asked,
    and the lines are bounded by the client's own goods (anything else is refused below, and so is an item named twice). The cap is
    the posting's, which the screen sends in parts."""
    from services.stock_latest_rows_service import latest_rows_for

    goods = _review_goods(db, firm_id, client_id)
    item_ids = [str(line["service_catalogue_id"]) for line in lines]
    _refuse_review_lines(item_ids, goods, allow_empty=True, capped=False)
    latest = latest_rows_for(db, firm_id, client_id, {g["id"] for g in goods})
    typed = {str(line["service_catalogue_id"]): int(line["nrv_per_unit_paise"]) for line in lines}
    return nrv_review.build_sheet(goods, latest, typed)


def _review_journal_links(db, firm_id: str, client_id: str, movement_ids: list[str]) -> Optional[dict[str, Optional[str]]]:
    """{movement id: its journal entry id or None}, or None when the read itself failed (which is not "no journal")."""
    if not movement_ids:
        return {}
    from core.db_provider import privileged_for
    try:
        rows = fetch_all(lambda: (privileged_for(db).table("inventory_stock_ledger")
                                  .select("id, journal_entry_id")
                                  .eq("firm_id", firm_id).eq("client_id", client_id)
                                  .in_("id", movement_ids)),
                         label="inventory.nrv_review_journal_links")
    except Exception as swallowed:  # noqa: BLE001 — a failed read is reported as unknown on each line, never as "no journal"
        capture_soft_failure(swallowed, operation="nrv_review.journal_links", firm_id=firm_id, client_id=client_id)
        return None
    return {str(r["id"]): r.get("journal_entry_id") for r in rows}


def post_review(db, *, firm_id: str, client_id: str, writedown_date: str, reference_no: str, lines: list[dict],
         created_by: Optional[str]) -> dict:
    """Write each line's item down to the NRV the CA entered, under one reference, through the single-item door's function.

    The firm's locked year and the client's finalised year are asked by the route before this runs (`period_lock_service.
    assert_not_closed`, as the single door asks them): the posting kernel asks the same closures for every journal, but only after
    `apply_nrv_writedown` has written the line's stock row, which would then stand in a closed year with no journal behind it. The
    filed-return lock is not asked, for the single door's reason: a write-down carries no GST line and reverses no credit, so it
    cannot change what a return said."""
    from domain.inventory_service import apply_nrv_writedown, nrv_writedown_answer, resolve_costing_policy
    from services.stock_latest_rows_service import latest_rows_for

    goods = _review_goods(db, firm_id, client_id)
    names = {str(g["id"]): g.get("name") or "" for g in goods}
    item_ids = [str(line["service_catalogue_id"]) for line in lines]
    _refuse_review_lines(item_ids, goods, allow_empty=False, capped=True)

    # What each line would do as the batch starts, read once for the sheet: it is what tells a line that needed nothing from one that
    # needed a write-down and did not get one (`apply_nrv_writedown` answers None for both, by design).
    before = latest_rows_for(db, firm_id, client_id, set(item_ids))
    # ONE read of the client's cost formula for the whole batch, as the count sheet does, for the client read under this firm.
    client = (db.table("clients").select("id").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    policy = resolve_costing_policy(db, client[0]["id"])

    posted: list[dict] = []
    not_needed: list[dict] = []
    failed: list[dict] = []
    for line in lines:
        item_id = str(line["service_catalogue_id"])
        nrv = int(line["nrv_per_unit_paise"])
        expected = nrv_writedown_answer(before.get(item_id), nrv)
        try:
            movement = apply_nrv_writedown(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=item_id,
                movement_date=writedown_date, nrv_per_unit_paise=nrv,
                reference_no=reference_no, created_by=created_by, policy=policy,
            )
        except Exception as swallowed:  # noqa: BLE001 — the function promises not to raise; one line that does must not hide the rest
            capture_posting_failure(swallowed, operation="nrv_review.post_line", firm_id=firm_id, client_id=client_id,
                                    source_id=item_id, reference_no=reference_no)
            movement = None
            expected = {**expected, "needed": True}
        if movement:
            posted.append({"service_catalogue_id": item_id, "name": names.get(item_id, ""), "nrv_per_unit_paise": nrv,
                           "write_down_paise": -int(movement["value_delta_paise"]),
                           "movement_id": movement.get("id"), "journal_posted": None})
        elif expected["needed"]:
            failed.append({"service_catalogue_id": item_id, "name": names.get(item_id, ""), "nrv_per_unit_paise": nrv,
                           "why": "The write-down could not be recorded just now; nothing was posted for this item."})
        else:
            not_needed.append({"service_catalogue_id": item_id, "name": names.get(item_id, ""), "nrv_per_unit_paise": nrv,
                               "why": ("The item holds no stock." if not expected["has_stock"] else
                                       "The value entered times the quantity held is not below the carrying value.")})

    links = _review_journal_links(db, firm_id, client_id, [p["movement_id"] for p in posted if p.get("movement_id")])
    for p in posted:
        if links is not None and p.get("movement_id"):
            p["journal_posted"] = bool(links.get(str(p["movement_id"])))

    return {
        "reference_no": reference_no,
        "writedown_date": writedown_date,
        "posted": posted,
        "not_needed": not_needed,
        "failed": failed,
        "posted_count": len(posted),
        "not_needed_count": len(not_needed),
        "failed_count": len(failed),
        "write_down_paise": sum(p["write_down_paise"] for p in posted),
        "message": nrv_review.posting_sentence(reference_no=reference_no, posted=posted, not_needed=not_needed, failed=failed),
    }
