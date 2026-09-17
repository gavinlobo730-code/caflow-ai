"""WHICH COLUMN HOLDS THE FIRM'S OWN GSTIN, AND WHY THERE ARE TWO.

WHAT WAS WRONG

`public.firms` carries BOTH `gst_number` (migration 003, with a shape CHECK) and
`gstin` (added by migration 014, given the same CHECK by 112/316). Nothing has
ever synced them, and the two sides of the product picked different ones:

  * BOTH screens wrote `gst_number`, straight over PostgREST — the Settings firm
    profile and the onboarding wizard's update step;
  * every backend reader read `gstin` — `invoice_pdf_service._firm_party` puts it
    on the CA's own fee invoice as the SUPPLIER's GSTIN (CGST Rule 46(a)), the
    same module's fallback decides CGST+SGST against IGST from
    `_state_code(firm["gstin"])`, `routers/onboarding` reports
    `gstin_configured` from it, and `routers/practice` provisions the
    firm-as-internal-client with it.

So a CA who typed their GSTIN into Settings got an invoice with no supplier
GSTIN on it and, because `_state_code(None)` is None, the whole tax on a LOCAL
supply landed in IGST. `POST /api/onboarding/firm` writes `gstin` correctly —
but the onboarding SCREEN does not call it for the update step, so which path a
firm came through decided whether its own GSTIN was readable at all.

MEASURED, because the severity turns on it: on 17-09-2026 production held 2
firms with BOTH columns NULL on both. So this was latent, not live — it became
live the moment anybody typed a GSTIN into Settings. The same shape as
`capital_wip` and the FX revaluation: built, reachable, and structurally nil.

THE RULE

    `gstin` is the column. `gst_number` is read as a fallback and never written.

One writer — `PATCH /api/firms/profile`, where `domain/gst/gstin.problem_with`
runs the CHECK DIGIT neither column's CHECK constraint can — and one reader,
below. A row written before this change still answers, because `gstin_of` falls
back; a row written after it needs no fallback.

WHY NOT A MIGRATION. Back-filling `gstin` from `gst_number` and dropping one
column is the honest end state and is an OWNER decision: merging a migration to
`main` applies it to the production database with no review step in between
(CLAUDE.md, "Migrations"). The fallback costs one `or` and keeps every existing
row readable until that decision is taken.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

#: The column the product writes and reads. Everything else is history.
CANONICAL_COLUMN = "gstin"

#: Migration 003's column. Still carries the value for any firm whose profile
#: was saved before 17-09-2026, so it is READ and never written.
LEGACY_COLUMN = "gst_number"

#: What a `select()` must name for `gstin_of` to be able to answer. A narrow
#: projection that omits one of these makes the fallback a silent no-op — the
#: same trap `domain/accounting/opening_documents` records for `is_opening`.
COLUMNS = (CANONICAL_COLUMN, LEGACY_COLUMN)


def gstin_of(firm: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The firm's own GSTIN, from whichever column carries it.

    `None` where the firm has not recorded one — which is a real state, not an
    error: a practice below the §22 threshold has no registration to record, and
    `invoice_pdf_service` already prints a fee invoice without one.
    """
    if not firm:
        return None
    for column in COLUMNS:
        value = firm.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def writes(gstin: Optional[str]) -> dict:
    """The column(s) a firm-profile save sets for a GSTIN.

    Only the canonical one. Writing both would make `gst_number` a cache with
    two writers, which is the shape CLAUDE.md records going wrong on
    `clients.gstin` and on the retired supplier table (PUR-16); leaving it alone makes it inert
    history that `gstin_of` can still read.
    """
    return {CANONICAL_COLUMN: (gstin or None)}
