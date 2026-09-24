"""Which clients need work on one hub tile — the fetch, and the client names.

`domain/hub/worklist.py` is the authority for WHICH tiles have a firm-level
worklist and what a row means; `public.hub_client_worklist` (migration 416) is
the only place that knows which table answers it. This module is the fetch, the
scope resolution and the join to a client's name.

── TWO PATHS, ONE RULE ──────────────────────────────────────────────────────

The SQL function is what production runs, for the reason CLAUDE.md's reporting
rule gives: the answer is one row per CLIENT and the population behind it is
one row per statement line, per bill, per asset, per engagement, for years.
`_python_twin` is the identical rule for mock mode and local dev, where there
is no `DATABASE_URL` and no SQL functions at all, and
`tests/test_hub_client_worklist_parity_pg.py` holds the two identical.

⚠️ THE FALLBACK IS LEDGER-PROPORTIONAL AND SAYS SO. It pages the outstanding
rows and tallies them here, which is exactly what the rule forbids in
production. It logs loudly when it is reached — the same posture
`stock_position_service` takes, and the reason its parity test exists.

── SCOPE IS RESOLVED ONCE, AT THE TOP ───────────────────────────────────────

`core.authz.effective_client_ids` answers None for a Partner (no restriction)
and a SET for everyone else, and an EMPTY set means NOTHING, never "no filter".
That distinction is the one `routers/accounting.py` records and the one that
turns a scoping bug into a cross-client read if it is collapsed, so it is
resolved here once and passed down rather than re-derived.

── THE NAMES ARE A SECOND, BOUNDED READ ─────────────────────────────────────

The function answers client ids and figures. A worklist showing uuids is
useless, so the names are fetched with `.in_` over exactly the ids that came
back — bounded by the ANSWER, not by the firm's client list. A client whose
name cannot be read is still listed, with its id, rather than dropped: a queue
that silently omits a client is the failure this whole screen exists to
prevent.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.authz import effective_client_ids
from core.supabase_client import get_service_supabase
from domain.banking import entry as bank_entry
from domain.hub import worklist as worklist_rules
from domain.hub.tiles import Unit

logger = logging.getLogger("caflow.hub.worklist")

#: What each tile's outstanding population is, for the Python twin ONLY. The
#: SQL function transcribes the same predicates and
#: `tests/test_the_firm_hub_tiles_land_somewhere.py` holds all three —
#: `hub_service._signals`, this, and migration 416 — to one vocabulary.
_POPULATION: dict[str, dict] = {
    "banking": {
        "table": "bank_transactions",
        "column": None,                       # a COUNT
        "in_": ("entry_state", list(bank_entry.OPEN_STATES)),
    },
    "purchases": {
        "table": "purchase_bills",
        "column": "outstanding_paise",        # a SUM of what is > 0
        "gt": ("outstanding_paise", 0),
    },
    "fixed_assets": {
        "table": "fixed_assets",
        "column": None,
        "is_null": "depreciation_posted_through",
    },
    "year_end": {
        "table": "year_end_engagements",
        "column": None,
        # The COMPLEMENT of the finished states, `_outstanding()`'s own rule:
        # a value added to the CHECK is almost always a new intermediate state
        # and should join the queue rather than be dropped.
        "in_": ("status", ["draft", "in_review", "approved"]),
    },
}


def _db():
    return get_service_supabase()


def worklist(current_user: dict, tile_id: str) -> dict:
    """Every client with outstanding work on this tile, worst first.

    A tile with no firm-level worklist is a 422 naming the reason, never an
    empty list — `domain/gst/gstr3b_computer`'s rule about a nil applies to a
    queue too: a nil meaning *nothing to do* and a nil meaning *nobody can
    tell* are different facts.
    """
    firm_id = current_user.get("firm_id")
    if not firm_id:
        raise HTTPException(status_code=400, detail="hub worklist: the caller has no firm")

    rules = worklist_rules.worklist_for(tile_id)
    if rules is None:
        why = worklist_rules.NO_WORKLIST_BECAUSE.get(tile_id)
        raise HTTPException(
            status_code=422,
            detail=why or f"{tile_id} has no firm-level worklist",
        )

    eff = effective_client_ids(current_user)
    scope: Optional[list[str]] = None if eff is None else sorted(eff)
    if scope is not None and not scope:
        # Assigned to nothing. NOT "no filter" — see the module docstring.
        return _shape(rules, [], clients_examined=0)

    rows = _rows(firm_id, tile_id, scope)
    named = _with_names(firm_id, rows)
    named.sort(key=lambda r: (-int(r["signal"]), r["client_name"] or ""))
    return _shape(rules, named, clients_examined=_client_count(firm_id, scope))


def _shape(rules, rows: list[dict], clients_examined: int) -> dict:
    """The payload. `question` and `unit` come off the TILE, never restated."""
    return {
        "tile": rules.tile_id,
        "label": rules.label,
        "question": rules.question,
        "unit": rules.unit.value,
        "column": rules.column,
        "opens_section": rules.opens_section,
        "rows": rows,
        # So an empty queue reads as "nothing outstanding" rather than as a
        # failed fetch — the three-state discipline the hub itself applies.
        "clients_examined": clients_examined,
    }


def _rows(firm_id: str, tile_id: str, scope: Optional[list[str]]) -> list[dict]:
    db = _db()
    if db is not None and hasattr(db, "rpc"):
        try:
            res = db.rpc("hub_client_worklist", {
                "p_firm": firm_id, "p_tile": tile_id, "p_client_ids": scope,
            }).execute()
            data = getattr(res, "data", None)
            if isinstance(data, list):
                return [{"client_id": str(r["client_id"]), "signal": int(r["signal"] or 0)}
                        for r in data if r.get("client_id")]
            raise ValueError(
                f"hub_client_worklist returned {type(data).__name__}, not a list")
        except Exception as e:                                  # noqa: BLE001
            logger.error("hub_client_worklist failed (%s %s) — falling back to "
                         "the Python rule, which reads every outstanding row: %s",
                         firm_id, tile_id, e)
    return _python_twin(db, firm_id, tile_id, scope)


def _python_twin(db, firm_id: str, tile_id: str,
                 scope: Optional[list[str]]) -> list[dict]:
    """The same answer, computed here. Mock mode and local dev only.

    Reads every OUTSTANDING row and tallies by client, which is proportional to
    the ledger rather than to the answer — see the module docstring. Paged
    through `core.db_paging.fetch_all` like every other read in this codebase,
    because an un-paged PostgREST read caps silently at ~1000 rows and a
    truncated queue is a queue that has quietly dropped a client.
    """
    if db is None:
        return []
    from core.db_paging import fetch_all

    spec = _POPULATION[tile_id]
    col = spec["column"]

    def one_page():
        # ⚠️ THE TABLE AND THE PROJECTION ARE WRITTEN OUT PER TILE RATHER THAN
        # TAKEN FROM `_POPULATION`, and the four near-identical lines are the
        # price of something real: `tests/test_backend_columns_exist_pg.py`
        # parses every `.select()` in `apps/api` as a STRING, so a projection
        # reached through a name — `spec["table"]`, an f-string — is invisible
        # to it and counts against the "unreadable" budget instead. Of all the
        # reads to leave unchecked, four feeding a queue a CA works from is a
        # poor choice, and the budget's own message invites a raise where the
        # coverage is recoverable. It is recoverable, so this is the fix.
        # `domain/tally/party_identifiers`'s note records the same trade.
        #
        # `id` is the keyset cursor, so it has to be in every projection.
        if tile_id == "banking":
            q = db.table("bank_transactions").select("id,client_id,entry_state")
        elif tile_id == "purchases":
            q = db.table("purchase_bills").select("id,client_id,outstanding_paise")
        elif tile_id == "fixed_assets":
            q = db.table("fixed_assets").select("id,client_id,depreciation_posted_through")
        else:
            q = db.table("year_end_engagements").select("id,client_id,status")

        # The PREDICATES still come from `_POPULATION`, which is what the
        # parity guard holds against migration 416 — only the projection is
        # spelled out, because only the projection is what that scan reads.
        q = q.eq("firm_id", firm_id)
        if scope is not None:
            q = q.in_("client_id", scope)
        if spec.get("in_"):
            q = q.in_(spec["in_"][0], spec["in_"][1])
        if spec.get("gt"):
            q = q.gt(spec["gt"][0], spec["gt"][1])
        if spec.get("is_null"):
            q = q.is_(spec["is_null"], "null")
        return q

    tally: dict[str, int] = {}
    for r in fetch_all(one_page, label=f"hub-worklist:{tile_id}"):
        cid = r.get("client_id")
        if not cid:
            continue
        tally[str(cid)] = tally.get(str(cid), 0) + (int(r.get(col) or 0) if col else 1)
    return [{"client_id": k, "signal": v} for k, v in tally.items()]


def _with_names(firm_id: str, rows: list[dict]) -> list[dict]:
    """Bounded by the ANSWER: `.in_` over exactly the ids that came back."""
    if not rows:
        return []
    db = _db()
    names: dict[str, dict] = {}
    if db is not None:
        try:
            got = (db.table("clients")
                     .select("id,client_name,legal_name,entity_type")
                     .eq("firm_id", firm_id)
                     .in_("id", [r["client_id"] for r in rows])
                     .execute().data) or []
            names = {str(c["id"]): c for c in got}
        except Exception:                                       # noqa: BLE001
            logger.exception("hub worklist: client names could not be read")

    out = []
    for r in rows:
        c = names.get(r["client_id"]) or {}
        out.append({
            **r,
            # `legal_name` first, the preference `_client_party` applies to the
            # documents these clients' own books produce.
            "client_name": c.get("legal_name") or c.get("client_name") or None,
            "entity_type": c.get("entity_type"),
        })
    return out


def _client_count(firm_id: str, scope: Optional[list[str]]) -> int:
    """How many clients this answer was computed over. A COUNT, never rows."""
    db = _db()
    if db is None:
        return 0
    try:
        q = db.table("clients").select("id", count="exact").eq("firm_id", firm_id)
        if scope is not None:
            q = q.in_("id", scope)
        return int(q.limit(1).execute().count or 0)
    except Exception:                                           # noqa: BLE001
        logger.exception("hub worklist: the client count could not be read")
        return 0


__all__ = ["worklist", "Unit"]
