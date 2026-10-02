"""Price lists and a default list per customer (accounting-20).

THIN, BY DESIGN. The rule is `domain/sales/price_list.py` and the keeping is
`services/price_list_service.py`; this module decides only who may ask and what
shape the request has. Read the domain header first: a price list is a PRE-FILL
source for the rate of an invoice line and nothing else. It changes no tax, posts
nothing, and the sales-invoice create path never reads it — the invoice keeps
whatever rate it was given.

`client_id` IS REQUIRED on every route: a list belongs to one client, because a
catalogue item does.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from services import price_list_service as service
from core import db_provider

router = APIRouter(prefix="/api/price-lists", tags=["accounting"])


def _db():
    """The privileged client, or a 503 with no database. Every route is rbac()-
gated and checks the client scope first; the service carries `firm_id` and
`client_id` on every read and write, and the tables' writes are service-role-
only by grant (migration 459)."""
    return db_provider.service_db_or_503('Price lists are kept in the database and are unavailable without it.')


class PriceListIn(BaseModel):
    client_id: str
    name: str
    description: Optional[str] = None


class PriceListPatchIn(BaseModel):
    """Only what is sent changes."""

    client_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PriceListItemIn(BaseModel):
    client_id: str
    #: Whole paise, strictly positive — the service refuses anything else in words.
    rate_paise: int


class AssignIn(BaseModel):
    client_id: str
    customer_id: str
    #: `null` clears the customer's default list.
    price_list_id: Optional[str] = None


@router.get("")
def list_price_lists(
    client_id: str = Query(...),
    include_archived: bool = Query(False),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The client's named price lists."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, {"price_lists": service.list_lists(
        db, current_user["firm_id"], client_id, include_archived)})


@router.get("/customers")
def customer_assignments(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Each customer of the client and the list they are on, if any."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, {"customers": service.customer_assignments(
        db, current_user["firm_id"], client_id)})


@router.get("/resolve")
def resolve_rate(
    client_id: str = Query(...),
    customer_id: str = Query(...),
    service_catalogue_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The rate to PRE-FILL on a line when this catalogue item is picked for this
    customer, where it came from and why. Reads only: the line stays editable and
    the invoice keeps whatever rate it is given."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.resolve_rate(
        db, current_user["firm_id"], client_id, customer_id, service_catalogue_id))


@router.put("/assign")
def assign_price_list(
    body: AssignIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Set or clear a customer's default price list. A change to the customer
    master, so it takes the same permission as editing a customer."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.assign(
        db, current_user["firm_id"], body.client_id, body.customer_id, body.price_list_id,
        actor=current_user))


@router.post("")
def create_price_list(
    body: PriceListIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.create_list(
        db, current_user["firm_id"], body.client_id, body.name, body.description,
        actor=current_user))


@router.patch("/{list_id}")
def update_price_list(
    list_id: str,
    body: PriceListPatchIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Rename, describe or archive a list."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    changes = body.model_dump(exclude_unset=True)
    changes.pop("client_id", None)
    return api_response(True, service.update_list(
        db, current_user["firm_id"], body.client_id, list_id, changes, actor=current_user))


@router.get("/{list_id}/items")
def list_price_list_items(
    list_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """A list's rates, beside the catalogue's own."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.list_items(
        db, current_user["firm_id"], client_id, list_id))


@router.put("/{list_id}/items/{service_catalogue_id}")
def set_price_list_item(
    list_id: str,
    service_catalogue_id: str,
    body: PriceListItemIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Give an item a rate on this list, or change it."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.set_item(
        db, current_user["firm_id"], body.client_id, list_id, service_catalogue_id,
        body.rate_paise, actor=current_user))


@router.delete("/{list_id}/items/{service_catalogue_id}")
def remove_price_list_item(
    list_id: str,
    service_catalogue_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Take an item off a list: the catalogue rate then applies to it."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.remove_item(
        db, current_user["firm_id"], client_id, list_id, service_catalogue_id,
        actor=current_user))
