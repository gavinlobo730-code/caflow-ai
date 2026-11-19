"""Sign-up links (POST-A-485, 497): asked for on the sign-up form, looked at and pressed on the page the mail opens.

All three routes are PUBLIC: the person has no account yet, which is the point. The sign-up form's link request is limited per network
address in the `signup_link` bucket (`middleware/public_rate_limit`; not the `signup` bucket that creating the firm spends) and per mailed ADDRESS by the row's own counters
(`domain/firm/signup_link`); the page's two calls are limited like the other pages that turn a mailed token into a sign-in
(`invite`). The secret travels in the body of a POST and never in a path, so no access log carries it. Mounted without the
sign-in guard, like the staff invitation's routes: there is no `users` row for it to find. The rules and their reasons are in
`services/signup_link_service`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from middleware.public_rate_limit import public_limit
from models.common import api_response
from services import signup_link_service

router = APIRouter(prefix="/api/signup", tags=["signup"])


class LinkRequest(BaseModel):
    email: EmailStr
    # The cleaning and the real limit are the service's (a sentence for the form); these bound what is read at all.
    firm_name: str = Field(max_length=500)
    full_name: str = Field(max_length=500)


class TokenBody(BaseModel):
    token: str = Field(max_length=500)


@router.post("/link", dependencies=[Depends(public_limit("signup_link"))])
def request_link(body: LinkRequest):
    """Mail a link that starts a new practice to `email`. Answers the same whether or not the address already has an account."""
    try:
        asked = signup_link_service.request_link(str(body.email), body.firm_name, body.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_response(True, {"sent": True, "valid_until": asked.valid_until, "wait_seconds": asked.wait_seconds})


@router.post("/link/look", dependencies=[Depends(public_limit("invite"))])
def look(body: TokenBody):
    """What a link is for, signing nobody in: the page asks this before it offers the button."""
    return api_response(True, signup_link_service.look(body.token))


@router.post("/link/session", dependencies=[Depends(public_limit("invite"))])
def session(body: TokenBody):
    """A sign-in for the link's own address, at the press. Nothing is used up; see `services/signup_link_service.open_sign_in`."""
    return api_response(True, signup_link_service.open_sign_in(body.token))
