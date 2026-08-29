"""The filing-demo framework: every flow, one set of rules.

WHY THIS EXISTS
    The owner's direction (2026-08-29): every statutory filing the product
    prepares — GST returns, TDS, ITR, PF, ESI, MCA — gets a portal-faithful
    demo walk-through, since real transmission is gated on registrations
    (GSP, ERI) that do not exist yet. That is many flows written by many
    hands, so the rules live in one framework (services/filing_demo/) and
    this file holds every flow to them:

      1. WRITES NOTHING — no flow module and no endpoint performs any write.
      2. THE ENVELOPE IS HONEST — simulated=True, filed=False, a
         SIM-NOT-FILED reference, and a disclaimer, in every response.
      3. REALISM IS LABELLED — a result stage's realistic reference never
         appears without its SPECIMEN note.

    GSTR-1 is the exemplar flow and is tested end-to-end here; the other
    flows get their own files, but the framework rules apply to them
    automatically because the scans below walk the whole package.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

import routers.filing_demo as fd_router
import services.filing_demo as fd
from services.filing_demo import common, gstr1
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"


# ── Rule 1: writes nothing ──────────────────────────────────────────────────

_WRITE_MARKERS = (".update(", ".insert(", ".upsert(", ".delete(",
                  "record_filing", "return_status_patch", "log_event(",
                  "log_timeline_event(")


def _package_sources():
    pkg = pathlib.Path(fd.__file__).parent
    return {p.name: p.read_text() for p in sorted(pkg.glob("*.py"))}


def test_no_flow_module_performs_any_write():
    """The whole safety argument, held for every flow at once — including the
    ones agents write later. A demo that gains a write starts changing real
    return statuses from a walk-through."""
    for name, src in _package_sources().items():
        for marker in _WRITE_MARKERS:
            assert marker not in src, (
                f"services/filing_demo/{name} contains {marker!r} — demo flows "
                "are read-only, without exception. The real status paths live "
                "in each module's own router."
            )


def test_the_router_performs_no_write_either():
    src = inspect.getsource(fd_router)
    for marker in _WRITE_MARKERS:
        assert marker not in src, f"routers/filing_demo.py contains {marker!r}"


def test_that_write_detector_would_catch_a_real_write():
    """A guard on absence proves nothing until it is shown catching presence.
    The GSTR-3B status endpoint certainly writes; the detector must see it."""
    import routers.gst_workspace as gw
    real = inspect.getsource(gw.update_gstr3b_status)
    assert any(m in real for m in _WRITE_MARKERS)


# ── Rule 2 and 3, end to end on the exemplar ────────────────────────────────

def _db_with_return(**overrides):
    db = FakeDB()
    row = {
        "id": "R1", "firm_id": FIRM, "client_id": CLIENT,
        "period": "042026", "gstin": "27ABCDE1234F1Z5",
        "status": "ca_approved",
        "total_taxable_paise": 1_00_000_00, "total_igst_paise": 9_000_00,
        "total_cgst_paise": 4_500_00, "total_sgst_paise": 4_500_00,
        "total_cess_paise": 0,
        "summary_json": {"counts": {"b2b": 12, "b2cl": 3, "hsn": 7}},
    }
    row.update(overrides)
    db.seed("gstr1_returns", row)
    return db


def test_gstr1_envelope_is_honest():
    out = gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "R1"})
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False, (
        "GSTN filing needs a GSP; claiming software may file GST today would "
        "teach a CA something false"
    )


def test_gstr1_follows_the_portal_sequence():
    """summary → documents table → freeze warning → declaration → signature →
    otp → transmit → result. No payment stage: GSTR-1 declares supplies, the
    tax is paid with GSTR-3B — an asymmetry the demo exists to show."""
    out = gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "R1"})
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "declaration",
                     "signature", "otp", "transmit", "result"]
    assert "table_61" not in str(out), "GSTR-1 has no payment step"


def test_gstr1_without_counts_still_builds():
    """An older record without summary_json must not lose the demo — the table
    stage is simply absent."""
    out = gstr1.build(_db_with_return(summary_json=None), FIRM, CLIENT,
                      {"return_id": "R1"})
    kinds = [s["kind"] for s in out["stages"]]
    assert "table" not in kinds
    assert kinds[0] == "summary" and kinds[-1] == "result"


def test_the_declaration_is_the_forms_own_wording():
    out = gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "R1"})
    decl = next(s for s in out["stages"] if s["kind"] == "declaration")
    assert "solemnly affirm and declare" in decl["text"]
    assert "nothing has been concealed therefrom" in decl["text"]
    assert "taxpayer's signatory" in decl["note"], (
        "whose signature this is — the one thing every demo must teach"
    )


def test_the_result_specimen_never_travels_without_its_note():
    out = gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "R1"})
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert len(result["specimen"]) == 15
    assert result["specimen"].startswith("AA27")
    assert "SPECIMEN" in result["specimen_note"]
    assert "not issued" in result["specimen_note"]
    assert any("Nothing was filed" in t for t in result["truth"])


def test_result_stage_constructor_cannot_omit_the_note():
    """The constructor derives the note itself — a flow author cannot forget
    it, which is stronger than reminding them."""
    stage = common.result_stage("GSTN", "ARN", "AA270426123456Z", "line", [])
    assert "SPECIMEN" in stage["specimen_note"]
    assert "GSTN" in stage["specimen_note"]


def test_a_missing_return_is_an_answer_not_an_incident():
    with pytest.raises(ValueError, match="not found"):
        gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "NOPE"})
    with pytest.raises(ValueError, match="return_id"):
        gstr1.build(_db_with_return(), FIRM, CLIENT, {})


def test_the_figures_are_the_records_own():
    out = gstr1.build(_db_with_return(), FIRM, CLIENT, {"return_id": "R1"})
    summary = out["stages"][0]
    by_label = {f["label"]: f.get("paise") for f in summary["figures"]}
    assert by_label["Taxable value"] == 1_00_000_00
    assert by_label["IGST"] == 9_000_00


# ── Specimen builders ───────────────────────────────────────────────────────

def test_every_specimen_matches_its_authoritys_format():
    assert len(common.specimen_gstn_arn("27X", "042026", "seed-1")) == 15
    assert common.specimen_tds_prn("seed-1").isdigit()
    assert len(common.specimen_tds_prn("seed-1")) == 15
    assert len(common.specimen_itr_ack("seed-1")) == 15
    assert len(common.specimen_epfo_trrn("seed-1")) == 10
    assert len(common.specimen_esic_challan("seed-1")) == 19
    srn = common.specimen_mca_srn("seed-1")
    assert srn[0].isalpha() and srn[1:].isdigit() and len(srn) == 9


def test_specimens_are_deterministic_and_seed_sensitive():
    assert common.specimen_tds_prn("a") == common.specimen_tds_prn("a")
    assert common.specimen_tds_prn("a") != common.specimen_tds_prn("b"), (
        "two different records demoing the same reference would look like a "
        "bug to anyone comparing screenshots"
    )


# ── The registry and the endpoints ──────────────────────────────────────────

def test_every_flow_is_registered_with_a_real_permission_resource():
    from core.permissions import PERMISSIONS
    assert set(fd.FLOWS) == {"gstr1", "gstr9", "tds", "itr", "pf", "esi", "mca"}
    for flow, (builder, resource) in fd.FLOWS.items():
        assert callable(builder), flow
        assert resource in PERMISSIONS, (
            f"flow {flow} gates on unknown resource {resource!r} — the demo "
            "shows the module's real figures, so it must gate like the module"
        )
        assert "read" in PERMISSIONS[resource], resource


def test_capabilities_answers_off_when_the_kill_switch_is_thrown(monkeypatch):
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "false")
    out = fd_router.capabilities({"role": "Partner", "firm_id": FIRM})
    assert out["data"]["enabled"] is False
    assert out["data"]["flows"] == [], (
        "a disabled build must offer no flows, or a screen renders a button "
        "the preview endpoint will refuse — the dead-control fault"
    )


def test_capabilities_filters_flows_by_role(monkeypatch):
    monkeypatch.delenv("ENABLE_FILING_SIMULATION", raising=False)
    partner = fd_router.capabilities({"role": "Partner", "firm_id": FIRM})
    assert set(partner["data"]["flows"]) == set(fd.FLOWS)
    assert partner["data"]["real_filing"] is False


def test_a_stub_flow_refuses_with_its_own_words():
    """A not-yet-built flow answers honestly instead of 500ing, so the
    endpoint can ship ahead of it. Stubs are DISCOVERED rather than named:
    the flow modules are being replaced one by one, and naming a particular
    module here made this test wrong the moment that flow was built (it
    originally pinned tds_return). When no stub remains, nothing is held to
    this rule and the loop is simply empty."""
    import importlib
    for name, src in _package_sources().items():
        if name in ("common.py", "__init__.py") or "not built yet" not in src:
            continue
        mod = importlib.import_module(f"services.filing_demo.{name[:-3]}")
        with pytest.raises(ValueError, match="not built yet"):
            mod.build(FakeDB(), FIRM, CLIENT, {})


def test_the_preview_endpoint_names_its_client_scope_check():
    """tests/test_router_client_scope.py's rule, honoured from birth: the
    scope check is visible in the endpoint's own source, not a call deep."""
    src = inspect.getsource(fd_router.preview)
    assert "assert_client_access(current_user, body.client_id)" in src
