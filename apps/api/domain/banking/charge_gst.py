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


def build_inclusive_lines(split: ChargeSplit, *, bank_account_id: str,
                          counter_account_id: str, is_credit: bool = False,
                          cgst_account_id: str | None = None,
                          sgst_account_id: str | None = None,
                          igst_account_id: str | None = None) -> list[dict]:
    """Journal lines for a tax-inclusive amount that crossed the bank.

    Money OUT — an inward supply the client PAID for. The tax is input credit
    under s.16 of the CGST Act, so it is DEBITED to the GST Input asset:

        Dr  <expense>           (taxable)
        Dr  GST Input CGST/SGST (the tax)      intra-state
        Dr  GST Input IGST      (the tax)      inter-state
            Cr  Bank                           (the gross debited)

    Money IN — an outward supply the client MADE. The tax is output tax under
    s.9 of the CGST Act (s.5 of the IGST Act inter-state): it is a LIABILITY
    the client now owes the government, so it is CREDITED to GST Output:

        Dr  Bank                (the gross received)
            Cr  <income>                       (taxable)
            Cr  GST Output CGST/SGST           (the tax)      intra-state
            Cr  GST Output IGST                (the tax)      inter-state

    The arithmetic is identical in both directions — split_inclusive_charge
    does not care which way the money went. What differs is which ACCOUNTS the
    tax lands on, and that difference is the whole point: putting output tax on
    the input-credit asset would claim ITC on a sale, which is why the two
    directions cannot share an account list even though they share the maths.
    """
    if not bank_account_id or not counter_account_id:
        raise ValueError("Both the bank and the counter account are required.")

    side = "Output" if is_credit else "Input"
    # CGST Act s.9 levies the tax on an outward supply; s.16 grants the credit
    # on an inward one. Both are stated on the line so the ledger explains
    # itself without the reader going back to the bank statement.
    section = "CGST Act s.9" if is_credit else "CGST Act s.16"

    def leg(account_id: str, amount: int, narration: str) -> dict:
        """One non-bank leg. It moves opposite to the bank: money into the bank
        is a debit there, so everything else on the entry is a credit."""
        return {
            "account_id": account_id,
            "debit_paise": 0 if is_credit else amount,
            "credit_paise": amount if is_credit else 0,
            "narration": narration,
        }

    lines = [leg(counter_account_id, split.taxable_paise,
                 "Receipt excluding GST" if is_credit else "Bank charges")]

    if split.is_interstate and split.igst_paise:
        if not igst_account_id:
            raise ValueError(f"An IGST {side.lower()} account is required for an inter-state amount.")
        lines.append(leg(igst_account_id, split.igst_paise,
                         f"{side} IGST ({section})"))
    elif not split.is_interstate and (split.cgst_paise or split.sgst_paise):
        if not cgst_account_id or not sgst_account_id:
            raise ValueError(f"CGST and SGST {side.lower()} accounts are required for an intra-state amount.")
        lines.append(leg(cgst_account_id, split.cgst_paise, f"{side} CGST ({section})"))
        lines.append(leg(sgst_account_id, split.sgst_paise, f"{side} SGST ({section})"))

    lines.append({
        "account_id": bank_account_id,
        "debit_paise": split.gross_paise if is_credit else 0,
        "credit_paise": 0 if is_credit else split.gross_paise,
        "narration": "Received into bank" if is_credit else "Bank charge debited",
    })

    # Cheap structural guarantee rather than trust: the split is exact by
    # construction, so a mismatch here means the line builder was edited wrongly.
    total_dr = sum(l["debit_paise"] for l in lines)
    total_cr = sum(l["credit_paise"] for l in lines)
    if total_dr != total_cr:
        raise ValueError(f"Inclusive-GST lines do not balance: {total_dr} vs {total_cr}")
    return lines


def build_charge_lines(split: ChargeSplit, *, bank_account_id: str,
                       expense_account_id: str, cgst_account_id: str | None = None,
                       sgst_account_id: str | None = None,
                       igst_account_id: str | None = None) -> list[dict]:
    """A bank CHARGE — money out, input credit. The named case of the above.

    Kept as its own name because "bank charge" is what the docs and the screen
    call it, but it DELEGATES: one implementation of the line shape, so the two
    directions cannot drift apart.
    """
    return build_inclusive_lines(
        split, bank_account_id=bank_account_id, counter_account_id=expense_account_id,
        is_credit=False, cgst_account_id=cgst_account_id,
        sgst_account_id=sgst_account_id, igst_account_id=igst_account_id)
