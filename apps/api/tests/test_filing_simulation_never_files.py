"""The filing demo must never be able to claim a return was filed.

WHY THIS EXISTS
    PracticeSync prepares GSTR-1 and GSTR-3B and produces the GSTN JSON. The CA
    uploads it to gst.gov.in and signs there. Real API filing needs GSP
    registration and is not built.

    So that the intended flow can be SHOWN before it exists, there is a
    simulation endpoint that plays back the steps. That is a reasonable thing to
    demo and a dangerous thing to leave lying around: the person demoing knows
    it is a mock; whoever opens the same screen next week does not. A return
    believed filed and not filed accrues Rs 50 a day under §47 from its real due
    date, and the correction window under §37(3)/§39(9) runs out regardless.

    Everything below is therefore about what the simulation must NOT do. The
    steps it returns are decoration; these are the contract.
"""
from __future__ import annotations

import pytest

from routers import gst_workspace as gw


@pytest.fixture()
def sim_on(monkeypatch):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "true")
    return True


# ── Off by default ──────────────────────────────────────────────────────────

def test_it_is_off_unless_switched_on(monkeypatch):
    """A demo affordance that ships enabled is a demo affordance in production."""
    monkeypatch.delenv("ENABLE_FILING_SIMULATION", raising=False)
    assert gw.filing_simulation_enabled() is False


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "  ", "maybe"])
def test_only_an_explicit_yes_turns_it_on(monkeypatch, value):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", value)
    assert gw.filing_simulation_enabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", " True "])
def test_the_usual_yeses_all_work(monkeypatch, value):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", value)
    assert gw.filing_simulation_enabled() is True


# ── The acknowledgement must not pass for a real one ────────────────────────

def test_the_reference_cannot_be_mistaken_for_an_arn():
    """A real ARN is 15 characters — AA, state code, MMYYYY, then a serial. A
    simulated reference that pattern-matches could be pasted into a portal field
    or a client email and be believed."""
    ack = gw._simulated_ack("042026", "abcdef12-3456-7890-abcd-ef1234567890")
    assert ack.startswith("SIM-NOT-FILED-")
    assert len(ack) != 15
    assert not ack[:2].isalpha() or not ack[2:4].isdigit(), (
        "the reference looks ARN-shaped at the start"
    )
    assert "NOT-FILED" in ack, "the string itself has to say it is not filed"


def test_the_reference_names_the_period_so_a_demo_is_reproducible():
    assert "042026" in gw._simulated_ack("042026", "abcdef1234")


# ── The response must carry its own disclaimer ──────────────────────────────

def test_the_steps_describe_a_filing_without_claiming_one():
    keys = [k for k, _ in gw._SIMULATION_STEPS]
    assert keys == ["validate", "authenticate", "upload", "process", "acknowledge"]
    joined = " ".join(l for _, l in gw._SIMULATION_STEPS).lower()
    assert "gstn" in joined or "gst portal" in joined


def test_the_module_never_reaches_a_government_host():
    """The simulation is scripted text. If a URL ever appears in this module,
    something is trying to actually talk to a portal."""
    import inspect
    src = inspect.getsource(gw)
    start = src.index("_SIMULATION_STEPS = [")
    end = src.index("def _simulated_ack")
    region = src[start:end]
    for host in ("gst.gov.in", "http://", "https://", "requests.", "httpx."):
        assert host not in region, f"the simulation block references {host!r}"


# ── It must not write anything ──────────────────────────────────────────────

def test_the_simulation_writes_nothing_at_all():
    """The whole safety argument. If this endpoint ever gains a write, a demo
    click starts changing a real return's status — and the period lock
    (migration 266) keys off exactly that.
    """
    import inspect
    src = inspect.getsource(gw.simulate_gstr3b_filing)
    for write in (".update(", ".insert(", ".upsert(", ".delete(",
                  "record_filing", "return_status_patch", "_MOCK_GSTR3B["):
        assert write not in src, (
            f"simulate_gstr3b_filing performs {write!r} — it must be read-only. "
            "The real 'this was filed on the portal' path is "
            "PATCH /gstr3b/{id}/status with status=submitted, which records the "
            "genuine ARN and the filings row the period lock reads."
        )


def test_that_write_detector_would_catch_a_real_write():
    """A guard on absence passes against an empty string. This pins the detector
    against the function that legitimately DOES write."""
    import inspect
    real = inspect.getsource(gw.update_gstr3b_status)
    assert any(w in real for w in (".update(", "record_filing", "return_status_patch")), (
        "the detector found no write in the endpoint that certainly has one, so "
        "the assertion above proves nothing"
    )


def test_the_real_filing_path_still_demands_an_explicit_ca_confirmation():
    """CLAUDE.md: never auto-submit to a government portal. Adding a simulation
    must not have loosened the thing it sits next to."""
    import inspect
    src = inspect.getsource(gw.update_gstr3b_status)
    assert "ca_approved" in src
    assert "DO NOT AUTO-SUBMIT" in src


# ── It has to mimic the portal's actual sequence ────────────────────────────
#
# A walk-through that invents its own order teaches a CA nothing they will
# recognise when they reach gst.gov.in. The portal's order is: saved return ->
# PROCEED TO PAYMENT (Table 6.1) -> PROCEED TO FILE -> declaration + authorised
# signatory -> FILE WITH DSC / FILE WITH EVC -> OTP or emSigner -> an
# irreversibility warning -> ARN.

def test_table_61_splits_liability_into_credit_and_cash():
    """The portal's most-misread screen, and the decision a CA actually makes
    there: how much of the liability the credit ledger discharges and how much
    has to be paid in cash by challan. A net figure alone hides it."""
    t = gw._table_61({
        "outward": {"taxable_igst_paise": 100000, "taxable_cgst_paise": 50000,
                    "taxable_sgst_paise": 50000},
        "net_payable": {"igst_paise": 30000, "cgst_paise": 0, "sgst_paise": 0},
    })
    by_head = {r["head"]: r for r in t["rows"]}
    assert by_head["IGST"]["liability_paise"] == 100000
    assert by_head["IGST"]["paid_through_itc_paise"] == 70000
    assert by_head["IGST"]["paid_in_cash_paise"] == 30000
    assert by_head["CGST"]["paid_through_itc_paise"] == 50000, "credit covered it all"
    assert by_head["CGST"]["paid_in_cash_paise"] == 0
    assert t["total_cash_paise"] == 30000


def test_every_head_adds_up():
    """Liability = what credit paid + what cash paid, per head. A split that
    does not reconcile is worse than no split."""
    t = gw._table_61({
        "outward": {"taxable_igst_paise": 123456, "taxable_cgst_paise": 7000,
                    "taxable_sgst_paise": 7000},
        "net_payable": {"igst_paise": 456, "cgst_paise": 7000, "sgst_paise": 0},
    })
    for r in t["rows"]:
        assert r["paid_through_itc_paise"] + r["paid_in_cash_paise"] == r["liability_paise"], r


def test_a_return_with_no_working_yields_zeros_rather_than_an_error():
    """An older saved return may have no summary_json. The demo must still open."""
    t = gw._table_61({})
    assert t["total_cash_paise"] == 0
    assert [r["head"] for r in t["rows"]] == ["IGST", "CGST", "SGST"]


def test_credit_can_never_be_shown_paying_more_than_the_liability():
    """max(liability - cash, 0). If Table 6 ever exceeded 3.1(a) — which would
    be a bug elsewhere — this must not render a negative ITC contribution."""
    t = gw._table_61({
        "outward": {"taxable_igst_paise": 1000},
        "net_payable": {"igst_paise": 5000},
    })
    assert t["rows"][0]["paid_through_itc_paise"] == 0


def test_the_declaration_is_the_form_s_own_wording():
    """Shown because it is the moment that matters: the person ticking it makes
    a statement to the department. Paraphrasing it would misrepresent what they
    are agreeing to."""
    d = gw._GSTR3B_DECLARATION
    assert "solemnly affirm and declare" in d
    assert "true and correct to the best of my/our knowledge" in d
    assert "nothing has been concealed therefrom" in d


def test_the_irreversibility_warning_names_the_correction_route():
    """"Cannot be revised" on its own reads as a dead end. §39(9) is the route,
    and a CA who does not know it will look for an edit button that is not
    there."""
    w = gw._FILING_WARNING
    assert "cannot be revised" in w
    assert "39(9)" in w


def test_both_signature_methods_are_offered_and_say_whose_signature_it_is():
    """The single most important thing this walk-through conveys: the signature
    is the TAXPAYER's — their DSC, or an EVC OTP to the mobile on their GST
    registration — never the firm's. That is why filing cannot be one button on
    our side, and it is why the demo has a signatory step at all."""
    import inspect
    src = inspect.getsource(gw.simulate_gstr3b_filing)
    assert '"evc"' in src and '"dsc"' in src
    assert "registered mobile" in src
    assert "TAXPAYER" in src or "taxpayer" in src
    assert "emSigner" in src, "DSC filing goes through emSigner; naming it is the point"


def test_the_steps_are_only_the_last_stage_not_the_whole_flow():
    """The transmission steps used to BE the demo. They are now what happens
    after the declaration is signed, and the stages before them are the part a
    CA has never seen laid out."""
    import inspect
    src = inspect.getsource(gw)
    i = src.index("_SIMULATION_STEPS = [")
    preamble = src[max(0, i - 1200):i]
    assert "PROCEED TO PAYMENT" in preamble
    assert "PROCEED TO FILE" in preamble
    assert "Table 6.1" in preamble
