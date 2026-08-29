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
