"""The hub — fifteen tiles, one request.

Thin surface over `services/hub_service.py`, which fetches what
`domain/hub/tiles.py` decides. Nothing here knows what a tile asks, which
table answers it, or that three of them have no figure at firm scope.

ONE ENDPOINT AND NOT FIFTEEN. `apps/api` runs in Singapore and Postgres is in
Mumbai; fifteen browser fetches would be fifteen cross-region round trips for a
screen showing fifteen numbers. The service's docstring carries the rest of
that argument, including why one tile failing must not empty the hub.

`client_id` IS THE SCOPE, NOT A FILTER. Omitted, this is the firm hub, scoped
by `effective_client_ids` so an Executive sees their own book. Given, it is
that client's hub and `assert_client_access` runs — a hub is a read of the
client's work like any other.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from services import hub_service

router = APIRouter(prefix="/api/hub", tags=["hub"])


@router.get("")
def get_hub(
    client_id: Optional[str] = Query(
        None, description="Omit for the firm hub; give one for that client's."),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Every tile this hub shows, with its figure.

    `client:read` is the guard: the hub names the practice's clients' work, and
    somebody who may not read clients has no business seeing how many of their
    returns are unfiled. It is deliberately NOT the union of the fifteen
    modules' own permissions — a tile shows a COUNT and links to a screen that
    runs its own `rbac()`, so a CA who cannot open Payroll sees that eleven
    runs are unreleased and is refused at the door. That is the truthful
    behaviour, and cheaper than fifteen permission checks on one request.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    return api_response(True, hub_service.hub(current_user, client_id))
