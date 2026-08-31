"""
Professional tax and Labour Welfare Fund: what is modelled, and what is a gap.

THE BUG

_compute_pt looked its state code up in a dict of slab tables and returned 0 for
anything it did not find. Four states are modelled — Maharashtra, Tamil Nadu,
Karnataka, West Bengal — so an employee whose pt_state was "GJ", "TG", "KL" or a
dozen others was silently deducted NOTHING on a run the CA had marked
pt_applicable.

A zero for Delhi and a zero for Gujarat are the same number meaning opposite
things: "nothing is due" and "something is due and nobody worked it out".
Article 276 makes the EMPLOYER liable to deduct and deposit professional tax, so
the second is a shortfall with interest, discovered at assessment.

LWF is blunter still: this module deducts it nowhere, so every employer who owes
it has been shown a payslip that quietly omits a statutory deduction.

WHY THE AMOUNTS ARE NOT SIMPLY FILLED IN

Twenty states' slabs and sixteen states' LWF amounts, each set by its own
notification and moving independently, written from memory, would be twenty and
sixteen confidently wrong numbers in people's pay. A wrong deduction is worse
than a flagged gap: the employee is short-paid and the employer still owes the
right figure. Same judgement as the ESIC reason codes.
"""
from __future__ import annotations

import pytest

from domain.payroll import lwf, professional_tax as pt
from routers.payroll import _compute_pt, _statutory_gaps


# ── the three answers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", sorted(pt.MODELLED_STATES))
def test_a_modelled_state_is_not_a_gap(code):
    assert not pt.classify_state(code).is_gap


@pytest.mark.parametrize("code", ["DL", "HR", "UP", "RJ", "CH"])
def test_a_state_that_does_not_levy_pt_is_a_correct_zero(code):
    r = pt.classify_state(code)
    assert not r.is_gap and r.amount_paise == 0
    assert "does not levy" in r.note


@pytest.mark.parametrize("code", ["GJ", "TG", "KL", "OD", "PB", "AP"])
def test_a_levying_state_we_do_not_model_is_a_gap(code):
    """The bug. These states levy PT; nothing was deducted; that must be said."""
    r = pt.classify_state(code)
    assert r.is_gap
    assert "levies professional tax" in r.note
    assert "Article 276" in r.note, "the note should say who carries the shortfall"


def test_an_unrecognised_code_is_a_gap_not_a_zero():
    """An unknown code cannot be told apart from a levying state, so it gets the
    cautious answer rather than the convenient one."""
    assert pt.classify_state("ZZ").is_gap


def test_no_state_set_is_not_a_gap():
    """PT is withheld only where the CA has said which state's law applies.
    Saying nothing is a choice, not an omission."""
    assert not pt.classify_state(None).is_gap
    assert not pt.classify_state("").is_gap


def test_the_modelled_states_are_all_levying_states():
    """A state cannot be modelled and also not levy the tax."""
    assert pt.MODELLED_STATES <= set(pt.LEVYING_STATES)


def test_levying_and_non_levying_do_not_overlap():
    assert not (set(pt.LEVYING_STATES) & set(pt.NON_LEVYING_STATES))


# ── the computation still works where it is modelled ─────────────────────────

def test_maharashtra_still_computes():
    """The classifier must not have disturbed the four states that do work."""
    assert _compute_pt(30_000_00, "MH", month=6, gender="M") > 0
    assert _compute_pt(30_000_00, "MH", month=2, gender="M") > 0


def test_karnataka_still_computes():
    assert _compute_pt(30_000_00, "KA") > 0


def test_an_unmodelled_state_still_returns_zero_rupees():
    """The number is unchanged — the fix is that the zero is now REPORTED, not
    that it silently became something else."""
    assert _compute_pt(30_000_00, "GJ") == 0


# ── LWF ──────────────────────────────────────────────────────────────────────

def test_lwf_models_no_state_yet_and_says_so():
    """Honest about its own state: the amounts are not carried, so nothing may
    claim to be modelled."""
    assert lwf.MODELLED_STATES == frozenset()


@pytest.mark.parametrize("code", ["MH", "KA", "TN", "DL", "GJ"])
def test_every_lwf_levying_state_is_a_gap(code):
    r = lwf.classify_state(code)
    assert r.is_gap
    assert r.employee_paise == 0 and r.employer_paise == 0
    assert "not modelled" in r.note


def test_a_state_without_an_lwf_act_is_not_a_gap():
    assert not lwf.classify_state("UP").is_gap
    assert not lwf.classify_state(None).is_gap


# ── what the run reports ─────────────────────────────────────────────────────

def test_a_gujarat_employee_produces_both_gaps():
    gaps = _statutory_gaps({"name": "Asha", "pt_applicable": True, "pt_state": "GJ"})
    assert len(gaps) == 2
    assert any("professional tax" in g for g in gaps)
    assert any("Labour Welfare Fund" in g for g in gaps)
    assert all(g.startswith("Asha:") for g in gaps)


def test_a_karnataka_employee_reports_only_the_lwf_gap():
    """PT is modelled for Karnataka, LWF is not — so exactly one gap, and it is
    the right one."""
    gaps = _statutory_gaps({"name": "Ravi", "pt_applicable": True, "pt_state": "KA"})
    assert len(gaps) == 1
    assert "Labour Welfare Fund" in gaps[0]


def test_no_pt_gap_is_raised_when_pt_is_not_applicable():
    """Somebody outside PT altogether should not be told their state's slabs are
    missing."""
    gaps = _statutory_gaps({"name": "Sam", "pt_applicable": False, "pt_state": "GJ"})
    assert not any("professional tax" in g for g in gaps)
