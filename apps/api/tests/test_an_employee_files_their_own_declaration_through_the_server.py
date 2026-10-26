"""POST-A-010, the employee portal's tax-declaration tab: the employee's Form 12BB is read and filed through the server.

THE FAULT. The tab read `payroll_it_declarations` and its lines from PostgREST, and wrote them there: an upsert of the header, a
delete of the old lines and an insert of the new ones, as the employee's own token, under migration 297's policies. The only
rules on that path were the database's: nothing refused a missing landlord's PAN above the Rule 26C threshold, a lender's
PAN against §24(b) interest, a regime that is not one or a head payroll cannot give effect to (the screen offered only the six it
can, and nothing else checked); the three steps were not tied together; and the browser held the employee, client and firm ids it
sent.

WHAT THE DOOR DOES, each pinned here:

  * WHO AND WHAT come from the principal: nothing in the body names an employee, a client or a firm, and a body that tries to is
    ignored, so the row written is the caller's;
  * AN EMPLOYEE DECLARES AND NEVER VERIFIES: the verified columns and the verification flag are reset on every filing, and a
    declaration the CA has finished verifying is read-only (409);
  * THE STAFF DOOR'S VALIDATION applies, in the employee's own words (a 422 whose sentence the tab shows), and a refused
    declaration writes nothing;
  * THE LINES ARE REPLACED WHOLESALE, and the filing is ONE database call (`file_it_declaration`, migration 548, POST-A-340): the
    route holds no read-back and no put-back, because the function does the header, the lines and the removal in one transaction
    under a row lock and a failure inside it leaves everything as it was (proved against real Postgres, with two concurrent callers,
    by `test_548_..._pg.py`; the harness's twin of the function is held to the same refusals here). The route turns the function's
    three refusals into words: a verified declaration is a 409 that says it is read-only, a filing that could not take the row is a
    409 that says the declaration changed, an employee that is not the principal's is a 403;
  * ONLY the caller's own declaration is ever read or returned.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
import routers.portal_employee as portal_mod
import tests.e2e_harness as harness
from core.portal_auth import get_current_portal_employee
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
CLIENT, OTHER_CLIENT = "C1", "C2"
ME, COLLEAGUE = "E-me", "E-colleague"
FY = "2026-27"
ME_CTX = {
    "portal": True, "employee": True, "employee_id": ME, "client_id": CLIENT,
    "firm_id": FIRM, "name": "Me", "employee_code": "EMP-001",
    "email": "me@f1.test", "role": "PortalEmployee", "auth_user_id": "auth-me",
}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    audit: list = []
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(portal_mod, "log_event", lambda *a, **k: audit.append((a, k)))
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: dict(ME_CTX)
    db.audit = audit
    # The principal's employee exists in production, and the function refuses an employee that is not that firm's and that client's.
    db.seed("payroll_employees", {"id": ME, "firm_id": FIRM, "client_id": CLIENT, "name": "Me"})
    db.seed("payroll_employees", {"id": COLLEAGUE, "firm_id": FIRM, "client_id": CLIENT, "name": "Colleague"})
    return TestClient(app, raise_server_exceptions=False), db


def _body(**over):
    body = {"fy": FY, "regime": "old", "rent_paid_declared_paise": 0, "landlord_name": "", "landlord_address": "",
            "landlord_pan": "", "rent_is_metro": False, "lta_declared_paise": 0, "home_loan_interest_declared_paise": 0,
            "lender_name": "", "lender_pan": "", "other_income_declared_paise": 0, "house_property_loss_declared_paise": 0,
            "items": [{"section": "80C", "amount_declared_paise": 15_000_000}]}
    body.update(over)
    return body


def _put(client, **over):
    return client.put("/api/portal/employee/tax-declaration", json=_body(**over))


def _heads(db, employee=ME):
    return [r for r in db.rows("payroll_it_declarations") if r["employee_id"] == employee]


def _lines(db):
    return sorted((r["section"], r["amount_declared_paise"]) for r in db.rows("payroll_it_declaration_items"))


def _seed_declaration(db, *, employee=ME, firm=FIRM, client=CLIENT, verified=False, rent_verified=0, lines=(("80C", 5_000_000),)):
    head = db.seed("payroll_it_declarations", {
        "firm_id": firm, "client_id": client, "employee_id": employee, "fy": FY, "regime": "new", "status": "submitted",
        "rent_paid_declared_paise": 6_000_000, "rent_paid_verified_paise": rent_verified, "landlord_name": "Old landlord",
        "landlord_address": "", "landlord_pan": "ABCDE1234F", "rent_is_metro": True, "lta_declared_paise": 100_000,
        "lta_verified_paise": 50_000 if rent_verified else 0, "home_loan_interest_declared_paise": 0,
        "home_loan_interest_verified_paise": 0, "lender_name": "", "lender_pan": "", "other_income_declared_paise": 0,
        "house_property_loss_declared_paise": 0, "proofs_verified": verified,
        "verified_at": "2026-10-01T00:00:00+00:00" if verified else None, "verified_by": "u1" if verified else None,
        "submitted_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00"})
    for section, paise in lines:
        db.seed("payroll_it_declaration_items", {"firm_id": firm, "declaration_id": head["id"], "section": section, "label": "",
                                                 "amount_declared_paise": paise, "amount_verified_paise": paise // 2,
                                                 "status": "verified", "proof_reference": "", "proof_attachments": []})
    return head


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_with_nothing_filed_the_read_says_so(world):
    client, _ = world
    r = client.get("/api/portal/employee/tax-declaration", params={"financial_year": FY})
    assert r.status_code == 200 and r.json()["data"] == {"fy": FY, "declaration": None, "items": []}


def test_the_read_is_the_callers_own_declaration_and_its_lines_in_the_columns_the_form_shows(world):
    client, db = world
    # The others are seeded FIRST, so a read that forgot to scope by the employee or the firm would return theirs.
    _seed_declaration(db, employee=COLLEAGUE, lines=(("80C", 9_900_000),))
    _seed_declaration(db, employee=ME, firm=OTHER_FIRM, client=OTHER_CLIENT, lines=(("80C", 7_700_000),))
    mine = _seed_declaration(db, lines=(("80D-self", 2_500_000), ("80C", 5_000_000)))
    body = client.get("/api/portal/employee/tax-declaration", params={"financial_year": FY}).json()["data"]
    assert body["declaration"]["id"] == mine["id"] and body["declaration"]["landlord_name"] == "Old landlord"
    assert not ({"firm_id", "client_id", "employee_id", "rent_paid_verified_paise", "verified_by"} & set(body["declaration"]))
    assert [(i["section"], i["amount_declared_paise"]) for i in body["items"]] == [("80C", 5_000_000), ("80D-self", 2_500_000)]


def test_a_year_that_is_not_one_is_a_422(world):
    client, _ = world
    assert client.get("/api/portal/employee/tax-declaration", params={"financial_year": "2026-28"}).status_code == 422


# ── filing ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_filing_writes_the_callers_row_with_the_principals_ids_and_nothing_verified(world):
    client, db = world
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 15_000_000},
                            {"section": "80D-self", "amount_declared_paise": 2_500_000},
                            {"section": "80TTA", "amount_declared_paise": 0}])
    assert r.status_code == 200, r.text
    [head] = _heads(db)
    assert (head["firm_id"], head["client_id"], head["employee_id"], head["fy"]) == (FIRM, CLIENT, ME, FY)
    assert head["status"] == "submitted" and head["regime"] == "old" and head["proofs_verified"] is False
    assert head["rent_paid_verified_paise"] == head["lta_verified_paise"] == head["home_loan_interest_verified_paise"] == 0
    assert head["verified_at"] is None and head["verified_by"] is None and head["submitted_at"]
    assert _lines(db) == [("80C", 15_000_000), ("80D-self", 2_500_000)], "a head declared at nothing is not a line"
    assert all(i["status"] == "declared" and i["amount_verified_paise"] == 0 and i["firm_id"] == FIRM
               for i in db.rows("payroll_it_declaration_items"))
    assert r.json()["data"]["declaration"]["id"] == head["id"] and len(r.json()["data"]["items"]) == 2


def test_a_body_that_names_somebody_else_is_ignored_and_the_row_is_the_callers(world):
    client, db = world
    r = client.put("/api/portal/employee/tax-declaration", json={
        **_body(), "employee_id": COLLEAGUE, "client_id": OTHER_CLIENT, "firm_id": OTHER_FIRM,
        "proofs_verified": True, "rent_paid_verified_paise": 999, "status": "verified"})
    assert r.status_code == 200, r.text
    [head] = db.rows("payroll_it_declarations")
    assert (head["employee_id"], head["firm_id"], head["client_id"]) == (ME, FIRM, CLIENT)
    assert head["proofs_verified"] is False and head["rent_paid_verified_paise"] == 0 and head["status"] == "submitted"


def test_re_filing_replaces_the_lines_wholesale_and_resets_what_the_ca_had_checked(world):
    client, db = world
    _seed_declaration(db, rent_verified=4_000_000, lines=(("80C", 5_000_000), ("80D-parents", 1_000_000)))
    _seed_declaration(db, employee=COLLEAGUE, lines=(("80C", 9_900_000),))
    r = _put(client, items=[{"section": "80CCD(1B)", "amount_declared_paise": 5_000_000}])
    assert r.status_code == 200, r.text
    [head] = _heads(db)
    assert head["rent_paid_verified_paise"] == 0 and head["lta_verified_paise"] == 0 and head["status"] == "submitted"
    mine = [(i["section"], i["amount_declared_paise"]) for i in db.rows("payroll_it_declaration_items")
            if i["declaration_id"] == head["id"]]
    assert mine == [("80CCD(1B)", 5_000_000)], "the withdrawn investments are gone, not merged"
    assert ("80C", 9_900_000) in _lines(db), "the colleague's lines are untouched"
    assert len(db.rows("payroll_it_declarations")) == 2


def test_one_declaration_per_employee_per_year_is_an_upsert(world):
    client, db = world
    _put(client); _put(client, regime="new")
    assert len(_heads(db)) == 1 and _heads(db)[0]["regime"] == "new"


def test_a_declaration_the_ca_finished_verifying_is_read_only_and_nothing_changes(world):
    client, db = world
    _seed_declaration(db, verified=True, rent_verified=4_000_000)
    before = ([dict(r) for r in db.rows("payroll_it_declarations")], [dict(r) for r in db.rows("payroll_it_declaration_items")])
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 1}])
    assert r.status_code == 409 and "read-only" in r.json()["detail"]
    assert ([dict(x) for x in db.rows("payroll_it_declarations")], [dict(x) for x in db.rows("payroll_it_declaration_items")]) == before
    assert db.audit == []


def test_the_filing_is_in_the_audit_log_by_the_employees_sign_in_id_and_email(world):
    """`audit_log.actor_id` takes the Supabase sign-in id (the same id the trigger writes), never the employee's row id."""
    client, db = world
    _put(client)
    [(args, kwargs)] = db.audit
    assert args[0] == FIRM and args[1] == "payroll_it_declaration" and args[3] == "employee_declare"
    assert kwargs["actor_id"] == "auth-me" and kwargs["actor_id"] != ME
    assert kwargs["actor_email"] == "me@f1.test" and kwargs["metadata"]["employee_id"] == ME


# ── refusals, each writing nothing ───────────────────────────────────────────────────────────────────────────────────

REFUSALS = [
    ("rent over the Rule 26C threshold with no landlord PAN", dict(rent_paid_declared_paise=15_000_000, landlord_name="L"), "landlord's PAN"),
    ("rent with no landlord named", dict(rent_paid_declared_paise=5_000_000), "landlord's name"),
    ("home-loan interest with no lender PAN", dict(home_loan_interest_declared_paise=100_000_00), "lender's PAN"),
    ("a head payroll cannot give effect to", dict(items=[{"section": "80GG", "amount_declared_paise": 100}]), "80GG"),
    ("a regime that is not one", dict(regime="maybe"), "regime"),
    ("a head declared twice", dict(items=[{"section": "80C", "amount_declared_paise": 1}, {"section": "80C", "amount_declared_paise": 2}]),
     "declared twice"),
]


@pytest.mark.parametrize("why, over, words", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_what_payroll_cannot_give_effect_to_is_refused_in_words_and_writes_nothing(world, why, over, words):
    client, db = world
    r = _put(client, **over)
    assert r.status_code == 422, (why, r.text)
    assert words in str(r.json()["detail"]), (why, r.json())
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == []


@pytest.mark.parametrize("over", [dict(landlord_pan="NOTAPAN"), dict(lender_pan="123"), dict(rent_paid_declared_paise=-1),
                                  dict(lta_declared_paise=-5), dict(fy="2026-28"), dict(landlord_name="x" * 201),
                                  dict(items=[{"section": "80C", "amount_declared_paise": -1}])])
def test_a_shape_the_model_refuses_is_a_422_and_writes_nothing(world, over):
    client, db = world
    assert _put(client, **over).status_code == 422
    assert db.rows("payroll_it_declarations") == []


def test_a_pan_is_upper_cased_and_a_blank_one_stays_blank(world):
    client, db = world
    _put(client, rent_paid_declared_paise=15_000_000, landlord_name="L", landlord_pan="abcde1234f")
    assert _heads(db)[0]["landlord_pan"] == "ABCDE1234F"


# ── the filing is one call, and its refusals are turned into words ─────────────────────────────────────────────────────

def _watch_the_function(monkeypatch):
    """Record the arguments the route hands `file_it_declaration`, and still run the harness's twin of it."""
    seen: list = []
    real = harness._Rpc.execute

    def execute(rpc):
        if rpc.fn == "file_it_declaration":
            seen.append(rpc.params)
        return real(rpc)

    monkeypatch.setattr(harness._Rpc, "execute", execute)
    return seen


def test_the_route_files_with_one_call_that_refuses_a_verified_declaration_and_leaves_out_a_head_declared_at_nothing(world, monkeypatch):
    client, _ = world
    seen = _watch_the_function(monkeypatch)
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 15_000_000}, {"section": "80TTA", "amount_declared_paise": 0}])
    assert r.status_code == 200, r.text
    [params] = seen
    assert params["p_refuse_verified"] is True, "the employee's door must refuse a verified declaration"
    assert [i["section"] for i in params["p_items"]] == ["80C"]
    assert (params["p_declaration"]["firm_id"], params["p_declaration"]["client_id"], params["p_declaration"]["employee_id"]) == (FIRM, CLIENT, ME)


def test_every_figure_the_employee_typed_reaches_the_function_under_its_own_key_and_the_audit_row_counts_the_lines(world, monkeypatch):
    """Every box carries its own non-zero value (the others of this file use nothing), so a figure under another box's key, a negated
    flag or a dropped name is a different payload. The audit row says how many lines were filed, and a head at nothing is not one."""
    client, db = world
    seen = _watch_the_function(monkeypatch)
    r = _put(client, regime="old", rent_paid_declared_paise=1_200_000, landlord_name="Landlord", landlord_address="12 Rose Street",
             landlord_pan="ABCDE1234F", rent_is_metro=True, lta_declared_paise=2_300_000, home_loan_interest_declared_paise=3_400_000,
             lender_name="Bank", lender_pan="ABCDE1234G", other_income_declared_paise=4_500_000,
             house_property_loss_declared_paise=5_600_000,
             items=[{"section": "80C", "amount_declared_paise": 6_700_000}, {"section": "80D-self", "amount_declared_paise": 800_000},
                    {"section": "80TTA", "amount_declared_paise": 0}])
    assert r.status_code == 200, r.text
    [params] = seen
    assert params["p_declaration"] == {
        "firm_id": FIRM, "client_id": CLIENT, "employee_id": ME, "fy": FY, "regime": "old",
        "rent_paid_declared_paise": 1_200_000, "landlord_name": "Landlord", "landlord_address": "12 Rose Street",
        "landlord_pan": "ABCDE1234F", "rent_is_metro": True,
        "lta_declared_paise": 2_300_000,
        "home_loan_interest_declared_paise": 3_400_000, "lender_name": "Bank", "lender_pan": "ABCDE1234G",
        "other_income_declared_paise": 4_500_000,
        "house_property_loss_declared_paise": 5_600_000,
    }
    assert params["p_items"] == [
        {"section": "80C", "label": "", "amount_declared_paise": 6_700_000, "proof_reference": "", "proof_attachments": []},
        {"section": "80D-self", "label": "", "amount_declared_paise": 800_000, "proof_reference": "", "proof_attachments": []},
    ]
    [(_, kwargs)] = db.audit
    assert kwargs["new_data"] == {"fy": FY, "regime": "old", "lines": 2}
    assert kwargs["metadata"] == {"employee_id": ME, "principal": "PortalEmployee"}


def test_the_employee_door_files_with_the_server_client_and_never_the_requests(world, monkeypatch):
    """The function is executable by the service role alone: the door builds the server's client itself, and the request's own client
    is wired to raise."""
    client, db = world
    import core.supabase_client as sc
    called = []
    monkeypatch.setattr(sc, "get_supabase", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the request's own client was used")))
    monkeypatch.setattr(sc, "get_service_supabase", lambda: (called.append(1), db)[1])
    r = _put(client)
    assert r.status_code == 200, r.text
    assert called, "the door never asked for the server's client"


def test_a_ca_who_finishes_verifying_before_the_function_takes_the_row_wins(world, monkeypatch):
    """The refusal is decided INSIDE the function, in the transaction that would have changed the declaration, so a verification
    that lands between this request's start and its write stands and the filing changes nothing."""
    client, db = world
    head = _seed_declaration(db, lines=(("80C", 5_000_000),))
    before = ([dict(r) for r in db.rows("payroll_it_declaration_items")], dict(head))
    real = harness._Rpc.execute

    def verify_first(rpc):
        if rpc.fn == "file_it_declaration":
            db.rows("payroll_it_declarations")[0].update(proofs_verified=True, rent_paid_verified_paise=4_000_000, verified_by="u1")
        return real(rpc)

    monkeypatch.setattr(harness._Rpc, "execute", verify_first)
    r = _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}])
    assert r.status_code == 409 and "read-only" in r.json()["detail"]
    row = db.rows("payroll_it_declarations")[0]
    assert row["proofs_verified"] is True and row["rent_paid_verified_paise"] == 4_000_000, "the verification must stand"
    assert row["regime"] == head["regime"] and row["landlord_name"] == "Old landlord", "and nothing of the filing was written"
    assert [dict(r) for r in db.rows("payroll_it_declaration_items")] == before[0]
    assert db.audit == []


def _function_raises(monkeypatch, code, message):
    from postgrest.exceptions import APIError

    def boom(rpc):
        raise APIError({"message": message, "code": code, "hint": None, "details": None})

    monkeypatch.setattr(harness._Rpc, "_fn_file_it_declaration", boom)


def test_a_filing_that_could_not_take_the_row_is_a_409_in_words_and_writes_nothing(world, monkeypatch):
    client, db = world
    _function_raises(monkeypatch, "40001", "file_it_declaration: could not take the declaration for employee x and year 2026-27")
    r = _put(client)
    assert r.status_code == 409 and "changed while you were saving" in r.json()["detail"]
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == [] and db.audit == []


def test_an_employee_that_is_not_the_principals_is_a_403_and_writes_nothing(world, monkeypatch):
    client, db = world
    db._tables["payroll_employees"] = []           # the function proves the employee is this firm's and this client's
    r = _put(client)
    assert r.status_code == 403
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == [] and db.audit == []


def test_any_other_failure_of_the_function_reaches_the_caller_as_a_failure_and_is_not_audited(world, monkeypatch):
    client, db = world
    _function_raises(monkeypatch, "XX000", "something the database did not expect")
    r = _put(client)
    assert r.status_code == 500
    assert db.rows("payroll_it_declarations") == [] and db.audit == []


def test_the_twin_refuses_what_the_function_refuses_and_writes_nothing_when_it_does():
    """The harness's twin is what every door test runs against, so it is held to the function's own refusals: a twin that was
    kinder than the database would pass a door test the database fails."""
    from postgrest.exceptions import APIError
    db = FakeDB()
    db.seed("payroll_employees", {"id": ME, "firm_id": FIRM, "client_id": CLIENT})

    def call(decl, items, refuse=False):
        return db.rpc("file_it_declaration", {"p_declaration": decl, "p_items": items, "p_refuse_verified": refuse}).execute().data

    good = {"firm_id": FIRM, "client_id": CLIENT, "employee_id": ME, "fy": FY, "regime": "new"}
    for bad, code in (({**good, "fy": None}, "22023"), ({**good, "employee_id": "E-other"}, "42501"),
                      ({**good, "client_id": OTHER_CLIENT}, "42501"), ({**good, "firm_id": OTHER_FIRM}, "42501")):
        with pytest.raises(APIError) as e:
            call(bad, [])
        assert e.value.code == code
    with pytest.raises(APIError) as e:
        call(good, "not a list")
    assert e.value.code == "22023"
    with pytest.raises(APIError) as e:
        call(good, [{"section": "80C", "amount_declared_paise": 1}, {"label": "no section"}])
    assert e.value.code == "23502"
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == [], "a refusal leaves nothing behind"
    declaration_id = call(good, [{"section": "80C", "amount_declared_paise": 100}])
    db.rows("payroll_it_declarations")[0].update(proofs_verified=True)
    with pytest.raises(APIError) as e:
        call(good, [{"section": "80C", "amount_declared_paise": 1}], refuse=True)
    assert e.value.code == "P0001" and e.value.message.startswith("declaration_verified:")
    assert call(good, [{"section": "80D-self", "amount_declared_paise": 2}], refuse=False) == declaration_id, "the staff door replaces it"
    assert db.rows("payroll_it_declarations")[0]["proofs_verified"] is False
    assert [(r["section"], r["amount_declared_paise"]) for r in db.rows("payroll_it_declaration_items")] == [("80D-self", 2)]


# ── a refusal names the box ──────────────────────────────────────────────────────────────────────────────────────────

def _messages(r):
    return [d["msg"] for d in r.json()["detail"]]


def test_two_bad_pans_are_two_sentences_each_naming_its_own_box(world):
    client, _ = world
    r = _put(client, landlord_pan="bad", lender_pan="12")
    assert r.status_code == 422
    assert _messages(r) == ["Landlord's PAN must be in the form AAAAA9999A.", "Lender's PAN must be in the form AAAAA9999A."]


def test_a_name_or_address_that_is_too_long_names_which_one(world):
    client, db = world
    r = _put(client, landlord_name="x" * 201, landlord_address="y" * 501, lender_name="z" * 201)
    assert r.status_code == 422
    assert sorted(_messages(r)) == sorted([
        "The landlord's name must be at most 200 characters.", "The landlord's address must be at most 500 characters.",
        "The lender's name must be at most 200 characters."])
    assert db.rows("payroll_it_declarations") == []


def test_a_name_at_the_limit_is_accepted(world):
    client, db = world
    assert _put(client, landlord_name="x" * 200, landlord_address="y" * 500).status_code == 200


def test_a_principal_with_no_client_is_refused_before_anything_is_written(monkeypatch, world):
    _, db = world
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: {**ME_CTX, "client_id": None}
    r = TestClient(app, raise_server_exceptions=False).put("/api/portal/employee/tax-declaration", json=_body())
    assert r.status_code == 403 and db.rows("payroll_it_declarations") == []
