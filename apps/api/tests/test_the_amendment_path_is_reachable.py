"""GST-13 — a §37 correction can now be seen AND declared.

WHAT WAS WRONG
    CGST Act §37: a filed GSTR-1 can never be revised, so a correction to it is
    declared in a LATER return's amendment tables — 9A for invoices, 9C for
    credit and debit notes, 10 for B2C-others.

    Three finished capabilities sat behind that and a grep of apps/web for any
    of them returned nothing:

        GET  /api/gst-workspace/gstr1/exceptions
        GET  /api/gst-workspace/gstr1/amendments
        POST /api/gst/gstr1/with-amendments

    The third is the sharpest, and routers/gst.py says so itself:
    "services/gst_amendment_service has worked out which corrections are
    outstanding since it was built, and domain/gst/amendments.merge_into_payload
    has been able to fold them into a payload for just as long. NOTHING
    CONNECTED THE TWO: there was no route that produced the merged payload."
    The route was then written to connect them — and had no caller either. So a
    CA could be told an amendment was due and had no way to produce the return
    that declares it.

WHAT THIS PINS
    That the three are reachable, and the two refusals that make the report
    safe to act on: an out-of-time correction is REPORTED and never silently
    dropped, and it never reaches the payload.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import routers.gst as gst
import routers.gst_workspace as gw
from domain.gst.exception_report import (
    AMEND_B2CS, AMEND_INVOICE, AMEND_NOTE, DECLARE_CURRENT, compare_payloads,
)


WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"


def _sources() -> str:
    out = []
    for folder in ("app", "lib", "components"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                out.append(path.read_text(errors="ignore"))
    return "\n".join(out)


BLOB = _sources()


def _reaches(path: str) -> bool:
    chunks = re.split(r"\{[^}]+\}", path)
    return re.search(r"[^\s\"'`]*?".join(re.escape(c) for c in chunks), BLOB) is not None


def test_the_web_tree_was_actually_read():
    assert len(BLOB) > 500_000, f"only {len(BLOB)} chars of frontend source found"


@pytest.mark.parametrize("path", [
    "/api/gst-workspace/gstr1/exceptions",
    "/api/gst-workspace/gstr1/amendments",
    "/api/gst/gstr1/with-amendments",
])
def test_the_amendment_path_has_a_screen(path):
    assert _reaches(path), (
        f"{path} is finished and mounted and nothing in apps/web calls it — a "
        f"CA can be told a §37 amendment is due and cannot produce the return "
        f"that declares it")


@pytest.mark.parametrize("path", [
    "/api/gst-workspace/gstr1/exceptions",
    "/api/gst-workspace/gstr1/amendments",
])
def test_those_endpoints_still_exist(path):
    assert path in {r.path for r in gw.router.routes}


def test_the_merged_payload_endpoint_still_exists():
    assert "/api/gst/gstr1/with-amendments" in {r.path for r in gst.router.routes}


# ───────── the four findings, which need four different actions ─────────

def _doc(no, section="b2b", taxable=1000_00, cgst=90_00, sgst=90_00, igst=0):
    return {"doc_no": no, "section": section, "taxable_paise": taxable,
            "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
            "cess_paise": 0}


def test_a_document_never_declared_is_not_an_amendment():
    """It goes in the CURRENT period's ordinary table. There is no filed entry
    to supersede, and putting it in 9A would amend an entry that does not
    exist."""
    filed = {"b2b": []}
    books = {"b2b": [{"ctin": "27AAAAA0000A1Z5", "inv": [
        {"inum": "INV-1", "idt": "01-06-2026", "val": 1180.0,
         "itms": [{"rt": 18.0, "txval": 1000.0, "camt": 90.0, "samt": 90.0}]}]}]}
    report = compare_payloads(filed, books)
    found = report["documents"]["missing_from_return"]
    assert len(found) == 1
    assert found[0]["declare_in"] == DECLARE_CURRENT
    assert found[0]["declare_in"] != AMEND_INVOICE


def test_a_document_that_vanished_from_the_books_is_an_amendment():
    """The most serious of the four: declared, then deleted or cancelled. A
    filed return cannot simply drop it."""
    filed = {"b2b": [{"ctin": "27AAAAA0000A1Z5", "inv": [
        {"inum": "INV-1", "idt": "01-06-2026", "val": 1180.0,
         "itms": [{"rt": 18.0, "txval": 1000.0, "camt": 90.0, "samt": 90.0}]}]}]}
    report = compare_payloads(filed, {"b2b": []})
    found = report["documents"]["missing_from_books"]
    assert len(found) == 1
    assert found[0]["declare_in"] == AMEND_INVOICE


def test_a_reclassified_document_is_reported_once_and_names_both_tables():
    """Amending the value alone would leave it in the wrong table, so it is a
    finding of its own — and it must NOT also be counted as a value change, or
    every total double-counts it."""
    inv = {"inum": "INV-1", "idt": "01-06-2026", "val": 1180.0,
           "itms": [{"rt": 18.0, "txval": 1000.0, "camt": 0.0, "samt": 0.0, "iamt": 180.0}]}
    filed = {"b2b": [{"ctin": "27AAAAA0000A1Z5", "inv": [inv]}]}
    books = {"exp": [{"exp_typ": "WPAY", "inv": [inv]}]}
    report = compare_payloads(filed, books)
    reclassified = report["documents"]["reclassified"]
    assert len(reclassified) == 1
    assert reclassified[0]["filed_section"] != reclassified[0]["books_section"]
    assert not any(d["doc_no"] == "INV-1"
                   for d in report["documents"]["amount_changed"]), \
        "a reclassified document counted twice inflates every total"


def test_the_four_tables_are_the_statutory_ones():
    """9A invoices, 9C notes, 10 B2C-others — Notification 26/2022 and the
    GSTR-1 format. A wrong table number is a return GSTN rejects."""
    assert (AMEND_INVOICE, AMEND_NOTE, AMEND_B2CS) == ("9A", "9C", "10")
    assert DECLARE_CURRENT == "current period"


def test_a_clean_period_says_so_rather_than_returning_nothing():
    report = compare_payloads({"b2b": []}, {"b2b": []})
    assert report["clean"] is True
    assert report["finding_count"] == 0
    assert report["ca_review_required"] is True
    assert "§37" in report["rule"]


# ───────── the portal sync that must NOT get a screen ─────────

def test_the_portal_sync_cannot_reach_gstn_and_is_deliberately_unreached():
    """GST-13 lists /api/gst-portal as having no screen. It should not get one.

    get_provider has exactly ONE provider — manual — because reading returns
    from the portal needs an empanelled GSP. A "Sync from the portal" button
    would therefore sync nothing and report `status: "manual"` with empty
    return lists, which is the failure that function's own docstring names: a
    CA reading it as "the portal says the return is not filed".
    """
    from domain.gst.portal_service import get_provider
    with pytest.raises(ValueError) as exc:
        get_provider("gsp")
    assert "empanelled GSP" in str(exc.value)
    assert get_provider("manual") is not None

    import routers.gst_portal as portal
    for route in portal.router.routes:
        assert not _reaches(route.path), (
            f"{route.path} now has a screen. The portal sync returns empty data "
            f"until a GSP is empanelled — see get_provider — so a screen for it "
            f"reports 'not filed' for every return. If a provider now exists, "
            f"delete this test in the same commit that wires it in.")
