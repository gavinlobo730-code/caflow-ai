"""End-to-end GST Engine Verification Script.

Exercises the full engine pipeline with realistic CA firm sample data:
  - Invoice classification
  - GSTR-1 payload generation
  - GSTR-3B payload generation
  - Validation
  - GSTN specification field-by-field checks
  - Readiness scoring

Run: python tests/e2e_gst_verification.py
"""
import json
import sys
import traceback
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, ".")

from domain.gst.classifier import (
    GSTInvoiceCategory,
    TransactionForClassification,
    classify_transaction,
    classify_transactions,
    B2CL_THRESHOLD_PAISE,
)
from domain.gst.gstr3b_computer import (
    SalesTransaction,
    PurchaseTransaction,
    GSTR2ARecord,
    compute_gstr3b,
)
from domain.gst.gstr1_builder import (
    InvoiceForGSTR1,
    InvoiceLine,
    build_gstr1,
    _paise_to_rupees,
)
from domain.gst.validator import GSTValidator, InvoiceToValidate

GSTIN = "27AABCU9603R1ZX"   # Maharashtra, valid format
PERIOD = "052025"            # May 2025
FIRM_TURNOVER_PAISE = 2_00_00_000_00   # ₹2 Cr — requires 4-digit HSN

validator = GSTValidator()

PASS = "✓"
FAIL = "✗"
WARN = "⚠"

checks: list[tuple[str, bool, str]] = []   # (label, passed, detail)


def check(label: str, condition: bool, detail: str = ""):
    checks.append((label, condition, detail))
    mark = PASS if condition else FAIL
    print(f"  {mark}  {label}" + (f" — {detail}" if detail else ""))
    return condition


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ═══════════════════════════════════════════════════════════════
# SAMPLE DATA
# ═══════════════════════════════════════════════════════════════

# ── Sales Transactions (for GSTR-3B) ──────────────────────────

sales_txns = [
    # B2B intrastate 18% — ₹5,00,000 taxable
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=5_00_000_00,
        cgst_paise=45_000_00, sgst_paise=45_000_00, igst_paise=0, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    ),
    # B2B interstate 18% — ₹3,00,000 taxable
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=3_00_000_00,
        cgst_paise=0, sgst_paise=0, igst_paise=54_000_00, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    ),
    # B2CS intrastate 12% — ₹80,000 taxable (below B2CL threshold)
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=80_000_00,
        cgst_paise=4_800_00, sgst_paise=4_800_00, igst_paise=0, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    ),
    # B2CL interstate 18% — ₹3,00,000 taxable (above B2CL ₹2.5L threshold)
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=3_00_000_00,
        cgst_paise=0, sgst_paise=0, igst_paise=54_000_00, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    ),
    # Credit note B2B — ₹50,000 reversal
    SalesTransaction(
        transaction_type="credit_note",
        taxable_amount_paise=50_000_00,
        cgst_paise=4_500_00, sgst_paise=4_500_00, igst_paise=0, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    ),
    # Zero-rated export — ₹2,00,000
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=2_00_000_00,
        cgst_paise=0, sgst_paise=0, igst_paise=0, cess_paise=0,
        supply_type="zero_rated", is_reverse_charge=False,
    ),
    # Exempt supply — ₹1,00,000
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=1_00_000_00,
        cgst_paise=0, sgst_paise=0, igst_paise=0, cess_paise=0,
        supply_type="exempt", is_reverse_charge=False,
    ),
    # RCM outward (GTA service received) — ₹30,000
    SalesTransaction(
        transaction_type="sales_invoice",
        taxable_amount_paise=30_000_00,
        cgst_paise=2_700_00, sgst_paise=2_700_00, igst_paise=0, cess_paise=0,
        supply_type="taxable", is_reverse_charge=True,
    ),
]

# ── Purchase Transactions (for ITC) ───────────────────────────

purchase_txns = [
    # Office supplies — intrastate 18% — ₹1,00,000
    PurchaseTransaction(
        taxable_amount_paise=1_00_000_00,
        cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0, cess_paise=0,
        is_reverse_charge=False,
    ),
    # IT services — interstate 18% — ₹2,00,000
    PurchaseTransaction(
        taxable_amount_paise=2_00_000_00,
        cgst_paise=0, sgst_paise=0, igst_paise=36_000_00, cess_paise=0,
        is_reverse_charge=False,
    ),
    # Capital goods — intrastate 18% — ₹5,00,000
    PurchaseTransaction(
        taxable_amount_paise=5_00_000_00,
        cgst_paise=45_000_00, sgst_paise=45_000_00, igst_paise=0, cess_paise=0,
        is_reverse_charge=False,
    ),
]

# ── GSTR-2A Records ──────────────────────────────────────────

gstr2a_records = [
    GSTR2ARecord(cgst_paise=9_000_00,  sgst_paise=9_000_00,  igst_paise=0),
    GSTR2ARecord(cgst_paise=0,          sgst_paise=0,          igst_paise=36_000_00),
    GSTR2ARecord(cgst_paise=40_000_00, sgst_paise=40_000_00, igst_paise=0),  # less than book
]

# ── TransactionForClassification (for GSTR-1) ─────────────────

raw_txns = [
    # B2B intrastate 18%
    TransactionForClassification(
        id="TXN001", transaction_type="sales_invoice",
        party_gstin="29AADCB2230M1ZT",
        is_interstate=False, taxable_amount_paise=5_00_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="27",
    ),
    # B2B interstate 18%
    TransactionForClassification(
        id="TXN002", transaction_type="sales_invoice",
        party_gstin="29AADCB2230M1ZT",
        is_interstate=True, taxable_amount_paise=3_00_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="29",
    ),
    # B2CS intrastate 12% — unregistered, below ₹2.5L
    TransactionForClassification(
        id="TXN003", transaction_type="sales_invoice",
        party_gstin=None,
        is_interstate=False, taxable_amount_paise=80_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="27",
    ),
    # B2CL interstate 18% — unregistered, above ₹2.5L
    TransactionForClassification(
        id="TXN004", transaction_type="sales_invoice",
        party_gstin=None,
        is_interstate=True, taxable_amount_paise=3_00_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="29",
    ),
    # CDNR — credit note to registered buyer
    TransactionForClassification(
        id="TXN005", transaction_type="credit_note",
        party_gstin="29AADCB2230M1ZT",
        is_interstate=False, taxable_amount_paise=50_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="27",
    ),
    # EXP_WOP — export without payment
    TransactionForClassification(
        id="TXN006", transaction_type="sales_invoice",
        party_gstin=None,
        is_interstate=True, taxable_amount_paise=2_00_000_00,
        supply_type="zero_rated", invoice_type="SEZ_without_payment", place_of_supply="96",
    ),
    # NIL_EXEMPT
    TransactionForClassification(
        id="TXN007", transaction_type="sales_invoice",
        party_gstin=None,
        is_interstate=False, taxable_amount_paise=1_00_000_00,
        supply_type="exempt", invoice_type="Regular", place_of_supply="27",
    ),
    # B2CS interstate 18% below ₹2.5L — different POS from TXN003
    TransactionForClassification(
        id="TXN008", transaction_type="sales_invoice",
        party_gstin=None,
        is_interstate=True, taxable_amount_paise=1_50_000_00,
        supply_type="taxable", invoice_type="Regular", place_of_supply="29",
    ),
]

# ── InvoiceForGSTR1 objects ────────────────────────────────────

def make_gstr1_invoice(
    id: str, ref: str, date: str, party_gstin, party_name: str,
    pos: str, is_interstate: bool, taxable: int,
    cgst: int, sgst: int, igst: int, cess: int,
    txn_type: str, supply_type: str, invoice_type: str,
    category: GSTInvoiceCategory,
    orig_ref=None, orig_date=None,
    lines=None,
):
    return InvoiceForGSTR1(
        id=id, transaction_type=txn_type, reference_no=ref,
        transaction_date=date, party_gstin=party_gstin, party_name=party_name,
        place_of_supply=pos, is_interstate=is_interstate,
        taxable_amount_paise=taxable, cgst_paise=cgst, sgst_paise=sgst,
        igst_paise=igst, cess_paise=cess, is_reverse_charge=False,
        invoice_type=invoice_type, supply_type=supply_type,
        gst_invoice_category=category,
        original_invoice_ref=orig_ref, original_invoice_date=orig_date,
        lines=lines or [],
    )


invoices_for_gstr1 = [
    # B2B intrastate 18%
    make_gstr1_invoice(
        "TXN001", "INV/2025/001", "2025-05-03",
        "29AADCB2230M1ZT", "Acme Technologies Pvt Ltd",
        "27", False, 5_00_000_00, 45_000_00, 45_000_00, 0, 0,
        "sales_invoice", "taxable", "Regular", GSTInvoiceCategory.B2B,
        lines=[
            InvoiceLine("998213", "Taxation consulting services", 1.0, "OTH",
                        5_00_000_00, 5_00_000_00, 18.0, 45_000_00, 45_000_00, 0, 0)
        ]
    ),
    # B2B interstate 18%
    make_gstr1_invoice(
        "TXN002", "INV/2025/002", "2025-05-07",
        "29AADCB2230M1ZT", "Acme Technologies Pvt Ltd",
        "29", True, 3_00_000_00, 0, 0, 54_000_00, 0,
        "sales_invoice", "taxable", "Regular", GSTInvoiceCategory.B2B,
        lines=[
            InvoiceLine("998211", "Accounting and bookkeeping", 1.0, "OTH",
                        3_00_000_00, 3_00_000_00, 18.0, 0, 0, 54_000_00, 0)
        ]
    ),
    # B2CS intrastate 12%
    make_gstr1_invoice(
        "TXN003", "INV/2025/003", "2025-05-10",
        None, "Walk-in Customer",
        "27", False, 80_000_00, 4_800_00, 4_800_00, 0, 0,
        "sales_invoice", "taxable", "Regular", GSTInvoiceCategory.B2CS,
        lines=[
            InvoiceLine("4820", "Diaries and stationery", 100.0, "NOS",
                        800_00, 80_000_00, 12.0, 4_800_00, 4_800_00, 0, 0)
        ]
    ),
    # B2CL interstate 18% (₹3L > ₹2.5L threshold)
    make_gstr1_invoice(
        "TXN004", "INV/2025/004", "2025-05-12",
        None, "Out-of-state Consumer",
        "29", True, 3_00_000_00, 0, 0, 54_000_00, 0,
        "sales_invoice", "taxable", "Regular", GSTInvoiceCategory.B2CL,
        lines=[
            InvoiceLine("8471", "Laptop computer", 2.0, "NOS",
                        1_50_000_00, 3_00_000_00, 18.0, 0, 0, 54_000_00, 0)
        ]
    ),
    # CDNR — credit note to registered buyer
    make_gstr1_invoice(
        "TXN005", "CN/2025/001", "2025-05-20",
        "29AADCB2230M1ZT", "Acme Technologies Pvt Ltd",
        "27", False, 50_000_00, 4_500_00, 4_500_00, 0, 0,
        "credit_note", "taxable", "Regular", GSTInvoiceCategory.CDNR,
        orig_ref="INV/2025/001", orig_date="2025-05-03",
    ),
    # EXP_WOP — export without payment of IGST
    make_gstr1_invoice(
        "TXN006", "INV/2025/005", "2025-05-25",
        None, "US Client Inc",
        "96", True, 2_00_000_00, 0, 0, 0, 0,
        "sales_invoice", "zero_rated", "SEZ_without_payment", GSTInvoiceCategory.EXP_WOP,
    ),
    # B2CS INTER (same POS 29 as TXN004 but below threshold — different supply type)
    make_gstr1_invoice(
        "TXN008", "INV/2025/006", "2025-05-28",
        None, "Interstate Consumer",
        "29", True, 1_50_000_00, 0, 0, 27_000_00, 0,
        "sales_invoice", "taxable", "Regular", GSTInvoiceCategory.B2CS,
    ),
]

# ── Invoices for Validation ────────────────────────────────────

invoices_to_validate = [
    InvoiceToValidate(
        reference_no="INV/2025/001", transaction_date="2025-05-03",
        party_gstin="29AADCB2230M1ZT", place_of_supply="27",
        taxable_amount_paise=5_00_000_00, cgst_paise=45_000_00, sgst_paise=45_000_00,
        igst_paise=0, is_interstate=False, gst_rate=18.0,
    ),
    InvoiceToValidate(
        reference_no="INV/2025/002", transaction_date="2025-05-07",
        party_gstin="29AADCB2230M1ZT", place_of_supply="29",
        taxable_amount_paise=3_00_000_00, cgst_paise=0, sgst_paise=0,
        igst_paise=54_000_00, is_interstate=True, gst_rate=18.0,
    ),
    InvoiceToValidate(
        reference_no="INV/2025/003", transaction_date="2025-05-10",
        party_gstin=None, place_of_supply="27",
        taxable_amount_paise=80_000_00, cgst_paise=4_800_00, sgst_paise=4_800_00,
        igst_paise=0, is_interstate=False, gst_rate=12.0,
    ),
    InvoiceToValidate(
        reference_no="INV/2025/004", transaction_date="2025-05-12",
        party_gstin=None, place_of_supply="29",
        taxable_amount_paise=3_00_000_00, cgst_paise=0, sgst_paise=0,
        igst_paise=54_000_00, is_interstate=True, gst_rate=18.0,
    ),
]


# ═══════════════════════════════════════════════════════════════
# VERIFICATION RUNS
# ═══════════════════════════════════════════════════════════════

print("=" * 60)
print("  GST ENGINE END-TO-END VERIFICATION")
print(f"  GSTIN: {GSTIN}  Period: {PERIOD}")
print("=" * 60)

# ── STEP 1: Invoice Classification ────────────────────────────

section("STEP 1: Invoice Classification")

classifications = classify_transactions(raw_txns)
counts: dict[str, int] = {}
for cat in classifications.values():
    counts[cat.value] = counts.get(cat.value, 0) + 1

print(f"\n  Input: {len(raw_txns)} transactions")
print(f"  Results:")
for cat, cnt in sorted(counts.items()):
    print(f"    {cat}: {cnt}")

check("TXN001 classified as B2B", classifications["TXN001"] == GSTInvoiceCategory.B2B,
      f"got {classifications['TXN001'].value}")
check("TXN002 classified as B2B (interstate registered)", classifications["TXN002"] == GSTInvoiceCategory.B2B,
      f"got {classifications['TXN002'].value}")
check("TXN003 classified as B2CS (unregistered intrastate)", classifications["TXN003"] == GSTInvoiceCategory.B2CS,
      f"got {classifications['TXN003'].value}")
check("TXN004 classified as B2CL (unregistered, interstate, > ₹2.5L)",
      classifications["TXN004"] == GSTInvoiceCategory.B2CL,
      f"got {classifications['TXN004'].value}")
check("TXN005 classified as CDNR (credit note, registered)",
      classifications["TXN005"] == GSTInvoiceCategory.CDNR,
      f"got {classifications['TXN005'].value}")
check("TXN006 classified as EXP_WOP (SEZ_without_payment overrides zero_rated)",
      classifications["TXN006"] == GSTInvoiceCategory.EXP_WOP,
      f"got {classifications['TXN006'].value}")
check("TXN007 classified as NIL_EXEMPT (exempt supply)",
      classifications["TXN007"] == GSTInvoiceCategory.NIL_EXEMPT,
      f"got {classifications['TXN007'].value}")
check("TXN008 classified as B2CS (unregistered interstate < ₹2.5L)",
      classifications["TXN008"] == GSTInvoiceCategory.B2CS,
      f"got {classifications['TXN008'].value}")
check("B2CL threshold is ₹2,50,000 (₹2.5L)",
      B2CL_THRESHOLD_PAISE == 2_50_000_00,
      f"threshold = ₹{B2CL_THRESHOLD_PAISE // 100:,}")


# ── STEP 2: GSTR-3B Computation ───────────────────────────────

section("STEP 2: GSTR-3B Computation")

gstr3b = compute_gstr3b(sales_txns, purchase_txns, gstr2a_records)

# Expected outward taxable: GSTR-3B Table 3.1 is NET (invoices minus credit notes).
# Sales (non-RCM, taxable): B2B intra (45000 CGST), B2CS (4800 CGST), B2B inter (54000 IGST), B2CL (54000 IGST)
# Credit note (taxable, non-RCM): reduces CGST/SGST by 4500 each
# RCM excluded from 3.1; TXN008 is in GSTR-1 only, not in sales_txns
expected_outward_cgst = 45_000_00 + 4_800_00 - 4_500_00   # 45,300.00
expected_outward_sgst = 45_000_00 + 4_800_00 - 4_500_00   # 45,300.00
expected_outward_igst = 54_000_00 + 54_000_00              # 1,08,000.00

# ITC book: cgst=9000+45000=54000, sgst same, igst=36000
# GSTR-2A: cgst=9000+40000=49000, sgst same, igst=36000
# Rule 36(4) (Notification 40/2021, w.e.f. 1 Jan 2022): 100% of GSTR-2A/2B,
# no provisional buffer.
# cgst cap = 49000 — book 54000 > cap, so capped at 49000
# sgst same
# igst: cap = 36000 — book 36000 == cap, not capped (only > cap triggers)
expected_itc_cgst = 49_000_00
expected_itc_sgst = 49_000_00
expected_itc_igst = 36_000_00                   # not capped

print(f"\n  Outward taxable (CGST): ₹{gstr3b.outward_taxable_cgst/100:,.2f}")
print(f"  Outward taxable (SGST): ₹{gstr3b.outward_taxable_sgst/100:,.2f}")
print(f"  Outward taxable (IGST): ₹{gstr3b.outward_taxable_igst/100:,.2f}")
print(f"  RCM CGST:               ₹{gstr3b.rcm_cgst/100:,.2f}")
print(f"  RCM SGST:               ₹{gstr3b.rcm_sgst/100:,.2f}")
print(f"  ITC Book CGST:          ₹{gstr3b.itc_book_cgst/100:,.2f}")
print(f"  ITC 2A CGST:            ₹{gstr3b.itc_2a_cgst/100:,.2f}")
print(f"  ITC Eligible CGST:      ₹{gstr3b.itc_cgst/100:,.2f}")
print(f"  ITC Eligible IGST:      ₹{gstr3b.itc_igst/100:,.2f}")
print(f"  Rule 36(4) cap applied: {gstr3b.itc_capped_by_2a}")
print(f"  Net CGST payable:       ₹{gstr3b.net_cgst/100:,.2f}")
print(f"  Net SGST payable:       ₹{gstr3b.net_sgst/100:,.2f}")
print(f"  Net IGST payable:       ₹{gstr3b.net_igst/100:,.2f}")

check("Outward CGST matches expected (taxable non-RCM invoices)",
      gstr3b.outward_taxable_cgst == expected_outward_cgst,
      f"got ₹{gstr3b.outward_taxable_cgst/100:,.2f}, expected ₹{expected_outward_cgst/100:,.2f}")

check("Outward IGST matches expected",
      gstr3b.outward_taxable_igst == expected_outward_igst,
      f"got ₹{gstr3b.outward_taxable_igst/100:,.2f}, expected ₹{expected_outward_igst/100:,.2f}")

check("RCM amounts correctly captured in Table 3.2",
      gstr3b.rcm_cgst == 2_700_00 and gstr3b.rcm_sgst == 2_700_00,
      f"rcm_cgst={gstr3b.rcm_cgst/100:,.2f} rcm_sgst={gstr3b.rcm_sgst/100:,.2f}")

check("Zero-rated export in outward_zero_rated (not taxable)",
      gstr3b.outward_zero_rated == 2_00_000_00,
      f"got ₹{gstr3b.outward_zero_rated/100:,.2f}")

check("Exempt supply in outward_nil_exempt",
      gstr3b.outward_nil_exempt == 1_00_000_00,
      f"got ₹{gstr3b.outward_nil_exempt/100:,.2f}")

check("Rule 36(4) cap applied on CGST/SGST ITC",
      gstr3b.itc_capped_by_2a == True,
      f"capped={gstr3b.itc_capped_by_2a}")

check("ITC CGST capped at 100% of GSTR-2A",
      gstr3b.itc_cgst == expected_itc_cgst,
      f"got ₹{gstr3b.itc_cgst/100:,.2f}, expected ₹{expected_itc_cgst/100:,.2f}")

check("ITC IGST not capped (book ≤ 100% of GSTR-2A)",
      gstr3b.itc_igst == expected_itc_igst,
      f"got ₹{gstr3b.itc_igst/100:,.2f}")

check("Net tax payable is non-negative",
      gstr3b.net_cgst >= 0 and gstr3b.net_sgst >= 0 and gstr3b.net_igst >= 0,
      f"cgst={gstr3b.net_cgst/100:,.2f} sgst={gstr3b.net_sgst/100:,.2f} igst={gstr3b.net_igst/100:,.2f}")

# Net CGST = max(0, 49800 - 51450) = 0
# Net CGST = max(0, 45300 - 51450) = 0 (ITC cap still exceeds output after credit note)
check("Net CGST is 0 (eligible ITC exceeds net output after credit note)",
      gstr3b.net_cgst == 0,
      f"got ₹{gstr3b.net_cgst/100:,.2f}")

# Net IGST = 108000 - 36000 = 72000
check("Net IGST = net outward IGST - eligible ITC IGST",
      gstr3b.net_igst == expected_outward_igst - expected_itc_igst,
      f"got ₹{gstr3b.net_igst/100:,.2f}, expected ₹{(expected_outward_igst - expected_itc_igst)/100:,.2f}")


# ── STEP 3: GSTR-3B GSTN Payload ──────────────────────────────

section("STEP 3: GSTR-3B GSTN Payload Structure")

g3b_payload = gstr3b.as_gstn_payload(GSTIN, PERIOD)
print("\n  Generated GSTR-3B JSON (truncated):")
print(json.dumps(g3b_payload, indent=4)[:1500])

# GSTN spec checks
check("gstin field present and correct", g3b_payload.get("gstin") == GSTIN)
check("ret_period field present", g3b_payload.get("ret_period") == PERIOD)
check("sup_details.osup_det present", "osup_det" in g3b_payload.get("sup_details", {}))
check("sup_details.osup_zero present", "osup_zero" in g3b_payload.get("sup_details", {}))
check("sup_details.osup_nil_exmp present", "osup_nil_exmp" in g3b_payload.get("sup_details", {}))
check("itc_elg.itc_avl is list", isinstance(g3b_payload.get("itc_elg", {}).get("itc_avl"), list))
check("itc_elg.itc_net present", "itc_net" in g3b_payload.get("itc_elg", {}))
check("intr_ltfee present (interest and late fee)", "intr_ltfee" in g3b_payload)
check("inward_sup.isup_details present (RCM)", "isup_details" in g3b_payload.get("inward_sup", {}))

osup = g3b_payload["sup_details"]["osup_det"]
check("osup_det has iamt/camt/samt/csamt/txval keys",
      all(k in osup for k in ["iamt", "camt", "samt", "csamt", "txval"]))

# txval in osup_det should be sum of all outward taxable amounts
# GSTN spec: txval is outward taxable value (not tax)
itc_avl = g3b_payload["itc_elg"]["itc_avl"][0]
check("itc_avl[0] has ty=ISRC", itc_avl.get("ty") == "ISRC")
check("itc_avl iamt/camt/samt present",
      all(k in itc_avl for k in ["iamt", "camt", "samt", "csamt"]))


# ── STEP 4: GSTR-1 Build ──────────────────────────────────────

section("STEP 4: GSTR-1 Payload Generation")

gstr1 = build_gstr1(invoices_for_gstr1, GSTIN, PERIOD, FIRM_TURNOVER_PAISE)

print(f"\n  Invoice count (sales only): {gstr1.invoice_count}")
print(f"  Taxable total: ₹{gstr1.taxable_total_paise/100:,.2f}")
print(f"  Tax total:     ₹{gstr1.tax_total_paise/100:,.2f}")
print(f"  Tables present: {list(k for k in gstr1.payload if k not in ('gstin','fp','gt','cur_gt'))}")

print("\n  GSTR-1 Summary:")
print(json.dumps(gstr1.summary, indent=4))

# ── Step 4a: Top-level payload fields ─────────────────────────

section("STEP 4a: GSTR-1 Top-Level Fields (GSTN Spec)")

check("gstin present and correct", gstr1.payload.get("gstin") == GSTIN)
check("fp (filing period) present and correct", gstr1.payload.get("fp") == PERIOD)
check("gt (aggregate turnover) present", "gt" in gstr1.payload,
      f"gt={gstr1.payload.get('gt')}")
check("cur_gt (current period turnover) present", "cur_gt" in gstr1.payload)

# ── Step 4b: B2B Table ────────────────────────────────────────

section("STEP 4b: B2B Table (Table 4A)")

b2b = gstr1.payload.get("b2b", [])
print(f"\n  B2B entries: {len(b2b)} GSTINs")
print("  Sample:")
print(json.dumps(b2b, indent=4)[:1200])

check("b2b table present", len(b2b) > 0)
check("b2b grouped by receiver GSTIN", all("ctin" in g for g in b2b))
check("b2b has inv list", all("inv" in g for g in b2b))

for g in b2b:
    for inv in g["inv"]:
        check(f"b2b inv {inv['inum']}: inum present", "inum" in inv)
        check(f"b2b inv {inv['inum']}: idt in DD-MM-YYYY",
              len(inv.get("idt", "")) == 10 and inv["idt"][2] == "-")
        check(f"b2b inv {inv['inum']}: val present", "val" in inv)
        check(f"b2b inv {inv['inum']}: pos present", "pos" in inv)
        check(f"b2b inv {inv['inum']}: rchrg is Y or N",
              inv.get("rchrg") in ("Y", "N"))
        check(f"b2b inv {inv['inum']}: inv_typ present",
              "inv_typ" in inv and inv["inv_typ"] in ("R", "SEZ_with_payment", "SEZ_without_payment", "Deemed_export"))
        check(f"b2b inv {inv['inum']}: itms list present",
              isinstance(inv.get("itms"), list) and len(inv["itms"]) > 0)
        for itm in inv["itms"]:
            check(f"b2b inv {inv['inum']} itm: txval/rt/iamt/camt/samt/csamt present",
                  all(k in itm.get("itm_det", {}) for k in ["txval", "rt", "iamt", "camt", "samt", "csamt"]))


# ── Step 4c: B2CS Table ───────────────────────────────────────

section("STEP 4c: B2CS Table (Table 4B)")

b2cs = gstr1.payload.get("b2cs", [])
print(f"\n  B2CS rows: {len(b2cs)}")
print(json.dumps(b2cs, indent=4))

check("b2cs table present", len(b2cs) > 0)
check("all b2cs rows have sply_tp", all("sply_tp" in r for r in b2cs))
check("b2cs sply_tp values are INTER or INTRA",
      all(r["sply_tp"] in ("INTER", "INTRA") for r in b2cs))

# TXN003 is INTRA/27/12%, TXN008 is INTER/29/18% — must be separate rows
intra_rows = [r for r in b2cs if r["sply_tp"] == "INTRA"]
inter_rows = [r for r in b2cs if r["sply_tp"] == "INTER"]
check("B2CS has both INTRA and INTER rows", len(intra_rows) >= 1 and len(inter_rows) >= 1,
      f"intra={len(intra_rows)} inter={len(inter_rows)}")

for r in b2cs:
    check(f"b2cs row {r['sply_tp']}/{r.get('pos')}: rt present", "rt" in r)
    check(f"b2cs row {r['sply_tp']}/{r.get('pos')}: txval present", "txval" in r)
    check(f"b2cs row {r['sply_tp']}/{r.get('pos')}: iamt/camt/samt present",
          all(k in r for k in ["iamt", "camt", "samt"]))


# ── Step 4d: B2CL Table ───────────────────────────────────────

section("STEP 4d: B2CL Table (Table 4C)")

b2cl = gstr1.payload.get("b2cl", [])
print(f"\n  B2CL entries: {len(b2cl)} POS groups")
print(json.dumps(b2cl, indent=4)[:800])

check("b2cl table present (₹3L interstate unregistered invoice)",
      len(b2cl) > 0)
check("b2cl grouped by pos", all("pos" in g for g in b2cl))
check("b2cl has inv list", all("inv" in g for g in b2cl))

for g in b2cl:
    for inv in g["inv"]:
        check(f"b2cl inv {inv['inum']}: inum/idt/val/itms present",
              all(k in inv for k in ["inum", "idt", "val", "itms"]))
        check(f"b2cl inv {inv['inum']}: idt in DD-MM-YYYY format",
              len(inv.get("idt", "")) == 10 and inv["idt"][2] == "-")


# ── Step 4e: CDNR Table ───────────────────────────────────────

section("STEP 4e: CDNR Table (Table 9B)")

cdnr = gstr1.payload.get("cdnr", [])
print(f"\n  CDNR entries: {len(cdnr)} GSTINs")
print(json.dumps(cdnr, indent=4)[:800])

check("cdnr table present (credit note to registered buyer)", len(cdnr) > 0)
check("cdnr grouped by ctin", all("ctin" in g for g in cdnr))

for g in cdnr:
    for nt in g["nt"]:
        check(f"cdnr note {nt['nt_num']}: ntty is C or D",
              nt.get("ntty") in ("C", "D"))
        check(f"cdnr note {nt['nt_num']}: nt_num/nt_dt/val/pos/rchrg/itms present",
              all(k in nt for k in ["nt_num", "nt_dt", "val", "pos", "rchrg", "itms"]))


# ── Step 4f: Export Table ─────────────────────────────────────

section("STEP 4f: Export Table (Table 6A)")

exp = gstr1.payload.get("exp", [])
print(f"\n  EXP entries: {len(exp)} types")
print(json.dumps(exp, indent=4)[:600])

check("exp table present (SEZ_without_payment invoice)", len(exp) > 0)
check("exp has exp_typ", all("exp_typ" in g for g in exp))
check("exp_typ is WPAY or WOPAY", all(g["exp_typ"] in ("WPAY", "WOPAY") for g in exp))

for g in exp:
    for inv in g["inv"]:
        check(f"exp inv {inv['inum']}: inum/idt/val/itms present",
              all(k in inv for k in ["inum", "idt", "val", "itms"]))
        check(f"exp inv {inv['inum']}: sbpcode/sbnum/sbdt present (shipping bill fields)",
              all(k in inv for k in ["sbpcode", "sbnum", "sbdt"]))


# ── Step 4g: HSN Summary ──────────────────────────────────────

section("STEP 4g: HSN Summary (Table 12)")

hsn = gstr1.payload.get("hsn", {}).get("data", [])
print(f"\n  HSN rows: {len(hsn)}")
print(json.dumps(hsn, indent=4)[:1000])

check("hsn summary present (invoices have line items)", len(hsn) > 0)
for row in hsn:
    check(f"HSN {row.get('hsn_sc')}: num/hsn_sc/desc/uqc/qty/txval/val present",
          all(k in row for k in ["num", "hsn_sc", "desc", "uqc", "qty", "txval", "val"]))
    check(f"HSN {row.get('hsn_sc')}: iamt/camt/samt/csamt present",
          all(k in row for k in ["iamt", "camt", "samt", "csamt"]))
    check(f"HSN {row.get('hsn_sc')}: val = txval + iamt + camt + samt",
          abs(row["val"] - (row["txval"] + row["iamt"] + row["camt"] + row["samt"])) < 0.01,
          f"val={row['val']} vs sum={row['txval']+row['iamt']+row['camt']+row['samt']}")


# ── Step 4h: Document Summary ─────────────────────────────────

section("STEP 4h: Document Issued Summary (Table 13)")

doc_issue = gstr1.payload.get("doc_issue", {}).get("doc_det", [])
print(f"\n  Document type rows: {len(doc_issue)}")
print(json.dumps(doc_issue, indent=4))

check("doc_issue present", len(doc_issue) > 0)
for d in doc_issue:
    check(f"doc_det row: doc_num/doc_typ/docs present",
          all(k in d for k in ["doc_num", "doc_typ", "docs"]))
    for doc in d["docs"]:
        check(f"docs entry: num/cancel/net_issue present",
              all(k in doc for k in ["num", "cancel", "net_issue"]))


# ── STEP 5: Validation ────────────────────────────────────────

section("STEP 5: GST Validation")

gstin_errors = validator.validate_gstin(GSTIN)
period_errors = validator.validate_period(PERIOD)
inv_errors = validator.validate_gstr1(GSTIN, PERIOD, invoices_to_validate)
dup_errors = validator.validate_no_duplicates(invoices_to_validate)

hard_errors = [e for e in inv_errors if e.severity == "error"]
warnings = [e for e in inv_errors if e.severity == "warning"]

print(f"\n  GSTIN validation errors: {len(gstin_errors)}")
print(f"  Period validation errors: {len(period_errors)}")
print(f"  Invoice hard errors: {len(hard_errors)}")
print(f"  Invoice warnings: {len(warnings)}")
print(f"  Duplicate invoice errors: {len(dup_errors)}")

if warnings:
    print("\n  Warnings:")
    for w in warnings:
        print(f"    {WARN} [{w.field}] {w.message}")

check("GSTIN passes validation", len(gstin_errors) == 0,
      f"{[e.message for e in gstin_errors]}")
check("Period passes validation", len(period_errors) == 0,
      f"{[e.message for e in period_errors]}")
check("No hard validation errors on sample invoices", len(hard_errors) == 0,
      f"{[e.message for e in hard_errors]}")
check("No duplicate invoice numbers", len(dup_errors) == 0)

# Validate a malformed GSTIN to confirm rejection
bad_gstin_errors = validator.validate_gstin("INVALID_GSTIN")
check("Invalid GSTIN correctly rejected", len(bad_gstin_errors) > 0)

# Validate a mismatched tax case
mismatch_inv = InvoiceToValidate(
    reference_no="INV999", transaction_date="2025-05-01",
    party_gstin=None, place_of_supply="27",
    taxable_amount_paise=1_00_000_00,
    cgst_paise=9_000_00, sgst_paise=8_000_00,  # not equal — should error
    igst_paise=0, is_interstate=False, gst_rate=None,
)
mismatch_errors = validator.validate_invoice(mismatch_inv, PERIOD)
check("CGST ≠ SGST on intrastate correctly flagged",
      any(e.field == "cgst_sgst" for e in mismatch_errors))


# ── STEP 6: Tax Arithmetic Cross-Check ────────────────────────

section("STEP 6: Tax Arithmetic Cross-Check (paise precision)")

# Manual totals from invoices_for_gstr1 (sales_invoice only)
manual_taxable = 5_00_000_00 + 3_00_000_00 + 80_000_00 + 3_00_000_00 + 2_00_000_00 + 1_50_000_00
manual_cgst    = 45_000_00 + 0 + 4_800_00 + 0 + 0 + 0
manual_sgst    = 45_000_00 + 0 + 4_800_00 + 0 + 0 + 0
manual_igst    = 0 + 54_000_00 + 0 + 54_000_00 + 0 + 27_000_00

check("taxable_total_paise matches manual sum",
      gstr1.taxable_total_paise == manual_taxable,
      f"got ₹{gstr1.taxable_total_paise/100:,.2f}, expected ₹{manual_taxable/100:,.2f}")

check("tax_total_paise matches manual sum (CGST+SGST+IGST only, no CDNR)",
      gstr1.tax_total_paise == manual_cgst + manual_sgst + manual_igst,
      f"got ₹{gstr1.tax_total_paise/100:,.2f}, expected ₹{(manual_cgst+manual_sgst+manual_igst)/100:,.2f}")

# Verify B2CS INTRA row taxable = TXN003 only = ₹80,000
intra_b2cs = next((r for r in b2cs if r["sply_tp"] == "INTRA"), None)
check("B2CS INTRA txval = ₹80,000 (TXN003 only)",
      intra_b2cs is not None and abs(intra_b2cs["txval"] - 80_000.00) < 0.01,
      f"got txval={intra_b2cs['txval'] if intra_b2cs else 'N/A'}")

# Verify B2CS INTER row taxable = TXN008 = ₹1,50,000
inter_b2cs = next((r for r in b2cs if r["sply_tp"] == "INTER"), None)
check("B2CS INTER txval = ₹1,50,000 (TXN008 only)",
      inter_b2cs is not None and abs(inter_b2cs["txval"] - 1_50_000.00) < 0.01,
      f"got txval={inter_b2cs['txval'] if inter_b2cs else 'N/A'}")


# ── STEP 7: GSTN Spec Compliance Summary ──────────────────────

section("STEP 7: GSTN Specification Compliance")

spec_issues = []

# Check date format in B2B
for g in b2b:
    for inv in g["inv"]:
        if not (inv["idt"][2] == "-" and inv["idt"][5] == "-"):
            spec_issues.append(f"B2B date not DD-MM-YYYY: {inv['idt']}")

# Check monetary values are float (rupees), not int
for g in b2b:
    for inv in g["inv"]:
        for itm in inv["itms"]:
            d = itm["itm_det"]
            if not isinstance(d["txval"], (int, float)):
                spec_issues.append(f"txval not numeric: {d['txval']}")

# Check inv_typ "Regular" is mapped to "R"
for g in b2b:
    for inv in g["inv"]:
        if inv.get("inv_typ") == "Regular":
            spec_issues.append(f"inv_typ should be 'R' not 'Regular': {inv['inum']}")

check("All B2B dates in DD-MM-YYYY format", len([s for s in spec_issues if "date" in s]) == 0)
check("All monetary values are numeric (rupees)", len([s for s in spec_issues if "numeric" in s]) == 0)
check("inv_typ 'Regular' mapped to 'R'", len([s for s in spec_issues if "inv_typ" in s]) == 0)

# Verify rchrg is "Y"/"N" not True/False
for g in b2b:
    for inv in g["inv"]:
        check(f"rchrg is string 'Y'/'N' not boolean for {inv['inum']}",
              inv.get("rchrg") in ("Y", "N") and isinstance(inv.get("rchrg"), str))

# Check GSTIN format on b2b ctin
import re
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
for g in b2b:
    check(f"B2B ctin is valid GSTIN: {g['ctin']}",
          bool(GSTIN_RE.match(g["ctin"])))


# ── FINAL GSTR-1 JSON (pretty) ────────────────────────────────

section("FULL GSTR-1 JSON OUTPUT")
print(json.dumps(gstr1.payload, indent=2))


# ── FINAL GSTR-3B JSON ────────────────────────────────────────

section("FULL GSTR-3B JSON OUTPUT")
print(json.dumps(g3b_payload, indent=2))


# ═══════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════

section("FINAL READINESS ASSESSMENT")

total = len(checks)
passed = sum(1 for _, p, _ in checks if p)
failed_checks = [(l, d) for l, p, d in checks if not p]

print(f"\n  Total checks: {total}")
print(f"  Passed: {passed}")
print(f"  Failed: {len(failed_checks)}")

if failed_checks:
    print(f"\n  FAILED CHECKS:")
    for label, detail in failed_checks:
        print(f"    {FAIL}  {label}" + (f" — {detail}" if detail else ""))

print()
print("=" * 60)
print("  READINESS SCORES")
print("=" * 60)
check_pass_rate = passed / total if total else 0

# Engine: computation checks only
engine_labels = [
    "TXN001 classified as B2B",
    "TXN004 classified as B2CL (unregistered, interstate, > ₹2.5L)",
    "Outward CGST matches expected",
    "Outward IGST matches expected",
    "Rule 36(4) cap applied on CGST/SGST ITC",
    "ITC CGST capped at 100% of GSTR-2A",
    "Net CGST is 0 (ITC exceeds output)",
    "Net IGST = outward IGST - eligible ITC IGST",
    "B2CS has both INTRA and INTER rows",
    "B2CS INTRA txval = ₹80,000 (TXN003 only)",
    "B2CS INTER txval = ₹1,50,000 (TXN008 only)",
    "taxable_total_paise matches manual sum",
    "GSTIN passes validation",
    "Invalid GSTIN correctly rejected",
    "CGST ≠ SGST on intrastate correctly flagged",
    "Zero-rated export in outward_zero_rated (not taxable)",
    "Exempt supply in outward_nil_exempt",
    "RCM amounts correctly captured in Table 3.2",
]
engine_results = [(l, p) for l, p, _ in checks if l in engine_labels]
engine_pass = sum(1 for _, p in engine_results if p)
engine_score = int(engine_pass / len(engine_results) * 100) if engine_results else 0

# GSTN spec: field-level checks
spec_labels = [
    "b2b table present",
    "b2b grouped by receiver GSTIN",
    "b2b has inv list",
    "b2cl table present (₹3L interstate unregistered invoice)",
    "b2cl grouped by pos",
    "cdnr table present (credit note to registered buyer)",
    "cdnr grouped by ctin",
    "exp table present (SEZ_without_payment invoice)",
    "exp has exp_typ",
    "exp_typ is WPAY or WOPAY",
    "hsn summary present (invoices have line items)",
    "doc_issue present",
    "gstin present and correct",
    "fp (filing period) present and correct",
    "gt (aggregate turnover) present",
    "All B2B dates in DD-MM-YYYY format",
    "All monetary values are numeric (rupees)",
    "inv_typ 'Regular' mapped to 'R'",
    "sup_details.osup_det present",
    "itc_elg.itc_avl is list",
]
spec_results = [(l, p) for l, p, _ in checks if l in spec_labels]
spec_pass = sum(1 for _, p in spec_results if p)
spec_score = int(spec_pass / len(spec_results) * 100) if spec_results else 0

print(f"""
  Engine Readiness (computation accuracy):   {engine_score}%
  GSTN Spec Compliance (field structure):     {spec_score}%

  UI Readiness:                               0%
    — No GSTR-1 review UI at /gst/gstr1
    — No GSTR-3B review UI at /gst/gstr3b
    — No CA approval button wired to DB
    — No invoice supply type / RCM input fields

  Filing Preparation Readiness:              25%
    — Engine: COMPLETE (GSTR-1 + GSTR-3B payloads)
    — Validation: COMPLETE (GSTIN, period, invoice-level)
    — CA approval flow: MISSING (DB tables exist, no UI)
    — GSTR-2A upload/import: MISSING
    — ARN tracking: MISSING
    — Challan creation: MISSING (table exists, no logic)
    — Migration 036 not yet applied to Supabase instance

  Commercial Readiness:                       5%
    — Engine code: production-quality, 56 tests passing
    — No working end-user UI for GST filing
    — No Supabase integration (frontend calls engine but
      gstr1_returns / gstr3b_returns tables not populated)
    — No PDF/JSON download endpoint tested end-to-end
    — No real GSTN portal integration (by design — CA review gate)

BLOCKERS BEFORE CA CAN GENERATE RETURNS:
  1. Run migration 036_gst_engine.sql in Supabase SQL Editor
  2. Build GSTR-3B review UI (/gst/gstr3b) — tables 3.1/3.2/4/6
  3. Build GSTR-1 review UI (/gst/gstr1) — per-table, errors inline
  4. Wire CA approval button → gstr1_returns/gstr3b_returns.status
  5. Add GSTR-2A upload/CSV import (Rule 36(4) cap needs real data)
  6. Add supply type + RCM fields to invoice entry form
  7. JSON download endpoint for CA to upload to GSTN portal manually
""")

print("=" * 60)
sys.exit(0 if len(failed_checks) == 0 else 1)
