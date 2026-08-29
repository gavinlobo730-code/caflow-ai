"""Rule 59(4): which inter-state B2C invoices are reported invoice-wise.

WHAT WAS WRONG — two independent faults in one `if`

    if txn.is_interstate and txn.taxable_amount_paise > B2CL_THRESHOLD_PAISE:

    with B2CL_THRESHOLD_PAISE fixed at Rs 2,50,000 and the comment citing
    "CGST Rule 59(2)".

    1. THE LIMIT IS Rs 1,00,000, NOT Rs 2,50,000. Notification 12/2024-Central
       Tax, dated 10 July 2024, substituted "one lakh rupees" for "two and a
       half lakh rupees" wherever they occur in Rule 59(4), with effect from
       1 AUGUST 2024. Every GSTR-1 this platform has produced for a period from
       August 2024 onward has put inter-state B2C invoices between Rs 1 lakh and
       Rs 2.5 lakh into the Table 7 summary when they belong in Table 5,
       invoice-wise.

    2. IT COMPARES THE TAXABLE VALUE. Rule 59(4) tests the INVOICE VALUE — the
       taxable value plus every tax head. GSTN's Returns Offline Tool compares
       its worksheet's "Invoice Value" column. At 18% the two differ by enough
       to move an invoice across the line on its own: taxable Rs 95,000 is an
       invoice value of Rs 1,12,100, which is B2CL.

    Both push the same way: fewer invoices reported invoice-wise than the rule
    requires. And the existing test asserted Rs 2,00,000 was B2CS, so it did not
    merely miss the change — it pinned the superseded figure in place.

    The threshold is now a function of the invoice date, which is also how
    GSTN's own tool models it: it holds a limit and the period that limit takes
    effect from, and picks between them per return period.
"""
import pytest

from domain.gst.classifier import (
    B2CL_NEW_THRESHOLD_FROM,
    B2CL_THRESHOLD_LEGACY_PAISE,
    B2CL_THRESHOLD_PAISE,
    GSTInvoiceCategory,
    TransactionForClassification,
    b2cl_threshold_paise,
    classify_transaction,
)

LAKH = 1_00_000_00


def _txn(value_paise, *, date="2026-04-10", interstate=True, taxable=None):
    return TransactionForClassification(
        id="t", transaction_type="sales_invoice", party_gstin=None,
        is_interstate=interstate,
        taxable_amount_paise=taxable if taxable is not None else value_paise,
        supply_type="taxable", invoice_type="Regular", place_of_supply="29",
        invoice_value_paise=value_paise, transaction_date=date,
    )


def _cat(*a, **k):
    return classify_transaction(_txn(*a, **k))


# ── the amounts ──────────────────────────────────────────────────────────────

def test_the_current_limit_is_one_lakh():
    assert B2CL_THRESHOLD_PAISE == LAKH
    assert B2CL_THRESHOLD_LEGACY_PAISE == 2_50_000_00
    assert B2CL_NEW_THRESHOLD_FROM == "2024-08-01"


@pytest.mark.parametrize("date,expected", [
    ("2024-07-31", B2CL_THRESHOLD_LEGACY_PAISE),   # last day of the old rule
    ("2024-08-01", B2CL_THRESHOLD_PAISE),          # the day it changed
    ("2024-08-02", B2CL_THRESHOLD_PAISE),
    ("2023-01-15", B2CL_THRESHOLD_LEGACY_PAISE),
    ("2026-04-10", B2CL_THRESHOLD_PAISE),
])
def test_the_limit_in_force_depends_on_the_invoice_date(date, expected):
    assert b2cl_threshold_paise(date) == expected


def test_a_missing_date_gets_the_current_limit():
    """Defaulting to the superseded figure would under-report B2CL on today's
    returns, which is the failure this whole module exists to end."""
    for bad in (None, "", "   ", "not-a-date"):
        assert b2cl_threshold_paise(bad) == B2CL_THRESHOLD_PAISE


# ── the classification ───────────────────────────────────────────────────────

def test_an_invoice_between_one_and_two_and_a_half_lakh_is_now_b2cl():
    """THE BUG, stated as a number. Rs 2,00,000 inter-state to an unregistered
    buyer went into the Table 7 summary and belongs in Table 5."""
    assert _cat(2_00_000_00) == GSTInvoiceCategory.B2CL


def test_the_same_invoice_before_august_2024_is_b2cs():
    """The old limit still governs an old period — a return being prepared or
    amended for, say, June 2024 must classify by the rule then in force."""
    assert _cat(2_00_000_00, date="2024-06-30") == GSTInvoiceCategory.B2CS
    assert _cat(2_00_000_00, date="2024-08-01") == GSTInvoiceCategory.B2CL


@pytest.mark.parametrize("value,expected", [
    (LAKH - 1, GSTInvoiceCategory.B2CS),
    (LAKH, GSTInvoiceCategory.B2CS),      # "exceeds" — at the limit is not over it
    (LAKH + 1, GSTInvoiceCategory.B2CL),
])
def test_the_boundary_is_exclusive(value, expected):
    assert _cat(value) == expected


def test_it_is_the_invoice_value_that_counts_not_the_taxable_value():
    """Taxable Rs 95,000 at 18% is an invoice value of Rs 1,12,100. Under the
    old comparison this was B2CS on both counts; it is B2CL."""
    taxable = 95_000_00
    invoice_value = taxable + 17_100_00
    assert invoice_value > LAKH and taxable < LAKH, "the fixture must straddle the limit"
    assert _cat(invoice_value, taxable=taxable) == GSTInvoiceCategory.B2CL


def test_an_intra_state_supply_is_never_b2cl_however_large():
    """Table 5 is inter-state only. A large intra-state B2C supply is summarised
    in Table 7 regardless of value."""
    assert _cat(50_00_000_00, interstate=False) == GSTInvoiceCategory.B2CS


def test_a_registered_buyer_is_b2b_whatever_the_value():
    txn = TransactionForClassification(
        id="t", transaction_type="sales_invoice", party_gstin="29AADCB2230M1ZT",
        is_interstate=True, taxable_amount_paise=5_00_000_00, supply_type="taxable",
        invoice_type="Regular", place_of_supply="29",
        invoice_value_paise=5_90_000_00, transaction_date="2026-04-10")
    assert classify_transaction(txn) == GSTInvoiceCategory.B2B


# ── The rule as the CA reads it on screen ───────────────────────────────────

def test_the_screen_does_not_quote_a_threshold_the_code_stopped_using():
    """The classifier was corrected to Rs 1 lakh and Rule 59(4); the GSTR-1
    screen went on telling the CA it used Rs 2.5 lakh and Rule 59(2).

    That is worse than either being wrong on its own. The app computed one rule
    and documented another, so a CA reconciling an unexpected B2CL row against
    the explanation printed beside it would conclude the software was broken —
    and there is nothing in a test of the OUTPUT that notices prose.

    Scanned rather than eyeballed because this drifted once already: the code
    was fixed and the sentence was not, in the same change.
    """
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web"
    screens = [web / "app" / "gst" / "gstr1" / "page.tsx"]
    for f in screens:
        assert f.exists(), f
        src = f.read_text()
        assert "Rule 59(2)" not in src, (
            f"{f.name} cites CGST Rule 59(2) for the B2CL threshold. The "
            "invoice-wise reporting rule is 59(4); 59(2) is a different provision."
        )
        # The superseded figure may only appear where it is explained as the
        # pre-01-08-2024 limit, never as the current one.
        if "2.5 lakh" in src or "2,50,000" in src or "2.5L" in src:
            assert "1 August 2024" in src or "01-08-2024" in src, (
                f"{f.name} states the old Rs 2.5 lakh limit without saying it was "
                "superseded. Notification 12/2024-Central Tax cut it to Rs 1 lakh "
                "with effect from 1 August 2024."
            )
        assert "₹1 lakh" in src or "1 lakh" in src, (
            f"{f.name} explains B2CL without naming the Rs 1 lakh limit the "
            "classifier actually applies"
        )


def test_that_scanner_would_catch_the_text_it_was_written_for():
    """A guard on absence passes against a file it cannot find. This pins the
    detector against the exact sentence that was wrong."""
    stale = ("No B2CL invoices. B2CL applies to inter-state unregistered "
             "invoices above ₹2.5L (CGST Rule 59(2)).")
    assert "Rule 59(2)" in stale
    assert not ("1 lakh" in stale)
