"""The MFA policy, served to the browser that has to act on it.

`REQUIRE_MFA` and `MFA_REQUIRED_ROLES` are environment variables, so which
roles `mfa_guard` refuses at aal1 is a fact the browser cannot know. A Partner
or Manager with no authenticator app was therefore never told to set one up:
`mfaAssurance.ts` rightly reads "no verified factor" as nothing owed at
sign-in, and the guard then 403s every administration screen they open.

MOUNTED WITHOUT `mfa_guard`, which is why it is its own router: the caller who
needs this answer is by construction at aal1, so behind the guard it would
answer only the people who no longer need it.
"""
from fastapi import APIRouter, Depends

from core.auth import get_current_user
from core.security_config import mfa_required_for, mfa_required_roles, require_mfa
from models.common import api_response

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/mfa-policy")
def mfa_policy(current_user: dict = Depends(get_current_user)) -> dict:
    return api_response(True, {
        "required": require_mfa(),
        "roles": sorted(mfa_required_roles()),
        # mfa_guard's own comparison on the caller's stored role, so the nudge
        # and the refusal cannot disagree about who is covered.
        "applies_to_caller": mfa_required_for(current_user.get("role")),
    })
