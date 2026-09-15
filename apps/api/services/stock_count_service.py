"""Fetches what `domain/inventory/count_session.py` decides with, and posts the
answer through the one adjustment path (INV-08).

The split is this file's whole point: the domain module is pure and takes
facts, this one reads them, and POSTING goes through
`domain/inventory_service.apply_stock_adjustment` — the same function the
single-item path calls — once per varying line. There is no second stock write
path, for the same reason there is no second posting kernel.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.inventory import count_session as cs

_logger = logging.getLogger("caflow.stock_count")

#: The columns a line read must carry. Named so a query can be checked against
#: them — a read that omits `reverse_itc` reports every shortage as undecided
#: and refuses a sheet the CA has already finished.
LINE_COLUMNS = (
    "id, session_id, service_catalogue_id, system_qty_units, counted_qty_units, "
    "reverse_itc, itc_reversal_is_interstate, notes"
)
SESSION_COLUMNS = (
    "id, firm_id, client_id, count_date, reference_no, status, notes, "
    "created_at, created_by, posted_at, posted_by"
)

#: How many lines go in one INSERT when a sheet is opened. Not a read cap —
#: `core.db_paging.PAGE` is that — and deliberately smaller, because the limit
#: here is request BODY size rather than PostgREST's row ceiling.
_INSERT_CHUNK = 500


def _qty(value) -> Decimal:
    """A quantity as Decimal, via its STRING.

    `Decimal(float(x))` is the bug this spells out of existence: 10.1 in binary
    floating point is 10.0999999999999996447…, so a count of 10.1 against books
    of 10.1 comes out as a variance of -3.55e-15 rather than zero and the sheet
    posts an adjustment of nothing. `NUMERIC(10,3)` is what the ledger keeps
    and `Decimal(str(...))` is what preserves it.
    """
    try:
        return Decimal(str(value or 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def open_session(db, *, firm_id: str, client_id: str, count_date: Optional[str],
                 reference_no: Optional[str], notes: Optional[str],
                 created_by: Optional[str]) -> dict:
    """A new sheet, with one line per stock item and the books' figure on it.

    THE SNAPSHOT IS AS AT THE COUNT DATE, not as at today. A sheet opened on
    3 April for a 31 March count must show what the books said on 31 March —
    showing today's figure would give the CA a variance against a position the
    count was never taken against.
    """
    date = (count_date or ist_today().isoformat())[:10]
    reference = (reference_no or f"PC-{date}").strip()

    from services import stock_position_service
    position = stock_position_service.position(db, firm_id, client_id, date)

    row = (db.table("stock_count_sessions").insert({
        "firm_id": firm_id, "client_id": client_id, "count_date": date,
        "reference_no": reference, "status": cs.STATUS_OPEN,
        "notes": notes, "created_by": created_by,
    }).execute().data or [{}])[0]
    session_id = row.get("id")
    if not session_id:
        raise HTTPException(status_code=500, detail="Could not open the count sheet.")

    items = position.get("items") or []
    # CHUNKED. A client with a few thousand SKUs would otherwise be one request
    # body large enough to be refused, and unlike a short READ that failure is
    # loud — so this is about not sending it, not about noticing.
    for start in range(0, len(items), _INSERT_CHUNK):
        db.table("stock_count_lines").insert([{
            "firm_id": firm_id, "client_id": client_id, "session_id": session_id,
            "service_catalogue_id": i.get("service_catalogue_id") or i.get("id"),
            "system_qty_units": str(_qty(i.get("qty_units"))),
        } for i in items[start:start + _INSERT_CHUNK]]).execute()
    return row


def _session(db, firm_id: str, session_id: str) -> dict:
    rows = (db.table("stock_count_sessions").select(
                "id, firm_id, client_id, count_date, reference_no, status, notes, "
                "created_at, created_by, posted_at, posted_by")
            .eq("id", session_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Count sheet not found.")
    return rows[0]


def _item_names(db, firm_id: str, client_id: str) -> dict[str, dict]:
    """Paged for the same reason the lines are: one row per stock item, and a
    truncated read would leave the sheet's later lines labelled with their raw
    uuid — which looks like a data problem rather than a short read."""
    rows = fetch_all(
        lambda: db.table("service_catalogue").select("id, name, unit")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good"),
        key="id", label="service_catalogue")
    return {r["id"]: r for r in rows}


def read_plan(db, *, firm_id: str, session_id: str) -> tuple[dict, cs.CountPlan]:
    """The sheet and what it will post, with the variance recomputed against
    the position AS AT THE COUNT DATE — see the domain module's header for why
    that is not the snapshot on the line."""
    session = _session(db, firm_id, session_id)
    client_id = session["client_id"]

    # PAGED. One line per stock ITEM is exactly the shape PostgREST silently
    # truncates at ~1000 rows, and a count sheet two hundred items short reads
    # exactly like a complete one — every variance on the missing items simply
    # never appears, so the CA posts a count that is not the count they took.
    # `core.db_paging.fetch_all` is the one helper (CLAUDE.md); `id` is in the
    # projection because it is the cursor.
    #
    # Spelled out for the column guard, which reads a literal only. A test
    # holds this and LINE_COLUMNS identical.
    line_rows = fetch_all(
        lambda: db.table("stock_count_lines").select(
            "id, session_id, service_catalogue_id, system_qty_units, "
            "counted_qty_units, reverse_itc, itc_reversal_is_interstate, notes")
        .eq("session_id", session_id).eq("firm_id", firm_id),
        key="id", label="stock_count_lines")

    from services import stock_position_service
    position = stock_position_service.position(db, firm_id, client_id, session["count_date"])
    current = {(i.get("service_catalogue_id") or i.get("id")): _qty(i.get("qty_units"))
               for i in (position.get("items") or [])}
    names = _item_names(db, firm_id, client_id)

    lines = []
    for r in line_rows:
        item_id = r["service_catalogue_id"]
        item = names.get(item_id) or {}
        counted = r.get("counted_qty_units")
        lines.append(cs.CountLine(
            service_catalogue_id=item_id,
            item_name=item.get("name") or item_id,
            unit=item.get("unit"),
            system_qty_units=_qty(r.get("system_qty_units")),
            current_qty_units=current.get(item_id, Decimal(0)),
            counted_qty_units=None if counted is None else _qty(counted),
            reverse_itc=(None if r.get("reverse_itc") is None else bool(r["reverse_itc"])),
            itc_reversal_is_interstate=bool(r.get("itc_reversal_is_interstate")),
            notes=r.get("notes") or "",
            line_id=str(r.get("id") or ""),
        ))
    lines.sort(key=lambda l: (l.item_name.lower(), l.service_catalogue_id))
    return session, cs.plan(count_date=session["count_date"],
                            reference_no=session["reference_no"], lines=lines)


def save_counts(db, *, firm_id: str, session_id: str, entries: list[dict]) -> int:
    """Write the counted quantities and the s.17(5)(h) decisions back.

    Refused once the session has posted: the adjustments are in the ledger and
    editing the sheet under them would leave a worksheet that no longer
    explains the journals it produced.
    """
    session = _session(db, firm_id, session_id)
    if session["status"] != cs.STATUS_OPEN:
        raise HTTPException(
            status_code=409,
            detail=f"This count sheet is {session['status']} and can no longer be edited.")
    # THE EXISTING LINES ARE READ ONCE and each entry MERGED onto its row, so
    # a caller sending only the counted quantity does not clear the CGST Act
    # s.17(5)(h) decision the CA made earlier. A hundred-line sheet is one
    # read, not a hundred.
    #
    # The update is then written as a LITERAL dict with all four keys, which
    # the column guard (tests/test_backend_columns_exist_pg.py) can read; a
    # `patch` variable built key by key is invisible to it.
    existing = {r["service_catalogue_id"]: r for r in fetch_all(
        lambda: db.table("stock_count_lines").select(
            "id, service_catalogue_id, counted_qty_units, reverse_itc, "
            "itc_reversal_is_interstate, notes")
        .eq("session_id", session_id).eq("firm_id", firm_id),
        key="id", label="stock_count_lines")}

    written = 0
    for e in entries:
        item_id = e.get("service_catalogue_id")
        prior = existing.get(item_id)
        if prior is None:
            # A line the sheet does not have. The update below would match no
            # row anyway — this only saves the round trip, and says so rather
            # than reading as a guard that is doing work.
            continue
        counted = (prior.get("counted_qty_units") if "counted_qty_units" not in e
                   else (None if e["counted_qty_units"] is None
                         else str(_qty(e["counted_qty_units"]))))
        reverse = (prior.get("reverse_itc") if "reverse_itc" not in e
                   else (None if e["reverse_itc"] is None else bool(e["reverse_itc"])))
        interstate = (bool(prior.get("itc_reversal_is_interstate"))
                      if "itc_reversal_is_interstate" not in e
                      else bool(e["itc_reversal_is_interstate"]))
        notes = prior.get("notes") if "notes" not in e else e["notes"]
        res = (db.table("stock_count_lines").update({
                   "counted_qty_units": counted,
                   "reverse_itc": reverse,
                   "itc_reversal_is_interstate": interstate,
                   "notes": notes,
               })
               .eq("session_id", session_id).eq("firm_id", firm_id)
               .eq("service_catalogue_id", item_id).execute())
        written += len(getattr(res, "data", None) or [])
    return written


def post_session(db, *, firm_id: str, session_id: str, actor_id: Optional[str]) -> dict:
    """Post every line that varies, under the session's own reference.

    ONE WRITE PATH: `apply_stock_adjustment`, once per varying line, exactly as
    the single-item screen calls it. The batch is not atomic and cannot be —
    each adjustment is its own journal through the posting kernel — so the
    session is marked posted only after the loop, and a line that failed is
    NAMED rather than swallowed. Re-posting is refused, which is what stops a
    half-posted sheet from doubling the lines that succeeded.

    BOTH PERIOD QUESTIONS ARE ASKED, unlike the single-item path — see the
    comment at the check. `routers/inventory.py:adjust_stock` asks only the
    firm's FY switch and is on the acknowledged debt list in
    tests/test_every_dated_posting_path_asserts_the_client_lock.py; this path
    is new, so it is built with both rather than added to that list.
    """
    session = _session(db, firm_id, session_id)
    if session["status"] != cs.STATUS_OPEN:
        raise HTTPException(
            status_code=409,
            detail=f"This count sheet is already {session['status']}.")

    _, plan = read_plan(db, firm_id=firm_id, session_id=session_id)
    if plan.gaps:
        raise HTTPException(status_code=422, detail=" ".join(plan.gaps))

    # BOTH QUESTIONS, and the second one is the point. `validate_posting_date`
    # is the FIRM's own financial-year switch — it takes no client_id and
    # therefore cannot know that this client's GSTR-3B for the count month has
    # already gone to the portal. `assert_open` is the client-scoped rule, and
    # a count sheet needs it because a SHORTAGE is a document that feeds a
    # return: `apply_stock_adjustment` registers the CGST Act s.17(5)(h)
    # reversal on GSTR-3B Table 4(B)(1) (INV-06). Posting a March shortage
    # after March's 3B is filed changes what that return should have said, and
    # the return cannot be recalled.
    #
    # Unconditional rather than gated on whether any line carries
    # `reverse_itc` — the same reasoning CLAUDE.md records for a fixed asset's
    # acquisition: a rule that depends on the order two fields are filled in is
    # not a rule, and the sheet is posted as one document whatever its lines
    # decided.
    from services.period_validation_service import period_validation_service
    from services import period_lock_service
    period_validation_service.validate_posting_date(firm_id or "", session["count_date"])
    period_lock_service.assert_open(db, firm_id, session["client_id"],
                                    session["count_date"])

    from domain.inventory_service import apply_stock_adjustment, resolve_costing_policy
    # ONE read of the client's cost formula for the whole sheet — a
    # hundred-line count would otherwise be a hundred `clients` round trips.
    policy = resolve_costing_policy(db, session["client_id"])
    posted, failed = [], []
    for p in plan.postable:
        try:
            movement = apply_stock_adjustment(
                db, firm_id=firm_id, client_id=session["client_id"],
                service_catalogue_id=p.line.service_catalogue_id,
                movement_date=session["count_date"],
                quantity=float(p.quantity), direction=p.direction,
                reverse_itc=bool(p.line.reverse_itc) if p.direction == cs.DECREASE else False,
                # THE SESSION'S OWN REFERENCE on every line, which is what
                # makes the hundred journals one count.
                reference_no=session["reference_no"],
                itc_reversal_is_interstate=p.line.itc_reversal_is_interstate,
                created_by=actor_id,
                policy=policy,
            )
            if movement is None:
                failed.append({"item": p.line.item_name,
                               "why": "the stock item could not be read"})
            else:
                posted.append({"item": p.line.item_name,
                               "quantity": str(p.quantity), "direction": p.direction})
        except Exception as e:  # noqa: BLE001 — one bad line must not hide the rest
            _logger.exception("count session %s: %s failed", session_id,
                              p.line.service_catalogue_id)
            failed.append({"item": p.line.item_name, "why": str(e)[:200]})

    db.table("stock_count_sessions").update({
        "status": cs.STATUS_POSTED,
        "posted_at": _now(),
        "posted_by": actor_id,
    }).eq("id", session_id).eq("firm_id", firm_id).execute()

    return {
        "session_id": session_id,
        "reference_no": session["reference_no"],
        "count_date": session["count_date"],
        "posted": posted,
        "posted_count": len(posted),
        # NAMED, never swallowed. A line that could not post leaves the books
        # disagreeing with the count, and the session is closed either way —
        # so the CA has to be told which ones to chase.
        "failed": failed,
        "failed_count": len(failed),
        "not_posted_count": len(plan.lines) - len(plan.postable),
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
