"""The e-way bill rule, against the shared vectors — CGST Rule 138(1).

SALES-17: the threshold was tested against the TAXABLE value. Explanation 2 to
Rule 138(1) defines consignment value as the §15 value "and ALSO INCLUDES the
central tax, State or Union territory tax, integrated tax and cess charged, if
any, in the document". A ₹48,000 consignment at 18% is ₹56,640 and needs an
e-way bill; the Compliance panel called it "below ₹50,000 — usually not
required". §129 detention follows, with a penalty of the tax plus an equal
amount.

The vectors are shared with apps/web/scripts/eway-parity.test.ts because the
rule exists twice — the panel recomputes on every keystroke, and a round trip
per keystroke is not a panel. This file is one half of what stops them drifting.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.gst.eway import EWAY_THRESHOLD_PAISE, EwayLine, assess, is_service_code

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "shared" / "eway-parity-vectors.json").read_text()
)["vectors"]


@pytest.mark.parametrize("vec", VECTORS, ids=[v["label"] for v in VECTORS])
def test_the_shared_vectors(vec):
    got = assess([EwayLine(**ln) for ln in vec["lines"]]).as_dict()
    want = vec["expected"]
    for key in ("consignment_value_paise", "exceeds_threshold", "verdict",
                "goods_lines", "service_lines", "unclassified_lines",
                "excluded_exempt_paise"):
        assert got[key] == want[key], (
            f"{vec['label']}: {key} — expected {want[key]!r}, got {got[key]!r}. "
            f"{vec['why']}")
    assert len(got["gaps"]) == want["gaps"], got["gaps"]


def test_the_threshold_is_fifty_thousand_rupees_in_paise():
    assert EWAY_THRESHOLD_PAISE == 50_000_00


def test_the_limit_is_exceeded_not_reached():
    """Rule 138(1): "of consignment value EXCEEDING fifty thousand rupees". The
    old test was `taxable_amount_paise < THRESHOLD -> not required`, which makes
    exactly ₹50,000 required. One paise, and the wrong side of a statute."""
    at = assess([EwayLine(hsn_sac="7306", taxable_amount_paise=50_000_00, gst_rate_bps=1800)])
    over = assess([EwayLine(hsn_sac="7306", taxable_amount_paise=50_000_01, gst_rate_bps=1800)])
    assert at.exceeds_threshold is False and at.verdict == "not_required"
    assert over.exceeds_threshold is True and over.verdict == "required"


@pytest.mark.parametrize("code,is_service", [
    ("998211", True), ("996511", True), ("99", True),
    ("7306", False), ("0401", False), ("8471", False),
    ("", False), (None, False),
    # Not digits, so not a SAC however it starts — a typed "99abc" is not a
    # classification and must not silently make a goods line a service.
    ("99abc", False),
])
def test_a_sac_is_chapter_99_and_digits(code, is_service):
    assert is_service_code(code) is is_service


def test_the_reason_says_the_tax_is_included():
    """The message is half the fix. A CA told "not required" with no reason
    cannot tell a rule that was applied from one that was applied wrongly, and
    this one had been applied wrongly for as long as it existed."""
    out = assess([EwayLine(hsn_sac="7306", taxable_amount_paise=48_000_00,
                           igst_paise=8_640_00, gst_rate_bps=1800)])
    assert "Explanation 2" in out.reason
    assert "tax" in out.reason


def test_a_wholly_exempt_consignment_is_refused_rather_than_guessed():
    """Rule 138(14) lists fourteen cases needing no e-way bill whatever the
    value, including the goods in the Annexure to Rule 138 — which this
    codebase does not hold and which cannot be written from memory. A wholly
    exempt consignment is the case that meets it often. Both guesses are
    expensive: "required" wastes an hour, "not required" is a detention."""
    out = assess([EwayLine(hsn_sac="0401", taxable_amount_paise=80_000_00, gst_rate_bps=0)])
    assert out.verdict == "undetermined"
    assert out.gaps and "138(14)" in " ".join(out.gaps)
    # The value is still computed and reported — refusing the verdict is not
    # refusing the arithmetic.
    assert out.consignment_value_paise == 80_000_00
