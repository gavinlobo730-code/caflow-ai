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


def grade(score: int) -> str:
    """Derive the band label from an integer score. No float arithmetic."""
    if score >= 80:
        return "Healthy"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Needs Attention"
    if score >= 35:
        return "At Risk"
    return "Critical"


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
