"""ONE ANSWER TO "IS THIS A COMPANIES ACT COMPANY", ON BOTH SIDES.

Two implementations decide it and they answer different questions with it:

  * `services/compliance_obligation_service.is_companies_act_company` settles
    the ITR due date — Explanation 2(a)(i) to §139(1) gives a company 31 October
    unconditionally — and drives `_roc_obligations`, which puts AOC-4 (§137),
    MGT-7 (§92) and ADT-1 (§139) on the compliance calendar.
  * `apps/web/lib/entityObligations.mcaRegime` decides whether the MCA workspace
    is OFFERED at all, and whether Year End may describe a set of statements as
    Schedule III.

The two SETS were identical, six values each, and held together by nothing but
a comment in each file saying the other agreed — the drift shape CLAUDE.md
records three times.

**THE NORMALISATIONS WERE NOT IDENTICAL, AND THAT IS THE DEFECT.** Python folds
runs of whitespace AND UNDERSCORES; the browser folded whitespace alone. So
`private_limited` was a Companies Act company on the server and not in the
browser: the calendar generated AOC-4 and MGT-7 for a client whose MCA
workspace the product then refused to show, and Year End declined to call their
statements Schedule III. The underscore is not hypothetical —
`normalise_entity_type`'s own docstring says the income-tax page renders entity
types with `.replace(/_/g, " ")`, so underscored spellings have been seen in
this data, and *the bug it replaced was a title-case value tested against an
underscored constant*. The same defect had simply never been swept out of
`apps/web`.

**THE LLP LIMB IS THE BROWSER'S ALONE AND THAT IS RIGHT.** `mcaRegime` has a
third answer: an LLP IS on the MCA portal but files Form 11 (§35) and Form 8
(§34) under the LLP Act 2008, not AOC-4 and not MGT-7. Python has no LLP set
because the only question it asks is the ITR due date, which an LLP does not
settle on entity type alone — LLP Act §34(4) with Rule 24(8) is a different
test and `itr_due_date_for_client` REFUSES. A test below asserts the asymmetry
so nobody "completes" it by giving Python a set that would decide nothing.

**THIS GUARD IS PYTHON** — the Schedule III lesson. One in `apps/web` would
assert the browser against a copy of itself. It runs BOTH implementations over
`shared/entity-type-vectors.json` rather than comparing two descriptions of
them, because the whole finding is that the two NORMALISE differently.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from services.compliance_obligation_service import (
    CLIENT_ENTITY_TYPES,
    is_companies_act_company,
    normalise_entity_type,
)

API = pathlib.Path(__file__).resolve().parent.parent
REPO = API.parent.parent
WEB = REPO / "apps" / "web"
MODULE = WEB / "lib" / "entityObligations.ts"
VECTORS = json.loads((REPO / "shared" / "entity-type-vectors.json").read_text())

_CASES = (
    [(v, True) for v in VECTORS["companies_act"]]
    + [(v, False) for v in VECTORS["not_companies_act"]]
)


def _browser(values: list[str]) -> list[str]:
    """`mcaRegime` for each value, through node."""
    script = (
        f"const m = await import({json.dumps(str(MODULE))});\n"
        f"const vs = {json.dumps(values)};\n"
        "process.stdout.write(JSON.stringify(vs.map((v) => m.mcaRegime(v))));"
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "--experimental-strip-types", "-e", script],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"node cannot run entityObligations here: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


_ALL = [v for v, _ in _CASES]
_REGIMES = _browser(_ALL)


def test_the_fixture_is_not_empty():
    """Vacuity floor: a fixture that lost its cases would pass every parametrised
    assertion below by having none."""
    assert len(VECTORS["companies_act"]) >= 12
    assert len(VECTORS["not_companies_act"]) >= 8


@pytest.mark.parametrize("value,expected", _CASES)
def test_both_sides_agree_on_every_vector(value: str, expected: bool):
    server = is_companies_act_company(value)
    browser = _REGIMES[_ALL.index(value)] == "companies-act"
    assert server == expected, f"the server says {server} for {value!r}"
    assert browser == expected, f"the browser says {browser} for {value!r}"


def test_an_underscored_spelling_reaches_both():
    """The specific case that was broken, asserted on its own so a regression
    names itself rather than appearing as one of twenty-eight parametrisations."""
    assert is_companies_act_company("private_limited")
    assert _browser(["private_limited"])[0] == "companies-act"


def test_both_normalisations_fold_the_same_characters():
    """On the SOURCE as well as the answers: the fixture can only cover the
    strings somebody thought of, and the rule is about a character class."""
    src = MODULE.read_text(encoding="utf-8")
    assert r"replace(/[\s_]+/g, " in src, (
        "lib/entityObligations.key must fold underscores as well as whitespace, "
        "the way services/compliance_obligation_service.normalise_entity_type "
        "does"
    )
    py = (API / "services" / "compliance_obligation_service.py").read_text(encoding="utf-8")
    assert r'sub(r"[\s_]+", " "' in py


def test_every_entity_type_the_schema_allows_is_classified_on_both_sides():
    """A value the CHECK permits that neither side recognises is a client whose
    regime nothing decides. The Python list is derived from migration 001 by
    `test_compliance_itr_due_date`; this walks it through the browser too."""
    regimes = _browser(list(CLIENT_ENTITY_TYPES))
    for entity, regime in zip(CLIENT_ENTITY_TYPES, regimes):
        server = is_companies_act_company(entity)
        if server:
            assert regime == "companies-act", f"{entity}: server says company, browser says {regime}"
        else:
            assert regime in ("llp-act", "none"), f"{entity}: browser says {regime}"


def test_the_llp_limb_is_the_browsers_alone_and_says_so():
    """An LLP must be `llp-act` in the browser and NOT a Companies Act company
    on either side. Python deliberately has no LLP set: the only question it
    asks is the ITR due date, which an LLP does not settle on entity type
    alone."""
    assert _browser(["LLP", "llp", "Limited Liability Partnership"]) == ["llp-act"] * 3
    assert not is_companies_act_company("LLP")
    py = (API / "services" / "compliance_obligation_service.py").read_text(encoding="utf-8")
    assert "_LLP_ACT" not in py and "llp act" not in py.lower().replace("llp act 2008", ""), (
        "compliance_obligation_service has grown an LLP classification. If the "
        "ITR due date now turns on it, this test and the fixture's note need "
        "rewriting rather than deleting."
    )


def test_neither_side_states_the_other_agrees_without_naming_this_guard():
    """Both files carried a comment asserting the other held the identical set,
    which is the claim that went unchecked. Each must now name where it is
    checked."""
    for path in (MODULE, API / "services" / "compliance_obligation_service.py"):
        src = path.read_text(encoding="utf-8")
        if "entityObligations" in src or "compliance_obligation_service" in src:
            assert "entity-type-vectors" in src or "normalise_entity_type" in src, (
                f"{path.name} refers to the other implementation without naming "
                "what holds the two together"
            )
