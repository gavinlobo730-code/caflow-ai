"""What this product says about filing, in one place and one voice.

WHY THIS MODULE EXISTS

    PracticeSync computes every Indian statutory return and transmits none of
    them. That is a permanent, load-bearing fact about the product — CLAUDE.md
    makes "never auto-submit anything to any government portal" a rule, and
    real submission needs registrations (a GSP for GST, an ERI for income tax,
    NIC credentials for e-way and e-invoice) that are months of commercial work
    rather than code.

    The product said so in THREE different voices. `services/filing_demo/
    common.envelope` built one sentence into every walk-through's payload;
    `components/FilingDemoWizard.tsx` hard-coded a DIFFERENT sentence into its
    banner; and a guard pinned that second sentence with
    `assert.match(src, /DEMO — nothing is being filed/)` — a regex over the
    SOURCE, which asserts that a string is present rather than that a banner
    exists, and which fails on any rewording however much better.

    None of the three said the thing a CA evaluating the software most wants
    to know: that direct submission is intended, and what stands in the way.
    The owner's direction, 24-09-2026: *"in the software only we can write that
    this is just a simulation, the real filings would be coming soon — you can
    sharpen the words professionally."*

THE RULE

    One posture, worded once, served to the browser. `apps/web/lib/filing/
    posture.ts` holds a FALLBACK for the window where the frontend has
    redeployed ahead of the backend — the `scheduleIiiCaptions.ts` shape — and
    `tests/test_one_filing_posture_and_the_browser_echoes_it.py` pins the two
    FROM THE PYTHON SIDE, because a guard written in `apps/web` would assert
    the browser against a copy of itself and pass whenever both drifted
    together. That mistake has been made in this repository before.

WHAT THE WORDING MAY AND MAY NOT CLAIM

    `roadmap` says direct submission is INTENDED and names what gates it. It
    deliberately does NOT say the registrations are under way: as at
    24-09-2026 none has been applied for, and the owner's decision (D17) is to
    start them once a CA demo happens. A product that claims a registration it
    does not hold is making a statement about its regulatory standing, which is
    a different kind of wrong from a marketing overstatement.

    Nothing here is a statutory citation, so nothing here is graded. It is
    product copy about a commercial posture — but it is copy a CA reads while
    deciding whether the software can be trusted with a return, which is why it
    lives beside the code rather than in a design file.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class FilingPosture:
    """The four sentences, and the badge word that heads them."""

    #: Short enough for a pill beside a title. Unambiguous to a CA who has
    #: walked in halfway through somebody else's screen.
    badge: str
    #: The banner's own line. States the negative FIRST, because that is the
    #: fact somebody glancing at the screen must not miss.
    headline: str
    #: What the walk-through is, and the two reassurances under it.
    body: str
    #: What happens instead today, and what would have to change. The only
    #: forward-looking sentence, and the one that must not overstate.
    roadmap: str
    #: The long form, for a response payload and for the end of a
    #: walk-through, where there is room for the whole position at once.
    disclaimer: str

    def as_dict(self) -> dict:
        return asdict(self)


POSTURE = FilingPosture(
    badge="DEMO",
    headline="Demonstration — no return is being filed",
    body=(
        "A step-by-step walk-through of the real submission sequence. No data "
        "leaves PracticeSync, no government system is contacted, and no filing "
        "status changes."
    ),
    roadmap=(
        "PracticeSync prepares the return and you submit it on the authority's "
        "own portal. Direct submission from within PracticeSync is planned: it "
        "requires authorisation from GSTN, the Income Tax Department or NIC, "
        "which those bodies grant only to registered providers."
    ),
    disclaimer=(
        "DEMONSTRATION — nothing was transmitted to any government system and "
        "nothing has been filed. No stored status has changed. PracticeSync "
        "prepares this return; submission happens on the authority's own "
        "portal. Direct submission from within PracticeSync is planned and "
        "requires a registration with the relevant authority."
    ),
)


def posture_payload() -> dict:
    """The block every filing-demo response carries, so the browser renders
    the served wording rather than its own.

    A function rather than a module constant that callers mutate: a dict handed
    out by reference is one `.update()` away from a flow rewriting the
    product's position for every other flow in the same process.
    """
    return POSTURE.as_dict()
