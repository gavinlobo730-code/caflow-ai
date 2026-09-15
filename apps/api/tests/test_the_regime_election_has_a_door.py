"""
§115BAC(6) WAS MODELLED AND NOBODY COULD ASK IT.

`domain/income_tax/regime_election.py` holds the two clauses of §115BAC(6)
with Rule 21AGA, and had NO production caller — the only mention of it outside
its own file and its own tests was a COMMENT in
`domain/payroll/declarations.py`. Its own docstring says why that mattered:

    "A missed Form 10-IEA taxes a client on the new regime for a year they
    planned around the old one, and it cannot be cured after the due date. A
    withdrawal made without realising it is final closes an option worth lakhs
    over a career. Neither failure is visible in the return — it computes
    cleanly either way."

Found by the same sweep that found the FX revaluation and the UQC list: a
module under `domain/` that nothing imports.

This module pins the DOOR. The rule itself is `tests/test_regime_election.py`'s
and is not restated here.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.income_tax as it
from core.auth import get_current_user

API = Path(__file__).resolve().parents[1]
PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


def _client() -> TestClient:
    """Through the REAL HTTP path, not by calling the handler.

    Calling it directly leaves every `Query(...)` default as a Query OBJECT —
    truthy — so `form_10iea_filed_on` read as a supplied value and every test
    got a 422 about the date format. It also means FastAPI's own parsing of
    the repeated `prior` parameter and of `Annotated[FYLabel, Query()]` is
    exercised, which is the half a direct call cannot reach.
    """
    app = FastAPI()
    app.include_router(it.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _ask(**kw):
    params: list[tuple[str, str]] = []
    prior = kw.pop("prior", [])
    kw.setdefault("wants_old_regime", True)
    kw.setdefault("has_business_income", False)
    kw.setdefault("financial_year", "2025-26")
    for k, v in kw.items():
        params.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
    for one in prior:
        params.append(("prior", one))
    return _client().get("/api/income-tax/regime-election", params=params).json()


# ── the two clauses reach the caller ─────────────────────────────────────────

def test_a_client_WITHOUT_business_income_elects_in_the_return():
    out = _ask(has_business_income=False)["data"]
    assert out["route"] == "in_the_return"
    assert out["form_10iea_required"] is False


def test_a_client_WITH_business_income_needs_form_10iea_and_a_date():
    out = _ask(has_business_income=True)["data"]
    assert out["route"] == "form_10iea"
    assert out["form_10iea_required"] is True
    assert out["due_date"], "Rule 21AGA ties the form to the §139(1) due date"


def test_the_due_date_follows_the_AUDIT_date_when_an_audit_applies():
    plain = _ask(has_business_income=True)["data"]["due_date"]
    audit = _ask(has_business_income=True, is_audit=True)["data"]["due_date"]
    assert audit != plain, (
        "Rule 21AGA defers to §139(1), whose date moves to 31 October where "
        "audit applies — a fixed 31 July here would be a second copy of a date "
        "compliance_engine owns")


def test_the_new_regime_needs_no_election_at_all():
    out = _ask(wants_old_regime=False, has_business_income=True)["data"]
    assert out["regime"] == "new"
    assert out["form_10iea_required"] is False


# ── prior history is an INPUT, and silence is its own answer ─────────────────

def test_saying_nothing_about_earlier_years_is_HISTORY_UNKNOWN_not_available():
    """The dangerous direction is assuming availability: it tells a CA the old
    regime is open when their client spent it years ago."""
    out = _ask(has_business_income=True)["data"]
    assert out["history_unknown"] is True


def test_a_prior_WITHDRAWAL_spends_the_option():
    out = _ask(has_business_income=True, prior=["2024-25:withdrew"])["data"]
    assert out["election_is_available"] is False
    assert out["history_unknown"] is False


def test_a_prior_OPT_OUT_does_not_spend_it():
    """The proviso bars a further election only after a WITHDRAWAL; opting out
    across years leaves the option exercised, not consumed."""
    out = _ask(has_business_income=True, prior=["2024-25:opted_out"])["data"]
    assert out["election_is_available"] is True
    assert out["history_unknown"] is False


# ── the wire format is the ROUTER's business, and it refuses cleanly ─────────

@pytest.mark.parametrize("bad", [
    "2024-25", "2024-25:", "2024-25:maybe", "opted_out", "2024-25:OPTED OUT",
])
def test_a_malformed_prior_election_is_REFUSED_with_the_format(bad):
    out = _ask(has_business_income=True, prior=[bad])
    assert out["success"] is False
    assert "opted_out" in (out["error"] or "") and "withdrew" in (out["error"] or "")


def test_the_action_is_case_and_space_insensitive():
    out = _ask(has_business_income=True, prior=["2024-25:  WITHDREW "])["data"]
    assert out["election_is_available"] is False


def test_a_malformed_FY_in_a_prior_election_is_refused():
    out = _ask(has_business_income=True, prior=["2024-28:withdrew"])
    assert out["success"] is False


def test_a_malformed_filing_date_is_refused_with_the_format():
    out = _ask(has_business_income=True, form_10iea_filed_on="31-07-2026")
    assert out["success"] is False
    assert "YYYY-MM-DD" in (out["error"] or "")


def test_a_LATE_form_is_not_merely_a_warning():
    """Rule 21AGA: filed after the §139(1) date, the new regime applies
    whatever the return says."""
    on_time = _ask(has_business_income=True,
                   form_10iea_filed_on="2026-07-01")["data"]
    late = _ask(has_business_income=True,
                form_10iea_filed_on="2027-01-01")["data"]
    assert on_time["regime"] == "old"
    assert late["regime"] == "new"
    assert late["election_is_available"] is False


# ── the shape of the door ────────────────────────────────────────────────────

def test_the_endpoint_reads_and_writes_nothing():
    """Arithmetic and dates on facts the caller states, like §44AB and HRA
    beside it. A GET deliberately — it avoids an entry on
    test_write_requires_write_permission.py's compute-only allowlist, which
    every POST preview has to earn."""
    src = (API / "routers" / "income_tax.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "regime_election")
    body = ast.dump(fn)
    for writer in ("insert", "update", "upsert", "delete", "get_supabase"):
        assert writer not in body, f"regime_election touches {writer}"


def test_it_carries_a_read_permission_on_the_income_tax_resource():
    src = (API / "routers" / "income_tax.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "regime_election")
    defaults = ast.dump(ast.Tuple(elts=list(fn.args.defaults), ctx=ast.Load()))
    assert "'income_tax'" in defaults and "'read'" in defaults


def test_the_due_date_is_not_restated_in_this_module():
    """CLAUDE.md names compliance_engine as the single source for every due
    date. The domain module already defers to it; the ROUTER must not shortcut
    past either."""
    src = (API / "routers" / "income_tax.py").read_text()
    start = src.index("def regime_election(")
    end = src.index("@router.post(\"/hra/compute\")", start)
    block = src[start:end]
    for spelled in ("31 July", "31-07", "07-31", "October 31"):
        assert spelled not in block, f"the router spells a due date ({spelled})"


def test_the_financial_year_is_a_TYPED_label_not_a_bare_string():
    """`2026-28` passes a shape regex and then means 2026-27."""
    src = (API / "routers" / "income_tax.py").read_text()
    start = src.index("def regime_election(")
    block = src[start:src.index("):", start)]
    assert "FYLabel" in block
    assert "Annotated[FYLabel, Query()]" in block, (
        "`fy: FYLabel = Query(...)` validates NOTHING — FastAPI discards the "
        "Annotated metadata when Query() sits in the default position")
