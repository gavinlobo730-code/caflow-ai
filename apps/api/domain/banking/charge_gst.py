"""
GST on bank charges — splitting a tax-INCLUSIVE bank debit (Banking B.3).

WHY THIS IS ITS OWN CALCULATION
    Every other GST split in this codebase works forward: a taxable value is
    known and the tax is computed ON it (domain/gst, _compute_line_gst). A bank
    charge arrives the other way round. The statement says one number — ₹590 —
    and that number is already inclusive of tax. The taxable value has to be
    backed OUT of it.

    Doing that with the forward helper would be wrong in a way that is easy to
    miss: 590 × 18% = 106.20, so you would book ₹590 of expense and ₹106.20 of
    input credit against a ₹590 payment, and the entry would not balance. The
    correct split is ₹500 + ₹90.

WHY IT MATTERS
    Bank charges are the most repetitive line on an Indian statement, they carry
    GST, and that GST is input tax credit under s.16 of the CGST Act, 2017 —
    a bank charge is an input service received in the course or furtherance of
    business. Booking the gross ₹590 to an expense account, which is what
    happens today, throws the credit away every single month.

PLACE OF SUPPLY
    Section 12(12) of the IGST Act, 2017: for banking and other financial
    services the place of supply is the location of the RECIPIENT on the
    supplier's records. So an account held with a branch in the client's own
    state is an intra-state supply (CGST + SGST); a bank registered in another
    state supplying the same service is inter-state (IGST).

    That fact is NOT inferred here. An IFSC does not encode a state, and
    guessing the tax head on a statutory credit is exactly the kind of thing this
    codebase refuses to do — the caller states it, and a matching rule can carry
    the answer so it is stated once per bank rather than once per charge.

Integer paise throughout, and the split is EXACT by construction: taxable + tax
always equals the gross the bank actually debited, so the journal balances
without a rounding plug.
"""
from __future__ import annotations

from dataclasses import dataclass

# GST rates a bank charge can realistically carry. Banking services are taxable
# at 18% (Notification 11/2017-CTR, as amended); 0 means the charge carries no
# GST at all, which some do (interest, certain government levies). Anything else
# is a typo, and a typo in a tax head becomes a wrong GSTR-3B.
ALLOWED_RATES_BPS: tuple[int, ...] = (0, 500, 1200, 1800, 2800)


@dataclass(frozen=True)
class ChargeSplit:
    """A bank charge broken into its taxable value and tax heads.

    `taxable_paise + cgst_paise + sgst_paise + igst_paise == gross_paise`,
    always. Exactly one of (cgst+sgst) / igst is non-zero.
    """
    gross_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    rate_bps: int
    is_interstate: bool

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def has_gst(self) -> bool:
        return self.tax_paise > 0


def split_inclusive_charge(gross_paise: int, rate_bps: int,
                           is_interstate: bool = False) -> ChargeSplit:
    """Back the taxable value out of a tax-inclusive bank charge.

        taxable = gross × 10000 ÷ (10000 + rate_bps)      [floor]
        tax     = gross − taxable                          [the remainder]

    The tax is the REMAINDER rather than a second independent computation. That
    is what makes the split exact: any rounding loss lands in the tax figure and
    the two still sum to what the bank actually took, so the journal balances
    with no adjustment line. Computing both independently would leave a
    one-paise hole roughly half the time.

    Intra-state tax is halved into CGST and SGST with the odd paise going to
    SGST — the same convention as _compute_line_gst on the sales side, so the
    two halves of the system round the same way.
    """
    gross = int(gross_paise)
    rate = int(rate_bps)
    if gross <= 0:
        raise ValueError("A bank charge must be a positive amount.")
    if rate not in ALLOWED_RATES_BPS:
        raise ValueError(
            f"Unsupported GST rate {rate} bps. Allowed: "
            + ", ".join(str(r) for r in ALLOWED_RATES_BPS))

    if rate == 0:
        return ChargeSplit(gross, gross, 0, 0, 0, 0, bool(is_interstate))

    taxable = (gross * 10000) // (10000 + rate)
    tax = gross - taxable

    if is_interstate:
        return ChargeSplit(gross, taxable, 0, 0, tax, rate, True)

    cgst = tax // 2
    sgst = tax - cgst          # odd paise to SGST, matching the sales-side split
    return ChargeSplit(gross, taxable, cgst, sgst, 0, rate, False)


def build_charge_lines(split: ChargeSplit, *, bank_account_id: str,
                       expense_account_id: str, cgst_account_id: str | None = None,
                       sgst_account_id: str | None = None,
                       igst_account_id: str | None = None) -> list[dict]:
    """Journal lines for a bank charge, GST separated out.

        Dr  Bank Charges        (taxable)
        Dr  GST Input – CGST    (half the tax)      intra-state
        Dr  GST Input – SGST    (the other half)    intra-state
        Dr  GST Input – IGST    (all the tax)       inter-state
            Cr  Bank            (the gross debited)

    Money OUT of the bank only: a bank CHARGE is by definition a debit. A refund
    of charges is a credit and goes through the ordinary two-line path — reversing
    these signs would silently book negative input credit.
    """
    if not bank_account_id or not expense_account_id:
        raise ValueError("Both the bank and the charge expense account are required.")

    lines = [{
        "account_id": expense_account_id,
        "debit_paise": split.taxable_paise, "credit_paise": 0,
        "narration": "Bank charges",
    }]

    if split.is_interstate and split.igst_paise:
        if not igst_account_id:
            raise ValueError("An IGST input account is required for an inter-state charge.")
        lines.append({
            "account_id": igst_account_id,
            "debit_paise": split.igst_paise, "credit_paise": 0,
            "narration": "Input IGST on bank charges (CGST Act s.16)",
        })
    elif not split.is_interstate and (split.cgst_paise or split.sgst_paise):
        if not cgst_account_id or not sgst_account_id:
            raise ValueError("CGST and SGST input accounts are required for an intra-state charge.")
        lines.append({
            "account_id": cgst_account_id,
            "debit_paise": split.cgst_paise, "credit_paise": 0,
            "narration": "Input CGST on bank charges (CGST Act s.16)",
        })
        lines.append({
            "account_id": sgst_account_id,
            "debit_paise": split.sgst_paise, "credit_paise": 0,
            "narration": "Input SGST on bank charges (CGST Act s.16)",
        })

    lines.append({
        "account_id": bank_account_id,
        "debit_paise": 0, "credit_paise": split.gross_paise,
        "narration": "Bank charge debited",
    })

    # Cheap structural guarantee rather than trust: the split is exact by
    # construction, so a mismatch here means the line builder was edited wrongly.
    total_dr = sum(l["debit_paise"] for l in lines)
    total_cr = sum(l["credit_paise"] for l in lines)
    if total_dr != total_cr:
        raise ValueError(f"Bank charge lines do not balance: {total_dr} vs {total_cr}")
    return lines
