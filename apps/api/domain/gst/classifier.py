"""Invoice classifier — assigns gst_invoice_category to each transaction.

CGST Act Section 2(6): aggregate turnover definition
CGST Act Section 2(84): registered person definition
CGST Act Section 12/13: place of supply rules
CGST Rule 46: mandatory fields on tax invoice including supply type
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class GSTInvoiceCategory(str, Enum):
    B2B = "B2B"           # supply to registered person (CGST Act §2(84))
    B2CS = "B2CS"         # unregistered, intra-state or inter-state ≤₹2.5L
    B2CL = "B2CL"         # unregistered, inter-state >₹2.5L taxable value
    CDNR = "CDNR"         # credit/debit note to registered person
    CDNA = "CDNA"         # credit/debit note to unregistered person
    EXP_WP = "EXP_WP"    # export with payment of IGST
    EXP_WOP = "EXP_WOP"  # export without payment of IGST (LUT/bond)
    NIL_EXEMPT = "NIL_EXEMPT"  # nil-rated or exempt supplies


# ₹2.5 lakh threshold for B2CL (inter-state unregistered) — CGST Rule 59(2)
B2CL_THRESHOLD_PAISE = 2_50_000_00  # 2,50,000 rupees in paise

# State codes for export detection
EXPORT_PLACE_OF_SUPPLY = "96"  # GSTN uses "96" for outside India


@dataclass(frozen=True)
class TransactionForClassification:
    """Minimal transaction fields needed for invoice classification."""
    id: str
    transaction_type: str       # sales_invoice | credit_note | debit_note
    party_gstin: str | None
    is_interstate: bool
    taxable_amount_paise: int
    supply_type: str            # taxable | zero_rated | nil_rated | exempt | non_gst
    invoice_type: str           # Regular | SEZ_with_payment | SEZ_without_payment | Deemed_export
    place_of_supply: str | None


def classify_transaction(txn: TransactionForClassification) -> GSTInvoiceCategory:
    """Classify a single transaction into its GSTN table category.

    Classification logic follows GSTR-1 instructions issued by CBIC.
    Credit notes (CDNR/CDNA) take priority over invoice type checks.
    Export supplies are detected via invoice_type or place_of_supply.
    """
    # Nil/exempt/non-GST supplies go to NIL_EXEMPT table regardless of buyer
    # CGST Act Section 23 — persons not liable to register (nil/exempt turnover)
    if txn.supply_type in ("nil_rated", "exempt", "non_gst"):
        return GSTInvoiceCategory.NIL_EXEMPT

    # Credit notes and debit notes route to CDNR/CDNA
    if txn.transaction_type in ("credit_note", "debit_note"):
        if txn.party_gstin:
            return GSTInvoiceCategory.CDNR
        return GSTInvoiceCategory.CDNA

    # Export supplies — CGST Act Section 16(1)(a) — zero-rated supplies
    is_export = (
        txn.supply_type == "zero_rated"
        or txn.invoice_type in ("SEZ_with_payment", "SEZ_without_payment", "Deemed_export")
        or txn.place_of_supply == EXPORT_PLACE_OF_SUPPLY
    )
    if is_export:
        # With payment of IGST vs without (LUT/Bond) — CGST Act Section 16(3)
        # SEZ_without_payment takes precedence — invoice_type is explicit; supply_type alone
        # (zero_rated) is insufficient to infer payment, so default to WOPAY (conservative).
        if txn.invoice_type == "SEZ_without_payment":
            return GSTInvoiceCategory.EXP_WOP
        if txn.invoice_type == "SEZ_with_payment":
            return GSTInvoiceCategory.EXP_WP
        # Regular exports: zero_rated + place_of_supply=="96"; assume no IGST payment (LUT)
        return GSTInvoiceCategory.EXP_WOP

    # B2B: supply to any GST-registered person — CGST Act Section 37, Table 4A
    if txn.party_gstin:
        return GSTInvoiceCategory.B2B

    # Unregistered buyer — split B2CS vs B2CL
    # CGST Rule 59(2): B2CL applies to inter-state invoice with taxable value >₹2.5L
    if txn.is_interstate and txn.taxable_amount_paise > B2CL_THRESHOLD_PAISE:
        return GSTInvoiceCategory.B2CL

    return GSTInvoiceCategory.B2CS


def classify_transactions(
    transactions: Sequence[TransactionForClassification],
) -> dict[str, GSTInvoiceCategory]:
    """Classify a batch of transactions. Returns {transaction_id: category}."""
    return {txn.id: classify_transaction(txn) for txn in transactions}
