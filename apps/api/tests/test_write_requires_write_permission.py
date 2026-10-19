"""
An endpoint that CHANGES data must not be satisfied by a read-level permission.

The client-scope sweep answered "may this caller see this client?". It never
asked "may this caller CHANGE it?". Those are different questions and the second
was going unchecked: a scan of all 428 mutating routes found 8 that a read-only
role could invoke.

Reviewer is the role that makes this concrete. The permission matrix documents
it as read/approve-only, so any mutation Reviewer can reach is a bug by the
project's own definition — no judgement call required.

The routes fixed here, and why each was wrong rather than merely inconsistent:

  * gst-portal sync-jobs (create + run) sat on gst:read while their own sibling
    in the same file, save_manual_snapshot, already used gst:compute. One file,
    two answers — that is an oversight, not a decision.
  * identity login-event sat on ai:read. It WRITES via login_events_repo.record,
    and "ai" is not even the subject; the endpoint records who signed in.

Left deliberately alone: POST endpoints that compute without writing — the
banking previews, billing preview-run, the GSTR validators, and /api/assistant.
They are POST only because they take a JSON body. A test that flagged those
would be a test nobody could keep green honestly.
"""
import pytest

from core.permissions import PERMISSIONS, can


READ_LEVEL = {"read"}


def test_reviewer_cannot_run_gst_portal_sync_jobs():
    """gst:compute excludes Reviewer; gst:read does not. This is the whole fix."""
    assert can("Reviewer", "gst", "read") is True      # unchanged: may look
    assert can("Reviewer", "gst", "compute") is False  # may not act


@pytest.mark.parametrize("role", ["Executive", "Manager", "Partner"])
def test_delivery_roles_keep_gst_portal_access(role):
    """The fix must not cost the people doing the work their access — that is
    how a tightened permission gets reverted a week later."""
    assert can(role, "gst", "compute") is True


def test_identity_write_is_available_to_every_staff_role():
    """login-event is self-service telemetry: the caller records the caller.
    Every staff role signs in, so every staff role must be able to write it.
    Modelled as identity:write rather than borrowed from team:write, which is
    Partner-only and would have broken sign-in recording for everyone else.
    """
    for role in ("Partner", "Manager", "Executive", "Reviewer"):
        assert can(role, "identity", "write") is True, role


def test_identity_write_is_not_available_to_portal_clients():
    """Staff telemetry. A portal Client is a different audience entirely."""
    assert can("Client", "identity", "write") is False


MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _read_level_offenders(routes, allowed) -> list[str]:
    """Mutating `/api/` routes that no permission above a read-only role's reach guards.

    A route guarded by `read` alone is an offender. A route that asks `read` AND another action is satisfied only when that other
    action EXCLUDES a Reviewer (a read-only role): then the read is a SECOND guard. That is the shape of the payroll finalise tier
    (finalize, disburse, reverse, the loan write-down and a leaver's settlement ask payroll:finalize and payroll:read, so a Partner
    blocked from reading payroll is told so at the door, POST-A-219) and of Form 24Q from the books (tds:compute, plus payroll:read
    because a 24Q lists every employee's PAN, salary and tax, migration 485). A second action a Reviewer holds (`time_entry:write`,
    `report:export`) does not make the route a write guard, and the first version of this refinement, which only asked that the
    actions not ALL be `read`, let that through (an independent review of it). A route with NO rbac dependency at all is not this
    test's question and is not flagged."""
    offenders = []
    for route in routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in allowed:
            continue
        methods = (getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}
        if not (methods & MUTATING):
            continue

        pairs = set()
        for dep in getattr(getattr(route, "dependant", None), "dependencies", []) or []:
            name = getattr(getattr(dep, "call", None), "__name__", "")
            if name.startswith("rbac_"):
                resource, action = name[len("rbac_"):].rsplit("_", 1)
                pairs.add((resource, action))

        actions = {action for _, action in pairs}
        if not actions:
            continue
        beyond_read = {(r, a) for r, a in pairs if a not in READ_LEVEL}
        if actions <= READ_LEVEL or (READ_LEVEL & actions and all(can("Reviewer", r, a) for r, a in beyond_read)):
            offenders.append(f"{sorted(methods & MUTATING)[0]} {path} -> {sorted(actions)}")
    return offenders


def test_a_read_level_guard_beside_a_stronger_one_is_not_an_offender_and_read_alone_is():
    """The negative control for the refinement above: on a small app, a POST guarded by read alone is flagged, and one guarded by
    read AND write is not (the same two routes the old rule flagged together)."""
    from fastapi import APIRouter, Depends, FastAPI

    from core.permissions import rbac

    app = FastAPI()
    r = APIRouter(prefix="/api/probe")
    r.post("/read-only", dependencies=[Depends(rbac("payroll", "read"))])(lambda: {})
    r.post("/read-and-write", dependencies=[Depends(rbac("payroll", "read")), Depends(rbac("payroll", "write"))])(lambda: {})
    r.post("/write-only", dependencies=[Depends(rbac("payroll", "write"))])(lambda: {})
    # read beside an action a REVIEWER also holds is still read-level: it is not a write guard
    r.post("/read-and-a-weak-one", dependencies=[Depends(rbac("payroll", "read")), Depends(rbac("time_entry", "write"))])(lambda: {})
    # read beside an action a Reviewer does not hold is the finalise-tier shape
    r.post("/read-and-finalize", dependencies=[Depends(rbac("payroll", "read")), Depends(rbac("payroll", "finalize"))])(lambda: {})
    app.include_router(r)
    assert _read_level_offenders(app.routes, set()) == [
        "POST /api/probe/read-only -> ['read']",
        "POST /api/probe/read-and-a-weak-one -> ['read', 'write']",
    ]


def test_no_mutating_route_is_guarded_by_a_read_level_action():
    """The ratchet. Walks every POST/PUT/PATCH/DELETE route and reads the rbac
    dependency off it — rbac() names its dependency rbac_{resource}_{action},
    which makes the declared action recoverable from the live app.

    ALLOWED lists the routes that mutate nothing despite being POST. Each entry
    is a claim that the handler performs no write; adding one is a statement
    about behaviour, not a way to silence the test.
    """
    import main

    ALLOWED = {
        # Compute-only: POST purely because the request carries a JSON body.
        # The filing-demo preview builds a walk-through script and writes
        # nothing by design — test_filing_demo_framework.py scans every flow
        # module and the router for write markers, so this claim is enforced,
        # not just asserted.
        "/api/filing-demo/{flow}/preview",
        "/api/banking/reconciliations/{recon_id}/preview",
        "/api/banking/transactions/{txn_id}/posting-preview",
        # The AS 11 revaluation preview. POST because the closing rates are a
        # map and a query string is the wrong place for one. It runs
        # `FXRevaluationService.plan`, which is the READ half of the walk the
        # posting path posts from, and writes nothing — enforced, not merely
        # asserted, by test_the_year_end_fx_revaluation_has_a_door.py, which
        # counts the rows in `fx_revaluations` and `journal_entries` either
        # side of the call. It sits at accounting:read deliberately: a
        # reviewer who may not post still needs to see the working.
        "/api/fx-revaluation/preview",
        "/api/billing/preview-run",
        # A leaver's settlement is COMPUTED and handed back for a human to act
        # on. POST only because the request body carries the facts no record
        # holds — why they left, what the contract says about notice, what they
        # still owe. Settling an employee ends their employment, releases money
        # and closes a PF account; none of that is something a preview should do
        # as a side effect, so the handler reads and returns and writes nothing.
        "/api/payroll/employees/{employee_id}/settlement",
        # NOTE: .../settlement/record is NOT here — it writes, posts to the
        # ledger and closes an employment, and is guarded at payroll:finalize.
        # §89(1) relief is likewise computed and returned. Nothing is
        # written and, in particular, Form 10E is not filed — the proviso
        # to §89 requires it on the e-filing portal before the return, and
        # that is the taxpayer's act, not payroll's.
        "/api/payroll/employees/{employee_id}/arrears-relief",
        # Rule 3 valuation is computed and returned. Recording it is a
        # separate PUT at payroll:write, because accepting a valuation
        # changes an employee's taxable salary and their Form 16.
        "/api/payroll/employees/{employee_id}/perquisites/value",
        # The mapped-IP check compares a list the CA pasted off the ESIC
        # portal against the members of this run's contribution file, and
        # returns the difference. POST only because that list is too long for
        # a query string. Nothing is transmitted and nothing is stored — the
        # pasted list is compared and discarded — and the return it compares
        # against is built by _build_run_esic, the same read-only assembly
        # GET /runs/{run_id}/esic already uses.
        "/api/payroll/runs/{run_id}/esic/mapped-ips",
        # PUR-32's preflight: reads this vendor's live bills and answers
        # which of them the one being typed may be a second copy of. POST
        # rather than GET because the request carries an invoice NUMBER, and a
        # document identifier has no business in a URL, a query string or an
        # access log — the same reason /tds-preview is a POST. It inserts
        # nothing: the rule it applies (domain/purchases/near_duplicate) takes
        # rows and returns findings, and never sees a database handle.
        "/api/purchase-bills/near-duplicates",
        # The NRV write-down preview (POST-A-134): what a write-down to this NRV would do right now, for the modal to
        # show before anyone presses Save. POST because the NRV is a value in a body, as for the write itself. It reads
        # the item and the stock ledger's latest row and hands them to `_compute_nrv_writedown`, the pure function the
        # posting runs, and writes nothing: test_the_nrv_writedown_preview_is_the_servers_arithmetic.py counts the
        # ledger, journal and audit rows either side of three previews, so this claim is enforced, not asserted. It sits
        # at accounting:read deliberately, like the FX revaluation preview: whoever may see the stock may see the working.
        "/api/inventory/items/{service_catalogue_id}/writedown-preview",
        "/api/gst/validate/gstr1",
        "/api/gst/validate/gstr3b",
        # Stateless Groq passthrough over a static prompt; loads nothing, writes
        # nothing. Verified when its dead client_id field was removed.
        "/api/assistant",
        # Copilot: deliberately open to every role. The protection here is that
        # the prompt carries no client-identifying data at all (see
        # test_copilot_no_client_data.py), which holds regardless of role.
        "/api/copilot/chat",
        "/api/copilot/conversations",
        "/api/copilot/conversations/{conversation_id}/archive",
        "/api/copilot/conversations/{conversation_id}/messages",
        "/api/copilot/messages/{message_id}/feedback",
    }

    offenders = _read_level_offenders(main.app.routes, ALLOWED)

    assert not offenders, (
        "these routes change data but are satisfied by a read-level permission:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nGive them an action that excludes read-only roles, or add them to "
          "ALLOWED with a note explaining why they write nothing."
    )


def test_the_route_walk_actually_found_routes():
    """Guard against the ratchet passing vacuously if route introspection or the
    rbac dependency naming ever changes shape."""
    import main

    MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
    seen = 0
    for route in main.app.routes:
        if not getattr(route, "path", "").startswith("/api/"):
            continue
        if (getattr(route, "methods", set()) or set()) & MUTATING:
            seen += 1

    assert seen >= 400, f"only {seen} mutating routes found — the walk looks broken"
