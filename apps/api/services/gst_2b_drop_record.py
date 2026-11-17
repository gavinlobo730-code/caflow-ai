"""What a bulk GSTR-2B drop did to each file, kept so it can be read back after the screen is closed (POST-A-057, migration 715).

WHY
    The firm-level GST page sends a drop of GSTR-2B files one per request, and the answer for each file (reconciled, matched no client,
    refused and why, what it replaced) lived only in the browser that sent it. Close the tab and nothing said what the drop did, while
    a refused or unmatched file left no trace at all (`gstr2b_uploads` keeps a reconciled file and nothing else).

WHAT IS KEPT
    `gstr2b_bulk_drops`: one row per drop, the firm and the member (`users.id`) who made it. The first request of a drop creates it and
    answers its id; every later request of the same drop names it, and a drop that is not this member's, in this firm, is refused in
    words before any file is touched. `gstr2b_bulk_drop_files`: one row per file the SERVER answered, carrying the answer's own fields.
    A client's NAME is not stored: it is read when the drop is read back, so a renamed client reads as it is called now. A file the
    browser could not read never reached the server and is not here, and the read-back says so.

WHO READS IT BACK
    The member who made the drop, and only the rows for clients that member may see NOW: assignment can change after a drop, and a row
    routed to a client the reader can no longer see is shown with its status and nothing about the client or what the reconciliation
    found. Both tables are written and read with the API's privileged client, always naming the firm; nothing signed in reaches them.

THE CODE DEPLOYS BEFORE ITS MIGRATION
    Until 715 is applied there is no table. Only "the table is not there" (`core.db_errors.is_missing_store`) is read as "not recorded":
    the drop is reconciled exactly as before and the answer says it was not recorded. Recording never fails a reconciliation that has
    already been written; a failure to record is said on the answer and reported.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Sequence

from core import db_errors
from core.db_paging import fetch_all
from core.observability import capture_soft_failure

_logger = logging.getLogger("caflow.gst_2b_drop_record")

#: How many of a member's drops the read-back returns, newest first.
READ_BACK_DROPS = 10

#: The answer's fields a file row keeps, as the answer carried them.
_KEPT = ("name", "status", "reason", "gstin", "period", "client_id", "needs_attention", "summary", "problems",
         "registration_caveat", "replaced_earlier")

NOT_RECORDED = ("What this drop did was not recorded, so it cannot be read back after this page is closed. The files above "
                "were reconciled exactly as listed.")
DROP_NOT_FOUND = ("The drop this file was sent as part of is not one of yours. Nothing was reconciled. Drop the files again to "
                  "start a new one.")
NOT_SEEN_NOW = ("This file was routed to a client you cannot see now, so the client and what the reconciliation found are not "
                "shown.")
BROWSER_ONLY = ("A file the browser could not read, or that was not started because the drop was stopped, never reached the "
                "server and is not listed here.")


class DropRefused(Exception):
    """A drop id that does not belong to this member in this firm. The message is the sentence for a person."""


def open_drop(db, *, firm_id: str, member_id: Optional[str], drop_id: Optional[str]) -> Optional[str]:
    """The drop this request belongs to: a new one when `drop_id` is None, else the named one if it is this member's.

    Returns None when the drop cannot be recorded (the table is not there yet, or the write failed): the request is then reconciled
    unrecorded. Raises `DropRefused` for a named drop that is not this member's in this firm, so a file is never added to somebody
    else's drop."""
    if not member_id:
        return None
    try:
        if drop_id:
            rows = (db.table("gstr2b_bulk_drops").select("id")
                    .eq("firm_id", firm_id).eq("id", drop_id).eq("created_by", member_id)
                    .limit(1).execute().data) or []
            if not rows:
                raise DropRefused(DROP_NOT_FOUND)
            return str(rows[0]["id"])
        made = (db.table("gstr2b_bulk_drops")
                .insert({"firm_id": firm_id, "created_by": member_id}).execute().data) or []
        return str(made[0]["id"]) if made else None
    except DropRefused:
        raise
    except Exception as exc:                                    # noqa: BLE001
        if db_errors.is_missing_store(exc):
            _logger.error("a bulk GSTR-2B drop is NOT recorded: this database has no gstr2b_bulk_drops (migration 715 has not been "
                          "applied). %s", exc)
        else:
            capture_soft_failure(exc, operation="gst2b.drop.open", firm_id=firm_id)
        return None


def _row(firm_id: str, drop_id: str, result: dict) -> dict:
    row = {k: result.get(k) for k in _KEPT}
    row["firm_id"] = firm_id
    row["drop_id"] = drop_id
    row["name"] = str(row.get("name") or "")[:300]
    row["gstin"] = str(row.get("gstin") or "")
    row["needs_attention"] = bool(row.get("needs_attention"))
    row["problems"] = list(row.get("problems") or [])
    return row


def record(db, *, firm_id: str, drop_id: Optional[str], results: Sequence[dict]) -> bool:
    """Keep what the drop did to these files. True when written; never raises (the reconciliations are already written)."""
    if not drop_id:
        return False
    if not results:
        return True
    try:
        written = (db.table("gstr2b_bulk_drop_files")
                   .insert([_row(firm_id, drop_id, r) for r in results]).execute().data) or []
        return len(written) == len(results)
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="gst2b.drop.record", firm_id=firm_id, drop_id=drop_id)
        return False


def _client_names(db, firm_id: str, ids: Sequence[str]) -> dict[str, str]:
    ids = sorted({str(i) for i in ids if i})
    names: dict[str, str] = {}
    for i in range(0, len(ids), 200):
        rows = (db.table("clients").select("id, client_name, legal_name")
                .eq("firm_id", firm_id).in_("id", ids[i:i + 200]).execute().data) or []
        names.update({str(r["id"]): (r.get("legal_name") or r.get("client_name") or "") for r in rows})
    return names


def _shown(row: dict, *, may_see: Callable[[str], bool], names: dict[str, str]) -> dict:
    out = {k: row.get(k) for k in _KEPT}
    out["problems"] = list(out.get("problems") or [])
    out["client_name"] = None
    out["client_hidden"] = False
    cid = out.get("client_id")
    if cid:
        if may_see(str(cid)):
            out["client_name"] = names.get(str(cid)) or None
        else:
            out.update(client_id=None, summary=None, problems=[], registration_caveat=None, replaced_earlier=None,
                       needs_attention=False, client_hidden=True, reason=NOT_SEEN_NOW)
    return out


def read_back(db, *, firm_id: str, member_id: Optional[str], may_see: Callable[[str], bool]) -> dict:
    """The member's latest drops, newest first, each with what it did to each file, in the order the server answered them.

    Raises what the read raised, except a missing table, which answers `recorded: False` with the sentence: an unread record is not a
    record of no drops."""
    empty = {"drops": [], "limited_to": READ_BACK_DROPS, "more": False, "browser_only": BROWSER_ONLY}
    if not member_id:
        return {**empty, "recorded": True}
    try:
        drops = (db.table("gstr2b_bulk_drops").select("id, created_at")
                 .eq("firm_id", firm_id).eq("created_by", member_id)
                 .order("created_at", desc=True).order("id", desc=True)
                 .limit(READ_BACK_DROPS + 1).execute().data) or []
    except Exception as exc:                                    # noqa: BLE001
        if not db_errors.is_missing_store(exc):
            raise
        _logger.error("the bulk GSTR-2B drops are NOT read: this database has no gstr2b_bulk_drops (migration 715). %s", exc)
        return {**empty, "recorded": False,
                "not_recorded": "Drops are not recorded on this deployment yet, so none can be read back."}
    seen: dict[str, bool] = {}

    def visible(cid: str) -> bool:
        """One access check per client, not one per row."""
        if cid not in seen:
            seen[cid] = bool(may_see(cid))
        return seen[cid]

    more = len(drops) > READ_BACK_DROPS
    drops = drops[:READ_BACK_DROPS]
    ids = [str(d["id"]) for d in drops]
    rows: list[dict] = []
    if ids:
        def page():
            return (db.table("gstr2b_bulk_drop_files")
                    .select("id, drop_id, seq, name, status, reason, gstin, period, client_id, needs_attention, "
                            "summary, problems, registration_caveat, replaced_earlier")
                    .eq("firm_id", firm_id).in_("drop_id", ids)
                    .order("seq").order("id"))
        rows = fetch_all(page, label="gst2b.drop_files")
    seen_ids = [str(r["client_id"]) for r in rows if r.get("client_id") and visible(str(r["client_id"]))]
    names = _client_names(db, firm_id, seen_ids)
    by_drop: dict[str, list[dict]] = {i: [] for i in ids}
    for r in rows:
        by_drop.setdefault(str(r["drop_id"]), []).append(_shown(r, may_see=visible, names=names))
    out = []
    for d in drops:
        results = by_drop.get(str(d["id"]), [])
        totals: dict[str, int] = {}
        for r in results:
            totals[str(r["status"])] = totals.get(str(r["status"]), 0) + 1
        out.append({"id": str(d["id"]), "created_at": d.get("created_at"), "file_count": len(results),
                    "totals": totals, "needs_attention": sum(1 for r in results if r["needs_attention"]),
                    "results": results})
    return {**empty, "drops": out, "more": more, "recorded": True}
