"""The staff door `PUT /api/payroll/declarations` files an employee's Form 12BB through `file_it_declaration` (POST-A-340, migration 548).

It used to upsert the header, delete the old lines and insert the new ones as separate requests with no put-back, so two filings of
one declaration at the same instant could leave the header of one beside the lines of the other. It makes ONE call now, and this
holds what the call carries and what comes back:

  * THE FIGURES ARE THE DOOR'S OWN: negatives floored at nothing, PANs upper-cased, a blank name stored blank; the lines carry their
    label, proof reference and (already normalised) attachments, and every line the caller sent is filed, a head at nothing included
    (the employee's door leaves those out, the staff door never did);
  * A VERIFIED DECLARATION IS REPLACED, not refused (`p_refuse_verified` is false), and the verdict is reset: the figures claimed are
    no longer the ones the CA checked;
  * THE FUNCTION'S REFUSALS are words: a row that could not be taken is a 409, an employee that is not the client's is a 404, and any
    other failure is the failure it is (nothing is logged to the client's timeline for a filing that did not happen);
  * VALIDATION STILL COMES FIRST: a declaration payroll cannot give effect to is a 422 and the function is never called.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as pr
import tests.e2e_harness as harness
from models.payroll import DeclarationIn, DeclarationItemIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_CLIENT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
EMP = "a0000000-0000-0000-0000-00000000000a"
OTHER_EMP = "b0000000-0000-0000-0000-00000000000b"
FY = "2026-27"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    db.seed("payroll_employees", {"id": EMP, "firm_id": FIRM, "client_id": CLIENT, "name": "Asha"})
    db.seed("payroll_employees", {"id": OTHER_EMP, "firm_id": FIRM, "client_id": OTHER_CLIENT, "name": "Bala"})
    wire_e2e(monkeypatch, db, [pr])
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "assert_payroll_enabled", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_not_internal_for_payroll", lambda *a, **k: None)
    logged: list = []
    monkeypatch.setattr(pr.timeline_service, "log", lambda *a, **k: logged.append((a, k)))
    db.logged = logged
    return db


def _body(**over):
    base = dict(client_id=CLIENT, employee_id=EMP, fy=FY, regime="old",
                items=[DeclarationItemIn(section="80C", amount_declared_paise=15_000_000, label="PPF", proof_reference="r-1")])
    base.update(over)
    return DeclarationIn(**base)


def _watch(monkeypatch):
    seen: list = []
    real = harness._Rpc.execute

    def execute(rpc):
        if rpc.fn == "file_it_declaration":
            seen.append(rpc.params)
        return real(rpc)

    monkeypatch.setattr(harness._Rpc, "execute", execute)
    return seen


def test_a_filing_is_one_call_that_carries_the_doors_figures_and_does_not_refuse_a_verified_declaration(world, monkeypatch):
    seen = _watch(monkeypatch)
    out = pr.upsert_declaration(_body(landlord_pan="abcde1234f", landlord_name="L", rent_paid_declared_paise=15_000_000, lta_declared_paise=-5),
                                current_user=USER)
    assert out["success"] is True
    [params] = seen
    assert params["p_refuse_verified"] is False, "the staff door replaces a verified declaration"
    decl = params["p_declaration"]
    assert (decl["firm_id"], decl["client_id"], decl["employee_id"], decl["fy"]) == (FIRM, CLIENT, EMP, FY)
    assert decl["landlord_pan"] == "ABCDE1234F" and decl["lta_declared_paise"] == 0
    [head] = world.rows("payroll_it_declarations")
    assert out["data"]["declaration_id"] == head["id"] and head["landlord_pan"] == "ABCDE1234F"
    [line] = world.rows("payroll_it_declaration_items")
    assert (line["section"], line["label"], line["amount_declared_paise"], line["proof_reference"], line["status"]) == \
        ("80C", "PPF", 15_000_000, "r-1", "declared")
    assert len(world.logged) == 1


def test_every_figure_the_door_was_given_reaches_the_function_under_its_own_key_and_a_proof_is_not_wiped(world, monkeypatch):
    """Every box carries its own non-zero value, the metro flag is on, and a line carries a proof attachment: a figure under another
    box's key, a flag negated, a name or address dropped, or a staff re-declaration that wipes the proofs the employee uploaded is a
    different payload."""
    seen = _watch(monkeypatch)
    attachment = {"name": "LIC receipt", "url": "https://files.example.test/lic.pdf"}
    body = _body(
        regime="old", rent_paid_declared_paise=1_200_000, landlord_name="Landlord", landlord_address="12 Rose Street",
        landlord_pan="abcde1234f", rent_is_metro=True, lta_declared_paise=2_300_000, home_loan_interest_declared_paise=3_400_000,
        lender_name="Bank", lender_pan="abcde1234g", other_income_declared_paise=4_500_000, house_property_loss_declared_paise=5_600_000,
        items=[DeclarationItemIn(section="80C", amount_declared_paise=6_700_000, label="LIC", proof_reference="ref-7",
                                 proof_attachments=[attachment]),
               DeclarationItemIn(section="80D-self", amount_declared_paise=0)])
    pr.upsert_declaration(body, current_user=USER)
    [params] = seen
    assert params["p_declaration"] == {
        "firm_id": FIRM, "client_id": CLIENT, "employee_id": EMP, "fy": FY, "regime": "old",
        "rent_paid_declared_paise": 1_200_000, "landlord_name": "Landlord", "landlord_address": "12 Rose Street",
        "landlord_pan": "ABCDE1234F", "rent_is_metro": True,
        "lta_declared_paise": 2_300_000,
        "home_loan_interest_declared_paise": 3_400_000, "lender_name": "Bank", "lender_pan": "ABCDE1234G",
        "other_income_declared_paise": 4_500_000,
        "house_property_loss_declared_paise": 5_600_000,
    }
    # Every line the caller sent is filed, a head at nothing included (the employee's door leaves those out).
    assert params["p_items"] == [
        {"section": "80C", "label": "LIC", "amount_declared_paise": 6_700_000, "proof_reference": "ref-7",
         "proof_attachments": [attachment]},
        {"section": "80D-self", "label": "", "amount_declared_paise": 0, "proof_reference": "", "proof_attachments": []},
    ]
    # And what the function stored is what was filed, the proofs included.
    [head] = world.rows("payroll_it_declarations")
    assert (head["rent_paid_declared_paise"], head["lta_declared_paise"], head["home_loan_interest_declared_paise"],
            head["other_income_declared_paise"], head["house_property_loss_declared_paise"]) == \
        (1_200_000, 2_300_000, 3_400_000, 4_500_000, 5_600_000)
    assert head["rent_is_metro"] is True and head["landlord_address"] == "12 Rose Street" and head["lender_name"] == "Bank"
    stored = {i["section"]: i for i in world.rows("payroll_it_declaration_items")}
    assert stored["80C"]["proof_attachments"] == [attachment]


def test_the_door_hands_the_function_the_routers_own_server_client_and_never_the_requests(monkeypatch):
    """The function is executable by the service role alone. The door files through the client its router builds for these tables
    (`core.db_provider.service_db`), and the request's own client (a signed-in session's, under USE_USER_JWT) is wired to raise, so a
    door that reached for it would fail here and not as 'permission denied for function' in production."""
    import core.db_provider as dbp
    import core.supabase_client as sc
    server = FakeDB()
    server.seed("payroll_employees", {"id": EMP, "firm_id": FIRM, "client_id": CLIENT, "name": "Asha"})
    wire_e2e(monkeypatch, server, [pr])

    def not_the_requests_client(*a, **k):
        raise AssertionError("the declaration was filed through the request's own client")

    monkeypatch.setattr(sc, "get_supabase", not_the_requests_client)
    monkeypatch.setattr(dbp, "request_db", not_the_requests_client)
    monkeypatch.setattr(dbp, "request_db_or_none", not_the_requests_client)
    monkeypatch.setattr(dbp, "_configured", lambda: True)
    monkeypatch.setattr(pr, "_db", dbp.service_db_or_none)          # the router's own binding, as it is in production
    monkeypatch.setattr(pr, "assert_payroll_enabled", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_not_internal_for_payroll", lambda *a, **k: None)
    monkeypatch.setattr(pr.timeline_service, "log", lambda *a, **k: None)
    out = pr.upsert_declaration(_body(), current_user=USER)
    assert out["success"] is True and len(server.rows("payroll_it_declarations")) == 1


def test_a_head_at_nothing_is_still_a_line_for_the_staff_door(world):
    pr.upsert_declaration(_body(items=[DeclarationItemIn(section="80C", amount_declared_paise=0)]), current_user=USER)
    assert [(i["section"], i["amount_declared_paise"]) for i in world.rows("payroll_it_declaration_items")] == [("80C", 0)]


def test_a_verified_declaration_is_replaced_and_its_verdict_reset(world):
    pr.upsert_declaration(_body(), current_user=USER)
    head = world.rows("payroll_it_declarations")[0]
    head.update(proofs_verified=True, rent_paid_verified_paise=4_000_000, verified_by="u9", verified_at="2026-10-01T00:00:00+00:00")
    out = pr.upsert_declaration(_body(regime="new", items=[DeclarationItemIn(section="80D-self", amount_declared_paise=7)]), current_user=USER)
    assert out["success"] is True
    [head] = world.rows("payroll_it_declarations")
    assert head["regime"] == "new" and head["proofs_verified"] is False and head["rent_paid_verified_paise"] == 0
    assert head["verified_by"] is None and head["verified_at"] is None
    assert [(i["section"], i["amount_declared_paise"]) for i in world.rows("payroll_it_declaration_items")] == [("80D-self", 7)]


def _raises(monkeypatch, code, message):
    from postgrest.exceptions import APIError

    def boom(rpc):
        raise APIError({"message": message, "code": code, "hint": None, "details": None})

    monkeypatch.setattr(harness._Rpc, "_fn_file_it_declaration", boom)


def test_a_row_that_could_not_be_taken_is_a_409_and_is_not_logged(world, monkeypatch):
    _raises(monkeypatch, "40001", "file_it_declaration: could not take the declaration")
    with pytest.raises(HTTPException) as e:
        pr.upsert_declaration(_body(), current_user=USER)
    assert e.value.status_code == 409 and "same moment" in e.value.detail
    assert world.rows("payroll_it_declarations") == [] and world.logged == []


def test_an_employee_that_is_not_the_clients_is_a_404_from_the_function_too(world, monkeypatch):
    _raises(monkeypatch, "42501", "file_it_declaration: employee x is not an employee of client y of firm z")
    with pytest.raises(HTTPException) as e:
        pr.upsert_declaration(_body(), current_user=USER)
    assert e.value.status_code == 404 and world.logged == []


def test_any_other_failure_is_the_failure_it_is_and_nothing_is_logged(world, monkeypatch):
    _raises(monkeypatch, "XX000", "something unexpected")
    from postgrest.exceptions import APIError
    with pytest.raises(APIError):
        pr.upsert_declaration(_body(), current_user=USER)
    assert world.logged == []


def test_what_payroll_cannot_give_effect_to_is_refused_before_the_function_is_called(world, monkeypatch):
    seen = _watch(monkeypatch)
    with pytest.raises(HTTPException) as e:
        pr.upsert_declaration(_body(rent_paid_declared_paise=15_000_000, landlord_name="L"), current_user=USER)   # no landlord PAN
    assert e.value.status_code == 422 and seen == []


def test_an_employee_of_another_client_never_reaches_the_function(world, monkeypatch):
    seen = _watch(monkeypatch)
    with pytest.raises(HTTPException) as e:
        pr.upsert_declaration(_body(employee_id=OTHER_EMP), current_user=USER)
    assert e.value.status_code == 404 and seen == [] and world.rows("payroll_it_declarations") == []
