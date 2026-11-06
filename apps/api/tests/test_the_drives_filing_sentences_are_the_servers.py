"""The sentences the browser drive's stubs speak for a refused filing date are the server's own, word for word (PRE-A-015, the twelfth slice; the MCA and obligation doors added by the thirteenth; the two "could not" sentences of the client MCA and TDS forms by the fourteenth).

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

SCENARIOS = Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "scenarios"
DRIVE = SCENARIOS / "dates.mjs"
#: The drive of the statement the product holds back (POST-A-402) speaks the status door's sentences too.
HELD_BACK_DRIVE = SCENARIOS / "heldBackStatement.mjs"


def _text(path: Path = DRIVE) -> str:
    return path.read_text(encoding="utf-8")


def _literal(name: str, params: str = "", path: Path = DRIVE) -> str:
    """The text of `const NAME = <params> => `…`;` or `const NAME = "…";` in the drive."""
    arrow = rf"\({params}\) => " if params else ""
    m = re.search(rf"const {name} = {arrow}([`\"])((?:(?!\1).)*)\1", _text(path), re.S)
    assert m, f"{name} is no longer written as a constant in {path.name}, so the drive's copy of the server's sentence cannot be compared"
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



def test_the_mca_door_says_what_the_drive_says_when_its_insert_fails():
    """A client's MCA tab creates a company and a filing through two doors that answer a failed insert with this one sentence (an HTTP 200 with success false), which the forms show."""
    import inspect
    from routers import mca_workspace
    sentence = _literal("MCA_COULD_NOT_SENTENCE")
    for door in (mca_workspace.create_company, mca_workspace.create_filing, mca_workspace.create_director):
        assert f'api_response(False, None, "{sentence}")' in inspect.getsource(door), f"{door.__name__} no longer answers a failed insert with the drive's sentence"


def test_the_mca_door_says_what_the_drive_says_when_a_director_is_added_twice():
    """The ordinary refusal of the Add Director form (migration 038's UNIQUE (client_id, din)): an HTTP 200 with success false, shown in the form."""
    import inspect
    from routers import mca_workspace
    assert f'"{_literal("MCA_DUPLICATE_DIN_SENTENCE")}"' in inspect.getsource(mca_workspace.create_director)


def test_the_tds_door_says_what_the_drive_says_for_a_challan_nobody_anticipated():
    from routers.tds_workspace import _could_not
    answer = _could_not(RuntimeError("something nobody anticipated"), "record the TDS challan")
    assert answer["error"] == _literal("TDS_COULD_NOT_CHALLAN_SENTENCE")


def test_the_404_the_client_forms_are_refused_with_is_what_the_client_scope_check_raises():
    """The create doors of a client's MCA and TDS tabs re-raise `assert_client_access`'s 404 for a client the caller is not assigned to (inside their `try`, through `except HTTPException: raise`)."""
    import inspect
    from core.authz import assert_client_access
    assert inspect.signature(assert_client_access).parameters["detail"].default == _literal("CLIENT_NOT_FOUND_SENTENCE")


def test_the_statutory_values_door_says_a_hole_in_the_bands_in_the_drives_words():
    """The statutory values screen shows the door's refusal of a slab set that does not start at zero (an HTTP 422 whose detail is this sentence) inside its dialog."""
    from fastapi import HTTPException
    from models.payroll import PTSlabSetIn
    from routers.payroll import put_pt_slabs
    body = PTSlabSetIn(state="GJ", effective_from="2027-04-01", notification_reference="PFT/1", notification_date="2026-03-10",
                       bands=[{"from_paise": 10000, "to_paise": None, "amount_paise": 20000}])
    with pytest.raises(HTTPException) as caught:
        put_pt_slabs(body, {"firm_id": "F1", "role": "Partner", "id": "u1"})
    assert caught.value.status_code == 422
    assert caught.value.detail == _literal("PT_UNCOVERED_SENTENCE")


# ── the nine writes of a client's compliance pages that used to drop their answer (POST-A-391) ─────────────────────────────────────────────────────────────

COMPLIANCE_ANSWERS = Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "scenarios" / "complianceAnswers.mjs"


def _compliance_literal(name: str) -> str:
    """The text of `const NAME = "…";` in the drive module that refuses those nine writes."""
    m = re.search(rf"const {name} = ([`\"])((?:(?!\1).)*)\1", COMPLIANCE_ANSWERS.read_text(encoding="utf-8"), re.S)
    assert m, f"{name} is no longer written as a constant in complianceAnswers.mjs, so the drive's copy of the server's sentence cannot be compared"
    return m.group(2)


def test_the_mca_doors_that_change_a_row_say_what_the_drive_says_when_they_fail():
    """A director's KYC change and a filing's status change answer a failed update with this one sentence (an HTTP 200 with success false), which the page now says above its table."""
    import inspect
    from routers import mca_workspace
    sentence = _compliance_literal("MCA_COULD_NOT_SENTENCE")
    assert sentence == _literal("MCA_COULD_NOT_SENTENCE"), "the two drive modules speak different sentences for one MCA door"
    for door in (mca_workspace.update_director, mca_workspace.update_filing_status):
        assert f'api_response(False, None, "{sentence}")' in inspect.getsource(door), f"{door.__name__} no longer answers a failed update with the drive's sentence"


def test_the_compliance_drive_modules_not_found_sentence_is_the_one_the_client_check_raises():
    """The answers the drive refuses with a status (a 404) are `assert_client_access`'s; the new module keeps its own copy of the sentence, so it is pinned to the other module's, which is pinned to the server."""
    assert _compliance_literal("CLIENT_NOT_FOUND_SENTENCE") == _literal("CLIENT_NOT_FOUND_SENTENCE")


def test_the_gst_doors_that_save_a_return_say_what_the_drive_says_when_they_fail():
    """Creating a GSTR-1 or a GSTR-3B, and saving one computed from the books, go through these two doors, which answer a failure with this sentence (an HTTP 200 with success false)."""
    import inspect
    from routers import gst_workspace
    sentence = _compliance_literal("GST_COULD_NOT_SENTENCE")
    for door in (gst_workspace.save_gstr1, gst_workspace.save_gstr3b):
        assert f'api_response(False, None, "{sentence}")' in inspect.getsource(door), f"{door.__name__} no longer answers a failure with the drive's sentence"


def test_the_tds_doors_say_what_the_drive_says_when_a_status_change_or_a_save_fails():
    """A TDS return's status change is worded by `_could_not`; the save of a quarter's statement (a new return, or one computed from the books) by `create_return`'s own fallback."""
    import inspect
    from routers.tds_workspace import _could_not, _statement_label, create_return, update_return_status
    assert _could_not(RuntimeError("something nobody anticipated"), "update the TDS return status")["error"] == _compliance_literal("TDS_COULD_NOT_STATUS_SENTENCE")
    # …and the status door is the one that speaks it, with that action (a hard-coded call above would pass whatever the door did)
    assert '_could_not(e, "update the TDS return status")' in inspect.getsource(update_return_status), "update_return_status no longer answers a failure with _could_not and the action the drive speaks"
    label = _statement_label("26Q", "2025-26")
    drive = _compliance_literal("TDS_COULD_NOT_SAVE_SENTENCE")
    assert drive == f"Could not save {label} for Q1 FY 2025-26. The cause has been logged; please try again, and report it if it keeps failing."
    source = inspect.getsource(create_return)
    for piece in ('f"Could not save {label} for {body.quarter} FY "', 'f"{body.financial_year}. The cause has been logged; please try "', 'f"again, and report it if it keeps failing."'):
        assert piece in source, f"create_return no longer words its fallback as the drive does: {piece}"


def test_the_held_back_statement_sentences_and_marker_are_what_the_tds_door_says():
    """The drive of the statement the product holds back (heldBackStatement.mjs) has its stub answer the first press in the status door's words and with its marker, and its rows wait
    for those words on the screen: a reworded sentence or a changed marker would leave the stub and the rows green and the drive would be testing an answer no server gives."""
    from routers.tds_workspace import _the_refusal
    current = {"status": "prepared", "deductee_count": 0, "quarter_end": "2025-06-30", "quarter": "Q1", "financial_year": "2025-26"}
    approval = _the_refusal(UpdateReturnStatusRequest(status="ca_approved", ca_approved=True), current, None)
    assert approval.sentence == _literal("HELD_BACK_APPROVAL", path=HELD_BACK_DRIVE)
    filing = _the_refusal(UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="PRN0000000001", filing_date="2026-10-07"),
                          {**current, "status": "ca_approved"}, "2026-10-07")
    assert filing.sentence == _literal("HELD_BACK_FILING", path=HELD_BACK_DRIVE)
    # the marker, as the drive writes it: `{ can_record_anyway: true, incomplete: ["…"] }`
    drive_marker = re.search(r"const MARKER = \{ can_record_anyway: true, incomplete: \[(?P<items>[^\]]*)\] \};", _text(HELD_BACK_DRIVE))
    assert drive_marker, "the drive no longer writes the marker as `{ can_record_anyway: true, incomplete: [...] }`"
    drive_items = re.findall(r'"([^"]*)"', drive_marker.group("items"))
    assert approval.marker() == {"can_record_anyway": True, "incomplete": drive_items}
    # …and a refusal that offers no way on has no marker at all, which is what the drive's ALREADY_FILED stub answers
    already = _the_refusal(UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="1", filing_date="2026-10-07"), {**current, "status": "filed"}, "2026-10-07")
    assert already.sentence == _literal("ALREADY_FILED", path=HELD_BACK_DRIVE) and already.marker() is None
