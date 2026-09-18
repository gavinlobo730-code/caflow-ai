"""SALES-33 — IGST §7(5) makes two classes inter-State whatever the geography.

`routers/sales_invoices.py` derived `is_interstate` as
`client_state_code != place_of_supply`, which is CGST §8(1). That is right for
an ordinary domestic supply and wrong for an export and for a supply to an SEZ,
and the whole mock and real suite passed with it wrong — 16,401 tests, none of
which pinned it — because every SEZ fixture in the repository happened to be
built with `is_interstate=True` by hand.

The negative control for this module is therefore the point of it: every test
here fails against the previous expression.
"""
from __future__ import annotations

import pytest

from domain.gst import inter_state as ins
from domain.gst import treatment as tr
from domain.gst.place_of_supply import recipient_place_of_supply
from domain.sales.line_tax import compute_line_gst


# ── the statute ──────────────────────────────────────────────────────────────

def test_an_sez_supply_inside_one_state_is_inter_state():
    """The defect this module exists for, stated as the smallest case.

    A supply to an SEZ unit in Maharashtra from a Maharashtra supplier. The two
    state codes are equal, so §8(1) alone calls it intra-State — and the
    proviso to §8(1) excludes exactly this supply from that definition while
    IGST §7(5)(b) puts it in the other one."""
    for kind in (tr.SEZ_WITH_PAYMENT, tr.SEZ_WITHOUT_PAYMENT):
        inter, why = ins.is_inter_state(
            gst_treatment=kind, supplier_state_code="27", place_of_supply="27")
        assert inter is True, kind
        assert "§7(5)(b)" in why
        assert "wherever both parties are" in why


def test_an_export_is_inter_state_even_where_the_place_of_supply_resolved_home():
    """The export road to the same defect, and it runs through a correct rule.

    A foreign buyer has no GSTIN and no state, so `recipient_place_of_supply`
    walks its chain to the last link — the SUPPLIER's own state, IGST
    §12(2)(b)(ii)'s unregistered walk-in — which is right for that case and
    exactly wrong here. The comparison then finds the two equal."""
    pos, source = recipient_place_of_supply(
        stated=None, customer={"gstin": None, "state_code": None},
        supplier_state="27")
    assert (pos, source) == ("27", "supplier_state"), (
        "the premise: the chain really does land on the supplier's own state"
    )
    for kind in (tr.EXPORT_WITH_PAYMENT, tr.EXPORT_WITHOUT_PAYMENT):
        inter, why = ins.is_inter_state(
            gst_treatment=kind, supplier_state_code="27", place_of_supply=pos)
        assert inter is True, kind
        assert "§7(5)(a)" in why


def test_a_deemed_export_is_placed_by_geography_like_any_other_supply():
    """The carve-out, and the one a careless reading gets wrong.

    §147 deems certain supplies of GOODS to be exports. The goods do not leave
    India and §7(5) does not name it, so it is an ordinary domestic supply for
    this purpose and commonly carries central and State tax. Folding it in
    because the word "export" is in its name would charge IGST on a domestic
    supply."""
    assert tr.DEEMED_EXPORT not in ins.ALWAYS_INTER_STATE
    inter, why = ins.is_inter_state(
        gst_treatment=tr.DEEMED_EXPORT, supplier_state_code="27",
        place_of_supply="27")
    assert inter is False
    assert "§8(1)" in why
    across, _ = ins.is_inter_state(
        gst_treatment=tr.DEEMED_EXPORT, supplier_state_code="27",
        place_of_supply="29")
    assert across is True, "it is still placed by geography, in both directions"
    assert "§147" in ins.DEEMED_EXPORT_IS_DOMESTIC


def test_the_statute_is_asked_before_anything_can_compare_states():
    """Order is the rule. Written the other way round — compare, then override
    — it is the same bug with more steps, because the override is what somebody
    forgets."""
    inter, _ = ins.is_inter_state(
        gst_treatment=tr.SEZ_WITH_PAYMENT, supplier_state_code="27",
        place_of_supply="27", stated=False)
    assert inter is True, (
        "an explicit False from the caller cannot make an SEZ supply "
        "intra-State — the statute does not leave that to be stated"
    )


# ── the caller's own flag ────────────────────────────────────────────────────

def test_a_stated_true_still_wins_and_a_silence_is_not_a_denial():
    """`is_inter_state` on the request is honoured where TRUE, unchanged: a
    caller asserting it knows something this module cannot see. What it may not
    do is make an export intra-State by staying silent, which is why `False`
    and `None` are the same thing here."""
    stated, why = ins.is_inter_state(
        gst_treatment=tr.REGULAR, supplier_state_code="27",
        place_of_supply="27", stated=True)
    assert stated is True
    assert "Stated on the request" in why

    for silence in (False, None):
        quiet, _ = ins.is_inter_state(
            gst_treatment=tr.REGULAR, supplier_state_code="27",
            place_of_supply="27", stated=silence)
        assert quiet is False, silence


def test_an_unknown_state_falls_to_intra_and_says_so():
    """The direction that cannot invent an inter-State supply out of missing
    data. CGST + SGST on a supply that turns out inter-State is a correctable
    mis-declaration on one return; IGST charged because a column was empty is
    money taken under the wrong head from a customer who cannot then claim it."""
    for supplier, pos in ((None, "27"), ("27", None), (None, None)):
        inter, why = ins.is_inter_state(
            gst_treatment=tr.REGULAR, supplier_state_code=supplier,
            place_of_supply=pos)
        assert inter is False
        assert "Record both" in why


@pytest.mark.parametrize("kind", sorted(ins.ALWAYS_INTER_STATE))
def test_every_always_inter_state_treatment_carries_its_own_reason(kind):
    """A treatment in the set with no sentence would answer True and explain
    nothing, which is how IGST appears on a same-state invoice as an
    unexplained result."""
    _, why = ins.is_inter_state(
        gst_treatment=kind, supplier_state_code="27", place_of_supply="27")
    assert "§7(5)" in why


def test_the_set_is_exactly_the_four_the_section_names():
    """Not five and not two. A treatment added to `domain/gst/treatment` that
    belongs here has to be put here deliberately."""
    assert ins.ALWAYS_INTER_STATE == {
        tr.EXPORT_WITH_PAYMENT, tr.EXPORT_WITHOUT_PAYMENT,
        tr.SEZ_WITH_PAYMENT, tr.SEZ_WITHOUT_PAYMENT,
    }
    assert ins.ALWAYS_INTER_STATE < tr.TREATMENTS


# ── what it costs, in money ──────────────────────────────────────────────────

def test_the_money_moves_by_the_whole_tax():
    """₹1,00,000 at 18% to an SEZ unit in the supplier's own state.

    Under the old expression the customer was charged ₹9,000 CGST + ₹9,000
    SGST. Three things were then wrong at once: the heads are wrong on the
    document, the SEZ unit cannot claim what it was charged, and GSTR-1 files a
    SEWP/SEWOP row carrying `camt` and `samt`, which the IRP's own validation
    32 rejects."""
    inter, _ = ins.is_inter_state(
        gst_treatment=tr.SEZ_WITHOUT_PAYMENT, supplier_state_code="27",
        place_of_supply="27")
    cgst, sgst, igst = compute_line_gst(100_00_000, 1800, inter)
    assert (cgst, sgst) == (0, 0), "no central or State tax on an SEZ supply"
    assert igst == 18_00_000

    was_cgst, was_sgst, was_igst = compute_line_gst(100_00_000, 1800, False)
    assert (was_cgst, was_sgst, was_igst) == (9_00_000, 9_00_000, 0), (
        "the premise: this is what the old expression produced"
    )


def test_the_create_time_treatment_helper_collapses_the_limbs_it_cannot_know():
    """At create time no tax has been computed, so an export made on payment
    cannot be told from one under an LUT. That is sound HERE because §7(5)
    reaches both, and it is why the helper has its own name rather than being a
    default argument on the one that reads a stored invoice."""
    from routers.sales_invoices import _gst_treatment_for
    assert _gst_treatment_for({"supply_type": "zero_rated",
                               "invoice_type": "Regular"}) in ins.ALWAYS_INTER_STATE
    for it in ("sez_with_payment", "sez_without_payment"):
        assert _gst_treatment_for({"supply_type": "zero_rated",
                                   "invoice_type": it}) in ins.ALWAYS_INTER_STATE
    assert _gst_treatment_for({"supply_type": "taxable",
                               "invoice_type": "Regular"}) == tr.REGULAR


# ── the wiring, which the first draft of this module did not test ────────────

def test_the_create_path_asks_the_authority_and_does_not_compare_states_itself():
    """THIS TEST EXISTS BECAUSE A NEGATIVE CONTROL CAUGHT ITS ABSENCE.

    Every test above exercises `domain/gst/inter_state` directly, and all
    thirteen of them PASSED against the router reverted to the old expression —
    so the module was proved and the wiring was not. A rule with a correct
    authority that nothing calls is the `capital_wip` shape this repository
    keeps finding, and it is exactly what the old code looked like from the
    domain side.

    So this asserts the CALL, and asserts the comparison is gone. The second
    half is what makes it a rule rather than a spelling: re-deriving
    `is_interstate` from two state codes anywhere in the create path is the
    defect, whatever it is spelled, because that expression cannot see §7(5)."""
    import inspect
    import re as _re
    import routers.sales_invoices as si

    src = inspect.getsource(si._create_invoice_core)
    src_no_comments = _re.sub(r"#[^\n]*", "", src)

    assert "inter_state.is_inter_state(" in src_no_comments, (
        "the create path must resolve this through the one authority — a "
        "second derivation is what §7(5) fell through the first time"
    )
    assert _re.search(r"is_interstate\s*=\s*bool\(", src_no_comments) is None, (
        "`is_interstate = bool(...)` is the old expression's shape: a state "
        "comparison with the request's flag OR-ed in front. It cannot see an "
        "export or an SEZ supply and must not come back"
    )
    assert "client_state_code != effective_supply_state" not in src_no_comments


def test_the_authority_is_reached_for_every_treatment_the_statute_names():
    """The helper the router passes must produce, for the request shapes a
    screen can actually send, a treatment the authority recognises. A typo in
    `_gst_treatment_for` would return something outside the vocabulary and the
    supply would silently fall through to the state comparison."""
    from routers.sales_invoices import _gst_treatment_for
    seen = {
        _gst_treatment_for({"supply_type": st, "invoice_type": it})
        for st in ("taxable", "zero_rated", "exempt", "nil_rated", "non_gst")
        for it in ("Regular", "sez_with_payment", "sez_without_payment",
                   "deemed_export")
    }
    assert seen <= tr.TREATMENTS, f"outside the vocabulary: {seen - tr.TREATMENTS}"
    assert seen & ins.ALWAYS_INTER_STATE, (
        "no request shape reaches the statute — the helper is not wired to the "
        "fields a screen sends"
    )
