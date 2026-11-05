"""The two request models that took a date as a bare string now judge it (PRE-A-015, found by the independent read of the tenth slice).

WHAT WAS WRONG
    `ReconciliationCreateIn` took both statement dates as `str` and compared them as text, and `CreateFilingRequest.original_filing_date` was a bare
    `Optional[str]`. Both reach DATE columns. The screens now refuse a blank or reversed window in a sentence before they ask, but a caller that is
    not the screen (an import, a script, a hand-made request) still reached Postgres with free text, which answers 500 and says nothing a person can
    use. The acknowledgement door had refused this for months (`clean_filed_date`); the earlier return's date did not.

WHAT IS HELD
    A statement date that is not an ISO date is a 422 with a sentence, a reversed window still is, and a valid one is stored as written. The earlier
    return's filing date is a real day that is not in the future (IST), blank is the same as absent, and the sentence names `original_filing_date`.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.ist_clock import ist_today
from models.banking import ReconciliationCreateIn
from routers.itr_workspace import CreateFilingRequest


def _recon(**over):
    base = dict(client_id="c1", bank_account_id="b1", statement_start_date="2026-09-01", statement_end_date="2026-09-30")
    base.update(over)
    return ReconciliationCreateIn(**base)


def _filing(**over):
    base = dict(client_id="c1", financial_year="2025-26", assessment_year="2026-27", itr_form="ITR-3")
    base.update(over)
    return CreateFilingRequest(**base)


@pytest.mark.parametrize("bad", ["", "   ", "30/09/2026", "2026-02-31", "2026-9-1x", "yesterday"])
@pytest.mark.parametrize("which", ["statement_start_date", "statement_end_date"])
def test_a_statement_date_that_is_not_an_iso_date_is_refused_in_a_sentence(which, bad):
    with pytest.raises(ValidationError) as caught:
        _recon(**{which: bad})
    assert "Statement dates are written YYYY-MM-DD." in str(caught.value)


def test_a_valid_window_is_stored_as_written_and_a_reversed_one_is_still_refused():
    r = _recon()
    assert (r.statement_start_date, r.statement_end_date) == ("2026-09-01", "2026-09-30")
    with pytest.raises(ValidationError) as caught:
        _recon(statement_start_date="2026-09-30", statement_end_date="2026-09-01")
    assert "must not precede" in str(caught.value)


@pytest.mark.parametrize("bad", ["20/07/2026", "2026-02-31", "last month"])
def test_an_earlier_returns_filing_date_that_is_not_a_date_is_refused_naming_itself(bad):
    with pytest.raises(ValidationError) as caught:
        _filing(return_type="revised", original_filing_date=bad)
    assert "original_filing_date" in str(caught.value)


def test_an_earlier_returns_filing_date_in_the_future_is_refused():
    tomorrow = ist_today().fromordinal(ist_today().toordinal() + 1).isoformat()
    with pytest.raises(ValidationError) as caught:
        _filing(return_type="revised", original_filing_date=tomorrow)
    assert "original_filing_date cannot be in the future" in str(caught.value)


def test_blank_is_the_same_as_absent_and_a_real_past_date_is_kept():
    assert _filing(return_type="revised", original_filing_date="").original_filing_date is None
    assert _filing(return_type="revised", original_filing_date="   ").original_filing_date is None
    assert _filing(return_type="original").original_filing_date is None
    assert _filing(return_type="revised", original_filing_date="2025-07-20").original_filing_date == "2025-07-20"
