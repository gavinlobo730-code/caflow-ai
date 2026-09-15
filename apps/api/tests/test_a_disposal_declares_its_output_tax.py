"""A fixed-asset disposal is a supply, and CGST Act s.18(6) says what it costs
(FA-08b).

WHAT WAS WRONG
    `journal_for_asset_disposal` posted four lines — accumulated depreciation
    cleared, the whole proceeds to bank, the asset out at cost, and the gain or
    loss balancing — and no tax line of any kind. `DisposalIn` carried no field
    that could have driven one. So the sale of a capital asset, which is a
    supply, was never declared: no output tax in the ledger, nothing in the
    return, and the CA had to remember to raise a separate sales invoice with
    nothing anywhere prompting them.

    It is not merely "tax on the sale" either. s.18(6) charges the HIGHER of
    the input tax credit taken on the asset — reduced for the time it was held
    — and the tax on the transaction value under s.15. An asset sold cheap
    early in its life pays back credit rather than tax on the price, and that
    is the case a plain output-tax line would under-declare.

WHAT IS PINNED HERE
    The arithmetic of both limbs and both readings of the reduction rule; that
    the journal BALANCES with the tax on it and measures the gain on the
    consideration NET of tax; that the return declares it in Table 3.1(a); and
    every refusal — an unstated supply, an unstated rate, an asset whose credit
    position was never recorded.

⚠️ TWO RULES PRESCRIBE THE REDUCTION AND THEY DISAGREE, so both readings are
    reported and neither is chosen. Rule 40(2) is five percentage points a
    quarter or part quarter from the invoice date; Rule 44(6), through Rule
    44(1)(b), pro-rates the credit over the remaining useful life in months out
    of sixty. Neither could be read against the Rules from this environment.
    The tests below assert BOTH figures precisely, so a later edit that quietly
    picks one fails here.
"""
from __future__ import annotations

import pytest

import routers.fixed_assets as fa
import services.gst_return_service as grs
import services.phase2_journal_service as pjs
from domain.gst import section_18_6 as s186
from models.accounting import DisposalIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM, CLIENT = "FIRM-A", "CLI"
GSTIN = "27AAAAA0000A1Z2"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}


# ── the engine, on its own ───────────────────────────────────────────────────

def _heads(c=0, s=0, i=0):
    return s186.TaxHeads(c, s, i)


def _compute(**kw):
    """A Rs 10,00,000 machine bought 15-01-2023 carrying Rs 1,80,000 of credit
    (18%, intra-state), sold 20-03-2026 for Rs 5,90,000 inclusive."""
    base = dict(credit_taken=_heads(90_000_00, 90_000_00), itc_was_taken=True,
                invoice_date="2023-01-15", disposal_date="2026-03-20",
                proceeds_paise=5_90_000_00, rate_bps=1800,
                is_interstate=False, is_supply=True)
    base.update(kw)
    return s186.compute(**base)


def _by(result, reading):
    return next(r for r in result.readings if r.reading == reading)


def test_both_readings_are_reported_and_they_differ():
    """38 months after the invoice: Rule 40(2) has run 13 quarters (twelve
    whole and a part) and leaves 35% of the credit; Rule 44(6) leaves 22 of 60
    months, 36.67%. The difference is real money, which is why neither is
    chosen."""
    r = _compute()
    assert [x.reading for x in r.readings] == [s186.BY_QUARTERS, s186.BY_MONTHS]
    assert _by(r, s186.BY_QUARTERS).elapsed == 13
    assert _by(r, s186.BY_MONTHS).elapsed == 38
    assert _by(r, s186.BY_QUARTERS).reduced_credit.total_paise == 63_000_00
    assert _by(r, s186.BY_MONTHS).reduced_credit.total_paise == 66_000_00


def test_the_higher_limb_wins_and_the_basis_says_which():
    """Rs 5,90,000 at 18% inclusive is Rs 90,000 of tax on the transaction
    value, above either reduced credit (Rs 63,000 / Rs 66,000), so the value
    limb is what is payable — and the two readings then AGREE, which is the
    common case on an asset sold at a sensible price."""
    r = _compute()
    assert r.tax_on_transaction_value.total_paise == 90_000_00
    for x in r.readings:
        assert x.basis == "transaction_value"
        assert x.amount_payable.total_paise == 90_000_00
    assert r.readings_agree is True


def test_an_asset_sold_cheap_early_pays_back_credit_instead():
    """The case s.18(6) exists for, and the one a plain output-tax line would
    under-declare by a factor of eighty. Sold for Rs 11,800 eleven months after
    a purchase that carried Rs 1,80,000 of credit: the tax on the price is
    Rs 1,800 and the reduced credit is Rs 1,44,000 or Rs 1,47,000 depending on
    the Rule — so the credit limb is the charge, and the two readings DIFFER,
    which is exactly when the ambiguity costs money."""
    r = _compute(disposal_date="2023-12-20", proceeds_paise=11_800_00)
    assert r.tax_on_transaction_value.total_paise == 1_800_00
    q, m = _by(r, s186.BY_QUARTERS), _by(r, s186.BY_MONTHS)
    assert q.elapsed == 4 and m.elapsed == 11        # 11 months and 5 days
    assert q.amount_payable.total_paise == 1_44_000_00   # 80% of 1,80,000
    assert m.amount_payable.total_paise == 1_47_000_00   # 49/60 of 1,80,000
    assert q.basis == m.basis == "reduced_credit"
    assert r.readings_agree is False


def test_the_reduction_rounds_up():
    """A sum the taxpayer OWES. Understating it leaves a residual demand with
    s.50(1) interest running, so both readings round the reduced credit UP —
    the same direction ESI and the GST late-filing interest take."""
    r = _compute(credit_taken=_heads(3_33_333, 0, 0), disposal_date="2023-04-20")
    # 3 months -> Rule 44(6) keeps 57/60. 333333 * 57 / 60 = 316666.35 -> 316667.
    assert _by(r, s186.BY_MONTHS).reduced_credit.cgst_paise == 3_16_667


def test_a_part_quarter_counts_as_a_whole_one():
    """Rule 40(2)'s own words: "for every quarter or PART THEREOF". Three whole
    months is exactly one quarter; a single day more is two, because a second
    quarter has begun.

    THE PART DAYS ARE THE POINT. Counting whole months and dividing by three
    loses that day and under-charges the reduction by a whole quarter on every
    disposal landing just past a quarter end."""
    assert _by(_compute(disposal_date="2023-04-15"), s186.BY_QUARTERS).elapsed == 1
    assert _by(_compute(disposal_date="2023-04-16"), s186.BY_QUARTERS).elapsed == 2
    # And any elapsed time at all is one quarter, including none.
    assert _by(_compute(disposal_date="2023-01-15"), s186.BY_QUARTERS).elapsed == 1
    assert _by(_compute(disposal_date="2023-01-16"), s186.BY_QUARTERS).elapsed == 1


def test_a_part_month_does_not_count_as_elapsed():
    """Rule 44(1)(b) counts the REMAINING useful life, and a convention is
    needed for the part month. Not counting it leaves the remaining life
    larger, the reduced credit larger and the amount payable larger or equal —
    the direction that cannot leave a shortfall."""
    assert _by(_compute(disposal_date="2023-02-14"), s186.BY_MONTHS).elapsed == 0
    assert _by(_compute(disposal_date="2023-02-15"), s186.BY_MONTHS).elapsed == 1


def test_a_blocked_asset_is_outside_the_section():
    """s.18(6) reaches capital goods "on which input tax credit has been
    taken". Where s.17(5) blocked it, the tax was capitalised and there is no
    credit to reduce — only the tax on the sale."""
    r = _compute(itc_was_taken=False)
    assert len(r.readings) == 1
    assert r.readings[0].basis == "transaction_value"
    assert any("does not reach the supply" in c for c in r.caveats)


def test_an_asset_that_does_not_say_is_refused_not_assumed():
    """A pre-343 row records nothing about the credit. Reading that as "no
    credit" would drop the limb that can be the higher one, so it is a NAMED
    gap instead."""
    r = _compute(itc_was_taken=None)
    assert any("does not record whether input tax credit was taken" in g
               for g in r.gaps)
    assert all(x.basis == "transaction_value" for x in r.readings)


def test_a_disposal_nobody_has_classified_names_the_gap():
    r = _compute(is_supply=None)
    assert any("whether this disposal is a SUPPLY" in g for g in r.gaps)


def test_a_disposal_recorded_as_not_a_supply_charges_nothing():
    r = _compute(is_supply=False)
    assert r.applies is False
    assert r.tax_on_transaction_value.total_paise == 0
    assert any("not a supply" in c for c in r.caveats)


def test_an_unstated_rate_refuses_the_value_limb():
    r = _compute(rate_bps=None)
    assert r.tax_on_transaction_value.total_paise == 0
    assert any("No GST rate is recorded" in g for g in r.gaps)


def test_a_head_mismatch_is_named_never_resolved():
    """Bought locally, sold across a state border. s.18(6) does not say which
    head the reduced-credit limb is paid in when they differ."""
    r = _compute(is_interstate=True)
    assert any("credit was taken as CGST + SGST and the sale is charged as IGST"
               in c for c in r.caveats)


def test_the_scrap_proviso_is_named_and_never_applied():
    """The proviso lets refractory bricks, moulds and dies, jigs and fixtures
    supplied AS SCRAP pay on the transaction value alone. It is the taxable
    person's OPTION, on an asset class this register does not record."""
    assert any("refractory bricks" in c for c in _compute().caveats)


def test_the_two_limbs_are_ranked_on_the_TOTAL_and_not_head_by_head():
    """s.18(6) compares two AMOUNTS, singular. Rule 44(6)'s "determined
    separately for ... central tax, State tax ... and integrated tax" governs
    how limb (a) is WORKED OUT, not how the two limbs are ranked.

    Head by head, a machine bought inter-state and sold locally would pay the
    credit limb on IGST (where the sale charges nothing) and the value limb on
    CGST and SGST (where the credit is nil) — the two added together, which is
    not a figure the section describes."""
    r = _compute(credit_taken=_heads(i=1_80_000_00),  # all IGST
                 disposal_date="2023-12-20", proceeds_paise=11_800_00)
    # The reduced credit is Rs 1,44,000 of IGST against Rs 1,800 of CGST+SGST
    # on the sale, so the credit limb is higher in TOTAL — and is what is paid.
    q = _by(r, s186.BY_QUARTERS)
    assert q.basis == "reduced_credit"
    assert q.amount_payable.total_paise == 1_44_000_00
    assert q.amount_payable.igst_paise == 1_44_000_00
    assert q.amount_payable.cgst_paise == 0


def test_a_rate_the_engine_does_not_hold_is_refused_here_too():
    """The model refuses one and so does the preview, but this is the module
    that turns a rate into money and it does not trust its callers."""
    r = _compute(rate_bps=1700)
    assert r.tax_on_transaction_value.total_paise == 0
    assert any("not a rate this engine holds" in g for g in r.gaps)


def test_the_two_rules_are_named_when_the_credit_limb_exists():
    assert any("Rule 40(2)" in c and "Rule 44(6)" in c for c in _compute().caveats)
    # …and not when there is no credit to reduce, where they say nothing.
    assert not any("Rule 40(2)" in c for c in _compute(itc_was_taken=False).caveats)


# ── the disposal, end to end ─────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [fa, grs, pjs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01"})
    d.coa = seed_standard_coa(d, FIRM, CLIENT)
    for name in ("Plant & Machinery", "Accumulated Depreciation",
                 "Profit on Asset Disposal", "Loss on Asset Disposal"):
        d.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": CLIENT, "system_account_key": None,
            "account_name": name, "is_active": True})
    monkeypatch.setattr(fa, "_db", lambda: d)
    monkeypatch.setattr(fa.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date",
                        lambda *a, **k: None)
    return d


def _asset(db, **kw):
    row = {
        "firm_id": FIRM, "client_id": CLIENT, "asset_name": "Lathe",
        "asset_code": "FA-001", "asset_category": "Plant & Machinery",
        "is_disposed": False, "purchase_date": "2025-04-01",
        "purchase_cost_paise": 10_00_000_00,
        "accumulated_depreciation_paise": 2_00_000_00,
        "depreciation_posted_through": "2025-05-31",
        "cgst_paise": 90_000_00, "sgst_paise": 90_000_00, "igst_paise": 0,
        "itc_eligible": True, "deleted_at": None, "notes": None,
    }
    row.update(kw)
    return db.seed("fixed_assets", row)


def _dispose(db, asset, **kw):
    payload = {"disposal_type": "Sale", "sale_proceeds_paise": 5_90_000_00,
               "disposal_date": "2025-06-20", "is_supply": True,
               "gst_rate_bps": 1800}
    payload.update(kw)
    return fa.dispose_asset(asset["id"], DisposalIn(**payload), CALLER)["data"]


def _lines(db, journal_id):
    return [l for l in db.rows("journal_lines")
            if l.get("journal_entry_id") == journal_id]


def _named(db, journal_id, needle):
    by_id = {a["id"]: a["account_name"] for a in db.rows("chart_of_accounts")}
    return [l for l in _lines(db, journal_id)
            if needle.lower() in by_id.get(l["account_id"], "").lower()]


def test_the_disposal_journal_carries_the_output_tax(db):
    """Rs 5,90,000 at 18% intra-state is Rs 45,000 on each of CGST and SGST,
    backed out of the proceeds — so the journal balances with no plug."""
    out = _dispose(db, _asset(db))
    lines = _lines(db, out["journal_entry_id"])
    assert sum(int(l["debit_paise"]) for l in lines) == \
           sum(int(l["credit_paise"]) for l in lines)
    tax = _named(db, out["journal_entry_id"], "GST Output")
    assert sorted(int(l["credit_paise"]) for l in tax) == [45_000_00, 45_000_00]


def test_the_gain_is_measured_net_of_the_tax(db):
    """The buyer's tax is not the seller's proceeds. WDV is Rs 8,00,000 and the
    consideration net of Rs 90,000 of tax is Rs 5,00,000, so the loss is
    Rs 3,00,000 — not the Rs 2,10,000 the gross figure would show."""
    out = _dispose(db, _asset(db))
    assert out["gain_loss_paise"] == -3_00_000_00
    loss = _named(db, out["journal_entry_id"], "Loss on Asset Disposal")
    assert [int(l["debit_paise"]) for l in loss] == [3_00_000_00]


def test_a_disposal_with_no_rate_posts_exactly_what_it_used_to(db):
    """The whole change is inert on a disposal nobody gave a rate. No tax line,
    and the gain is the gross figure it always was."""
    out = _dispose(db, _asset(db), gst_rate_bps=None, is_supply=None)
    assert _named(db, out["journal_entry_id"], "GST Output") == []
    assert out["gain_loss_paise"] == 5_90_000_00 - 8_00_000_00


def test_an_interstate_disposal_credits_igst(db):
    out = _dispose(db, _asset(db), is_interstate=True)
    tax = _named(db, out["journal_entry_id"], "GST Output - IGST")
    assert [int(l["credit_paise"]) for l in tax] == [90_000_00]
    assert _named(db, out["journal_entry_id"], "GST Output - CGST") == []


def test_the_treatment_is_recorded_on_the_asset(db):
    """Migration 383. The row is the DOCUMENT the return reads — a disposal
    carrying tax in the ledger and nothing here is the books-vs-ledger
    difference this change exists to close."""
    asset = _asset(db)
    _dispose(db, asset)
    live = [a for a in db.rows("fixed_assets") if a["id"] == asset["id"]][0]
    assert live["disposal_gst_rate_bps"] == 1800
    assert live["disposal_is_supply"] is True
    assert live["disposal_is_interstate"] is False


def test_the_answer_carries_the_whole_18_6_working(db):
    """Both readings, the working behind each, and the excess the journal did
    NOT post. This is a sum the CA pays over; a single number would hide the
    ambiguity."""
    out = _dispose(db, _asset(db))
    s = out["section_18_6"]
    assert s["applies"] is True
    assert [r["reading"] for r in s["readings"]] == [s186.BY_QUARTERS, s186.BY_MONTHS]
    assert all("excess_over_tax_charged_paise" in r for r in s["readings"])
    assert s["tax_charged_paise"] == 90_000_00


def test_the_excess_is_reported_and_not_posted(db):
    """Sold for a song two months in. The reduced credit is the higher limb, so
    s.18(6) demands more than the journal charges — and the difference is the
    CA's to raise, because two Rules give two figures and there is no invoice
    behind it."""
    out = _dispose(db, _asset(db), sale_proceeds_paise=11_800_00)
    s = out["section_18_6"]
    assert all(r["basis"] == "reduced_credit" for r in s["readings"])
    assert all(r["excess_over_tax_charged_paise"] > 0 for r in s["readings"])
    # …and the ledger carries only the tax on the transaction value.
    tax = _named(db, out["journal_entry_id"], "GST Output")
    assert sum(int(l["credit_paise"]) for l in tax) == s["tax_charged_paise"]


def test_a_rate_the_engine_cannot_split_is_refused_at_the_model():
    with pytest.raises(ValueError):
        DisposalIn(sale_proceeds_paise=1, gst_rate_bps=1700)


def test_a_failed_journal_takes_the_treatment_back_with_the_claim(db):
    """The claim is written BEFORE the journal so a retry cannot post twice;
    if the journal then fails, the compensating update must undo all of it.
    Leaving the GST treatment behind would leave an asset back in the register
    carrying a rate — and gst_return_service reads those columns."""
    asset = _asset(db)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(fa._journal_svc, "journal_for_asset_disposal",
                   lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        with pytest.raises(RuntimeError):
            _dispose(db, asset)
    finally:
        monkey.undo()
    live = [a for a in db.rows("fixed_assets") if a["id"] == asset["id"]][0]
    assert live["is_disposed"] is False
    assert live["disposal_gst_rate_bps"] is None
    assert live["disposal_is_supply"] is None
    assert live["disposal_is_interstate"] is False


# ── the preview, which writes nothing ────────────────────────────────────────

def test_the_preview_answers_the_same_figures_as_the_disposal(db):
    """Two derivations of one figure is how a preview comes to disagree with
    the thing it previews, so both go through the same module. Asserted by
    running the preview and then the disposal on the same asset."""
    asset = _asset(db)
    pre = fa.preview_disposal(
        asset["id"], proceeds_paise=5_90_000_00, disposal_date="2025-06-20",
        gst_rate_bps=1800, is_interstate=False, is_supply=True,
        current_user=CALLER)["data"]
    out = _dispose(db, asset)
    assert pre["gain_loss_paise"] == out["gain_loss_paise"]
    assert pre["tax_charged_paise"] == out["section_18_6"]["tax_charged_paise"]
    assert pre["section_18_6"]["readings"] == out["section_18_6"]["readings"]


def test_the_preview_writes_nothing(db):
    asset = _asset(db)
    fa.preview_disposal(asset["id"], proceeds_paise=5_90_000_00,
                        gst_rate_bps=1800, current_user=CALLER)
    live = [a for a in db.rows("fixed_assets") if a["id"] == asset["id"]][0]
    assert live["is_disposed"] is False
    assert live.get("disposal_gst_rate_bps") is None
    assert not db.rows("journal_entries")


def test_the_preview_says_what_depreciation_still_blocks_the_disposal(db):
    """The refusal dispose_asset makes, shown BEFORE the CA commits rather than
    as a 422 afterwards."""
    asset = _asset(db, depreciation_posted_through="2025-04-30")
    pre = fa.preview_disposal(asset["id"], proceeds_paise=1,
                              disposal_date="2025-06-20",
                              current_user=CALLER)["data"]
    assert pre["depreciation_months_outstanding"] == ["2025-05"]


# ── the return declares it ───────────────────────────────────────────────────

def test_the_return_declares_the_disposal_in_3_1_a(db):
    """A disposal is not a sales invoice, so gstr3b_from_books could not see
    the output tax the journal now posts — it would have sat in the GST Output
    ledger with no return declaring it."""
    _dispose(db, _asset(db))
    r = grs.gstr3b_from_books(db, FIRM, CLIENT, "062025", GSTIN)
    out = r["working"]["outward"]
    assert out["taxable_value_paise"] == 5_00_000_00
    assert out["taxable_cgst_paise"] == 45_000_00
    assert out["taxable_sgst_paise"] == 45_000_00
    assert r["reconciliation"]["asset_disposals"]["count"] == 1
    assert r["reconciliation"]["output_gst"]["matched"] is True


def test_the_return_says_gstr1_will_not_carry_it(db):
    _dispose(db, _asset(db))
    notes = " ".join(grs.gstr3b_from_books(db, FIRM, CLIENT, "062025", GSTIN)
                     ["disposal_caveats"])
    assert "Rule 46" in notes and "GSTR-1" in notes


def test_the_return_names_a_disposal_where_18_6_demands_more(db):
    _dispose(db, _asset(db), sale_proceeds_paise=11_800_00)
    notes = " ".join(grs.gstr3b_from_books(db, FIRM, CLIENT, "062025", GSTIN)
                     ["disposal_caveats"])
    assert "s.18(6) may demand more" in notes


def test_a_disposal_with_no_rate_is_not_on_the_return(db):
    _dispose(db, _asset(db), gst_rate_bps=None, is_supply=None)
    r = grs.gstr3b_from_books(db, FIRM, CLIENT, "062025", GSTIN)
    assert r["reconciliation"]["asset_disposals"]["count"] == 0
    assert r["working"]["outward"]["taxable_value_paise"] == 0
    assert r["disposal_caveats"] == []


# ── what the return does NOT read ───────────────────────────────────────────

def _row(**kw):
    base = {"id": "fa", "asset_name": "Lathe", "is_disposed": True,
            "disposal_gst_rate_bps": 1800, "disposal_is_interstate": False,
            "disposal_is_supply": True, "disposal_value_paise": 1_18_000_00,
            "purchase_date": "2025-04-01", "disposal_date": "2025-06-20",
            "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
            "itc_eligible": False}
    base.update(kw)
    return base


def test_a_rate_of_zero_declares_nothing():
    """Recorded, and recorded as nil. It posts identically to a disposal with
    no rate, so nothing in the books says whether the supply is nil-rated,
    exempt or outside the levy — and declaring its VALUE would assert one."""
    supplies, caveats = s186.outward_supplies([_row(disposal_gst_rate_bps=0)])
    assert supplies == () and caveats == ()


def test_an_asset_still_in_the_register_is_not_declared():
    """The fetch filters on is_disposed and the reader asks again — a test
    double that ignored the filter would otherwise declare a sale that has not
    happened."""
    assert s186.outward_supplies([_row(is_disposed=False)]) == ((), ())


def test_a_disposal_outside_the_period_is_not_on_this_return(db):
    """The fetch's own date window, driven rather than read off the query text
    so it is the behaviour that is pinned."""
    _dispose(db, _asset(db, depreciation_posted_through="2025-06-30"),
             disposal_date="2025-07-03", sale_proceeds_paise=5_90_000_00)
    rows = grs._disposals_declaring_gst(db, FIRM, CLIENT, "2025-06-01", "2025-06-30")
    assert rows == []

