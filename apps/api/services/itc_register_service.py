"""Reclaimable ITC reversals and their reclaims — GSTR-3B 4(B)(2) and 4(D)(1).

WHY IT REGISTERS A JOURNAL RATHER THAN POSTING ONE
    CLAUDE.md: one posting kernel, no alternative paths. Giving credit back is
    a real movement — a credit to GST Input — and that posting already has a
    home: the CA raises it as a manual journal like any other entry.

    What was missing was never a way to POST the reversal. It was a way to say
    WHAT IT WAS. A journal crediting GST Input could be a Rule 37 reversal, a
    cancelled bill, or a plain correction, and the return has to tell them
    apart. So a register row points at an already-posted journal and classifies
    it, and cannot drift from the ledger because it never writes to it.

THE INTEGRITY CHECK, AND WHY IT IS THE POINT
    A register row is a figure on a filed return. If it could claim more than
    the journal behind it actually moved, the return would declare a reversal
    the ledger does not support — and the books-vs-ledger reconciliation would
    be comparing a number against itself, because the same register would feed
    both sides. So every row is checked against the GST Input movement on its
    own journal, and refused if it exceeds it.

WHAT DOES NOT BELONG HERE
    Permanent reversals — Rules 38, 42, 43 and §17(5). Those are Table 4(B)(1),
    they are derived from the documents (a cancelled bill, blocked credit on a
    line), and registering them would double-count.
"""
from __future__ import annotations

import logging
from typing import Optional

_logger = logging.getLogger("caflow.itc_register")

PAGE = 1000

RECLAIMABLE_REASONS = ("rule_37", "rule_37a", "section_16_2b",
                       "section_16_2c", "other")

_HEADS = ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise")


class ITCRegisterError(ValueError):
    """A register row that would misstate a return. Never swallowed."""


def _paginate_all(make_query, key: str = "id") -> list:
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        page = q.order(key).limit(PAGE).execute().data or []
        out.extend(page)
        if len(page) < PAGE:
            break
        cursor = page[-1].get(key)
        if cursor is None:
            break
    return out


def _amounts(src: dict) -> dict:
    return {h: int(src.get(h) or 0) for h in _HEADS}


def _total(a: dict) -> int:
    return sum(a[h] for h in _HEADS)


def _gst_input_credit_on(db, firm_id: str, client_id: str, journal_entry_id: str) -> int:
    """Net CREDIT to GST Input on one posted journal, in paise.

    Credit to an asset is the direction that gives input tax back, so a
    reversal shows here as a positive number. A journal that debits GST Input
    (taking credit) nets negative and can never support a reversal row.

    Resolved the same way _gl_gst_movements resolves it — by system key, then
    by name and account_type — because a chart built by coa_seed_service leaves
    system_account_key NULL and the live firm that broke the GSTR-3B
    reconciliation was exactly that shape.
    """
    coa = (db.table("chart_of_accounts")
           .select("id, client_id, system_account_key, account_name, account_type")
           .eq("firm_id", firm_id)
           .or_(f"client_id.eq.{client_id},client_id.is.null")
           .execute().data) or []
    in_ids = {c["id"] for c in coa if c.get("system_account_key") == "gst_input"}
    if not in_ids:
        in_ids = {c["id"] for c in coa
                  if c.get("account_type") == "Asset"
                  and "gst input" in (c.get("account_name") or "").lower()}
    if not in_ids:
        raise ITCRegisterError(
            "No GST Input account found for this client, so a reversal cannot "
            "be checked against the ledger. Set up the chart of accounts first.")

    lines = (db.table("journal_lines")
             .select("account_id, debit_paise, credit_paise")
             .eq("journal_entry_id", journal_entry_id).execute().data) or []
    return sum(int(l.get("credit_paise") or 0) - int(l.get("debit_paise") or 0)
               for l in lines if l.get("account_id") in in_ids)


def _posted_journal(db, firm_id: str, client_id: str, journal_entry_id: str) -> dict:
    rows = (db.table("journal_entries")
            .select("id, firm_id, client_id, is_posted, entry_date, reference_no")
            .eq("id", journal_entry_id).eq("firm_id", firm_id).limit(1)
            .execute().data) or []
    if not rows:
        raise ITCRegisterError("Journal entry not found for this firm.")
    je = rows[0]
    if je.get("client_id") != client_id:
        raise ITCRegisterError("That journal belongs to a different client.")
    if not je.get("is_posted"):
        raise ITCRegisterError(
            "A draft journal cannot support a return figure — post it first.")
    return je


def _existing_for_journal(db, firm_id: str, journal_entry_id: str) -> Optional[dict]:
    rows = (db.table("itc_reversal_register").select("id")
            .eq("firm_id", firm_id).eq("journal_entry_id", journal_entry_id)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def record_reversal(db, firm_id: str, client_id: str, *, journal_entry_id: str,
                    period: str, reason_code: str, amounts: dict,
                    purchase_bill_id: Optional[str] = None,
                    notes: Optional[str] = None,
                    actor_id: Optional[str] = None) -> dict:
    """Classify a posted journal as a Table 4(B)(2) reversal.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This records a decision the CA
    # has already made and posted; it files nothing.
    """
    if reason_code not in RECLAIMABLE_REASONS:
        raise ITCRegisterError(
            f"{reason_code!r} is not a reclaimable ground. Rules 38, 42, 43 and "
            "section 17(5) are permanent reversals — Table 4(B)(1) — and are "
            "taken from the documents, not registered here.")
    amt = _amounts(amounts)
    if _total(amt) <= 0:
        raise ITCRegisterError("A reversal of nothing is not a declaration.")

    _posted_journal(db, firm_id, client_id, journal_entry_id)
    if _existing_for_journal(db, firm_id, journal_entry_id):
        raise ITCRegisterError(
            "That journal is already registered. Declaring one posting twice "
            "would double the reversal on the return.")

    moved = _gst_input_credit_on(db, firm_id, client_id, journal_entry_id)
    if _total(amt) > moved:
        raise ITCRegisterError(
            f"The journal gives back {moved} paise of input tax; this row "
            f"declares {_total(amt)}. A return figure the ledger does not "
            "support is the one thing this register exists to prevent.")

    # The dict is written INLINE, with every key a string literal, so
    # tests/_backend_query_parser can read the column names and check them
    # against the real schema. Building it in a variable and passing
    # .insert(row) hides all of them — the parser sees a Name — and these are
    # the columns that carry figures onto a filed return.
    return (db.table("itc_reversal_register").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "journal_entry_id": journal_entry_id,
        "kind": "reversal",
        "reason_code": reason_code,
        "period": period,
        # Explicit, not left to the column default: the CHECK constraint ties
        # kind to this column, so a reversal states that it releases nothing
        # rather than relying on NULL arriving by omission.
        "reverses_id": None,
        "purchase_bill_id": purchase_bill_id,
        "notes": notes,
        "created_by": actor_id,
        "igst_paise": amt["igst_paise"],
        "cgst_paise": amt["cgst_paise"],
        "sgst_paise": amt["sgst_paise"],
        "cess_paise": amt["cess_paise"],
    }).execute().data or [{}])[0]


def outstanding_for(db, firm_id: str, reversal_id: str) -> dict:
    """What of one reversal has not yet been reclaimed, per head."""
    rows = (db.table("itc_reversal_register").select("*")
            .eq("firm_id", firm_id).eq("id", reversal_id).limit(1)
            .execute().data) or []
    if not rows:
        raise ITCRegisterError("Reversal not found.")
    rev = rows[0]
    if rev.get("kind") != "reversal":
        raise ITCRegisterError("That row is a reclaim, not a reversal.")
    claimed = (db.table("itc_reversal_register").select("*")
               .eq("firm_id", firm_id).eq("reverses_id", reversal_id)
               .execute().data) or []
    out = _amounts(rev)
    for c in claimed:
        for h in _HEADS:
            out[h] -= int(c.get(h) or 0)
    return out


def record_reclaim(db, firm_id: str, client_id: str, *, journal_entry_id: str,
                   period: str, reverses_id: str, amounts: dict,
                   notes: Optional[str] = None,
                   actor_id: Optional[str] = None) -> dict:
    """Classify a posted journal as a Table 4(D)(1) reclaim of an earlier 4(B)(2).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    amt = _amounts(amounts)
    if _total(amt) <= 0:
        raise ITCRegisterError("A reclaim of nothing is not a declaration.")

    _posted_journal(db, firm_id, client_id, journal_entry_id)
    if _existing_for_journal(db, firm_id, journal_entry_id):
        raise ITCRegisterError("That journal is already registered.")

    left = outstanding_for(db, firm_id, reverses_id)
    over = [h for h in _HEADS if amt[h] > left[h]]
    if over:
        raise ITCRegisterError(
            "This reclaims more than was reversed: "
            + ", ".join(f"{h} {amt[h]} > {left[h]}" for h in over)
            + ". Credit can only come back once.")

    # A reclaim TAKES credit again, so its journal debits GST Input — the
    # opposite sign to a reversal.
    moved = -_gst_input_credit_on(db, firm_id, client_id, journal_entry_id)
    if _total(amt) > moved:
        raise ITCRegisterError(
            f"The journal takes back {moved} paise of input tax; this row "
            f"declares {_total(amt)}.")

    return (db.table("itc_reversal_register").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "journal_entry_id": journal_entry_id,
        "kind": "reclaim",
        "reason_code": "other",
        "period": period,
        "reverses_id": reverses_id,
        "notes": notes,
        "created_by": actor_id,
        "igst_paise": amt["igst_paise"],
        "cgst_paise": amt["cgst_paise"],
        "sgst_paise": amt["sgst_paise"],
        "cess_paise": amt["cess_paise"],
    }).execute().data or [{}])[0]


def for_period(db, firm_id: str, client_id: str, period: str) -> dict:
    """The register rows a GSTR-3B for `period` has to declare."""
    rows = _paginate_all(lambda: db.table("itc_reversal_register").select("*")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("period", period))
    reversals = [r for r in rows if r.get("kind") == "reversal"]
    reclaims = [r for r in rows if r.get("kind") == "reclaim"]

    def _sum(rs):
        return {h: sum(int(r.get(h) or 0) for r in rs) for h in _HEADS}

    return {
        "period": period,
        "reversals": reversals,          # -> Table 4(B)(2)
        "reclaims": reclaims,            # -> Table 4(D)(1)
        "reversal_totals": _sum(reversals),
        "reclaim_totals": _sum(reclaims),
        "ca_review_required": True,
    }
