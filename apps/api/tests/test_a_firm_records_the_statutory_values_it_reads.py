"""
A firm records the state statutory figures it reads, and the run uses them.

THE PROBLEM, WHICH IS COMMERCIAL AS MUCH AS TECHNICAL

Professional tax is levied by twenty-two states, each setting its own slabs by
its own notification on its own cycle. domain/payroll/professional_tax.py models
FOUR of them and reports a named gap for the rest rather than deducting zero,
which is right — Article 276 makes the employer liable to deduct and deposit it,
so a silent nil is a shortfall with interest, not an absence of liability.

Correct, and not a product. A CA whose client has staff in Telangana is told the
software cannot compute a deduction the employer owes, and the only remedy is
that somebody edits Python. Writing the other eighteen states' slabs from memory
would put eighteen confidently wrong deductions into people's pay.

The Labour Welfare Fund is refused by the same shape and is deliberately NOT in
this change: PT already has a slip column, a ledger leg and a payslip line, so a
recorded slab becomes a deduction the same day; LWF has none of those and its
table ships with them.

So the CA records what they READ — once per firm, reused across every client of
that firm, with the notification it came from and its date.

THE THREE RULES THIS FILE PINS

  1. A zero is only allowed when it is SOURCED. Nothing recorded, nothing
     effective yet, or bands that leave a hole all come back usable=False —
     the gap survives rather than becoming a nil deduction.
  2. A revision is a NEW effective_from, and a run for an earlier month keeps
     computing at the figures that applied to it. Editing in place would
     silently restate a month already posted to the general ledger.
  3. For a state the CODE models, the code wins and the disagreement is
     REPORTED. Applying the firm row would let one typo replace a table
     verified against the state Act for every client of the firm; dropping it
     would leave a CA believing they had fixed something.

NEGATIVE CONTROL
    Make professional_tax() fall back to 0 when nothing is recorded (drop the
    usable flag) and six tests below fail — every one of them asserting that an
    unrecorded or half-recorded state stays a gap. Relax
    bands_cover_every_wage to `bool(bands)` and the hole tests fail.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.payroll import firm_rates as fr
from domain.payroll.professional_tax import MODELLED_STATES


def _slab(frm, to, amount, **kw):
    base = {"state": "GJ", "effective_from": "2026-04-01", "basis": "monthly",
            "from_paise": frm, "to_paise": to, "amount_paise": amount,
            "notification_reference": "GJ/PT/2026-01", "notification_date": "2026-03-15"}
    base.update(kw)
    return base


#: A complete Gujarat-shaped set: nil to ₹12,000, ₹200 above.
COMPLETE = [_slab(0, 1_200_000, 0), _slab(1_200_000, None, 20_000)]
AUG = date(2026, 8, 31)


# ── bands have to cover every wage ───────────────────────────────────────────

def test_a_complete_set_covers_every_wage():
    assert fr.bands_cover_every_wage(COMPLETE) is True


def test_a_set_that_does_not_start_at_zero_does_not_cover():
    """A wage below the lowest band has no band, and the only answer available
    is a zero meaning "nobody recorded this"."""
    assert fr.bands_cover_every_wage([_slab(500_000, None, 20_000)]) is False


def test_a_hole_between_bands_does_not_cover():
    assert fr.bands_cover_every_wage(
        [_slab(0, 500_000, 0), _slab(600_000, None, 20_000)]) is False


def test_a_set_with_no_open_top_band_does_not_cover():
    """Without "and above", the highest earners fall through."""
    assert fr.bands_cover_every_wage(
        [_slab(0, 500_000, 0), _slab(500_000, 1_200_000, 10_000)]) is False


def test_an_open_band_that_is_not_last_does_not_cover():
    assert fr.bands_cover_every_wage(
        [_slab(0, None, 0), _slab(1_200_000, None, 20_000)]) is False


def test_no_bands_at_all_do_not_cover():
    assert fr.bands_cover_every_wage([]) is False


# ── professional tax from a recorded set ─────────────────────────────────────

def test_a_recorded_slab_produces_the_deduction():
    r = fr.professional_tax(COMPLETE, gross_paise=1_500_000, month=8, on=AUG, state="GJ")
    assert r.usable and r.employee_paise == 20_000


def test_the_notification_travels_with_the_figure():
    """The whole argument for using a hand-entered number is that somebody read
    a named notification on a named date, so the register prints it."""
    r = fr.professional_tax(COMPLETE, gross_paise=1_500_000, month=8, on=AUG, state="GJ")
    assert r.notification_reference == "GJ/PT/2026-01"
    assert r.notification_date == "2026-03-15"


def test_a_matched_nil_band_is_a_real_zero():
    """A state saying nothing is due at this wage is an ANSWER, and it is
    sourced. Distinct from the unsourced zeros below."""
    r = fr.professional_tax(COMPLETE, gross_paise=500_000, month=8, on=AUG, state="GJ")
    assert r.usable is True and r.employee_paise == 0 and r.is_gap is False


def test_nothing_recorded_stays_a_gap():
    r = fr.professional_tax([], gross_paise=1_500_000, month=8, on=AUG, state="GJ")
    assert r.is_gap and r.employee_paise == 0
    assert "No professional-tax slabs are recorded for GJ" in r.note


def test_a_set_with_a_hole_stays_a_gap_rather_than_deducting_nil():
    """The headline refusal: a half-recorded state must not quietly deduct
    nothing from the people the CA had not got to yet."""
    r = fr.professional_tax([_slab(0, 500_000, 0), _slab(600_000, None, 20_000)],
                            gross_paise=550_000, month=8, on=AUG, state="GJ")
    assert r.is_gap
    assert "do not cover every wage" in r.note


def test_a_slab_that_is_not_yet_effective_is_not_used():
    future = [dict(b, effective_from="2026-10-01") for b in COMPLETE]
    r = fr.professional_tax(future, gross_paise=1_500_000, month=8, on=AUG, state="GJ")
    assert r.is_gap


# ── a revision is a new version, and an old month keeps its old figures ──────

def test_the_latest_version_effective_on_the_date_wins():
    old = [dict(b, effective_from="2025-04-01", amount_paise=b["amount_paise"] // 2)
           for b in COMPLETE]
    r = fr.professional_tax(old + COMPLETE, gross_paise=1_500_000, month=8, on=AUG, state="GJ")
    assert r.employee_paise == 20_000


def test_a_month_before_the_revision_keeps_the_old_figure():
    """Editing a slab in place would silently restate a month already posted to
    the general ledger. A revision is a new effective_from, so it does not."""
    old = [dict(b, effective_from="2025-04-01", amount_paise=10_000) for b in COMPLETE]
    r = fr.professional_tax(old + COMPLETE, gross_paise=1_500_000, month=8,
                            on=date(2026, 3, 31), state="GJ")
    assert r.employee_paise == 10_000


# ── the month qualifiers, without a rule engine ──────────────────────────────

def test_a_half_yearly_levy_reads_six_months_of_pay():
    """Tamil Nadu's shape, recorded rather than coded, so a state that shares
    it needs no code change."""
    half = [_slab(0, 1_200_000, 0, basis="half_yearly", months=[9, 3]),
            _slab(1_200_000, None, 100_000, basis="half_yearly", months=[9, 3])]
    r = fr.professional_tax(half, gross_paise=300_000, month=9, on=date(2026, 9, 30), state="XX")
    assert r.usable and r.employee_paise == 100_000, "6 x 3,000 is above the band"


def test_a_half_yearly_levy_is_nil_in_the_other_months():
    half = [_slab(0, 1_200_000, 0, basis="half_yearly", months=[9, 3]),
            _slab(1_200_000, None, 100_000, basis="half_yearly", months=[9, 3])]
    r = fr.professional_tax(half, gross_paise=300_000, month=8, on=AUG, state="XX")
    assert r.usable and r.employee_paise == 0
    assert "not deducted in this month" in r.note


def test_a_band_with_no_months_applies_every_month():
    """Walked over a whole financial year rather than a calendar one — the set
    is effective from 1 April, so January to March belong to the NEXT calendar
    year and dating them 2026 would be testing the effective-from rule again."""
    for m in range(1, 13):
        on = date(2026, m, 28) if m >= 4 else date(2027, m, 28)
        r = fr.professional_tax(COMPLETE, gross_paise=1_500_000, month=m,
                                on=on, state="GJ")
        assert r.employee_paise == 20_000, f"month {m}"


# ── the code wins for a state it models ──────────────────────────────────────

def test_slabs_recorded_against_a_modelled_state_are_reported():
    """Not applied and not dropped. Applying would let one typo replace a table
    verified against the state Act for every client of the firm."""
    [msg] = fr.slabs_recorded_against_a_modelled_state(
        [_slab(0, None, 20_000, state="MH")], MODELLED_STATES)
    assert "MH" in msg and "NOT used" in msg
    assert "code change, not a settings change" in msg


def test_slabs_for_an_unmodelled_state_are_not_reported_as_a_conflict():
    assert fr.slabs_recorded_against_a_modelled_state(
        [_slab(0, None, 20_000, state="GJ")], MODELLED_STATES) == []


def test_each_conflicting_state_is_named_once():
    slabs = [_slab(0, 100, 0, state="MH"), _slab(100, None, 20_000, state="MH"),
             _slab(0, None, 10_000, state="KA")]
    msgs = fr.slabs_recorded_against_a_modelled_state(slabs, MODELLED_STATES)
    assert len(msgs) == 2


def test_the_four_modelled_states_are_the_ones_the_code_verifies():
    """If a fifth state is modelled in code, this file's premise moves with it
    rather than silently going stale."""
    assert MODELLED_STATES == frozenset({"MH", "TN", "KA", "WB"})


# ── the endpoints, in mock mode ──────────────────────────────────────────────

import routers.payroll as pr  # noqa: E402

USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "role": "Partner"}


@pytest.fixture()
def mock_mode(monkeypatch):
    monkeypatch.setattr(pr, "_db", lambda: None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    pr._MOCK_PT_SLABS.clear()
    yield
    pr._MOCK_PT_SLABS.clear()


def _set(state="GJ", effective_from="2026-04-01", bands=None):
    from models.payroll import PTSlabSetIn, PTSlabBandIn
    bands = bands if bands is not None else [
        PTSlabBandIn(from_paise=0, to_paise=1_200_000, amount_paise=0),
        PTSlabBandIn(from_paise=1_200_000, to_paise=None, amount_paise=20_000),
    ]
    return PTSlabSetIn(state=state, effective_from=effective_from,
                       notification_reference="GJ/PT/2026-01",
                       notification_date="2026-03-15", bands=bands)


def test_a_recorded_set_reads_back(mock_mode):
    assert pr.put_pt_slabs(_set(), USER)["data"]["bands"] == 2
    got = pr.get_statutory_values(current_user=USER)["data"]
    assert len(got["pt_slabs"]) == 2
    assert got["pt_recorded_states"] == ["GJ"]


def test_the_screen_reads_who_levies_and_who_is_modelled_from_the_api(mock_mode):
    """So the Settings screen can say "eighteen states levy this, you have
    recorded three" without holding its own copy of who levies what."""
    got = pr.get_statutory_values(current_user=USER)["data"]
    assert set(got["pt_modelled_states"]) == {"MH", "TN", "KA", "WB"}
    assert "GJ" in got["pt_levying_states"] and "DL" not in got["pt_levying_states"]


def test_a_set_with_a_hole_is_refused_at_the_door(mock_mode):
    """Refused at WRITE time, not merely ignored at read time. A half-recorded
    state must not be able to exist: between two per-band calls a wage in the
    hole would come out as a silent nil."""
    from fastapi import HTTPException
    from models.payroll import PTSlabBandIn
    with pytest.raises(HTTPException) as e:
        pr.put_pt_slabs(_set(bands=[
            PTSlabBandIn(from_paise=0, to_paise=500_000, amount_paise=0),
            PTSlabBandIn(from_paise=600_000, to_paise=None, amount_paise=20_000)]), USER)
    assert e.value.status_code == 422
    assert "do not cover every wage" in e.value.detail
    assert pr._MOCK_PT_SLABS == {}


def test_a_set_that_does_not_start_at_zero_is_refused(mock_mode):
    from fastapi import HTTPException
    from models.payroll import PTSlabBandIn
    with pytest.raises(HTTPException) as e:
        pr.put_pt_slabs(_set(bands=[
            PTSlabBandIn(from_paise=500_000, to_paise=None, amount_paise=20_000)]), USER)
    assert e.value.status_code == 422


def test_a_set_mixing_two_bases_is_refused(mock_mode):
    """A state reads its slab against the month or against six months, not
    both — a mixed set would compute two different measures from one table."""
    from fastapi import HTTPException
    from models.payroll import PTSlabBandIn
    with pytest.raises(HTTPException) as e:
        pr.put_pt_slabs(_set(bands=[
            PTSlabBandIn(from_paise=0, to_paise=1_200_000, amount_paise=0),
            PTSlabBandIn(from_paise=1_200_000, to_paise=None, amount_paise=20_000,
                         basis="half_yearly")]), USER)
    assert e.value.status_code == 422
    assert "same basis" in e.value.detail


def test_rerecording_a_version_replaces_it_rather_than_adding_to_it(mock_mode):
    """A set that was two bands and is now three must not leave the old two
    behind, where they would overlap and make the lookup order-dependent."""
    from models.payroll import PTSlabBandIn
    pr.put_pt_slabs(_set(), USER)
    pr.put_pt_slabs(_set(bands=[
        PTSlabBandIn(from_paise=0, to_paise=500_000, amount_paise=0),
        PTSlabBandIn(from_paise=500_000, to_paise=1_200_000, amount_paise=10_000),
        PTSlabBandIn(from_paise=1_200_000, to_paise=None, amount_paise=20_000)]), USER)
    assert len(pr.get_statutory_values(current_user=USER)["data"]["pt_slabs"]) == 3


def test_a_notification_reference_is_required():
    from pydantic import ValidationError
    from models.payroll import PTSlabSetIn, PTSlabBandIn
    with pytest.raises(ValidationError):
        PTSlabSetIn(state="GJ", effective_from="2026-04-01",
                    notification_reference="", notification_date="2026-03-15",
                    bands=[PTSlabBandIn(from_paise=0, to_paise=None, amount_paise=0)])


def test_a_date_that_is_not_a_date_is_refused():
    from pydantic import ValidationError
    from models.payroll import PTSlabSetIn, PTSlabBandIn
    band = [PTSlabBandIn(from_paise=0, to_paise=None, amount_paise=0)]
    for bad in ("2026-02-30", "01-04-2026", "2026-4-1"):
        with pytest.raises(ValidationError):
            PTSlabSetIn(state="GJ", effective_from=bad, notification_reference="x",
                        notification_date="2026-03-15", bands=band)


def test_deleting_a_version_puts_the_state_back_into_the_gaps(mock_mode):
    from datetime import date as _date
    pr.put_pt_slabs(_set(), USER)
    slabs = pr._read_firm_pt_slabs(None, "f1")
    assert pr._states_the_firm_covers(slabs, _date(2026, 8, 31)) == {"GJ"}

    pr.delete_pt_slabs(state="gj", effective_from="2026-04-01", current_user=USER)
    slabs = pr._read_firm_pt_slabs(None, "f1")
    assert pr._states_the_firm_covers(slabs, _date(2026, 8, 31)) == set()


def test_a_modelled_state_is_never_reported_as_covered(mock_mode):
    """Recording MH does not make the code use it, so it must not silence the
    conflict either."""
    from datetime import date as _date
    pr.put_pt_slabs(_set(state="MH"), USER)
    slabs = pr._read_firm_pt_slabs(None, "f1")
    assert pr._states_the_firm_covers(slabs, _date(2026, 8, 31)) == set()
    assert pr.get_statutory_values(current_user=USER)["data"]["pt_conflicts"]


# ── the run uses them ────────────────────────────────────────────────────────

def test_the_run_computes_pt_for_a_state_the_firm_recorded():
    """The whole point: eighteen states go from "nothing deducted, here is a
    gap" to a computed deduction, without a code change."""
    from datetime import date as _date
    slabs = [dict(b, state="GJ") for b in COMPLETE]
    assert pr._compute_pt(1_500_000, "GJ", month=8, firm_slabs=slabs,
                          on=_date(2026, 8, 31)) == 20_000


def test_an_unrecorded_state_still_deducts_nothing():
    assert pr._compute_pt(1_500_000, "GJ", month=8) == 0


def test_a_recorded_set_with_a_hole_still_deducts_nothing():
    """usable=False must not become a deduction. This is the branch that turns
    a refusal into a silent zero if anybody relaxes the cover check."""
    from datetime import date as _date
    holed = [_slab(0, 500_000, 0, state="GJ"), _slab(600_000, None, 20_000, state="GJ")]
    assert pr._compute_pt(1_500_000, "GJ", month=8, firm_slabs=holed,
                          on=_date(2026, 8, 31)) == 0


def test_a_firm_slab_never_displaces_a_modelled_state():
    """Maharashtra's February differential and women's exemption are not
    expressible as plain slabs, and MH is verified against the Act. A recorded
    set must not replace it."""
    from datetime import date as _date
    mh = [dict(b, state="MH", amount_paise=99_999) for b in COMPLETE]
    assert pr._compute_pt(1_500_000, "MH", month=8, firm_slabs=mh,
                          on=_date(2026, 8, 31)) == 200_00


def test_a_covered_state_stops_being_reported_as_a_gap():
    emp = {"name": "Asha", "pt_applicable": True, "pt_state": "GJ"}
    assert pr._statutory_gaps(emp, set()), "unrecorded GJ is still a gap"
    assert not [g for g in pr._statutory_gaps(emp, {"GJ"}) if "professional tax" in g]


def test_the_run_reports_a_set_recorded_against_a_modelled_state():
    import inspect
    src = inspect.getsource(pr.create_run)
    assert "slabs_recorded_against_a_modelled_state" in src
    assert "_states_the_firm_covers" in src


def test_the_slabs_are_read_once_for_the_whole_run():
    """A 200-employee run in three states is one query, not two hundred — the
    reporting rule in CLAUDE.md, and the mistake the attendance read made."""
    import inspect
    src = inspect.getsource(pr.create_run)
    assert src.count("_read_firm_pt_slabs(") == 1
    assert "_read_firm_pt_slabs" not in inspect.getsource(pr._compute_slip)
