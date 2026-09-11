"""The supply's treatment has one source, and an invoice shows what it owes.

SALES-19 — TWO VOCABULARIES, AND THE SCREEN READ THE WRONG ONE.
    The invoice carries `supply_type` (taxable | zero_rated | nil_rated |
    exempt | non_gst) and `invoice_type` (Regular | SEZ_with_payment |
    SEZ_without_payment | Deemed_export) — migration 268, and the pair
    `domain/gst/classifier` reads to build GSTR-1. The e-invoice RECORD
    independently carries `gst_treatment` in a different vocabulary, captured
    when a CA prepares an IRN and described by its own service as "metadata on
    this record only".

    `CompliancePanel` built its whole view from the second
    (`gst_treatment: irn.record?.gst_treatment ?? null`) and hardcoded
    `is_reverse_charge: null`. So an invoice marked zero-rated / SEZ — the
    fields that actually reach the return — was shown as "Regular" until
    somebody prepared an e-invoice record, and every invoice was shown as not
    reverse-charge including the ones that are.

SALES-26 — WHAT THE INVOICE STILL OWES.
    The sales list had no balance column and the receipt allocation screen
    showed the invoice TOTAL, its own comment admitting "(invoice total, not
    outstanding)". Migration 278 made `outstanding_paise` a generated column —
    total plus debit notes less paid less credited — precisely so this would be
    cheap, and no sales screen read it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.gst.treatment import (
    DEEMED_EXPORT, EXPORT_WITH_PAYMENT, EXPORT_WITHOUT_PAYMENT, REGULAR,
    SEZ_WITH_PAYMENT, SEZ_WITHOUT_PAYMENT, TREATMENTS, treatment_for_invoice,
)

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"


def _code(path: Path) -> str:
    """Comments and docstrings stripped — the prose below quotes the defect."""
    src = path.read_text()
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    src = re.sub(r"#[^\n]*", "", src)
    return re.sub(r'("""|\'\'\')[\s\S]*?\1', "", src)


# ── SALES-19: the derivation ────────────────────────────────────────────────

@pytest.mark.parametrize("itype,expected", [
    ("SEZ_with_payment",    SEZ_WITH_PAYMENT),
    ("SEZ_without_payment", SEZ_WITHOUT_PAYMENT),
    ("Deemed_export",       DEEMED_EXPORT),
])
def test_the_invoice_type_settles_sez_and_deemed_export(itype, expected):
    assert treatment_for_invoice(supply_type="taxable", invoice_type=itype) == expected


def test_an_export_splits_on_whether_igst_was_charged():
    """IGST §16(3) gives two routes and they are not interchangeable: (b) on
    payment of IGST, refunded under §54; (a) under an LUT or bond, with nothing
    charged and the input credit refunded instead. GSTR-1 Table 6A declares
    which with exp_typ WPAY or WOPAY, so filing the wrong one asks for the
    wrong refund under the wrong rule. The tax on the document is the
    evidence — the same evidence classifier.TransactionForClassification uses
    for the same decision."""
    assert treatment_for_invoice(supply_type="zero_rated", invoice_type="Regular",
                                 igst_paise=18_000_00) == EXPORT_WITH_PAYMENT
    assert treatment_for_invoice(supply_type="zero_rated", invoice_type="Regular",
                                 igst_paise=0) == EXPORT_WITHOUT_PAYMENT


@pytest.mark.parametrize("stype", ["taxable", "nil_rated", "exempt", "non_gst"])
def test_an_ordinary_domestic_supply_is_regular(stype):
    """This vocabulary distinguishes export and SEZ ROUTES, not rates. What a
    nil or exempt supply is instead is carried by `supply_type`, which the
    return reads directly — folding it in here would lose that."""
    assert treatment_for_invoice(supply_type=stype, invoice_type="Regular") == REGULAR


def test_nothing_recorded_reads_as_regular():
    assert treatment_for_invoice(supply_type=None, invoice_type=None) == REGULAR


def test_every_answer_is_in_the_screens_vocabulary():
    """The six the compliance screens know. A seventh would render blank."""
    seen = {
        treatment_for_invoice(supply_type=s, invoice_type=i, igst_paise=g)
        for s in ("taxable", "zero_rated", "nil_rated", "exempt", "non_gst", None)
        for i in ("Regular", "SEZ_with_payment", "SEZ_without_payment",
                  "Deemed_export", None)
        for g in (0, 1)
    }
    assert seen <= TREATMENTS, sorted(seen - TREATMENTS)


def test_the_invoice_detail_serves_it():
    """A derivation nothing calls is a second opinion the product never asks
    for — the defect was precisely that the screen asked the wrong source."""
    code = _code(API_ROOT / "routers" / "sales_invoices.py")
    assert "treatment_for_invoice(" in code
    assert code.count('["gst_treatment"] = _gst_treatment(') == 2, (
        "the mock branch and the live branch must both serve it, or the answer "
        "depends on whether a database is configured")


def test_the_panel_reads_the_invoice_not_only_the_einvoice_record():
    """Both halves of the defect, as CODE. `is_reverse_charge: null` was a
    literal, and the treatment came only from an IRN record that may not
    exist."""
    panel = _code(WEB_ROOT / "components" / "invoices" / "CompliancePanel.tsx")
    assert not re.search(r"is_reverse_charge:\s*null\s*,", panel), (
        "is_reverse_charge is pinned to null again, so the treatment summary "
        "reports every invoice as not reverse-charge including the ones that "
        "are")
    assert "invoice.is_reverse_charge" in panel
    assert re.search(r"gst_treatment:\s*invoice\.gst_treatment\s*\?\?", panel), (
        "the panel must prefer the invoice's own derived treatment; the "
        "e-invoice record's value is the fallback, not the source")


# ── SALES-26: what the invoice still owes ───────────────────────────────────

def test_the_sales_list_shows_a_balance():
    page = _code(WEB_ROOT / "app" / "clients" / "[id]" / "sales" / "page.tsx")
    assert re.search(r'key:\s*"outstanding_paise"', page), (
        "the invoice list has no balance column, so the one question a sales "
        "register is for — who owes what — cannot be answered from it")


def test_the_allocation_screen_offers_the_outstanding_not_the_total():
    """A CA allocating a receipt against the invoice TOTAL is reading the
    figure from before every earlier payment."""
    page = _code(WEB_ROOT / "app" / "clients" / "[id]" / "sales" / "page.tsx")
    assert "invoiceOutstanding" in page, (
        "the allocation list is back to showing the invoice total")
    assert "invoiceDisplayTotal" not in page, (
        "the total-showing helper is back")
    assert "outstanding_paise, status" in page, (
        "the allocation query no longer selects outstanding_paise, so the "
        "helper falls back to the total on every row")
