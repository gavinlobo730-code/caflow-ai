"""Fetches the firm-wide risk register's inputs. The RULE is `domain/risk/register`.

WHAT THIS REPLACED

    `apps/web/app/risks/page.tsx` made six PostgREST reads of its own and
    derived nine kinds of statutory risk in the browser. `rbac()` never ran on
    any of them and neither did `core.authz`'s assignment scope, so an
    Executive who cannot see a client still read that client's compliance
    calendar, loans and fixed deposits. See the domain module for the two
    statutory figures that were wrong as a consequence.

SCOPE

    "All clients" means the CALLER's clients. `effective_client_ids` returns
    None for a firm-wide role and a concrete set otherwise; an EMPTY set means
    NOTHING, never "no filter" — ACC-17's rule, and getting it the other way
    round is a cross-client read.

READS

    Every one is paged through `core.db_paging.fetch_all`. `compliance_calendar`
    carries a row per obligation per client per period, so a fifty-client book
    passes PostgREST's ~1000-row cap inside a year — and the cap is silent, so
    an unpaged read produces a register that is short by an unknown amount with
    nothing on the screen to say so. That is exactly the defect the browser's
    own Export had before it was paged.

    The calendar is read ONCE and used three times — overdue filings, TDS
    defaults and the recent-activity set — rather than once per question.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reads and reports. It
    # writes nothing, files nothing and reaches no portal.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.risk import register as rule
from services.compliance_engine import advance_tax_due_dates

_logger = logging.getLogger("caflow.risk.register")

#: The advance-tax obligation the calendar records. One spelling, read twice.
_ADVANCE_TAX_TYPE = "ADVANCE_TAX"


def _scoped(query, client_ids: Optional[set[str]]):
    """Narrow a firm-scoped query to the caller's own clients.

    None means no restriction; a non-empty set is an `.in_`. An EMPTY set never
    reaches here — `build_register` short-circuits, because `.in_` over an empty
    list is a query PostgREST answers inconsistently and the intended answer is
    'nothing', not 'everything'."""
    return query if client_ids is None else query.in_("client_id", sorted(client_ids))


def build_register(db, firm_id: str, client_ids: Optional[set[str]] = None) -> dict:
    """The register, as a plain dict for `api_response`."""
    as_at = ist_today()

    if client_ids is not None and not client_ids:
        empty = rule.RiskRegister()
        empty.notes.append(
            "No clients are assigned to you, so there is nothing to report. "
            "This is not the same as a clean register."
        )
        return _to_payload(empty, as_at)

    clients = fetch_all(
        lambda: _scoped_clients(
            db.table("clients").select("id, client_name, gstin, pan").eq("firm_id", firm_id),
            client_ids,
        ),
        label="risk_register.clients",
    )

    # ONE calendar read, three questions. The window is the wider of "overdue"
    # (everything before today) and "recently active" (the last ninety days), so
    # a single fetch answers both; narrowing to only the overdue half would make
    # every client with nothing overdue look inactive.
    since = (as_at - timedelta(days=rule.INACTIVE_AFTER_DAYS)).isoformat()
    calendar = fetch_all(
        lambda: _scoped(
            db.table("compliance_calendar")
            .select("id, client_id, compliance_type, due_date, filing_status")
            .eq("firm_id", firm_id),
            client_ids,
        ),
        label="risk_register.compliance_calendar",
    )

    recent = {
        str(e.get("client_id"))
        for e in calendar
        if (e.get("due_date") or "") >= since
    }

    advance = [e for e in calendar if (e.get("compliance_type") or "") == _ADVANCE_TAX_TYPE]
    tracked = {str(e.get("client_id")) for e in advance}
    filed_keys = {
        f"{e.get('client_id')}|{str(e.get('due_date') or '')[:10]}"
        for e in advance
        if (e.get("filing_status") or "") == "filed"
    }
    # The FY the register is being read in. §208's four dates are derived by
    # `compliance_engine`, never written out here — CLAUDE.md makes that module
    # the single source for every due date in this product.
    fy_end = as_at.year + 1 if as_at.month >= 4 else as_at.year
    installments = advance_tax_due_dates(fy_end)

    # `dsc_records` carries no client_id — a DSC is held by a PERSON and
    # registered to the FIRM — so it is firm-scoped and never client-scoped, and
    # an assignment-scoped caller sees the firm's certificates because they are
    # the firm's. `deleted_at` is migration 351's soft delete.
    dsc_rows = fetch_all(
        lambda: db.table("dsc_records")
        .select("id, holder_name, expiry_date")
        .eq("firm_id", firm_id)
        .is_("deleted_at", "null"),
        label="risk_register.dsc_records",
    )

    loans = fetch_all(
        lambda: _scoped(
            db.table("loans")
            .select("id, client_id, lender_name, loan_type, outstanding_paise")
            .eq("firm_id", firm_id)
            .eq("status", "overdue"),
            client_ids,
        ),
        label="risk_register.loans",
    )

    deposits = fetch_all(
        lambda: _scoped(
            db.table("fixed_deposits")
            .select("id, client_id, bank_name, maturity_date, maturity_amount_paise")
            .eq("firm_id", firm_id)
            .eq("status", "active"),
            client_ids,
        ),
        label="risk_register.fixed_deposits",
    )

    reg = rule.build(
        calendar=calendar,
        clients=clients,
        client_ids_with_recent_entries=recent,
        advance_tax_installments=installments,
        advance_tax_tracked_client_ids=tracked,
        advance_tax_filed_keys=filed_keys,
        dsc_rows=dsc_rows,
        loans=loans,
        deposits=deposits,
        as_at=as_at,
    )
    return _to_payload(reg, as_at)


def _scoped_clients(query, client_ids: Optional[set[str]]):
    """`clients` is keyed on `id`, not `client_id` — the one table where the
    scope column has a different name, which is why `_scoped` is not reused."""
    return query if client_ids is None else query.in_("id", sorted(client_ids))


def _to_payload(reg: rule.RiskRegister, as_at) -> dict:
    return {
        "as_at": as_at.isoformat(),
        "counts": reg.counts,
        "notes": reg.notes,
        "gaps": reg.gaps,
        "rows": [
            {
                "client_id": r.client_id,
                "client_name": r.client_name,
                "risk_type": r.risk_type,
                "description": r.description,
                "severity": r.severity,
                "action": r.action,
                "days_overdue": r.days_overdue,
                "amount_paise": r.amount_paise,
                "date": r.on_date,
            }
            for r in reg.rows
        ],
    }
