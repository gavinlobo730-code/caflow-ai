"""PUR-29 / SALES-34 — where the SUPPLIER sits, asked one way everywhere.

Three call sites answered "which state is this client in" three different ways,
and the comparison that decides IGST against CGST+SGST was resolved with one
rule on the vendor side and another on the client side of the very same
expression.

  * `routers/purchase_bills.py` read the VENDOR as
    `state_code or gstin-prefix` and the CLIENT as `gstin-prefix` alone;
  * `routers/sales_invoices.py` read the client as `gstin-prefix` alone;
  * `apps/web/lib/{invoices,purchases}/editorContext.ts` read
    `state_code || gstin.slice(0,2)` — the OPPOSITE precedence to the backend.

And `domain/gst/place_of_supply.supplier_state_code`, which has held the chain
since it was written and which nothing called, disagreed with its own sibling
in the same module about how to read a GSTIN.
"""
from __future__ import annotations

import inspect
import re

import pytest

from domain.gst import place_of_supply as pos


# ── the authority agrees with itself ─────────────────────────────────────────

def test_the_supplier_half_reads_a_gstin_the_way_the_recipient_half_does():
    """Both halves take the PREFIX, and this one did not.

    `supplier_state_code` called `gstin.state_code`, which requires a fully
    VALID GSTIN and answers None on a bad check digit. Four lines below it,
    `recipient_place_of_supply` takes `gstin[:2]` with a comment saying exactly
    why — "the question is which state, not whether the registration number is
    well-formed, and falling through on a bad check digit would silently turn
    an inter-state supply intra-state".

    That is not a hypothetical: it is what the supplier half did."""
    bad_check_digit = "27ABCDE1234F1Z5"
    from domain.gst.gstin import problem_with
    assert problem_with(bad_check_digit), "the premise: this GSTIN is malformed"

    assert pos.supplier_state_code({"gstin": bad_check_digit}) == "27", (
        "a transposed digit must not erase the supplier's state — that is what "
        "turns an inter-state supply intra-state"
    )
    got, _ = pos.recipient_place_of_supply(
        stated=None, customer={"gstin": bad_check_digit}, supplier_state="29")
    assert got == "27", "the sibling already did this; now they agree"


def test_a_prefix_that_is_not_a_state_falls_through_to_the_column():
    """Taking the prefix is not trusting the GSTIN. A two-character prefix
    naming no state is not an answer, and the recorded column is asked next."""
    assert pos.supplier_state_code(
        {"gstin": "ZZABCDE1234F1Z5", "state_code": "29"}) == "29"
    assert pos.supplier_state_code({"gstin": "ZZABCDE1234F1Z5"}) is None


def test_an_unregistered_client_is_placed_by_the_column_it_has():
    """The case the routers could not see at all. An unregistered client has no
    GSTIN by definition, so a GSTIN-only read answers nothing — and an empty
    supplier state makes every document intra-State whatever the other party's
    state is."""
    assert pos.supplier_state_code({"gstin": None, "state_code": "27"}) == "27"
    assert pos.supplier_state_code({"gstin": "", "state_code": "27"}) == "27"
    assert pos.supplier_state_code({}) is None


def test_the_gstin_still_wins_where_both_are_recorded():
    """CGST §25 makes the first two characters of a GSTIN the registration's
    state, so for a registered person it is the authority and
    `clients.state_code` may be a stale postal address."""
    assert pos.supplier_state_code(
        {"gstin": "29ABCDE1234F1Z5", "state_code": "27"}) == "29"


# ── the call sites ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("module_name, func_name", [
    ("routers.sales_invoices", "_create_invoice_core"),
    ("routers.purchase_bills", "_resolve_vendor_and_interstate"),
])
def test_neither_router_places_its_own_client_by_a_private_helper(
        module_name, func_name):
    """Both must reach the authority. A private `_get_state_code_from_gstin`
    in a router is how the two sides of one comparison came to be resolved by
    different rules."""
    import importlib
    mod = importlib.import_module(module_name)
    src = re.sub(r"#[^\n]*", "", inspect.getsource(getattr(mod, func_name)))
    assert "supplier_state_code(" in src, (
        f"{func_name} must place the client through the one authority"
    )
    assert not re.search(r"_get_state_code_from_gstin\(\s*client", src), (
        "the private GSTIN-only helper must not decide a CLIENT's state — it "
        "cannot see an unregistered client, and it disagrees with the vendor "
        "side of its own comparison"
    )


def test_both_client_reads_name_both_columns():
    """A narrow projection makes the second link of the chain a silent no-op.

    The trap `domain/accounting/opening_documents` records for `is_opening` and
    `domain/firm/identity` for `gst_number`: the filter reads the key off the
    row, so a `.select()` that omits it never fires. Here it would mean an
    unregistered client is placed by nothing, which is the defect this module
    is about."""
    from pathlib import Path
    api = Path(__file__).resolve().parents[1]
    for name in ("routers/sales_invoices.py", "routers/purchase_bills.py"):
        src = (api / name).read_text()
        selects = re.findall(r'table\("clients"\)\s*\n?\s*\.select\("([^"]+)"\)', src)
        placing = [p for p in selects if "gstin" in p]
        assert placing, f"{name}: no clients projection names a gstin"
        for proj in placing:
            assert "state_code" in proj, (
                f"{name}: `.select(\"{proj}\")` names the GSTIN and not the "
                f"state column, so `supplier_state_code`'s second link cannot "
                f"fire for an unregistered client"
            )


def test_the_bulk_import_carries_the_same_two_facts_as_a_single_create():
    """A cache that drops a column is a divergence between one bill and a
    hundred — the kind of defect a test suite structurally cannot see, because
    both paths pass their own tests.

    THIS TEST CHECKED A STRING AND A NEGATIVE CONTROL CAUGHT IT. Asserting
    `"client_state_code" in src` passed with the PRODUCER deleted, because the
    consumer still mentioned the key — so the assertion proved the cache was
    read and not that anything filled it. It reads the dict literal that BUILDS
    the cache, which is the half that can go missing."""
    import ast as _ast
    from pathlib import Path
    api = Path(__file__).resolve().parents[1]
    tree = _ast.parse((api / "routers" / "purchase_bills.py").read_text())

    built = [
        {k.value for k in node.keys if isinstance(k, _ast.Constant)}
        for node in _ast.walk(tree)
        if isinstance(node, _ast.Dict)
        and any(isinstance(k, _ast.Constant) and k.value == "client_gstin"
                for k in node.keys)
    ]
    assert built, "no dict literal builds the bulk cache any more"
    for keys in built:
        assert "client_state_code" in keys, (
            "the bulk cache carries the client's GSTIN and not its recorded "
            "state, so an imported bill is placed by the GSTIN alone while a "
            "typed one is placed by both — an unregistered client's bills "
            "would book central and State tax however far the vendor is"
        )
