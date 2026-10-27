"""The sentences the rupee sweep converted, and the four it found wrong while converting them, each say what is true.

`tests/test_a_sentence_written_for_a_person_names_rupees_and_never_a_count_of_paise.py` holds the RULE (no module prints a count of
paise) and the helpers. This file drives the sentences the rule cannot see, because their wording was wrong rather than their unit:

    * the ITC matcher said "the bill claims ₹0.00 less tax than GSTR-2B carries" for a pair whose tax agrees and whose taxable value
      does not, naming a difference that is not there;
    * the ITC register's refusals said "The journal gives back minus ₹90.00 of input tax" when the journal TAKES credit;
    * a foreign document's over-allocation and unbalanced-total sentences named a dollar amount as rupees (or as a bare count of
      minor units), where the currency is the one fact the sentence has;
    * a trial balance's negative-amount refusal printed a bare "(-500000)" beside sentences that now say rupees.
"""
import pytest

from domain.gst.itc_matching import BookBill, PortalDocument, reconcile
from domain.money_sentence import amount_text


# ── ITC matcher ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _bill(taxable, cgst, sgst):
    return BookBill(bill_id="b1", supplier_gstin="27AABCU9603R1ZM", bill_no="INV/1", bill_date="2026-06-01", taxable_paise=taxable,
                    igst_paise=0, cgst_paise=cgst, sgst_paise=sgst, supplier_name="Acme") if "supplier_name" in BookBill.__dataclass_fields__ \
        else BookBill(bill_id="b1", supplier_gstin="27AABCU9603R1ZM", bill_no="INV/1", bill_date="2026-06-01", taxable_paise=taxable,
                      igst_paise=0, cgst_paise=cgst, sgst_paise=sgst)


def _doc(taxable, cgst, sgst):
    return PortalDocument(section="b2b", document_type="invoice", supplier_gstin="27AABCU9603R1ZM", supplier_name="Acme",
                          document_number="INV/1", document_date="2026-06-01", taxable_paise=taxable, igst_paise=0,
                          cgst_paise=cgst, sgst_paise=sgst, cess_paise=0, itc_available="Y")


def _mismatch(bill, doc):
    result = reconcile([bill], [doc])
    return next(m for m in result.matches if m.status == "amount_mismatch")


def test_a_pair_whose_tax_agrees_and_whose_taxable_value_differs_names_the_taxable_value_and_no_tax_difference():
    m = _mismatch(_bill(10_000_00, 900_00, 900_00), _doc(9_000_00, 900_00, 900_00))
    assert m.difference_paise == 0
    assert "The tax agrees, but the taxable value does not" in m.reason
    assert "₹10,000.00" in m.reason and "₹9,000.00" in m.reason
    assert "less tax" not in m.reason and "more tax" not in m.reason and "paise" not in m.reason


def test_a_pair_whose_tax_differs_says_how_much_more_or_less_the_bill_claims():
    more = _mismatch(_bill(10_000_00, 950_00, 950_00), _doc(10_000_00, 900_00, 900_00))
    assert "The bill claims ₹100.00 more tax than GSTR-2B carries" in more.reason
    less = _mismatch(_bill(10_000_00, 850_00, 850_00), _doc(10_000_00, 900_00, 900_00))
    assert "The bill claims ₹100.00 less tax than GSTR-2B carries" in less.reason


# ── ITC register refusals ───────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("net,reversal,reclaim", [
    (90_00, "gives back ₹90.00 of input tax", "takes back no input tax (it gives back ₹90.00 of credit)"),
    (-90_00, "gives back no input tax (it takes ₹90.00 of credit)", "takes back ₹90.00 of input tax"),
    (0, "gives back no input tax", "takes back no input tax"),
])
def test_the_register_says_what_the_journal_did_to_input_tax_and_never_gives_back_minus_an_amount(net, reversal, reclaim):
    from services.itc_register_service import _gave_back, _took_back
    assert _gave_back(net) == reversal
    assert _took_back(-net) == reclaim
    for sentence in (_gave_back(net), _took_back(net)):
        assert "back minus" not in sentence and "paise" not in sentence


# ── a foreign document is not in rupees ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("amount,currency,minor,expected", [
    (150_000, None, None, "₹1,500.00"), (150_000, "INR", None, "₹1,500.00"), (150_000, "inr", 3, "₹1,500.00"),
    (150_000, "USD", 2, "1,500.00 USD"), (150_000, "JPY", 0, "1,50,000 JPY"), (150_000, "KWD", 3, "150.000 KWD"),
    (150_000, "USD", None, "150000 USD (smallest units)"), (-5, "usd", 2, "-0.05 USD"),
])
def test_an_amount_is_rupees_only_in_the_base_currency(amount, currency, minor, expected):
    assert amount_text(amount, currency, minor) == expected


def test_a_receipt_in_dollars_is_refused_in_dollars_and_one_in_rupees_in_rupees():
    from pydantic import ValidationError

    from models.invoices import ReceiptIn
    base = dict(client_id="c1", customer_id="cu1", receipt_date="2026-06-01", amount_paise=100_000, payment_mode="bank")
    alloc = [dict(sales_invoice_id="i1", allocated_paise=150_000)]
    # The model's field names are the route's own; build with what it declares so a rename shows here and not as a skip.
    fields = ReceiptIn.model_fields
    kwargs = {k: v for k, v in base.items() if k in fields}
    kwargs["allocations"] = alloc if "allocations" in fields else []
    with pytest.raises(ValidationError) as inr:
        ReceiptIn(**kwargs)
    said = inr.value.errors()[0]["msg"]                  # the message, not pydantic's echo of the input's own field names
    assert "₹1,500.00" in said and "₹1,000.00" in said and "paise" not in said
    with pytest.raises(ValidationError) as usd:
        ReceiptIn(**kwargs, currency="USD")
    said = usd.value.errors()[0]["msg"]
    assert "₹" not in said and "150000 USD (smallest units)" in said


def test_a_foreign_documents_own_totals_are_named_in_its_currency():
    from domain.accounting.draft_integrity import _foreign_problems
    header = {"txn_currency": "usd", "txn_taxable": 100_000, "txn_total_gst": 18_000}
    rows = [{"taxable_amount_paise": 90_000, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 16_200}]
    text = " | ".join(p.message if hasattr(p, "message") else str(p) for p in _foreign_problems(header, rows))
    assert "100000 USD (smallest units)" in text and "90000 USD (smallest units)" in text
    assert "18000 USD (smallest units)" in text and "16200 USD (smallest units)" in text
    assert "₹" not in text


# ── a trial balance ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_negative_trial_balance_amount_is_named_in_rupees_with_the_word_minus():
    from domain.accounting.trial_balance import TrialBalanceError, TrialBalanceRow, validate
    rows = [TrialBalanceRow(account_name="Cash", account_type="asset", debit_paise=-5_000_00, credit_paise=0)]
    with pytest.raises(TrialBalanceError) as exc:
        validate(rows)
    text = str(exc.value)
    assert "is negative (minus ₹5,000.00)" in text and "-500000" not in text


# ── the year-end note's own helper ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("paise,expected", [(10_000_00, "Rs 10,000.00"), (0, "Rs 0.00"), (-5_00, "minus Rs 5.00")])
def test_the_year_end_notes_write_a_negative_figure_in_words_and_never_the_sign(paise, expected):
    from routers.year_end_notes import _rupees
    assert _rupees(paise) == expected and "₹" not in _rupees(paise)


# ── the self-assessment worksheet ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_challan_whose_split_does_not_foot_is_named_in_rupees():
    from domain.income_tax.self_assessment import position
    challan = {"challan_serial_no": "00123", "tax_paise": 50_000_00, "surcharge_paise": 0, "cess_paise": 2_000_00,
               "interest_paise": 0, "fee_paise": 0, "total_paise": 51_000_00, "minor_head": "300", "amount_paise": 51_000_00}
    pos = position(financial_year="2025-26", challans=[challan])
    text = " ".join(pos.gaps)
    assert "add up to ₹52,000.00, and its total is ₹51,000.00" in text and "paise" not in text
