"""
Tally Migration System — Import Tally XML data into CAflow AI.
Supports: Masters, Ledger Accounts, Opening Balances, Customers, Vendors,
          Journal Entries, Trial Balance.

Workflow: Upload → Parse → Mapping → Validation → Preview → Import

Dry-run mode: validates without importing. Rollback: deletes created records.
Never imports directly without preview step.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    import xml.etree.ElementTree as ET
except ImportError:
    ET = None  # type: ignore

_logger = logging.getLogger("caflow.tally.migration")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_JOBS: dict[str, dict] = {}
_MOCK_ITEMS: dict[str, list] = {}


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


# PostgREST caps a response at ~1000 rows and says nothing about it. Every read
# of tally_migration_items below goes through _all_items for that reason — see
# its docstring for what the unpaged versions were doing.
_ITEM_PAGE = 1000

# Rows per insert when saving parsed items. A single insert of a whole Tally
# export is one enormous request body; chunking keeps each round trip bounded
# and gives a failure a much smaller blast radius.
_INSERT_CHUNK = 500

# How often a running import writes its progress back to the job row. Small
# enough that the UI moves, large enough that the heartbeat is a rounding error
# against the work itself.
_PROGRESS_EVERY = 25


def _all_items(sb, job_id: str, firm_id: str, columns: str = "*",
               status: str | None = None) -> list[dict]:
    """EVERY item on a job, via keyset paging over `id`.

    THE BUG THIS EXISTS TO FIX
        All three reads of tally_migration_items were a plain
        `.select(...).eq("job_id", ...).execute()` with no paging, so PostgREST's
        ~1000-row cap truncated each of them in silence. This is audit C6, the
        same class that truncated the ledger for reporting and the column list
        for the schema guard — the third and fourth time it has appeared in this
        codebase.

        On this path it was not a slow report, it was wrong books:

          * execute_import      imported the first 1000 items and wrote
                                status='completed'. Item 1001 onward were never
                                touched, and nothing anywhere said so — the job
                                row claimed success.
          * rollback_migration  deleted the first 1000 created records, so a
                                rollback could not fully undo an import it was
                                the designated remedy for.
          * get_migration_preview  showed the CA the first 1000 items to review
                                and approve, presenting a partial list as whole.

        A CA importing several years of a real practice is well past 1000 items,
        so all three would have fired on first contact with real data.

    Keyset rather than OFFSET for the reason documented at length in
    domain/reporting/sources.py::_fetch_all: OFFSET re-scans every preceding row
    on each page. End of data is a SHORT page, never an assumed row count.
    """
    out: list[dict] = []
    cursor: str | None = None
    # `id` must be in the projection or the next cursor cannot be read.
    select = columns if columns == "*" or "id" in columns else f"id, {columns}"

    while True:
        q = (sb.table("tally_migration_items").select(select)
             .eq("job_id", job_id).eq("firm_id", firm_id))
        if status is not None:
            q = q.eq("status", status)
        if cursor is not None:
            q = q.gt("id", cursor)
        page = q.order("id").limit(_ITEM_PAGE).execute().data or []
        out.extend(page)
        if len(page) < _ITEM_PAGE:
            return out
        cursor = page[-1]["id"]


# ── Job Management ────────────────────────────────────────────────────────────

def create_migration_job(
    firm_id: str,
    name: str,
    source_file_name: str,
    target_financial_year: str,
    created_by: str,
    import_types: list[str] | None = None,
    description: str | None = None,
    source_file_size_bytes: int | None = None,
    client_id: str | None = None,
) -> dict:
    if _USE_MOCK:
        job = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "name": name,
            "description": description,
            "source_file_name": source_file_name,
            "source_file_size_bytes": source_file_size_bytes,
            "import_types": import_types or ["ledgers", "journals"],
            "target_financial_year": target_financial_year,
            "status": "uploaded",
            "total_items": 0,
            "imported_items": 0,
            "failed_items": 0,
            "validation_errors": [],
            "import_audit_log": [],
            "is_dry_run": True,
            "dry_run_report": None,
            "rollback_data": None,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_JOBS[job["id"]] = job
        _MOCK_ITEMS[job["id"]] = []
        return job

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "name": name,
        "description": description,
        "source_file_name": source_file_name,
        "source_file_size_bytes": source_file_size_bytes,
        "import_types": import_types or ["ledgers", "journals"],
        "target_financial_year": target_financial_year,
        "is_dry_run": True,
        "created_by": created_by,
    }
    res = sb.table("tally_migration_jobs").insert(row).execute()
    return res.data[0] if res.data else row


def list_migration_jobs(firm_id: str) -> list[dict]:
    if _USE_MOCK:
        return [j for j in _MOCK_JOBS.values() if j["firm_id"] == firm_id]
    sb = _supabase()
    res = sb.table("tally_migration_jobs").select("*").eq("firm_id", firm_id).order(
        "created_at", desc=True
    ).execute()
    return res.data or []


def get_migration_job(firm_id: str, job_id: str) -> dict | None:
    if _USE_MOCK:
        j = _MOCK_JOBS.get(job_id)
        return j if j and j["firm_id"] == firm_id else None
    sb = _supabase()
    res = sb.table("tally_migration_jobs").select("*").eq("id", job_id).eq(
        "firm_id", firm_id
    ).single().execute()
    return res.data


# ── Tally XML Parsing ─────────────────────────────────────────────────────────

def parse_tally_xml(xml_content: str) -> dict[str, list[dict]]:
    """
    Parse Tally XML export (TALLYMESSAGE or ENVELOPE format).
    Returns categorized items: ledgers, journals, customers, vendors.
    """
    result: dict[str, list[dict]] = {
        "ledgers": [],
        "journals": [],
        "customers": [],
        "vendors": [],
        "opening_balances": [],
        "masters": [],
    }

    if not ET:
        _logger.error("xml.etree.ElementTree not available")
        return result

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        _logger.error("Tally XML parse error: %s", e)
        return result

    # Parse LEDGER entries
    for ledger in root.iter("LEDGER"):
        name = ledger.get("NAME") or (ledger.find("NAME") and ledger.find("NAME").text) or ""  # type: ignore
        group = ledger.findtext("PARENT") or ""
        opening_balance = _parse_tally_amount(ledger.findtext("OPENINGBALANCE") or "0")
        address = ledger.findtext("ADDRESS") or ""
        email = ledger.findtext("EMAIL") or ""
        pan = ledger.findtext("INCOMETAXNUMBER") or ""
        gstin = ledger.findtext("GSTREGISTRATIONNUMBER") or ""

        ledger_data = {
            "tally_id": name,
            "name": name,
            "group": group,
            "opening_balance_paise": opening_balance,
            "address": address,
            "email": email,
            "pan": pan,
            "gstin": gstin,
        }

        # Classify as customer/vendor/ledger
        group_lower = group.lower()
        if "sundry debtors" in group_lower or "trade receivable" in group_lower:
            result["customers"].append(ledger_data)
        elif "sundry creditors" in group_lower or "trade payable" in group_lower:
            result["vendors"].append(ledger_data)
        else:
            result["ledgers"].append(ledger_data)
            if opening_balance != 0:
                result["opening_balances"].append({
                    "ledger_name": name,
                    "amount_paise": opening_balance,
                    "group": group,
                })

    # Parse VOUCHER entries (journal entries)
    for voucher in root.iter("VOUCHER"):
        vtype = voucher.findtext("VOUCHERTYPENAME") or ""
        date_str = voucher.findtext("DATE") or ""
        narration = voucher.findtext("NARRATION") or ""
        vno = voucher.findtext("VOUCHERNUMBER") or ""

        lines = []
        for entry in voucher.iter("ALLLEDGERENTRIES.LIST"):
            ledger_name = entry.findtext("LEDGERNAME") or ""
            amount = _parse_tally_amount(entry.findtext("AMOUNT") or "0")
            is_debit = amount < 0  # Tally uses negative for debit
            lines.append({
                "ledger_name": ledger_name,
                "amount_paise": abs(amount),
                "is_debit": is_debit,
            })

        if lines:
            result["journals"].append({
                "tally_id": vno,
                "voucher_type": vtype,
                "date": _parse_tally_date(date_str),
                "narration": narration,
                "voucher_number": vno,
                "lines": lines,
            })

    return result


def _parse_tally_amount(s: str) -> int:
    """Convert Tally amount string to paise. Tally uses space-separated format."""
    cleaned = re.sub(r"[^\d.\-]", "", s.strip().replace(",", ""))
    if not cleaned:
        return 0
    return round(float(cleaned) * 100)


def _parse_tally_date(s: str) -> str | None:
    """Parse Tally date YYYYMMDD to YYYY-MM-DD."""
    s = s.strip()
    if re.match(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


# ── Validation ────────────────────────────────────────────────────────────────

def validate_migration_data(
    parsed: dict[str, list[dict]],
    import_types: list[str],
) -> tuple[list[dict], list[str]]:
    """
    Validate parsed Tally data before import.
    Returns (items, errors).
    """
    items: list[dict] = []
    errors: list[str] = []

    if "ledgers" in import_types or "masters" in import_types:
        for ledger in parsed.get("ledgers", []):
            item = {
                "item_type": "ledger",
                "tally_id": ledger.get("tally_id"),
                "tally_data": ledger,
                "status": "validated",
                "validation_errors": [],
            }
            if not ledger.get("name"):
                item["status"] = "failed"
                item["validation_errors"].append("Ledger name is required")
                errors.append(f"Ledger missing name: {ledger}")
            items.append(item)

    if "customers" in import_types:
        for cust in parsed.get("customers", []):
            gstin = cust.get("gstin", "")
            item = {
                "item_type": "customer",
                "tally_id": cust.get("tally_id"),
                "tally_data": cust,
                "status": "validated",
                "validation_errors": [],
            }
            if gstin and not re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", gstin):
                item["validation_errors"].append(f"Invalid GSTIN format: {gstin}")
            items.append(item)

    if "vendors" in import_types:
        for vendor in parsed.get("vendors", []):
            item = {
                "item_type": "vendor",
                "tally_id": vendor.get("tally_id"),
                "tally_data": vendor,
                "status": "validated",
                "validation_errors": [],
            }
            items.append(item)

    if "journals" in import_types:
        for j in parsed.get("journals", []):
            lines = j.get("lines", [])
            total_debit = sum(l["amount_paise"] for l in lines if l["is_debit"])
            total_credit = sum(l["amount_paise"] for l in lines if not l["is_debit"])
            item = {
                "item_type": "journal",
                "tally_id": j.get("tally_id"),
                "tally_data": j,
                "status": "validated",
                "validation_errors": [],
            }
            if abs(total_debit - total_credit) > 1:  # 1 paise tolerance
                item["status"] = "failed"
                item["validation_errors"].append(
                    f"Journal not balanced: Dr={total_debit} Cr={total_credit}"
                )
                errors.append(f"Unbalanced journal {j.get('tally_id')}")
            items.append(item)

    if "opening_balances" in import_types:
        for ob in parsed.get("opening_balances", []):
            items.append({
                "item_type": "opening_balance",
                "tally_id": ob.get("ledger_name"),
                "tally_data": ob,
                "status": "validated",
                "validation_errors": [],
            })

    return items, errors


def save_migration_items(
    firm_id: str,
    job_id: str,
    items: list[dict],
) -> None:
    if _USE_MOCK:
        rows = [{"id": str(uuid4()), "firm_id": firm_id, "job_id": job_id, **item}
                for item in items]
        _MOCK_ITEMS[job_id] = rows
        if job_id in _MOCK_JOBS:
            _MOCK_JOBS[job_id]["total_items"] = len(items)
        return

    sb = _supabase()
    rows = [{"firm_id": firm_id, "job_id": job_id, **item} for item in items]
    # Chunked: one insert carrying a whole Tally export is a single very large
    # request body, and a failure anywhere in it loses the lot.
    for i in range(0, len(rows), _INSERT_CHUNK):
        sb.table("tally_migration_items").insert(rows[i:i + _INSERT_CHUNK]).execute()
    sb.table("tally_migration_jobs").update({
        "total_items": len(items),
        "status": "previewing",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).eq("firm_id", firm_id).execute()


def get_migration_preview(firm_id: str, job_id: str) -> dict:
    """Return preview of all items to be imported, grouped by type."""
    if _USE_MOCK:
        items = _MOCK_ITEMS.get(job_id, [])
    else:
        sb = _supabase()
        # Paged: the CA approves what this returns, so a truncated preview is
        # consent given to a list that was never shown in full.
        items = _all_items(sb, job_id, firm_id)

    by_type: dict[str, list] = {}
    errors_count = 0
    for item in items:
        t = item["item_type"]
        by_type.setdefault(t, []).append(item)
        if item.get("status") == "failed":
            errors_count += 1

    return {
        "total": len(items),
        "by_type": {k: {"count": len(v), "items": v[:10]} for k, v in by_type.items()},
        "error_count": errors_count,
        "can_import": errors_count == 0,
    }


def execute_import(
    firm_id: str,
    job_id: str,
    actor_id: str,
    is_dry_run: bool = True,
) -> dict:
    """
    Execute the import. If is_dry_run=True, validates but does not write.
    Returns import report.
    """
    if _USE_MOCK:
        job = _MOCK_JOBS.get(job_id, {})
        items = _MOCK_ITEMS.get(job_id, [])
        total = len(items)
        report = {
            "total": total,
            "imported": total if not is_dry_run else 0,
            "failed": 0,
            "skipped": 0,
            "is_dry_run": is_dry_run,
            "message": "Dry run completed" if is_dry_run else "Import completed",
        }
        job["status"] = "completed" if not is_dry_run else "previewing"
        job["imported_items"] = report["imported"]
        job["dry_run_report"] = report if is_dry_run else None
        return report

    sb = _supabase()
    # Firm-scoped job fetch: gives the importer the job's target client_id
    # (customers/vendors need it) and doubles as the ownership check.
    job_res = sb.table("tally_migration_jobs").select("id, client_id").eq(
        "id", job_id
    ).eq("firm_id", firm_id).execute().data
    if not job_res:
        raise ValueError("Migration job not found")
    job_client_id = job_res[0].get("client_id")

    items = _all_items(sb, job_id, firm_id)

    imported = 0
    failed = 0
    skipped = 0
    audit_log = []

    if not is_dry_run:
        # Mark the job running BEFORE the first write, so a caller polling the
        # job can tell "in progress" from "never started" — and so a crash
        # leaves evidence rather than a job stuck looking pending.
        sb.table("tally_migration_jobs").update({
            "status": "importing",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).eq("firm_id", firm_id).execute()

    for processed, item in enumerate(items, start=1):
        if item["status"] == "failed":
            failed += 1
            continue

        if is_dry_run:
            skipped += 1
            continue

        # ALREADY DONE — this is what makes the import resumable. Each item is
        # marked the instant it lands, so a run killed by a deploy, an OOM or a
        # free-tier spin-down can simply be started again: the finished items
        # are skipped and the remainder proceeds. Without this, re-running after
        # a partial import would duplicate every record it had already created,
        # which on a CA's books is worse than the original failure.
        if item["status"] == "imported":
            imported += 1
            continue

        try:
            created_id, created_type = _import_single_item(firm_id, job_client_id, item, sb)
            # created_record_type is what rollback_migration deletes from —
            # it was never written before, making every rollback a silent
            # no-op (R2.2 investigation finding).
            sb.table("tally_migration_items").update({
                "status": "imported",
                "created_record_id": created_id,
                "created_record_type": created_type,
            }).eq("id", item["id"]).eq("firm_id", firm_id).execute()
            imported += 1
            audit_log.append({"item_id": item["id"], "status": "imported", "record_id": created_id})
        except Exception as e:
            sb.table("tally_migration_items").update({
                "status": "failed",
                "error_message": str(e),
            }).eq("id", item["id"]).eq("firm_id", firm_id).execute()
            failed += 1
            audit_log.append({"item_id": item["id"], "status": "failed", "error": str(e)})

        # Heartbeat. A long import is otherwise indistinguishable from a hung
        # one — the CA watching the screen sees the same thing either way, and
        # so does anyone debugging it. Every _PROGRESS_EVERY items, not every
        # item, so progress reporting cannot itself double the round trips.
        if not is_dry_run and processed % _PROGRESS_EVERY == 0:
            try:
                sb.table("tally_migration_jobs").update({
                    "imported_items": imported,
                    "failed_items": failed,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", job_id).eq("firm_id", firm_id).execute()
            except Exception as e:  # progress is not the job — never fail on it
                _logger.warning("Import progress update failed (job %s): %s", job_id, e)

    final_status = "completed" if not is_dry_run else "previewing"
    sb.table("tally_migration_jobs").update({
        "status": final_status,
        "imported_items": imported,
        "failed_items": failed,
        "import_audit_log": audit_log,
        "is_dry_run": is_dry_run,
        "completed_at": datetime.now(timezone.utc).isoformat() if not is_dry_run else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).eq("firm_id", firm_id).execute()

    return {
        "total": len(items),
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "is_dry_run": is_dry_run,
        "audit_log": audit_log,
    }


def run_import_detached(firm_id: str, job_id: str, actor_id: str) -> None:
    """execute_import for a caller that is no longer waiting — the background
    entry point.

    WHY THE IMPORT CANNOT RUN IN THE REQUEST
        It used to. gunicorn runs with `--timeout 120`, and the import does two
        round trips per item (insert the record, mark the item). At the ~50 ms
        Singapore↔Mumbai round trip that is roughly 100 ms an item, so the
        worker was killed somewhere past ~1,200 items — mid-write, with no
        report and no explanation. A CA importing years of a real practice is
        well past that on the first attempt, which made this the single most
        likely thing to fail on first contact with a paying customer.

        It also held the ONLY worker for its whole duration, so the app was
        unresponsive to everyone else while one person imported.

    WHICH DATABASE ROLE THIS RUNS AS
        `service_role`, deliberately. A background task outlives the request, so
        the caller's JWT is gone by the time this runs (core.supabase_client's
        request token is reset when the response completes) and get_supabase()
        falls back to the service client. That is the correct role here — there
        is no user session to act on behalf of — and it is safe for THIS work
        specifically: customers, vendors, tally_migration_jobs and
        tally_migration_items all grant service_role full access. Many tables do
        NOT (they are granted to `authenticated` only), so a future background
        job touching anything else must check before assuming.

        Authorization is not weakened by this. The endpoint has already run
        rbac("accounting", "approve") and _assert_job_scope, and every query
        below is still filtered by firm_id.

    FAILURE
        Any exception marks the job `failed` with the reason, because the
        alternative is a job that sits at `importing` forever and tells nobody
        why. The items already imported keep their own `imported` status, so
        re-running resumes rather than duplicating.
    """
    try:
        execute_import(firm_id=firm_id, job_id=job_id, actor_id=actor_id,
                       is_dry_run=False)
    except Exception as e:
        _logger.exception("Detached import failed (job %s)", job_id)
        try:
            _supabase().table("tally_migration_jobs").update({
                "status": "failed",
                "import_audit_log": {"error": str(e)},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).eq("firm_id", firm_id).execute()
        except Exception:
            _logger.exception("Could not even mark job %s failed", job_id)


def _import_single_item(
    firm_id: str, client_id: str | None, item: dict, sb: Any
) -> tuple[str | None, str | None]:
    """Import a single Tally item into CAflow tables. Returns
    (created_record_id, created_record_table) — the table name is persisted on
    the item so rollback knows where to delete from.

    customers/vendors are PER-CLIENT masters (client_id NOT NULL, migration
    049), so those item types require the job to target a client — refused
    with a clear error instead of an opaque NOT NULL violation."""
    item_type = item["item_type"]
    data = item.get("tally_data", {})

    if item_type in ("customer", "vendor") and not client_id:
        raise ValueError(
            f"Cannot import {item_type}s: this migration job has no target "
            "client. Create the job with a client_id to import customer/"
            "vendor masters."
        )

    if item_type in ("customer",):
        res = sb.table("customers").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "name": data.get("name", ""),
            "gstin": data.get("gstin"),
            "pan": data.get("pan"),
            "email": data.get("email"),
            "address": data.get("address"),
        }).execute()
        return (res.data[0]["id"] if res.data else None), "customers"

    if item_type in ("vendor",):
        res = sb.table("vendors").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "name": data.get("name", ""),
            "gstin": data.get("gstin"),
            "pan": data.get("pan"),
            "email": data.get("email"),
            "address": data.get("address"),
        }).execute()
        return (res.data[0]["id"] if res.data else None), "vendors"

    return None, None  # Other types require more complex mapping


def rollback_migration(firm_id: str, job_id: str, actor_id: str) -> dict:
    """Delete all records created by this import job."""
    if _USE_MOCK:
        job = _MOCK_JOBS.get(job_id, {})
        job["status"] = "rolled_back"
        job["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        job["rolled_back_by"] = actor_id
        _MOCK_ITEMS[job_id] = []
        return {"rolled_back": True, "message": "Rollback completed"}

    sb = _supabase()
    # Ownership check FIRST: without it, any authenticated user who guessed a
    # job id could delete another firm's imported customers/vendors and flip
    # their job to rolled_back (R2.2 investigation finding — cross-tenant
    # destructive action; RLS is the backstop, this is the primary guard).
    job = sb.table("tally_migration_jobs").select("id").eq("id", job_id).eq(
        "firm_id", firm_id
    ).execute().data
    if not job:
        raise ValueError("Migration job not found")

    # Get all created records — firm-scoped and PAGED, matching every other item
    # read. Unpaged, a rollback stopped after 1000 deletions and reported done,
    # leaving the remainder of a bad import in the books permanently.
    created = _all_items(
        sb, job_id, firm_id,
        columns="created_record_id, created_record_type", status="imported",
    )

    # Deleting only from the tables the importer writes — never a
    # caller-influenced name (defence in depth around the dynamic .table()).
    _ROLLBACK_TABLES = {"customers", "vendors"}

    rolled_back = 0
    for item in created:
        rec_id = item.get("created_record_id")
        rec_type = item.get("created_record_type")
        if rec_id and rec_type in _ROLLBACK_TABLES:
            try:
                sb.table(rec_type).delete().eq("id", rec_id).eq("firm_id", firm_id).execute()
                rolled_back += 1
            except Exception as e:
                _logger.warning("Rollback failed for %s %s: %s", rec_type, rec_id, e)

    sb.table("tally_migration_jobs").update({
        "status": "rolled_back",
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "rolled_back_by": actor_id,
    }).eq("id", job_id).eq("firm_id", firm_id).execute()

    return {"rolled_back": True, "records_deleted": rolled_back}
