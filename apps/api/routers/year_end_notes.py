"""
Year End Notes to Accounts router — Phase 6.
Manages Notes to Financial Statements.
Auto-generates standard notes from GL data; supports manual placeholder notes.
Notes can be locked individually (immutable after locking).

Reference: Companies Act 2013, Schedule III — Notes to Accounts.
All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.observability import capture_soft_failure
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event
# M2 audit finding: every endpoint below resolved its engagement by firm_id
# alone (_get_engagement_db, live mode) or not checked its client at all
# (_mock_engagement, mock mode); list_notes, get_note and lock_note didn't
# resolve the engagement at all, applying only an inline firm_id filter on
# year_end_notes in live mode and no tenancy check whatsoever in mock mode.
# Delegates to year_end.py's own _assert_engagement_scope rather than a
# fifth copy of the same check.
from routers.year_end import _assert_engagement_scope

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-notes"])

# Note types — auto-generated (at least partly computed from real data) vs
# manual placeholder. task #240 fix: gst_tds moved out of _AUTO_NOTE_TYPES --
# there is no FY-level GST/TDS payable aggregation function anywhere in the
# codebase (gst_return_service's GL-movement helpers are period-scoped, one
# GSTR-3B return at a time, not a financial year), so unlike fixed_assets/
# share_capital/loans it genuinely cannot be computed here. It now gets the
# same honest CA-input placeholder as related_party/contingent_liabilities
# instead of a plausible-looking fabricated number.
# accounting_policies is "auto" in the same limited sense as the others:
# part of it is read off the books (which depreciation methods the register
# actually uses, whether stock is tracked), and the rest is named as the
# CA's to complete. Schedule III, Division I, General Instructions require
# the notes to disclose significant accounting policies, and there was no
# such note at all.
_AUTO_NOTE_TYPES   = {"accounting_policies", "fixed_assets", "share_capital", "loans"}
_MANUAL_NOTE_TYPES = {"related_party", "contingent_liabilities", "gst_tds"}
_ALL_NOTE_TYPES    = _AUTO_NOTE_TYPES | _MANUAL_NOTE_TYPES

# ── Mock store ────────────────────────────────────────────────────────────────
# engagement_id → list of note dicts
_MOCK_NOTES: dict[str, list[dict]] = {}


# ── Request models ────────────────────────────────────────────────────────────

class NoteUpdateIn(BaseModel):
    title:   Optional[str] = None
    content: Optional[str] = None
    note_data: Optional[dict] = None


# ── Real-data computation for auto note types ─────────────────────────────────
# task #240 fix: these figures used to be hardcoded literal constants (e.g.
# gross_block_paise=80_000_00) regardless of the actual client/FY — a
# "Generate Notes" click produced numbers with no connection to the client's
# books at all, which could have ended up in a filed Balance Sheet. Below,
# each figure is either computed from real data or explicitly left blank
# with requires_ca_review=True (the same honest-placeholder pattern already
# used for related_party/contingent_liabilities) — never a plausible-looking
# fabricated number.

def _compute_fixed_assets_note_data(db, firm_id: str, client_id: str, fy_end: Optional[str]) -> dict:
    """Real Fixed Assets figures for the FY, from the fixed assets register.
    Depreciation charge uses the SAME fixed-annual-charge-on-opening-WDV
    logic as routers.fixed_assets (task #232's rounding fix)."""
    if db is None:
        return {
            "gross_block_paise": 0, "accumulated_dep_paise": 0,
            "net_block_paise": 0, "depreciation_charge_paise": 0,
            "note_type": "fixed_assets", "is_auto_generated": True,
            "requires_ca_review": True,
            "review_note": "Fixed assets register unavailable — figures require manual entry.",
        }
    from routers.fixed_assets import _annual_depreciation_for_period
    rows = (
        db.table("fixed_assets").select("*")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("is_disposed", False)
        .execute().data or []
    )
    gross_block     = sum(int(a.get("purchase_cost_paise") or 0) for a in rows)
    accumulated_dep = sum(int(a.get("accumulated_depreciation_paise") or 0) for a in rows)
    period = (fy_end or "")[:7]  # "YYYY-MM" — March of the FY-end year
    dep_charge = 0
    if period:
        for a in rows:
            charge, _fy, _opening = _annual_depreciation_for_period(a, period)
            dep_charge += charge
    return {
        "gross_block_paise":        gross_block,
        "accumulated_dep_paise":    accumulated_dep,
        "net_block_paise":          gross_block - accumulated_dep,
        "depreciation_charge_paise": dep_charge,
        "note_type": "fixed_assets",
        "is_auto_generated": True,
    }


def _compute_accounting_policies_data(
    db, firm_id: str, client_id: str, fy_end: Optional[str],
) -> dict:
    """What the books themselves say about the entity's accounting policies.

    Schedule III, Division I, General Instructions require the notes to
    disclose the significant accounting policies. Most of them are the CA's
    JUDGEMENTS — revenue recognition, employee benefits, provisions, taxes on
    income — and the system has no basis whatever for asserting them.

    Two it genuinely knows, because they are facts about how these books were
    kept rather than opinions about them:

      * DEPRECIATION — every row in fixed_assets carries its own
        depreciation_method (SL or WDV, models/accounting.DepreciationMethod),
        so the methods actually in use are read off the register rather than
        assumed. The Fixed Assets note used to assert "Written Down Value
        method" as flat text for every client, which is simply false for any
        client whose assets are on straight line.
      * INVENTORY — domain/inventory_service implements moving-average
        costing, by construction and not as a configurable option, so a
        stock-tracked client's valuation basis is a property of the engine.

    Everything else is left explicitly blank for the CA, following the pattern
    task #240 established for gst_tds: an honest placeholder, never a
    plausible-looking fabrication. A policies note is the WORST place to
    invent text, because it reads as boilerplate — nobody re-reads it, and it
    ends up attached to a filed AOC-4 asserting a policy the client does not
    follow.
    """
    # Judgements no ledger can answer. Named individually so the CA is
    # prompted for each rather than handed one blank box.
    ca_input_required = [
        "Basis of preparation and compliance with applicable accounting standards",
        "Revenue recognition",
        "Employee benefits",
        "Provisions, contingent liabilities and contingent assets",
        "Taxes on income, including deferred tax",
        "Borrowing costs",
        "Impairment of assets",
    ]
    blank = {
        "entity_type": None,
        "depreciation_methods": [],
        "has_fixed_assets": False,
        "inventory_is_stock_tracked": False,
        "inventory_valuation_basis": None,
        "has_foreign_currency_transactions": False,
        "ca_input_required": ca_input_required,
        "note_type": "accounting_policies",
        "is_auto_generated": True,
        # Always true, whatever was derived. The derived policies are a
        # starting point the CA confirms, not a disclosure the software makes
        # on their behalf.
        "requires_ca_review": True,
    }
    if db is None:
        blank["review_note"] = (
            "Books unavailable — every accounting policy requires the CA's input."
        )
        return blank

    data = dict(blank)

    # Each read is written out in full rather than through a helper taking the
    # table name as a parameter. A dynamic table name is invisible to
    # tests/test_backend_columns_exist_pg, which checks every backend query
    # against the real schema — and CLAUDE.md's whole point about renaming a
    # column is that the breakage is silent. Four explicit queries the checker
    # can read beat one tidy helper it cannot.
    #
    # Each is guarded on its own: a table this deployment lacks, or an
    # unreachable one, must not fail note generation. The note is still useful
    # with fewer derived policies, and every policy it cannot derive is named
    # for the CA anyway.
    try:
        entity = (db.table("clients").select("entity_type")
                  .eq("firm_id", firm_id).eq("id", client_id)
                  .execute().data or [])
        if entity:
            data["entity_type"] = entity[0].get("entity_type")
    except Exception as exc:
        capture_soft_failure(exc, operation="accounting_policies.entity_type",
                             firm_id=firm_id, client_id=client_id)

    try:
        assets = (db.table("fixed_assets").select("depreciation_method")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("is_disposed", False)
                  .execute().data or [])
    except Exception as exc:
        capture_soft_failure(exc, operation="accounting_policies.depreciation_methods",
                             firm_id=firm_id, client_id=client_id)
        assets = []
    if assets:
        data["has_fixed_assets"] = True
        data["depreciation_methods"] = sorted(
            {a.get("depreciation_method") for a in assets if a.get("depreciation_method")}
        )

    try:
        catalogue = (db.table("service_catalogue").select("kind")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .execute().data or [])
    except Exception as exc:
        capture_soft_failure(exc, operation="accounting_policies.inventory_basis",
                             firm_id=firm_id, client_id=client_id)
        catalogue = []
    if any(i.get("kind") == "good" for i in catalogue):
        data["inventory_is_stock_tracked"] = True
        data["inventory_valuation_basis"] = "moving average"

    # Multi-currency is dormant for most clients (migration 147 defaults
    # txn_currency to INR), so this is normally False and the policy is
    # omitted rather than stated as "nil".
    #
    # txn_currency is on journal_LINES, not journal_entries — migration 147
    # adds it to the line because the rate is frozen per leg. Reading it off
    # the entry compiles, returns nothing, and reports "no foreign currency"
    # for every client in the practice; the backend column checker caught
    # that, which is the whole reason these queries are written out where it
    # can see them.
    #
    # Filtered and limited server-side rather than fetched and scanned: this
    # answers a yes/no question, and CLAUDE.md's reporting rule is that what
    # crosses the wire is proportional to the ANSWER, not to the ledger.
    # txn_currency is NOT NULL DEFAULT 'INR' (migration 147), so neq is safe
    # here — no row can carry a NULL for the comparison to swallow.
    try:
        foreign = (db.table("journal_lines")
                   .select("txn_currency, journal_entries!inner(client_id, firm_id)")
                   .eq("journal_entries.firm_id", firm_id)
                   .eq("journal_entries.client_id", client_id)
                   .neq("txn_currency", "INR")
                   .limit(1)
                   .execute().data or [])
    except Exception as exc:
        capture_soft_failure(exc, operation="accounting_policies.foreign_currency",
                             firm_id=firm_id, client_id=client_id)
        foreign = []
    if foreign:
        data["has_foreign_currency_transactions"] = True
        data["ca_input_required"] = ca_input_required + [
            "Foreign currency transactions and translation"
        ]
    return data


def _accounting_policies_text(data: dict) -> str:
    """The note as a CA would read it: what the books show, then what is
    still needed. Derived policies are stated as derived; the rest are named
    as outstanding rather than filled with boilerplate."""
    _METHOD_NAMES = {"SL": "Straight Line", "WDV": "Written Down Value"}
    lines: list[str] = []

    if data.get("has_fixed_assets"):
        methods = [_METHOD_NAMES.get(m, m) for m in data.get("depreciation_methods") or []]
        if len(methods) == 1:
            lines.append(
                f"Depreciation — fixed assets are stated at cost less accumulated "
                f"depreciation. Depreciation is provided on the {methods[0]} method, "
                f"read from the fixed assets register."
            )
        elif len(methods) > 1:
            # Worth saying plainly: mixed methods within one register are
            # legitimate but a CA should be able to see it at a glance.
            lines.append(
                f"Depreciation — fixed assets are stated at cost less accumulated "
                f"depreciation. The register uses more than one method "
                f"({', '.join(methods)}); the basis for each class requires the "
                f"CA's confirmation."
            )
        else:
            lines.append(
                "Depreciation — the fixed assets register records no depreciation "
                "method, so the basis requires the CA's input."
            )

    if data.get("inventory_is_stock_tracked"):
        lines.append(
            "Inventories — valued on the moving average cost basis, which is how "
            "stock movements are costed in these books."
        )

    outstanding = data.get("ca_input_required") or []
    if outstanding:
        lines.append(
            "The following policies require the CA's input before these "
            "statements are issued, and are deliberately left blank rather "
            "than pre-filled: " + "; ".join(outstanding) + "."
        )
    return " ".join(lines)


def _compute_gl_schedule_balances(
    db, firm_id: str, client_id: str, fy_start: Optional[str], fy_end: Optional[str],
) -> Optional[dict]:
    """Share Capital / Borrowings balances straight from the General Ledger,
    via the SAME account_group_mappings-driven engine the Balance Sheet
    itself uses (services.year_end_financial_service) — single source of
    truth, never a fabricated placeholder. Returns None if unavailable (e.g.
    the books don't balance yet), so callers fall back to an honest
    CA-review note rather than a wrong number."""
    if db is None or not fy_start or not fy_end:
        return None
    from services.year_end_financial_service import generate_financial_statements
    try:
        result = generate_financial_statements(db, client_id, firm_id, fy_start, fy_end)
    except Exception:
        return None
    return result.get("balance_sheet", {}).get("equity_and_liabilities", {})


# ── Note content generators ───────────────────────────────────────────────────

def _generate_note_content(note_type: str, eng: dict, computed: dict) -> dict:
    """
    Generate note content for auto note types.
    All monetary values in integer paise. Never float.
    """
    fy = eng.get("financial_year", "")
    gl = computed.get("gl_balances")

    policies = computed.get("accounting_policies") or {}

    _note_templates: dict[str, dict] = {
        "accounting_policies": {
            "title":   "Significant Accounting Policies",
            "content": _accounting_policies_text(policies),
            "note_data": policies,
        },
        "fixed_assets": {
            "title":   "Fixed Assets (Schedule III, Companies Act 2013)",
            # The depreciation basis is NOT restated here. This used to read
            # "Depreciation is provided on Written Down Value method" for every
            # client, as flat text — false for any client whose register is on
            # straight line, and every asset row carries its own
            # depreciation_method. The basis now belongs to the Significant
            # Accounting Policies note, derived from the register, and stating
            # it twice is how the two come to disagree.
            "content": (
                f"Fixed assets are stated at cost less accumulated depreciation. "
                f"The depreciation basis is disclosed in the Significant Accounting "
                f"Policies note. Useful lives follow Companies Act 2013, Schedule II. "
                f"Financial year: {fy}."
            ),
            "note_data": computed["fixed_assets"],
        },
        "share_capital": {
            "title":   "Share Capital",
            "content": (
                f"Details of authorised, issued, subscribed and paid-up share capital "
                f"as at 31st March of FY {fy}. "
                f"[Reference: Companies Act 2013, §64]"
            ),
            "note_data": {
                "authorised_paise":  None,   # Memorandum/Articles fact — not a GL balance
                "issued_paise":      None,   # Memorandum/Articles fact — not a GL balance
                "subscribed_paise":  None,   # Memorandum/Articles fact — not a GL balance
                "paid_up_paise":     (gl or {}).get("share_capital", 0) if gl is not None else None,
                "note_type":         "share_capital",
                "is_auto_generated": True,
                "requires_ca_review": True,
                "review_note": (
                    "Paid-up capital is computed from the General Ledger (share_capital "
                    "schedule line). Authorised, issued and subscribed capital are "
                    "Memorandum/Articles of Association facts, not GL balances — CA must fill these in."
                    if gl is not None else
                    "General Ledger balance unavailable — all figures require manual entry."
                ),
            },
        },
        "loans": {
            "title":   "Long-term and Short-term Borrowings",
            "content": (
                f"Secured and unsecured loans as at 31st March of FY {fy}. "
                f"Secured loans are against hypothecation of assets."
            ),
            "note_data": {
                "long_term_total_paise":  (gl or {}).get("long_term_borrowings", 0) if gl is not None else None,
                "short_term_total_paise": (gl or {}).get("short_term_borrowings", 0) if gl is not None else None,
                "long_term_secured_paise":    None,
                "long_term_unsecured_paise":  None,
                "short_term_secured_paise":   None,
                "short_term_unsecured_paise": None,
                "note_type": "loans",
                "is_auto_generated": True,
                "requires_ca_review": True,
                "review_note": (
                    "Totals are computed from the General Ledger (long_term_borrowings / "
                    "short_term_borrowings schedule lines). The secured/unsecured split is "
                    "not tracked in the Chart of Accounts — CA must classify each loan."
                    if gl is not None else
                    "General Ledger balance unavailable — figures require manual entry."
                ),
            },
        },
        "gst_tds": {
            "title":   "Statutory Dues (GST & TDS)",
            "content": (
                f"GST and TDS dues as at 31st March of FY {fy}. "
                f"PLACEHOLDER — CA to fill in from GSTR-3B and TDS return records for the FY. "
                f"[CGST Act 2017 §49; IT Act 1961 §194C/194J]"
            ),
            "note_data": {
                "gst_payable_paise": None,
                "tds_payable_paise": None,
                "input_itc_paise":   None,
                "note_type": "gst_tds",
                "is_auto_generated": False,
                "requires_ca_review": True,
                "review_note": (
                    "No financial-year-level GST/TDS payable aggregation exists yet — "
                    "CA must fill this in from GSTR-3B and TDS return records for the FY."
                ),
            },
        },
        "related_party": {
            "title":   "Related Party Transactions",
            "content": (
                "PLACEHOLDER — CA to fill in related party transactions. "
                "[Companies Act 2013, §188; AS-18 / Ind AS 24]"
            ),
            "note_data": {
                "transactions": [],
                "note_type": "related_party",
                "is_auto_generated": False,
                "requires_ca_review": True,
            },
        },
        "contingent_liabilities": {
            "title":   "Contingent Liabilities and Capital Commitments",
            "content": (
                "PLACEHOLDER — CA to disclose contingent liabilities and capital commitments. "
                "[AS-29; Companies Act 2013, Schedule III]"
            ),
            "note_data": {
                "items": [],
                "note_type": "contingent_liabilities",
                "is_auto_generated": False,
                "requires_ca_review": True,
            },
        },
    }

    return _note_templates.get(note_type, {
        "title":     note_type.replace("_", " ").title(),
        "content":   f"Auto-generated note for {note_type}.",
        "note_data": {"note_type": note_type, "is_auto_generated": True},
    })


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{engagement_id}/notes")
def list_notes(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    # M2 audit finding: never resolved the engagement at all — live mode
    # applied only an inline firm_id filter on year_end_notes, mock mode
    # had no tenancy check whatsoever.
    _assert_engagement_scope(current_user, engagement_id)

    if _USE_MOCK:
        return api_response(True, _MOCK_NOTES.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("year_end_notes")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .order("sequence_no")
        .execute()
        .data
    )
    return api_response(True, rows)


@router.post("/{engagement_id}/notes/generate")
def generate_notes(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """
    Auto-generate standard Notes to Accounts from GL data.
    Creates auto notes for: fixed_assets, share_capital, loans, gst_tds.
    Creates manual placeholders for: related_party, contingent_liabilities.
    """
    now = datetime.now(timezone.utc).isoformat()

    # M2 audit finding: engagement resolved by firm_id alone (live) or not
    # checked at all (mock) — never checked the caller's assignment to its
    # client.
    eng = _assert_engagement_scope(current_user, engagement_id)
    if eng.get("status") == "locked":
        raise HTTPException(status_code=403, detail="Engagement is locked")

    if _USE_MOCK:
        db = None
    else:
        from core.supabase_client import get_supabase
        db = get_supabase()

    computed = {
        "accounting_policies": _compute_accounting_policies_data(
            db, current_user["firm_id"], eng.get("client_id", ""), eng.get("fy_end"),
        ),
        "fixed_assets": _compute_fixed_assets_note_data(
            db, current_user["firm_id"], eng.get("client_id", ""), eng.get("fy_end"),
        ),
        "gl_balances": _compute_gl_schedule_balances(
            db, current_user["firm_id"], eng.get("client_id", ""),
            eng.get("fy_start"), eng.get("fy_end"),
        ),
    }

    # Significant Accounting Policies comes FIRST. Schedule III presents it
    # ahead of the notes that depend on it — a reader has to know the
    # depreciation basis before the Fixed Assets figures mean anything.
    note_types_ordered = [
        "accounting_policies",
        "fixed_assets", "share_capital", "loans", "gst_tds",
        "related_party", "contingent_liabilities",
    ]

    generated_notes = []
    for idx, note_type in enumerate(note_types_ordered, start=1):
        content = _generate_note_content(note_type, eng, computed)
        note = {
            "id":            str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "firm_id":       current_user["firm_id"],
            "note_type":     note_type,
            # `note_number` deliberately omitted: it belongs to the never-applied
            # notes_to_accounts schema (migration 067). The table this actually
            # writes to, year_end_notes, orders by sequence_no and has no
            # note_number column — sending it makes PostgREST reject the insert.
            "sequence_no":   idx,
            # Numbered from POSITION, not from a literal in the template.
            # Every title used to carry its own hardcoded "Note 1 —", so
            # inserting a note ahead of them left "Note 1 — Fixed Assets"
            # sitting at sequence 2 and the note references in the statements
            # pointing at the wrong note.
            "title":         f"Note {idx} — {content['title']}",
            "content":       content["content"],
            "note_data":     content["note_data"],
            "is_locked":     False,
            "is_auto_generated": note_type in _AUTO_NOTE_TYPES,
            "created_by":    current_user.get("auth_user_id"),
            "created_at":    now,
            "updated_at":    now,
        }
        generated_notes.append(note)

    if _USE_MOCK:
        _MOCK_NOTES[engagement_id] = generated_notes
        return api_response(True, generated_notes)

    # Regenerate the unlocked notes only.
    #
    # This used to be an unfiltered DELETE over the engagement. A partner locks
    # a note after reviewing its wording — the update endpoint refuses to touch
    # a locked note for exactly that reason — and then anyone with
    # year_end:write clicking "Generate Notes" replaced it with the empty
    # placeholder, with no warning and no record of what it had said. The lock
    # has to mean the same thing on both paths or it means nothing.
    locked = (db.table("year_end_notes")
              .select("note_type")
              .eq("engagement_id", engagement_id)
              .eq("is_locked", True)
              .execute().data) or []
    locked_types = {row.get("note_type") for row in locked}

    db.table("year_end_notes").delete().eq(
        "engagement_id", engagement_id).eq("is_locked", False).execute()
    to_insert = [n for n in generated_notes if n["note_type"] not in locked_types]
    result = db.table("year_end_notes").insert(to_insert).execute() if to_insert else None
    inserted = result.data if result is not None else []

    log_event(
        current_user["firm_id"], "year_end_notes", engagement_id, "generate",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"count": len(inserted), "preserved_locked": len(locked_types)},
    )
    return api_response(True, inserted)


@router.get("/{engagement_id}/notes/{note_id}")
def get_note(
    engagement_id: str,
    note_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    # M2 audit finding: never resolved the engagement at all.
    _assert_engagement_scope(current_user, engagement_id)

    if _USE_MOCK:
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    return api_response(True, row)


@router.patch("/{engagement_id}/notes/{note_id}")
def update_note(
    engagement_id: str,
    note_id: str,
    data: NoteUpdateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    now = datetime.now(timezone.utc).isoformat()

    # M2 audit finding: engagement resolved by firm_id alone (live) or not
    # checked at all (mock) — never checked the caller's assignment to its
    # client.
    eng = _assert_engagement_scope(current_user, engagement_id)
    if eng.get("status") == "locked":
        raise HTTPException(status_code=403, detail="Engagement is locked")

    if _USE_MOCK:
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note.get("is_locked"):
            raise HTTPException(status_code=403, detail="Note is locked and cannot be modified")
        updates = data.model_dump(exclude_none=True)
        note.update(updates)
        note["updated_at"] = now
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()

    existing = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Note not found")
    if existing.get("is_locked"):
        raise HTTPException(status_code=403, detail="Note is locked and cannot be modified")

    updates = data.model_dump(exclude_none=True)
    updates["updated_at"] = now

    updated = (
        db.table("year_end_notes")
        .update(updates)
        .eq("id", note_id)
        .execute()
        .data[0]
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/notes/{note_id}/lock")
def lock_note(
    engagement_id: str,
    note_id: str,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """Lock a note — immutable after locking. Requires Manager or Partner."""
    now = datetime.now(timezone.utc).isoformat()

    # M2 audit finding: never resolved the engagement at all.
    _assert_engagement_scope(current_user, engagement_id)

    if _USE_MOCK:
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note.get("is_locked"):
            raise HTTPException(status_code=409, detail="Note is already locked")
        note["is_locked"]  = True
        note["locked_by"]  = current_user.get("auth_user_id")
        note["locked_at"]  = now
        note["updated_at"] = now
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()

    existing = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Note not found")
    if existing.get("is_locked"):
        raise HTTPException(status_code=409, detail="Note is already locked")

    updated = (
        db.table("year_end_notes")
        .update({
            "is_locked":  True,
            "locked_by":  current_user.get("auth_user_id"),
            "locked_at":  now,
            "updated_at": now,
        })
        .eq("id", note_id)
        .execute()
        .data[0]
    )
    log_event(
        current_user["firm_id"], "year_end_note", note_id, "lock",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"is_locked": True},
    )
    return api_response(True, updated)
