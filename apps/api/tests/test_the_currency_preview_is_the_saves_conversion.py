"""The browser's INR total of a foreign document is the save's own conversion (POST-A-266, part 3).

`shared/fx-conversion-vectors.json` is read by this file and by apps/web/lib/services/currencyPreview.test.ts, so the
browser mirror and `domain/currency/conversion.to_base_minor` cannot drift apart without one of the two failing.
"""
from __future__ import annotations

import json
import pathlib
from decimal import Decimal

from domain.currency.conversion import to_base_minor

ROOT = pathlib.Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "shared/fx-conversion-vectors.json").read_text(encoding="utf-8"))


def test_every_conversion_vector_is_what_the_server_computes():
    assert len(VECTORS["conversions"]) >= 15
    for v in VECTORS["conversions"]:
        assert to_base_minor(v["txn_minor"], Decimal(v["rate"]), v["txn_minor_unit"]) == v["base_minor"], v


def test_a_document_is_converted_head_by_head_and_the_vectors_show_why_it_matters():
    differs = 0
    for d in VECTORS["documents"]:
        rate = Decimal(d["rate"])
        assert sum(to_base_minor(h, rate, d["txn_minor_unit"]) for h in d["heads"]) == d["base_total"], d
        assert to_base_minor(sum(d["heads"]), rate, d["txn_minor_unit"]) == d["one_conversion_of_the_total"], d
        differs += d["base_total"] != d["one_conversion_of_the_total"]
    assert differs >= 1, "a vector must show the old single conversion giving a different INR total"


# ── the saves themselves, driven, not read as text ────────────────────────────────────────────────────────────────
# Rs 105.55 at 18% intra-state: heads 10555 + 949 + 950. At 83.5 the heads converted one by one come to 10,39,910 paise
# and the total converted once to 10,39,909, so a save that changed to one conversion fails here.
_RATE = Decimal("83.5")
_HEAD_KEYS = ("taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise")


def _usd(rate=_RATE):
    from domain.currency.document_currency import DocumentCurrency
    return DocumentCurrency(is_foreign=True, currency="USD", rate=rate, minor_unit=2, rate_source="manual",
                            rate_type="manual", rate_date="2026-06-01", rate_selected_by=None, rate_overridden=True)


def _head_sum(heads, rate=_RATE):
    return sum(to_base_minor(h, rate, 2) for h in heads)


def test_a_foreign_bill_is_converted_head_by_head_as_the_preview_does():
    from domain.currency.document_currency import identity_currency
    from routers.purchase_bills import _compute_bill_lines_and_totals
    vendor = {"id": "V1", "name": "Supplier", "state_code": "27", "tds_applicable": False, "gstin": "27AABCU9603R1ZX"}
    line = {"description": "svc", "hsn_sac": "9982", "quantity": 1, "rate_paise": 10_555, "gst_rate_percent": 18.0}
    for rcm in (False, True):
        txn = _compute_bill_lines_and_totals([dict(line)], False, vendor, "2026-06-01", "F",
                                             identity_currency("2026-06-01"), db=None, is_reverse_charge=rcm)
        base = _compute_bill_lines_and_totals([dict(line)], False, vendor, "2026-06-01", "F", _usd(), db=None,
                                              is_reverse_charge=rcm)
        heads = [txn["taxable_amount_paise"]] if rcm else [txn[k] for k in _HEAD_KEYS]
        assert base["total_paise"] == _head_sum(heads), (rcm, base["total_paise"])
    full = [txn[k] for k in _HEAD_KEYS]
    assert _head_sum(full) != to_base_minor(sum(full), _RATE, 2), "the case must separate the two rules"


def test_a_foreign_sales_invoice_is_converted_head_by_head_as_the_preview_does(monkeypatch):
    from tests.test_invoice_round_off import _CALLER, _ro_invoice, _ro_setup
    si, db = _ro_setup(monkeypatch)
    inr = si._create_invoice_core(_ro_invoice("FX-INR"), _CALLER)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    for row in db.rows("clients"):
        if row["id"] == "CLI":
            row["multi_currency_enabled"] = True
            row["functional_currency"] = "INR"
    db.seed("firms", {"id": "FIRM-RO", "multi_currency_entitled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "\u20b9", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    usd = si._create_invoice_core(_ro_invoice("FX-USD", currency="USD", exchange_rate=_RATE), _CALLER)
    heads = [inr[k] for k in _HEAD_KEYS]
    assert usd["total_paise"] == _head_sum(heads), usd["total_paise"]
    for k in _HEAD_KEYS:
        assert usd[k] == to_base_minor(inr[k], _RATE, 2), k
