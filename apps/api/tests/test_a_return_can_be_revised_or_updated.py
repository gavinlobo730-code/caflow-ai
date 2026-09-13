"""
A RETURN OF INCOME HAS THREE KINDS, and this product held one. IT-23's fourth
limb, migration 381.

WHAT WAS WRONG
    IT Act 1961 s. 139(1) is the ORIGINAL return, s. 139(5) the REVISED return
    and s. 139(8A) the UPDATED return (ITR-U). `itr_filings` had no column
    saying which — and could not have had a second row anyway, because
    migration 319 declares `UNIQUE (firm_id, client_id, financial_year,
    itr_form)` on that table. A revised return has to sit BESIDE the original:
    the original's acknowledgement number and date are fields on the revised
    return's own form, and the register has to show both.

    So a practice that revises a return, which is an ordinary week's work, had
    nowhere to record it. The finding itself did not mention the constraint.

WHAT IS ASSERTED HERE, AND WHAT IS DELIBERATELY NOT
    The three KINDS, what each requires of the document, and the refusals are
    settled law and are pinned exactly.

    The two WINDOWS and s. 140B's bands are `[S]` — read from knowledge, not
    confirmed against the bare Act, because egress is refused at this
    environment's proxy. So what is pinned about them is the SHAPE that makes
    a wrong figure visible rather than silent: that both readings of s. 139(8A)
    are reported where they disagree, that every answer carries its caveats,
    that the s. 139(5) answer names the limb this product cannot see, and that
    s. 140B REFUSES a year the table does not hold rather than falling back
    onto a neighbour's percentages. A test that asserted "48 months" as
    correct would be asserting the same unverified reading twice.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.income_tax import return_type as RT


# ── The three kinds ──────────────────────────────────────────────────────────

def test_the_three_kinds_and_their_sections():
    assert RT.RETURN_TYPES == ("original", "revised", "updated")
    assert RT.SECTION_FOR_TYPE == {
        "original": "s. 139(1)",
        "revised": "s. 139(5)",
        "updated": "s. 139(8A)",
    }


@pytest.mark.parametrize("given,expected", [
    (None, "original"), ("", "original"), ("  ", "original"),
    ("revised", "revised"), (" Revised ", "revised"), ("UPDATED", "updated"),
])
def test_a_kind_is_canonicalised_on_the_way_in(given, expected):
    """Tolerant in, CANONICAL out — the value is STORED and then filtered on,
    so two spellings of one kind read as two kinds once the table holds both.
    The same argument `itr_workflow.validated_form` makes for the form."""
    assert RT.validated_return_type(given) == expected


def test_an_unknown_kind_is_refused_naming_the_three():
    with pytest.raises(ValueError) as ei:
        RT.validated_return_type("belated")
    for word in ("original", "revised", "updated", "139(8A)"):
        assert word in str(ei.value)


def test_an_original_has_no_window_of_this_sort():
    """s. 139(1)'s own due date is `compliance_engine.itr_due_date`, and a
    belated return under s. 139(4) is a different question again. Answering
    None is what stops this module inventing a third."""
    assert RT.window_for("original", "2026-27") is None


# ── s. 139(5): the revised return ────────────────────────────────────────────

def test_the_revised_window_shuts_on_31_december_of_the_assessment_year():
    w = RT.revised_return_window("2026-27", as_at=date(2026, 9, 13))
    assert w.closes_on == "2026-12-31"
    assert w.is_open is True


def test_the_revised_window_is_shut_the_day_after():
    assert RT.revised_return_window("2026-27", as_at=date(2026, 12, 31)).is_open
    assert not RT.revised_return_window("2026-27", as_at=date(2027, 1, 1)).is_open


def test_the_revised_answer_names_the_limb_this_product_cannot_see():
    """s. 139(5) shuts the window at 31 December OR the completion of the
    assessment, WHICHEVER IS EARLIER. No assessment order is recorded against
    a client here, so an answer of 'open' means 'open unless the assessment is
    complete' — and it has to say so, because the missing limb can only make
    the window shut sooner."""
    w = RT.revised_return_window("2026-27", as_at=date(2026, 9, 13))
    assert any("COMPLETION OF THE ASSESSMENT" in g for g in w.gaps)
    assert w.caveats, "the [S] grade must reach the answer"


# ── s. 139(8A): the updated return ───────────────────────────────────────────

def test_the_updated_window_reports_both_readings():
    """TWO DATES, NOT ONE. The Finance Act 2025 took the window from 24 months
    to 48; what it did to an assessment year whose 24-month window had already
    closed could not be read here. Reporting only the longer date would tell a
    CA a window is open that may have shut — the direction that costs a
    filing — and only the shorter would refuse work the Act now allows."""
    w = RT.updated_return_window("2026-27", as_at=date(2026, 9, 13))
    # AY 2026-27 ends 31-03-2027.
    assert w.closes_on == "2031-03-31"
    assert w.alternative_closes_on == "2029-03-31"


def test_where_the_two_readings_disagree_the_answer_is_neither_open_nor_shut():
    """AY 2022-23 ended 31-03-2023: 24 months closed 31-03-2025 and 48 months
    closes 31-03-2027. Today falls between them, so `is_open` is None and the
    disagreement is NAMED rather than resolved silently."""
    w = RT.updated_return_window("2022-23", as_at=date(2026, 9, 13))
    assert w.is_open is None
    assert w.closes_on == "2027-03-31"
    assert w.alternative_closes_on == "2025-03-31"
    assert any("disagree" in g for g in w.gaps)


def test_where_the_two_readings_agree_the_answer_is_definite():
    w = RT.updated_return_window("2026-27", as_at=date(2026, 9, 13))
    assert w.is_open is True and not w.gaps
    shut = RT.updated_return_window("2022-23", as_at=date(2040, 1, 1))
    assert shut.is_open is False and not shut.gaps


def test_an_assessment_year_before_the_section_existed_says_so():
    """s. 139(8A) was inserted by the Finance Act 2022 and reaches AY 2020-21
    onwards. 'There is no updated return for this year' is a DIFFERENT answer
    from 'the window has closed', and is given differently."""
    w = RT.updated_return_window("2019-20", as_at=date(2026, 9, 13))
    assert w.is_open is False and w.closes_on is None
    assert any("2020-21" in c for c in w.caveats)


# ── s. 140B ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("furnished,months", [
    # AY 2024-25 ends 31-03-2025.
    # WELL inside the assessment year, which is the case the short-circuit is
    # for: a plain month difference would answer -9 here, and -9 falls in the
    # first band, so the nonsense would be charged at 25% rather than caught.
    ("2024-06-15", 0),
    ("2025-03-31", 0),      # the last day of the assessment year
    ("2025-04-01", 1),      # April has begun, so one month has
    ("2026-03-31", 12),     # exactly twelve
    ("2026-04-01", 13),     # one day past it
])
def test_the_months_are_counted_from_the_end_of_the_assessment_year(furnished, months):
    assert RT.months_from_ay_end("2024-25", date.fromisoformat(furnished)) == months


def test_the_band_turns_over_on_the_anniversary_not_after_it():
    """'within twelve months from the end of the relevant assessment year' —
    so 31-03-2026 is inside the first band for AY 2024-25 and 01-04-2026 is
    not. The anchor being the last day of March is what puts the boundary
    exactly there with a plain month difference."""
    inside = RT.additional_tax("2024-25", date(2026, 3, 31), 100_00, 0)
    outside = RT.additional_tax("2024-25", date(2026, 4, 1), 100_00, 0)
    assert inside.percent == 25
    assert outside.percent == 50


def test_the_base_is_tax_plus_interest_not_tax_alone():
    """s. 140B(3) charges on 'the aggregate of tax and interest payable'.
    Charging on the tax alone understates what the client pays over on every
    late updated return."""
    r = RT.additional_tax("2024-25", date(2026, 3, 31), 10_000_00, 1_000_00)
    assert r.base_paise == 11_000_00
    assert r.additional_tax_paise == 2_750_00


def test_the_charge_rounds_up():
    """A sum the assessee OWES. Understating it leaves a residual demand with
    its own interest running — the same direction ESI takes, and the opposite
    of the GST discount, which floors because there flooring cannot
    under-declare tax."""
    r = RT.additional_tax("2024-25", date(2026, 3, 31), 3, 0)   # 25% of 3 paise
    assert r.additional_tax_paise == 1


def test_a_year_the_table_does_not_hold_is_refused_not_substituted():
    """EVERY sibling registry in domain/income_tax falls back to
    LATEST_VERIFIED_FY for a missing year, which turns a gap into a
    confidently wrong number. This is additional tax a client PAYS OVER, so
    the answer is a sentence instead — the same refusal
    `late_filing.SECTION_50_3_NOTIFIED_RATE_BPS` makes."""
    r = RT.additional_tax("2031-32", date(2033, 4, 1), 10_000_00, 0)
    assert r.additional_tax_paise is None
    assert r.percent is None
    assert "2031-32" in r.refusal and "Finance Act" in r.refusal


def test_past_the_last_band_there_is_no_charge_because_there_is_no_return():
    r = RT.additional_tax("2024-25", date(2035, 1, 1), 10_000_00, 0)
    assert r.additional_tax_paise is None
    assert "no updated return can be furnished" in r.refusal


def test_the_first_section_139_8a_year_has_only_the_two_original_bands():
    """AY 2020-21 could only ever have been furnished inside the 24-month
    window, so 60% and 70% describe a band that did not exist for it."""
    assert [b.percent for b in RT.ADDITIONAL_TAX_BANDS_BY_AY["2020-21"]] == [25, 50]


def test_no_year_is_claimed_as_verified():
    """`LATEST_VERIFIED_AY` is None, which is the same statement
    `tax_audit.LATEST_VERIFIED_FY` makes: nobody has read these percentages
    off a Finance Act."""
    assert RT.LATEST_VERIFIED_AY is None


def test_every_computed_answer_carries_its_caveats():
    r = RT.additional_tax("2024-25", date(2026, 3, 31), 10_000_00, 0)
    joined = " ".join(r.caveats)
    assert "[S]" in joined
    assert "140B(2)" in joined, "the credit for tax already paid must be named"


# ── The workflow ─────────────────────────────────────────────────────────────

@pytest.fixture
def workflow(monkeypatch):
    from domain.income_tax import itr_workflow as w
    monkeypatch.setattr(w, "_USE_MOCK", True)
    w._MOCK_FILINGS.clear()
    return w


def test_a_filing_created_without_a_kind_is_an_original(workflow):
    """The column defaults to 'original' and so does the call, so every caller
    written before migration 381 keeps creating exactly what it created."""
    f = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U")
    assert f["return_type"] == "original"
    assert f["original_acknowledgement_number"] is None
    assert f["original_filing_date"] is None


def test_a_revised_return_without_the_earlier_receipt_is_refused(workflow):
    """s. 139(5) reaches a person 'having furnished a return', and both the
    revised return and ITR-U carry the earlier receipt as fields of their own.
    A return without them cannot be filed, so it is refused at creation rather
    than at the portal."""
    with pytest.raises(workflow.ITRWorkflowError) as ei:
        workflow.create_itr_filing(
            firm_id="F", client_id="C", financial_year="2025-26",
            assessment_year="2026-27", itr_form="ITR-6", created_by="U",
            return_type="revised")
    assert "acknowledgement number" in str(ei.value)
    assert "filing date" in str(ei.value)


def test_a_revised_return_reads_the_receipt_off_the_original_it_names(workflow):
    """SERVED, not re-typed — the same reasoning `domain/tds/deductor.resolve`
    gives for the TAN. The CA already recorded the acknowledgement when the
    original was filed."""
    original = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U")
    original["acknowledgement_number"] = "123456789012345"
    original["filing_date"] = "2026-07-20"

    revised = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U",
        return_type="revised", original_filing_id=original["id"])
    assert revised["return_type"] == "revised"
    assert revised["original_acknowledgement_number"] == "123456789012345"
    assert revised["original_filing_date"] == "2026-07-20"
    assert revised["original_filing_id"] == original["id"]


def test_what_the_caller_typed_wins_over_what_is_on_file(workflow):
    """A CA correcting a mis-keyed acknowledgement must be able to."""
    original = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U")
    original["acknowledgement_number"] = "WRONGNUMBER0001"
    original["filing_date"] = "2026-07-20"
    revised = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U",
        return_type="revised", original_filing_id=original["id"],
        original_acknowledgement_number="123456789012345")
    assert revised["original_acknowledgement_number"] == "123456789012345"
    assert revised["original_filing_date"] == "2026-07-20"   # still read


def test_an_original_stores_no_earlier_receipt_however_it_is_called(workflow):
    """Meaningless on an original, and stored as absent rather than as
    whatever a caller happened to send."""
    f = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="U",
        return_type="original", original_filing_id="whatever",
        original_acknowledgement_number="123456789012345",
        original_filing_date="2026-07-20")
    assert f["original_acknowledgement_number"] is None
    assert f["original_filing_date"] is None
    assert f["original_filing_id"] is None


def test_a_second_updated_return_WARNS_rather_than_refusing(workflow):
    """s. 139(8A) bars a second updated return for an assessment year, and the
    bar is about a return FURNISHED. A draft being prepared is not one, which
    is why migration 381 puts no unique index on it — a constraint cannot see
    the difference and would refuse a CA who deleted a draft and started
    again. The provisos are beyond this product, the portal enforces the bar
    anyway, and refusing wrongly stops lawful work while allowing wrongly
    costs a rejection the CA sees at once."""
    first = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2021-22",
        assessment_year="2022-23", itr_form="ITR-6", created_by="U",
        return_type="updated", original_acknowledgement_number="1",
        original_filing_date="2022-07-20")
    assert workflow.already_furnished_updated_return("F", "C", "2021-22") is None, (
        "a DRAFT updated return is not one that has been furnished")

    first["status"] = "filed"
    first["acknowledgement_number"] = "999888777666555"
    warning = workflow.already_furnished_updated_return("F", "C", "2021-22")
    assert warning and "999888777666555" in warning and "139(8A)" in warning
    # And it does not warn about ITSELF.
    assert workflow.already_furnished_updated_return(
        "F", "C", "2021-22", exclude_filing_id=first["id"]) is None


def test_the_warning_is_scoped_to_the_year_and_the_client(workflow):
    filed = workflow.create_itr_filing(
        firm_id="F", client_id="C", financial_year="2021-22",
        assessment_year="2022-23", itr_form="ITR-6", created_by="U",
        return_type="updated", original_acknowledgement_number="1",
        original_filing_date="2022-07-20")
    filed["status"] = "filed"
    assert workflow.already_furnished_updated_return("F", "C", "2022-23") is None
    assert workflow.already_furnished_updated_return("F", "OTHER", "2021-22") is None


# ── The endpoint ─────────────────────────────────────────────────────────────

_USER = {"firm_id": "F", "id": "U", "role": "Partner", "auth_user_id": "a"}


def test_the_endpoint_serves_the_kinds_and_their_windows():
    from routers.itr_workspace import list_return_kinds
    body = list_return_kinds(assessment_year="2026-27", furnished_on=None,
                             tax_paise=0, interest_paise=0,
                             current_user=_USER)["data"]
    kinds = {k["return_type"]: k for k in body["kinds"]}
    assert set(kinds) == set(RT.RETURN_TYPES)
    assert kinds["original"]["window"] is None
    assert kinds["revised"]["window"]["closes_on"] == "2026-12-31"
    assert kinds["updated"]["window"]["alternative_closes_on"] == "2029-03-31"
    assert kinds["revised"]["needs_the_earlier_receipt"] is True
    assert kinds["original"]["needs_the_earlier_receipt"] is False


def test_the_endpoint_answers_section_140b_only_when_asked():
    from routers.itr_workspace import list_return_kinds
    quiet = list_return_kinds(assessment_year="2024-25", furnished_on=None,
                              tax_paise=0, interest_paise=0,
                              current_user=_USER)["data"]
    assert quiet["additional_tax"] is None

    asked = list_return_kinds(assessment_year="2024-25",
                              furnished_on="2026-03-31",
                              tax_paise=10_000_00, interest_paise=1_000_00,
                              current_user=_USER)["data"]["additional_tax"]
    assert asked["percent"] == 25
    assert asked["additional_tax_paise"] == 2_750_00
    assert asked["caveats"]


def test_the_endpoint_says_no_year_is_verified():
    from routers.itr_workspace import list_return_kinds
    body = list_return_kinds(assessment_year="2026-27", furnished_on=None,
                             tax_paise=0, interest_paise=0,
                             current_user=_USER)["data"]
    assert body["additional_tax_verified_through_ay"] is None


def test_a_bad_furnished_on_is_a_422_not_a_500():
    from fastapi import HTTPException

    from routers.itr_workspace import list_return_kinds
    with pytest.raises(HTTPException) as ei:
        list_return_kinds(assessment_year="2026-27", furnished_on="20 July",
                          tax_paise=0, interest_paise=0, current_user=_USER)
    assert ei.value.status_code == 422


# ── The screen ───────────────────────────────────────────────────────────────

def test_the_screen_asks_for_the_kinds_rather_than_deriving_the_windows():
    """A window is STATUTE. The browser copy is a LABEL table only — the same
    rule the ITR form list follows, and the reason
    `apps/api/tests/test_the_browser_fallback_speaks_the_engines_vocabulary.py`
    exists for the Schedule III captions.
    """
    import pathlib
    page = (pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
            / "app" / "clients" / "[id]" / "tax" / "filing" / "page.tsx")
    src = page.read_text(encoding="utf-8")
    assert "/api/itr/return-kinds" in src, "the screen must ask"
    assert "return_type: kind" in src, "the create call must send the kind"
    for spelled_out in ("139(5)", "139(8A)"):
        assert spelled_out in src, "the fallback labels name their sections"
    # The DATES must not be in the browser at all.
    for a_date in ("12-31", "December 31", "48 months", "24 months"):
        assert a_date not in src, (
            f"{a_date!r} is in the screen — the windows are the server's "
            f"answer, and a second copy is one that can disagree")
