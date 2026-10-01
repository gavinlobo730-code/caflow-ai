"""The MFA policy, served to the browser that has to act on it — and the
deployment's own posture, served to the Partner who has to trust it.

`REQUIRE_MFA` and `MFA_REQUIRED_ROLES` are environment variables, so which
roles `mfa_guard` refuses at aal1 is a fact the browser cannot know. A Partner
or Manager with no authenticator app was therefore never told to set one up:
`mfaAssurance.ts` rightly reads "no verified factor" as nothing owed at
sign-in, and the guard then 403s every administration screen they open.

MOUNTED WITHOUT `mfa_guard`, which is why it is its own router: the caller who
needs this answer is by construction at aal1, so behind the guard it would
answer only the people who no longer need it.

`/posture` is the exception and carries the guard itself, route by route: it is
firm administration (`firm:admin`, Partner-only) and reports what the whole
deployment resolved for USE_USER_JWT, REQUIRE_MFA and the settings that fail
the same way — see `core/security_posture.py`.
"""
from fastapi import APIRouter, Depends

from core.auth import get_current_user, mfa_guard
from core.permissions import rbac
from core.security_config import mfa_required_for, mfa_required_roles, require_mfa
from core.security_posture import security_posture
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


@router.get("/posture", dependencies=[Depends(mfa_guard)])
def posture(current_user: dict = Depends(rbac("firm", "admin"))) -> dict:
    """What this deployment actually resolved for its safety switches.

    SECURITY-PRIVACY-16. `USE_USER_JWT` and `REQUIRE_MFA` are dashboard values
    (`sync: false` in render.yaml), so the repository cannot say whether they
    are on; this endpoint can, from inside the running process. Partner-only
    (`firm:admin`) and behind `mfa_guard` — unlike `/mfa-policy` above, whose
    caller is by construction at aal1, this is firm administration, and it
    reads the configuration of the whole deployment.

    Booleans, counts and fixed sentences only: no origin, no key, no URL.
    """
    return api_response(True, security_posture())
