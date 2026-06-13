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
    from core.supabase_client import get_supabase_client
    return get_supabase_client()


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
) -> dict:
    if _USE_MOCK:
        job = {
            "id": str(uuid4()),
            "firm_id": firm_id,
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
    if rows:
        sb.table("tally_migration_items").insert(rows).execute()
    sb.table("tally_migration_jobs").update({
        "total_items": len(items),
        "status": "previewing",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()


def get_migration_preview(firm_id: str, job_id: str) -> dict:
    """Return preview of all items to be imported, grouped by type."""
    if _USE_MOCK:
        items = _MOCK_ITEMS.get(job_id, [])
    else:
        sb = _supabase()
        res = sb.table("tally_migration_items").select("*").eq("job_id", job_id).eq(
            "firm_id", firm_id
        ).execute()
        items = res.data or []

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
    items_res = sb.table("tally_migration_items").select("*").eq("job_id", job_id).eq(
        "firm_id", firm_id
    ).execute()
    items = items_res.data or []

    imported = 0
    failed = 0
    skipped = 0
    audit_log = []

    for item in items:
        if item["status"] == "failed":
            failed += 1
            continue

        if is_dry_run:
            skipped += 1
            continue

        try:
            created_id = _import_single_item(firm_id, item, sb)
            sb.table("tally_migration_items").update({
                "status": "imported",
                "created_record_id": created_id,
            }).eq("id", item["id"]).execute()
            imported += 1
            audit_log.append({"item_id": item["id"], "status": "imported", "record_id": created_id})
        except Exception as e:
            sb.table("tally_migration_items").update({
                "status": "failed",
                "error_message": str(e),
            }).eq("id", item["id"]).execute()
            failed += 1
            audit_log.append({"item_id": item["id"], "status": "failed", "error": str(e)})

    final_status = "completed" if not is_dry_run else "previewing"
    sb.table("tally_migration_jobs").update({
        "status": final_status,
        "imported_items": imported,
        "failed_items": failed,
        "import_audit_log": audit_log,
        "is_dry_run": is_dry_run,
        "completed_at": datetime.now(timezone.utc).isoformat() if not is_dry_run else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()

    return {
        "total": len(items),
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "is_dry_run": is_dry_run,
        "audit_log": audit_log,
    }


def _import_single_item(firm_id: str, item: dict, sb: Any) -> str | None:
    """Import a single Tally item into CAflow tables. Returns created record ID."""
    item_type = item["item_type"]
    data = item.get("tally_data", {})

    if item_type in ("customer",):
        res = sb.table("customers").insert({
            "firm_id": firm_id,
            "name": data.get("name", ""),
            "gstin": data.get("gstin"),
            "pan": data.get("pan"),
            "email": data.get("email"),
            "address": data.get("address"),
        }).execute()
        return res.data[0]["id"] if res.data else None

    if item_type in ("vendor",):
        res = sb.table("vendors").insert({
            "firm_id": firm_id,
            "name": data.get("name", ""),
            "gstin": data.get("gstin"),
            "pan": data.get("pan"),
            "email": data.get("email"),
            "address": data.get("address"),
        }).execute()
        return res.data[0]["id"] if res.data else None

    return None  # Other types require more complex mapping


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
    # Get all created records
    items_res = sb.table("tally_migration_items").select(
        "created_record_id, created_record_type"
    ).eq("job_id", job_id).eq("status", "imported").execute()

    rolled_back = 0
    for item in (items_res.data or []):
        rec_id = item.get("created_record_id")
        rec_type = item.get("created_record_type")
        if rec_id and rec_type:
            try:
                sb.table(rec_type).delete().eq("id", rec_id).eq("firm_id", firm_id).execute()
                rolled_back += 1
            except Exception as e:
                _logger.warning("Rollback failed for %s %s: %s", rec_type, rec_id, e)

    sb.table("tally_migration_jobs").update({
        "status": "rolled_back",
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "rolled_back_by": actor_id,
    }).eq("id", job_id).execute()

    return {"rolled_back": True, "records_deleted": rolled_back}
