"""GST-10 — the annual return, and what it refuses to invent.

CGST Act s.44 with Rule 80(1): GSTR-9 consolidates the financial year's GSTR-1
and GSTR-3B, and the portal opens it once every one of them is furnished. So
the figures were all in this product already and nothing added them up; the tab
loaded a draft nothing created.

The tests that matter most here are the REFUSALS. A nil on an annual return is
a positive declaration that nothing was owed, so a row nobody can derive must
never come out as zero — it carries a note, and the note reaches the screen
beside its own figure.
"""
from __future__ import annotations

import pathlib

import pytest

from domain.gst import gstr9_builder as g9
from services.gst_return_service import gstr9_fy_periods

API = pathlib.Path(__file__).resolve().parent.parent
PERIODS = gstr9_fy_periods("2025-26")


# ── Reading a payload's rupees back to paise ────────────────────────────────

@pytest.mark.parametrize("rupees, paise", [
    (100000.00, 10000000),
    (0.01, 1),
    (1234.56, 123456),
    # The ones the naive conversion loses a paisa on — see the test below.
    (0.29, 29),
    (1.13, 113),
    (0.05, 5),
    (999999.99, 99999999),
    (None, 0),
    ("", 0),
    ("not money", 0),
])
def test_a_stored_rupee_figure_converts_to_paise_EXACTLY(rupees, paise):
    """Through `Decimal(str(v))`, never `int(v * 100)`.

    `0.29 * 100` is 28.999999999999996 in binary floating point and `int()` of
    it is 28. One paisa lost per figure, twelve months of them, on a return
    that has to foot — and the loss is silent and only on some values, which is
    the shape that survives a spot-check.
    """
    assert g9.paise_of(rupees) == paise


def test_the_naive_conversion_is_the_one_this_avoids():
    """Stated as a fact about binary floating point rather than as a style
    rule, so nobody 'simplifies' it back. Found by walking every 2-decimal
    value from 0.01 to 999.99, not chosen to make a point."""
    losses = [c for c in range(1, 100000) if int((c / 100) * 100) != c]
    assert len(losses) > 1000, (
        "a great many 2-decimal rupee figures lose a paisa through "
        "`int(value * 100)` — this is not an edge case")
    assert int(0.29 * 100) == 28               # a paisa short
    assert g9.paise_of(0.29) == 29             # exact
    for cents in losses[:200]:
        assert g9.paise_of(cents / 100) == cents


# ── The shape of a year ─────────────────────────────────────────────────────

def _g1(**over):
    base = {
        "b2cs": [{"txval": 20000.00, "iamt": 0, "camt": 1800.00,
                  "samt": 1800.00, "csamt": 0}],
        "b2b": [{"ctin": "27AAPFU0939F1ZV", "inv": [
            {"inv_typ": "R", "itms": [{"itm_det": {
                "txval": 100000.00, "iamt": 0, "camt": 9000.00,
                "samt": 9000.00, "csamt": 0}}]}]}],
        "exp": [
            {"exp_typ": "WPAY", "inv": [{"itms": [{"itm_det": {
                "txval": 300000.00, "iamt": 54000.00, "camt": 0,
                "samt": 0, "csamt": 0}}]}]},
            {"exp_typ": "WOPAY", "inv": [{"itms": [{"itm_det": {
                "txval": 200000.00, "iamt": 0, "camt": 0,
                "samt": 0, "csamt": 0}}]}]},
        ],
        "cdnr": [{"nt": [{"ntty": "C", "itms": [{"itm_det": {
            "txval": 5000.00, "iamt": 0, "camt": 450.00,
            "samt": 450.00, "csamt": 0}}]}]}],
        "hsn": {"data": [{"hsn_sc": "998314", "desc": "IT services",
                          "uqc": "OTH", "qty": 1.0, "txval": 100000.00,
                          "iamt": 0, "camt": 9000.00, "samt": 9000.00,
                          "csamt": 0}]},
    }
    base.update(over)
    return base


def _g3b(**over):
    base = {
        "payload_json": {
            "sup_details": {
                "isup_rev": {"txval": 0, "iamt": 1000, "camt": 0,
                             "samt": 0, "csamt": 0},
                "osup_nil_exmp": {"txval": 7000},
                "osup_nongst": {"txval": 3000},
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "iamt": 500, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "IMPS", "iamt": 200, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "ISRC", "iamt": 1000, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "ISD", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "OTH", "iamt": 0, "camt": 9000, "samt": 9000, "csamt": 0},
                ],
                "itc_inelg": [
                    {"ty": "RUL", "iamt": 100, "camt": 0, "samt": 0, "csamt": 0},
                ],
            },
        },
        "tax_liability_paise": 1000000,
        "itc_claimed_paise": 800000,
        "net_tax_paise": 200000,
        "cash_payable_paise": 100000,
    }
    base.update(over)
    return base


def _year(*, filed=True, months_with_data=1, **over):
    out = []
    for i, p in enumerate(PERIODS):
        out.append(g9.MonthlyReturn(
            period=p,
            gstr1_status="submitted" if filed else None,
            gstr3b_status="submitted" if filed else None,
            gstr1_payload=_g1() if i < months_with_data else None,
            gstr3b_row=_g3b() if i < months_with_data else None))
    return out


def _build(**kw):
    kw.setdefault("financial_year", "2025-26")
    kw.setdefault("gstin", "27AAPFU0939F1ZV")
    kw.setdefault("months", _year())
    return g9.build_gstr9(**kw)


def _row(out: g9.GSTR9, table: str, code: str) -> g9.Row:
    return next(r for r in out.tables[table] if r.code == code)


# ── Part II ─────────────────────────────────────────────────────────────────

def test_the_b2b_section_is_split_by_inv_typ_not_lumped_into_4B():
    """Tables 4B, 4D, 4E and 5B all ride in the GSTN `b2b` section, told apart
    only by `inv_typ`. Putting every one on 4B declares a deemed export and an
    SEZ supply as ordinary B2B."""
    months = _year(months_with_data=0)
    months[0] = g9.MonthlyReturn(
        period=PERIODS[0], gstr1_status="submitted", gstr3b_status="submitted",
        gstr1_payload={"b2b": [{"inv": [
            {"inv_typ": "R", "itms": [{"itm_det": {"txval": 100.00}}]},
            {"inv_typ": "DE", "itms": [{"itm_det": {"txval": 200.00}}]},
            {"inv_typ": "SEWP", "itms": [{"itm_det": {"txval": 300.00}}]},
            {"inv_typ": "SEWOP", "itms": [{"itm_det": {"txval": 400.00}}]},
        ]}]},
        gstr3b_row={})
    out = _build(months=months)
    assert _row(out, "4", "4B").txval == 10000
    assert _row(out, "4", "4E").txval == 20000
    assert _row(out, "4", "4D").txval == 30000
    # SEZ WITHOUT payment bears no tax, so it is Table 5, not Table 4.
    assert _row(out, "5", "5B").txval == 40000


def test_an_export_on_payment_and_one_under_LUT_go_to_DIFFERENT_tables():
    """IGST Act s.16(3): with payment of tax and claim the tax back (Table 4C),
    or under a bond or LUT and claim the unutilised credit (Table 5A)."""
    out = _build()
    assert _row(out, "4", "4C").txval == 30000000
    assert _row(out, "4", "4C").iamt == 5400000
    assert _row(out, "5", "5A").txval == 20000000
    assert _row(out, "5", "5A").iamt == 0


def test_a_credit_note_REDUCES_4N_and_a_debit_note_increases_it():
    out = _build()
    h = _row(out, "4", "4H")
    cn = _row(out, "4", "4I")
    n = _row(out, "4", "4N")
    assert cn.txval == 500000
    assert n.txval == h.txval - cn.txval
    assert n.camt == h.camt - cn.camt


def test_the_reverse_charge_LIABILITY_is_table_4G_and_comes_from_GSTR_3B():
    """It is an INWARD supply on which the recipient pays, so GSTR-1 has no row
    for it at all — GSTR-3B Table 3.1(d) is where it was declared."""
    out = _build()
    assert _row(out, "4", "4G").iamt == 100000   # ₹1,000 whole rupees, one month


def test_the_HSN_summary_is_the_twelve_monthly_table_12s_added_up():
    out = _build(months=_year(months_with_data=3))
    assert len(out.hsn) == 1
    assert out.hsn[0]["hsn_sc"] == "998314"
    assert out.hsn[0]["txval_paise"] == 3 * 10000000
    assert out.hsn[0]["qty"] == 3.0


# ── Part III ────────────────────────────────────────────────────────────────

def test_table_4A_s_FIVE_ROWS_ARE_table_6_s_rows():
    """GST-24 split imports of services out of the domestic reverse-charge row
    and PUR-18 gave imports of goods a document, so each is already told apart
    in the return being consolidated. There is nothing to apportion here."""
    out = _build()
    assert _row(out, "6", "6E").iamt == 50000     # IMPG
    assert _row(out, "6", "6F").iamt == 20000     # IMPS
    assert _row(out, "6", "6C+6D").iamt == 100000  # ISRC
    assert _row(out, "6", "6B").camt == 900000     # OTH


def test_6A_is_the_SUM_of_the_five_rows_and_6O_equals_it():
    out = _build()
    a, o = _row(out, "6", "6A"), _row(out, "6", "6O")
    assert (a.iamt, a.camt, a.samt) == (o.iamt, o.camt, o.samt)
    assert a.iamt == 50000 + 20000 + 100000


def test_the_6B_TOTAL_is_derived_and_only_its_SPLIT_is_refused():
    """The amount is known — Table 4(A)(5) is exactly 'inward supplies other
    than imports and reverse charge'. What nothing records is whether a supply
    was an input, a capital good or an input service, which is a judgement
    about USE."""
    out = _build()
    assert _row(out, "6", "6B").camt == 900000
    assert _row(out, "6", "6B").note is None
    for code in ("6B(1)", "6B(2)", "6B(3)"):
        r = _row(out, "6", code)
        assert r.note, code
        assert r.camt == 0
    assert any("three-way split" in g for g in out.gaps)


def test_a_stated_6B_split_that_does_not_ADD_UP_is_reported():
    out = _build(inputs=g9.AnnualInputs(
        itc_inputs={"cgst_paise": 100000},
        itc_capital_goods={"cgst_paise": 100000},
        itc_input_services={"cgst_paise": 100000}))
    assert any("do not add up" in g for g in out.gaps)


def test_a_stated_6B_split_that_DOES_add_up_is_not_complained_about():
    out = _build(inputs=g9.AnnualInputs(
        itc_inputs={"cgst_paise": 400000, "sgst_paise": 400000},
        itc_capital_goods={"cgst_paise": 200000, "sgst_paise": 200000},
        itc_input_services={"cgst_paise": 300000, "sgst_paise": 300000}))
    assert not any("do not add up" in g for g in out.gaps)
    assert not any("three-way split" in g for g in out.gaps)


def test_ISD_and_the_two_TRAN_rows_are_NAMED_never_declared_nil():
    out = _build()
    for code in ("6G", "6K", "6L"):
        assert _row(out, "6", code).note, code
    assert any("ISD" in g and "TRAN" in g for g in out.gaps)


def test_the_6C_6D_SPLIT_is_refused_with_the_reason():
    """`vendors.gst_registration_status` records it (migration 388) but the
    monthly GSTR-3B this consolidates accumulates one combined figure."""
    r = _row(_build(), "6", "6C+6D")
    assert r.note and "UNREGISTERED" in r.note
    assert any("6C and 6D" in g for g in _build().gaps)


# ── Table 7: the per-ground split GSTR-3B cannot give ───────────────────────

def test_table_7_splits_by_STATUTORY_GROUND_which_3B_cannot():
    """GSTR-3B Table 4(B) has two boxes, permanent and reclaimable, and Rules
    38, 42, 43 and s.17(5) share one. `itc_reversal_register` records the
    ground (migration 362), which is what Table 7 asks for."""
    out = _build(reversals=[
        g9.Reversal("rule_37", igst_paise=100),
        g9.Reversal("rule_42", cgst_paise=200),
        g9.Reversal("rule_43", sgst_paise=300),
        g9.Reversal("section_17_5_h", cgst_paise=400),
        g9.Reversal("rule_38", igst_paise=500),
    ])
    assert _row(out, "7", "7A").iamt == 100
    assert _row(out, "7", "7C").camt == 200
    assert _row(out, "7", "7D").samt == 300
    assert _row(out, "7", "7E").camt == 400
    assert _row(out, "7", "7H").iamt == 500     # Rule 38 has no row of its own
    assert _row(out, "7", "7I").iamt == 600


def test_rule_39_is_NAMED_because_no_ISD_invoice_is_modelled():
    assert "ISD" in (_row(_build(), "7", "7B").note or "")


def test_7J_is_6O_LESS_7I():
    out = _build(reversals=[g9.Reversal("rule_37", igst_paise=100)])
    assert (_row(out, "7", "7J").iamt
            == _row(out, "6", "6O").iamt - _row(out, "7", "7I").iamt)


def test_a_ground_with_no_row_is_NAMED_and_kept_OUT_of_the_total():
    """Silently folding an unknown ground into 'other reversals' would put a
    figure on a statutory return nobody decided the home of."""
    out = _build(reversals=[g9.Reversal("some_new_ground", igst_paise=999)])
    assert _row(out, "7", "7I").iamt == 0
    assert any("some_new_ground" in g for g in out.gaps)


# ── Table 8 ─────────────────────────────────────────────────────────────────

def test_8A_is_left_for_the_portal_and_says_so():
    out = _build()
    assert _row(out, "8", "8A").note
    assert any("8A" in g for g in out.gaps)


def test_8B_is_DERIVED_even_though_6B_s_split_is_not():
    """8B is 6(B) + 6(H), and both totals are derived. The three-way split of
    6B is what is missing, and 8B does not need it."""
    out = _build()
    b = _row(out, "8", "8B")
    assert b.note is None
    assert b.camt == _row(out, "6", "6B").camt + _row(out, "6", "6H").camt


def test_8D_appears_only_when_there_is_an_8A_to_subtract_from():
    assert all(r.code != "8D" for r in _build().tables["8"])
    with_2b = _build(two_b={"igst_paise": 999})
    assert any(r.code == "8D" for r in with_2b.tables["8"])


def test_8C_is_a_fact_about_the_NEXT_year_and_is_refused():
    assert _row(_build(), "8", "8C").note
    assert any("next financial year" in g for g in _build().gaps)


# ── Completeness ────────────────────────────────────────────────────────────

def test_a_year_with_every_return_filed_is_COMPLETE():
    assert _build(months=_year(filed=True)).is_complete


def test_a_year_with_an_UNFILED_month_is_not_and_names_it():
    months = _year(filed=True)
    months[5] = g9.MonthlyReturn(period=months[5].period, gstr1_status="draft",
                                 gstr3b_status="submitted")
    out = _build(months=months)
    assert not out.is_complete
    assert any(months[5].period in g and "GSTR-1 outstanding" in g for g in out.gaps)
    assert any("Rule 80(1)" in g for g in out.gaps)


def test_a_FILED_month_whose_payload_this_product_never_held_is_NAMED():
    """The CA prepared it elsewhere and recorded the ARN here. Its tax is in the
    GSTR-3B row and its Table 4 breakdown is not, so the breakdown is short by
    whatever that month declared — and saying nothing would present a short
    Table 4 as the year's."""
    months = [g9.MonthlyReturn(period=p, gstr1_status="submitted",
                               gstr3b_status="submitted")
              for p in PERIODS]
    out = _build(months=months)
    assert any("does not hold their GSTR-1" in g for g in out.gaps)
    assert any("does not hold their GSTR-3B payload" in g for g in out.gaps)


# ── What is deliberately not built ──────────────────────────────────────────

@pytest.mark.parametrize("table", ["10-14", "15", "16", "18", "19"])
def test_each_unbuilt_table_says_WHY(table):
    assert g9.NOT_BUILT[table].strip()


def test_the_late_fee_table_points_at_the_refusal_that_already_exists():
    """Table 19 must not invent a late fee for the ANNUAL return.

    THIS TEST NAMED A SPELLING AND THE SPELLING MOVED. It asserted
    `LATE_FEE_RATES == {}`, which was a fine proxy while the table was empty
    for every return — and the notified GSTR-1 and GSTR-3B ladders
    (Notifications 19/2021 and 20/2021) have since been written in, so the
    proxy failed on a change that did not touch this rule at all. The fourth
    or fifth time this pattern has been fixed in this repository.

    The RULE is about GSTR-9 specifically, and it still holds. s.47(2)'s
    annual-return fee is a DIFFERENT figure from the monthly one — ₹200 a day
    combined, capped at a percentage of the taxpayer's turnover in the State,
    reduced again by its own notifications — and none of it is held here. So
    the assertion is what it was always about: ask for a GSTR-9 late fee and be
    REFUSED, whatever other returns the table has learned."""
    from datetime import date as _d
    from domain.gst.late_filing import late_fee
    out = late_fee(return_type="gstr9", financial_year="2025-26",
                   due_date=_d(2026, 12, 31), filed_on=_d(2027, 2, 15))
    assert out["refused"] is True, (
        "s.47(2)'s annual-return fee is not held — Table 19 must not invent one"
    )
    assert "fee_paise" not in out
    assert "late_filing" in g9.NOT_BUILT["19"]


# ── The inv_typ map is read off the builder that writes them ────────────────

def test_every_inv_typ_the_GSTR1_BUILDER_writes_has_a_home_here():
    """A value added to `gstr1_builder._INV_TYP` without a row here would fall
    into 4B, which declares a deemed export as an ordinary B2B supply."""
    from domain.gst.gstr1_builder import _INV_TYP
    assert set(_INV_TYP.values()) <= set(g9.INV_TYP_ROW), (
        f"{sorted(set(_INV_TYP.values()) - set(g9.INV_TYP_ROW))} has no Table 4 "
        f"or Table 5 row in gstr9_builder.INV_TYP_ROW")


def test_nothing_here_files_or_posts():
    """The builder is PURE — no database handle reaches it, so it cannot write
    even by accident, and nothing in it can reach a portal."""
    import inspect
    src = (API / "domain" / "gst" / "gstr9_builder.py").read_text()
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in src
    for forbidden in ("requests.", "httpx.", "urllib", "_create_journal",
                      "get_supabase", "supabase", ".table("):
        assert forbidden not in src, forbidden
    # And no entry point takes one.
    assert "db" not in inspect.signature(g9.build_gstr9).parameters
    assert _build().as_dict()["ca_review_required"] is True


# ── The service, run rather than read ───────────────────────────────────────
#
# Two things the pure builder cannot show, and both would be silent: that the
# figures come from `payload_json` rather than from `gstr3b_returns`' own
# per-head paise columns (which `save_gstr3b` has NEVER written, so reading
# them gives a confident nil for every month of every client), and that a
# GSTR-9 draft row in the shared `gstr1_returns` store is not mistaken for a
# monthly GSTR-1.


class _Q:
    def __init__(self, store, table):
        self._rows = list(store.get(table, []))

    def select(self, *a, **k): return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def gte(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col) or "") >= str(val)]
        return self

    def lte(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col) or "") <= str(val)]
        return self

    def in_(self, col, vals):
        wanted = {str(v) for v in vals}
        self._rows = [r for r in self._rows if str(r.get(col) or "") in wanted]
        return self

    def is_(self, col, _null):
        self._rows = [r for r in self._rows if r.get(col) is None]
        return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, **tables): self.store = tables
    def table(self, name): return _Q(self.store, name)


def _service_db(**over):
    g1 = [{"id": f"g1-{i}", "firm_id": "F1", "client_id": "C1", "period": p,
           "status": "submitted", "return_type": "gstr1",
           "gstin": "27AAPFU0939F1ZV", "payload_json": _g1()}
          for i, p in enumerate(PERIODS)]
    g3 = [{"id": f"g3-{i}", "firm_id": "F1", "client_id": "C1", "period": p,
           "status": "submitted", "gstin": "27AAPFU0939F1ZV", **_g3b()}
          for i, p in enumerate(PERIODS)]
    store = {"gstr1_returns": g1, "gstr3b_returns": g3,
             "itc_reversal_register": [], "gstr2b_reconciliations": []}
    store.update(over)
    return _FakeDB(**store)


def test_a_FIXTURE_MAY_NOT_INVENT_A_COLUMN():
    """How the mock suite came to agree with a query the database rejects.

    The first draft of `_reversals` filtered `itc_reversal_register` on a
    `reversal_date`, and the fixtures below carried one, so every test here
    passed. The column does not exist: PostgREST answers PGRST204 and performs
    NO read, so Table 7 of every annual return would have been empty against
    production and right in mock mode.
    `tests/test_backend_columns_exist_pg.py` caught it, but only after a
    twenty-six minute real-Postgres run — and only because the query was in
    the SERVICE. A fixture is the other half of the same mistake and nothing
    was checking it.

    The rule, not a spelling of it: every key of every fixture row this module
    stands up must be a real column of the table it claims to be. A table the
    point-in-time snapshot predates is skipped, the same carve-out
    `production_types` makes for a write.
    """
    from tests import production_types as pt
    db = _service_db(itc_reversal_register=[_rev("r1", "092025", 500)])
    unknown: list[str] = []
    for table, rows in db.store.items():
        if not pt.known_table(table):
            continue
        known = set(pt._SCHEMA[table])
        for row in rows:
            for key in row:
                if key not in known and (table, key) not in pt.ADDED_AFTER_THE_SNAPSHOT:
                    unknown.append(f"{table}.{key}")
    assert not unknown, (
        "these fixture rows name columns production does not have, so a query "
        "filtering on one would pass here and read nothing there: "
        + ", ".join(sorted(set(unknown))))


def test_the_service_reads_the_PAYLOAD_not_the_per_head_paise_columns():
    """`save_gstr3b` writes `tax_liability_paise`, `itc_claimed_paise`,
    `net_tax_paise`, `rcm_cash_paise` and `cash_payable_paise` — and NONE of
    migration 036's per-head columns, which keep their DEFAULT 0. Reading them
    would give a confident nil for every month of every client, which is the
    worst possible answer on an annual return."""
    from services import gstr9_service
    db = _service_db()
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    six_a = next(r for r in out["tables"]["6"] if r["code"] == "6A")
    assert six_a["igst_paise"] == 12 * (50000 + 20000 + 100000)
    assert out["is_complete"] is True


def test_a_GSTR9_DRAFT_in_the_shared_store_is_not_read_as_a_monthly_GSTR1():
    """`gstr1_returns` holds BOTH since migration 053, and a GSTR-9 row carries
    `period = 'FY2025-26'`. Without the return_type filter its own payload
    would be consolidated into itself."""
    from services import gstr9_service
    db = _service_db()
    # `zz-` so `fetch_all`'s ORDER BY id puts it LAST and it would WIN the
    # per-period dict without the filter. Ordering must not be what makes this
    # test pass.
    db.store["gstr1_returns"].append({
        "id": "zz-annual", "firm_id": "F1", "client_id": "C1",
        "period": PERIODS[0], "status": "submitted", "return_type": "gstr9",
        "gstin": "27AAPFU0939F1ZV",
        "payload_json": {"b2cs": [{"txval": 99999999.00}]}})
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    four_a = next(r for r in out["tables"]["4"] if r["code"] == "4A")
    assert four_a["txval_paise"] == 12 * 2000000, (
        "the annual draft's own payload was consolidated into the annual return")


def test_the_service_reads_only_ONE_registrations_returns():
    """A client may hold several GSTINs (GST-20), and each files its own annual
    return. Consolidating both into one would declare another registration's
    supplies under this one."""
    from services import gstr9_service
    db = _service_db()
    for i, p in enumerate(PERIODS):
        # A DIFFERENT figure, and a `zz-` id so it sorts LAST and would win the
        # per-period dict without the GSTIN filter. An identical payload would
        # make this test pass whether the filter was there or not.
        db.store["gstr1_returns"].append({
            "id": f"zz-other-{i}", "firm_id": "F1", "client_id": "C1",
            "period": p, "status": "submitted", "return_type": "gstr1",
            "gstin": "29AAPFU0939F1ZR",
            "payload_json": _g1(b2cs=[{"txval": 77777777.00, "iamt": 0,
                                       "camt": 0, "samt": 0, "csamt": 0}])})
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    four_a = next(r for r in out["tables"]["4"] if r["code"] == "4A")
    assert four_a["txval_paise"] == 12 * 2000000, (
        "the OTHER registration's supplies were declared under this one")


def _rev(rid: str, period: str, cgst: int) -> dict:
    return {"id": rid, "firm_id": "F1", "client_id": "C1", "period": period,
            "reason_code": "rule_42", "cgst_paise": cgst}


def test_the_reversal_register_is_read_for_the_FINANCIAL_YEAR():
    """The year is selected by `period`, which is the column the register HAS.

    `itc_reversal_register` carries no reversal date at all — migration 285
    gives it `period`, "MMYYYY of the GSTR-3B this row is declared in". A
    filter naming a column production does not have is not a narrower read: it
    is PGRST204 and NO read, so Table 7 would be empty against the real
    database and right in every mock test. It is also the statutorily correct
    key: s.44 with Rule 80(1) consolidates the returns FURNISHED for the year.
    """
    from services import gstr9_service
    db = _service_db(itc_reversal_register=[
        _rev("r1", "092025", 500),
        _rev("r2", "092026", 900),   # the NEXT financial year
    ])
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    seven_c = next(r for r in out["tables"]["7"] if r["code"] == "7C")
    assert seven_c["cgst_paise"] == 500


def test_the_twelve_periods_are_NAMED_because_MMYYYY_does_not_sort():
    """A `gte('042025').lte('032026')` reads TEXT, and '042025' > '032026'.

    So a range would keep NOTHING of the year it was asked for, and a range
    the other way round ('032026'..'042025' reversed) keeps May 2025 through
    March of every later year. Each of the twelve months carries a DIFFERENT
    figure, so a filter that drops or admits any one of them changes the total
    — an assertion on a single month would pass on nine of the twelve wrong
    filters.
    """
    from services import gstr9_service
    inside = [_rev(f"in-{i}", p, 100 + i) for i, p in enumerate(PERIODS)]
    outside = [
        _rev("before", "032025", 7_000),   # March of the PREVIOUS FY
        _rev("after", "042026", 9_000),    # April of the NEXT FY
        _rev("way-after", "122030", 11_000),
    ]
    db = _service_db(itc_reversal_register=inside + outside)
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    seven_c = next(r for r in out["tables"]["7"] if r["code"] == "7C")
    assert seven_c["cgst_paise"] == sum(100 + i for i in range(12)), (
        "the year is the twelve named periods — not a string range over them")


def test_a_reversal_belonging_to_another_client_or_firm_is_not_consolidated():
    from services import gstr9_service
    db = _service_db(itc_reversal_register=[
        _rev("mine", "092025", 500),
        {"id": "zz-other-client", "firm_id": "F1", "client_id": "C2",
         "period": "092025", "reason_code": "rule_42", "cgst_paise": 4_000},
        {"id": "zz-other-firm", "firm_id": "F2", "client_id": "C1",
         "period": "092025", "reason_code": "rule_42", "cgst_paise": 8_000},
    ])
    out = gstr9_service.build(db, "F1", "C1", financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    seven_c = next(r for r in out["tables"]["7"] if r["code"] == "7C")
    assert seven_c["cgst_paise"] == 500


def test_a_malformed_financial_year_is_a_422_not_a_500():
    from fastapi import HTTPException
    from services import gstr9_service
    with pytest.raises(HTTPException) as e:
        gstr9_service.build(_service_db(), "F1", "C1",
                            financial_year="not-a-year",
                            gstin="27AAPFU0939F1ZV")
    assert e.value.status_code == 422


def test_the_service_names_table_8A_as_the_portals():
    from services import gstr9_service
    out = gstr9_service.build(_service_db(), "F1", "C1",
                              financial_year="2025-26",
                              gstin="27AAPFU0939F1ZV")
    assert "8A" in out["not_built"]
    assert "auto-populated by the portal" in out["not_built"]["8A"]


def test_an_UNREADABLE_payload_figure_is_VALIDATED_not_swallowed():
    """A bare `except` around a figure that belongs on a statutory return is a
    silent swallow — the figure disappears and nothing says so. The shape of a
    GSTN money field is known, so there is nothing to guess: anything that is
    not a number is not one."""
    import ast
    tree = ast.parse((API / "domain" / "gst" / "gstr9_builder.py").read_text())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert not handlers, (
        "no exception handler at all in this module — every reader validates. "
        f"Found one at line {handlers[0].lineno if handlers else '?'}.")
    assert g9.paise_of("not money") == 0
    assert g9.paise_of(True) == 0, "a bool is an int in Python and would be ₹1"
    assert g9.paise_of("1e3") == 100000, "scientific notation is still a number"


def test_the_HSN_QUANTITY_is_validated_the_same_way():
    months = [g9.MonthlyReturn(
        period=PERIODS[0], gstr1_status="submitted", gstr3b_status="submitted",
        gstr1_payload={"hsn": {"data": [
            {"hsn_sc": "1001", "qty": "bad", "txval": 100.00},
            {"hsn_sc": "1001", "qty": 2.5, "txval": 100.00},
        ]}}, gstr3b_row={})]
    out = _build(months=months)
    assert out.hsn[0]["qty"] == 2.5
    assert out.hsn[0]["txval_paise"] == 20000
