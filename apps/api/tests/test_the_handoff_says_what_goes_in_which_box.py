"""The statutory handoff — the screen a CA works from with the portal open.

Track F, phase F3. Of the seven steps between correct books and a closed
obligation, six are ours and step 4 — the handoff — was the one nothing did.
This file is about the assembly: that the right obligations arise, in the right
order, carrying the warnings that change what a CA does, and NEVER carrying a
credential field.

Everything here is pure. domain/payroll/handoff.py takes figures and returns
panels; it reads no database and reaches no network, which is why the last two
tests can assert those as facts rather than as intentions.
"""
from __future__ import annotations

import pytest

from domain.payroll import handoff as h

MONTH = "2026-09"

ECR_TOTALS = {"members": 12, "gross_wages": 6_00_000, "epf_wages": 1_80_000,
              "eps_wages": 1_80_000, "epf_contribution": 13_140,
              "eps_contribution": 14_994}
ESIC_TOTALS = {"members": 5, "wages_rupees": 75_000, "days": 130}


def _epf(**over):
    args = dict(
        wage_month=MONTH, due_date="2026-10-15",
        establishment_code="MHBAN0012345000", identity_gaps=[],
        file_totals=ECR_TOTALS, edli_paise=90_000, admin_paise=50_000,
        problems=[], filable=True, filename="ECR_202609.txt",
        blocking_months=[], sequence_note=None, required_returns=["regular"],
        return_type_reason=None, interest_note=None, recorded=None)
    args.update(over)
    return h.epf_obligation(**args)


def _esic(**over):
    args = dict(
        wage_month=MONTH, contribution_period="2026-H1", due_date="2026-10-15",
        employer_code="31000123450001099", identity_gaps=[],
        file_totals=ESIC_TOTALS, employee_share_paise=56_300,
        employer_share_paise=2_43_800, problems=[], filable=True,
        filename="ESIC_202609.csv", recorded=None)
    args.update(over)
    return h.esic_obligation(**args)


# ── the period a CA has to find it under ─────────────────────────────────────

def test_a_wage_month_is_spelled_out():
    assert h.month_label("2026-09") == "September 2026"
    assert h.month_label("2027-01") == "January 2027"


def test_the_october_period_spans_the_calendar_year_and_says_so():
    """"2026-H2" means October 2026 to March 2027, which is not what "H2 of
    2026" sounds like to anybody who has not read ESI Rule 50. This screen is
    read under time pressure and the label is the thing a CA searches the portal
    for."""
    assert h.contribution_period_label("2026-H2") == (
        "October 2026 – March 2027 (contribution period 2026-H2)")
    assert h.contribution_period_label("2026-H1") == (
        "April – September 2026 (contribution period 2026-H1)")


def test_the_esic_panel_shows_the_period_beside_the_month():
    """September is filed under 2026-H1, and a CA looking for "September" on
    the portal will not find it."""
    panel = _esic(contribution_period="2026-H1")
    assert "September 2026" in panel.period_label
    assert "April – September 2026" in panel.period_label


# ── a blocked or incomplete month is NOT a withheld file ─────────────────────

def test_a_blocked_month_still_offers_the_file():
    """EPFO's revamped ECR refuses a month while an earlier one is unapproved.
    That is a fact about the UPLOAD, not about the return — the file is correct
    — so it belongs beside the download and never instead of it."""
    panel = _epf(blocking_months=["2026-07", "2026-08"],
                 sequence_note="EPFO is still waiting for 2026-07 and 2026-08.")
    assert panel.artefact.available is True
    assert panel.blocking == ["EPFO is still waiting for 2026-07 and 2026-08."]


def test_a_blocked_month_with_no_note_still_names_the_months():
    panel = _epf(blocking_months=["2026-07"], sequence_note=None)
    assert "2026-07" in panel.blocking[0]


def test_a_missing_establishment_code_does_not_withhold_the_ecr():
    """The code is not a field on the file — EPFO takes the establishment from
    the portal login — so a missing one is a warning, not a refusal."""
    panel = _epf(establishment_code=None,
                 identity_gaps=["No EPF establishment code is recorded."])
    assert panel.artefact.available is True
    assert "No EPF establishment code is recorded." in panel.warnings
    assert panel.identity[0].value is None


def test_an_unfilable_ecr_says_which_members_stopped_it():
    panel = _epf(filable=False, problems=["R. Kumar has no UAN",
                                          "S. Iyer contributed while absent"])
    assert panel.artefact.available is False
    assert "R. Kumar has no UAN" in panel.artefact.why_not
    assert "S. Iyer contributed while absent" in panel.artefact.why_not


def test_an_ecr_with_no_members_says_that_rather_than_nothing():
    """`filable` false with no problems means nobody in the run contributes —
    which is an answer, and a blank panel is not."""
    panel = _epf(filable=False, problems=[])
    assert "no member of this run carries a pf contribution" in (
        panel.artefact.why_not or "").lower()


def test_a_supplementary_return_is_called_out_before_the_upload():
    panel = _epf(required_returns=["regular", "supplementary"],
                 return_type_reason="two members joined after the last filing.")
    assert any("Supplementary" in w for w in panel.warnings)
    assert panel.record_options == ["regular", "supplementary"]


def test_an_ordinary_regular_return_adds_no_noise():
    """ecr_sequence's values are LOWERCASE — REGULAR = "regular". Comparing
    against "Regular" would fire this warning on every ordinary month, which is
    how a real one becomes invisible."""
    assert not any("egular" in w for w in _epf().warnings)
    assert _epf().record_options == ["regular"]


def test_a_month_with_nothing_required_still_offers_a_regular():
    """decide_returns returns an empty tuple when nothing is outstanding. The
    CA is still entitled to record what they filed, so the form must have
    something to default to."""
    assert _epf(required_returns=[]).record_options == ["regular"]


# ── the figures, and whose figures they are ──────────────────────────────────

def test_edli_and_admin_are_marked_as_not_being_in_the_file():
    """They are raised by the portal on the challan, not read off the upload.
    A CA comparing the screen to the challan needs to know which numbers came
    from where, or an honest difference reads as a bug in one of them."""
    by_label = {f.label: f for f in _epf().confirm}
    assert "not in the file" in by_label["EDLI (A/c 21)"].note
    assert "not in the file" in by_label["Administrative charges (A/c 2)"].note
    assert by_label["EDLI (A/c 21)"].amount_paise == 90_000


def test_the_ecr_wage_figures_are_reported_in_rupees_not_paise():
    """The ECR carries whole rupees, because EPFO works in rupees. Converting
    to paise and back would put a unit change inside the one number the CA is
    checking against the portal."""
    by_label = {f.label: f for f in _epf().confirm}
    assert by_label["Total EPF wages"].rupees == 1_80_000
    assert by_label["Total EPF wages"].amount_paise is None


def test_a_headcount_is_a_count_and_not_money():
    by_label = {f.label: f for f in _epf().confirm}
    assert by_label["Members in the file"].count == 12
    assert by_label["Members in the file"].amount_paise is None
    assert by_label["Members in the file"].rupees is None


def test_the_esic_contributions_say_the_portal_computes_its_own():
    """ESIC's manual: "IP Contribution and Employer contribution calculation
    will be automatically done by the system." The file carries days and wages
    only, so ours are a cross-check and are labelled as one."""
    by_label = {f.label: f for f in _esic().confirm}
    assert "our figure" in by_label["Employee share (0.75%)"].note
    assert "our figure" in by_label["Employer share (3.25%)"].note


def test_the_esic_shares_carry_the_rounding_rule():
    """Both shares round UP to the next whole rupee — the opposite direction to
    the GST discount rounding, and the reason _compute_esi was wrong until
    2026-09-11."""
    by_label = {f.label: f for f in _esic().confirm}
    assert "rounded UP" in by_label["Employee share (0.75%)"].note


# ── the three ESIC facts that change what a CA does ──────────────────────────

def test_the_esic_panel_warns_that_a_submission_cannot_be_reduced():
    """"No way contribution amount submitted during monthly contribution will
    reduce" — a supplementary can only ADD. The confirm screen at ESIC is the
    last moment an over-declaration can be stopped."""
    assert h.ESIC_IRREVERSIBLE in _esic().warnings


def test_the_esic_panel_warns_that_the_upload_is_all_or_nothing():
    assert h.ESIC_ALL_OR_NOTHING in _esic().warnings


def test_the_esic_panel_warns_that_a_zero_de_registers_somebody():
    """A zero-wage row does not report an unpaid month — it takes the insured
    person off the establishment, and they stop being listed afterwards."""
    assert h.ESIC_ZERO_REMOVES in _esic().warnings


def test_those_three_warnings_are_there_even_when_everything_is_clean():
    panel = _esic(identity_gaps=[], problems=[], filable=True)
    assert len(panel.warnings) == 3


# ── professional tax: one state, one authority, one challan ──────────────────

def _pt(**over):
    args = dict(wage_month=MONTH,
                by_state={"MAHARASHTRA": 40_000, "KARNATAKA": 20_000},
                headcount_by_state={"MAHARASHTRA": 2, "KARNATAKA": 1},
                registrations=[{"state": "Maharashtra",
                                "ptrc_number": "27999999999P"}],
                recorded_by_state=None)
    args.update(over)
    return h.professional_tax_obligations(**args)


def test_two_states_are_two_panels():
    """Two authorities, two due dates, two registration certificates, two
    challans. One "professional tax: ₹600" row is not a smaller version of
    that — it is a figure nobody can pay."""
    panels = _pt()
    assert [p.state for p in panels] == ["KARNATAKA", "MAHARASHTRA"]
    assert len({p.key for p in panels}) == 2


def test_a_state_with_no_deduction_raises_no_panel():
    assert _pt(by_state={}, headcount_by_state={}) == []


def test_professional_tax_shows_no_due_date_and_says_why():
    """compliance_engine.payroll_deposit_due_dates excludes PT for this reason:
    each state fixes its own and there is no rule to derive. A wrong date in a
    CA's calendar is worse than a missing one."""
    panel = _pt()[0]
    assert panel.due_date is None
    assert "each state fixes its own" in panel.due_note


def test_professional_tax_offers_no_file_and_says_why():
    """Nothing in this product produces a PT challan or return for any state
    (Track F, phase F5). Saying so beats a download button that is not there."""
    panel = _pt()[0]
    assert panel.artefact.available is False
    assert "does not produce a professional-tax challan" in panel.artefact.why_not


def test_a_state_with_no_ptrc_is_blocked_and_named():
    karnataka = _pt()[0]
    assert karnataka.state == "KARNATAKA"
    assert karnataka.identity[0].value is None
    assert any("No PTRC is recorded for Karnataka" in b
               for b in karnataka.blocking)


def test_a_state_with_a_ptrc_is_not_blocked():
    maharashtra = _pt()[1]
    assert maharashtra.identity[0].value == "27999999999P"
    assert maharashtra.blocking == []


def test_the_ptrc_is_matched_however_the_state_was_capitalised():
    panels = h.professional_tax_obligations(
        wage_month=MONTH, by_state={"MAHARASHTRA": 40_000},
        headcount_by_state={"MAHARASHTRA": 2},
        registrations=[{"state": "  maharashtra  ",
                        "ptrc_number": "27999999999P"}])
    assert panels[0].blocking == []


def test_the_panel_asks_for_a_ptrc_and_not_a_ptec():
    """The Registration Certificate is the employer's authority to deduct and
    deposit; the Enrolment Certificate is the entity's own levy on itself.
    Showing the wrong one sends a CA to the portal with a number that will not
    work."""
    label = _pt()[0].identity[0]
    assert label.label == "PTRC number"
    assert "Not the PTEC" in label.note


def test_a_recorded_remittance_comes_back_on_its_own_state_panel():
    panels = _pt(recorded_by_state={"MAHARASHTRA": {"challan_number": "MH-77"}})
    by_state = {p.state: p for p in panels}
    assert by_state["MAHARASHTRA"].recorded == {"challan_number": "MH-77"}
    assert by_state["KARNATAKA"].recorded is None


# ── what no panel may ever contain ───────────────────────────────────────────

CREDENTIAL_WORDS = ("password", "passcode", "otp", "one-time password", "pin",
                    "captcha", "username", "user id", "login id", "credential",
                    "dsc pin", "evc")


def _every_panel():
    return [_epf(), _esic(), *_pt()]


@pytest.mark.parametrize("word", CREDENTIAL_WORDS)
def test_no_panel_asks_for_a_credential(word):
    """THE RULE, NOT A SPELLING OF IT.

    A password box in this product is a credential-capture surface whatever it
    is labelled, and an OTP is typed on the portal, never in the software that
    prepared the return. This asserts it structurally: no field a CA could fill
    in, on any panel, is named after a secret.

    `record_back` is the one thing the CA types, and it is deliberately an
    acknowledgement — a TRRN or a challan number — which is a receipt, not a
    credential.
    """
    for panel in _every_panel():
        for f in panel.identity:
            assert word not in f.label.lower(), f"{panel.key}: {f.label}"
        assert word not in (panel.record_back or "").lower(), panel.key
        assert word not in panel.title.lower(), panel.key


def test_every_panel_ends_in_recording_something_the_portal_gave_back():
    for panel in _every_panel():
        assert panel.record_back, f"{panel.key} has no acknowledgement to record"


def test_the_module_reaches_no_network():
    """Nothing here transmits, and that is checked rather than asserted in
    prose. There is no EPFO, ESIC or state professional-tax API a CA firm can
    hold — see docs/compliance/08-… — so a network import in this module would
    be a bug before it was a policy breach."""
    import pathlib
    src = pathlib.Path(h.__file__).read_text()
    for banned in ("import requests", "import httpx", "urllib", "http.client",
                   "aiohttp", "socket"):
        assert banned not in src, f"{banned} has no business in the handoff"


def test_the_professional_tax_portal_is_not_named_as_one_host():
    """Twenty-two states, twenty-two sites. Naming one would send a CA in
    Karnataka to Maharashtra's portal."""
    assert h.PORTALS[h.PROFESSIONAL_TAX][1] == ""
    assert _pt()[0].portal_host == ""


def test_the_epfo_and_esic_hosts_are_the_real_ones():
    assert _epf().portal_host == "unifiedportal-emp.epfindia.gov.in"
    assert _esic().portal_host == "esic.gov.in"


def test_every_panel_serialises_to_json_safe_primitives():
    """The screen renders this, so a dataclass that leaked through would be a
    500 on a page a CA is holding open beside a government portal."""
    import json
    for panel in _every_panel():
        json.dumps(panel.to_dict())
