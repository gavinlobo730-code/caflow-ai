"""IT-18, first half — a demo number must never read as a client's own.

WHAT THE FINDING SAID, AND WHAT IS ACTUALLY TRUE
    IT-18 says the invented AIS figures in ai_insight_service, risk_engine and
    document_intelligence_service could be read as a client's own. Measured
    against the tree, all three are narrower than that:

      * ai_insight_service's "AIS shows income ₹8.5L vs books ₹7.3L" lives in
        MOCK_AI_INSIGHTS_V2, and ai_insights_repository reads it only when
        SUPABASE_URL is unset.
      * risk_engine's copy is in MOCK_RISKS / MOCK_DOCUMENT_RISKS, and every
        function that touches them early-returns on SUPABASE_URL.
      * document_intelligence_service's copies are in MOCK_DOCUMENT_RISKS and
        MOCK_DOCUMENT_EXTRACTIONS — and its unversioned router is NOT MOUNTED.
        It was retired in the R2.8 fix phase for exactly this reason; main.py
        carries the comment saying so, and v1/v2 are the audited replacements.

    So none of it reaches a real CA today. What DID need fixing is one line the
    finding does not mention, and this file exists to keep it fixed.

WHAT WAS ACTUALLY WRONG
    detect_document_risks read:

        book_income = int(total_income * 0.85)  # mock book income difference
        diff = total_income - book_income

    and reported the gap as a finding — "AIS shows ₹8,50,000 but books show
    ₹7,22,500. Difference ₹1,27,500." That is not the client's books. It is the
    AIS figure times 0.85, so the risk fired on EVERY AIS carrying any income,
    always at exactly 15%, stating a specific rupee amount about accounts
    nobody had looked at.

    It was unreachable only because that function has no caller. The next
    person to wire document analysis up would have shipped it.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib
import re

import pytest

import domain.ai_insight_service as insights
import domain.document_intelligence_service as docint
import domain.risk_engine as risks


API = pathlib.Path(__file__).resolve().parents[1]


def test_the_book_figure_is_never_derived_from_the_ais_figure():
    """The fix, stated as the RULE rather than as the constant. Any fraction of
    the AIS total presented as the book total is a fabricated reconciliation,
    whatever the fraction is."""
    src = inspect.getsource(docint.detect_document_risks)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "book_income" not in body, (
        "detect_document_risks is deriving a book figure again. AIS is the "
        "department's statement of what OTHERS reported (§285BB); the books "
        "are not held by this function, and a difference it states is invented.")
    assert not re.search(r"total_income\s*\*\s*0?\.\d", body)


def test_it_still_says_what_it_does_know():
    """Refusing to invent must not mean saying nothing. The AIS total IS held,
    and 'reconcile this before filing' is the useful, true thing to say."""
    found = docint.detect_document_risks(
        "doc-1", "client-1", {"total_income_paise": 8_50_000_00}, "AIS")
    ais = [r for r in found if r["category"] == "AIS_MISMATCH"]
    assert len(ais) == 1
    text = ais[0]["description"]
    assert "8,50,000" in text, "Indian grouping, not 850,000"
    assert "285BB" in text
    # …and NO second figure, because there is no second figure to state.
    assert "7,22,500" not in text
    assert "books show" not in text


def test_no_ais_finding_at_all_when_there_is_no_income():
    assert not [r for r in docint.detect_document_risks(
        "doc-1", "client-1", {"total_income_paise": 0}, "AIS")
        if r["category"] == "AIS_MISMATCH"]


# ─────────── the mock lists, and the guard that keeps them mock ───────────

# Snapshotted at IMPORT, deliberately. detect_document_risks APPENDS to
# MOCK_DOCUMENT_RISKS — in mock mode that list is the store — so a test above
# that calls it would otherwise put its own row into the sweep below and fail
# it on a client id the test itself chose.
MOCK_LISTS = [
    (insights, "MOCK_AI_INSIGHTS_V2", list(insights.MOCK_AI_INSIGHTS_V2)),
    (risks, "MOCK_RISKS", list(risks.MOCK_RISKS)),
    (docint, "MOCK_DOCUMENT_RISKS", list(docint.MOCK_DOCUMENT_RISKS)),
]


@pytest.mark.parametrize("module,name,rows", MOCK_LISTS,
                         ids=lambda v: getattr(v, "__name__", str(v))[:40])
def test_the_demo_rows_belong_to_demo_clients(module, name, rows):
    """Every fabricated row is attached to a seeded demo client id — c-001 and
    friends. Real client ids are UUIDs, so a demo row cannot be selected for a
    real client even where a reader forgets to branch on SUPABASE_URL. That is
    the belt; the SUPABASE_URL branch is the braces."""
    assert rows, f"{name} is empty — this test would be vacuous"
    for row in rows:
        client_id = str(row.get("client_id") or "")
        assert re.fullmatch(r"c-\d+", client_id), (
            f"{name} carries client_id {client_id!r}, which is not a demo id. A "
            f"fabricated row with a real-looking client id is a demo number "
            f"that reads as a client's own.")


def test_every_reader_of_a_mock_risk_list_branches_on_the_database():
    """The RULE: a function that reads one of these lists must first check
    whether a real database is configured. Stated over the source rather than
    per function, so a new reader is caught the day it is written."""
    offenders = []
    for path in (API / "domain" / "risk_engine.py",
                 API / "repositories" / "ai_insights_repository.py"):
        tree = ast.parse(path.read_text())
        text = path.read_text()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            src = ast.get_source_segment(text, node) or ""
            if "MOCK_" not in src:
                continue
            if "SUPABASE_URL" not in src and "_USE_MOCK" not in src:
                offenders.append(f"{path.name}::{node.name}")
    assert not offenders, (
        "these read a demo list without checking for a real database: "
        + ", ".join(offenders))


def test_the_unversioned_document_intelligence_router_stays_unmounted():
    """It serves MOCK_DOCUMENTS and MOCK_CLIENTS with no firm scope and no
    SUPABASE_URL branch — a real CA would see demo documents belonging to demo
    clients as their own. It was retired in the R2.8 fix phase; v1 and v2 are
    the audited replacements. Mounting it again is the regression."""
    os.environ.setdefault("APP_ENV", "development")
    from main import app
    mounted = {r.path for r in app.routes}
    assert not any(p.startswith("/api/document-intelligence/") for p in mounted), (
        "routers/document_intelligence.py is mounted again — see the comment in "
        "main.py and use document-intelligence-v1 / -v2 instead")
    # …and the versioned ones ARE there, so this is not passing by the whole
    # feature having disappeared.
    assert any(p.startswith("/api/document-intelligence-v1/") for p in mounted)
    assert any(p.startswith("/api/document-intelligence-v2/") for p in mounted)
