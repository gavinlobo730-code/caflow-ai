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
    B2CS = "B2CS"         # unregistered, intra-state or inter-state at/below the limit
    B2CL = "B2CL"         # unregistered, inter-state above the limit (see below)
    CDNR = "CDNR"         # credit/debit note to registered person
    CDNA = "CDNA"         # credit/debit note to unregistered person
    EXP_WP = "EXP_WP"    # export with payment of IGST — Table 6A
    EXP_WOP = "EXP_WOP"  # export without payment of IGST (LUT/bond) — Table 6A
    # SEZ supplies (Table 6B) and deemed exports (Table 6C) are zero-rated, and
    # they are NOT Table 6A. Their recipient is a registered person with a
    # GSTIN, and the GSTN payload carries them inside the `b2b` section with an
    # inv_typ that says which they are — because the recipient's own return has
    # to match them, and Table 6A has no ctin field at all.
    #
    # Routing them to 6A dropped the recipient GSTIN on the floor. An SEZ unit
    # claiming a refund of the tax under CGST s.16(3), or a deemed-export
    # recipient claiming one under Notification 48/2017-Central Tax, had nothing
    # to match against.
    SEZ_WP = "SEZ_WP"              # SEZ supply with payment of IGST — Table 6B
    SEZ_WOP = "SEZ_WOP"            # SEZ supply under LUT/bond — Table 6B
    DEEMED_EXPORT = "DEEMED_EXPORT"  # Table 6C
    NIL_EXEMPT = "NIL_EXEMPT"  # nil-rated or exempt supplies


# The categories that are filed inside the GSTN `b2b` section. Kept as a set
# rather than tested one at a time, so a new member is added in one place.
B2B_SECTION_CATEGORIES = frozenset({
    GSTInvoiceCategory.B2B,
    GSTInvoiceCategory.SEZ_WP,
    GSTInvoiceCategory.SEZ_WOP,
    GSTInvoiceCategory.DEEMED_EXPORT,
})

# Zero-rated under IGST Act s.16(1): an export, an SEZ supply, and (by
# Notification 48/2017-Central Tax read with s.147) a deemed export.
ZERO_RATED_CATEGORIES = frozenset({
    GSTInvoiceCategory.EXP_WP,
    GSTInvoiceCategory.EXP_WOP,
    GSTInvoiceCategory.SEZ_WP,
    GSTInvoiceCategory.SEZ_WOP,
    GSTInvoiceCategory.DEEMED_EXPORT,
})


# CGST Rule 59(4) — invoice-wise reporting of inter-state supplies to
# unregistered persons (GSTR-1 Table 5).
#
# Notification 12/2024-Central Tax, dated 10 July 2024, substituted "one lakh
# rupees" for "two and a half lakh rupees" wherever they occur in Rule 59(4),
# WITH EFFECT FROM 1 AUGUST 2024. This module carried the old figure, and the
# citation named Rule 59(2), which is a different provision.
#
# The threshold is therefore a function of the invoice's date, not a constant.
# GSTN's own Returns Offline Tool treats it that way too: it holds a limit and
# the period the limit takes effect from (B2CL_MIN / B2CL_MIN_PRD) and picks
# between them per return period.
B2CL_THRESHOLD_PAISE = 1_00_000_00          # Rs 1,00,000 — from 01-08-2024
B2CL_THRESHOLD_LEGACY_PAISE = 2_50_000_00   # Rs 2,50,000 — up to 31-07-2024
B2CL_NEW_THRESHOLD_FROM = "2024-08-01"


def b2cl_threshold_paise(transaction_date: str | None) -> int:
    """The Rule 59(4) limit in force on `transaction_date` (YYYY-MM-DD).

    A missing or unparseable date gets the CURRENT limit. Returns are prepared
    for recent periods; defaulting to the superseded figure would silently
    under-report B2CL on today's filings, which is the failure this function
    exists to end.
    """
    d = (transaction_date or "").strip()[:10]
    if len(d) == 10 and d < B2CL_NEW_THRESHOLD_FROM:
        return B2CL_THRESHOLD_LEGACY_PAISE
    return B2CL_THRESHOLD_PAISE

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
    # Rule 59(4) tests the INVOICE VALUE — taxable value plus every tax head —
    # not the taxable value. GSTN's tool compares the worksheet's "Invoice
    # Value" column. On an 18% supply the two differ by enough to move an
    # invoice between Table 5 and Table 7: taxable Rs 95,000 is an invoice
    # value of Rs 1,12,100, which is B2CL.
    invoice_value_paise: int
    # The threshold changed on 01-08-2024, so classification depends on when
    # the supply was made. YYYY-MM-DD.
    transaction_date: str | None
    # WHETHER A ZERO-RATED SUPPLY WAS MADE ON PAYMENT OF TAX. IGST Act s.16(3)
    # gives two routes: (a) under a letter of undertaking or bond, with no tax
    # charged and the input credit refunded, or (b) on payment of IGST, which
    # is then refunded. Table 6A declares which with exp_typ WPAY or WOPAY.
    #
    # This dataclass carried no tax field at all, so the classifier could not
    # tell them apart and its own comment said "assume no IGST payment (LUT)".
    # An exporter who paid IGST was filed as WOPAY, which asks for a refund of
    # accumulated credit instead of the tax actually paid — the wrong refund,
    # under the wrong rule.
    #
    # Defaulted to 0 so existing callers are unchanged: a caller that does not
    # pass it gets the old behaviour, which is WOPAY.
    igst_paise: int = 0


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

    # ── Zero-rated supplies — IGST Act s.16 ─────────────────────────────────
    #
    # THREE DESTINATIONS, NOT ONE. All of these are zero-rated and every one of
    # them used to be filed as a physical export in Table 6A:
    #
    #   Table 6A  a real export out of India                 exp_typ WPAY/WOPAY
    #   Table 6B  a supply to an SEZ unit or developer       inside b2b, w/ ctin
    #   Table 6C  a deemed export (Notification 48/2017-CT)  inside b2b, w/ ctin
    #
    # 6B and 6C go to a REGISTERED recipient, and the whole point of declaring
    # them is that the recipient's own return matches them — an SEZ unit's
    # s.16(3) refund, or a deemed-export recipient's refund under Notification
    # 48/2017-Central Tax read with s.147. Table 6A has no ctin field, so
    # sending them there dropped the recipient GSTIN entirely.
    #
    # invoice_type is the authority for 6B and 6C because it is an explicit
    # statement about the supply. supply_type "zero_rated" and place of supply
    # "96" describe a physical export.
    if txn.invoice_type == "SEZ_with_payment":
        return GSTInvoiceCategory.SEZ_WP
    if txn.invoice_type == "SEZ_without_payment":
        return GSTInvoiceCategory.SEZ_WOP
    if txn.invoice_type == "Deemed_export":
        # Deemed exports are ALWAYS on payment of tax — Notification
        # 48/2017-Central Tax works by treating the supply as made on payment
        # and refunding it afterwards, to either the supplier or the recipient.
        # There is no LUT route, so there is nothing to detect here.
        return GSTInvoiceCategory.DEEMED_EXPORT

    is_export = (txn.supply_type == "zero_rated"
                 or txn.place_of_supply == EXPORT_PLACE_OF_SUPPLY)
    if is_export:
        # s.16(3): (a) under an LUT or bond, no tax charged; (b) on payment of
        # IGST, refunded afterwards. The invoice says which — it either carries
        # IGST or it does not. This used to be assumed to be (a) always,
        # because the dataclass had no tax field: an exporter who paid IGST was
        # filed as WOPAY, claiming a refund of accumulated credit instead of
        # the tax they actually paid.
        return (GSTInvoiceCategory.EXP_WP if txn.igst_paise > 0
                else GSTInvoiceCategory.EXP_WOP)

    # B2B: supply to any GST-registered person — CGST Act Section 37, Table 4A
    if txn.party_gstin:
        return GSTInvoiceCategory.B2B

    # Unregistered buyer — split B2CS vs B2CL.
    # CGST Rule 59(4): B2CL is an inter-state supply whose INVOICE VALUE exceeds
    # the limit in force on the invoice date. Both halves of that sentence were
    # wrong here: it compared taxable value, against a fixed Rs 2.5 lakh.
    if (txn.is_interstate
            and txn.invoice_value_paise > b2cl_threshold_paise(txn.transaction_date)):
        return GSTInvoiceCategory.B2CL

    return GSTInvoiceCategory.B2CS


def classify_transactions(
    transactions: Sequence[TransactionForClassification],
) -> dict[str, GSTInvoiceCategory]:
    """Classify a batch of transactions. Returns {transaction_id: category}."""
    return {txn.id: classify_transaction(txn) for txn in transactions}
