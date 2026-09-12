"""
IGST Act §§7 and 8, decided on the server — and the case where nobody can.

WHAT WAS WRONG (no finding; the 12 September probe pass found it)
    The GSTR-1 Table 11A advance carried `is_interstate` as a field the BROWSER
    computed and `receipt_service` stored verbatim:

        is_interstate: advancePos !== clientStateCode

    Two things. It is a statutory rule in the frontend, which this codebase
    does not allow — and the receipt form's own comment in that place claimed
    the split was "DERIVED ... rather than asked as a third question", which
    was the right instinct on the wrong side of the wire.

    And `clients.state_code` is nullable with nothing requiring it. For a
    client with none recorded, `advancePos !== ""` is true for every place of
    supply, so EVERY advance was declared inter-state — IGST in Table 11A where
    CGST and SGST were due, on a return the CA files.

WHY THE SERVER CAN DO BETTER THAN THE BROWSER COULD
    It can see the client's GSTIN, whose first two characters ARE the
    registration's state under CGST §25 — so a registered client always carries
    its own state whether or not `state_code` was ever filled in. Only where
    neither is known does the question have no answer, and then the answer is
    None rather than a default: `gst_advance_service` already names an advance
    it cannot declare, and an undecided treatment belongs in that list beside a
    missing rate. Defaulting it to False (intra-state) is the mirror of the
    browser's bug, not a fix for it.
"""
import pytest

from domain.gst.place_of_supply import is_interstate, supplier_state_code


# ---------------------------------------------------------------------------
# The rule.
# ---------------------------------------------------------------------------
def test_the_suppliers_state_comes_from_the_gstin_first():
    # CGST §25: the first two characters of a GSTIN are the registration's
    # state. A registered client therefore always carries its own state, which
    # is exactly what the browser could not see.
    assert supplier_state_code({"gstin": "27AAPFU0939F1ZV"}) == "27"


def test_a_recorded_state_code_is_used_when_there_is_no_gstin():
    assert supplier_state_code({"state_code": "29"}) == "29"
    assert supplier_state_code({"gstin": "", "state_code": "29"}) == "29"


def test_the_gstin_wins_over_a_state_code_that_disagrees():
    # The registration is the fact; `state_code` is free text somebody typed.
    assert supplier_state_code({"gstin": "27AAPFU0939F1ZV", "state_code": "29"}) == "27"


def test_a_client_with_neither_has_no_state():
    assert supplier_state_code({}) is None
    assert supplier_state_code(None) is None


def test_the_same_state_is_intra_state():
    assert is_interstate({"gstin": "27AAPFU0939F1ZV"}, "27") is False


def test_a_different_state_is_inter_state():
    assert is_interstate({"gstin": "27AAPFU0939F1ZV"}, "29") is True


@pytest.mark.parametrize("client,pos", [
    ({}, "27"),                                   # no supplier state
    ({"gstin": "27AAPFU0939F1ZV"}, ""),           # no place of supply
    ({"gstin": "27AAPFU0939F1ZV"}, None),
    (None, "27"),
])
def test_an_undecidable_split_is_None_and_never_a_default(client, pos):
    # THE DEFECT, in one assertion. The browser's rule answered `True` for the
    # first of these; a naive server-side fix answers `False`. Both are a
    # guess at the tax head on a filed return.
    assert is_interstate(client, pos) is None


# ---------------------------------------------------------------------------
# The report side: an undecided treatment is named, not defaulted.
# ---------------------------------------------------------------------------
from services.gst_advance_service import _missing_phrase           # noqa: E402


def test_an_undecided_treatment_is_named_among_the_missing():
    phrase = _missing_phrase(1800, "27", None)
    assert "inter-state or intra-state treatment" in phrase


def test_the_three_absences_read_as_one_sentence():
    assert _missing_phrase(1800, "27", True) == "it is not declarable"  # nothing missing
    assert _missing_phrase(None, "27", True) == "it has no GST rate recorded"
    assert _missing_phrase(None, "", None) == (
        "it has no GST rate, no place of supply and no inter-state or "
        "intra-state treatment recorded")


def test_an_advance_with_no_treatment_is_not_declared(monkeypatch):
    # The key the buckets are built on used to be `bool(r.get("is_interstate"))`,
    # which read a NULL as intra-state and put CGST+SGST on a row nobody had
    # decided. It now falls into the undeclarable list instead.
    from services import gst_advance_service as svc

    class _DB:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def gte(self, *_a, **_k):
            return self

        def lte(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def gt(self, *_a, **_k):
            # `_paginate_all` keysets forward on the last id; the second page
            # must come back empty or the walk never ends.
            self._exhausted = True
            return self

        def __init__(self):
            self._table = None
            self._exhausted = False

        def table(self, name):                                  # noqa: F811
            self._table = name
            return self

        def execute(self):
            if self._exhausted:
                class _Empty:
                    data = []
                return _Empty()
            rows = ([{"id": "C", "gst_advance_tax_applicable": True}]
                    if self._table == "clients" else
                    [{"id": "R1", "amount_paise": 1_00_000,
                      "receipt_date": "2026-04-10", "gst_rate_bps": 1800,
                      "place_of_supply": "27", "is_interstate": None}]
                    if self._table == "receipts" else [])

            class _R:
                data = rows
            return _R()

    out = svc.table_11_sections(_DB(), "F", "C", "042026")
    assert out["at"] == [] and out["txpd"] == []
    assert out["gaps"] and "treatment" in out["gaps"][0]["reason"]
