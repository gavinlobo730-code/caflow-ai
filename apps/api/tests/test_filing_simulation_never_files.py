"""The filing demo must never be able to claim a return was filed.

WHY THIS EXISTS
    PracticeSync prepares every Indian statutory filing and produces the
    payload. The CA uploads it to the authority's own portal and signs there.
    Real API filing needs registrations that do not exist (a GSP for GST, ERI
    for ITR) and is not built.

    So that the intended flow can be SHOWN before it exists, there are demo
    walk-throughs. That is a reasonable thing to demo and a dangerous thing to
    leave lying around: the person demoing knows it is a mock; whoever opens
    the same screen next week does not. A return believed filed and not filed
    accrues Rs 50 a day under §47 from its real due date, and the correction
    window under §37(3)/§39(9) runs out regardless.

    Everything below is therefore about what the demo must NOT do. The stages
    it returns are decoration; these are the contract.

WHERE THE CONTRACT NOW LIVES, AND WHAT MOVED
    This file was written against POST /gst-workspace/gstr3b/{id}/
    simulate-filing, the first walk-through built, when it was the only one.
    Every statutory filing now runs through the shared framework in
    services/filing_demo/, GSTR-3B included, and that endpoint has been
    deleted rather than left beside its replacement — CLAUDE.md's own rule for
    a superseded simulation, and the only way two demos of one return cannot
    drift apart.

    The contract did not move with it; it was retargeted. The kill switch,
    the honest reference, the specimen and its label, the no-network scan and
    the no-write scan are all below, now asserted against the framework and
    the GSTR-3B flow that replaced the endpoint.

    What is NOT here any more is the shape of that endpoint's JSON — its
    table_61 dict, its steps list, its declaration constant. Those are stages
    now, and tests/test_filing_demo_gstr3b.py pins each of them harder than
    this file ever did: the payment stage's per-head arithmetic, that Table 6
    sets off 4(C) and never 4(A), the declaration verbatim, the §39(9) freeze
    warning, and both signature methods. Nothing was dropped; read the two
    files together.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

import routers.filing_demo as fd_router
import services.filing_demo as fd
from routers import gst_workspace as gw
from services.filing_demo import common, gstr3b
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
GSTIN = "27ABCDE1234F1Z5"
PERIOD = "042026"


@pytest.fixture()
def sim_on(monkeypatch):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "true")
    return True


def _demo_sources() -> dict:
    pkg = pathlib.Path(fd.__file__).parent
    return {p.name: p.read_text() for p in sorted(pkg.glob("*.py"))}


def _gstr3b_demo() -> dict:
    """The walk-through that replaced the deleted endpoint, over a return with
    real figures on it."""
    db = FakeDB()
    db.seed("gstr3b_returns", {
        "id": "R3B", "firm_id": FIRM, "client_id": CLIENT,
        "period": PERIOD, "gstin": GSTIN, "status": "ca_approved",
        "tax_liability_paise": 1_80_000_00, "itc_claimed_paise": 1_00_000_00,
        "net_tax_paise": 80_000_00, "summary_json": {},
    })
    return gstr3b.build(db, FIRM, CLIENT, {"return_id": "R3B"})


# ── On by default, with a kill switch ───────────────────────────────────────
#
# REVERSED from the original design, by the owner's explicit decision
# (2026-08-29). The first version shipped default-OFF so a filing demo could
# never appear in production by accident; the owner then made demo filing a
# core product capability — every statutory module gets a portal-faithful
# walk-through, the deployment records no real filings, and the DEMO labelling
# inside the flow is the operative safeguard. The flag is now the kill switch
# for any future deployment that records real filings.

def test_it_is_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("ENABLE_FILING_SIMULATION", raising=False)
    assert gw.filing_simulation_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "  ", "maybe"])
def test_the_kill_switch_kills_it(monkeypatch, value):
    """Anything that is not an explicit yes disables. On a deployment with real
    filings, `false` must reliably remove every demo affordance."""
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", value)
    assert gw.filing_simulation_enabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", " True "])
def test_the_usual_yeses_all_work(monkeypatch, value):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", value)
    assert gw.filing_simulation_enabled() is True


def test_there_is_exactly_one_reading_of_the_switch(monkeypatch):
    """The GST dashboard's capability flag and the filing-demo endpoints must
    never be able to disagree about whether demos are on — a screen that shows
    a button the preview endpoint refuses is the dead-control fault."""
    assert gw.filing_simulation_enabled is common.filing_simulation_enabled
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "false")
    assert fd_router.capabilities({"role": "Partner", "firm_id": FIRM})[
        "data"]["enabled"] is False


# ── The acknowledgement must not pass for a real one ────────────────────────

def test_the_reference_cannot_be_mistaken_for_an_arn():
    """A real ARN is 15 characters — AA, state code, MMYY, a serial, a check
    character. A simulated reference that pattern-matches could be pasted into
    a portal field or a client email and be believed."""
    ack = common.honest_reference("gstr3b", "abcdef12-3456-7890-abcd-ef1234567890")
    assert ack.startswith("SIM-NOT-FILED-")
    assert len(ack) != 15
    assert not ack[:2].isalpha() or not ack[2:4].isdigit(), (
        "the reference looks ARN-shaped at the start")
    assert "NOT-FILED" in ack, "the string itself has to say it is not filed"


def test_the_reference_names_the_flow_and_record_so_a_demo_is_reproducible():
    """It used to carry the period, because the only demo was a GSTR-3B one.
    The framework's reference carries the FLOW and the record id instead —
    which identifies a walk-through across eight filings, where a period could
    not."""
    ack = _gstr3b_demo()["acknowledgement"]
    assert ack.startswith("SIM-NOT-FILED-GSTR3B-")
    assert "R3B" in ack


def test_every_flows_reference_says_not_filed():
    """Not just GSTR-3B's. A flow added later inherits this or fails here."""
    for flow in fd.FLOWS:
        assert common.honest_reference(flow, "seed").startswith("SIM-NOT-FILED-")


# ── The specimen ARN: realism, on condition of labelling ────────────────────
#
# The owner chose a realistic ARN for the success panel — a demo ending on an
# obviously fake string undercuts the walk-through — on condition it is marked
# SPECIMEN wherever it appears. So the specimen exists, its shape is right,
# and the tests below hold the condition: it never travels without its label,
# and the honest SIM-NOT-FILED reference stays alongside.

def test_the_specimen_has_the_real_arn_shape():
    arn = common.specimen_gstn_arn(GSTIN, PERIOD, "fd8d8ae1-ea4a-47d7")
    assert len(arn) == 15, arn
    assert arn.startswith("AA27"), "two letters then the GSTIN's state code"
    assert arn[4:8] == "0426", "MMYY of the period"
    assert arn[8:14].isdigit(), "six-digit serial"
    assert arn[14].isalpha(), "check character"


def test_the_specimen_is_deterministic_so_a_demo_replays_identically():
    a = common.specimen_gstn_arn(GSTIN, PERIOD, "fd8d8ae1-ea4a-47d7")
    b = common.specimen_gstn_arn(GSTIN, PERIOD, "fd8d8ae1-ea4a-47d7")
    assert a == b
    c = common.specimen_gstn_arn(GSTIN, "052026", "fd8d8ae1-ea4a-47d7")
    assert a != c, "a different period must yield a different specimen"


def test_a_missing_gstin_or_odd_period_still_yields_a_wellformed_specimen():
    """An older record may lack a GSTIN. The demo must not crash or emit a
    ragged string that betrays the fallback."""
    arn = common.specimen_gstn_arn("", PERIOD, "row-1")
    assert len(arn) == 15 and arn.startswith("AA27")
    assert len(common.specimen_gstn_arn(GSTIN, "bad", "row-1")) == 15


def test_the_specimen_never_travels_without_its_label():
    """The condition the realism was granted on, asserted on the response a
    screen actually receives: if a specimen is in it, its SPECIMEN note is
    beside it and the honest acknowledgement is still present."""
    out = _gstr3b_demo()
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert result["specimen"]
    assert "SPECIMEN" in result["specimen_note"]
    assert "not issued" in result["specimen_note"]
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-")
    assert out["filed"] is False and out["simulated"] is True
    assert "nothing has been filed" in out["disclaimer"]


def test_no_flows_result_stage_can_omit_the_note():
    """The stage constructor derives the note from the authority itself, so a
    flow author cannot forget it — stronger than reminding them."""
    for name, src in _demo_sources().items():
        assert '"specimen_note"' not in src or name == "common.py", (
            f"services/filing_demo/{name} sets specimen_note by hand; it must "
            "come from common.result_stage, which cannot omit it")


# ── Nothing reaches a government system ─────────────────────────────────────

def test_no_demo_module_can_reach_a_government_host():
    """The walk-throughs are scripted text. If a URL or an HTTP client ever
    appears in this package, something is trying to actually talk to a
    portal — which is the one thing that would make a demo able to file."""
    for name, src in _demo_sources().items():
        for marker in ("http://", "https://", "requests.", "httpx.", "urllib",
                       "socket."):
            assert marker not in src, (
                f"services/filing_demo/{name} references {marker!r}")


def test_the_deleted_endpoint_has_not_come_back():
    """The GSTR-3B walk-through lives in services/filing_demo/gstr3b.py and is
    served by the shared preview endpoint. A second one in the GST router is
    what this change removed, and re-adding it would put two demos — with two
    safety arguments — against one return."""
    src = inspect.getsource(gw)
    assert "simulate-filing" not in src.replace(
        "# GSTR-3B used to carry its own walk-through — POST "
        "/gstr3b/{id}/simulate-filing", ""), (
        "a filing-simulation endpoint is back in routers/gst_workspace.py")
    assert "gstr3b" in fd.FLOWS


# ── It must not write anything ──────────────────────────────────────────────

_WRITES = (".update(", ".insert(", ".upsert(", ".delete(", "record_filing",
           "return_status_patch", "_MOCK_GSTR3B[")


def test_the_demo_writes_nothing_at_all():
    """The whole safety argument. If a demo ever gains a write, a click starts
    changing a real return's status — and the period lock (migration 266) keys
    off exactly that."""
    for name, src in _demo_sources().items():
        for write in _WRITES:
            assert write not in src, (
                f"services/filing_demo/{name} performs {write!r} — it must be "
                "read-only. The real 'this was filed on the portal' path is "
                "PATCH /gstr3b/{id}/status with status=submitted, which records "
                "the genuine ARN and the filings row the period lock reads.")
    endpoint = inspect.getsource(fd_router)
    for write in _WRITES:
        assert write not in endpoint, f"routers/filing_demo.py performs {write!r}"


def test_that_write_detector_would_catch_a_real_write():
    """A guard on absence passes against an empty string. This pins the detector
    against the function that legitimately DOES write."""
    real = inspect.getsource(gw.update_gstr3b_status)
    assert any(w in real for w in (".update(", "record_filing", "return_status_patch")), (
        "the detector found no write in the endpoint that certainly has one, so "
        "the assertion above proves nothing")


def test_the_demo_cannot_move_a_returns_status():
    """Belt and braces on the scan above: the walk-through is built from a
    seeded return and the row is unchanged afterwards."""
    db = FakeDB()
    row = {"id": "R3B", "firm_id": FIRM, "client_id": CLIENT,
           "period": PERIOD, "gstin": GSTIN, "status": "ca_approved",
           "tax_liability_paise": 0, "itc_claimed_paise": 0,
           "net_tax_paise": 0, "summary_json": {}}
    db.seed("gstr3b_returns", dict(row))
    gstr3b.build(db, FIRM, CLIENT, {"return_id": "R3B"})
    after = db.table("gstr3b_returns").select("*").eq("id", "R3B").execute().data[0]
    assert after["status"] == "ca_approved"
    assert {k: after[k] for k in row} == row, "the demo changed the saved return"


def test_the_real_filing_path_still_demands_an_explicit_ca_confirmation():
    """CLAUDE.md: never auto-submit to a government portal. Replacing the
    simulation must not have loosened the thing it sat next to."""
    src = inspect.getsource(gw.update_gstr3b_status)
    assert "ca_approved" in src
    assert "DO NOT AUTO-SUBMIT" in src


def test_the_preview_endpoint_refuses_when_the_switch_is_off(monkeypatch):
    """The kill switch has to bite at the endpoint, not only in the capability
    probe — a deployment with real filings must not be able to serve a
    walk-through to a caller that asks for one directly."""
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "false")
    out = fd_router.preview(
        "gstr3b", fd_router.PreviewRequest(client_id=CLIENT, ref={"return_id": "R3B"}),
        {"role": "Partner", "firm_id": FIRM, "id": "U1",
         "email": "partner@example.com"})
    assert out["success"] is False
    assert "switched off" in (out["error"] or "")
