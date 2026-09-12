"""
The sales invoice's number, read out of the firm's own settings.

WHAT THIS CLOSES (SALES-12). `invoice_settings` has carried `prefix`,
`include_financial_year`, `sequence_length`, `starting_number` and
`manual_override_allowed` since migration 126, and `/settings/invoice-settings`
has let a CA configure all five. Nothing has ever read them. The invoice number
was typed from scratch on every invoice, and the settings screen quietly
described a series the product did not run.

WHAT IT DOES NOT DO. It does not hand out numbers. `suggest` reads the highest
number the series has reached and returns the next one for the CA to accept,
edit or ignore; the number that is written is the one in the request body, as
it always was. That is the "Automatic (Manual Override)" mode Tally names, and
it is the mode a practice actually runs — a client arriving mid-year with a
series already going, an import, a correction. `domain/gst/invoice_series.py`
carries the statute and the reasoning.

WHY THE SCAN IS BOUNDED, AND WHY IT IS BOUNDED THIS WAY. Reading every invoice
number a client has ever had is proportional to transaction volume, which this
codebase does not allow of anything. So the read is `LIKE '<series head>%'`,
ordered descending, capped at a window — the same shape and the same reasoning
as `services/numbering._SEQUENCE_WINDOW`. One row would do while every number
in the series is zero-padded to one width, because lexicographic order is then
numeric order; a window survives the series having picked up a wider or
unpadded number from an import, where '…/9' would otherwise sort above
'…/0042' and win.

THE FINANCIAL YEAR IS THE DOCUMENT'S, NEVER THE CLOCK'S — SALES-24's rule, and
here it decides which numbers count. It also decides something less obvious: a
series with `include_financial_year` OFF has the same head every year, so the
window sees every year's numbers and the sequence keeps CLIMBING instead of
restarting. That is not a compromise, it is required — the uniqueness index on
(firm_id, client_id, invoice_no) is for the client full stop, not per year, so
a series that restarted at 001 without the year in the number would collide
with its own previous April on the second of two consecutive years.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.ist_clock import ist_fy_label
from domain.gst.invoice_series import (
    SeriesSettings,
    format_number,
    next_sequence,
    sequence_break,
    settings_gap,
    split_number,
)

#: How many numbers to read back before taking the highest. `numbering.py`'s
#: reasoning, and deliberately the same figure — two windows that differ invite
#: the question of why, and there is no answer.
_SEQUENCE_WINDOW = 50


def settings_for(db, firm_id: str) -> SeriesSettings:
    """The firm's numbering settings, or migration 126's own defaults.

    A firm that has never opened Invoice Settings has no row. That is not an
    error and must not become one: the defaults ARE the column defaults, so an
    un-configured firm gets INV/2026-27/001 rather than a blank box.
    """
    if db is None:
        return SeriesSettings.from_row(None)
    try:
        resp = (db.table("invoice_settings").select(
            "prefix, include_financial_year, sequence_length, starting_number, "
            "manual_override_allowed")
            .eq("firm_id", firm_id).limit(1).execute())
        rows = resp.data or []
    except Exception:  # noqa: BLE001
        # A settings read that fails must not stop an invoice being raised. The
        # defaults are legal and the number stays editable, so the worst case is
        # a suggestion the CA overwrites — which is the ordinary case anyway.
        return SeriesSettings.from_row(None)
    return SeriesSettings.from_row(rows[0] if rows else None)


def series_head(settings: SeriesSettings, fy_label: str) -> str:
    """Everything before the digits — `INV/2026-27/`. Two numbers belong to the
    same series when they share it."""
    head, _ = split_number(format_number(settings, fy_label, 1))
    return head


def numbers_in_series(db, firm_id: str, client_id: str, head: str) -> list[str]:
    """The window of numbers already used in this series, highest first.

    Firm- AND client-scoped, because the uniqueness constraint is, and because
    the service-role key bypasses RLS — the `.eq("firm_id", …)` here is the
    primary isolation control, not a convenience.
    """
    if db is None or not head:
        return []
    try:
        resp = (db.table("client_sales_invoices").select("invoice_no")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .is_("deleted_at", "null")
                .like("invoice_no", f"{head}%")
                .order("invoice_no", desc=True)
                .limit(_SEQUENCE_WINDOW).execute())
    except Exception:  # noqa: BLE001
        return []
    return [r.get("invoice_no") or "" for r in (resp.data or [])]


def suggest(db, firm_id: str, client_id: str, invoice_date=None,
            existing: Optional[Iterable[str]] = None) -> dict:
    """What to pre-fill the invoice number box with, and why it might be empty.

    `existing` is for mock mode and for the tests: the router holds
    MOCK_SALES_INVOICES and there is no database to read. Passing it skips the
    query entirely rather than having this module learn about the mock store.
    """
    fy = ist_fy_label(invoice_date)
    settings = settings_for(db, firm_id)
    gap = settings_gap(settings, fy)
    head = series_head(settings, fy)
    if gap:
        # No suggestion, and the reason names the setting to change. Refusing to
        # suggest is the point: a truncated number is a different number, and a
        # number Rule 46(b) forbids is one the IRP and GSTR-1 will both reject.
        return {"suggested_number": None, "series_head": head, "fy_label": fy,
                "next_sequence": None, "manual_override_allowed":
                settings.manual_override_allowed, "gap": gap}
    used = list(existing) if existing is not None else numbers_in_series(
        db, firm_id, client_id, head)
    seq = next_sequence(used, settings, fy)
    return {"suggested_number": format_number(settings, fy, seq),
            "series_head": head, "fy_label": fy, "next_sequence": seq,
            "manual_override_allowed": settings.manual_override_allowed,
            "gap": None}


def gap_notice(db, firm_id: str, client_id: str, invoice_no: str, invoice_date=None,
               existing: Optional[Iterable[str]] = None) -> Optional[str]:
    """Why the number the CA chose is not the next one in its series, or None.

    A WARNING, never a refusal — `domain/gst/invoice_series.sequence_break` says
    why, and the decision it records is the owner's of 2026-09-12. Silent when
    the number belongs to some other series the firm runs on purpose: Rule 46(b)
    allows "one or multiple series", and complaining about the other one trains
    a CA to ignore the warning that matters.
    """
    if not (invoice_no or "").strip():
        return None
    fy = ist_fy_label(invoice_date)
    settings = settings_for(db, firm_id)
    if settings_gap(settings, fy):
        # The firm's own series is unusable, so there is no sequence to be out
        # of. Complaining about the CA's number here would blame them for a
        # settings problem `suggest` has already reported.
        return None
    used = list(existing) if existing is not None else numbers_in_series(
        db, firm_id, client_id, series_head(settings, fy))
    return sequence_break(invoice_no, used, settings, fy)
