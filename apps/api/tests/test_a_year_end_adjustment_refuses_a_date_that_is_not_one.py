"""A year-end adjustment's date is judged before it is stored (found by the twelfth slice's drive of the form, PRE-A-015).

WHAT WAS WRONG
    `AdjustmentCreateIn.adjustment_date` and `AdjustmentUpdateIn.adjustment_date` were bare strings that go straight into a DATE column, and the date
    is the entry date of the journal a posting writes into the audited books. A caller that is not the screen (a script, a hand-made request) that sent
    "" or "2026-02-30" reached Postgres with it and got a 500 (SQLSTATE 22007/22008, which the unhandled-failure speaker does not map), with no sentence.
    The screen now starts the box empty and asks for the date in words; this is the same refusal for every other caller.

WHAT IS HELD
    A date that is not a real day is a 422 naming the field, in the one rule every model of this kind shares (`models/iso_date.a_real_date`); a
    real one is stored in its canonical form; an update that leaves the date out leaves it alone, and one that sends a blank is refused (a blank cannot
    clear the date of an entry). Whether the date is inside the engagement's year is NOT judged here: that is the door's own rule and is open (the ledger).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.iso_date import a_real_date
from routers.year_end_adjustments import AdjustmentCreateIn, AdjustmentUpdateIn


def _create(**over):
    base = dict(adjustment_type="accrual", description="Accrual for March rent", amount_paise=12_500_000,
                debit_account_id="00000000-0000-4000-8000-0000000000a1", credit_account_id="00000000-0000-4000-8000-0000000000a2",
                adjustment_date="2026-03-31")
    base.update(over)
    return AdjustmentCreateIn(**base)


@pytest.mark.parametrize("bad", ["", "   ", "31/03/2026", "2026-02-30", "2026-3-31x", "year end"])
def test_a_create_date_that_is_not_a_real_day_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        _create(adjustment_date=bad)
    assert "adjustment_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_real_date_is_stored_in_its_canonical_form():
    assert _create(adjustment_date="2026-03-31").adjustment_date == "2026-03-31"
    assert _create(adjustment_date=" 2026-03-31 ").adjustment_date == "2026-03-31"


def test_an_update_that_leaves_the_date_out_leaves_it_alone_and_one_that_sends_it_judges_it():
    assert AdjustmentUpdateIn().adjustment_date is None
    assert "adjustment_date" not in AdjustmentUpdateIn(description="Rent, corrected").model_dump(exclude_unset=True)
    assert AdjustmentUpdateIn(adjustment_date="2026-03-31").adjustment_date == "2026-03-31"
    for bad in ("", "   ", "2026-02-30", "soon"):
        with pytest.raises(ValidationError) as caught:
            AdjustmentUpdateIn(adjustment_date=bad)
        assert "adjustment_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_the_shared_rule_says_which_field_the_caller_sent():
    assert a_real_date("2026-11-05", "start_date") == "2026-11-05"
    with pytest.raises(ValueError, match="start_date must be a date written YYYY-MM-DD."):
        a_real_date("later", "start_date")
