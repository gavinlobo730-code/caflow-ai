"""What an invoice DECLARES about a supply has to match the tax it carries.

SALES-16. `_create_invoice_core` computes GST from `gst_rate_bps` and
`is_interstate` alone. `supply_type` and `is_reverse_charge` are stored and
never consulted, so a CA can tick "Exempt" — or "Reverse charge" — and leave the
lines at 18%. Both things then happen:

  * the invoice posts CGST/SGST Output to the ledger and the customer is
    charged the tax;
  * `gstr1_builder._build_nil_exempt` reports a nil/exempt/non-GST supply as
    `nil_amt`/`expt_amt`/`ngsup_amt` — the TAXABLE VALUE only, with the tax
    heads silently dropped — and a reverse-charge B2B row goes out with
    `rchrg: "Y"`, which tells the portal the RECIPIENT owes the tax.

So the books declare output tax the return does not, by the whole amount, and
nothing says so until somebody reconciles. On reverse charge it is worse than a
mismatch: the supplier has collected tax from a customer who is simultaneously
being told by the portal that they must pay it themselves.

THE STATUTE, because these are two different rules that happen to have the same
remedy:

  * §2(47) defines an exempt supply as one attracting a nil rate or wholly
    exempt under §11 or IGST §6, and §2(78) a non-taxable supply as one not
    leviable at all. Charging 18% on a supply the invoice says is one of those
    is charging tax on something the document itself declares untaxable.
  * §9(3) and §9(4) shift the liability to the recipient, and Rule 46(p)
    requires the invoice to carry "tax payable on reverse charge basis". The
    supplier does not charge the tax — that IS the mechanism.

ZERO-RATED IS DELIBERATELY NOT HERE. §16(3) gives an exporter or SEZ supplier a
CHOICE: supply under an LUT or bond and charge nothing (§16(3)(a)), or supply on
payment of IGST and claim it back under §54 (§16(3)(b)). A zero-rated invoice
carrying IGST is the second option and is entirely correct, so refusing it would
refuse a lawful export. `gstr3b_computer` already carries this distinction and
says the same thing.
"""
from __future__ import annotations

#: Supply types the invoice can declare, per migration 268's CHECK.
#: These three assert that no tax is chargeable on the supply.
UNTAXED_SUPPLY_TYPES = frozenset({"nil_rated", "exempt", "non_gst"})

_LABEL = {
    "nil_rated": "nil-rated",
    "exempt":    "exempt",
    "non_gst":   "non-GST",
}


def tax_conflict(
    *,
    supply_type: str | None,
    is_reverse_charge: bool | None,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    igst_paise: int = 0,
    cess_paise: int = 0,
) -> str | None:
    """The reason this document's tax contradicts its own classification, or None.

    Returns a sentence a CA can act on rather than a boolean: the two causes
    have different remedies (change the rate, or change the classification) and
    which applies depends on what the CA meant.
    """
    tax = int(cgst_paise or 0) + int(sgst_paise or 0) + int(igst_paise or 0) \
        + int(cess_paise or 0)
    if tax <= 0:
        return None

    stype = (supply_type or "taxable").strip().lower()

    if stype in UNTAXED_SUPPLY_TYPES:
        return (
            f"This invoice is classified as a {_LABEL[stype]} supply but carries "
            f"₹{tax / 100:,.2f} of GST. A {_LABEL[stype]} supply attracts no tax "
            f"(CGST §2(47)/§2(78)), and GSTR-1 reports it as value only — so the "
            f"tax would be charged to the customer and posted to the ledger while "
            f"the return declared none. Either set the line rates to 0% or change "
            f"the supply type to Taxable."
        )

    if is_reverse_charge:
        return (
            f"This invoice is marked as reverse charge but carries ₹{tax / 100:,.2f} "
            f"of GST. Under CGST §9(3)/(4) the RECIPIENT pays the tax — Rule 46(p) "
            f"requires the invoice to say so and the supplier does not charge it. "
            f"GSTR-1 would report this as rchrg=Y, telling the portal the customer "
            f"owes tax you have already collected from them. Either set the line "
            f"rates to 0% or untick reverse charge."
        )

    return None
