"""GSTR-3B computation engine.

CGST Act Section 39 — furnishing of returns.
CGST Rule 36(4) — ITC restricted to 105% of eligible GSTR-2A credit.
CGST Act Section 49 — payment of tax, interest, penalty and fee.

All amounts are integer paise. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class SalesTransaction:
    """Posted sales invoice or credit/debit note fields for GSTR-3B."""
    transaction_type: str
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    supply_type: str       # taxable | zero_rated | nil_rated | exempt | non_gst
    is_reverse_charge: bool


@dataclass(frozen=True)
class PurchaseTransaction:
    """Posted purchase invoice fields for ITC computation."""
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    is_reverse_charge: bool


@dataclass(frozen=True)
class GSTR2ARecord:
    """Supplier-filed invoice from GSTR-2A."""
    cgst_paise: int
    sgst_paise: int
    igst_paise: int


@dataclass
class GSTR3BResult:
    """Computed GSTR-3B values — all amounts in paise."""

    # Table 3.1: Outward supplies (CGST Act Section 37)
    outward_taxable_igst: int = 0
    outward_taxable_cgst: int = 0
    outward_taxable_sgst: int = 0
    outward_taxable_cess: int = 0
    outward_zero_rated: int = 0      # zero-rated (export) taxable value
    outward_nil_exempt: int = 0      # nil-rated + exempt taxable value

    # Table 3.2: Inward supplies on reverse charge (CGST Act Section 9(3), 9(4))
    rcm_igst: int = 0
    rcm_cgst: int = 0
    rcm_sgst: int = 0

    # Table 4: ITC available
    itc_igst: int = 0
    itc_cgst: int = 0
    itc_sgst: int = 0
    itc_cess: int = 0

    # ITC working — raw figures before Rule 36(4) cap
    itc_book_igst: int = 0
    itc_book_cgst: int = 0
    itc_book_sgst: int = 0
    itc_2a_igst: int = 0
    itc_2a_cgst: int = 0
    itc_2a_sgst: int = 0
    itc_capped_by_2a: bool = False   # True if Rule 36(4) cap was applied

    # Table 6: Net tax payable
    net_igst: int = 0
    net_cgst: int = 0
    net_sgst: int = 0
    net_cess: int = 0

    def as_gstn_payload(self, gstin: str, period: str) -> dict:
        """Return GSTN-compatible GSTR-3B JSON.

        Format follows GSTN API specification v1.3.
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        """
        return {
            "gstin": gstin,
            "ret_period": period,
            "inward_sup": {
                "isup_details": [
                    {
                        "ty": "RCM",
                        "inter": self.rcm_igst,
                        "intra_cgst": self.rcm_cgst,
                        "intra_sgst": self.rcm_sgst,
                    }
                ]
            },
            "sup_details": {
                "osup_det": {
                    "txval": self.outward_taxable_igst + self.outward_taxable_cgst + self.outward_taxable_sgst,
                    "iamt": self.outward_taxable_igst,
                    "camt": self.outward_taxable_cgst,
                    "samt": self.outward_taxable_sgst,
                    "csamt": self.outward_taxable_cess,
                },
                "osup_zero": {
                    "txval": self.outward_zero_rated,
                    "iamt": 0, "camt": 0, "samt": 0, "csamt": 0,
                },
                "osup_nil_exmp": {
                    "txval": self.outward_nil_exempt,
                },
                "isup_rev": {
                    "txval": 0,
                    "iamt": self.rcm_igst,
                    "camt": self.rcm_cgst,
                    "samt": self.rcm_sgst,
                    "csamt": 0,
                },
                "osup_nongst": {"txval": 0},
            },
            "itc_elg": {
                "itc_avl": [
                    {
                        "ty": "ISRC",       # inputs, inputs services, capital goods combined
                        "iamt": self.itc_igst,
                        "camt": self.itc_cgst,
                        "samt": self.itc_sgst,
                        "csamt": self.itc_cess,
                    }
                ],
                "itc_rev": [],
                "itc_net": {
                    "iamt": self.itc_igst,
                    "camt": self.itc_cgst,
                    "samt": self.itc_sgst,
                    "csamt": self.itc_cess,
                },
                "itc_inelg": [],
            },
            "intr_ltfee": {
                "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
                "fee_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            },
        }


# CGST Rule 36(4): eligible ITC capped at 105% of GSTR-2A credit
# Multiplied by 105 and divided by 100 using integer arithmetic to avoid float
_RULE_36_4_NUMERATOR = 105
_RULE_36_4_DENOMINATOR = 100


def _apply_rule_36_4_cap(book: int, gstr2a: int) -> tuple[int, bool]:
    """Return (capped_itc, was_capped) using integer paise arithmetic.

    CGST Rule 36(4): ITC cannot exceed 105% of eligible GSTR-2A credit.
    If GSTR-2A is zero (no records uploaded), book ITC is used as-is.
    """
    if gstr2a == 0:
        # No GSTR-2A data — use book ITC; warn CA to upload GSTR-2A
        return book, False
    cap = (gstr2a * _RULE_36_4_NUMERATOR) // _RULE_36_4_DENOMINATOR
    if book > cap:
        return cap, True
    return book, False


def compute_gstr3b(
    sales: Sequence[SalesTransaction],
    purchases: Sequence[PurchaseTransaction],
    gstr2a_records: Sequence[GSTR2ARecord],
) -> GSTR3BResult:
    """Compute GSTR-3B figures from transaction data.

    Args:
        sales: Posted sales invoices and credit/debit notes for the period.
        purchases: Posted purchase invoices for the period.
        gstr2a_records: Supplier-filed records from GSTR-2A for the period.

    Returns:
        GSTR3BResult with all table values computed in paise.
    """
    result = GSTR3BResult()

    # ── Table 3.1: Outward supplies ──────────────────────────────────────────
    for s in sales:
        if s.supply_type in ("nil_rated", "exempt"):
            result.outward_nil_exempt += s.taxable_amount_paise
        elif s.supply_type == "zero_rated":
            result.outward_zero_rated += s.taxable_amount_paise
        elif s.supply_type == "taxable":
            if not s.is_reverse_charge:
                result.outward_taxable_igst += s.igst_paise
                result.outward_taxable_cgst += s.cgst_paise
                result.outward_taxable_sgst += s.sgst_paise
                result.outward_taxable_cess += s.cess_paise

    # ── Table 3.2: Reverse charge inward supplies ────────────────────────────
    for s in sales:
        if s.is_reverse_charge:
            result.rcm_igst += s.igst_paise
            result.rcm_cgst += s.cgst_paise
            result.rcm_sgst += s.sgst_paise

    # ── Table 4: ITC available ───────────────────────────────────────────────
    book_igst = sum(p.igst_paise for p in purchases)
    book_cgst = sum(p.cgst_paise for p in purchases)
    book_sgst = sum(p.sgst_paise for p in purchases)
    book_cess = sum(p.cess_paise for p in purchases)

    # Add RCM tax paid as ITC — CGST Act Section 9(3) ITC available on RCM
    book_igst += sum(p.igst_paise for p in purchases if p.is_reverse_charge)
    book_cgst += sum(p.cgst_paise for p in purchases if p.is_reverse_charge)
    book_sgst += sum(p.sgst_paise for p in purchases if p.is_reverse_charge)

    gstr2a_igst = sum(r.igst_paise for r in gstr2a_records)
    gstr2a_cgst = sum(r.cgst_paise for r in gstr2a_records)
    gstr2a_sgst = sum(r.sgst_paise for r in gstr2a_records)

    itc_igst, capped_i = _apply_rule_36_4_cap(book_igst, gstr2a_igst)
    itc_cgst, capped_c = _apply_rule_36_4_cap(book_cgst, gstr2a_cgst)
    itc_sgst, capped_s = _apply_rule_36_4_cap(book_sgst, gstr2a_sgst)

    result.itc_book_igst = book_igst
    result.itc_book_cgst = book_cgst
    result.itc_book_sgst = book_sgst
    result.itc_2a_igst = gstr2a_igst
    result.itc_2a_cgst = gstr2a_cgst
    result.itc_2a_sgst = gstr2a_sgst
    result.itc_igst = itc_igst
    result.itc_cgst = itc_cgst
    result.itc_sgst = itc_sgst
    result.itc_cess = book_cess
    result.itc_capped_by_2a = capped_i or capped_c or capped_s

    # ── Table 6: Net tax payable ─────────────────────────────────────────────
    # CGST Act Section 49: IGST credit first against IGST, then CGST, then SGST
    igst_after_itc = result.outward_taxable_igst - itc_igst

    if igst_after_itc <= 0:
        # Excess IGST ITC — offset against CGST and SGST (Section 49(5))
        excess_igst_itc = abs(igst_after_itc)
        half_excess = excess_igst_itc // 2
        result.net_igst = 0
        result.net_cgst = max(0, result.outward_taxable_cgst - itc_cgst - half_excess)
        result.net_sgst = max(0, result.outward_taxable_sgst - itc_sgst - (excess_igst_itc - half_excess))
    else:
        result.net_igst = igst_after_itc
        result.net_cgst = max(0, result.outward_taxable_cgst - itc_cgst)
        result.net_sgst = max(0, result.outward_taxable_sgst - itc_sgst)

    result.net_cess = max(0, result.outward_taxable_cess - result.itc_cess)

    return result
