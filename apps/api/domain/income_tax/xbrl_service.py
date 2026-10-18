"""
XBRL Generation Engine — Schedule III → MCA taxonomy mapping.
Companies Act 2013, Schedule III — Balance Sheet and P&L format.
The taxonomy versions, their tags and namespaces and whether each has been checked are in
`domain/income_tax/xbrl_taxonomy` (POST-A-118); this module reads them.

# CA REVIEW REQUIRED — DO NOT AUTO-FILE XBRL to MCA portal
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring
import xml.etree.ElementTree as ET

from domain.money_text import rupees_paise
from domain.income_tax.xbrl_taxonomy import (
    DEFAULT_TAXONOMY, TAXONOMY_BY_VERSION, taxonomy_for, taxonomy_notice,
)
from core import db_provider

_logger = logging.getLogger("caflow.xbrl")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_PACKAGES: dict[str, dict] = {}

# Kept as a name for callers and tests that import it; the table itself is the registry's (domain/income_tax/xbrl_taxonomy).
DEFAULT_MAPPINGS = TAXONOMY_BY_VERSION[DEFAULT_TAXONOMY].mappings


_supabase = db_provider.request_db


def create_xbrl_package(
    firm_id: str,
    client_id: str,
    financial_year: str,
    created_by: str,
    year_end_engagement_id: str | None = None,
    taxonomy_version: str = DEFAULT_TAXONOMY,
) -> dict:
    # An unregistered version is refused before anything is stored (UnknownTaxonomy), and the canonical name is what is kept.
    taxonomy_version = taxonomy_for(taxonomy_version).version
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "taxonomy_version": taxonomy_version,
            "status": "draft",
            "year_end_engagement_id": year_end_engagement_id,
            "balance_sheet_json": {},
            "pnl_json": {},
            "notes_json": {},
            "xbrl_xml": None,
            "validation_errors": [],
            "missing_tags": [],
            "version": 1,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_PACKAGES[row["id"]] = row
        return _with_notice(row)

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "taxonomy_version": taxonomy_version,
        "status": "draft",
        "year_end_engagement_id": year_end_engagement_id,
        "created_by": created_by,
    }
    res = sb.table("xbrl_packages").insert(row).execute()
    return _with_notice(res.data[0] if res.data else row)


def _with_notice(package: dict) -> dict:
    """The package as the API returns it: `taxonomy_notice` says whether the version it was tagged under has been checked.
    Added on the way out and never stored, so it cannot go stale when a version is promoted."""
    return {**package, "taxonomy_notice": taxonomy_notice(package.get("taxonomy_version"))}


def list_xbrl_packages(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [_with_notice(p) for p in _MOCK_PACKAGES.values()
                if p["firm_id"] == firm_id and p["client_id"] == client_id]
    sb = _supabase()
    res = sb.table("xbrl_packages").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).order("created_at", desc=True).execute()
    return [_with_notice(p) for p in (res.data or [])]


def update_xbrl_data(
    firm_id: str,
    package_id: str,
    balance_sheet_json: dict | None = None,
    pnl_json: dict | None = None,
    notes_json: dict | None = None,
) -> dict:
    update: dict = {"updated_at": datetime.now(timezone.utc).isoformat(), "status": "draft"}
    if balance_sheet_json is not None:
        update["balance_sheet_json"] = balance_sheet_json
    if pnl_json is not None:
        update["pnl_json"] = pnl_json
    if notes_json is not None:
        update["notes_json"] = notes_json

    if _USE_MOCK:
        if package_id in _MOCK_PACKAGES:
            _MOCK_PACKAGES[package_id].update(update)
        return _MOCK_PACKAGES.get(package_id, {})

    sb = _supabase()
    res = sb.table("xbrl_packages").update(update).eq("id", package_id).eq(
        "firm_id", firm_id
    ).execute()
    return res.data[0] if res.data else {}


def validate_xbrl_package(
    firm_id: str,
    package_id: str,
    taxonomy_version: str | None = None,
) -> dict:
    """
    Validate XBRL package against MCA taxonomy. With no version given, the package's own stored version is the one it is
    checked against, and a stored version this product does not hold is refused (UnknownTaxonomy) rather than checked
    against another one's tags.
    Checks: mandatory tags present, data types correct, balancing equations.
    Returns validation report with errors and missing tags.
    """
    if _USE_MOCK:
        pkg = _MOCK_PACKAGES.get(package_id, {})
        bs = pkg.get("balance_sheet_json", {})
        pnl = pkg.get("pnl_json", {})
        data = {**bs, **pnl}
        errors, missing = _run_validation(data, taxonomy_version or pkg.get("taxonomy_version"))
        pkg["validation_errors"] = errors
        pkg["missing_tags"] = missing
        pkg["status"] = "validation_failed" if errors or missing else "validated"
        return _with_notice(pkg)

    sb = _supabase()
    pkg_res = sb.table("xbrl_packages").select("*").eq("id", package_id).eq(
        "firm_id", firm_id
    ).maybe_single().execute()
    if not pkg_res.data:
        raise ValueError("XBRL package not found")

    pkg = pkg_res.data
    data = {**pkg.get("balance_sheet_json", {}), **pkg.get("pnl_json", {})}
    errors, missing = _run_validation(data, taxonomy_version or pkg.get("taxonomy_version"))

    new_status = "validation_failed" if (errors or missing) else "validated"
    update_res = sb.table("xbrl_packages").update({
        "validation_errors": errors,
        "missing_tags": missing,
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", package_id).execute()

    result = update_res.data[0] if update_res.data else pkg
    result["validation_errors"] = errors
    result["missing_tags"] = missing
    return _with_notice(result)


def _check_balance_equation(data: dict, mappings=None) -> list[str]:
    """Companies Act 2013, Schedule III, Part I: Total Assets must equal
    Total Equity and Liabilities. the tag table carries no explicit
    "TotalAssets"/"TotalEquityAndLiabilities" tag, so sum the Balance Sheet
    lines by their section ("...NonCurrentAssets.../...CurrentAssets..." vs
    "...Equity..."/"...Liabilities...") — the same grouping the section
    names themselves encode."""
    total_assets = 0
    total_equity_liab = 0
    for schedule_line, _xbrl_tag, _label, _mandatory in (DEFAULT_MAPPINGS if mappings is None else mappings):
        val = data.get(schedule_line)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        parts = schedule_line.split(".")
        if len(parts) < 2 or parts[0] != "BalanceSheet":
            continue
        section = parts[1]
        if section == "Equity" or "Liabilities" in section:
            total_equity_liab += val
        elif "Assets" in section:
            total_assets += val

    if total_assets != total_equity_liab:
        return [
            f"Balance Sheet does not balance: Total Assets (₹{rupees_paise(total_assets)}) != "
            f"Total Equity & Liabilities (₹{rupees_paise(total_equity_liab)}), "
            f"difference ₹{rupees_paise(total_assets - total_equity_liab)}"
        ]
    return []


def _run_validation(data: dict, taxonomy_version: str | None) -> tuple[list[str], list[str]]:
    """Check mandatory tags, data type compliance, and the Balance Sheet
    equation (Total Assets == Total Equity and Liabilities)."""
    errors: list[str] = []
    missing: list[str] = []
    mappings = taxonomy_for(taxonomy_version).mappings

    for schedule_line, xbrl_tag, label, is_mandatory in mappings:
        if is_mandatory and schedule_line not in data:
            missing.append(f"{schedule_line} ({xbrl_tag}) — {label}")
        elif schedule_line in data:
            val = data[schedule_line]
            if not isinstance(val, (int, float)):
                errors.append(f"{schedule_line}: expected numeric value, got {type(val).__name__}")
            if isinstance(val, float):
                errors.append(f"{schedule_line}: use integer paise — never float")

    errors.extend(_check_balance_equation(data, mappings))
    return errors, missing


def generate_xbrl_xml(
    firm_id: str,
    package_id: str,
    client_name: str,
    cin: str,
) -> str:
    """
    Generate MCA XBRL XML from validated package data.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA portal
    """
    if _USE_MOCK:
        pkg = _MOCK_PACKAGES.get(package_id, {})
    else:
        sb = _supabase()
        pkg_res = sb.table("xbrl_packages").select("*").eq("id", package_id).eq(
            "firm_id", firm_id
        ).maybe_single().execute()
        if not pkg_res.data:
            raise ValueError("XBRL package not found")
        pkg = pkg_res.data

    if pkg.get("status") not in ("validated", "reviewed"):
        raise ValueError("XBRL package must be validated before generating XML")
    # The tags and the namespace are the package's own version's (UnknownTaxonomy if the stored version is not one we hold).
    taxonomy = taxonomy_for(pkg.get("taxonomy_version"))

    # Build XBRL XML structure
    xbrl_ns = "http://www.xbrl.org/2003/instance"
    mca_ns = taxonomy.namespace
    xbrl = Element("xbrl", {
        "xmlns": xbrl_ns,
        f"xmlns:{taxonomy.prefix}": mca_ns,
        "xmlns:xbrli": xbrl_ns,
    })

    # Context
    ctx = SubElement(xbrl, "context", {"id": "CurrentPeriod"})
    entity = SubElement(ctx, "entity")
    SubElement(entity, "identifier", {"scheme": "http://www.mca.gov.in"}).text = cin
    period = SubElement(ctx, "period")
    fy_start, fy_end_yr = pkg["financial_year"].split("-")
    SubElement(period, "startDate").text = f"{fy_start}-04-01"
    SubElement(period, "endDate").text = f"20{fy_end_yr}-03-31"

    # Unit
    unit = SubElement(xbrl, "unit", {"id": "INR"})
    SubElement(unit, "measure").text = "iso4217:INR"

    # Data items
    all_data = {
        **pkg.get("balance_sheet_json", {}),
        **pkg.get("pnl_json", {}),
    }
    for schedule_line, xbrl_tag, _, _ in taxonomy.mappings:
        if schedule_line in all_data:
            # Convert paise to rupees for XBRL (store in rupees per MCA requirement).
            # task #240 fix: floor division truncated every non-zero paise
            # remainder toward zero (e.g. 12,345 paise -> Rs 123, silently
            # dropping 45 paise) instead of rounding to the nearest rupee —
            # never float, per CLAUDE.md, so round via Decimal.
            val_paise = all_data[schedule_line]
            if isinstance(val_paise, int) and not isinstance(val_paise, bool):
                val_rupees = int(
                    (Decimal(val_paise) / 100).to_integral_value(rounding=ROUND_HALF_UP)
                )
            else:
                val_rupees = val_paise
            elem = SubElement(xbrl, xbrl_tag, {
                "contextRef": "CurrentPeriod",
                "unitRef": "INR",
                "decimals": "0",
            })
            elem.text = str(val_rupees)

    xml_str = tostring(xbrl, encoding="unicode", xml_declaration=False)
    xml_output = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

    if not _USE_MOCK:
        sb = _supabase()
        sb.table("xbrl_packages").update({
            "xbrl_xml": xml_output,
            "status": "validated",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", package_id).execute()

    return xml_output


def get_default_tag_mappings(taxonomy_version: str | None = DEFAULT_TAXONOMY) -> list[dict]:
    return [
        {
            "schedule_line": sl,
            "xbrl_tag": tag,
            "xbrl_label": label,
            "is_mandatory": mandatory,
            "data_type": "monetary",
        }
        for sl, tag, label, mandatory in taxonomy_for(taxonomy_version).mappings
    ]
