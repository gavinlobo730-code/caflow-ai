"""The house-property and salary worksheets — IT Act §§22-27 and §§15-17
(TDS-INCOME-TAX-14, -15).

A SEPARATE ROUTER FROM `routers/income_tax`, deliberately. That file is the
computation's door; these are the WORKING PAPERS that feed it, kept per client
and per year, and a screen asking "what does the engine take" should not have to
read past them.

PREPARE-ONLY. Both verbs work a head of income out for a CA to look at. Neither
touches the computation, posts anything or files anything: the screen puts the
result in the computation's own boxes when the CA presses the button.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal

`GET` is `income_tax:read` and the write is `income_tax:compute` — preparation
work, the tier that already uploads an AIS statement and records a
carried-forward loss. Every route names its client in the query or the body, so
the mount-level guard fires, and each also asks `assert_client_access` itself.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.fy import FYLabel
from models.income_tax_worksheets import PAYLOADS
from services import income_tax_worksheet_service as svc

router = APIRouter(prefix="/api/income-tax/worksheets", tags=["income-tax"])
_logger = logging.getLogger("caflow.income_tax_worksheets.router")


class SaveWorksheetRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    #: The regime the computation is on. NOT stored: it is a property of the
    #: computation and the working is recomputed for whichever is asked.
    use_new_regime: bool = True
    #: The CA's inputs. Validated against the kind's own model in the service,
    #: which is also where an unknown kind is refused.
    payload: dict


def _unprocessable(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                 for e in exc.errors(include_url=False)]
        return HTTPException(status_code=422, detail="; ".join(parts))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/{kind}")
def read_worksheet(
    kind: str,
    client_id: str,
    financial_year: Annotated[FYLabel, Query()],
    use_new_regime: bool = True,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The saved inputs (or an empty worksheet) with the result worked out for
    the regime and year asked."""
    assert_client_access(current_user, client_id)
    try:
        return api_response(True, svc.get(
            firm_id=current_user["firm_id"], client_id=client_id,
            fy=financial_year, kind=kind, use_new_regime=use_new_regime))
    except svc.UnknownKind as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, *svc.Refused) as e:
        # A row written under an older vocabulary, or one the domain now
        # refuses. A sentence, never a 500.
        raise _unprocessable(e)


@router.put("/{kind}")
def save_worksheet(
    kind: str,
    req: SaveWorksheetRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Work the inputs out, and keep them only if the domain accepts them."""
    assert_client_access(current_user, req.client_id)
    try:
        return api_response(True, svc.save(
            firm_id=current_user["firm_id"], client_id=req.client_id,
            fy=req.financial_year, kind=kind, payload=req.payload,
            use_new_regime=req.use_new_regime, user_id=current_user["id"]))
    except svc.UnknownKind as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, *svc.Refused) as e:
        raise _unprocessable(e)


#: The kinds this router serves, for a guard that asserts the migration's CHECK
#: and the service agree about them.
KINDS = tuple(PAYLOADS)
