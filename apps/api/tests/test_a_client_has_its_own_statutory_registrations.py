"""
A statutory return is filed BY an establishment, and we held no number for one.

WHAT WAS MISSING
    Three outputs in domain/payroll are finished and correct and could not be
    filed, because each is a return by an establishment identified by a
    registration this database had no column for:

        ecr.py       the EPFO Electronic Challan cum Return
        esic.py      the ESIC monthly contribution return
        form24q.py   Form 24Q's Annexure I

    A grep across the repo found exactly two `tan` columns — customers.tan and
    form_26as_records.deductor_tan — and neither is the client's OWN TAN as an
    employer. No EPF establishment code, no ESIC employer code, no PT
    registration, no LIN, anywhere.

    routers/tds.py still shows the shape of the hole: Compute24QRequest takes
    `tan`, `deductor_name`, `deductor_pan` and `deductor_address` in the
    request BODY, because there was nowhere to read them from. A CA who had
    just produced a quarter's deductee rows from the books then retyped the
    deductor block by hand, every quarter, for every client.

WHAT A MISSING ONE DOES IS NOT THE SAME EVERYWHERE, AND THAT IS THE POINT
    24Q  the TAN is IN the return, so a missing one is a PROBLEM and clears
         `ready`. A 24Q with a blank TAN is not a return with a small omission,
         it is a return filed against no account.
    ECR  the establishment is chosen by the portal login at upload; the file is
         member lines only. A missing code is reported BESIDE the file and must
         never reach ecr.problems, which would flip is_filable and withhold a
         correct return over reference data.
    ESIC the same.

NEGATIVE CONTROL
    Revert the four call sites in routers/payroll.py and delete
    domain/payroll/identity.py, and every test below fails: the endpoints 404,
    the deductor block is absent from /24q-source, and the PT gap never
    appears on a run.
"""
from __future__ import annotations

import pytest

from domain.payroll import identity as ident
import routers.payroll as pr


# ── TAN is checked; the others are not, and that asymmetry is deliberate ─────

def test_a_tan_is_uppercased_and_spaces_removed():
    assert ident.normalise_tan("  delm 12345 f ") == "DELM12345F"


def test_a_blank_tan_clears_rather_than_failing():
    """"This client has no TAN" is a real answer. Refusing it would leave a CA
    unable to correct a TAN they had entered by mistake."""
    assert ident.normalise_tan("") is None
    assert ident.normalise_tan(None) is None
    assert ident.normalise_tan("   ") is None


@pytest.mark.parametrize("bad", [
    "DELM12345",       # nine characters
    "DELM123456F",     # six digits
    "DEL1M2345F",      # a digit inside the letter block
    "DELM12345F1",     # eleven characters
    "AAAAA1234A",      # a PAN, which is the wrong identifier entirely
])
def test_a_string_that_is_not_a_tan_is_refused(bad):
    """Ten plausible characters that are not a TAN file the quarter against no
    account, and TRACES is where that is discovered."""
    with pytest.raises(ident.IdentityError):
        ident.normalise_tan(bad)


def test_the_other_registrations_are_stored_as_given():
    """No pattern is invented for them. An EPF establishment code, an ESIC
    employer code, a state PT number and a LIN each vary by region, vintage and
    issuing office; a regex written from memory would refuse valid
    registrations rather than catch typos."""
    assert ident.normalise_code(" mhban0012345000 ") == "MHBAN0012345000"
    assert ident.normalise_code("27/AB-1/PT") == "27/AB-1/PT"      # punctuation survives
    assert ident.normalise_code("  ") is None


# ── the ECR and ESIC gaps stay OUT of the problems that withhold a file ──────

def test_a_missing_epf_code_is_reported_but_does_not_withhold_the_ecr():
    gaps = ident.ecr_gaps({})
    assert len(gaps) == 1
    assert gaps[0].field == "epf_establishment_code"
    assert "portal login" in gaps[0].note


def test_a_recorded_epf_code_leaves_no_gap():
    assert ident.ecr_gaps({"epf_establishment_code": "MHBAN0012345000"}) == []


def test_a_missing_esic_code_is_reported_the_same_way():
    gaps = ident.esic_gaps(None)
    assert [g.field for g in gaps] == ["esic_employer_code"]


def test_the_ecr_endpoint_does_not_fold_identity_gaps_into_problems():
    """The assertion the wording alone cannot make. build_ecr's is_filable is
    `bool(members) and not problems`, so an identity gap appended to problems
    would silently withhold a correct return."""
    import inspect
    src = inspect.getsource(pr.run_ecr)
    assert "identity_gaps" in src
    assert "ecr.problems.append" not in src
    assert "problems.extend(estab_gaps)" not in src


# ── the 24Q deductor block, where a missing TAN IS the return's problem ──────

_CLIENT = {
    "client_name": "Acme Traders",
    "legal_name": "Acme Traders Private Limited",
    "pan": "AAACA1234E",
    "address_line1": "12 Nariman Point",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400021",
}


def test_the_deductor_block_is_assembled_so_nobody_retypes_it():
    block, problems = ident.deductor_block({"tan": "MUMA12345B"}, _CLIENT)
    assert problems == []
    assert block == {
        "tan": "MUMA12345B",
        "deductor_name": "Acme Traders Private Limited",
        "deductor_pan": "AAACA1234E",
        "deductor_address": "12 Nariman Point, Mumbai, Maharashtra, 400021",
    }


def test_the_legal_name_wins_over_the_working_name():
    """A return carries the name on the registration, not the name the firm
    files the client under."""
    block, _ = ident.deductor_block({"tan": "MUMA12345B"}, _CLIENT)
    assert block["deductor_name"] == "Acme Traders Private Limited"


def test_the_working_name_is_used_when_there_is_no_legal_name():
    block, problems = ident.deductor_block(
        {"tan": "MUMA12345B"}, {**_CLIENT, "legal_name": None})
    assert block["deductor_name"] == "Acme Traders"
    assert problems == []


def test_a_missing_tan_is_a_problem_on_the_24q():
    _, problems = ident.deductor_block({}, _CLIENT)
    assert len(problems) == 1
    assert "TAN" in problems[0] and "s.203A" in problems[0]


def test_a_missing_address_is_a_problem_too():
    _, problems = ident.deductor_block(
        {"tan": "MUMA12345B"},
        {"client_name": "Acme", "pan": "AAACA1234E"})
    assert any("address" in p for p in problems)


def test_the_24q_assembly_pushes_those_problems_onto_the_source():
    """Form24QSource.is_ready is `bool(deductees) and not problems`, so a
    missing TAN must clear `ready` rather than sit in a field beside it.

    Asserted on the BEHAVIOUR of the assembly rather than on the text of one
    endpoint. It used to read the endpoint's source for the line that does it —
    which broke the moment the assembly moved into a helper so the JSON source
    and the CSV working paper could share it, and which would not have noticed
    if the line had been kept and neutered.
    """
    src, _months, deductor = pr._assemble_24q_source(
        _Db24Q(), {"firm_id": "F", "id": "u"}, "CLI", "2026-27", "Q1")
    assert any("TAN" in p and "s.203A" in p for p in src.problems), (
        "a client with no TAN recorded must make the quarter NOT ready")
    assert src.is_ready is False
    assert deductor is not None


class _Db24Q:
    """The smallest database that gets _assemble_24q_source to the deductor
    block: a client with no statutory identity, and no payroll runs."""

    class _Q:
        def __init__(self, table): self._table = table
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def in_(self, *_a, **_k): return self
        def maybe_single(self): return self

        def execute(self):
            class R:
                pass
            r = R()
            if self._table == "clients":
                # maybe_single() -> a dict; the plain path -> a list.
                r.data = {"client_name": "Acme", "pan": "AAACA1234E"}
            else:
                r.data = []
            return r

    def table(self, name): return self._Q(name)


# ── professional tax: one registration per state, reported once per state ────

def test_a_state_with_no_ptrc_is_a_gap():
    gaps = ident.pt_registration_gaps({"KA"}, [])
    assert len(gaps) == 1
    assert "KA" in gaps[0] and "PTRC" in gaps[0]


def test_a_ptec_does_not_satisfy_a_ptrc():
    """The Enrolment Certificate is the entity's own levy on itself. Only the
    Registration Certificate authorises deducting from employees and
    depositing it, which is what the payslip has already done."""
    gaps = ident.pt_registration_gaps(
        {"MH"}, [{"state": "MH", "ptec_number": "PTEC-1", "ptrc_number": None}])
    assert len(gaps) == 1


def test_a_recorded_ptrc_closes_the_gap():
    assert ident.pt_registration_gaps(
        {"MH"}, [{"state": "MH", "ptrc_number": "27123456789P"}]) == []


def test_each_state_is_named_once_however_many_employees_work_there():
    """Reported per STATE, not per employee: the registration is a fact about
    the employer there, and forty repetitions would bury every other gap."""
    gaps = ident.pt_registration_gaps({"KA", "MH", "TN"}, [])
    assert len(gaps) == 3
    assert sorted(gaps) == gaps          # deterministic, alphabetical by state


def test_only_the_unregistered_states_are_named():
    gaps = ident.pt_registration_gaps(
        {"KA", "MH"}, [{"state": "mh", "ptrc_number": "27123456789P"}])
    assert len(gaps) == 1 and "KA" in gaps[0]


def test_the_run_collects_pt_registration_gaps_into_statutory_gaps():
    """One list, not a third one. A screen with three ideas of "incomplete"
    teaches nobody to read any of them."""
    import inspect
    src = inspect.getsource(pr.create_run)
    assert "identity_domain.pt_registration_gaps" in src
    assert "statutory_gaps.extend(identity_domain.pt_registration_gaps(" in src


# ── the endpoints, end to end in mock mode ───────────────────────────────────
# Shallow on purpose, the way test_new_payroll_endpoints_are_callable.py is:
# their job is to execute the handler and let a TypeError, a NameError or a bad
# argument surface. The arithmetic is tested above.

CLIENT = "11111111-1111-1111-1111-111111111111"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "role": "Partner"}


@pytest.fixture()
def mock_mode(monkeypatch):
    monkeypatch.setattr(pr, "_db", lambda: None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    pr._MOCK_IDENTITY.clear()
    pr._MOCK_PT_REGISTRATIONS.clear()
    yield
    pr._MOCK_IDENTITY.clear()
    pr._MOCK_PT_REGISTRATIONS.clear()


def test_an_unrecorded_client_reads_back_empty_rather_than_absent(mock_mode):
    res = pr.get_statutory_identity(client_id=CLIENT, current_user=USER)
    assert res["success"]
    assert res["data"]["identity"] == {
        "tan": None, "epf_establishment_code": None,
        "esic_employer_code": None, "lin": None, "note": None}
    assert res["data"]["pt_registrations"] == []


def test_the_screen_reads_its_own_field_list_from_the_api(mock_mode):
    """The form and the API cannot drift into disagreeing about which
    registrations exist if only one of them holds the list."""
    fields = pr.get_statutory_identity(client_id=CLIENT, current_user=USER)["data"]["fields"]
    assert [f["name"] for f in fields] == [
        "tan", "epf_establishment_code", "esic_employer_code", "lin"]
    assert all(f["label"] and f["used_for"] for f in fields)


def test_a_recorded_tan_reads_back(mock_mode):
    from models.payroll import StatutoryIdentityIn
    pr.put_statutory_identity(
        StatutoryIdentityIn(client_id=CLIENT, tan="muma12345b"), USER)
    got = pr.get_statutory_identity(client_id=CLIENT, current_user=USER)["data"]
    assert got["identity"]["tan"] == "MUMA12345B"


def test_editing_one_field_does_not_clear_the_others(mock_mode):
    """PATCH-shaped. A form that edits the EPF code must not silently blank a
    TAN it never showed — which is what a full-object PUT would do."""
    from models.payroll import StatutoryIdentityIn
    pr.put_statutory_identity(
        StatutoryIdentityIn(client_id=CLIENT, tan="MUMA12345B"), USER)
    pr.put_statutory_identity(
        StatutoryIdentityIn(client_id=CLIENT, epf_establishment_code="MHBAN0012345000"), USER)
    got = pr.get_statutory_identity(client_id=CLIENT, current_user=USER)["data"]["identity"]
    assert got["tan"] == "MUMA12345B"
    assert got["epf_establishment_code"] == "MHBAN0012345000"


def test_an_explicit_blank_clears_the_field(mock_mode):
    """Different from not sending it: this is a CA saying the client has none."""
    from models.payroll import StatutoryIdentityIn
    pr.put_statutory_identity(StatutoryIdentityIn(client_id=CLIENT, tan="MUMA12345B"), USER)
    pr.put_statutory_identity(StatutoryIdentityIn(client_id=CLIENT, tan=""), USER)
    assert pr.get_statutory_identity(
        client_id=CLIENT, current_user=USER)["data"]["identity"]["tan"] is None


def test_a_bad_tan_is_a_422_and_not_a_stored_string(mock_mode):
    from fastapi import HTTPException
    from models.payroll import StatutoryIdentityIn
    with pytest.raises(HTTPException) as e:
        pr.put_statutory_identity(
            StatutoryIdentityIn(client_id=CLIENT, tan="AAAAA1234A"), USER)
    assert e.value.status_code == 422
    assert pr.get_statutory_identity(
        client_id=CLIENT, current_user=USER)["data"]["identity"]["tan"] is None


def test_an_empty_body_is_refused_rather_than_writing_nothing(mock_mode):
    from fastapi import HTTPException
    from models.payroll import StatutoryIdentityIn
    with pytest.raises(HTTPException) as e:
        pr.put_statutory_identity(StatutoryIdentityIn(client_id=CLIENT), USER)
    assert e.value.status_code == 422


def test_pt_registrations_are_per_state(mock_mode):
    from models.payroll import PTRegistrationIn
    pr.put_pt_registration(
        PTRegistrationIn(client_id=CLIENT, state="MH", ptrc_number="27123456789P"), USER)
    pr.put_pt_registration(
        PTRegistrationIn(client_id=CLIENT, state="ka", ptrc_number="KA-PTRC-9"), USER)
    rows = pr.get_statutory_identity(
        client_id=CLIENT, current_user=USER)["data"]["pt_registrations"]
    assert sorted(r["state"] for r in rows) == ["KA", "MH"]


def test_a_state_code_that_is_not_two_letters_is_refused():
    from pydantic import ValidationError
    from models.payroll import PTRegistrationIn
    with pytest.raises(ValidationError):
        PTRegistrationIn(client_id=CLIENT, state="Maharashtra", ptrc_number="x")


def test_deleting_a_registration_puts_the_state_back_into_the_gaps(mock_mode):
    from models.payroll import PTRegistrationIn
    pr.put_pt_registration(
        PTRegistrationIn(client_id=CLIENT, state="MH", ptrc_number="27123456789P"), USER)
    _, regs = pr._read_statutory_identity(None, "f1", CLIENT)
    assert ident.pt_registration_gaps({"MH"}, regs) == []

    pr.delete_pt_registration(client_id=CLIENT, state="MH", current_user=USER)
    _, regs = pr._read_statutory_identity(None, "f1", CLIENT)
    assert len(ident.pt_registration_gaps({"MH"}, regs)) == 1
