"""Where an asset is and who keeps it, with its dated history (POST-A-112, migration 591).

`fixed_assets.location` was one free-text field that a move overwrote, so where an asset was last March, and who held it before, was
nowhere, and nothing recorded who an asset is in the keeping of. A movement is now a row of `fixed_asset_movements`, written only by
the database function `record_fixed_asset_movement`, which in ONE transaction stores where the asset was and who held it (read off
the asset itself, never sent) and moves the asset: a movement and the register's place and keeper are written together. It also asks
that the place and keeper the person's form opened on are still the register's, so a form opened before somebody else recorded a
movement cannot put the asset back where it was (409, nothing recorded).

Correcting a mistyped place or keeper stays an edit of the asset (`PATCH /api/fixed-assets/{id}`), which records no movement: a typo
is not a movement, so a correction changes the register alone and the latest movement keeps what was recorded then.

Every read names the firm and the client; the write goes through the API's privileged client, because the signed-in role holds no
write on the table and may not call the function, and the route asks who is calling first.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_errors import error_code
from core.db_paging import fetch_all, fetch_all_in
from core.db_provider import privileged_for

MAX_TEXT = 200
MAX_NOTE = 500
#: The place and keeper a form opened on are only compared, never stored; the bound only keeps a request finite (a place written by the
#: opening register before 591 had no limit).
MAX_SEEN = 2000
#: The one sentence for an asset that is not there or not the caller's to reach (the routes, and the function's own P0002).
NOT_FOUND = "Asset not found"


def _message(exc: BaseException) -> str:
    """The sentence the database function raised, wherever the client put it."""
    said = getattr(exc, "message", None)
    if isinstance(said, str) and said.strip():
        return said.strip()
    first = (getattr(exc, "args", None) or [None])[0]
    if isinstance(first, dict) and isinstance(first.get("message"), str):
        return first["message"].strip()
    return str(exc).strip()


def _with_names(db, firm_id: str, rows: list[dict]) -> list[dict]:
    """Each movement with the name of the member who recorded it (`recorded_by`), None where the member is gone."""
    ids = sorted({str(r["created_by"]) for r in rows if r.get("created_by")})
    names = {}
    if ids:
        for u in fetch_all_in(lambda: db.table("users").select("id, full_name, email").eq("firm_id", firm_id), "id", ids,
                              label="fixed_asset_movements.recorded_by"):
            names[str(u.get("id"))] = u.get("full_name") or u.get("email")
    return [{**r, "recorded_by": names.get(str(r.get("created_by")))} for r in rows]


def history(db, firm_id: str, client_id: str, asset_id: str) -> list[dict]:
    """The asset's movements, latest first (by the day it moved, then the moment it was recorded), every one of them."""
    # The columns are written out here, not held in a constant, so the backend column check reads them against the schema.
    rows = fetch_all(lambda: db.table("fixed_asset_movements")
                     .select("id, asset_id, moved_on, from_location, to_location, from_custodian, to_custodian, note, created_by, created_at")
                     .eq("firm_id", firm_id).eq("client_id", client_id).eq("asset_id", asset_id),
                     label="fixed_asset_movements.history")
    rows.sort(key=lambda r: (str(r.get("moved_on") or ""), str(r.get("created_at") or ""), str(r.get("id") or "")), reverse=True)
    return _with_names(db, firm_id, rows)


def record(db, firm_id: str, client_id: str, asset_id: str, *, moved_on: str, seen_location: Optional[str],
           seen_custodian: Optional[str], to_location: Optional[str], to_custodian: Optional[str], note: Optional[str],
           recorded_by: Optional[str]) -> dict:
    """Record one movement and move the asset, through the database function, and answer the stored row with who recorded it.

    `seen_location` and `seen_custodian` are the place and keeper the person's form opened on; `to_location` and `to_custodian` are
    where the asset is and who keeps it AFTER the movement (the screen offers the present ones to change); a blank one means none. The
    function's refusals are its own sentences: 404 for an asset that is not this client's, 409 for an asset that has moved since the
    form was opened, 422 for what cannot be a movement (disposed, a day not yet come, before the purchase or the latest movement,
    nothing moved)."""
    try:
        res = privileged_for(db).rpc("record_fixed_asset_movement", {
            "p_firm_id": firm_id, "p_client_id": client_id, "p_asset_id": asset_id, "p_moved_on": moved_on,
            "p_seen_location": seen_location, "p_seen_custodian": seen_custodian,
            "p_to_location": to_location, "p_to_custodian": to_custodian, "p_note": note, "p_created_by": recorded_by,
        }).execute()
    except Exception as exc:  # noqa: BLE001 - every database refusal is a sentence, and anything else is raised as it was
        code = error_code(exc)
        if code == "P0002":
            raise HTTPException(status_code=404, detail=NOT_FOUND) from exc
        if code == "55000":
            raise HTTPException(status_code=409, detail=_message(exc)) from exc
        if code == "23514":
            raise HTTPException(status_code=422, detail=_message(exc)) from exc
        raise
    row = res.data
    if isinstance(row, list):
        row = row[0] if row else None
    if not isinstance(row, dict):
        raise HTTPException(status_code=500, detail="The movement was recorded but its row could not be read back. Reload the asset.")
    return _with_names(db, firm_id, [row])[0]
