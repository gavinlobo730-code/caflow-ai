"""What a bank line that carries GST owes the return (BANK-24).

WHAT WAS WRONG
    A CA opens a statement line in the posting drawer, says "there is 18% GST
    inside this ₹590", and `bank_posting_service` posts
    Dr Bank Charges 500 / Dr GST Input 90 / Cr Bank 590. That 90 is input tax
    credit under CGST Act s.16 — a bank charge is an input service received in
    the course or furtherance of business — and it sits in the GST Input
    ledger from that moment.

    GSTR-3B is built from DOCUMENTS. `gst_return_service.gstr3b_from_books`
    assembles Table 4(A) out of purchase bills and the two purchase note
    types, and Table 3.1(a) out of sales invoices and the s.34 notes. A bank
    charge is none of those, so the credit the CA declared never reached the
    return. And because `_gl_gst_movements` DOES read the GST Input account,
    the very same 90 came back on the other side of the books-vs-ledger
    reconciliation as an unexplained ITC difference — every month, on a return
    the CA is about to file under s.39.

    Money IN is the same defect and the worse one. `build_inclusive_lines`
    credits GST Output for an outward supply received straight into the bank,
    so the liability is recognised in the ledger and the return declares none
    of it: tax not paid, with s.50(1) interest running and a s.73 demand
    behind it.

THE DOCUMENT IS THE TRANSACTION, NOT THE JOURNAL
    The reconciliation is only worth reading while its two sides are derived
    independently — the same reason Table 4(B) is built from documents and
    never from the movement on gst_input. Reading the bank side out of
    `journal_lines` would make that slice compare the ledger with itself and
    agree by construction. So this module reads `bank_transactions`, where
    migration 382 records the rate that was POSTED, and the journal stays the
    other side of the check.

WHAT IS DECLARED, AND WHAT IS ONLY NAMED
    A row with a non-zero recorded rate is unambiguous: the CA said this
    amount contains tax at that rate, and the ledger already carries it. It is
    declared.

    A row with a recorded 0, or with none recorded, is NOT declared and must
    not be. Both post exactly the same two legs as an ordinary line, so
    nothing in the ledger distinguishes a nil-rated supply from a loan
    drawdown, a capital contribution or an interest credit — and putting one
    in Table 3.1(c) would assert a fact the books do not hold. Same refusal
    the advance receipt makes about Table 3.2.

    Two things the declaration cannot supply are NAMED on every answer rather
    than guessed:

    * s.16(2)(aa) with Rule 36(4) allows credit only where the supplier's
      invoice has been furnished and communicated in GSTR-2B. A bank charge
      here has no supplier GSTIN and no invoice number — the journal never
      carried one and the matching rule has no field for one — so the credit
      goes on the return (the CA declared it, and the ledger holds it) and the
      answer says it is not corroborated by a 2B document. Inventing a GSTIN
      to make the 2B match work would be worse than the gap.

    * An outward supply declared here has no tax invoice behind it, so GSTR-1
      — which is built from invoices — will not carry it and the portal's own
      3B-vs-1 comparison will differ by exactly this amount. Rule 46 requires
      the invoice; naming the difference is what puts that in front of the CA
      instead of leaving a silent mismatch on the portal.

RULE 36(4) REACHES IT, AND THAT IS RIGHT
    The credit goes into the population the 2A/2B cap is applied to, not
    alongside it. Rule 36(4) sits outside only SELF-ASSESSED reverse-charge
    tax, because that is raised on the recipient's own s.31(3)(f) invoice and
    no supplier furnishes it under s.37(1). A bank charges the tax and files
    it, so the invoice IS furnished — the product simply cannot see which 2B
    row it is. If the CA has uploaded a 2B that contains the bank's invoice
    the cap does not bite; if it does not contain it, s.16(2)(aa) genuinely
    withholds the credit and the cap is the right answer. Either way the
    direction is conservative.

PLACE OF SUPPLY
    Only the head is known (IGST Act s.12(12), stated by the CA — an IFSC does
    not encode a state). There is no recipient state and no recipient class,
    so an outward line reaches Table 3.1(a) and never Table 3.2: that table is
    "of the supplies shown in 3.1(a)" broken down by place of supply and
    recipient, and a bucket built without them would assert what the books do
    not hold. `SalesTransaction` defaults keep it out by construction; this is
    written down so a later edit does not helpfully fill the fields in.

Pure: rows in, figures out, no database handle — the same shape as
`domain/reporting/fixed_asset_movement`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from domain.banking.charge_gst import ChargeSplit, split_inclusive_charge
from domain.money_text import rupees_paise

# The columns this module reads off each row. NOT exported as a projection
# constant: there is exactly one fetch (gst_return_service.
# _bank_lines_declaring_gst) and a select list assembled in Python is invisible
# to test_backend_columns_exist_pg, which is what checks every column name
# against the real schema. The fetch spells them out; that a fetched row
# carries what this module needs is proved end to end, by posting a real
# transaction and reading the return.
_READS = ("id", "transaction_date", "description", "debit_paise",
          "credit_paise", "gst_rate_bps", "gst_is_interstate",
          "posted_journal_id", "category")

_S16_2AA = (
    "Bank-line GST of {tax} is claimed with no supplier invoice or GSTIN "
    "behind it, so nothing here can match it to GSTR-2B. CGST Act s.16(2)(aa) "
    "allows the credit only where the supplier has furnished the invoice and "
    "it has been communicated to the recipient — check it appears in 2B "
    "before filing."
)

_RULE_46 = (
    "Output tax of {tax} is declared from bank receipts that have no tax "
    "invoice behind them. GSTR-1 is built from invoices, so it will not carry "
    "these and the portal's GSTR-1 vs GSTR-3B comparison will differ by this "
    "amount until the invoices are raised (CGST Rule 46)."
)

_NO_HEAD_SPLIT = (
    "No place of supply is recorded for a bank line, so these supplies are in "
    "Table 3.1(a) and not in the Table 3.2 state-wise breakdown."
)


@dataclass(frozen=True)
class DeclaredBankGST:
    """One posted bank line whose amount the CA said contains tax."""
    transaction_id: str
    transaction_date: str
    description: str
    category: str
    # True where the money left the bank: an INWARD supply, whose tax is input
    # credit. False where it arrived: an OUTWARD supply, whose tax is output
    # tax. The direction decides the head, exactly as it does in
    # charge_gst.build_inclusive_lines, and it is the only thing that does.
    is_inward: bool
    split: ChargeSplit


@dataclass(frozen=True)
class BankGSTOnTheReturn:
    """Everything the period's bank lines contribute to GSTR-3B."""
    inward: tuple[DeclaredBankGST, ...]
    outward: tuple[DeclaredBankGST, ...]
    caveats: tuple[str, ...]

    @property
    def itc_paise(self) -> int:
        return sum(d.split.tax_paise for d in self.inward)

    @property
    def inward_taxable_paise(self) -> int:
        return sum(d.split.taxable_paise for d in self.inward)

    @property
    def output_tax_paise(self) -> int:
        return sum(d.split.tax_paise for d in self.outward)

    @property
    def outward_taxable_paise(self) -> int:
        return sum(d.split.taxable_paise for d in self.outward)

    @property
    def is_empty(self) -> bool:
        return not self.inward and not self.outward


def _rupees(paise: int) -> str:
    """A caveat is read by a person, so it says rupees."""
    return f"Rs {rupees_paise(paise)}"


def declared_gst(rows: Iterable[dict]) -> BankGSTOnTheReturn:
    """Split every posted bank line that declares a non-zero GST rate.

    A row is read only if it is POSTED — an unposted line has no journal, so
    the ledger side of the reconciliation has nothing for it either, and
    declaring it would put tax on the return for an entry that is not in the
    books.
    """
    inward: list[DeclaredBankGST] = []
    outward: list[DeclaredBankGST] = []

    for row in rows:
        if not row.get("posted_journal_id"):
            continue
        rate = row.get("gst_rate_bps")
        if rate is None:
            continue
        rate = int(rate)
        if rate == 0:
            # Recorded, and recorded as nil. See the module docstring: the CA
            # saying "no GST in this" is an answer, but it is not a supply
            # classification, so it goes nowhere on the return.
            continue

        debit = int(row.get("debit_paise") or 0)
        credit = int(row.get("credit_paise") or 0)
        gross = max(debit, credit)
        if gross <= 0:
            # split_inclusive_charge refuses a non-positive amount, and rightly
            # — but a return build must not raise on one stray row. A zero-
            # amount line declares nothing either way.
            continue

        is_inward = credit <= 0
        entry = DeclaredBankGST(
            transaction_id=str(row.get("id") or ""),
            transaction_date=str(row.get("transaction_date") or "")[:10],
            description=str(row.get("description") or ""),
            category=str(row.get("category") or ""),
            is_inward=is_inward,
            split=split_inclusive_charge(
                gross, rate, bool(row.get("gst_is_interstate"))),
        )
        (inward if is_inward else outward).append(entry)

    caveats: list[str] = []
    itc = sum(d.split.tax_paise for d in inward)
    out_tax = sum(d.split.tax_paise for d in outward)
    if itc:
        caveats.append(_S16_2AA.format(tax=_rupees(itc)))
    if out_tax:
        caveats.append(_RULE_46.format(tax=_rupees(out_tax)))
        caveats.append(_NO_HEAD_SPLIT)

    return BankGSTOnTheReturn(tuple(inward), tuple(outward), tuple(caveats))
