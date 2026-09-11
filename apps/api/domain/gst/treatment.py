"""One vocabulary for "what kind of supply is this", derived from the invoice.

SALES-19. The treatment of a supply was captured TWICE, in two vocabularies
that could disagree:

  * the INVOICE carries `supply_type` (taxable | zero_rated | nil_rated |
    exempt | non_gst) and `invoice_type` (Regular | SEZ_with_payment |
    SEZ_without_payment | Deemed_export), migration 268. This pair is what
    GSTR-1 is built from — `domain/gst/classifier.classify_transaction` reads
    it and nothing else.
  * the E-INVOICE RECORD carries `gst_treatment` (regular |
    export_with_payment | export_without_payment | sez_with_payment |
    sez_without_payment | deemed_export), captured independently when a CA
    prepares an IRN, and described by its own service as "metadata on this
    record only — never fed into tax/journal math".

The Compliance panel read only the SECOND. So a CA who marked an invoice
`zero_rated` / `SEZ_without_payment` — the fields the return actually uses —
was shown "Regular" on the compliance screen until somebody also prepared an
e-invoice record, and if they prepared one saying something else, the screen
showed that instead of what would be filed.

WHICH ONE WINS IS NOT ARBITRARY. The invoice's pair is what reaches the return,
so it is the source and this module derives the treatment from it. The
e-invoice record's `gst_treatment` stays what it always was — a note on that
record — and is displayed only where the invoice itself says nothing, which is
never now that this function always answers.

THE EXPORT SPLIT IS A REAL STATUTORY DISTINCTION, not a label. IGST §16(3)
gives a zero-rated supplier two routes: (a) under a letter of undertaking or
bond, charging no tax and reclaiming the input credit, or (b) on payment of
IGST, which is then refunded under §54. GSTR-1 Table 6A declares which with
`exp_typ` WPAY or WOPAY, and asking for the wrong one asks for the wrong
refund under the wrong rule. The tax actually charged is what tells them
apart, which is why this takes `igst_paise` — the same evidence
`classifier.TransactionForClassification` uses for the same decision.
"""
from __future__ import annotations

from typing import Optional

#: The e-invoice record's vocabulary, which is the one the screens speak.
REGULAR = "regular"
EXPORT_WITH_PAYMENT = "export_with_payment"
EXPORT_WITHOUT_PAYMENT = "export_without_payment"
SEZ_WITH_PAYMENT = "sez_with_payment"
SEZ_WITHOUT_PAYMENT = "sez_without_payment"
DEEMED_EXPORT = "deemed_export"

TREATMENTS = frozenset({
    REGULAR, EXPORT_WITH_PAYMENT, EXPORT_WITHOUT_PAYMENT,
    SEZ_WITH_PAYMENT, SEZ_WITHOUT_PAYMENT, DEEMED_EXPORT,
})

#: invoice_type → treatment, where the invoice type alone settles it.
_BY_INVOICE_TYPE = {
    "sez_with_payment":    SEZ_WITH_PAYMENT,
    "sez_without_payment": SEZ_WITHOUT_PAYMENT,
    "deemed_export":       DEEMED_EXPORT,
}


def treatment_for_invoice(
    *,
    supply_type: Optional[str],
    invoice_type: Optional[str],
    igst_paise: int = 0,
) -> str:
    """The supply's treatment, in the vocabulary the compliance screens use."""
    itype = (invoice_type or "Regular").strip().lower()
    mapped = _BY_INVOICE_TYPE.get(itype)
    if mapped:
        return mapped

    stype = (supply_type or "taxable").strip().lower()
    if stype == "zero_rated":
        # IGST §16(3): (b) on payment of IGST, refunded under §54; (a) under an
        # LUT or bond, with nothing charged. The tax on the document is the
        # evidence — Table 6A's exp_typ turns on exactly this.
        return EXPORT_WITH_PAYMENT if int(igst_paise or 0) > 0 else EXPORT_WITHOUT_PAYMENT

    # nil_rated, exempt, non_gst and taxable are all ordinary domestic supplies
    # as far as THIS vocabulary is concerned — it distinguishes export and SEZ
    # routes, not rates. What they are instead is carried by supply_type, which
    # the return reads directly.
    return REGULAR
