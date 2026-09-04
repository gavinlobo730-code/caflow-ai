"""
The exception index: which employees will make a statutory output fail, before
it is built.

WHAT WAS WRONG

Nothing was wrong with the refusals. Every statutory file payroll produces
already refuses the rows it cannot honestly carry, and each refusal is correct:

    the ECR      refuses a member with no UAN (UAN-based format)
    the ESIC     return refuses an employee with no IP number
    Form 24Q     refuses a deductee with no valid PAN — §206AA, because a row
                 declaring tax at slab rates against no PAN declares a SHORT
                 deduction and §201(1) puts that on the deductor
    §192         withholds on the general ladder with no date of birth on file,
                 which over-deducts anyone sixty or over on the old regime

What was wrong is WHEN a CA finds out. Every one of those refusals lands at
file-build time — on the 7th, trying to file, with the run already finalised and
the journal already posted. The information was on the employee master the whole
time and nothing asked.

NEGATIVE CONTROLS
    Report the date-of-birth gap for everyone, not only the old regime, and
    test_a_new_regime_employee_is_not_asked_for_a_date_of_birth fails.
    Count exceptions rather than employees in the summary and
    test_the_summary_counts_people_not_rows fails.
    Include resigned employees and
    test_a_leaver_is_not_an_exception fails.
    Drop the enablement filter and
    test_a_client_payroll_is_off_for_contributes_nobody fails.
"""
from __future__ import annotations

import pytest

from domain.payroll import exceptions as exc


def _emp(**kw) -> dict:
    """An employee with NOTHING missing — every gap must be opted into."""
    base = {
        "id": "E1", "client_id": "CLI", "name": "Asha Rao",
        "pan": "ABCPA1234A", "uan": "100200300400", "esi_number": "3100123456",
        "date_of_birth": "1985-04-03",
        "bank_account_no": "12345678", "bank_ifsc": "HDFC0001234",
        "pf_applicable": True, "esi_applicable": True,
        "pt_applicable": True, "pt_state": "MH", "status": "active",
    }
    base.update(kw)
    return base


def _kinds(emp: dict, **kw) -> set:
    return {e["kind"] for e in exc.for_employee(emp, fy="2026-27", **kw)}


def test_a_complete_employee_has_no_exceptions():
    """The fixture must be clean or every test below passes vacuously."""
    assert exc.for_employee(_emp(), fy="2026-27", old_regime=True) == []


def test_no_uan_blocks_the_ecr():
    out = exc.for_employee(_emp(uan=""), fy="2026-27")
    assert len(out) == 1
    assert out[0]["kind"] == "uan" and out[0]["blocks"] == "EPFO ECR"


def test_a_uan_that_is_not_twelve_digits_blocks_it_too():
    """The ECR checks this at file build, by which time the round trip is lost."""
    assert "uan" in _kinds(_emp(uan="12345"))


def test_an_employee_outside_pf_is_not_asked_for_a_uan():
    """They are not on the ECR at all, so a UAN blocks nothing for them."""
    assert "uan" not in _kinds(_emp(uan="", pf_applicable=False))


def test_no_esic_ip_blocks_the_esic_return():
    out = exc.for_employee(_emp(esi_number=""), fy="2026-27")
    assert out[0]["kind"] == "esic_ip"


def test_an_employee_outside_esi_is_not_asked_for_an_ip_number():
    assert "esic_ip" not in _kinds(_emp(esi_number="", esi_applicable=False))


def test_no_valid_pan_blocks_the_24q_and_says_why():
    """The note has to carry §206AA, because "missing PAN" reads as paperwork
    and a short deduction under §201(1) is not paperwork."""
    out = exc.for_employee(_emp(pan=""), fy="2026-27")
    assert out[0]["kind"] == "pan" and out[0]["blocks"] == "Form 24Q"
    assert "206AA" in out[0]["note"] and "201(1)" in out[0]["note"]
    assert "pan" in _kinds(_emp(pan="NOTAPAN"))


def test_an_old_regime_employee_with_no_date_of_birth_is_reported():
    out = exc.for_employee(_emp(date_of_birth=None), fy="2026-27", old_regime=True)
    assert out[0]["kind"] == "date_of_birth"
    assert "over-deducted" in out[0]["note"]


def test_a_new_regime_employee_is_not_asked_for_a_date_of_birth():
    """§115BAC(1A) has ONE ladder for every individual regardless of age, and
    payroll withholds on the new regime by default. Reporting this for everyone
    would put a line against most of the roster that changes nothing."""
    assert "date_of_birth" not in _kinds(_emp(date_of_birth=None), old_regime=False)


def test_no_bank_details_blocks_the_payment():
    assert "bank" in _kinds(_emp(bank_account_no=""))
    assert "bank" in _kinds(_emp(bank_ifsc="NOPE"))
    assert "bank" in _kinds(_emp(bank_ifsc="HDFC1001234")), "the 5th char must be 0"


def test_an_unmodelled_pt_state_is_reported_with_the_domain_s_own_words():
    """The note comes from professional_tax.classify_state, not from a second
    copy of the same sentence here."""
    out = exc.for_employee(_emp(pt_state="GJ"), fy="2026-27")
    assert out[0]["kind"] == "pt_state"
    assert out[0]["note"]


def test_a_modelled_pt_state_is_not_a_gap():
    assert "pt_state" not in _kinds(_emp(pt_state="MH"))


def test_an_employee_outside_pt_is_not_asked_for_a_state():
    assert "pt_state" not in _kinds(_emp(pt_state="GJ", pt_applicable=False))


def test_the_summary_is_per_kind_across_the_roster():
    rows = (exc.for_employee(_emp(pan="", uan=""), fy="2026-27")
            + exc.for_employee(_emp(id="E2", name="Ravi", pan=""), fy="2026-27"))
    assert exc.summarise(rows) == {"pan": 2, "uan": 1}


def test_the_summary_counts_people_not_rows():
    """One person is ONE person to chase, however many times they appear.

    for_employee yields at most one row per kind, so this cannot happen today —
    the dedupe is defensive. It is asserted anyway because the failure it
    prevents is silent: a roster that looks twice as bad as it is, which is
    exactly the kind of number somebody escalates on.
    """
    one = exc.for_employee(_emp(pan=""), fy="2026-27")
    assert exc.summarise(one + one) == {"pan": 1}, (
        "the same employee counted twice would overstate the roster")


def test_every_exception_names_what_it_blocks():
    """"Missing UAN" is a shrug; "this employee cannot be on the ECR" is a
    deadline."""
    rows = exc.for_employee(
        _emp(pan="", uan="", esi_number="", bank_ifsc="", pt_state="GJ",
             date_of_birth=None),
        fy="2026-27", old_regime=True)
    assert len(rows) == 6
    assert all(r["blocks"] and r["note"] and r["employee"] for r in rows)
    assert {r["kind"] for r in rows} == set(exc.KINDS)


# ─── the endpoint, on the real path ─────────────────────────────────────────

import routers.payroll as payroll_mod  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-EXC"
USER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI-ON", "firm_id": FIRM, "client_name": "Acme Pvt Ltd",
                       "financial_year_start": "2026-04-01"})
    d.seed("clients", {"id": "CLI-OFF", "firm_id": FIRM, "client_name": "Beta LLP",
                       "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "s-1", "firm_id": FIRM,
                                       "client_id": "CLI-ON", "payroll_enabled": True})
    d.seed("client_payroll_settings", {"id": "s-2", "firm_id": FIRM,
                                       "client_id": "CLI-OFF", "payroll_enabled": False})
    return d


def _index(fy="2026-27"):
    return payroll_mod.payroll_employee_exceptions(
        financial_year=fy, current_user=USER)["data"]


def test_a_clean_roster_reports_nothing(db):
    db.seed("payroll_employees", {**_emp(), "firm_id": FIRM, "client_id": "CLI-ON"})
    out = _index()
    assert out["exceptions"] == [] and out["summary"] == {}
    assert out["employees_checked"] == 1


def test_an_employee_missing_a_uan_reaches_the_index(db):
    db.seed("payroll_employees", {**_emp(uan=""), "firm_id": FIRM, "client_id": "CLI-ON"})
    out = _index()
    assert out["summary"] == {"uan": 1}
    assert out["exceptions"][0]["client_name"] == "Acme Pvt Ltd"


def test_a_client_payroll_is_off_for_contributes_nobody(db):
    """They have no statutory output to block, and listing their staff would
    bury the employees somebody actually has to chase."""
    db.seed("payroll_employees", {**_emp(id="E9", uan=""), "firm_id": FIRM,
                                  "client_id": "CLI-OFF"})
    out = _index()
    assert out["exceptions"] == [] and out["employees_checked"] == 0


def test_a_leaver_is_not_an_exception(db):
    """Chasing a resigned employee for a UAN is noise. Their history stays
    readable; they are simply off the roster."""
    db.seed("payroll_employees", {**_emp(uan="", status="resigned"),
                                  "firm_id": FIRM, "client_id": "CLI-ON"})
    assert _index()["exceptions"] == []


def test_the_denominator_is_reported(db):
    """"14 employees need a UAN" means something different out of 20 than out of
    400, and a list with no total invites the first reading."""
    for i in range(3):
        db.seed("payroll_employees", {**_emp(id=f"E{i}", uan="" if i == 0 else "100200300400"),
                                      "firm_id": FIRM, "client_id": "CLI-ON"})
    out = _index()
    assert out["employees_checked"] == 3 and out["summary"] == {"uan": 1}


def test_the_date_of_birth_gap_needs_an_old_regime_declaration(db):
    """The endpoint reads the firm's declarations to decide, so an employee who
    has intimated nothing is on the §115BAC(1A) default and is not asked."""
    db.seed("payroll_employees", {**_emp(id="E-NEW", date_of_birth=None),
                                  "firm_id": FIRM, "client_id": "CLI-ON"})
    assert _index()["exceptions"] == []

    db.seed("payroll_it_declarations", {"id": "d-1", "firm_id": FIRM,
                                        "client_id": "CLI-ON", "employee_id": "E-NEW",
                                        "fy": "2026-27", "regime": "old"})
    assert _index()["summary"] == {"date_of_birth": 1}
