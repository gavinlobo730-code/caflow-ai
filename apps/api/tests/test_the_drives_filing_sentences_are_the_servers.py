"""The sentences the browser drive's stubs speak for a refused filing date are the server's own, word for word (PRE-A-015, the twelfth slice; the MCA and obligation doors added by the thirteenth).

WHAT WAS WRONG
    The drive of the filing prompts (`apps/web/scripts/drive/scenarios/dates.mjs`) has its stub answer a blank date, a date before the period ended and a
    date before the quarter ended in the route's words, and its rows wait for those words on the screen. They were typed by hand, so a reworded server
    sentence would leave the stub and the rows green and the drive would be testing a sentence no server says. The rule is held from the side that owns the
    vocabulary (the Python), the way the Schedule III captions are: the drive's copy is read out of the file and compared with what the door raises.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from routers.tds_workspace import UpdateReturnStatusRequest, _why_this_status_cannot_be_recorded
from services.gst_filing_record_service import FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B, FiledDateRefused, checked_filed_date

DRIVE = Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "scenarios" / "dates.mjs"


def _text() -> str:
    return DRIVE.read_text(encoding="utf-8")


def _literal(name: str, params: str = "") -> str:
    """The text of `const NAME = <params> => `…`;` or `const NAME = "…";` in the drive."""
    arrow = rf"\({params}\) => " if params else ""
    m = re.search(rf"const {name} = {arrow}([`\"])((?:(?!\1).)*)\1", _text(), re.S)
    assert m, f"{name} is no longer written as a constant in dates.mjs, so the drive's copy of the server's sentence cannot be compared"
    return m.group(2)


@pytest.mark.parametrize("form", [FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B])
def test_the_blank_date_sentence_is_what_the_door_raises(form):
    with pytest.raises(FiledDateRefused) as caught:
        checked_filed_date(form, "", period="092026")
    assert _literal("GSTR_FILED_SENTENCE", "form").replace("${form}", form) == caught.value.sentence


@pytest.mark.parametrize("form", [FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B])
def test_the_before_the_period_sentence_is_what_the_door_raises(form):
    with pytest.raises(FiledDateRefused) as caught:
        checked_filed_date(form, "2026-09-15", period="092026")
    drive = _literal("GSTR_BEFORE_PERIOD_SENTENCE", "filed, end").replace("${filed}", "2026-09-15").replace("${end}", "2026-09-30")
    assert drive == caught.value.sentence


def test_the_before_the_quarter_sentence_is_what_the_tds_door_says():
    body = UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="PRN0000000001", filing_date="2026-09-15")
    current = {"status": "ca_approved", "deductee_count": 1, "quarter_end": "2026-09-30", "quarter": "Q2", "financial_year": "2026-27"}
    assert _why_this_status_cannot_be_recorded(body, current, "2026-09-15") == _literal("TDS_BEFORE_QUARTER_SENTENCE")


def test_the_before_the_year_sentence_is_what_the_mca_door_says():
    """The MCA filings (the tracker's Mark Filed, its batch and a client's Mark Filed) are answered with this sentence as an HTTP 200 with success false."""
    from routers.mca_workspace import _judged_filing_date
    day, sentence = _judged_filing_date({"form_type": "AOC-4", "financial_year": None, "period": "FY 2025-26"}, "2026-01-15")
    assert day is None
    assert sentence == _literal("MCA_BEFORE_YEAR_SENTENCE")


def test_the_obligation_door_says_a_date_before_the_period_in_the_same_words_as_the_gst_door():
    """The shared Mark as Filed prompt (Deadlines, a client's Compliance tab, Practice > Compliance) asks the obligation door, which says it in the
    sentence alone (the dialog shows the answer as it stands)."""
    from core.exceptions import ValidationError
    from domain.compliance_record_service import _filed_date_for
    record = {"obligation_type": "GSTR3B", "period_end": "2026-09-30", "status": "Ready To File"}
    with pytest.raises(ValidationError) as caught:
        _filed_date_for(record, {"filed_date": "2026-09-15"})
    drive = _literal("GSTR_BEFORE_PERIOD_SENTENCE", "filed, end").replace("${filed}", "2026-09-15").replace("${end}", "2026-09-30")
    assert caught.value.message == drive

