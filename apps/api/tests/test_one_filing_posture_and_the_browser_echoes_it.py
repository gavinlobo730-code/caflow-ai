"""This product words its filing position once, and the browser echoes it.

THE DEFECT

    PracticeSync computes every Indian statutory return and transmits none of
    them. That is permanent and load-bearing — CLAUDE.md makes "never
    auto-submit anything to any government portal" a rule, and real submission
    needs registrations (a GSP for GST, an ERI for income tax, NIC credentials
    for e-way and e-invoice) that are months of commercial work rather than
    code.

    The product stated it in THREE voices. `services/filing_demo/common.
    envelope` built one sentence into every walk-through's payload. The wizard
    HARD-CODED A DIFFERENT SENTENCE into its banner — the two were never the
    same words, and nothing compared them. And the guard over that banner read

        assert.match(src, /DEMO — nothing is being filed/)

    which asserts that a STRING is present in the source. It cannot tell a
    banner that renders from one that is commented out, it cannot tell a
    sticky banner from one that scrolls away, and it fails on any rewording
    however much better — which is exactly the "a guard states one spelling of
    its own rule" shape this repository has now fixed five times.

    None of the three said what a CA evaluating the software most wants to
    know: that direct submission is intended, and what stands in the way.

THE RULE, AND WHY THIS GUARD IS ON THE PYTHON SIDE

    `domain/filing_posture.py` is the authority. `apps/web/lib/filing/
    posture.ts` is a FALLBACK for the window where the frontend has redeployed
    ahead of the backend, and for the frame before the fetch returns.

    A guard written in `apps/web` would assert that file against a copy of
    itself and pass whenever both drifted together — which is what the
    Schedule III caption list did for months, and what the marketing config
    did until 24-09-2026. So the comparison happens here, where the authority
    lives.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from domain.filing_posture import POSTURE, posture_payload

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
FALLBACK_TS = WEB / "lib" / "filing" / "posture.ts"
WIZARD = WEB / "components" / "FilingDemoWizard.tsx"

FIELDS = ("badge", "headline", "body", "roadmap", "disclaimer")


def _browser_posture() -> dict:
    """Evaluate the fallback module itself rather than regexing its strings.

    The strings are written as `"a " + "b " + "c"` concatenations so they stay
    inside the line length, and a regex over the source would have to
    reimplement that join. Node is already how the marketing-parity and
    identifier-parity guards read TypeScript.
    """
    script = (
        f'import {{ FILING_POSTURE }} from "{FALLBACK_TS}";\n'
        "process.stdout.write(JSON.stringify(FILING_POSTURE));\n"
    )
    out = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        pytest.skip(f"node could not read the fallback module: {out.stderr[-400:]}")
    return json.loads(out.stdout)


# ── 1. the two agree, field by field ────────────────────────────────────────


@pytest.mark.parametrize("field", FIELDS)
def test_the_browser_fallback_matches_the_authority(field):
    """Field by field rather than dict-equal, so a failure names WHICH
    sentence drifted instead of printing two paragraphs side by side."""
    mine = getattr(POSTURE, field)
    theirs = _browser_posture().get(field)
    assert theirs == mine, (
        f"apps/web/lib/filing/posture.ts `{field}` has drifted from "
        f"domain/filing_posture.POSTURE.{field}.\n"
        f"  authority: {mine!r}\n"
        f"  browser:   {theirs!r}\n"
        "Edit the PYTHON module and copy the string across — the browser copy "
        "is a fallback, never a second implementation."
    )


def test_the_browser_declares_no_field_the_authority_lacks():
    """The other direction. A value invented in the browser is one that never
    arrives from the server, so it would show only in the redeploy window and
    then silently stop — the hardest kind of copy defect to notice."""
    extra = set(_browser_posture()) - set(FIELDS)
    assert not extra, f"the browser fallback declares unknown field(s): {sorted(extra)}"


# ── 2. the payload carries it ───────────────────────────────────────────────


def test_every_filing_demo_response_carries_the_posture():
    from services.filing_demo.common import envelope

    e = envelope(
        "gstr3b", "t", "s", "seed",
        {"how": "h", "software_permitted": False, "note": "n"},
        "when this is real", [],
    )
    assert e["posture"] == posture_payload()
    assert e["disclaimer"] == POSTURE.disclaimer
    # The two keys are not redundant: `disclaimer` is the long form every
    # existing caller and test already reads, and `posture` is the same
    # position broken into the pieces a banner needs.
    assert e["disclaimer"] != e["posture"]["body"]


def test_the_payload_is_a_copy_so_one_flow_cannot_reword_the_product():
    a, b = posture_payload(), posture_payload()
    a["headline"] = "mutated"
    assert b["headline"] == POSTURE.headline
    assert posture_payload()["headline"] == POSTURE.headline


# ── 3. the wizard renders it, and holds no rival wording ────────────────────


def _wizard_source_without_comments() -> str:
    src = WIZARD.read_text()
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in src.split("\n"))


def test_the_wizard_renders_the_served_posture():
    """The RULE, not a spelling of it: the banner's three lines each come from
    the posture object. A rewording in Python now reaches the screen; it used
    to reach only the payload."""
    src = _wizard_source_without_comments()
    for field in ("headline", "body", "roadmap"):
        assert f"posture.{field}" in src, (
            f"the wizard no longer renders posture.{field} — the banner has "
            "gone back to its own wording, which is how the product came to "
            "state its filing position two different ways"
        )


def test_the_wizard_prefers_the_served_value_over_its_fallback():
    src = _wizard_source_without_comments()
    assert re.search(r"script\?\.posture\s*\?\?\s*FILING_POSTURE", src), (
        "the wizard must read `script?.posture ?? FILING_POSTURE`. Reading the "
        "fallback directly makes the served value dead, and the parity guard "
        "above would then be pinning a constant nobody renders"
    )


def test_no_screen_writes_its_own_filing_disclaimer():
    """A second wording anywhere in apps/web is the defect returning.

    Matched on the DISTINCTIVE phrases rather than on a whole sentence, so a
    copy that paraphrases is caught too. The fallback module is the one place
    allowed to hold them.
    """
    banned = ("nothing is being filed", "No data leaves PracticeSync", "no government system is contacted")
    offenders: list[str] = []
    for f in WEB.rglob("*.ts*"):
        rel = f.relative_to(WEB).as_posix()
        if rel.startswith(("node_modules/", ".next/", "out/", "scripts/")):
            continue
        if rel == "lib/filing/posture.ts":
            continue
        body = f.read_text(errors="ignore")
        body = re.sub(r"/\*[\s\S]*?\*/", "", body)
        body = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.split("\n"))
        for phrase in banned:
            if phrase in body:
                offenders.append(f"{rel}: {phrase!r}")
    assert not offenders, (
        "a screen states the filing position in its own words:\n  "
        + "\n  ".join(offenders)
        + "\nRender the served `posture` instead — domain/filing_posture.py is "
        "the one authority."
    )


# ── 4. what the wording may and may not claim ───────────────────────────────


def test_the_roadmap_sentence_claims_no_registration_this_product_lacks():
    """D17, 24-09-2026: the owner starts the GSP/ERI/NIC applications once a CA
    demo happens. As at that date none has been applied for.

    A product that says a registration is "in progress" or "pending approval"
    is making a claim about its own regulatory standing, which is a different
    and worse kind of wrong from a marketing overstatement — so the forbidden
    phrasings are asserted rather than left to a reviewer's eye.
    """
    text = " ".join(getattr(POSTURE, f) for f in FIELDS).lower()
    for claim in (
        "in progress", "under way", "underway", "applied for", "pending approval",
        "awaiting approval", "registered gsp", "we are registered", "coming soon",
    ):
        assert claim not in text, (
            f"the filing posture claims {claim!r}. No GSP, ERI or NIC "
            "registration has been applied for (D17) — say what is PLANNED and "
            "what gates it, never what is in motion."
        )
    assert "planned" in text, "the posture must say direct submission is planned"


def test_the_posture_never_says_anything_was_filed():
    text = " ".join(getattr(POSTURE, f) for f in FIELDS).lower()
    assert "nothing has been filed" in text or "no return is being filed" in text
    for lie in ("successfully filed", "submitted to", "has been submitted"):
        assert lie not in text, f"the posture says {lie!r}"
