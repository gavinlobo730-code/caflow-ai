"""
Module 9.0 / M4 — Governance approval engine (maker-checker).

A maker submits an approval_request for a sensitive action; a Partner (checker)
approves or rejects. On approval the registered handler executes the real
mutation via existing repositories/services (no duplicated business logic). Every
transition is mirrored to the immutable audit_log.

Request types (handlers execute against existing server paths):
  mfa_reset   -> services.mfa_reset_service (a lost authenticator, POST-A-006)

Two sets of types were RETIRED, each because its handler reported a success it had not earned:

  * chart of accounts (coa_create / coa_update / coa_delete), 17-10-2026 (POST-A-007's review): the handlers called the
    in-memory `domain.accounting_service`, which the REST routes had already been moved off because a change made there
    "was reported as saved and was not", so an approved request recorded success and wrote no account.
  * staff and client assignments (user_create / user_activation / role_change / assignment_create / assignment_remove /
    assignment_transfer), 19-10-2026 (POST-A-240): no screen or job ever raised one, and each handler wrote the
    repository directly and so skipped what the direct route asks first (that the user, and for an assignment the client,
    belong to this firm; the invitation a new user needs; the route's own audit entry). A handler whose update matched no
    user returned an empty result and the request read `approved`, the same false success. A firm that wants a second
    person on these acts builds it as a request that calls the SAME function the route calls, not the repository.

Nothing creates a retired type. A stored request of one can still be rejected or cancelled and is refused on approval in
words (`RETIRED_TYPES`).
"""
import logging
from typing import Optional

from fastapi import HTTPException

from repositories.approval_repository import approval_repo
from services import mfa_reset_service
from services.audit_service import log_event

logger = logging.getLogger(__name__)


# type -> required payload keys, summary builder, handler, and optional hooks:
#   prepare(firm_id, payload, actor) -> payload   validates when the request is MADE and returns what is stored
#   check_decider(firm_id, req, decider)          refuses a decision BEFORE it is claimed (raises HTTPException)
#   audit_extra(req, result, decider) -> dict     extra metadata on the "approved" audit entry
#   after_approval(firm_id, req, result, decider) a second record the type owes once its action has run
_SPECS: dict[str, dict] = {
    "mfa_reset":         {"required": [],
                           "summary": mfa_reset_service.summary,
                           "handler": mfa_reset_service.execute,
                           "prepare": mfa_reset_service.prepare,
                           "check_decider": mfa_reset_service.check_decider,
                           "audit_extra": mfa_reset_service.audit_extra,
                           "after_approval": mfa_reset_service.after_approval},
}

REQUEST_TYPES = tuple(_SPECS.keys())

# Types an earlier version accepted, that a stored row may still carry. Reading one is fine; carrying one out is not.
# Why each group was retired is in the module docstring.
RETIRED_TYPES = frozenset({
    "coa_create", "coa_update", "coa_delete",
    "user_create", "user_activation", "role_change",
    "assignment_create", "assignment_remove", "assignment_transfer",
})


def _audit(firm_id: str, req: dict, action: str, actor: dict, **extra) -> None:
    # `actor` is a current_user, and audit_log.actor_id takes the SUPABASE AUTH
    # id — the same key migration 111's trigger writes as auth.uid(). See
    # tests/test_the_audit_log_names_one_kind_of_actor.py.
    log_event(firm_id, "approval_request", req.get("id", ""), action,
              actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
              metadata={"request_type": req.get("request_type"), **extra})


# ── Public API ───────────────────────────────────────────────────────────────

def create_request(firm_id: str, request_type: str, payload: dict, actor: dict) -> dict:
    spec = _SPECS.get(request_type)
    if not spec:
        if request_type in RETIRED_TYPES:
            # A sentence, not "unknown": the caller did nothing wrong in asking for a kind this product once accepted.
            raise HTTPException(400, f"'{request_type}' requests are no longer accepted. That action is made directly, "
                                     "with its own checks, and does not go through an approval.")
        raise HTTPException(400, f"Unknown request_type '{request_type}'")
    missing = [k for k in spec["required"] if k not in (payload or {})]
    if missing:
        raise HTTPException(422, f"Missing payload fields: {', '.join(missing)}")
    if spec.get("prepare"):
        # The stored payload is what the SERVER resolved, never the browser's words about whom the request is for.
        payload = spec["prepare"](firm_id, payload or {}, actor)
    row = approval_repo.create({
        "firm_id": firm_id, "request_type": request_type,
        "summary": spec["summary"](payload), "payload": payload,
        "status": "pending",
        "requested_by": actor.get("id"), "requested_by_email": actor.get("email"),
    })
    _audit(firm_id, row, "request_created", actor, summary=row.get("summary"))
    return row


def _load_pending(firm_id: str, request_id: str) -> dict:
    req = approval_repo.get(firm_id, request_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    if req["status"] != "pending":
        raise HTTPException(409, f"Request already {req['status']}")
    return req


def _lost_the_race() -> HTTPException:
    return HTTPException(409, "Request already decided")


# A decision is CLAIMED before anything else happens: one `UPDATE ... WHERE status = 'pending'`
# (`approval_repo.decide_if_pending`), so of two simultaneous decisions exactly one gets a row back
# and the other is refused. Reading the status and writing it later left a window in which two
# approvals both passed the check and the handler (a user created, a role changed, an account
# archived) ran twice, and in which a rejection could overwrite an approval whose action had
# already run (POST-A-007).

def approve(firm_id: str, request_id: str, approver: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    spec = _SPECS.get(req["request_type"])
    if spec is None:
        # Refused before the claim, so the request stays pending and can still be rejected or cancelled.
        raise HTTPException(409, "This kind of request can no longer be carried out. Reject it instead.")
    if spec.get("check_decider"):
        # Refused before the claim, like an unknown type: the request stays pending and the right person can decide it.
        spec["check_decider"](firm_id, req, approver)
    claimed = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "approved", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(),
    })
    if claimed is None:
        raise _lost_the_race()
    try:
        result = spec["handler"](firm_id, req["payload"])  # executes the real mutation
    except Exception:
        # The action raised, so the request is not decided: put it back for the next try. A handler is one repository
        # call or two (the same as before the claim existed, when a failure also left the request pending), so the
        # retry is the same attempt again. If even the put-back fails, or the process dies between the claim and the
        # result, the request is left reading approved with no result: the API refuses a second approval of it (409),
        # and the log says so at ERROR in the first case.
        try:
            approval_repo.update(firm_id, request_id, {
                "status": "pending", "decided_by": None, "decided_by_email": None, "decided_at": None,
            })
        except Exception:  # noqa: BLE001 - the original failure is the one to raise
            logger.error("approval %s: the action failed AND the request could not be put back to pending",
                         request_id, exc_info=True)
        raise
    updated = approval_repo.update(firm_id, request_id, {"result": result})
    extra = spec["audit_extra"](req, result, approver) if spec.get("audit_extra") else {}
    _audit(firm_id, req, "approved", approver, **extra)
    if spec.get("after_approval"):
        spec["after_approval"](firm_id, req, result, approver)
    return updated


def reject(firm_id: str, request_id: str, approver: dict, reason: Optional[str] = None) -> dict:
    req = _load_pending(firm_id, request_id)
    updated = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "rejected", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(), "reason": reason,
    })
    if updated is None:
        raise _lost_the_race()
    _audit(firm_id, req, "rejected", approver, reason=reason)
    return updated


def cancel(firm_id: str, request_id: str, actor: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    # Only the original requester or a Partner may cancel a pending request.
    is_partner = str(actor.get("role", "")).strip().lower() in ("partner", "owner")
    if not is_partner and actor.get("id") != req.get("requested_by"):
        raise HTTPException(403, "Only the requester or a Partner may cancel this request")
    updated = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "cancelled", "decided_by": actor.get("id"),
        "decided_by_email": actor.get("email"), "decided_at": _now(),
    })
    if updated is None:
        raise _lost_the_race()
    _audit(firm_id, req, "cancelled", actor)
    return updated


def list_requests(firm_id: str, status: Optional[str] = None) -> list[dict]:
    return approval_repo.list(firm_id, status=status)


def get_request(firm_id: str, request_id: str) -> Optional[dict]:
    return approval_repo.get(firm_id, request_id)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
