"""The ITR filing-demo flow (services/filing_demo/itr.py), held to the
framework rules and to its own statutory specifics.

What is particular to ITR among the demo flows:
  - software_permitted is TRUE — an e-Return Intermediary genuinely can
    transmit an ITR through the department's ERI APIs today, and the demo
    must teach that truthfully (PracticeSync is simply not a registered ERI
    yet);
  - verification is IT Act §140 — the taxpayer's (or karta's, managing
    director's, partner's, authorised signatory's), never the firm's;
  - e-verification within 30 days of transmission or the return is treated
    as never filed (CBDT Notification 05/2022) — carried by a warning stage;
  - PracticeSync emits no ITR JSON, and a whole STAGE says exactly why —
    the Department's schemas are held and every field path is verified, and
    what is missing is the SW######## software-provider id (a registration)
    and the non-computed half of a return. That is the most useful thing the
    demo can teach a CA evaluating the product, and it is read out of
    domain/income_tax/itr_json.py rather than restated, because the sentence
    it replaced ("no generator yet") had already gone stale;
  - the demo is gated on status == 'ready_for_filing', the last stop before
    'filed' in domain/income_tax/itr_workflow.py's state machine.
"""
from __future__ import annotations

import pytest

from services.filing_demo import common, itr
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"


def _db(filing_overrides: dict | None = None, snapshots: list | None = None):
    """A FakeDB with one ready-to-file ITR and, by default, the snapshot it
    pins. `snapshots=[]` seeds none; a list seeds exactly those."""
    db = FakeDB()
    filing = {
        "id": "F1", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2025-26", "assessment_year": "2026-27",
        "itr_form": "ITR-6", "status": "ready_for_filing",
        "computation_snapshot_id": "S1",
    }
    filing.update(filing_overrides or {})
    db.seed("itr_filings", filing)

    default_snapshot = {
        "id": "S1", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2025-26", "version": 3,
        "taxable_income_paise": 12_50_000_00,
        "tax_liability_paise": 2_10_000_00,
        "tds_deducted_paise": 1_50_000_00,
        "advance_tax_paid_paise": 40_000_00,
        "net_payable_paise": 20_000_00,
        "is_refund": False,
    }
    for snap in ([default_snapshot] if snapshots is None else snapshots):
        db.seed("tax_computation_snapshots", snap)
    return db


def _figures(out: dict) -> dict:
    summary = out["stages"][0]
    return {f["label"]: f.get("paise") for f in summary["figures"]}


# ── Rule 2: the envelope is honest ──────────────────────────────────────────

def test_itr_envelope_is_honest():
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-ITR")
    assert "nothing has been filed" in out["disclaimer"]


def test_real_channel_says_software_may_file_itr():
    """The one flow where software_permitted is True — ERIs file through the
    department's APIs today. Claiming otherwise would teach a CA something
    false in the opposite direction from the GST flows."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    rc = out["real_channel"]
    assert rc["software_permitted"] is True
    assert "ERI" in rc["how"]
    assert "not yet a registered ERI" in rc["note"], (
        "the honest reason this is a demo at all"
    )


# ── The portal sequence ─────────────────────────────────────────────────────

def test_itr_follows_the_portal_sequence():
    """summary → the return file (what is ready, what is not) → 30-day
    e-verification warning → §140 declaration → signature → otp → transmit →
    result. No payment stage: self-assessment tax under §140A is paid as a
    challan before filing, not inside the filing flow — the summary says so
    rather than the sequence inventing a step the portal does not have."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "declaration", "signature",
                     "otp", "transmit", "result"]


def test_signature_methods_route_the_otp_stage_correctly():
    """Aadhaar OTP and EVC go through the otp stage; DSC skips it. The wizard
    implements the skip from the otp flag, so the flags ARE the behaviour."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    sig = next(s for s in out["stages"] if s["kind"] == "signature")
    by_key = {m["key"]: m["otp"] for m in sig["methods"]}
    assert by_key == {"aadhaar_otp": True, "evc": True, "dsc": False}


def test_the_warning_carries_the_30_day_everification_clock():
    # CBDT Notification 05/2022 — 30 days from transmission, or the return
    # is treated as never having been filed.
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
    assert "30" in warning["text"]
    assert "never having been filed" in warning["text"]
    assert "CPC" in warning["text"], "the postal ITR-V route is real too"


def test_the_declaration_is_the_forms_own_wording():
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    decl = next(s for s in out["stages"] if s["kind"] == "declaration")
    assert "solemnly declare" in decl["text"]
    assert "correct and complete" in decl["text"]
    assert "Income-tax Act, 1961" in decl["text"]
    assert "competent to make this return and verify it" in decl["text"]
    # §140 capacities, by constitution of the taxpayer.
    opts = " / ".join(decl["signatory_options"])
    for capacity in ("Self", "Karta", "Managing director", "Partner",
                     "Authorised signatory"):
        assert capacity in opts
    assert "taxpayer's verification" in decl["note"], (
        "whose signature this is — the one thing every demo must teach"
    )


def test_the_transmit_stage_does_not_claim_a_file_that_was_not_produced():
    """PracticeSync emits no ITR JSON, and a transmit step claiming the
    artefact exists would be the demo's first lie.

    The REASON in that step used to be "generator not yet built", and that
    sentence went stale: the Department's AY 2026-27 schemas have since been
    downloaded by hand and committed, and every field path is verified
    against them by tests/test_itr_schema_paths.py. What is actually missing
    is the SW######## provider id (and the non-computed half of a return), so
    the step names that instead — a stale honest answer is still a wrong
    answer, and this is the flow where a CA is most likely to check."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    transmit = next(s for s in out["stages"] if s["kind"] == "transmit")
    first = transmit["steps"][0]["label"]
    assert "NOT produced" in first
    assert "SW########" in first
    assert "generator not yet built" not in first, (
        "the schemas are held now; this reason is no longer true")


# ── The return file: the refusal, surfaced as a stage ───────────────────────

def test_the_return_file_stage_names_what_the_portal_would_reject_for():
    """The most useful thing this demo can teach a CA evaluating the product:
    the figures are right and the file still cannot be produced, for two
    named reasons rather than one vague one.

    Every row is read out of domain/income_tax/itr_json.py — the authority on
    what it would refuse and why — so the stage cannot drift from the module
    the way the old transmit sentence did."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    stage = next(s for s in out["stages"] if s["kind"] == "table")
    assert stage["title"] == "The return file — what is ready, and what is not"
    needs = [r[0]["text"] for r in stage["rows"]]
    assert any("SW########" in n for n in needs)
    assert any("PersonalInfo" in n for n in needs)
    assert any("Balance sheet" in n for n in needs)
    states = {r[0]["text"]: r[1]["text"] for r in stage["rows"]}
    provider_row = next(n for n in needs if "SW########" in n)
    assert "NOT HELD" in states[provider_row]
    assert "e-Return Intermediary" in states[provider_row], (
        "the id comes with ERI registration — the gate, named")


def test_the_return_file_stage_reports_the_schema_as_actually_held():
    """The schemas ARE committed and the paths ARE verified, so the stage must
    say so — under-claiming is as much a fidelity fault as over-claiming, and
    it would tell a CA the product is further behind than it is."""
    from domain.income_tax import itr_json
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    stage = next(s for s in out["stages"] if s["kind"] == "table")
    schema_state = stage["rows"][0][1]["text"]
    assert "Held and verified" in schema_state
    mapping = itr_json.FIELD_MAPPINGS["ITR-6"]
    assert str(len(mapping.paths)) in schema_state
    assert (mapping.schema_file or "") in schema_state


def test_the_return_file_stage_never_prints_a_provider_id(monkeypatch):
    """Where one IS configured the stage says so and stops. The SW######## id
    identifies the software provider; a walk-through that renders it puts it
    on every screenshot a CA takes."""
    monkeypatch.setenv("ITR_SOFTWARE_PROVIDER_ID", "SW12345678")
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    stage = next(s for s in out["stages"] if s["kind"] == "table")
    assert "SW12345678" not in str(stage)
    provider_state = next(r[1]["text"] for r in stage["rows"]
                          if "SW########" in r[0]["text"])
    assert provider_state.startswith("Configured")


def test_the_summary_names_the_140a_challan_where_tax_is_payable():
    """IT Act §140A: tax still payable after TDS and advance tax is paid,
    with §234 interest, BEFORE the return is furnished. There is no payment
    stage because the portal has none — the challan is a separate act — but a
    CA must not leave this walk-through thinking the return pays it."""
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    note = out["stages"][0]["note"]
    assert "§140A" in note
    assert "§234A" in note and "§234C" in note
    assert "no payment step" in note


def test_the_140a_line_is_absent_on_a_refund():
    """Telling a refund case to pay self-assessment tax would be worse than
    saying nothing at all."""
    db = _db(snapshots=[{
        "id": "S1", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2025-26", "version": 1,
        "taxable_income_paise": 8_00_000_00,
        "net_payable_paise": -35_000_00, "is_refund": True,
    }])
    out = itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    assert "§140A" not in out["stages"][0]["note"]


def test_the_flow_says_what_changes_when_filing_is_real():
    """ITR is the ONE flow where software may transmit, so this note is the
    one a CA will read hardest. It has to name the ERI registration, the
    SW######## id it carries, and the whitelisted-static-IP condition — which
    is a hosting problem this API's Singapore region does not currently
    meet — rather than implying the gate is code."""
    note = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})["when_this_is_real"]
    assert "e-Return Intermediary" in note
    assert "SW########" in note
    assert "static IP" in note
    assert "§140" in note, "verification stays the taxpayer's either way"


# ── Rule 3: realism is labelled ─────────────────────────────────────────────

def test_the_result_specimen_never_travels_without_its_note():
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert result["specimen"] == common.specimen_itr_ack("F1")
    assert len(result["specimen"]) == 15 and result["specimen"].isdigit()
    assert "SPECIMEN" in result["specimen_note"]
    assert "Income Tax Department" in result["specimen_note"]
    assert "ITR-V" in result["filed_line"]
    assert any("Nothing was filed" in t for t in result["truth"])
    assert any("e-verif" in t for t in result["truth"]), (
        "the result must point at the e-verification step — a real filing "
        "is not done at transmission"
    )


# ── The figures are the record's own, paise-exact ───────────────────────────

def test_figures_come_from_the_pinned_snapshot():
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    by_label = _figures(out)
    assert by_label["Taxable income"] == 12_50_000_00
    assert by_label["Tax liability"] == 2_10_000_00
    assert by_label["TDS deducted"] == 1_50_000_00
    assert by_label["Advance tax paid"] == 40_000_00
    assert by_label["Net tax payable"] == 20_000_00
    note = out["stages"][0]["note"]
    assert "v3" in note, "the summary says which snapshot the figures are from"


def test_the_refund_line_leads_and_reads_as_a_refund():
    """net_payable_paise is negative for a refund (itr_engine's convention);
    the headline shows the magnitude under a Refund due label — the number
    the client asks about, stated the way the client asks it."""
    db = _db(snapshots=[{
        "id": "S1", "firm_id": FIRM, "client_id": CLIENT,
        "financial_year": "2025-26", "version": 1,
        "taxable_income_paise": 8_00_000_00,
        "tax_liability_paise": 60_000_00,
        "tds_deducted_paise": 95_000_00,
        "advance_tax_paid_paise": 0,
        "net_payable_paise": -35_000_00,
        "is_refund": True,
    }])
    out = itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    headline = summary["figures"][0]
    assert headline["label"] == "Refund due"
    assert headline["paise"] == 35_000_00
    assert "Net tax payable" not in _figures(out)


def test_a_dangling_snapshot_id_falls_back_to_the_latest_for_the_year():
    """The pinned id often points nowhere (the column is nullable and drafts
    regenerate); the chain is pinned → latest for client+year → zeros."""
    db = _db(
        filing_overrides={"computation_snapshot_id": "GONE"},
        snapshots=[
            {"id": "S-old", "firm_id": FIRM, "client_id": CLIENT,
             "financial_year": "2025-26", "version": 1,
             "taxable_income_paise": 1_00_000_00,
             "net_payable_paise": 1_000_00, "is_refund": False},
            {"id": "S-new", "firm_id": FIRM, "client_id": CLIENT,
             "financial_year": "2025-26", "version": 2,
             "taxable_income_paise": 2_00_000_00,
             "net_payable_paise": 2_000_00, "is_refund": False},
            # Another year's snapshot must never be picked up.
            {"id": "S-wrong-year", "firm_id": FIRM, "client_id": CLIENT,
             "financial_year": "2024-25", "version": 9,
             "taxable_income_paise": 9_00_000_00,
             "net_payable_paise": 9_000_00, "is_refund": False},
        ])
    out = itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    by_label = _figures(out)
    assert by_label["Taxable income"] == 2_00_000_00
    assert by_label["Net tax payable"] == 2_000_00
    assert "does not pin" in out["stages"][0]["note"]


def test_no_snapshot_at_all_still_builds_with_zeros_and_says_so():
    db = _db(filing_overrides={"computation_snapshot_id": None}, snapshots=[])
    out = itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    by_label = _figures(out)
    assert by_label["Net tax payable"] == 0
    assert by_label["Taxable income"] == 0
    assert "No computation snapshot yet" in out["stages"][0]["note"]
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds[0] == "summary" and kinds[-1] == "result"


def test_the_summary_states_the_139_1_due_dates():
    # IT Act §139(1) via services/compliance_engine.py::itr_due_date —
    # FY 2025-26 ends 31-03-2026, so 31 Jul 2026 / 31 Oct 2026 (audit).
    out = itr.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    note = out["stages"][0]["note"]
    assert "31 Jul 2026" in note
    assert "31 Oct 2026" in note


# ── Refusals: plain sentences, never 500s ───────────────────────────────────

def test_a_missing_ref_is_an_answer_not_an_incident():
    with pytest.raises(ValueError, match="filing_id"):
        itr.build(_db(), FIRM, CLIENT, {})


def test_an_unknown_filing_is_an_answer_not_an_incident():
    with pytest.raises(ValueError, match="not found"):
        itr.build(_db(), FIRM, CLIENT, {"filing_id": "NOPE"})


def test_another_firms_filing_is_not_found_not_leaked():
    with pytest.raises(ValueError, match="not found"):
        itr.build(_db(), "FIRM-B", CLIENT, {"filing_id": "F1"})
    with pytest.raises(ValueError, match="not found"):
        itr.build(_db(), FIRM, "OTHER-CLIENT", {"filing_id": "F1"})


@pytest.mark.parametrize("status", ["draft", "review", "partner_review"])
def test_a_filing_not_yet_ready_is_refused_by_name(status):
    """Gated on 'ready_for_filing' — the last stop before 'filed' in the
    itr_workflow state machine. The refusal names the actual status so the
    CA knows which review step is outstanding."""
    db = _db(filing_overrides={"status": status})
    with pytest.raises(ValueError, match=status):
        itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})


def test_an_already_filed_return_is_refused():
    db = _db(filing_overrides={"status": "filed"})
    with pytest.raises(ValueError, match="already recorded as filed"):
        itr.build(db, FIRM, CLIENT, {"filing_id": "F1"})
