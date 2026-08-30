"""
The year-end pack must say what it is, and a UDIN must never be manufactured.

TWO PROBLEMS, ONE THEME

The pack carried a Balance Sheet, a Statement of Profit and Loss and Notes, no
auditor's report, and no statement that there was none. To anyone not looking
for the absence it reads as a complete audited set. Its cover also said the
figures came from the "verified General Ledger" — "verified" is an assurance
word, nothing verifies the ledger, and the claim travelled on a document that
leaves the firm.

And there was nowhere to record a UDIN, the number ICAI issues to the member
who signs a document so a holder can verify the signature on ICAI's portal.

WHAT IS DELIBERATELY NOT BUILT

No auditor's report is drafted, and no CARO 2020 findings are generated. Both
are the AUDITOR'S OPINION, formed by a person under section 143 of the
Companies Act 2013 and signed by them. Software emitting draft opinion text
would be manufacturing assurance nobody gave — a worse defect than the one
being fixed, and not one a test could catch once it looked plausible.

Nor is a UDIN generated. It is issued by ICAI's portal against the signing
member's own credentials; a number minted here would be a fabricated
attestation reference on a document asserting a CA signed it, which is
precisely the harm the number exists to prevent.
"""
import pytest

from domain.udin import (
    UDIN_LENGTH, describe_udin_format, is_valid_udin, membership_number,
    normalise_udin,
)

VALID = "19304576AKTSBN1359"      # year 19, membership 304576, portal chars


# ── The UDIN format ──────────────────────────────────────────────────────────

def test_a_real_shaped_udin_is_accepted():
    assert is_valid_udin(VALID) is True
    assert len(VALID) == UDIN_LENGTH


def test_whitespace_and_case_do_not_change_the_number():
    """A CA pasting from the portal brings spaces and mixed case with them.
    Rejecting on that would push them to retype an 18-character string, which
    is how a transposed digit gets onto a signed document."""
    assert normalise_udin("  19304576aktsbn1359 ") == VALID
    assert is_valid_udin(" 19304576 aktsbn1359 ") is True


def test_the_membership_number_can_be_read_back():
    """Shown so a CA sees whose number they entered before the pack is issued,
    while a transposition is still cheap to fix."""
    assert membership_number(VALID) == "304576"


@pytest.mark.parametrize("bad", [
    "",                       # nothing recorded
    None,
    "1930457",                # too short
    "19304576AKTSBN135",      # 17 characters
    "19304576AKTSBN13599",    # 19 characters
    "ABCDEFGH1234567890",     # letters where the year and membership go
    "19304576AKTSBN13!9",     # punctuation in the portal segment
    "x19304576AKTSBN1359",    # embedded in a longer string
])
def test_what_cannot_be_a_udin_is_refused(bad):
    assert is_valid_udin(bad) is False
    assert membership_number(bad) is None


def test_the_format_is_explained_rather_than_merely_refused():
    """A rejected entry must say what was expected, and must say the number
    comes from ICAI rather than from here."""
    text = describe_udin_format()
    assert "18" in text
    assert "membership" in text
    assert "cannot be produced here" in text


def test_nothing_in_the_module_generates_a_udin():
    """The rule this module exists to hold. A generator would be a fabricated
    attestation reference, which is the harm the number prevents."""
    import domain.udin as udin_mod
    names = [n for n in dir(udin_mod) if not n.startswith("_")]
    for banned in ("generate_udin", "create_udin", "new_udin", "mint_udin"):
        assert banned not in names, f"domain.udin exposes {banned}"
    import inspect
    source = inspect.getsource(udin_mod)
    assert "random" not in source and "uuid" not in source, (
        "domain.udin imports a randomness source — a UDIN must come from "
        "ICAI's portal, never from this process"
    )


# ── What the pack says about itself ──────────────────────────────────────────

def _cover_text(eng: dict) -> str:
    """Render just the cover flowables and collect their text. The PDF's own
    content streams are compressed, so the paragraphs are read before they are
    laid out."""
    from services.year_end_pdf_service import _cover_page, _styles
    elements: list = []
    _cover_page(elements, _styles(), eng, "Year-End Pack", is_draft=False)
    return " ".join(getattr(e, "text", "") or "" for e in elements)


ENG = {"id": "E1", "client_name": "Test Client", "financial_year": "2024-25",
       "status": "approved"}


def test_the_pack_says_it_is_not_audited():
    """A Balance Sheet, a P&L and Notes with no auditor's report and no
    statement that there is none reads as a complete audited set."""
    text = _cover_text(ENG)
    assert "not audited" in text
    assert "does not contain" in text and "auditor" in text


def test_the_pack_names_the_two_reports_it_does_not_contain():
    """Naming section 143 and CARO 2020 is what makes the absence checkable
    rather than a general disclaimer."""
    text = _cover_text(ENG)
    assert "143" in text
    assert "Auditor" in text and "2020" in text


def test_the_pack_no_longer_calls_the_ledger_verified():
    """Nothing verifies the ledger — the statements are struck from whatever is
    posted. Using an assurance word on a document that leaves the firm claims
    work that was not done."""
    assert "verified" not in _cover_text(ENG).lower()


def test_a_recorded_udin_is_printed_and_attributed_to_icai():
    text = _cover_text({**ENG, "udin": VALID})
    assert VALID in text
    assert "ICAI UDIN portal" in text
    assert "not generated by this software" in text


def test_no_udin_line_appears_when_none_is_recorded():
    """An empty UDIN label on a signed document invites someone to read the
    blank as "none required"."""
    text = _cover_text(ENG)
    assert "UDIN:" not in text


def test_a_blank_udin_is_treated_as_absent_not_as_a_value():
    for empty in ("", "   ", None):
        assert "UDIN:" not in _cover_text({**ENG, "udin": empty})


# ── Recording a UDIN through the API ─────────────────────────────────────────

def _app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.year_end as ye
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(ye.router)   # the router carries its own /year-end prefix
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f.test", "auth_user_id": "auth-1"}
    return app, ye, TestClient(app, raise_server_exceptions=False)


def test_the_api_records_a_valid_udin():
    app, ye, client = _app()
    ye._MOCK_ENGAGEMENTS["E1"] = {"id": "E1", "firm_id": "F1", "client_id": "C1",
                                  "financial_year": "2024-25", "status": "locked"}
    r = client.patch("/year-end/engagements/E1/udin", json={"udin": VALID})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["udin"] == VALID
    assert data["udin_recorded_at"] is not None
    assert data["udin_recorded_by"] == "u1"


def test_the_api_refuses_a_number_that_cannot_be_a_udin():
    app, ye, client = _app()
    ye._MOCK_ENGAGEMENTS["E2"] = {"id": "E2", "firm_id": "F1", "client_id": "C1",
                                  "financial_year": "2024-25", "status": "locked"}
    r = client.patch("/year-end/engagements/E2/udin", json={"udin": "12345"})
    assert r.status_code == 422
    assert "18 characters" in r.json()["detail"]


def test_a_udin_recorded_in_error_can_be_cleared():
    """A WRONG number on an issued document is worse than none, so removing
    one has to be possible."""
    app, ye, client = _app()
    ye._MOCK_ENGAGEMENTS["E3"] = {"id": "E3", "firm_id": "F1", "client_id": "C1",
                                  "financial_year": "2024-25", "status": "locked"}
    client.patch("/year-end/engagements/E3/udin", json={"udin": VALID})
    r = client.patch("/year-end/engagements/E3/udin", json={"udin": None})
    assert r.status_code == 200
    assert r.json()["data"]["udin"] is None
    assert r.json()["data"]["udin_recorded_at"] is None


def test_a_locked_year_can_still_have_its_udin_recorded():
    """The UDIN is obtained AFTER the statements are signed, which is after the
    year is locked. A lock that blocked it would make the field unreachable in
    the only state it is ever used in."""
    app, ye, client = _app()
    ye._MOCK_ENGAGEMENTS["E4"] = {"id": "E4", "firm_id": "F1", "client_id": "C1",
                                  "financial_year": "2024-25", "status": "locked"}
    r = client.patch("/year-end/engagements/E4/udin", json={"udin": VALID})
    assert r.status_code == 200


def test_another_firms_engagement_is_not_reachable():
    app, ye, client = _app()
    ye._MOCK_ENGAGEMENTS["E5"] = {"id": "E5", "firm_id": "OTHER", "client_id": "C9",
                                  "financial_year": "2024-25", "status": "locked"}
    r = client.patch("/year-end/engagements/E5/udin", json={"udin": VALID})
    assert r.status_code == 404
