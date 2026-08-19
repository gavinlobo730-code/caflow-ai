"""GSTR-1 payload builder — assembles GSTN-compatible JSON.

CGST Act Section 37 — furnishing details of outward supplies.
GSTN API Specification v1.3 (July 2023).

Table mapping:
  4A  → B2B  (supplies to registered persons)
  4B  → B2CS (unregistered, intra-state or inter-state ≤₹2.5L)
  4C  → B2CL (unregistered, inter-state >₹2.5L)
  9B  → CDNR (credit/debit notes to registered)
  9B  → CDNUR (credit/debit notes to unregistered)
  6A  → EXP  (exports)
  12  → HSN  (HSN/SAC summary)
  13  → DOC  (documents issued summary)

All amounts in paise internally; converted to rupees (2 decimal) for GSTN JSON.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .classifier import GSTInvoiceCategory


@dataclass(frozen=True)
class InvoiceLine:
    """Single line item on an invoice."""
    hsn_sac_code: str
    description: str
    quantity: float
    unit: str
    rate_paise: int
    taxable_paise: int
    gst_rate: float    # e.g. 18.0
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int


@dataclass(frozen=True)
class InvoiceForGSTR1:
    """Transaction fields required to build GSTR-1 tables."""
    id: str
    transaction_type: str
    reference_no: str              # invoice number
    transaction_date: str          # YYYY-MM-DD
    party_gstin: str | None
    party_name: str
    place_of_supply: str           # 2-digit state code
    is_interstate: bool
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    is_reverse_charge: bool
    invoice_type: str              # Regular | SEZ_with_payment | SEZ_without_payment | Deemed_export
    supply_type: str
    gst_invoice_category: GSTInvoiceCategory
    original_invoice_ref: str | None  # for CDNR/CDNUR
    original_invoice_date: str | None
    lines: list[InvoiceLine]
    # Invoice-level round-off (nearest ₹1), integer paise. DEFAULT 0 so existing
    # callers/invoices are unchanged; included in the GSTN invoice "val" so the
    # reported invoice value reconciles to the invoice's printed total. Does not
    # affect taxable value or tax (CGST Act §15).
    round_off_paise: int = 0


# GSTR-1 permits paise, so its GSTN JSON uses 2-decimal rupees. Canonical
# conversion lives in the shared GST money module (GSTR-3B uses whole rupees).
from domain.gst.money import paise_to_rupees_2dp as _paise_to_rupees


def _format_date_gstn(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD-MM-YYYY (GSTN format)."""
    parts = iso_date.split("-")
    if len(parts) != 3:
        return iso_date
    return f"{parts[2]}-{parts[1]}-{parts[0]}"


@dataclass
class GSTR1Payload:
    """Assembled GSTR-1 payload ready for GSTN upload."""
    gstin: str
    period: str          # MMYYYY
    payload: dict        # GSTN-compatible JSON
    summary: dict        # human-readable summary for CA review
    invoice_count: int
    taxable_total_paise: int
    tax_total_paise: int


def build_gstr1(
    invoices: Sequence[InvoiceForGSTR1],
    gstin: str,
    period: str,
    aggregate_turnover_paise: int = 0,
) -> GSTR1Payload:
    """Build the complete GSTR-1 payload from classified invoices.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Args:
        invoices: All classified, posted transactions for the period.
        gstin: Taxpayer GSTIN (2-digit state + PAN + entity + Z + checksum).
        period: MMYYYY filing period string.
        aggregate_turnover_paise: Annual aggregate turnover used for HSN digit requirement.

    Returns:
        GSTR1Payload with GSTN-compatible JSON and human-readable summary.
    """
    b2b_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.B2B]
    b2cs_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.B2CS]
    b2cl_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.B2CL]
    cdnr_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.CDNR]
    cdnur_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.CDNA]
    nil_invoices = [i for i in invoices if i.gst_invoice_category == GSTInvoiceCategory.NIL_EXEMPT]
    exp_invoices = [i for i in invoices if i.gst_invoice_category in (
        GSTInvoiceCategory.EXP_WP, GSTInvoiceCategory.EXP_WOP
    )]

    payload: dict = {
        "gstin": gstin,
        "fp": period,
        "gt": _paise_to_rupees(aggregate_turnover_paise),
        "cur_gt": _paise_to_rupees(
            sum(i.taxable_amount_paise for i in invoices
                if i.transaction_type == "sales_invoice")
        ),
    }

    b2b = _build_b2b(b2b_invoices)
    if b2b:
        payload["b2b"] = b2b

    b2cs = _build_b2cs(b2cs_invoices)
    if b2cs:
        payload["b2cs"] = b2cs

    b2cl = _build_b2cl(b2cl_invoices)
    if b2cl:
        payload["b2cl"] = b2cl

    nil = _build_nil(nil_invoices)
    if nil:
        payload["nil"] = {"inv": nil}

    cdnr = _build_cdnr(cdnr_invoices)
    if cdnr:
        payload["cdnr"] = cdnr

    cdnur = _build_cdnur(cdnur_invoices)
    if cdnur:
        payload["cdnur"] = cdnur

    exp = _build_exp(exp_invoices)
    if exp:
        payload["exp"] = exp

    hsn = _build_hsn_summary(invoices, aggregate_turnover_paise)
    if hsn:
        payload["hsn"] = {"data": hsn}

    doc_issue = _build_doc_summary(invoices)
    if doc_issue:
        payload["doc_issue"] = {"doc_det": doc_issue}

    all_sales = [i for i in invoices if i.transaction_type == "sales_invoice"]
    taxable_total = sum(i.taxable_amount_paise for i in all_sales)
    tax_total = sum(i.cgst_paise + i.sgst_paise + i.igst_paise for i in all_sales)

    summary = {
        "period": period,
        "gstin": gstin,
        "counts": {
            "b2b": sum(len(g["inv"]) for g in b2b),
            "b2cs_rate_groups": len(b2cs),
            "b2cl": sum(len(g["inv"]) for g in b2cl),
            "credit_notes_registered": len(cdnr_invoices),
            "credit_notes_unregistered": len(cdnur_invoices),
            "exports": len(exp_invoices),
            # Table 8. Counted so a CA reviewing the summary can see nil/exempt
            # turnover was declared — it was absent from the payload entirely
            # before, and absent from this summary too, so nothing on screen
            # revealed that it had been dropped.
            "nil_exempt": len(nil_invoices),
        },
        "totals_rupees": {
            "taxable": _paise_to_rupees(taxable_total),
            "cgst": _paise_to_rupees(sum(i.cgst_paise for i in all_sales)),
            "sgst": _paise_to_rupees(sum(i.sgst_paise for i in all_sales)),
            "igst": _paise_to_rupees(sum(i.igst_paise for i in all_sales)),
        },
    }

    return GSTR1Payload(
        gstin=gstin,
        period=period,
        payload=payload,
        summary=summary,
        invoice_count=len(all_sales),
        taxable_total_paise=taxable_total,
        tax_total_paise=tax_total,
    )


# ── Table 4A: B2B Invoices ────────────────────────────────────────────────────

def _build_b2b(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Group B2B invoices by receiver GSTIN.

    GSTN format: [{ctin, inv: [{inum, idt, val, pos, rchrg, inv_typ, itms}]}]
    """
    by_gstin: dict[str, list[InvoiceForGSTR1]] = {}
    for inv in invoices:
        gstin = inv.party_gstin or ""
        by_gstin.setdefault(gstin, []).append(inv)

    result = []
    for receiver_gstin, invs in by_gstin.items():
        invoice_list = []
        for inv in invs:
            invoice_list.append({
                "inum": inv.reference_no,
                "idt": _format_date_gstn(inv.transaction_date),
                "val": _paise_to_rupees(inv.taxable_amount_paise + inv.cgst_paise + inv.sgst_paise + inv.igst_paise + inv.cess_paise + inv.round_off_paise),
                "pos": inv.place_of_supply or "",
                "rchrg": "Y" if inv.is_reverse_charge else "N",
                "inv_typ": inv.invoice_type if inv.invoice_type != "Regular" else "R",
                "itms": _build_invoice_items(inv),
            })
        result.append({"ctin": receiver_gstin, "inv": invoice_list})
    return result


def _build_invoice_items(inv: InvoiceForGSTR1) -> list[dict]:
    """Build itms array from invoice lines, grouped by GST rate."""
    if not inv.lines:
        # Header-level fallback when line items are not stored
        return [{
            "num": 1,
            "itm_det": {
                "txval": _paise_to_rupees(inv.taxable_amount_paise),
                "rt": _infer_rate(inv),
                "iamt": _paise_to_rupees(inv.igst_paise),
                "camt": _paise_to_rupees(inv.cgst_paise),
                "samt": _paise_to_rupees(inv.sgst_paise),
                "csamt": _paise_to_rupees(inv.cess_paise),
            },
        }]

    # Group lines by GST rate — GSTN requires one itm_det per rate
    by_rate: dict[float, dict] = {}
    for line in inv.lines:
        r = line.gst_rate
        if r not in by_rate:
            by_rate[r] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
        by_rate[r]["txval"] += line.taxable_paise
        by_rate[r]["iamt"] += line.igst_paise
        by_rate[r]["camt"] += line.cgst_paise
        by_rate[r]["samt"] += line.sgst_paise
        by_rate[r]["csamt"] += line.cess_paise

    items = []
    for idx, (rate, totals) in enumerate(by_rate.items(), start=1):
        items.append({
            "num": idx,
            "itm_det": {
                "txval": _paise_to_rupees(totals["txval"]),
                "rt": rate,
                "iamt": _paise_to_rupees(totals["iamt"]),
                "camt": _paise_to_rupees(totals["camt"]),
                "samt": _paise_to_rupees(totals["samt"]),
                "csamt": _paise_to_rupees(totals["csamt"]),
            },
        })
    return items


def _infer_rate(inv: InvoiceForGSTR1) -> float:
    """Infer GST rate from tax amounts when no line items are stored."""
    if inv.taxable_amount_paise == 0:
        return 0.0
    total_tax = inv.cgst_paise + inv.sgst_paise + inv.igst_paise
    rate = (total_tax * 100 * 100) // inv.taxable_amount_paise  # integer paise math
    return float(rate) / 100


# ── Table 4B: B2CS ────────────────────────────────────────────────────────────

def _build_b2cs(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Build B2CS table grouped by rate, place of supply, AND supply type (INTER/INTRA).

    GSTN format: [{sply_tp, rt, pos, txval, iamt, camt, samt, csamt}]
    B2CS = unregistered buyer, intra-state OR inter-state ≤₹2.5L.

    GSTN spec requires separate rows when sply_tp differs, even at identical rate+POS.
    Key includes is_interstate so INTER and INTRA are never merged.
    """
    # Key: (rate, place_of_supply, is_interstate) — all three determine a distinct GSTN row
    by_key: dict[tuple, dict] = {}
    for inv in invoices:
        rate = _infer_rate(inv)
        key = (rate, inv.place_of_supply or "", inv.is_interstate)
        if key not in by_key:
            by_key[key] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
        by_key[key]["txval"] += inv.taxable_amount_paise
        by_key[key]["iamt"] += inv.igst_paise
        by_key[key]["camt"] += inv.cgst_paise
        by_key[key]["samt"] += inv.sgst_paise
        by_key[key]["csamt"] += inv.cess_paise

    return [
        {
            # sply_tp comes directly from the grouping key — no representative-invoice lookup
            "sply_tp": "INTER" if is_interstate else "INTRA",
            "rt": rate,
            "pos": pos,
            "txval": _paise_to_rupees(totals["txval"]),
            "iamt": _paise_to_rupees(totals["iamt"]),
            "camt": _paise_to_rupees(totals["camt"]),
            "samt": _paise_to_rupees(totals["samt"]),
            "csamt": _paise_to_rupees(totals["csamt"]),
        }
        for (rate, pos, is_interstate), totals in by_key.items()
    ]


# ── Table 4C: B2CL ────────────────────────────────────────────────────────────

def _build_b2cl(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Build B2CL table grouped by place of supply.

    GSTN format: [{pos, inv: [{inum, idt, val, itms}]}]
    """
    by_pos: dict[str, list[InvoiceForGSTR1]] = {}
    for inv in invoices:
        pos = inv.place_of_supply or ""
        by_pos.setdefault(pos, []).append(inv)

    return [
        {
            "pos": pos,
            "inv": [
                {
                    "inum": inv.reference_no,
                    "idt": _format_date_gstn(inv.transaction_date),
                    "val": _paise_to_rupees(inv.taxable_amount_paise + inv.igst_paise + inv.cess_paise + inv.round_off_paise),
                    "itms": _build_invoice_items(inv),
                }
                for inv in invs
            ],
        }
        for pos, invs in by_pos.items()
    ]


# ── Table 8: Nil-rated, exempted and non-GST outward supplies ────────────────

# GSTN sply_ty codes. The prefixes are genuinely confusable: INTR* is
# INTER-state, INTRA* is INTRA-state. Getting them backwards silently files
# every nil supply against the wrong half of table 8.
_NIL_SPLY_TY = {
    (True, True):   "INTRB2B",    # inter-state, registered buyer
    (True, False):  "INTRB2C",    # inter-state, unregistered
    (False, True):  "INTRAB2B",   # intra-state, registered
    (False, False): "INTRAB2C",   # intra-state, unregistered
}

# supply_type → the table 8 amount column it belongs in. CGST §23 / §11:
# nil-rated (taxable at 0%), exempted (notified exempt), and non-GST (outside
# GST altogether, e.g. petrol, alcohol) are three distinct declarations, not
# one bucket.
_NIL_AMOUNT_FIELD = {
    "nil_rated": "nil_amt",
    "exempt":    "expt_amt",
    "non_gst":   "ngsup_amt",
}


def _build_nil(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Table 8 — nil-rated, exempted and non-GST outward supplies.

    GSTN format: [{sply_ty, nil_amt, expt_amt, ngsup_amt}]

    WHY THIS EXISTS
        classify_transaction routes nil_rated / exempt / non_gst to NIL_EXEMPT
        ahead of every other check, and nothing here consumed that category —
        so every such supply was computed, categorised, and then silently
        dropped from the payload. A firm with exempt turnover filed a GSTR-1
        that simply did not mention it.

        That also blocked credit and debit notes from inheriting their
        original invoice's classification (CGST §34): inheriting a nil supply
        moved the note into a table that was not being built, turning a
        wrong-table entry into no entry at all.

    A credit note SUBTRACTS. Table 8 reports net values for the period, and a
    note against a nil supply adjusts that supply — it is not a separate one.
    """
    by_key: dict[tuple, dict] = {}
    for inv in invoices:
        field = _NIL_AMOUNT_FIELD.get(inv.supply_type)
        if field is None:
            # Only the three §23/§11 categories belong in table 8. Anything
            # else reaching here would be a classifier change, and silently
            # folding it into nil_amt would misdeclare it.
            continue
        key = (inv.is_interstate, bool(inv.party_gstin))
        if key not in by_key:
            by_key[key] = {"nil_amt": 0, "expt_amt": 0, "ngsup_amt": 0}
        sign = -1 if inv.transaction_type == "credit_note" else 1
        by_key[key][field] += sign * inv.taxable_amount_paise

    return [
        {
            "sply_ty": _NIL_SPLY_TY[key],
            "nil_amt": _paise_to_rupees(totals["nil_amt"]),
            "expt_amt": _paise_to_rupees(totals["expt_amt"]),
            "ngsup_amt": _paise_to_rupees(totals["ngsup_amt"]),
        }
        for key, totals in by_key.items()
    ]


# ── Table 9B: CDNR / CDNUR ───────────────────────────────────────────────────

def _build_cdnr(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Credit/debit notes to registered buyers.

    GSTN format: [{ctin, nt: [{ntty, nt_num, nt_dt, val, pos, rchrg, itms}]}]
    """
    by_gstin: dict[str, list] = {}
    for inv in invoices:
        gstin = inv.party_gstin or ""
        by_gstin.setdefault(gstin, []).append(inv)

    return [
        {
            "ctin": g,
            "nt": [
                {
                    "ntty": "C" if inv.transaction_type == "credit_note" else "D",
                    "nt_num": inv.reference_no,
                    "nt_dt": _format_date_gstn(inv.transaction_date),
                    "val": _paise_to_rupees(inv.taxable_amount_paise + inv.cgst_paise + inv.sgst_paise + inv.igst_paise + inv.cess_paise + inv.round_off_paise),
                    "pos": inv.place_of_supply or "",
                    "rchrg": "Y" if inv.is_reverse_charge else "N",
                    "itms": _build_invoice_items(inv),
                }
                for inv in invs
            ],
        }
        for g, invs in by_gstin.items()
    ]


def _build_cdnur(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Credit/debit notes to unregistered buyers."""
    return [
        {
            "ntty": "C" if inv.transaction_type == "credit_note" else "D",
            "nt_num": inv.reference_no,
            "nt_dt": _format_date_gstn(inv.transaction_date),
            "typ": "B2CL" if inv.is_interstate else "B2CS",
            "val": _paise_to_rupees(inv.taxable_amount_paise + inv.igst_paise + inv.cess_paise + inv.round_off_paise),
            "pos": inv.place_of_supply or "",
            "itms": _build_invoice_items(inv),
        }
        for inv in invoices
    ]


# ── Table 6A: Exports ─────────────────────────────────────────────────────────

def _build_exp(invoices: list[InvoiceForGSTR1]) -> list[dict]:
    """Export invoices — with or without payment of IGST."""
    by_type: dict[str, list] = {}
    for inv in invoices:
        exp_type = "WPAY" if inv.gst_invoice_category == GSTInvoiceCategory.EXP_WP else "WOPAY"
        by_type.setdefault(exp_type, []).append(inv)

    return [
        {
            "exp_typ": exp_type,
            "inv": [
                {
                    "inum": inv.reference_no,
                    "idt": _format_date_gstn(inv.transaction_date),
                    "val": _paise_to_rupees(inv.taxable_amount_paise + inv.igst_paise + inv.cess_paise + inv.round_off_paise),
                    "sbpcode": "",
                    "sbnum": "",
                    "sbdt": "",
                    "itms": _build_invoice_items(inv),
                }
                for inv in invs
            ],
        }
        for exp_type, invs in by_type.items()
    ]


# ── Table 12: HSN Summary ─────────────────────────────────────────────────────

# CGST Rule 46(h): turnover thresholds for HSN digit requirement
_HSN_DIGITS_5CR_PAISE = 5_00_00_000_00   # ₹5 Cr in paise → 6-digit HSN
_HSN_DIGITS_1_5CR_PAISE = 1_50_00_000_00  # ₹1.5 Cr → 4-digit HSN (below this: optional)


def _required_hsn_digits(turnover_paise: int) -> int:
    if turnover_paise >= _HSN_DIGITS_5CR_PAISE:
        return 6
    if turnover_paise >= _HSN_DIGITS_1_5CR_PAISE:
        return 4
    return 0  # optional below ₹1.5 Cr


def _build_hsn_summary(invoices: Sequence[InvoiceForGSTR1], turnover_paise: int) -> list[dict]:
    """Aggregate line items by HSN/SAC code for Table 12."""
    required_digits = _required_hsn_digits(turnover_paise)

    by_hsn: dict[str, dict] = {}
    for inv in invoices:
        if inv.transaction_type not in ("sales_invoice",):
            continue
        if inv.lines:
            for line in inv.lines:
                code = (line.hsn_sac_code or "")[:max(required_digits, len(line.hsn_sac_code or ""))]
                if not code:
                    continue
                if code not in by_hsn:
                    by_hsn[code] = {
                        "desc": line.description[:30],
                        "uqc": line.unit,
                        "qty": 0.0,
                        "txval": 0,
                        "iamt": 0,
                        "camt": 0,
                        "samt": 0,
                        "csamt": 0,
                    }
                by_hsn[code]["qty"] += line.quantity
                by_hsn[code]["txval"] += line.taxable_paise
                by_hsn[code]["iamt"] += line.igst_paise
                by_hsn[code]["camt"] += line.cgst_paise
                by_hsn[code]["samt"] += line.sgst_paise
                by_hsn[code]["csamt"] += line.cess_paise
        else:
            # No line items — aggregate at invoice level (no HSN breakdown possible)
            code = "OTH"
            if code not in by_hsn:
                by_hsn[code] = {"desc": "Other", "uqc": "OTH", "qty": 0.0,
                                 "txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
            by_hsn[code]["txval"] += inv.taxable_amount_paise
            by_hsn[code]["iamt"] += inv.igst_paise
            by_hsn[code]["camt"] += inv.cgst_paise
            by_hsn[code]["samt"] += inv.sgst_paise
            by_hsn[code]["csamt"] += inv.cess_paise

    return [
        {
            "num": idx,
            "hsn_sc": code,
            "desc": data["desc"],
            "uqc": data["uqc"],
            "qty": round(data["qty"], 3),
            # csamt was omitted here while every other table's `val` includes
            # cess, so an HSN row's value understated a cess-bearing supply.
            # Latent today — client_sales_invoice_lines has no cess column, so
            # line cess is always 0 — but wrong the moment one is added.
            "val": _paise_to_rupees(data["txval"] + data["iamt"] + data["camt"]
                                    + data["samt"] + data["csamt"]),
            "txval": _paise_to_rupees(data["txval"]),
            "iamt": _paise_to_rupees(data["iamt"]),
            "camt": _paise_to_rupees(data["camt"]),
            "samt": _paise_to_rupees(data["samt"]),
            "csamt": _paise_to_rupees(data["csamt"]),
        }
        for idx, (code, data) in enumerate(by_hsn.items(), start=1)
    ]


# ── Table 13: Documents Issued Summary ───────────────────────────────────────

def _build_doc_summary(invoices: Sequence[InvoiceForGSTR1]) -> list[dict]:
    """Count documents issued by type for Table 13."""
    counts: dict[str, int] = {
        "Invoices for outward supply": 0,
        "Credit Note": 0,
        "Debit Note": 0,
    }
    for inv in invoices:
        if inv.transaction_type == "sales_invoice":
            counts["Invoices for outward supply"] += 1
        elif inv.transaction_type == "credit_note":
            counts["Credit Note"] += 1
        elif inv.transaction_type == "debit_note":
            counts["Debit Note"] += 1

    result = []
    for idx, (doc_type, count) in enumerate(counts.items(), start=1):
        if count == 0:
            continue
        result.append({
            "doc_num": idx,
            "doc_typ": doc_type,
            "docs": [{"num": count, "cancel": 0, "net_issue": count}],
        })
    return result
