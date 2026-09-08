"""FA-07: buying an asset on credit no longer double-counts it.

WHAT THE OLD JOURNAL DID

    Dr <category account>   cost
      Cr Bank               cost

unconditionally, for every asset ever added. A CA who buys a machine on a
purchase bill gets the BILL's journal — Dr Purchases, Dr GST Input, Cr Trade
Payables — and then adds the machine to the register, which posts the pair
above. The cost is now in both Purchases and Fixed Assets, Bank has been
credited for something bought on credit, and the payable is still outstanding.

These test the three credit legs, the §17(5) capitalisation, and the refusals.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.accounting import FixedAssetIn


def _asset(**kw):
    base = dict(client_id="c1", asset_name="CNC Lathe", asset_category="Plant & Machinery",
                purchase_date="2026-05-10", purchase_cost_paise=10_00_000_00)
    base.update(kw)
    return FixedAssetIn(**base)


# ── the model refuses what would post to the wrong account ──────────────────

def test_from_bill_without_a_bill_is_refused():
    """The entry reclassifies that bill's cost out of purchases. With no bill
    there is nothing to reclassify, and the entry would credit an expense
    nothing put there — balanced, and wrong."""
    with pytest.raises(ValidationError, match="purchase_bill_id"):
        _asset(acquisition_mode="from_bill")


def test_credit_without_a_vendor_is_refused():
    """A payable with no vendor cannot be settled by any later payment."""
    with pytest.raises(ValidationError, match="vendor_id"):
        _asset(acquisition_mode="credit")


def test_tax_without_an_itc_answer_is_refused():
    """Whether §17(5) blocks the credit changes the balance sheet AND the
    depreciable cost, so it cannot fall to a default."""
    with pytest.raises(ValidationError, match="itc_eligible"):
        _asset(igst_paise=1_80_000_00)


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValidationError, match="acquisition_mode"):
        _asset(acquisition_mode="lease")


def test_the_default_is_paid_so_existing_callers_are_unaffected():
    a = _asset()
    assert a.acquisition_mode == "paid"
    assert a.itc_eligible is None and a.igst_paise == 0


def test_tax_may_not_be_negative():
    with pytest.raises(ValidationError):
        _asset(cgst_paise=-1, itc_eligible=True)


# ── the credit leg, which is the finding ────────────────────────────────────

class _Acct:
    """Resolves a CoA pattern to a stable name so the journal can be read."""
    NAMES = {
        "%Plant & Machinery%": "fa-plant",
        "%Trade Payable%": "trade-payables",
        "%Purchase%": "purchases",
        "%GST Input%": "gst-input",
        "%Bank%": "generic-bank",
        "%Cash in Hand%": "cash-in-hand",
    }

    def __call__(self, db, firm_id, client_id, pattern, system_key=None):
        return self.NAMES[pattern]


def _lines_for(asset: dict) -> list[dict]:
    """Build the acquisition journal's lines without a database."""
    from services.phase2_journal_service import phase2_journal_service as K
    captured = {}

    def _create(**kw):
        captured.update(kw)
        return "journal-1"

    class _DB:
        def table(self, *a, **k): raise AssertionError("should not query")

    orig_find, orig_create, orig_mock = K._find_account, K._create_journal, None
    import services.phase2_journal_service as mod
    orig_mock = mod._USE_MOCK
    mod._USE_MOCK = False
    K._find_account = _Acct()
    K._create_journal = lambda **kw: _create(**kw)
    try:
        import unittest.mock as m
        with m.patch("core.supabase_client.get_supabase", return_value=_DB()), \
             m.patch("domain.accounting.payment_account.resolve_payment_account") as rp:
            from domain.accounting.payment_account import PaymentAccount
            src = "cash" if str(asset.get("payment_mode", "")).lower() == "cash" else "generic_bank"
            rp.return_value = PaymentAccount(
                account_id="cash-in-hand" if src == "cash" else "generic-bank",
                source=src, is_fallback=src != "cash", reason="")
            K.journal_for_asset_acquisition(asset, "f1", "c1")
    finally:
        K._find_account, K._create_journal = orig_find, orig_create
        mod._USE_MOCK = orig_mock
    return captured["lines"]


def _base(**kw):
    a = {"id": "a1" * 18, "asset_name": "CNC Lathe", "asset_category": "Plant & Machinery",
         "purchase_date": "2026-05-10", "purchase_cost_paise": 10_00_000_00,
         "asset_code": "FA-0001"}
    a.update(kw)
    return a


def test_bought_on_credit_credits_the_vendor_not_the_bank():
    """THE DEFECT. Bank was credited for a machine nobody had paid for."""
    lines = _lines_for(_base(acquisition_mode="credit", vendor_id="v1"))
    credits = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert credits == {"trade-payables": 10_00_000_00}
    assert "generic-bank" not in credits


def test_capitalised_from_a_bill_moves_cost_out_of_purchases():
    """The bill already posted its payable. A second entry crediting Bank or
    Payables would double it — so this reclassifies, touching neither."""
    lines = _lines_for(_base(acquisition_mode="from_bill", purchase_bill_id="b1"))
    debits = {l["account_id"]: l["debit_paise"] for l in lines if l["debit_paise"]}
    credits = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert debits == {"fa-plant": 10_00_000_00}
    assert credits == {"purchases": 10_00_000_00}
    assert "trade-payables" not in credits and "generic-bank" not in credits


def test_paid_in_cash_credits_cash_in_hand():
    lines = _lines_for(_base(acquisition_mode="paid", payment_mode="cash"))
    credits = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert credits == {"cash-in-hand": 10_00_000_00}


def test_eligible_tax_is_input_credit_and_raises_the_credit_leg():
    """The vendor is owed cost PLUS tax; the tax is an asset (ITC), not cost."""
    lines = _lines_for(_base(acquisition_mode="credit", vendor_id="v1",
                             igst_paise=1_80_000_00, itc_eligible=True))
    debits = {l["account_id"]: l["debit_paise"] for l in lines if l["debit_paise"]}
    credits = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert debits == {"fa-plant": 10_00_000_00, "gst-input": 1_80_000_00}
    assert credits == {"trade-payables": 11_80_000_00}


def test_blocked_tax_never_becomes_an_input_credit_line():
    """§17(5) tax is capitalised by the ROUTER into purchase_cost_paise, so the
    journal sees one bigger asset and no GST Input line at all."""
    lines = _lines_for(_base(acquisition_mode="credit", vendor_id="v1",
                             purchase_cost_paise=11_80_000_00,
                             igst_paise=1_80_000_00, itc_eligible=False))
    assert not [l for l in lines if l["account_id"] == "gst-input"]
    credits = {l["account_id"]: l["credit_paise"] for l in lines if l["credit_paise"]}
    assert credits == {"trade-payables": 11_80_000_00}


@pytest.mark.parametrize("mode,vendor,bill", [
    ("paid", None, None), ("credit", "v1", None), ("from_bill", None, "b1"),
])
def test_every_mode_balances(mode, vendor, bill):
    lines = _lines_for(_base(acquisition_mode=mode, vendor_id=vendor, purchase_bill_id=bill,
                             igst_paise=1_80_000_00 if mode != "from_bill" else 0,
                             itc_eligible=True if mode != "from_bill" else None))
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


# ── §17(5) capitalisation is a DEPRECIATION fact ────────────────────────────

def test_blocked_tax_is_added_to_the_depreciable_cost():
    """Not presentational: a blocked ₹1,80,000 that stays out of the cost is
    ₹1,80,000 of depreciation the client never claims, for the asset's life."""
    from routers.fixed_assets import capitalised_cost_paise as cap
    assert cap(10_00_000_00, 1_80_000_00, 0, 0, False) == 11_80_000_00


def test_eligible_tax_is_not_capitalised():
    """It is an input credit, claimed in the return — not part of the machine."""
    from routers.fixed_assets import capitalised_cost_paise as cap
    assert cap(10_00_000_00, 1_80_000_00, 0, 0, True) == 10_00_000_00


def test_tax_not_stated_leaves_the_cost_alone():
    """Every row created before migration 343 has itc_eligible NULL, and their
    cost must not move underneath them."""
    from routers.fixed_assets import capitalised_cost_paise as cap
    assert cap(10_00_000_00, 0, 0, 0, None) == 10_00_000_00
    assert cap(10_00_000_00, 90_000_00, 90_000_00, 0, None) == 10_00_000_00


def test_blocked_cgst_and_sgst_are_both_capitalised():
    """An intra-state purchase splits the tax across two heads; capitalising
    only one is the easy half-fix."""
    from routers.fixed_assets import capitalised_cost_paise as cap
    assert cap(10_00_000_00, 0, 90_000_00, 90_000_00, False) == 11_80_000_00
