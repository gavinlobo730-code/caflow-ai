"""The house-property and salary worksheets, kept and worked out
(TDS-INCOME-TAX-14, -15).

WHAT THIS DOES AND WHAT IT LEAVES TO THE DOMAIN
    The rules are in `domain/income_tax/house_property` and `schedule_s`, which
    read nothing. This module is the I/O around them: it keeps the CA's INPUTS
    (`income_tax_worksheets`, migration 455) and hands every read back with the
    result recomputed — for the regime and the year ASKED, because neither is a
    property of the stored row. A figure stored beside the inputs would be wrong
    the day the CA flips the regime on the computation screen.

PREPARE-ONLY
    Nothing here reaches the computation by itself. The result carries the
    figures the computation's own boxes take (`head_income_paise`,
    `engine_inputs`) and the screen puts them there when the CA presses the
    button — the same posture as the 26AS claim prefill, which fills an empty
    box once and never overwrites a typed figure. Nothing is posted, nothing is
    filed and no return is touched.

One code path, two backends: the mock store is the same shape as the table so
the body below is not two implementations of the feature (`ais_service`'s
arrangement).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from domain.income_tax import house_property as hp
from domain.income_tax import schedule_s as ss
from models.income_tax_worksheets import PAYLOADS
from core import db_provider

_logger = logging.getLogger("caflow.income_tax_worksheets")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_ROWS: dict[tuple, dict] = {}

KINDS: tuple[str, ...] = tuple(PAYLOADS)

#: The refusals the domain modules raise, caught together at the door.
Refused = (hp.WorksheetRefused, ss.WorksheetRefused)


class UnknownKind(LookupError):
    """A worksheet kind this build does not have."""


_supabase = db_provider.request_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_kind(kind: str) -> None:
    if kind not in PAYLOADS:
        raise UnknownKind(
            f"There is no {kind!r} worksheet. Expected one of {', '.join(KINDS)}.")


def work_out(kind: str, payload: dict, *, fy: str, use_new_regime: bool) -> dict:
    """The worksheet's result for these inputs, the regime and the year.

    `payload` is validated through the SAME model the write door uses, so a row
    written before a vocabulary moved is refused here with a sentence, not
    computed on whatever it holds.
    """
    _check_kind(kind)
    model = PAYLOADS[kind].model_validate(payload or {})
    if kind == "house_property":
        return hp.compute(model.to_domain(), fy=fy,
                          use_new_regime=use_new_regime).to_dict()
    employers, hra = model.to_domain()
    return ss.compute(employers, fy=fy, use_new_regime=use_new_regime, hra=hra).to_dict()


def get(*, firm_id: str, client_id: str, fy: str, kind: str,
        use_new_regime: bool) -> dict:
    """The saved inputs (or an empty worksheet) with the result worked out."""
    _check_kind(kind)
    row = _find(firm_id, client_id, fy, kind)
    payload = (row or {}).get("payload_json") or {}
    return {
        "kind": kind,
        "financial_year": fy,
        "saved": row is not None,
        "updated_at": (row or {}).get("updated_at"),
        "payload": payload,
        "result": work_out(kind, payload, fy=fy, use_new_regime=use_new_regime),
    }


def save(*, firm_id: str, client_id: str, fy: str, kind: str, payload: dict,
         use_new_regime: bool, user_id: str) -> dict:
    """Validate, work out, THEN store — so a worksheet the domain refuses is
    never kept, and the answer to the save is the working the CA is about to
    look at."""
    _check_kind(kind)
    model = PAYLOADS[kind].model_validate(payload or {})
    clean = model.model_dump(mode="json")
    result = work_out(kind, clean, fy=fy, use_new_regime=use_new_regime)
    row = _upsert(firm_id=firm_id, client_id=client_id, fy=fy, kind=kind,
                  payload=clean, user_id=user_id)
    return {
        "kind": kind,
        "financial_year": fy,
        "saved": True,
        "updated_at": row.get("updated_at"),
        "payload": clean,
        "result": result,
    }


# ── I/O, both backends ──────────────────────────────────────────────────────

def _find(firm_id: str, client_id: str, fy: str, kind: str) -> Optional[dict]:
    if _USE_MOCK:
        row = _MOCK_ROWS.get((firm_id, client_id, fy, kind))
        return dict(row) if row else None
    res = (_supabase().table("income_tax_worksheets").select("*")
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("financial_year", fy).eq("worksheet_kind", kind)
           .limit(1).execute())
    return (res.data or [None])[0]


def _upsert(*, firm_id: str, client_id: str, fy: str, kind: str,
            payload: dict, user_id: str) -> dict:
    if _USE_MOCK:
        prior = _MOCK_ROWS.get((firm_id, client_id, fy, kind)) or {}
        saved = {
            "id": prior.get("id") or str(uuid4()),
            "firm_id": firm_id, "client_id": client_id,
            "financial_year": fy, "worksheet_kind": kind,
            "payload_json": payload, "updated_by": user_id,
            "created_at": prior.get("created_at") or _now(),
            "updated_at": _now(),
        }
        _MOCK_ROWS[(firm_id, client_id, fy, kind)] = saved
        return dict(saved)
    res = (_supabase().table("income_tax_worksheets")
           .upsert({
               "firm_id": firm_id,
               "client_id": client_id,
               "financial_year": fy,
               "worksheet_kind": kind,
               "payload_json": payload,
               "updated_by": user_id,
               "updated_at": _now(),
           }, on_conflict="firm_id,client_id,financial_year,worksheet_kind")
           .execute())
    return (res.data or [{}])[0]


def _reset_mock_state() -> None:
    """Tests only."""
    _MOCK_ROWS.clear()
