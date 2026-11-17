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


def test_the_saves_still_convert_each_head_and_add_them():
    """If a save stops converting head by head, the browser mirror is no longer the save's rule."""
    api = ROOT / "apps/api/routers"
    sales = (api / "sales_invoices.py").read_text(encoding="utf-8")
    bills = (api / "purchase_bills.py").read_text(encoding="utf-8")
    for head in ("total_taxable_paise", "total_cgst_paise", "total_sgst_paise", "total_igst_paise", "total_cess_paise"):
        assert f"dc.to_base({head})" in sales, head
    assert "base_total     = base_taxable + base_total_gst + base_cess" in sales
    for head in ("total_taxable", "total_cgst", "total_sgst", "total_igst", "total_cess"):
        assert f"{head} = dc.to_base({head})" in bills.replace("    =", " =").replace("   =", " =").replace("  =", " ="), head
    assert "total_paise   = total_taxable if is_reverse_charge else total_taxable + total_gst_sum + total_cess" in bills
