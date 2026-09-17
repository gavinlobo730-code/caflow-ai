"""The Rule 48(4) scope test, against the shared vectors — CGST Rule 48(4).

SALES-18: `apps/web/lib/invoices/compliance.irnEligibility` was the ONLY
implementation of this rule in the repository. A statutory rule living solely
in the browser bundle breaks the house rule that computation, validation and
statutory rules live in `apps/api`, and it is what let SALES-17 — the e-way
threshold measured on the pre-GST taxable value — sit unnoticed for as long as
it did: a wrong number in a TypeScript file has no Python twin to disagree with
it and no parity vector to fail.

The vectors are shared with apps/web/scripts/irn-parity.test.ts because the rule
exists twice — the Compliance panel recomputes on every keystroke, and a round
trip per keystroke is not a panel. This file is one half of what stops them
drifting; change one implementation and both suites fail, which is the point.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.gst.irn_scope import assess

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "shared" / "irn-parity-vectors.json").read_text()
)["vectors"]


@pytest.mark.parametrize("vec", VECTORS, ids=[v["label"] for v in VECTORS])
def test_the_shared_vectors(vec):
    got = assess(**vec["input"]).as_dict()
    want = vec["expected"]
    for key in ("verdict", "supply_in_scope", "threshold_paise",
                "turnover_exceeds", "turnover_unknown"):
        assert got[key] == want[key], (
            f"{vec['label']}: {key} — expected {want[key]!r}, got {got[key]!r}. "
            f"{vec['why']}")
    assert len(got["gaps"]) == want["gaps"], got["gaps"]


def test_the_vector_file_did_not_shrink():
    """A parity fixture whose vectors are deleted passes silently."""
    assert len(VECTORS) >= 23, f"the vector file shrank to {len(VECTORS)}"


def test_every_vector_input_is_a_real_keyword_of_assess():
    """The vectors are splatted into `assess`, so a renamed parameter would
    TypeError on every one — but a vector carrying an extra key nobody reads
    would pass forever while asserting nothing about it."""
    import inspect

    allowed = set(inspect.signature(assess).parameters)
    for vec in VECTORS:
        extra = set(vec["input"]) - allowed
        assert not extra, f"{vec['label']}: {extra} is not a parameter of assess()"
