"""
Income Tax Computation Workspace — snapshot management, disallowances, deductions, losses.
IT Act 1961 — Sections 40A(3), 43B, 80C–80JJAA, 72 (carry-forward of losses).

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

_logger = logging.getLogger("caflow.tax.workspace")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_SNAPSHOTS: dict[str, dict] = {}
_MOCK_DISALLOWANCES: dict[str, dict] = {}
_MOCK_DEDUCTIONS: dict[str, dict] = {}
_MOCK_LOSSES: dict[str, dict] = {}


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


# Income figures persisted as first-class snapshot columns. The insert used to
# spread the caller's raw `income` dict as top-level columns — any unknown key
# (a typo, a new frontend field) made the whole insert fail with an unknown-
# column error. Only these keys become columns (migration 156 defines them);
# everything else remains available inside computation_json, which stores the
# full computation result anyway.
_INCOME_COLUMNS = frozenset({
    "gross_salary_paise",
    "business_income_paise",
    "other_income_paise",
    "total_disallowances_paise",
    "advance_tax_paid_paise",
    "tds_deducted_paise",
    "taxable_income_paise",
    "tax_liability_paise",
    "net_payable_paise",
    "is_refund",
})


def _income_columns(income: dict) -> dict:
    return {k: v for k, v in (income or {}).items() if k in _INCOME_COLUMNS}


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_computation_snapshot(
    firm_id: str,
    client_id: str,
    financial_year: str,
    assessment_year: str,
    regime: str,
    income: dict,
    computation_result: dict,
    created_by: str,
    notes: str | None = None,
) -> dict:
    """
    Create an immutable versioned computation snapshot.
    Each save increments the version — old snapshots are never mutated.
    """
    if _USE_MOCK:
        existing = [
            s for s in _MOCK_SNAPSHOTS.values()
            if s["firm_id"] == firm_id and s["client_id"] == client_id
            and s["financial_year"] == financial_year
        ]
        version = len(existing) + 1
        snap = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "assessment_year": assessment_year,
            "version": version,
            "regime": regime,
            **income,
            "computation_json": computation_result,
            "status": "draft",
            "notes": notes,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_SNAPSHOTS[snap["id"]] = snap
        return snap

    sb = _supabase()
    # Determine next version
    existing = sb.table("tax_computation_snapshots").select("version").eq(
        "firm_id", firm_id
    ).eq("client_id", client_id).eq("financial_year", financial_year).execute()
    version = (max((r["version"] for r in existing.data), default=0) + 1) if existing.data else 1

    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "assessment_year": assessment_year,
        "version": version,
        "regime": regime,
        **_income_columns(income),
        "computation_json": computation_result,
        "status": "draft",
        "notes": notes,
        "created_by": created_by,
    }
    res = sb.table("tax_computation_snapshots").insert(row).execute()
    return res.data[0] if res.data else row


def list_snapshots(firm_id: str, client_id: str, financial_year: str) -> list[dict]:
    if _USE_MOCK:
        return [
            s for s in _MOCK_SNAPSHOTS.values()
            if s["firm_id"] == firm_id and s["client_id"] == client_id
            and s["financial_year"] == financial_year
        ]
    sb = _supabase()
    res = sb.table("tax_computation_snapshots").select("*").eq(
        "firm_id", firm_id
    ).eq("client_id", client_id).eq("financial_year", financial_year).order(
        "version", desc=True
    ).execute()
    return res.data or []


def get_snapshot(firm_id: str, snapshot_id: str) -> Optional[dict]:
    """Fetch a single snapshot by id, scoped to firm_id. Used by the router
    to resolve the snapshot's client before checking assignment scope."""
    if _USE_MOCK:
        s = _MOCK_SNAPSHOTS.get(snapshot_id)
        return s if s and s.get("firm_id") == firm_id else None
    sb = _supabase()
    res = sb.table("tax_computation_snapshots").select("*").eq(
        "id", snapshot_id
    ).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else None


def review_snapshot(firm_id: str, snapshot_id: str, reviewed_by: str) -> dict:
    """Mark snapshot as reviewed. IT Act — CA must review before filing."""
    if _USE_MOCK:
        if snapshot_id in _MOCK_SNAPSHOTS:
            _MOCK_SNAPSHOTS[snapshot_id]["status"] = "reviewed"
            _MOCK_SNAPSHOTS[snapshot_id]["reviewed_by"] = reviewed_by
            _MOCK_SNAPSHOTS[snapshot_id]["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        return _MOCK_SNAPSHOTS.get(snapshot_id, {})
    sb = _supabase()
    res = sb.table("tax_computation_snapshots").update({
        "status": "reviewed",
        "reviewed_by": reviewed_by,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", snapshot_id).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else {}


# ── Disallowances ─────────────────────────────────────────────────────────────

def create_disallowance(
    firm_id: str,
    client_id: str,
    financial_year: str,
    section: str,
    description: str,
    amount_paise: int,
    created_by: str,
    auto_detected: bool = False,
    evidence_document_id: str | None = None,
    journal_entry_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    IT Act Section 40A(3): cash payments >₹10,000.
    IT Act Section 43B: statutory liabilities (PF/ESI/GST/Bonus) allowed only on actual payment.
    """
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "section": section,
            "description": description,
            "amount_paise": amount_paise,
            "auto_detected": auto_detected,
            "evidence_document_id": evidence_document_id,
            "journal_entry_id": journal_entry_id,
            "notes": notes,
            "status": "pending",
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_DISALLOWANCES[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "section": section,
        "description": description,
        "amount_paise": amount_paise,
        "auto_detected": auto_detected,
        "evidence_document_id": evidence_document_id,
        "journal_entry_id": journal_entry_id,
        "notes": notes,
        "status": "pending",
        "created_by": created_by,
    }
    res = sb.table("tax_disallowances").insert(row).execute()
    return res.data[0] if res.data else row


def list_disallowances(firm_id: str, client_id: str, financial_year: str) -> list[dict]:
    if _USE_MOCK:
        return [
            d for d in _MOCK_DISALLOWANCES.values()
            if d["firm_id"] == firm_id and d["client_id"] == client_id
            and d["financial_year"] == financial_year
        ]
    sb = _supabase()
    res = sb.table("tax_disallowances").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).eq("financial_year", financial_year).order("created_at", desc=True).execute()
    return res.data or []


def get_disallowance(firm_id: str, disallowance_id: str) -> Optional[dict]:
    """Fetch a single disallowance by id, scoped to firm_id. Used by the
    router to resolve the disallowance's client before checking assignment
    scope."""
    if _USE_MOCK:
        d = _MOCK_DISALLOWANCES.get(disallowance_id)
        return d if d and d.get("firm_id") == firm_id else None
    sb = _supabase()
    res = sb.table("tax_disallowances").select("*").eq(
        "id", disallowance_id
    ).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else None


def update_disallowance_status(
    firm_id: str, disallowance_id: str, status: str
) -> dict:
    """Accept or reject a disallowance — requires CA review."""
    if _USE_MOCK:
        if disallowance_id in _MOCK_DISALLOWANCES:
            _MOCK_DISALLOWANCES[disallowance_id]["status"] = status
        return _MOCK_DISALLOWANCES.get(disallowance_id, {})
    sb = _supabase()
    res = sb.table("tax_disallowances").update({"status": status}).eq(
        "id", disallowance_id
    ).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else {}


def auto_detect_40a3(firm_id: str, client_id: str, financial_year: str, created_by: str) -> list[dict]:
    """IT Act §40A(3): surface cash payments for the CA to review.

    §40A(3) disallows expenditure where the payment — or the AGGREGATE of
    payments made to a person in a day — exceeds ₹10,000 otherwise than by
    account-payee cheque, draft or electronic mode.

    WHAT THIS RETURNS, AND WHAT IT DOES NOT DECIDE
        The scan reads the CREDIT side of cash accounts (money leaving; a cash
        payment credits cash) aggregated per day per counterparty account. It
        used to read the debit side, which is money coming IN — so it produced
        the client's cash RECEIPTS as though they were disallowable payments,
        and never surfaced a single real one. See migration 288.

        The ledger carries no party dimension, so "aggregate paid to a person
        in a day" is not derivable; the per-day-per-counterparty-account total
        is the closest honest proxy and is what the amount reflects. Rule 6DD
        exempts a long list of payments (banking companies, government where
        legal tender is required, a producer for agricultural produce, a
        village without banking facilities, and more), and the second proviso
        raises the limit to ₹35,000 for plying, hiring or leasing goods
        carriages — all facts about the payee that no ledger scan can settle.

        So every row created here is a CANDIDATE for CA review, recorded with
        status pending, never a determination. The CA accepts or rejects it.
    """
    LIMIT_PAISE = 1_000_000  # ₹10,000 = 1,000,000 paise
    if _USE_MOCK:
        return []  # No mock ledger data

    sb = _supabase()
    cash_entries = sb.rpc("get_cash_payments_above_threshold", {
        "p_firm_id": firm_id,
        "p_client_id": client_id,
        "p_threshold_paise": LIMIT_PAISE,
    }).execute()

    created = []
    if cash_entries.data:
        for entry in cash_entries.data:
            count = int(entry.get("entry_count") or 1)
            account = entry.get("counterparty_account") or "Unallocated"
            if count > 1:
                # Name the aggregation, so a CA seeing a figure larger than any
                # single voucher knows why it is larger.
                description = (
                    f"Cash payments to {account} on {entry.get('entry_date')} "
                    f"— {count} vouchers aggregated (§40A(3) applies to the "
                    f"day's total paid to one person)"
                )
            else:
                description = (
                    f"Cash payment: {entry.get('narration') or account}"
                )
            d = create_disallowance(
                firm_id=firm_id,
                client_id=client_id,
                financial_year=financial_year,
                section="40A(3)",
                description=description,
                amount_paise=entry.get("amount_paise", 0),
                created_by=created_by,
                auto_detected=True,
                journal_entry_id=entry.get("journal_entry_id"),
            )
            created.append(d)
    return created


# ── Deduction Claims ──────────────────────────────────────────────────────────

def create_deduction_claim(
    firm_id: str,
    client_id: str,
    financial_year: str,
    section: str,
    claimed_amount_paise: int,
    created_by: str,
    sub_head: str | None = None,
    evidence_document_id: str | None = None,
    notes: str | None = None,
) -> dict:
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "section": section,
            "sub_head": sub_head,
            "claimed_amount_paise": claimed_amount_paise,
            "allowed_amount_paise": claimed_amount_paise,
            "evidence_document_id": evidence_document_id,
            "notes": notes,
            "status": "pending",
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_DEDUCTIONS[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "section": section,
        "sub_head": sub_head,
        "claimed_amount_paise": claimed_amount_paise,
        "allowed_amount_paise": claimed_amount_paise,
        "evidence_document_id": evidence_document_id,
        "notes": notes,
        "status": "pending",
        "created_by": created_by,
    }
    res = sb.table("tax_deduction_claims").insert(row).execute()
    return res.data[0] if res.data else row


def list_deduction_claims(firm_id: str, client_id: str, financial_year: str) -> list[dict]:
    if _USE_MOCK:
        return [
            d for d in _MOCK_DEDUCTIONS.values()
            if d["firm_id"] == firm_id and d["client_id"] == client_id
            and d["financial_year"] == financial_year
        ]
    sb = _supabase()
    res = sb.table("tax_deduction_claims").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).eq("financial_year", financial_year).order("section").execute()
    return res.data or []


# ── Brought Forward Losses ────────────────────────────────────────────────────

def create_bf_loss(
    firm_id: str,
    client_id: str,
    assessment_year: str,
    loss_type: str,
    original_amount_paise: int,
    expiry_assessment_year: str,
    created_by: str,
    source_itr_ack: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    IT Act Section 72: business loss carry-forward up to 8 assessment years.
    Section 74: capital loss carry-forward up to 8 assessment years.
    """
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "assessment_year": assessment_year,
            "loss_type": loss_type,
            "original_amount_paise": original_amount_paise,
            "utilized_amount_paise": 0,
            "remaining_amount_paise": original_amount_paise,
            "max_carry_forward_years": 8,
            "expiry_assessment_year": expiry_assessment_year,
            "is_expired": False,
            "source_itr_ack": source_itr_ack,
            "notes": notes,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_LOSSES[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "assessment_year": assessment_year,
        "loss_type": loss_type,
        "original_amount_paise": original_amount_paise,
        "utilized_amount_paise": 0,
        "remaining_amount_paise": original_amount_paise,
        "expiry_assessment_year": expiry_assessment_year,
        "source_itr_ack": source_itr_ack,
        "notes": notes,
        "created_by": created_by,
    }
    res = sb.table("brought_forward_losses").insert(row).execute()
    return res.data[0] if res.data else row


def list_bf_losses(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [
            l for l in _MOCK_LOSSES.values()
            if l["firm_id"] == firm_id and l["client_id"] == client_id
        ]
    sb = _supabase()
    res = sb.table("brought_forward_losses").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).order("assessment_year").execute()
    return res.data or []


def get_bf_loss(firm_id: str, loss_id: str) -> Optional[dict]:
    """Fetch a single brought-forward-loss row by id, scoped to firm_id.
    Used by the router to resolve the loss's client before checking
    assignment scope. Deliberately NOT .single() — see utilize_bf_loss's
    own .single() call a few lines down for the bug this avoids: Supabase's
    real .single() raises (PGRST116) rather than returning no data on zero
    rows, which would turn a routine 404 into an unhandled 500."""
    if _USE_MOCK:
        l = _MOCK_LOSSES.get(loss_id)
        return l if l and l.get("firm_id") == firm_id else None
    sb = _supabase()
    res = sb.table("brought_forward_losses").select("*").eq(
        "id", loss_id
    ).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else None


def utilize_bf_loss(
    firm_id: str, loss_id: str, utilization_paise: int
) -> dict:
    """Record utilization of a brought-forward loss in the current year."""
    if _USE_MOCK:
        if loss_id in _MOCK_LOSSES:
            loss = _MOCK_LOSSES[loss_id]
            new_util = loss["utilized_amount_paise"] + utilization_paise
            if new_util > loss["original_amount_paise"]:
                raise ValueError("Utilization exceeds original loss amount")
            loss["utilized_amount_paise"] = new_util
            loss["remaining_amount_paise"] = loss["original_amount_paise"] - new_util
        return _MOCK_LOSSES.get(loss_id, {})

    sb = _supabase()
    existing = sb.table("brought_forward_losses").select("*").eq("id", loss_id).eq(
        "firm_id", firm_id
    ).single().execute()
    if not existing.data:
        raise ValueError("Loss record not found")
    loss = existing.data
    new_util = loss["utilized_amount_paise"] + utilization_paise
    if new_util > loss["original_amount_paise"]:
        raise ValueError("Utilization exceeds original loss amount")
    res = sb.table("brought_forward_losses").update({
        "utilized_amount_paise": new_util,
        "remaining_amount_paise": loss["original_amount_paise"] - new_util,
    }).eq("id", loss_id).execute()
    return res.data[0] if res.data else {}
