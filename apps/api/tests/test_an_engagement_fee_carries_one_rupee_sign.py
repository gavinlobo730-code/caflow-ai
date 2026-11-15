"""An engagement letter's fee carries one rupee sign, whatever its template writes beside it (PRE-A-025).

WHAT WAS WRONG
    The letter EL-2026-0005 the live site mailed on 16-11-2026 read "Rs Rs 4,000 per month" (two rupee signs).
    The `{{engagement_fee}}` merge field already carries its sign (`_format_fee`), and the default templates in
    code stopped writing one beside it, but templates already stored in a firm's library kept the old text: all
    six of the owner's Test Firm templates (made in June) read "₹{{engagement_fee}}" in production, and a CA who
    types a sign before the placeholder in a template of their own gets the same.

WHAT THIS HOLDS
    `_render_merge_fields` drops a sign written immediately before the fee placeholder, in every spelling a
    template may carry, and touches nothing else; each default template merges to exactly one sign.
"""
import re

import pytest

from routers.engagement_letters import _format_fee, _render_merge_fields
import routers.engagement_letters as el

FEE = {"engagement_fee": _format_fee(400000)}  # Rs 4,000


@pytest.mark.parametrize("written", [
    "₹{{engagement_fee}}", "₹ {{engagement_fee}}", "&#8377;{{engagement_fee}}", "&#x20B9;{{engagement_fee}}",
    "Rs.{{engagement_fee}}", "Rs. {{engagement_fee}}", "Rs {{engagement_fee}}", "INR {{engagement_fee}}",
    "inr{{engagement_fee}}", "{{engagement_fee}}",
])
def test_a_sign_beside_the_fee_is_not_printed_twice(written):
    out = _render_merge_fields(f"<p>Our fee is <strong>{written} per month</strong></p>", FEE)
    assert out == "<p>Our fee is <strong>₹4,000 per month</strong></p>"


def test_nothing_else_in_the_template_is_touched():
    text = "Rs. 500 is the filing fee; INR is the currency; ₹ marks rupees. Fee: ₹{{engagement_fee}}."
    out = _render_merge_fields(text, FEE)
    assert out == "Rs. 500 is the filing fee; INR is the currency; ₹ marks rupees. Fee: ₹4,000."


def test_a_word_ending_in_rs_or_inr_before_the_fee_is_not_a_sign():
    # "Partners" ends in "rs": only a whole "Rs" is a sign
    assert _render_merge_fields("Partners {{engagement_fee}}", FEE) == "Partners ₹4,000"


def test_every_default_template_merges_to_one_sign():
    templates = [v for k, v in vars(el).items() if isinstance(v, str) and "{{engagement_fee}}" in v]
    for container in (getattr(el, "DEFAULT_TEMPLATES", None), getattr(el, "_DEFAULT_TEMPLATES", None)):
        if isinstance(container, (list, tuple)):
            templates += [t.get("content", "") for t in container if isinstance(t, dict)]
    assert templates, "no default template with a fee was found to check"
    for t in templates:
        out = _render_merge_fields(t, FEE)
        assert "₹₹" not in out and not re.search(r"₹\s*₹", out)
        assert out.count("₹4,000") == t.count("{{engagement_fee}}")
