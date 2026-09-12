"""
Three GST findings, and the shape they share: a figure the books hold that the
return did not declare, or declared in the wrong place.

GST-06 — A NON-GST SUPPLY EXISTED IN GSTR-1 AND NOT IN GSTR-3B
    `gstr3b_computer`'s outward loop classified `nil_rated`/`exempt`,
    `zero_rated` and `taxable`. `non_gst` fell off the end of the chain, and
    3.1(e) was a literal 0 in the payload. GSTR-1 declares the same invoice —
    `gstr1_builder` maps `non_gst` to `ngsup_amt` — so ONE DOCUMENT produced
    two returns that disagreed about whether it existed.

    No tax was underpaid: 3.1(e) is a disclosure line and a supply outside the
    levy bears none. What was wrong is the declaration, and the mismatch is the
    kind a portal comparison surfaces months later.

    3.1(e) IS NOT 3.1(c), which is the distinction the fix turns on. Nil-rated
    and exempt supplies are ones GST reaches and then charges at nil or
    relieves under §11. Non-GST supplies are outside the levy: §9(1) and §9(2)
    exclude petroleum products and alcoholic liquor for human consumption, and
    Schedule III puts a further list outside "supply" altogether.

GST-22 — THE SCREEN PRINTED A TURNOVER UNDER A TAX HEADING
    Table 3.1 on the GSTR-3B screen had four columns where the form has five,
    so the nil-rated/exempt row's taxable VALUE was rendered in the IGST
    column.

GST-29 — THE CHECK DIGIT GUARDED THE FRONT DOOR ONLY
    `gstin_problem` ran on the three single-create paths. `POST
    /customers/bulk`, `PATCH /customers/{id}` and the vendor equivalents did
    not, so a transposed GSTIN entered by CSV or by edit and reached GSTR-1
    Table 4A untested. §16(2)(aa) makes the credit available to whoever the
    GSTIN names.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from domain.gst.gstr3b_computer import GSTR3BResult, SalesTransaction, compute_gstr3b
from domain.gst.gstin import problem_with as gstin_problem

API = Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"


def _sale(**kw) -> SalesTransaction:
    base = dict(
        transaction_type="invoice", supply_type="taxable",
        taxable_amount_paise=0, cgst_paise=0, sgst_paise=0, igst_paise=0,
        cess_paise=0, is_interstate=False, is_reverse_charge=False,
        recipient_type="registered", place_of_supply=None,
    )
    base.update(kw)
    return SalesTransaction(**{k: v for k, v in base.items()
                               if k in SalesTransaction.__dataclass_fields__})


# ── GST-06 ───────────────────────────────────────────────────────────────────

def test_a_non_gst_supply_reaches_table_31e():
    r = compute_gstr3b([_sale(supply_type="non_gst", taxable_amount_paise=75_000_00)], [], [])
    assert r.outward_non_gst == 75_000_00, (
        "a non-GST outward supply fell off the end of the classification chain")
    assert r.outward_nil_exempt == 0, (
        "and it must NOT land in 3.1(c) — §11 relief and being outside the "
        "levy are different declarations")


def test_a_credit_note_reduces_it_like_every_other_line():
    r = compute_gstr3b([
        _sale(supply_type="non_gst", taxable_amount_paise=75_000_00),
        _sale(supply_type="non_gst", transaction_type="credit_note",
              taxable_amount_paise=25_000_00),
    ], [], [])
    assert r.outward_non_gst == 50_000_00


def test_the_payload_declares_it_rather_than_a_literal_zero():
    r = compute_gstr3b([_sale(supply_type="non_gst", taxable_amount_paise=1_00_000_00)], [], [])
    payload = r.as_gstn_payload("27ABCDE1234F1Z5", "042026")
    assert payload["sup_details"]["osup_nongst"] == {"txval": 100000.0}, (
        "3.1(e) was hardcoded {'txval': 0}, so the return declared nothing "
        "however many such supplies the period held")


def test_it_carries_no_tax_because_the_levy_does_not_reach_it():
    """A supply outside the levy cannot bear tax, so the form gives 3.1(e) no
    tax columns and neither does the payload."""
    r = compute_gstr3b([_sale(supply_type="non_gst", taxable_amount_paise=1_00_000_00)], [], [])
    payload = r.as_gstn_payload("27ABCDE1234F1Z5", "042026")
    assert set(payload["sup_details"]["osup_nongst"]) == {"txval"}
    assert r.outward_taxable_igst == r.outward_taxable_cgst == r.outward_taxable_sgst == 0


def test_gstr1_and_gstr3b_no_longer_disagree_about_the_same_invoice():
    """The finding's actual complaint. gstr1_builder has always mapped
    `non_gst` to `ngsup_amt`; 3B declared nothing."""
    from domain.gst import gstr1_builder
    assert gstr1_builder.NIL_EXEMPT_FIELD_BY_SUPPLY_TYPE["non_gst"] == "ngsup_amt" \
        if hasattr(gstr1_builder, "NIL_EXEMPT_FIELD_BY_SUPPLY_TYPE") \
        else "non_gst" in inspect.getsource(gstr1_builder)
    r = compute_gstr3b([_sale(supply_type="non_gst", taxable_amount_paise=42_000_00)], [], [])
    assert r.outward_non_gst == 42_000_00


def test_every_supply_type_the_classifier_can_produce_lands_somewhere():
    """The RULE behind GST-06 rather than the one value it caught. The
    classifier's vocabulary and the 3.1 accumulator must stay in step — an
    `elif` chain with no final branch loses whatever it does not name, and
    loses it silently."""
    vocabulary = ["taxable", "zero_rated", "nil_rated", "exempt", "non_gst"]
    for supply_type in vocabulary:
        r = compute_gstr3b([_sale(supply_type=supply_type,
                                  taxable_amount_paise=10_000_00)], [], [])
        landed = (r.outward_taxable_value + r.outward_zero_rated
                  + r.outward_nil_exempt + r.outward_non_gst)
        assert landed == 10_000_00, (
            f"supply_type={supply_type!r} contributed nothing to any 3.1 line — "
            "it fell off the end of the classification chain, which is exactly "
            "what GST-06 was")


def test_the_screen_contract_carries_it():
    import services.gst_return_service as svc
    src = inspect.getsource(svc)
    assert '"non_gst_paise": result.outward_non_gst' in src, (
        "computed and not served is not a fixed bug")


def test_the_filing_demo_stopped_saying_it_is_not_tracked():
    demo = (API / "services" / "filing_demo" / "gstr3b.py").read_text()
    assert "(e) Non-GST outward supplies" in demo, (
        "the walk-through must show the row the live return now carries")
    assert "not tracked\n    # upstream" not in demo


# ── GST-22 ───────────────────────────────────────────────────────────────────

def _screen() -> str:
    page = WEB / "app" / "gst" / "gstr3b" / "page.tsx"
    if not page.exists():
        pytest.skip("apps/web not present")
    return (page.read_text()
            .replace("\r\n", "\n"))


def _screen_code() -> str:
    text = _screen()
    text = re.sub(r"\{/\*[\s\S]*?\*/\}", "", text)
    return re.sub(r"/\*[\s\S]*?\*/", "", text)


def _table_31() -> str:
    """Table 3.1's own markup. Scoped, because Table 3.2 below it has a
    "Taxable value" header too — an unscoped search for one is satisfied by the
    other, which is how a negative control on this test passed while it was
    being written."""
    code = _screen_code()
    start = code.index("Table 3.1 — Outward Taxable Supplies")
    return code[start:code.index("</table>", start)]


# `<th(?=[\s>])`, not `<th`: the latter also matches `<thead>`, and with
# `.*?` reaching the first `</th>` the first "header" then came back as the
# whole `<thead><tr><th …>` prefix. Caught by the test failing on correct
# markup, which is the good direction for a scanner to be wrong in.
_TH = re.compile(r"<th(?=[\s>])[^>]*>(.*?)</th>", re.S)


def test_table_31_has_the_forms_five_columns():
    headers = _TH.findall(_table_31())
    assert [h.strip() for h in headers] == [
        "Supply Type", "Taxable value", "IGST", "CGST", "SGST"], (
        "the form has five columns and this table had four, so 3.1(c)'s "
        f"turnover was printed under the heading IGST. Got: {headers}")


def test_the_nil_exempt_value_is_in_the_value_column():
    code = _table_31()
    # From the row's own <tr>, so the LABEL cell is cell 0 and the column
    # positions below mean what they say.
    at = code.index("(c) Nil-rated / Exempt")
    row = code[code.rindex("<tr", 0, at):]
    row = row[:row.index("</tr>")]
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    assert len(cells) == 5, f"3.1(c) must have five cells, got {len(cells)}"
    assert "nil_exempt_paise" in cells[1], "the value belongs in the value column"
    for tax_cell in cells[2:]:
        assert "—" in tax_cell, (
            "a nil-rated or exempt supply bears no tax; a figure there is the "
            "wrong unit under a statutory column name")


def test_the_screen_renders_31e():
    code = _table_31()
    assert "(e) Non-GST outward supplies" in code
    assert "non_gst_paise" in code


def test_the_output_tax_total_excludes_reverse_charge_and_says_so():
    """§2(82) defines output tax as EXCLUDING reverse-charge tax and §49(4)
    then bars the credit ledger from paying it. With 3.1(d) now in the table,
    a total that swept it in would be both wrong and the wrong base for the
    Table 6 set-off below."""
    code = _table_31()
    total = code[code.index("Total output tax"):]
    total = total[:total.index("</tr>")]
    assert "rcm_inward" not in total
    text = _screen()
    assert "s.2(82)" in text and "s.49(4)" in text


def test_table_32_is_rendered_and_called_a_breakdown():
    code = _screen_code()
    assert "Table 3.2" in code, (
        "computed by gstr3b_computer since the set-off work and served to "
        "nobody — the portal cross-checks it against 3.1(a) and GSTR-1")
    # The exact BINDING, not the substring. `inter_state_3_2` on its own is
    # still present in a field renamed `inter_state_3_2_DISABLED`, which is how
    # a negative control on this test slipped through while it was being
    # written.
    assert re.search(r"\bw\.inter_state_3_2\b", code), (
        "the section must read the working's own field")
    for kind in ("unregistered", "composition", "uin"):
        assert f'"{kind}"' in code, (
            f"3.2 has three recipient classes and {kind} is missing")
    text = _screen()
    assert "breakdown, not an addition" in text, (
        "every rupee in 3.2 is already in 3.1(a); a reader must not be left "
        "wondering whether the two tables add up")


# ── GST-29 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("router,func", [
    ("customers", "bulk_create_customers"),
    ("customers", "update_customer"),
    ("vendors", "create_vendors_bulk"),
    ("vendors", "update_vendor"),
])
def test_every_door_a_gstin_is_typed_at_checks_the_check_digit(router, func):
    mod = __import__(f"routers.{router}", fromlist=["x"])
    src = inspect.getsource(getattr(mod, func))
    assert "gstin_problem" in src, (
        f"{router}.{func} accepts a GSTIN and does not test its check digit. "
        "A CSV import and an edit form are both places a human types one, and "
        "§16(2)(aa) sends the credit to whoever it names.")


def test_a_bulk_row_with_a_bad_gstin_is_an_item_error_not_a_batch_refusal():
    """Both bulk endpoints are explicitly designed so 'one malformed CSV row
    cannot 422 the whole batch'. A check-digit failure is exactly that kind of
    row, so it must be collected, not raised."""
    for router, func in (("customers", "bulk_create_customers"),
                         ("vendors", "create_vendors_bulk")):
        mod = __import__(f"routers.{router}", fromlist=["x"])
        src = inspect.getsource(getattr(mod, func))
        block = src[src.index("gstin_problem"):]
        block = block[:block.index("continue") + len("continue")]
        assert "errors.append" in block, f"{router}.{func} should collect, not raise"
        assert "HTTPException" not in block


def test_the_patch_paths_refuse_outright():
    """A PATCH is one record and one intent, so there is nothing to collect —
    the same 422 the create path gives."""
    for router, func in (("customers", "update_customer"),
                         ("vendors", "update_vendor")):
        mod = __import__(f"routers.{router}", fromlist=["x"])
        src = inspect.getsource(getattr(mod, func))
        block = src[src.index("gstin_problem"):]
        assert "status_code=422" in block[:400]


def test_a_patch_that_does_not_touch_the_gstin_is_not_asked():
    """`exclude_none=True` means an untouched field is absent, and absent must
    not be read as empty-and-invalid — that would make every unrelated edit
    fail."""
    for router, func in (("customers", "update_customer"),
                         ("vendors", "update_vendor")):
        mod = __import__(f"routers.{router}", fromlist=["x"])
        src = inspect.getsource(getattr(mod, func))
        assert 'if "gstin" in payload' in src


def test_the_fixtures_the_bulk_path_is_tested_with_are_real_gstins():
    """The guard's own discovery. test_customer_bulk_create's two GSTINs both
    ended in 5 — a plausible shape and the wrong check digit — so the import
    path had only ever been exercised with GSTINs the portal would reject."""
    fixture = (API / "tests" / "test_customer_bulk_create.py").read_text()
    for name, value in re.findall(r'^(GSTIN_\w+) = "([^"]+)"', fixture, re.M):
        assert gstin_problem(value) is None, (
            f"{name} = {value} is not a valid GSTIN: {gstin_problem(value)}")


def test_the_authority_is_still_one_module():
    """Four more call sites, still one implementation. A second check-digit
    routine anywhere is the drift this repository keeps recording."""
    hits = set()
    for path in (API / "routers").rglob("*.py"):
        text = path.read_text()
        if "gstin_problem" in text or "problem_with" in text:
            hits.add(path.name)
    assert hits == {"customers.py", "vendors.py", "onboarding.py"}, hits
    for name in sorted(hits):
        src = (API / "routers" / name).read_text()
        assert "from domain.gst.gstin import" in src, (
            f"{name} must delegate to the one authority, not re-implement it")
