"""
Applying a named salary structure, and the three refusals the table's shape
forces.

WHAT WAS MISSING
    public.salary_structures has existed since migration 054 and NO RUN HAS
    EVER READ IT. A CA could create "Junior — 40/20", see it listed, and nothing
    would ever apply it: every employee's basic, HRA and DA are keyed in one by
    one on the employee master.

WHAT APPLYING ONE MEANS
    It writes a payroll_salary_revisions row (migration 300), not a live link.
    The run already reads revisions, so a structure applied from 1 October
    starts in October and does not restate September, which is posted. A live
    salary_structure_id would mean editing a structure silently restates every
    employee on it, including months already in the general ledger.

THE THREE THINGS THE TABLE'S OWN SHAPE FORCES
    1. The percentages are of GROSS. Migration 054 comments them "% of CTC",
       and read literally with an Indian CTC — which includes employer PF —
       that is circular: PF is 12% of basic and basic would be a percentage of
       a total including it. The caller names the gross; nothing is inferred.
    2. `special_percent` cannot be honoured alongside a fixed medical_paise,
       because the shortfall the percentages must leave depends on the gross.
       Special is the remainder, in paise, so the heads sum exactly.
    3. HRA and DA are stored as percentages of BASIC to two decimals, while the
       structure states them as percentages of gross. The conversion is exact
       only when the ratio lands on two decimals — and where it does not, the
       difference is REPORTED per employee with both figures rather than
       rounded away. HRA feeds §10(13A) and Annexure II.

NEGATIVE CONTROL
    Make special the remainder of the INTENDED figures instead of the actual
    ones and test_the_heads_always_sum_to_the_gross fails on the drift case.
    Drop the drift check and test_a_percentage_that_does_not_survive_the_round_trip_is_reported
    passes silently while paying a different HRA.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from domain.payroll.salary_structure import (
    Application, StructureError, apply_structure, drift_note, percent_of)

GROSS = 5_000_000          # ₹50,000 a month


def _structure(**kw) -> dict:
    base = {"name": "Junior", "basic_percent": 40, "hra_percent": 20,
            "da_percent": 0, "lta_percent": 5, "medical_paise": 125_000}
    base.update(kw)
    return base


# ── the ordinary case ────────────────────────────────────────────────────────

def test_the_heads_come_off_the_gross():
    a = apply_structure(_structure(), GROSS)
    assert a.basic_paise == 2_000_000                 # 40%
    assert a.lta_paise == 250_000                     # 5%
    assert a.medical_paise == 125_000                 # the fixed figure


def test_hra_is_stored_as_a_percentage_of_basic_not_of_gross():
    """The employee master and payroll_salary_revisions both hold it that way,
    and 20% of gross on a 40% basic is 50% of basic."""
    a = apply_structure(_structure(), GROSS)
    assert a.hra_percent_of_basic == Decimal("50.00")
    assert percent_of(a.basic_paise, a.hra_percent_of_basic) == 1_000_000


@pytest.mark.parametrize("gross", [1_000_000, 3_333_300, 5_000_000, 12_345_600])
def test_the_heads_always_sum_to_the_gross(gross):
    """Special is the remainder IN PAISE of what will ACTUALLY be paid, so
    nothing is lost to rounding and nothing is invented by it."""
    a = apply_structure(_structure(), gross)
    assert sum(c.paise for c in a.components) == gross


def test_special_allowance_is_the_remainder():
    a = apply_structure(_structure(), GROSS)
    assert a.special_allowance_paise == (
        GROSS - 2_000_000 - 1_000_000 - 0 - 250_000 - 125_000)


def test_the_revision_it_writes_carries_every_head():
    a = apply_structure(_structure(), GROSS)
    rev = a.as_revision()
    assert set(rev) == {"basic_paise", "hra_percent", "da_percent", "lta_paise",
                        "medical_paise", "special_allowance_paise",
                        "other_allowances_paise"}
    assert rev["basic_paise"] == 2_000_000
    assert rev["hra_percent"] == "50.00"


def test_other_allowances_are_not_a_structure_head():
    """Anything the CA had set there is a separate decision, and applying a
    structure must not silently zero it — the caller carries it forward."""
    assert apply_structure(_structure(), GROSS).as_revision()["other_allowances_paise"] == 0


# ── the two-decimal round trip ───────────────────────────────────────────────

def test_a_clean_ratio_has_no_drift():
    assert apply_structure(_structure(), GROSS).drifts == ()
    assert drift_note("Asha", apply_structure(_structure(), GROSS)) == []


def test_a_percentage_that_does_not_survive_the_round_trip_is_reported():
    """17% of gross on a 43% basic is 39.5348…% of basic, which stores as 39.53
    and pays ₹1.05 less a month. Reported with both figures, not rounded away:
    a figure that is nearly right reconciles for eleven months and fails in the
    twelfth."""
    a = apply_structure(_structure(basic_percent=43, hra_percent=17,
                                   lta_percent=0, medical_paise=0), GROSS)
    [hra] = a.drifts
    assert hra.name == "HRA"
    assert hra.intended_paise == 850_000
    assert hra.paise == 849_895
    [note] = drift_note("Bikram", a)
    assert "850000" in note and "849895" in note and "105 paise less" in note


def test_a_drifting_head_still_leaves_the_gross_exact():
    """The difference goes to special allowance. Computing special from the
    INTENDED figures instead would make the gross itself wrong."""
    a = apply_structure(_structure(basic_percent=43, hra_percent=17,
                                   lta_percent=0, medical_paise=0), GROSS)
    assert sum(c.paise for c in a.components) == GROSS


# ── the refusals ─────────────────────────────────────────────────────────────

def test_a_structure_cannot_be_applied_without_a_gross():
    """The percentages are of something, and nothing here can infer what — the
    "% of CTC" in migration 054 is circular for an Indian CTC, which includes
    the employer's PF, itself 12% of basic."""
    with pytest.raises(StructureError, match="monthly gross is required"):
        apply_structure(_structure(), 0)


def test_a_zero_basic_is_refused():
    """Every statutory computation in this system starts from basic: PF,
    gratuity, the HRA exemption and the Bonus Act."""
    with pytest.raises(StructureError, match="Basic must be more than 0"):
        apply_structure(_structure(basic_percent=0), GROSS)


def test_percentages_beyond_the_whole_gross_are_refused():
    with pytest.raises(StructureError, match="more than the whole of it"):
        apply_structure(_structure(basic_percent=60, hra_percent=30,
                                   da_percent=20, lta_percent=5), GROSS)


def test_a_medical_amount_that_does_not_fit_is_refused():
    """A fixed rupee allowance larger than what the percentages leave would make
    special allowance negative — which would pay a negative head rather than
    say the structure does not fit this salary."""
    with pytest.raises(StructureError, match="does not fit"):
        apply_structure(_structure(medical_paise=5_000_000), GROSS)


def test_a_negative_percentage_is_refused():
    with pytest.raises(StructureError, match="cannot be negative"):
        apply_structure(_structure(hra_percent=-5), GROSS)


def test_a_percentage_that_is_not_a_number_is_refused():
    with pytest.raises(StructureError, match="not a percentage"):
        apply_structure(_structure(hra_percent="twenty"), GROSS)


# ── the arithmetic matches the run's ─────────────────────────────────────────

def test_percent_of_matches_the_routers_own_derivation():
    """Two derivations of one percentage drift, and this one has to reproduce
    that one to the paise or the round-trip check above is meaningless."""
    import routers.payroll as pr
    for base in (0, 1, 999_999, 2_000_000, 3_333_333):
        for pct in ("0", "0.01", "12.5", "39.53", "50.00", "100"):
            assert percent_of(base, pct) == pr._percent_of(base, pct), (base, pct)


def test_nothing_here_uses_floating_point():
    import inspect
    import domain.payroll.salary_structure as mod
    src = inspect.getsource(mod)
    assert "float(" not in src
    assert "Decimal" in src


# ── the endpoint, through the harness ────────────────────────────────────────
#
# Driven through FakeDB rather than the mock branch, so what is asserted is the
# real path: the roster read, the refusals, the rows written and the run that
# afterwards pays from them.

import routers.payroll as payroll_mod  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-STRUCT"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    # Payroll is switched ON for this client (migration 332). A firm that
    # runs payroll for a client has said so; without the row every write
    # below is refused, which is the gate working rather than a fixture
    # detail — see assert_payroll_enabled.
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                        "payroll_enabled": True})
    d.seed("salary_structures", {
        "id": "STR-1", "firm_id": FIRM, "client_id": "CLI", "name": "Junior",
        "basic_percent": 40, "hra_percent": 20, "da_percent": 0,
        "lta_percent": 5, "medical_paise": 125_000, "special_percent": 35,
    })
    d.seed("payroll_employees", {
        "id": "e-1", "firm_id": FIRM, "client_id": "CLI", "name": "Asha",
        "basic_paise": 0, "hra_percent": 0.0, "da_percent": 0.0,
        "other_allowances_paise": 50_000, "lta_paise": 0, "medical_paise": 0,
        "special_allowance_paise": 0, "pf_applicable": False,
        "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active",
    })
    return d


def _apply(**kw):
    from models.payroll import ApplyStructureIn, StructureAssignmentIn
    body = {"client_id": "CLI", "effective_from": "2026-10-01",
            "assignments": [StructureAssignmentIn(employee_id="e-1",
                                                  monthly_gross_paise=GROSS)]}
    body.update(kw)
    return payroll_mod.apply_salary_structure("STR-1", ApplyStructureIn(**body), CALLER)


def test_applying_writes_a_revision_not_a_link(db):
    """THE HEADLINE. Nothing had ever read salary_structures; now applying one
    produces the effective-dated row the run already knows how to use."""
    out = _apply()
    assert out["success"] and out["data"]["applied"] == 1
    [rev] = db.rows("payroll_salary_revisions")
    assert rev["employee_id"] == "e-1"
    assert rev["effective_from"] == "2026-10-01"
    assert rev["basic_paise"] == 2_000_000
    assert rev["hra_percent"] == "50.00"


def test_the_revision_records_which_structure_produced_it(db):
    """Provenance, not a live link: the structure cannot reach back and change
    a revision (migration 330)."""
    _apply()
    [rev] = db.rows("payroll_salary_revisions")
    assert rev["source_structure_id"] == "STR-1"


def test_an_existing_other_allowance_is_carried_forward_not_zeroed(db):
    """No structure head produces it, so it is a separate decision the CA made
    and applying a template must not silently undo it."""
    _apply()
    [rev] = db.rows("payroll_salary_revisions")
    assert rev["other_allowances_paise"] == 50_000


def test_preview_computes_everything_and_writes_nothing(db):
    out = _apply(preview=True)
    assert out["data"]["preview"] is True and out["data"]["applied"] == 0
    assert out["data"]["employees"][0]["Basic"] == 2_000_000
    assert db.rows("payroll_salary_revisions") == []


def test_the_response_shows_every_head_the_employee_will_be_paid(db):
    [row] = _apply(preview=True)["data"]["employees"]
    assert row["Basic"] + row["HRA"] + row["DA"] + row["LTA"] \
        + row["Medical"] + row["Special allowance"] == GROSS


def test_a_drift_is_reported_on_the_response(db):
    """43/17 cannot be expressed as a two-decimal percentage of basic. The CA
    sees it before committing, not on a payslip in March."""
    db.rows("salary_structures")[0].update({"basic_percent": 43, "hra_percent": 17,
                                            "lta_percent": 0, "medical_paise": 0})
    out = _apply(preview=True)
    assert any("HRA works out to" in n for n in out["data"]["notes"])


def test_a_structure_that_does_not_fit_stops_the_whole_request(db):
    """A partial application would leave half a roster on the new scale and half
    on the old, with nothing on the screen saying which."""
    from fastapi import HTTPException
    from models.payroll import StructureAssignmentIn
    db.seed("payroll_employees", {
        "id": "e-2", "firm_id": FIRM, "client_id": "CLI", "name": "Bikram",
        "other_allowances_paise": 0, "is_active": True, "status": "active"})
    with pytest.raises(HTTPException) as e:
        _apply(assignments=[
            StructureAssignmentIn(employee_id="e-1", monthly_gross_paise=GROSS),
            # ₹1,000 a month cannot carry a ₹1,250 fixed medical allowance.
            StructureAssignmentIn(employee_id="e-2", monthly_gross_paise=100_000)])
    assert e.value.status_code == 422
    assert any("Bikram" in p for p in e.value.detail["problems"])
    assert db.rows("payroll_salary_revisions") == [], "Asha must not be changed either"


def test_an_employee_from_another_client_is_refused(db):
    from fastapi import HTTPException
    from models.payroll import StructureAssignmentIn
    with pytest.raises(HTTPException) as e:
        _apply(assignments=[StructureAssignmentIn(employee_id="somebody-else",
                                                  monthly_gross_paise=GROSS)])
    assert e.value.status_code == 422
    assert "not on this client's roster" in e.value.detail


def test_the_same_employee_twice_is_refused(db):
    from fastapi import HTTPException
    from models.payroll import StructureAssignmentIn
    with pytest.raises(HTTPException) as e:
        _apply(assignments=[
            StructureAssignmentIn(employee_id="e-1", monthly_gross_paise=GROSS),
            StructureAssignmentIn(employee_id="e-1", monthly_gross_paise=1_000_000)])
    assert e.value.status_code == 422


def test_an_empty_request_is_refused(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _apply(assignments=[])
    assert e.value.status_code == 422


def test_a_structure_from_another_client_is_not_found(db):
    from fastapi import HTTPException
    from models.payroll import ApplyStructureIn, StructureAssignmentIn
    with pytest.raises(HTTPException) as e:
        payroll_mod.apply_salary_structure("STR-NOPE", ApplyStructureIn(
            client_id="CLI", effective_from="2026-10-01",
            assignments=[StructureAssignmentIn(employee_id="e-1",
                                               monthly_gross_paise=GROSS)]), CALLER)
    assert e.value.status_code == 404


def test_backdating_over_a_released_month_is_reported_not_refused(db):
    """Legitimate: a rise agreed in November and effective from September is how
    arrears arise, and this system computes them (IT Act s.89). Those months are
    not recomputed — the slips are stored — so it is a note, not a block."""
    db.seed("payroll_runs", {"id": "RUN-1", "firm_id": FIRM, "client_id": "CLI",
                             "month": "2026-10", "status": "finalized"})
    out = _apply()
    assert out["success"]
    assert any("already released" in n and "arrears" in n for n in out["data"]["notes"])


def test_a_month_before_the_revision_is_not_reported(db):
    db.seed("payroll_runs", {"id": "RUN-0", "firm_id": FIRM, "client_id": "CLI",
                             "month": "2026-08", "status": "finalized"})
    assert not any("already released" in n for n in _apply()["data"]["notes"])


def test_the_run_afterwards_pays_from_the_revision(db):
    """The point of writing a revision rather than a link: the run already reads
    them, so nothing downstream needed changing."""
    _apply()
    in_force = payroll_mod._salary_in_force(db, FIRM, "CLI", "2026-10")
    assert in_force["e-1"]["basic_paise"] == 2_000_000
    assert payroll_mod._salary_in_force(db, FIRM, "CLI", "2026-09") == {}, \
        "and September, before it takes effect, is untouched"
