"""The firm-wide statutory risk register.

FIVE ROUTES WERE HERE AND ARE RETIRED (POST-A-548, 22-11-2026): a list of the risks recorded against documents, their
counts, one client's, the firm's score, and a route to mark one resolved or dismissed. No screen called any of them, so a
risk recorded there could be neither seen nor closed by a person, and NOTHING RECORDS ONE: no code inserts into
`document_risks` (`detect_document_risks` has no caller) and production held no row. A screen for them would have been a
screen over an empty table for good, so the routes went and their tests with them. The table and the functions that
still read it for a count stay (`domain/risk_engine.get_all_risks`, which the insight feed reads, and
`get_risk_dashboard_stats`, which the copilot's firm context reads); if document risks are ever recorded, the way to see
and close one is designed then, with the writer.
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from core.authz import effective_client_ids

router = APIRouter(prefix="/api/risks", tags=["risks"])


@router.get("/register")
def risk_register(current_user: dict = Depends(rbac("risk", "read"))):
    """The firm-wide statutory risk register.

    It derives nine kinds from the compliance CALENDAR, the client master, the
    DSC register, loans and fixed deposits. It is NOT the risks recorded against
    documents (`document_risks`), a different population whose own routes were
    retired on 22-11-2026 (the module's header says why).

    `apps/web/app/risks/page.tsx` used to derive all nine in the browser from
    six PostgREST reads, so `rbac()` ran on none of them and neither did
    `core.authz`'s assignment scope. `effective_client_ids` supplies that scope
    here: None means firm-wide, and an EMPTY set means nothing rather than
    everything.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Reports only; writes nothing.
    """
    from core.supabase_client import get_supabase
    from services.risk_register_service import build_register

    firm_id = current_user.get("firm_id")
    return api_response(
        True,
        build_register(get_supabase(), firm_id, effective_client_ids(current_user)),
    )
