"""
A RECORDED DISALLOWANCE SAT PENDING FOR EVER AND WAS LEFT OUT OF THE RETURN.

`tax_disallowances.status` is `pending` on creation — the column's own default
and `create_disallowance`'s literal — and the tax computation screen sends only
the accepted ones to the engine:

    const totalDisall = disallowances
      .filter(d => d.status === "accepted")
      .reduce((s, d) => s + d.amount_paise, 0);

`PATCH /api/itr/disallowances/{id}/status` is the only thing that moves a row
out of `pending`, and it had NO CALLER. So every §40A(3) cash disallowance and
every §43B unpaid statutory liability a CA recorded showed in the panel, amber,
and was silently excluded from the computation.

THE DIRECTION IS THE DANGEROUS ONE. §40A(3) ADDS a disallowed cash payment back
to income, so leaving it out makes the tax come out TOO LOW — a return that
under-reports, which is what §270A charges a penalty for. An omission that
overstated tax would at least be visible to the client.

THE HALF-FIX THAT WAS ALREADY THERE IS THE PROOF. That filter's own comment
records that the total "used to be computed after the compute call and saved
alongside a figure it had not influenced, so accepting a disallowance changed
the tax by exactly ₹0". Somebody moved the filter to the right side of the
call — and left the state it filters on unreachable.

AND THE STATUS HAD NO CHECK CONSTRAINT
    Migration 156 records `pending|accepted|rejected` in a COMMENT and nothing
    enforces it, so the database stores "Accepted" or "approve" happily and the
    `=== "accepted"` filter then skips the row for ever. Unlike the loss-type
    case, where migration 319's CHECK at least failed loudly, this one fails
    silent. The request model validates it.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.itr_workspace as itrw
from core.auth import get_current_user

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(itrw.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_three_states_are_named_in_one_place():
    assert itrw.DISALLOWANCE_STATUSES == ("pending", "accepted", "rejected")


@pytest.mark.parametrize("raw,expected", [
    ("accepted", "accepted"), ("  ACCEPTED ", "accepted"),
    ("Rejected", "rejected"), ("pending", "pending"),
])
def test_a_status_is_normalised_on_the_way_in(raw, expected):
    assert itrw.DisallowanceStatusRequest(status=raw).status == expected


@pytest.mark.parametrize("bad", ["approve", "accept", "Accepted!", "", "done"])
def test_a_status_outside_the_three_is_refused(bad):
    """Silent is the point. There is NO CHECK constraint on the column, so an
    unvalidated value is stored and then skipped by the computation's filter —
    the disallowance simply never reaches the return and nothing says so."""
    with pytest.raises(Exception) as e:
        itrw.DisallowanceStatusRequest(status=bad)
    assert "pending, accepted, rejected" in str(e.value)


def test_the_endpoint_refuses_a_bad_status_with_the_valid_list():
    r = _client().patch("/api/itr/disallowances/D1/status", json={"status": "approve"})
    assert r.status_code == 422, r.text
    assert "Unknown status 'approve'" in r.text
    assert "pending, accepted, rejected" in r.text


def test_accepting_is_an_approve_action_not_a_write():
    """Manager+, because accepting changes the tax on a return. The tier is
    deliberate and is asserted so a later 'simplification' to `write` — which
    an Executive holds — is a decision rather than a slip."""
    import inspect
    src = inspect.getsource(itrw.update_disallowance_status)
    assert 'rbac("income_tax", "approve")' in src


def test_a_new_disallowance_starts_pending_and_is_therefore_excluded():
    """The premise of the whole file: creation is `pending`, and pending is not
    what the computation filters for. If creation ever defaults to `accepted`,
    this fails — and it should, because that would add every recorded item to
    income with nobody having judged it.

    Read off create_disallowance's OWN source rather than the module's. A
    negative control found the difference: `"status": "pending"` appears four
    times in that file (disallowances and deduction claims, each twice), so a
    whole-file `in` check passes while the function under test has been
    changed. An assertion a neighbour can satisfy is not an assertion.
    """
    import inspect
    from domain.income_tax.computation_workspace import create_disallowance
    src = inspect.getsource(create_disallowance)
    assert '"status": "pending"' in src, (
        "create_disallowance no longer records a disallowance as pending")
    assert '"status": "accepted"' not in src
