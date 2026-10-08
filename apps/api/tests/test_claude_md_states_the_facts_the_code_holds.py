"""The design record states a few facts the code owns, and they are held to the code (engineering-24).

WHAT WAS WRONG
    CLAUDE.md is the repository's main design record and it is one very large file edited by every change. A fact
    written into it is a second copy of something the code already says, and nothing compared the two. It had
    already gone wrong in the expensive way: for a day after Groq retired `llama-3.3-70b-versatile` (a live
    `model_not_found`, 29-09-2026) the file went on naming the dead model as the default, and the person reading it
    to set an environment variable would have trusted it. The only tests that mention CLAUDE.md check narrow
    citations (a compliance marker points at a file that exists), never a stated value.

WHAT THIS HOLDS, AND WHY THESE
    A short list, chosen because each is a value somebody sets, reads or tunes by hand on the strength of the page:

      * the Groq and the Gemini DEFAULT model, and that the environment variable the page says overrides each one
        really does (a default that the override cannot reach is a different fact from the one the page states);
      * the four AI rate-limit buckets (`chat`, `intelligence`, `extract`, `vision`) and their per-minute figures;
      * the gateway's forty-second budget against the browser client's forty-five-second abort, the pair the page
        gives as the reason the budget is what it is, and the relation between them that must hold whatever either
        number becomes (the call has to finish before the browser gives up on it);
      * every environment variable the page names as one the backend reads, which the backend must still read.

    What this file does NOT do is say the prose is right. It compares a number or a name written on the page with
    the code that owns it, and fails with the sentence to fix. It parses the page where the value is written and
    FAILS when it cannot find it there: a bullet that was reworded or moved is a reason to update this test, never a
    reason for it to pass over nothing.

WHAT IS DELIBERATELY NOT HERE
    * The migration directory having no duplicate numbers beyond the recorded historical ones: that is already
      `tests/test_migration_numbering.py`, which holds the six known pairs and fails a seventh, and a second copy of
      it would be two lists to keep in step. The same goes for "no AI key is named in either browser app"
      (`tests/test_the_facts_behind_the_marketing_claims.py`).
    * A TEST COUNT. The page says "~7,000 tests" and the suite has collected more than three times that for a while;
      a count is out of date the day it is written, and a test that pins one fails on every addition. The right
      fix is for the page to stop stating one, and that is an edit to the page, which is not made here.
    * Which RELEASE of a model a provider serves. That is a fact about a live account, and the probe on the Partner's
      AI status screen is the check for it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.ai import gateway, gemini_vision, groq_text
from middleware.rate_limit import BUCKETS
from tests.test_render_manifest_matches_code import _read_by_code

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
CLAUDE_MD = REPO / "CLAUDE.md"
WEB_API_CLIENT = REPO / "apps" / "web" / "lib" / "api" / "index.ts"

pytestmark = pytest.mark.skipif(not CLAUDE_MD.is_file(), reason="CLAUDE.md is not in this checkout")


def _page() -> str:
    """The design record with every run of whitespace collapsed to one space, so a sentence the editor wrapped
    across lines reads as it does on screen."""
    return re.sub(r"\s+", " ", CLAUDE_MD.read_text(encoding="utf-8"))


def _found(pattern: str, what: str) -> re.Match:
    hit = re.search(pattern, _page())
    assert hit, (f"CLAUDE.md no longer states {what} where this test looks for it. If the sentence was reworded or "
                 "moved, update the pattern here; do not delete the test, it is what keeps the page and the code "
                 "saying the same thing.")
    return hit


# ═══ The model defaults ══════════════════════════════════════════════════════════════════════════════════════════

def _stated_default(provider_marker: str) -> tuple[str, str]:
    """(the default model the page names, the environment variable it says overrides it) for one provider bullet."""
    hit = _found(rf"\*\*{provider_marker}\*\* .{{0,700}}?Default model `([^`]+)`.{{0,250}}?overridable via `([A-Z_]+)`",
                 f"the {provider_marker} default model and its override")
    return hit.group(1), hit.group(2)


def test_the_groq_default_model_the_page_names_is_the_one_the_code_uses():
    stated, _ = _stated_default("Groq")
    assert stated == groq_text.DEFAULT_TEXT_MODEL, (
        f"CLAUDE.md says the Groq default is `{stated}` and domain/ai/groq_text.py sets "
        f"`{groq_text.DEFAULT_TEXT_MODEL}`. The code is the authority: fix the page.")


def test_the_gemini_default_model_the_page_names_is_the_one_the_code_uses():
    stated, _ = _stated_default("Gemini")
    assert stated == gemini_vision.DEFAULT_VISION_MODEL, (
        f"CLAUDE.md says the Gemini default is `{stated}` and domain/ai/gemini_vision.py sets "
        f"`{gemini_vision.DEFAULT_VISION_MODEL}`. The code is the authority: fix the page.")


@pytest.mark.parametrize("provider, current, default", [
    ("Groq", lambda: groq_text.text_model(), lambda: groq_text.DEFAULT_TEXT_MODEL),
    ("Gemini", lambda: gemini_vision.vision_model(), lambda: gemini_vision.DEFAULT_VISION_MODEL),
])
def test_the_variable_the_page_says_overrides_a_default_really_does(monkeypatch, provider, current, default):
    """A default that the stated override cannot reach is not the fact the page states. Setting the variable the
    page names moves the model; clearing it, or setting it to blanks, puts the default back."""
    _, variable = _stated_default(provider)
    monkeypatch.setenv(variable, "a-model-somebody-chose")
    assert current() == "a-model-somebody-chose", f"{variable} no longer overrides the {provider} model"
    monkeypatch.setenv(variable, "   ")
    assert current() == default(), f"a blank {variable} must fall back to the default, not to an empty model name"
    monkeypatch.delenv(variable)
    assert current() == default()


def test_the_model_the_page_calls_retired_is_not_the_default_of_either_provider():
    """The mistake this file exists for, said directly. The page may MENTION the retired model (it says when and why
    it was retired); it may not be the one the code defaults to."""
    assert "llama-3.3-70b-versatile" not in (groq_text.DEFAULT_TEXT_MODEL, gemini_vision.DEFAULT_VISION_MODEL)
    assert "gemini-2.5-flash" not in (groq_text.DEFAULT_TEXT_MODEL, gemini_vision.DEFAULT_VISION_MODEL)


# ═══ The rate-limit buckets ══════════════════════════════════════════════════════════════════════════════════════

def test_the_rate_limit_figures_the_page_states_are_the_buckets_the_code_enforces():
    hit = _found(r"`chat` (\d+)/min, `intelligence` (\d+), `extract` (\d+), `vision` (\d+)",
                 "the four AI rate-limit buckets")
    stated = dict(zip(("chat", "intelligence", "extract", "vision"), map(int, hit.groups()), strict=True))
    for name, per_minute in stated.items():
        assert name in BUCKETS, f"CLAUDE.md names a `{name}` bucket the limiter does not have"
        limit, window_seconds = BUCKETS[name]
        assert (limit, window_seconds) == (per_minute, 60), (
            f"CLAUDE.md says `{name}` is {per_minute}/min and middleware/rate_limit.py allows {limit} per "
            f"{window_seconds} s")


# ═══ The forty-second budget and the forty-five-second abort ═════════════════════════════════════════════════════

def _browser_abort_seconds() -> float:
    assert WEB_API_CLIENT.is_file(), "apps/web/lib/api/index.ts is where the browser client's abort is read from"
    hit = re.search(r"controller\.abort\(\)\s*,\s*([0-9_]+)\s*\)", WEB_API_CLIENT.read_text(encoding="utf-8"))
    assert hit, "the browser client no longer aborts through `controller.abort()` on a timer; update this reading"
    return int(hit.group(1).replace("_", "")) / 1000


def test_the_gateway_finishes_a_call_before_the_browser_gives_up_on_it():
    """THE RELATION, which must hold whatever either number becomes: `lib/api` aborts at N seconds and never
    retries, so a model call that can run longer than that is a call the user is told failed while it is still
    spending tokens. The gateway holds the whole call (every retry, every fallback) to a budget below the abort."""
    assert gateway.TOTAL_BUDGET_S < _browser_abort_seconds(), (
        f"the gateway allows a call {gateway.TOTAL_BUDGET_S} s and the browser client aborts at "
        f"{_browser_abort_seconds()} s")


def test_the_two_numbers_the_page_gives_for_it_are_the_numbers_in_the_code():
    hit = _found(r"held to (\d+) seconds because `lib/api` aborts at (\d+)", "the gateway budget and the browser abort")
    budget, abort = map(int, hit.groups())
    assert budget == gateway.TOTAL_BUDGET_S, f"CLAUDE.md says {budget} s and domain/ai/gateway.py says {gateway.TOTAL_BUDGET_S}"
    assert abort == _browser_abort_seconds(), f"CLAUDE.md says the browser aborts at {abort} s and the client says {_browser_abort_seconds()}"


# ═══ The environment variables the page names ════════════════════════════════════════════════════════════════════

#: Every variable CLAUDE.md names as one the backend reads, with the sentence's reason for being on the list. Each
#: must still be named on the page (so the list cannot outlive the sentence) and still be read by the backend (so
#: the page cannot go on telling somebody to set one nothing looks at). A variable the page names that is NOT on
#: this list is not asserted; the list is the short set whose value somebody sets by hand.
NAMED_AS_READ: dict[str, str] = {
    "GROQ_API_KEY": "the text provider's key; without it the assistant is mock text and the probe says `skipped`",
    "GEMINI_API_KEY": "the vision provider's key; without it image extraction fails closed",
    "GROQ_TEXT_MODEL": "overrides the Groq default",
    "GEMINI_VISION_MODEL": "overrides the Gemini default",
    "GROQ_TEXT_MODEL_FALLBACK": "the second route; none is built in, so unset means none",
    "GEMINI_VISION_MODEL_FALLBACK": "the second route for the vision door; unset means none",
    "USE_USER_JWT": "whether requests run as the caller, so row-level security applies on the API path",
    "REQUIRE_MFA": "whether MFA is enforced on the routers that carry the guard",
    "APP_ENV": "`production` literally decides the two safety switches' defaults",
    "SUPABASE_JWT_ISSUER": "the issuer a login token must carry where the project has a custom auth domain",
    "TRUSTED_PROXY_HOPS": "how many proxies in front of the API wrote the forwarded address",
    "ENABLE_SCHEDULER": "the in-process daily sweep, enabled in exactly one process",
    "ENABLE_FILING_SIMULATION": "the kill switch for the demo filing walk-throughs",
    "PRACTICE_MAIL_ENABLED": "the practice's own mail switch, off unless explicitly on",
}


def test_the_list_is_long_enough_to_mean_something_and_the_scan_finds_the_reads():
    assert len(NAMED_AS_READ) >= 10
    assert len(_read_by_code()) >= 15, "the environment scan found almost nothing; the checks below would pass over nothing"


@pytest.mark.parametrize("name", sorted(NAMED_AS_READ))
def test_a_variable_the_page_names_is_still_named_on_the_page(name):
    assert f"`{name}`" in _page(), (
        f"CLAUDE.md no longer names `{name}`. Remove it from NAMED_AS_READ ({NAMED_AS_READ[name]}) or put the "
        "sentence back; the list is held to the page and the page to the code.")


@pytest.mark.parametrize("name", sorted(NAMED_AS_READ))
def test_a_variable_the_page_names_as_read_is_read_by_the_backend(name):
    read = _read_by_code()
    assert name in read, (
        f"CLAUDE.md tells a reader `{name}` matters ({NAMED_AS_READ[name]}) and nothing in apps/api reads it. "
        "Either the code stopped honouring it, or the scan's reading of how it is read needs extending "
        "(tests/test_render_manifest_matches_code.py `_READ`).")


# ═══ Known contradictions between a sentence on the page and a thing the code now holds ══════════════════════════
#
# There is NO generic detector for a prose rule, and this file does not pretend to be one: a sentence that says
# "X is not built" goes stale the day X is built, and nothing can tell from the sentence alone. What can be pinned
# is each contradiction that has actually been found, in the direction that cannot be satisfied by deleting the
# test: the page must not say the thing WHILE the code that makes it false is still in the tree. Each case names
# both halves, so a reader who trips it sees what changed.

def test_the_page_does_not_say_the_revised_and_updated_return_is_unbuilt():
    """IT-23 built the §139(5) revised and §139(8A) updated return (migration 381 gave `itr_filings` a
    `return_type`; `domain/income_tax/return_type.py` is the authority; `GET /api/itr/return-kinds` serves it). The
    seven-forms bullet went on saying they were "Still not built" and that they "need a migration replacing
    migration 319's UNIQUE", which is the opposite of the IT-23 bullet far above it."""
    assert (API / "domain" / "income_tax" / "return_type.py").is_file(), "premise: the return-kind authority exists"
    assert list((API / "migrations").glob("381_*.sql")), "premise: migration 381 exists"
    page = _page()
    assert not re.search(r"Still not built: the §139\(5\) revised and §139\(8A\) updated return", page), (
        "CLAUDE.md still says the §139(5) revised and §139(8A) updated return are not built; "
        "domain/income_tax/return_type.py and migration 381 build them. See the IT-23 return-kinds bullet.")
    assert not re.search(r"need a `return_type` and a migration replacing migration 319", page), (
        "CLAUDE.md still says the revised return needs a migration replacing migration 319's key; migration 381 "
        "is that migration.")


_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}


def test_the_page_counts_what_the_irp_module_names_as_not_held():
    """GST-32 names the things `irp_validations` does not hold, and the page gave a COUNT. Migration 411 gave a sales
    invoice line an `is_service` and `goods_unit_finding` now asks the goods-only quantity rule, so the module's
    `NOT_HELD` went from five entries to four while the page went on saying five and on saying the goods-only rule
    "needs an `is_service` that `client_sales_invoice_lines` does not have". The number is what is held to the code;
    the clause is the known contradiction."""
    from domain.gst import irp_validations

    hit = _found(r"(\w+) things are NAMED as not held", "how many things the IRP validations name as not held")
    stated = _NUMBER_WORDS.get(hit.group(1).lower())
    assert stated is not None, f"CLAUDE.md gives the count as {hit.group(1)!r}, which this test cannot read as a number"
    assert stated == len(irp_validations.NOT_HELD), (
        f"CLAUDE.md says {hit.group(1)} things are named as not held and domain/gst/irp_validations.py `NOT_HELD` "
        f"has {len(irp_validations.NOT_HELD)}. The code is the authority: fix the page.")
    assert hasattr(irp_validations, "goods_unit_finding"), "premise: the goods-only quantity rule is built"
    assert not re.search(r"goods-only quantity rule \(both need an `is_service`", _page()), (
        "CLAUDE.md still says the goods-only quantity rule needs an `is_service` that "
        "`client_sales_invoice_lines` does not have; migration 411 added it and `goods_unit_finding` asks it.")


#: The four returns GST-25 built for a registration that does not file GSTR-1 and GSTR-3B, each the module that
#: decides it. `registrations.files_gstr1_and_3b` has refused such a registration those screens since GST-20; these
#: are the returns it owes instead, and the design record has to say they exist or the next reader concludes the
#: product still has nothing to offer a composition dealer or an e-commerce operator.
GST_25_BUILDERS = ("composition", "gstr8", "gstr4_annual", "gstr9c")


@pytest.mark.parametrize("module", GST_25_BUILDERS)
def test_the_page_names_each_return_builder_for_a_registration_that_does_not_file_gstr1_and_3b(module):
    path = API / "domain" / "gst" / f"{module}.py"
    assert path.is_file(), f"premise: {path} exists; if it was renamed, update GST_25_BUILDERS and the page together"
    assert f"domain/gst/{module}.py" in _page(), (
        f"CLAUDE.md does not name `domain/gst/{module}.py`, the builder GST-25 added for a registration that "
        "does not file GSTR-1 and GSTR-3B. Add it to the GST-25 bullet (after the multi-registration one).")


def test_the_years_the_page_says_the_gst_late_fee_is_held_for_are_the_years_the_table_holds():
    """The table-3b row for the section 47 late fee said the code refuses a year before 2021-22 and refuses GSTR-9,
    after the same page's section 47 paragraph had said both are computed (`LATE_FEE_RATES` from FY 2017-18,
    `_annual_late_fee` from FY 2022-23). The row now states the held range, and a year added to the table (or the
    first year of the annual fee moving) fails here instead of leaving the row to age."""
    from domain.gst import late_filing

    hit = _found(r"GSTR-1 and GSTR-3B are HELD for FY (\d{4}-\d{2}) to (\d{4}-\d{2})",
                 "the financial years the GSTR-1 and GSTR-3B late fee is held for")
    first, last = hit.groups()
    held = sorted({fy for (_rt, fy) in late_filing.LATE_FEE_RATES})
    assert len(held) >= 10, "premise: the late-fee table holds a run of years, not a stub"
    assert (first, last) == (held[0], held[-1]), (
        f"CLAUDE.md says the GSTR-1 and GSTR-3B late fee is held for FY {first} to {last}; "
        f"domain/gst/late_filing.py LATE_FEE_RATES holds FY {held[0]} to {held[-1]}. "
        "The code is the authority: fix the page.")
    assert late_filing.LATE_FEE_FIRST_HELD_FY == held[0], (
        "LATE_FEE_FIRST_HELD_FY is documented as the first year any ladder is held for; it has drifted from the "
        "table's first year")
    annual = _found(r"GSTR-9 from FY (\d{4}-\d{2}) \(7/2023-CT", "the first financial year the GSTR-9 late fee is held for")
    assert annual.group(1) == late_filing.GSTR9_FEE_FIRST_HELD_FY, (
        f"CLAUDE.md says the GSTR-9 late fee is held from FY {annual.group(1)} and late_filing.py "
        f"GSTR9_FEE_FIRST_HELD_FY is {late_filing.GSTR9_FEE_FIRST_HELD_FY}")
    assert "the §47 late fee for a year BEFORE 2021-22" not in _page(), (
        "the table-3b row still describes the late fee as refused for a year before 2021-22 and for GSTR-9")


def test_the_page_says_the_invoice_furnishing_facility_is_built_and_where():
    """Rule 59(2)'s Invoice Furnishing Facility was "not built" when the GST-11 bullet was written. It is:
    `domain/gst/iff.py`, `GET /api/gst-workspace/iff/compute`, `gst_return_service.iff_from_books` and the
    `IffPanel`, and `return_period.IFF_NOT_BUILT` was renamed `IFF_AVAILABLE` so a quarterly GSTR-1 says it is
    available. The bullet went on saying it was not built, on the very return that now names it."""
    from domain.gst import return_period

    assert (API / "domain" / "gst" / "iff.py").is_file(), "premise: the facility's module exists"
    assert hasattr(return_period, "IFF_AVAILABLE") and not hasattr(return_period, "IFF_NOT_BUILT"), (
        "premise: the quarterly return's sentence says the facility is available")
    page = _page()
    assert not re.search(r"Invoice Furnishing Facility is not built", page), (
        "CLAUDE.md still says Rule 59(2)'s Invoice Furnishing Facility is not built; domain/gst/iff.py builds it.")
    assert "domain/gst/iff.py" in page, (
        "CLAUDE.md does not name domain/gst/iff.py, the Rule 59(2) builder. Describe it beside the GST-11 bullet.")


def test_the_page_does_not_say_the_payment_code_is_unwired_from_the_deductee_rows():
    """`Vocabulary.payment_code()` was "deliberately NOT yet wired into `tds_return_service.py`'s per-line deductee
    output" when it was written. `domain/tds/deductee_payment_code.py` wires it onto the 24Q/26Q/27Q rows
    (TDS-INCOME-TAX-31), and `tds_return_service` imports it; the later bullet says so and the earlier one did not."""
    wired = (API / "services" / "tds_return_service.py").read_text(encoding="utf-8")
    assert "deductee_payment_code" in wired, "premise: tds_return_service uses deductee_payment_code"
    assert not re.search(r"deliberately NOT yet wired into `tds_return_service\.py`", _page()), (
        "CLAUDE.md still says the s.393 payment code is not wired into tds_return_service.py's deductee rows; "
        "domain/tds/deductee_payment_code.py does that. Point the sentence at the TDS-INCOME-TAX-31 bullet.")
