"""
DPDP domain — what the Digital Personal Data Protection Act obliges, and what
another law obliges instead.

`retention` is the written retention position: one entry per data category,
naming the statute, whose duty it is, and the date the duty lapses.
"""
from .retention import (
    CATEGORIES,
    RULES,
    Anchor,
    Category,
    ErasureDecision,
    Rule,
    erasure_decision,
    position,
    retained_until,
)

__all__ = [
    "CATEGORIES",
    "RULES",
    "Anchor",
    "Category",
    "ErasureDecision",
    "Rule",
    "erasure_decision",
    "position",
    "retained_until",
]
