"""The three challan functions of migration 585, as an in-memory double the mock suite shares (ledger POST-A-419).

`create_delivery_challan_atomic`, `record_challan_lot_atomic` and `correct_draft_challan_lines_atomic` are database functions, and the mock suite has no database, so the doubles that stand in for one
need these. They mirror the functions' rules, and the refusals carry the words the real functions raise (`challan_not_issued`, `lot_exceeds_line`, ...), which
`services/delivery_challan_writes` reads. Two things keep a double from drifting from what it mirrors: `tests/test_585_..._pg.py` runs the real functions on Postgres, and
`tests/test_the_challan_double_and_the_challan_functions_agree_pg.py` runs the same scenarios through both and compares what they leave. Atomicity is real here: each call snapshots the two or
three tables it writes and puts them back when it refuses, as the function's transaction does.

A double adapts this module by giving it the dict of its rows (`tables`, table name to a list of dicts) and a function that makes a new id for a table.
"""
from __future__ import annotations

import copy
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from core.ist_clock import ist_now
from tests.production_types import assert_write_fits_production_types

_TABLES = ("delivery_challans", "delivery_challan_lines", "delivery_challan_returns")


class Refusal(Exception):
    """A refusal as PostgREST words it: the dict the client's error prints, carrying the function's own word."""

    def __init__(self, word: str, sqlstate: str = "P0001", detail: str = ""):
        super().__init__(str({"message": word, "code": sqlstate, "details": detail, "hint": None}))


def _rows(tables: dict, name: str) -> list:
    return tables.setdefault(name, [])


def _atomic(tables: dict, body: Callable):
    snapshot = {name: copy.deepcopy(_rows(tables, name)) for name in _TABLES}
    try:
        return body()
    except BaseException:
        for name, rows in snapshot.items():
            tables[name] = rows
        raise


def _same(a, b) -> bool:
    return str(a) == str(b)


def _as_the_column_stores(value):
    """A quantity as `numeric(10,3)` keeps it: a value with a fourth decimal is rounded half up (1.0005 is stored as 1.001); one that fits is left as it was given."""
    if value is None:
        return None
    exact = Decimal(str(value))
    rounded = exact.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return value if exact == rounded else str(rounded)


def create(tables: dict, new_id: Callable[[str], str], header: dict, lines: list) -> dict:
    if not isinstance(header, dict):
        raise Refusal("create_delivery_challan_atomic: the header must be a JSON object", "22023")
    if not isinstance(lines, list):
        raise Refusal("create_delivery_challan_atomic: the lines must be a JSON array", "22023")
    if "firm_id" not in header or "client_id" not in header:
        raise Refusal("create_delivery_challan_atomic: the header names no firm or no client", "22023")
    if any(k in header for k in ("id", "issued_at", "received_back_on")):
        raise Refusal("create_delivery_challan_atomic: a challan is made as a draft, with no id of its own choosing, no moment of issue and no day it came back", "22023")
    status = header.get("status")
    if (status if status is not None else "draft") != "draft":        # `coalesce(p_header ->> 'status', 'draft') <> 'draft'`: a status that is the empty text is not a draft
        raise Refusal("challan_not_a_draft")

    def body():
        assert_write_fits_production_types("delivery_challans", [header])
        row = {**header, "id": new_id("delivery_challans")}
        row.setdefault("status", "draft")
        _rows(tables, "delivery_challans").append(row)
        for line in lines:
            if not isinstance(line, dict):
                raise Refusal("create_delivery_challan_atomic: every line must be a JSON object", "22023")
            own = {k: v for k, v in line.items() if k not in ("challan_id", "firm_id", "client_id")}
            if "quantity" in own:
                own["quantity"] = _as_the_column_stores(own["quantity"])
            if "description" in own and own["description"] is None:
                raise Refusal('null value in column "description" of relation "delivery_challan_lines" violates not-null constraint', "23502")
            written = {**own, "challan_id": row["id"], "firm_id": header["firm_id"], "client_id": header["client_id"]}
            assert_write_fits_production_types("delivery_challan_lines", [written])
            _rows(tables, "delivery_challan_lines").append({"id": new_id("delivery_challan_lines"), **written})
        return dict(row)

    return _atomic(tables, body)


def record_lot(tables: dict, new_id: Callable[[str], str], firm_id, client_id, challan_id, lot: dict) -> dict:
    if not isinstance(lot, dict):
        raise Refusal("record_challan_lot_atomic: the lot must be a JSON object", "22023")

    def body():
        challan = next((c for c in _rows(tables, "delivery_challans")
                        if _same(c.get("id"), challan_id) and _same(c.get("firm_id"), firm_id) and _same(c.get("client_id"), client_id)), None)
        if challan is None:
            raise Refusal("challan_not_found", "P0002")
        if challan.get("status") != "issued":
            raise Refusal("challan_not_issued", detail=f"status is {challan.get('status')}")
        if challan.get("reason") != "job_work":
            raise Refusal("challan_not_job_work", detail=f"reason is {challan.get('reason')}")
        line = next((ln for ln in _rows(tables, "delivery_challan_lines")
                     if "challan_line_id" in lot and _same(ln.get("id"), lot["challan_line_id"]) and _same(ln.get("challan_id"), challan_id)
                     and _same(ln.get("firm_id"), firm_id) and _same(ln.get("client_id"), client_id)), None)
        if line is None:
            raise Refusal("line_not_found", "P0002")
        mine = [r for r in _rows(tables, "delivery_challan_returns") if _same(r.get("challan_line_id"), line["id"])]
        back = sum((Decimal(str(r.get("quantity_returned") or 0)) for r in mine), Decimal(0))
        lost = sum((Decimal(str(r.get("quantity_lost_or_wasted") or 0)) for r in mine), Decimal(0))

        def stored(value) -> Decimal:
            return Decimal(str(value or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        now_back, now_lost = stored(lot.get("quantity_returned")), stored(lot.get("quantity_lost_or_wasted"))
        if now_back + now_lost > Decimal(str(line.get("quantity") or 0)) - back - lost:
            raise Refusal("lot_exceeds_line")
        if now_back == 0 and now_lost == 0:      # the table's own CHECK: a lot records something that moved
            raise Refusal('new row for relation "delivery_challan_returns" violates check constraint "delivery_challan_returns_something_moved"', "23514")
        written = {**{k: v for k, v in lot.items() if k not in ("challan_id", "challan_line_id", "firm_id", "client_id")},
                   "challan_id": challan["id"], "challan_line_id": line["id"], "firm_id": firm_id, "client_id": client_id}
        for column in ("quantity_returned", "quantity_lost_or_wasted"):
            if column in written:
                written[column] = _as_the_column_stores(written[column])
        assert_write_fits_production_types("delivery_challan_returns", [written])
        row = {"id": new_id("delivery_challan_returns"), **written}
        _rows(tables, "delivery_challan_returns").append(row)
        every = [ln for ln in _rows(tables, "delivery_challan_lines") if _same(ln.get("challan_id"), challan_id)]
        returns = [r for r in _rows(tables, "delivery_challan_returns") if _same(r.get("challan_id"), challan_id)]

        def came_back(ln) -> Decimal:
            return sum((Decimal(str(r.get("quantity_returned") or 0)) for r in returns if _same(r.get("challan_line_id"), ln["id"])), Decimal(0))

        stamped, last = False, None
        if not any(Decimal(str(ln.get("quantity") or 0)) > came_back(ln) for ln in every):
            last = max(str(r.get("returned_on"))[:10] for r in returns)
            challan.update({"status": "received_back", "received_back_on": last, "updated_at": ist_now().isoformat()})
            stamped = True
        return {"lot": dict(row), "challan_marked_received_back": stamped, "received_back_on": last}

    return _atomic(tables, body)


def correct_draft(tables: dict, firm_id, client_id, challan_id, header: dict, fixes: list) -> int:
    if not isinstance(header, dict):
        raise Refusal("correct_draft_challan_lines_atomic: the header patch must be a JSON object", "22023")
    if not isinstance(fixes, list):
        raise Refusal("correct_draft_challan_lines_atomic: the fixes must be a JSON array", "22023")
    if any(k in header for k in ("id", "firm_id", "client_id", "status", "issued_at", "received_back_on")):
        raise Refusal("correct_draft_challan_lines_atomic: a correction of a draft does not name its id, its owner, its status or a day", "22023")
    if any((not isinstance(f, dict)) or "id" not in f or any(k not in ("id", "description", "hsn_sac") for k in f) for f in fixes):
        raise Refusal("correct_draft_challan_lines_atomic: a correction names a line by id and gives its description and/or its HSN code, nothing else", "22023")
    if len({str(f["id"]) for f in fixes}) != len(fixes):
        raise Refusal("duplicate_fix", detail="a line is corrected once in a request")

    def body():
        challan = next((c for c in _rows(tables, "delivery_challans")
                        if _same(c.get("id"), challan_id) and _same(c.get("firm_id"), firm_id) and _same(c.get("client_id"), client_id)), None)
        if challan is None:
            raise Refusal("challan_not_found", "P0002")
        if challan.get("status") != "draft":
            raise Refusal("challan_not_draft", detail=f"status is {challan.get('status')}")
        if header:
            assert_write_fits_production_types("delivery_challans", [header])
            challan.update(header)
        done = 0
        for fix in fixes:
            if "description" in fix and fix["description"] is None:
                raise Refusal('null value in column "description" of relation "delivery_challan_lines" violates not-null constraint', "23502")
            line = next((ln for ln in _rows(tables, "delivery_challan_lines")
                         if _same(ln.get("id"), fix["id"]) and _same(ln.get("challan_id"), challan_id)
                         and _same(ln.get("firm_id"), firm_id) and _same(ln.get("client_id"), client_id)), None)
            if line is not None:
                line.update({k: v for k, v in fix.items() if k != "id"})
                done += 1
        if done != len(fixes):
            raise Refusal("line_not_found", "P0002", detail=f"{done} of {len(fixes)} corrections named a line this challan holds")
        return done

    return _atomic(tables, body)


def call(tables: dict, new_id: Callable[[str], str], fn: str, params: dict):
    """The rpc entry point a double's own `rpc` calls: the function's name and the named parameters, as PostgREST takes them."""
    if fn == "create_delivery_challan_atomic":
        return create(tables, new_id, params["p_header"], params["p_lines"])
    if fn == "record_challan_lot_atomic":
        return record_lot(tables, new_id, params["p_firm_id"], params["p_client_id"], params["p_challan_id"], params["p_lot"])
    if fn == "correct_draft_challan_lines_atomic":
        return correct_draft(tables, params["p_firm_id"], params["p_client_id"], params["p_challan_id"], params["p_header"], params["p_fixes"])
    raise Exception(f"FakeDB: unsupported rpc {fn!r}")


FUNCTIONS = ("create_delivery_challan_atomic", "record_challan_lot_atomic", "correct_draft_challan_lines_atomic")
