"""A physical count of a client's fixed assets, the working paper a CA keeps for the audit (POST-A-112, migration 592).

A count is a row of `fixed_asset_verifications` (the day, who counted, open or closed) and a finding per asset in
`fixed_asset_verification_findings`, beside the place and keeper the register held when the finding was recorded. The API writes a
count's header itself and every finding and the close through the database functions of 592, which hold the rules that must not race:
a finding on a closed count, an asset not held on the day counted, a close while an asset held that day has no finding. A client has at
most one open count (a unique index). A finding moves nothing: an asset found elsewhere is moved by a movement (591), which the person
records, and a closed count is never reopened.

Every read names the firm and the client; the writes go through the API's privileged client, because the signed-in role holds no
write on either table and may call neither function, and the routes ask who is calling first.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException

from core.db_errors import error_code
from core.db_paging import fetch_all, fetch_all_in
from core.db_provider import privileged_for
from core.ist_clock import ist_date_of
from domain.fixed_assets.verification import FINDINGS, held_on, register_on, tally

__all__ = ["FINDINGS"]

NOT_FOUND = "Verification not found"
ASSET_NOT_FOUND = "Asset not found"
MAX_TEXT = 200
MAX_NOTE = 500

# Every select list below is written out where it is read, not held in a constant, so the backend column check reads it against the schema.


def _message(exc: BaseException) -> str:
    """The sentence the database raised, wherever the client put it."""
    said = getattr(exc, "message", None)
    if isinstance(said, str) and said.strip():
        return said.strip()
    first = (getattr(exc, "args", None) or [None])[0]
    if isinstance(first, dict) and isinstance(first.get("message"), str):
        return first["message"].strip()
    return str(exc).strip()


def _refused(exc: BaseException, not_found: str) -> HTTPException:
    """A database refusal in the API's terms: P0002 a 404 in the routes' one sentence, 55000 (a closed count) a 409, 23514 a 422 in
    the function's own words. Anything else is raised as it was."""
    code = error_code(exc)
    if code == "P0002":
        return HTTPException(status_code=404, detail=ASSET_NOT_FOUND if _message(exc) == ASSET_NOT_FOUND else not_found)
    if code == "55000":
        return HTTPException(status_code=409, detail=_message(exc))
    if code == "23514":
        return HTTPException(status_code=422, detail=_message(exc))
    raise exc


def _names(db, firm_id: str, ids: set) -> dict:
    """The name of each member, by internal id; a member who has gone is absent (and read as None)."""
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    return {str(u.get("id")): u.get("full_name") or u.get("email")
            for u in fetch_all_in(lambda: db.table("users").select("id, full_name, email").eq("firm_id", firm_id), "id", ids,
                                  label="fixed_asset_verifications.names")}


def _assets(db, firm_id: str, client_id: str) -> list[dict]:
    """Every asset of the client, deleted ones included (a finding recorded before a deletion still names its asset)."""
    return fetch_all(lambda: db.table("fixed_assets")
                     .select("id, asset_code, asset_name, asset_category, location, custodian, purchase_date, is_disposed, disposal_date, deleted_at")
                     .eq("firm_id", firm_id).eq("client_id", client_id),
                     label="fixed_asset_verifications.assets")


def _movements(db, firm_id: str, client_id: str) -> list[dict]:
    """The client's asset movements (591), for the place and keeper the register held on a count's day."""
    return fetch_all(lambda: db.table("fixed_asset_movements").select("id, asset_id, moved_on, created_at, from_location, from_custodian")
                     .eq("firm_id", firm_id).eq("client_id", client_id), label="fixed_asset_verifications.movements")


def _findings(db, firm_id: str, client_id: str, verification_ids: list[str]) -> list[dict]:
    if not verification_ids:
        return []
    return fetch_all_in(lambda: db.table("fixed_asset_verification_findings")
                        .select("id, verification_id, asset_id, finding, found_in, register_location, register_custodian, note, recorded_by, recorded_at")
                        .eq("firm_id", firm_id).eq("client_id", client_id), "verification_id", verification_ids,
                        label="fixed_asset_verifications.findings")


def _counts(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(lambda: db.table("fixed_asset_verifications")
                     .select("id, client_id, verified_on, counted_by, note, status, closed_at, closed_by, created_by, created_at")
                     .eq("firm_id", firm_id).eq("client_id", client_id), label="fixed_asset_verifications.counts")


def _header(count: dict, findings: list[dict], assets: list[dict], names: dict) -> dict:
    """A count as a screen shows it: its day, who counted, open or closed, and the tally (an open count also says how many assets held
    on the day have no finding yet)."""
    if count.get("status") == "open":
        found_for = {f["asset_id"] for f in findings}
        to_count = sum(1 for a in assets if held_on(a, str(count["verified_on"])[:10]) and a["id"] not in found_for)
    else:
        to_count = None
    return {**count, "verified_on": str(count["verified_on"])[:10],
            "closed_on": _closed_on(count.get("closed_at")),
            "closed_by_name": names.get(str(count.get("closed_by"))), "created_by_name": names.get(str(count.get("created_by"))),
            "tally": tally(findings, to_count)}


def _closed_on(closed_at) -> Optional[str]:
    """The Indian day a count was closed on, or None where it is not closed or the stamp cannot be read (said as not recorded)."""
    day = ist_date_of(closed_at) if closed_at else None
    return day.isoformat() if day else None


def list_counts(db, firm_id: str, client_id: str) -> list[dict]:
    """The client's counts, latest day first (then latest made), each with its tally."""
    counts = _counts(db, firm_id, client_id)
    findings = _findings(db, firm_id, client_id, [c["id"] for c in counts])
    assets = _assets(db, firm_id, client_id) if any(c.get("status") == "open" for c in counts) else []
    names = _names(db, firm_id, {c.get("closed_by") for c in counts} | {c.get("created_by") for c in counts})
    by_count: dict = {}
    for f in findings:
        by_count.setdefault(f["verification_id"], []).append(f)
    counts.sort(key=lambda c: (str(c.get("verified_on") or ""), str(c.get("created_at") or ""), str(c.get("id"))), reverse=True)
    return [_header(c, by_count.get(c["id"], []), assets, names) for c in counts]


def one_count(db, firm_id: str, client_id: str, verification_id: str) -> Optional[dict]:
    rows = (db.table("fixed_asset_verifications")
            .select("id, client_id, verified_on, counted_by, note, status, closed_at, closed_by, created_by, created_at")
            .eq("id", verification_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def paper(db, firm_id: str, client_id: str, count: dict) -> dict:
    """The working paper of one count. An open count lists every asset held on the day counted, with the place and keeper the register
    held that day and its finding or none yet, and any finding of an asset no longer held (deleted, disposed of or its purchase date
    corrected since); a closed count lists its findings alone, which are its record, with what the register held as each recorded."""
    findings = _findings(db, firm_id, client_id, [count["id"]])
    assets = _assets(db, firm_id, client_id)
    moves = _movements(db, firm_id, client_id) if count.get("status") == "open" else []
    by_id = {a["id"]: a for a in assets}
    by_asset = {f["asset_id"]: f for f in findings}
    day = str(count["verified_on"])[:10]
    names = _names(db, firm_id, {f.get("recorded_by") for f in findings} | {count.get("closed_by"), count.get("created_by")})

    def line(asset: Optional[dict], finding: Optional[dict], asset_id: str) -> dict:
        a = asset or {}
        place, keeper = register_on(a, moves, day) if asset else (None, None)
        return {
            "asset_id": asset_id, "asset_code": a.get("asset_code"), "asset_name": a.get("asset_name"),
            "asset_category": a.get("asset_category"),
            # What the register held on the day counted (an open count, read now) and what was stored with the finding.
            "location": place, "custodian": keeper,
            "held_on_the_day": bool(asset) and held_on(asset, day),
            "finding": (finding or {}).get("finding"), "found_in": (finding or {}).get("found_in"),
            "register_location": (finding or {}).get("register_location"),
            "register_custodian": (finding or {}).get("register_custodian"), "note": (finding or {}).get("note"),
            "recorded_by": names.get(str((finding or {}).get("recorded_by"))) if finding else None,
            "recorded_at": (finding or {}).get("recorded_at"),
        }

    if count.get("status") == "open":
        ids = [a["id"] for a in assets if held_on(a, day)]
        ids += [f["asset_id"] for f in findings if f["asset_id"] not in set(ids)]
    else:
        ids = [f["asset_id"] for f in findings]
    lines = [line(by_id.get(i), by_asset.get(i), i) for i in ids]
    lines.sort(key=lambda r: (str(r.get("asset_code") or ""), str(r.get("asset_name") or ""), r["asset_id"]))
    return {"verification": _header(count, findings, assets, names), "lines": lines, "findings": FINDINGS}


def create(db, firm_id: str, client_id: str, *, verified_on: str, counted_by: str, note: Optional[str],
           created_by: Optional[str]) -> dict:
    """Open a count. A client has at most one open count, so one already open is named and nothing is made (409)."""
    open_now = [c for c in _counts(db, firm_id, client_id) if c.get("status") == "open"]
    if open_now:
        raise HTTPException(status_code=409, detail=_one_open(open_now[0]))
    try:
        rows = (privileged_for(db).table("fixed_asset_verifications").insert({
            "firm_id": firm_id, "client_id": client_id, "verified_on": verified_on, "counted_by": counted_by, "note": note,
            "status": "open", "created_by": created_by,
        }).execute().data) or []
    except Exception as exc:  # noqa: BLE001 - the one-open index answers a race in the same words; anything else is raised as it was
        if error_code(exc) == "23505":
            again = [c for c in _counts(db, firm_id, client_id) if c.get("status") == "open"]
            raise HTTPException(status_code=409, detail=_one_open(again[0]) if again else
                                "Another count of this client was opened at the same moment. Read the counts again.") from exc
        raise
    if not rows:
        raise HTTPException(status_code=500, detail="The count was opened but could not be read back. Read the counts again.")
    return rows[0]


def _one_open(count: dict) -> str:
    day = str(count.get("verified_on") or "")[:10]
    shown = date.fromisoformat(day).strftime("%d %b %Y") if day else "an earlier day"
    return (f"The count of {shown} is still open. Close it, or record its findings, before a new count is opened: a client "
            f"has one open count at a time.")


def record_finding(db, firm_id: str, client_id: str, verification_id: str, asset_id: str, *, finding: str,
                   found_in: Optional[str], note: Optional[str], recorded_by: Optional[str]) -> dict:
    """Record (or replace) what the count found of one asset, through the database function, which reads the register's place and
    keeper off the asset and refuses what cannot be a finding in its own words."""
    try:
        res = privileged_for(db).rpc("record_fixed_asset_finding", {
            "p_firm_id": firm_id, "p_client_id": client_id, "p_verification_id": verification_id, "p_asset_id": asset_id,
            "p_finding": finding, "p_found_in": found_in, "p_note": note, "p_recorded_by": recorded_by,
        }).execute()
    except Exception as exc:  # noqa: BLE001 - every database refusal is a sentence, and anything else is raised as it was
        raise _refused(exc, NOT_FOUND) from exc
    row = res.data[0] if isinstance(res.data, list) and res.data else res.data
    if not isinstance(row, dict):
        raise HTTPException(status_code=500, detail="The finding was recorded but could not be read back. Read the count again.")
    return {**row, "recorded_by_name": _names(db, firm_id, {row.get("recorded_by")}).get(str(row.get("recorded_by")))}


def close(db, firm_id: str, client_id: str, verification_id: str, *, closed_by: Optional[str]) -> dict:
    """Close the count once every asset held on the day counted has a finding; a closed count never reopens."""
    try:
        res = privileged_for(db).rpc("close_fixed_asset_verification", {
            "p_firm_id": firm_id, "p_client_id": client_id, "p_verification_id": verification_id, "p_closed_by": closed_by,
        }).execute()
    except Exception as exc:  # noqa: BLE001 - every database refusal is a sentence, and anything else is raised as it was
        raise _refused(exc, NOT_FOUND) from exc
    row = res.data[0] if isinstance(res.data, list) and res.data else res.data
    if not isinstance(row, dict):
        raise HTTPException(status_code=500, detail="The count was closed but could not be read back. Read the counts again.")
    return row
