"""Product Bible Chapter 16 — the seven dimensions, their weights and the bands.

MOVED OUT OF `routers/health.py` RATHER THAN COPIED (25-09-2026), because
`domain/health/overrides.py` has to recompute the composite after a CA replaces
a dimension's score, and a domain module importing a router is the wrong
direction — the reasoning `domain/fixed_assets/schedule_ii.py` records for
Schedule II Part C. The router re-exports every name here, so nothing that
imported `routers.health.DIMENSION_WEIGHTS_BP` had to change.

Integer arithmetic only. Weights are basis points (1% = 100 bp) so the
composite is `sum(score * weight_bp) // 10000` with no float anywhere.
"""
from __future__ import annotations

#: The seven dimensions and their weights, summing to 10000 bp = 100%.
DIMENSION_WEIGHTS_BP: dict[str, int] = {
    "compliance_health":     2500,   # 25%
    "accounting_quality":    2000,   # 20%
    "work_progress":         1500,   # 15%
    "document_health":       1500,   # 15%
    "ai_risk_signals":       1000,   # 10%
    "open_notices":          1000,   # 10%
    "client_responsiveness":  500,   #  5%
}

#: The dimension names, as a set, for anything that has to ask "is this one of
#: them" — `overrides.py` does, and a list comparison there would drift.
DIMENSIONS: frozenset[str] = frozenset(DIMENSION_WEIGHTS_BP)

#: What a CA reads for each dimension — ONE NAME PER DIMENSION, EVERYWHERE.
#:
#: There were four vocabularies for these seven (sweep-client-misc-04,
#: sweep-health-hub-06). The firm-level detail page said "Compliance Health …
#: Client Responsiveness"; the client tab's cards said "Compliance, Accounting,
#: Documents, Responsiveness, Relationship Risk, Financial Risk, Engagement
#: Health" — the LEGACY flat columns, three of which name nothing in this model
#: (`relationship_risk_score` is a constant 100, `financial_risk_score` is
#: open_notices under another name); the Add Override picker on that same tab
#: offered the model's keys under a third set of words; and the Overview card a
#: fourth. So a CA wanting to override the "Financial Risk" card they could see
#: found no such entry in the picker.
#:
#: The browser renders `apps/web/lib/health/vocabulary.ts`, which a test pins
#: to THIS dict from the Python side — the Schedule III caption lesson: a guard
#: written in apps/web would assert the browser against a copy of itself.
DIMENSION_LABELS: dict[str, str] = {
    "compliance_health":     "Compliance Health",
    "accounting_quality":    "Accounting Quality",
    "work_progress":         "Work Progress",
    "document_health":       "Document Health",
    "ai_risk_signals":       "AI Risk Signals",
    "open_notices":          "Open Notices",
    "client_responsiveness": "Client Responsiveness",
}

#: The five bands, highest floor first. `grade` walks this table rather than
#: restating it, so the table IS the rule — which is what lets the browser's
#: fallback (`gradeForScore`) be pinned to it row for row (sweep-client-
#: purchases-05: the header badge said "Fair" at 73 on its own 80/60/40 ladder
#: while the Health page, reading this function's answer, said "Good").
GRADE_BANDS: tuple[tuple[int, str], ...] = (
    (80, "Healthy"),
    (65, "Good"),
    (50, "Needs Attention"),
    (35, "At Risk"),
    (0,  "Critical"),
)


def grade(score: int) -> str:
    """Derive the band label from an integer score. No float arithmetic.

    A score below every floor (negative, which nothing should produce) is
    Critical — the bottom band, never an absent answer."""
    for floor, band in GRADE_BANDS:
        if score >= floor:
            return band
    return GRADE_BANDS[-1][1]


def weighted_score(dimension_scores: dict[str, int]) -> int:
    """The composite from the seven dimensions.

    A dimension the caller did not supply counts as 100 — inherited from the
    original and kept deliberately, because a dimension whose own fetch failed
    must not drag the score down and look like a finding about the client.
    """
    total_bp = 0
    for dim, weight_bp in DIMENSION_WEIGHTS_BP.items():
        total_bp += dimension_scores.get(dim, 100) * weight_bp
    return total_bp // 10000
