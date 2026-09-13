"""E and F — the turnover fractions Rules 42 and 43 apportion by.

FA-19. `gst_return_service.outward_turnover` answers them, and it answers them
by building the SAME outward-document list `gstr3b_from_books` builds and
running it through the SAME computer. That is the point: a Rule 43 working and
the GSTR-3B it belongs to must not be able to disagree about what was supplied.

The construction was extracted into `_outward_transactions` rather than copied,
because it is not trivial — a note inherits its parent invoice's classification
(CGST §34), a sales debit note is signed the other way from a credit note, and
the recipient type feeds Table 3.2.

WHAT E AND F ARE

  E   "aggregate value of exempt supplies". §2(47) makes an exempt supply one
      taxed at nil, wholly exempt under §11 CGST / §6 IGST, OR non-taxable —
      and §2(78) makes a non-taxable supply one on which tax is not leviable at
      all. So nil-rated, exempt and non-GST are ONE figure.
  F   "total turnover in the State", §2(112): taxable, exempt, exports and
      inter-State supplies, excluding tax.

THE EXCLUSION THAT MATTERS: a zero-rated supply is NOT in E. §16(1) of the IGST
Act allows credit on it expressly and Rule 43(1)(b) calls such supplies "other
than exempted supplies". Putting an exporter's turnover in E would reverse the
credit the export scheme exists to refund.
"""
from __future__ import annotations

import pytest

import services.gst_return_service as grs

FIRM, CLIENT, PERIOD = "firm-1", "client-1", "062025"


def _inv(kind, value):
    """One posted sales invoice of `value` paise, classified `kind`."""
    return {"id": f"i-{kind}-{value}", "customer_id": None,
            "taxable_amount_paise": value, "cgst_paise": 0, "sgst_paise": 0,
            "igst_paise": 0, "cess_paise": 0, "supply_type": kind,
            "is_reverse_charge": False, "is_interstate": False,
            "supply_state_code": "27"}


@pytest.fixture
def books(monkeypatch):
    """A period whose outward side is whatever the test puts in `rows`."""
    rows: dict = {"sales": [], "cn": [], "sdn": []}
    monkeypatch.setattr(grs, "_posted_sales", lambda *a: rows["sales"])
    monkeypatch.setattr(grs, "_issued_credit_notes", lambda *a: rows["cn"])
    monkeypatch.setattr(grs, "_issued_sales_debit_notes", lambda *a: rows["sdn"])
    monkeypatch.setattr(grs, "_customers_for_3b", lambda *a: {})
    monkeypatch.setattr(grs, "_classification_by_parent_invoice",
                        lambda db, firm, notes: rows["parents"])
    rows["parents"] = {}
    return rows


def _turnover():
    return grs.outward_turnover(None, FIRM, CLIENT, PERIOD)


def test_nil_rated_and_exempt_are_both_in_E(books):
    books["sales"] = [_inv("nil_rated", 10_00_000), _inv("exempt", 20_00_000)]
    t = _turnover()
    assert t["exempt_paise"] == 30_00_000
    assert t["total_paise"] == 30_00_000


def test_a_non_GST_supply_is_in_E_TOO(books):
    """§2(47) reads in §2(78): an exempt supply INCLUDES a non-taxable supply.
    Petroleum and alcoholic liquor are outside the levy entirely, and leaving
    them out of E understates the reversal on every client who deals in them."""
    books["sales"] = [_inv("non_gst", 40_00_000)]
    t = _turnover()
    assert t["exempt_paise"] == 40_00_000
    assert t["total_paise"] == 40_00_000


def test_a_ZERO_RATED_supply_is_not_in_E(books):
    """The exclusion that matters. IGST §16(1) allows the credit and Rule
    43(1)(b) names zero-rated supplies as being other than exempted ones —
    so an exporter's turnover swells F and leaves E alone."""
    books["sales"] = [_inv("taxable", 60_00_000), _inv("zero_rated", 40_00_000)]
    t = _turnover()
    assert t["exempt_paise"] == 0
    assert t["total_paise"] == 1_00_00_000
    assert t["breakdown"]["zero_rated_paise"] == 40_00_000


def test_F_is_every_bucket_and_E_is_the_two(books):
    books["sales"] = [_inv("taxable", 1_000), _inv("zero_rated", 2_000),
                      _inv("exempt", 4_000), _inv("non_gst", 8_000)]
    t = _turnover()
    assert t["total_paise"] == 15_000
    assert t["exempt_paise"] == 12_000
    assert t["breakdown"] == {"taxable_paise": 1_000, "zero_rated_paise": 2_000,
                              "nil_exempt_paise": 4_000, "non_gst_paise": 8_000}


def test_a_credit_note_reduces_the_turnover_it_adjusts(books):
    """CGST §34 — a note inherits its parent invoice's classification, and
    reduces. An exempt supply credited in the same month is not exempt turnover
    twice over."""
    books["sales"] = [_inv("exempt", 50_00_000)]
    books["parents"] = {"i-exempt-5000000": {"supply_type": "exempt",
                                             "invoice_type": "Regular",
                                             "is_reverse_charge": False}}
    books["cn"] = [{"id": "cn1", "sales_invoice_id": "i-exempt-5000000",
                    "taxable_amount_paise": 20_00_000,
                    "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
                    "cess_paise": 0}]
    t = _turnover()
    assert t["exempt_paise"] == 30_00_000
    assert t["total_paise"] == 30_00_000


def test_a_sales_debit_note_increases_it(books):
    """§34(3) — signed the other way from a credit note. `_outward_transactions`
    carries that, which is one of the reasons it was extracted rather than
    re-written for this caller."""
    books["sales"] = [_inv("taxable", 50_00_000)]
    books["sdn"] = [{"id": "dn1", "sales_invoice_id": None,
                     "taxable_amount_paise": 10_00_000,
                     "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
                     "cess_paise": 0}]
    t = _turnover()
    assert t["total_paise"] == 60_00_000


def test_a_period_with_no_supplies_answers_zero_rather_than_raising(books):
    """Rule 43(1)(g)'s proviso is the CALLER's decision to make — the working
    reports the refusal and names the last-period substitution. This function
    just says what the books hold."""
    t = _turnover()
    assert t == {"period": PERIOD, "exempt_paise": 0, "total_paise": 0,
                 "breakdown": {"taxable_paise": 0, "zero_rated_paise": 0,
                               "nil_exempt_paise": 0, "non_gst_paise": 0},
                 "caveats": []}


def test_the_figures_are_VALUES_not_tax(books):
    """Rule 43(1)(g)'s E and F are turnover, so the tax on an invoice must not
    inflate either. `outward_taxable_value` is the taxable value and the tax
    columns are read separately by the return."""
    inv = _inv("taxable", 1_00_000)
    inv.update(cgst_paise=9_000, sgst_paise=9_000)
    books["sales"] = [inv]
    t = _turnover()
    assert t["total_paise"] == 1_00_000


def test_gstr3b_and_the_working_build_the_outward_side_the_same_way():
    """One implementation. `gstr3b_from_books` must call the extracted builder
    rather than keeping its own inline copy — two constructions of one list is
    how a return and a working come apart."""
    import inspect
    src = inspect.getsource(grs.gstr3b_from_books)
    assert "_outward_transactions(db, firm_id, client_id, start, end)" in src
    # ...and must NOT have kept the loop it used to run inline.
    assert 'transaction_type="sales_invoice"' not in src
    assert inspect.getsource(grs.outward_turnover).count("_outward_transactions") == 1


def test_E_is_exactly_the_untaxed_supply_types_the_rest_of_the_engine_knows():
    """`domain/gst/supply_classification.UNTAXED_SUPPLY_TYPES` is the codebase's
    own answer to "which supplies carry no tax", and E is the same set. Pinned
    so a sixth supply type added there cannot silently stay out of E — which
    would understate every Rule 42 and Rule 43 reversal for the clients who
    make it."""
    from domain.gst.supply_classification import UNTAXED_SUPPLY_TYPES
    assert UNTAXED_SUPPLY_TYPES == {"nil_rated", "exempt", "non_gst"}
    # …and the computer buckets exactly those three into the two fields E sums.
    import inspect
    src = inspect.getsource(__import__("domain.gst.gstr3b_computer",
                                       fromlist=["x"]).compute_gstr3b)
    assert 'if s.supply_type in ("nil_rated", "exempt"):' in src
    assert 'elif s.supply_type == "non_gst":' in src
    assert 'elif s.supply_type == "zero_rated":' in src


# ── the reverse-charge OUTWARD supply, which is turnover and is not counted ──

def test_an_outward_reverse_charge_supply_is_reported_as_missing_from_F(books):
    """FOUND BY PROBING, not by the finding. `compute_gstr3b` accumulates a
    taxable supply into `outward_taxable_value` only `if not
    s.is_reverse_charge` — correct for Table 3.1(a), where the supplier
    declares no output tax on it. But §2(112) excludes only "the value of
    INWARD supplies on which tax is payable ... on reverse charge basis", so a
    GTA's or an advocate's own outward supplies ARE their turnover and belong
    in F.

    Leaving them out shrinks F, which makes E ÷ F and any Rule 42 or 43
    reversal LARGER — the safe direction, the same one the ceiling rounding
    takes. Safe is not silent: the answer says so."""
    rcm = _inv("taxable", 30_00_000)
    rcm["is_reverse_charge"] = True
    books["sales"] = [_inv("taxable", 70_00_000), rcm]
    t = _turnover()
    assert t["total_paise"] == 70_00_000        # the RCM supply is not in F
    assert len(t["caveats"]) == 1
    assert "3000000 paise" in t["caveats"][0]
    assert "reverse charge" in t["caveats"][0]


def test_a_client_with_no_such_supply_gets_no_caveat(books):
    """A sentence on every return is a sentence nobody reads."""
    books["sales"] = [_inv("taxable", 70_00_000)]
    assert _turnover()["caveats"] == []


def test_the_caveat_travels_onto_the_rule_43_answer(monkeypatch):
    """A caveat about how E and F were MEASURED belongs on the answer they
    produced, not in a log."""
    import services.gst_rule_43_service as r43
    monkeypatch.setattr(grs, "outward_turnover", lambda *a: {
        "period": PERIOD, "exempt_paise": 1, "total_paise": 2,
        "breakdown": {}, "caveats": ["the sentence"]})

    class _DB:
        def table(self, name):
            class _Q:
                def select(self, *a, **k): return self
                def eq(self, *a): return self
                def is_(self, *a): return self
                def gt(self, *a): return self
                def order(self, *a, **k): return self
                def limit(self, n): return self
                def execute(self): return type("R", (), {"data": []})()
            return _Q()

    out = r43.for_period(_DB(), FIRM, CLIENT, PERIOD)
    assert "the sentence" in out["caveats"]
