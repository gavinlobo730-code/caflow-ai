"""The seeder's income-tax stage records facts, asks the engine for every figure, and stops where the facts stop (found by walking the ITR doors to fill the empty tax screens).

WHAT IT IS FOR
    The tax screens (computation, filing, advance tax, the capital-gains register, losses, deductions) rendered nothing on
    a seeded firm. `seed_demo_firm._income_tax` fills them through the doors a CA's screen posts to. The risk in a stage
    like this is not the plumbing but the temptation to put a figure of its own in: a slab, a rate, a limit, a "mostly
    right" tax. So the rule it is held to is that the FIXTURE carries facts (salary, the tax already deducted, a sale, a
    proof, a loss brought forward), the BOOKS carry the business income, and EVERY FIGURE THAT IS TAX comes back from the
    engine's doors.

WHAT IS HELD
    * the doors are called in the order the screens offer them, and the return is pinned to the reviewed computation;
    * the business income is the book-to-tax bridge's (or the section 44AD deemed income on the books' turnover), and an
      incomplete bridge is a finding and not a figure; a client with no assets states depreciation of zero, a client with
      assets does not;
    * the advance tax paid is the engine's own schedule, instalment by instalment, on the due dates that have passed, and a
      due date still to come is skipped and counted;
    * the old-regime comparison is saved but neither reviewed nor pinned; the new-regime computation is both;
    * a return becomes filed only through the acknowledgement, whose number is labelled as a seed's; one still to be filed
      (a date that has not come) is left ready for filing and counted; one waiting for a Partner stops there;
    * a refusal that is a finding is reported and the next client is still done; a dead run (an expired login, a server
      error) stops; a call with no answer is reported;
    * an obligation the acknowledgement left open is named, and a client that owns assets is never given a computed return.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.demo import fixture

_API_ROOT = Path(__file__).resolve().parents[1]


def _seeder():
    spec = importlib.util.spec_from_file_location("seed_demo_firm_income_tax", _API_ROOT / "scripts" / "seed_demo_firm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seeder = _seeder()

FY = "2025-26"
FIRM = fixture.build(FY)
CLIENT = {c.name: c for c in FIRM.clients}
PRIYA, MEHER, ANAND, VAIBHAV = (CLIENT[n] for n in ("Priya Sharma", "Meher Enterprises", "Anand Textiles", "Vaibhav Infra"))

SCHEDULE = [
    {"installment_number": 1, "due_date": "2025-06-15", "required_cumulative_paise": 15_00},
    {"installment_number": 2, "due_date": "2025-09-15", "required_cumulative_paise": 45_00},
    {"installment_number": 3, "due_date": "2025-12-15", "required_cumulative_paise": 75_00},
    {"installment_number": 4, "due_date": "2026-03-15", "required_cumulative_paise": 100_00},
]


def _comp(regime="new", taxable=26_59_717_00, tax=3_36_741_00, net=0, **over):
    return {"regime": regime, "rates_verified": True, "validation_errors": [],
            "income": {"taxable_income_paise": taxable}, "tax": {"total_tax_paise": tax},
            "payable": {"net_payable_paise": net}, **over}


class FakeApi:
    """The seeder's client. `answers` maps (method, path-prefix) to a function of the body that may raise or return."""

    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def _do(self, method, path, body=None):
        self.calls.append((method, path, body))
        for (m, prefix), fn in self.answers.items():
            if m == method and path.startswith(prefix):
                return fn(body)
        return self._default(method, path, body)

    def _default(self, method, path, body):
        n = len(self.calls)
        if path.startswith("/api/accounting/profit-loss"):
            return {"data": {"revenue": {"total_paise": 99_278_400}}}
        if path.startswith("/api/income-tax/presumptive/44ad"):
            return {"data": {"eligible": True, "presumptive_income_paise": 5_956_704, "reasons": []}}
        if path.startswith("/api/income-tax/book-to-tax-bridge"):
            return {"data": {"is_complete": True, "taxable_income_paise": 62_971_766, "missing": [], "reasons": []}}
        if path.startswith("/api/income-tax/capital-gains"):
            return {"data": {"section_ref": "Section 112A", "gain_type": "LTCG", "gain_paise": 22_000_000}}
        if path.startswith("/api/income-tax/advance-tax/compute"):
            return {"data": {"installments": SCHEDULE}}
        if path.startswith("/api/income-tax/compute"):
            return {"data": _comp("new" if body.get("use_new_regime") else "old")}
        if path.startswith("/api/itr/disallowances/auto-detect-40a3"):
            return {"data": {"detected": 0, "items": []}}
        if path.endswith("/acknowledge"):
            return {"data": {"status": "filed", "compliance_obligation": {"state": "closed", "closed": True}}}
        return {"data": {"id": f"id-{n}"}}

    #: What `GET /api/income-tax/assessee-kind` answers for the entity types these tests use. Plain data, so the stage can
    #: be run in a process that cannot import the API (see the last test); a test below holds it to the real rule.
    KIND = {"Individual": "individual", "Proprietorship": "individual", "Partnership": "firm"}

    def get(self, path):
        if path.startswith("/api/income-tax/assessee-kind"):
            self.calls.append(("GET", path, None))
            from urllib.parse import parse_qs, urlparse
            entity = parse_qs(urlparse(path).query)["entity_type"][0]
            kind = self.KIND.get(entity)
            return {"data": {"kind": kind, "refusal": None if kind else f"no tax basis for {entity}"}}
        return self._do("GET", path)

    def post(self, path, body):
        return self._do("POST", path, body)

    def paths(self, method="POST"):
        return [p for m, p, _ in self.calls if m == method]

    def bodies(self, prefix, method="POST"):
        return [b for m, p, b in self.calls if m == method and p.startswith(prefix)]

    def sent_to(self, path, method="POST"):
        """The bodies sent to exactly this path (a prefix match would count `/advance-tax/compute` as `/advance-tax`)."""
        return [b for m, p, b in self.calls if m == method and p.split("?")[0] == path]


def _written():
    return {k: 0 for k in ("bf_losses", "disallowances_detected", "deduction_claims", "capital_gains",
                           "advance_tax_instalments", "advance_tax_not_yet_due", "itr_filings", "itr_waiting",
                           "itr_filed", "itr_not_yet_filable", "obligations_closed")} | {
        "obligations_left_open": [], "returns_refused": [], "health_not_scored": []}


def _run(api, client, written=None, today=date(2026, 10, 19), monkeypatch=None):
    written = written if written is not None else _written()
    if monkeypatch is not None:
        import core.ist_clock
        monkeypatch.setattr(core.ist_clock, "ist_today", lambda: today)
    seeder._income_tax(api, client, "cid", FY, written)
    return written


def _refusal(status, text="refused"):
    return seeder.ApiRefusal(f"\nPOST /x → HTTP {status}\n{text}\nNothing further was written.", status)


# ── the order, and what each door is given ──────────────────────────────────

def test_the_individual_walks_the_doors_in_the_order_the_screens_offer_them(monkeypatch):
    api = FakeApi()
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    paths = [p.split("?")[0] for p in api.paths()]
    order = ["/api/itr/disallowances/auto-detect-40a3", "/api/income-tax/book-to-tax-bridge", "/api/income-tax/capital-gains",
             "/api/itr/deductions", "/api/income-tax/compute", "/api/income-tax/advance-tax/compute",
             "/api/income-tax/advance-tax", "/api/income-tax/compute", "/api/itr/snapshots", "/api/income-tax/compute",
             "/api/itr/snapshots", "/api/itr/snapshots/id-", "/api/itr/filings", "/api/itr/filings/id-"]
    at = -1
    for want in order:
        at = next((i for i in range(at + 1, len(paths)) if paths[i].startswith(want)), None)
        assert at is not None, f"{want} is not called after the one before it: {paths}"
    assert w["itr_filings"] == 1 and w["itr_filed"] == 1 and w["capital_gains"] == 1 and w["deduction_claims"] == 2
    assert w["returns_refused"] == [] and w["obligations_left_open"] == [] and w["obligations_closed"] == 1


def test_the_return_is_pinned_to_the_reviewed_new_regime_computation_and_the_comparison_is_neither(monkeypatch):
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    snaps = api.bodies("/api/itr/snapshots")
    snaps = [b for b in snaps if b is not None and "regime" in b]
    assert [s["regime"] for s in snaps] == ["old", "new"], "the comparison first, so the latest computation is the new regime"
    reviews = [p for p in api.paths() if p.endswith("/review")]
    assert len(reviews) == 1, "only the computation the return is pinned to is reviewed"
    new_snapshot_id = next(p.split("/")[4] for p in api.paths() if p.endswith("/review"))
    filing = api.bodies("/api/itr/filings")[0]
    assert filing["computation_snapshot_id"] == new_snapshot_id
    assert filing["itr_form"] == "ITR-3" and filing["assessment_year"] == "2026-27"


def test_a_snapshot_is_saved_the_way_the_computation_screen_saves_it(monkeypatch):
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    new = [b for b in api.bodies("/api/itr/snapshots") if b and b.get("regime") == "new"][0]
    assert new["computation_result"] == _comp("new"), "the server's whole answer is kept"
    assert new["income"]["taxable_income_paise"] == 26_59_717_00
    assert new["income"]["tax_liability_paise"] == 3_36_741_00 and new["income"]["net_payable_paise"] == 0
    assert new["income"]["tds_deducted_paise"] == 2_00_000_00 and new["income"]["is_refund"] is False


def test_the_acknowledgement_is_labelled_as_a_seeds_and_carries_the_stated_date(monkeypatch):
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    (ack,) = api.bodies("/api/itr/filings/id-", method="POST")[-1:]
    assert ack == {"acknowledgement_number": "SEED-ITR-AKQPS1138F-AY2026-27", "filing_date": "2026-07-24"}
    transitions = [b["new_status"] for b in api.bodies("/api/itr/filings/id-") if b and "new_status" in b]
    assert transitions == ["review", "partner_review", "ready_for_filing"], "filed is never a transition"


def test_no_door_is_asked_to_move_a_return_to_filed(monkeypatch):
    for client in (PRIYA, MEHER):
        api = FakeApi()
        _run(api, client, monkeypatch=monkeypatch)
        assert not any(b and b.get("new_status") == "filed" for b in api.bodies("/api/itr/filings/id-"))


# ── the business income is the books', and the facts stop where the engine stops ──

def test_a_client_with_no_assets_states_depreciation_of_zero_and_one_with_assets_does_not(monkeypatch):
    assert not PRIYA.assets
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    assert api.bodies("/api/income-tax/book-to-tax-bridge")[0] == {
        "client_id": "cid", "fy": FY, "depreciation_per_books_paise": 0}
    with_assets = SimpleNamespace(**{**vars(PRIYA), "assets": ("an asset",), "name": "Owns Things"})
    api = FakeApi()
    _run(api, with_assets, monkeypatch=monkeypatch)
    assert api.bodies("/api/income-tax/book-to-tax-bridge")[0] == {"client_id": "cid", "fy": FY}


def test_an_incomplete_bridge_is_a_finding_and_writes_no_computation_and_no_filing(monkeypatch):
    api = FakeApi({("POST", "/api/income-tax/book-to-tax-bridge"): lambda body: {"data": {
        "is_complete": False, "taxable_income_paise": -1, "missing": ["Depreciation allowable under IT Act §32"],
        "reasons": ["Depreciation under IT Act §32 was not supplied."]}}})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "bridge is incomplete" in w["returns_refused"][0]
    assert not api.bodies("/api/income-tax/compute") and not api.bodies("/api/itr/snapshots") and not api.bodies("/api/itr/filings")
    assert w["itr_filings"] == 0 and w["itr_filed"] == 0


def test_the_proprietors_income_is_the_deemed_income_on_the_books_turnover(monkeypatch):
    api = FakeApi()
    w = _run(api, MEHER, monkeypatch=monkeypatch)
    presumptive = api.bodies("/api/income-tax/presumptive/44ad")[0]
    assert presumptive == {"fy": FY, "assessee_kind": "individual", "is_resident": True, "turnover_paise": 99_278_400}, \
        "how the turnover was received is not in the books, so no channel is stated: the door's defaults stand"
    assert not api.bodies("/api/income-tax/book-to-tax-bridge"), "a presumptive assessee needs no section 32 figure"
    compute = api.bodies("/api/income-tax/compute")[0]
    assert compute["presumptive_income_paise"] == 5_956_704 and compute["business_income_paise"] == 0
    assert w["itr_filings"] == 1 and w["itr_waiting"] == 1 and w["itr_filed"] == 0
    assert not any(p.endswith("/acknowledge") for p in api.paths())


def test_a_refused_presumptive_scheme_is_a_finding(monkeypatch):
    api = FakeApi({("POST", "/api/income-tax/presumptive/44ad"): lambda body: {"data": {
        "eligible": False, "presumptive_income_paise": 0, "reasons": ["turnover above the limit"]}}})
    w = _run(api, MEHER, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "44AD does not apply" in w["returns_refused"][0]
    assert w["itr_filings"] == 0


def test_a_sale_the_seeder_has_no_box_for_is_a_finding_and_not_a_guess(monkeypatch):
    api = FakeApi({("POST", "/api/income-tax/capital-gains"): lambda body: {"data": {
        "section_ref": "Section 111A", "gain_type": "STCG", "gain_paise": 5}}})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "STCG under Section 111A" in w["returns_refused"][0]
    assert not api.bodies("/api/income-tax/compute") and w["itr_filings"] == 0


def test_a_proof_with_no_box_in_the_computation_is_a_finding_and_not_dropped(monkeypatch):
    odd = SimpleNamespace(**{**vars(PRIYA), "income_tax": SimpleNamespace(**{
        **vars(PRIYA.income_tax), "deductions": (("80G", "Donation", 5_000_00),)})})
    api = FakeApi()
    w = _run(api, odd, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "no box in the computation for 80G" in w["returns_refused"][0]
    assert w["itr_filings"] == 0


# ── the advance tax is the engine's schedule ────────────────────────────────

def test_tax_the_deduction_at_source_already_covers_leaves_nothing_to_pay_in_advance(monkeypatch):
    """Estimated = the engine's tax less the TDS the client already had deducted. Where that is nothing, no instalment is
    recorded and the schedule is not even asked for: the register stays empty rather than recording zeros."""
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": _comp(
        "new" if body["use_new_regime"] else "old", tax=1_00_000_00)}})      # less than the 2,00,000 TDS
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert w["advance_tax_instalments"] == 0 and not api.sent_to("/api/income-tax/advance-tax/compute")
    assert not api.sent_to("/api/income-tax/advance-tax")


def test_the_instalments_are_the_difference_between_the_schedules_cumulative_figures(monkeypatch):
    big = 2_00_000_00 + 100_00           # tax such that estimated = 100_00 paise (the schedule above is in paise)
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": _comp(
        "new" if body["use_new_regime"] else "old", tax=big)}})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    (saved,) = api.sent_to("/api/income-tax/advance-tax")
    assert [i["paid_amount_paise"] for i in saved["installments"]] == [15_00, 30_00, 30_00, 25_00]
    assert sum(i["paid_amount_paise"] for i in saved["installments"]) == saved["estimated_tax_paise"] == 100_00
    assert [i["paid_date"] for i in saved["installments"]] == [r["due_date"] for r in SCHEDULE]
    assert all("challan_number" not in i for i in saved["installments"]), "a bank's number is not ours to invent"
    assert w["advance_tax_instalments"] == 4


def test_the_computation_after_the_payments_carries_what_was_paid(monkeypatch):
    big = 2_00_000_00 + 100_00
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": _comp(
        "new" if body["use_new_regime"] else "old", tax=big)}})
    _run(api, PRIYA, monkeypatch=monkeypatch)
    advances = [b["advance_tax_paid_paise"] for b in api.bodies("/api/income-tax/compute")]
    assert advances == [0, 100_00, 100_00], advances


def test_an_instalment_whose_due_date_has_not_come_is_skipped_and_counted(monkeypatch):
    big = 2_00_000_00 + 100_00
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": _comp(
        "new" if body["use_new_regime"] else "old", tax=big)}})
    w = _run(api, PRIYA, today=date(2025, 12, 1), monkeypatch=monkeypatch)
    (saved,) = api.sent_to("/api/income-tax/advance-tax")
    assert [i["installment_number"] for i in saved["installments"]] == [1, 2]
    assert w["advance_tax_not_yet_due"] == 2


def test_a_client_whose_computation_owes_no_tax_records_no_advance_tax(monkeypatch):
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": _comp(tax=0)}})
    w = _run(api, MEHER, monkeypatch=monkeypatch)
    assert w["advance_tax_instalments"] == 0 and not api.sent_to("/api/income-tax/advance-tax")


# ── how far the return goes ─────────────────────────────────────────────────

def test_a_filing_date_still_to_come_leaves_the_return_ready_and_counted(monkeypatch):
    api = FakeApi()
    w = _run(api, PRIYA, today=date(2026, 7, 1), monkeypatch=monkeypatch)
    assert w["itr_not_yet_filable"] == 1 and w["itr_filed"] == 0
    assert not any(p.endswith("/acknowledge") for p in api.paths())
    assert [b["new_status"] for b in api.bodies("/api/itr/filings/id-") if b][-1] == "ready_for_filing"


@pytest.mark.parametrize("closure,left_open", [
    ({"state": "closed", "closed": True}, False),
    ({"state": "already_filed", "closed": False}, False),
    ({"state": "not_on_the_calendar", "closed": False, "message": "No ITR obligation is on the calendar."}, True),
    ({"state": "not_allowed", "closed": False, "message": "Your access does not include Compliance."}, True),
    ({}, True),
])
def test_an_obligation_the_acknowledgement_left_open_is_named(monkeypatch, closure, left_open):
    api = FakeApi({("POST", "/api/itr/filings/id-"): lambda body: (
        {"data": {"status": "filed", "compliance_obligation": closure}} if body and "acknowledgement_number" in body
        else {"data": {"id": "x"}})})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert bool(w["obligations_left_open"]) is left_open
    if left_open:
        assert "Priya Sharma ITR-3 FY 2025-26" in w["obligations_left_open"][0]


# ── a client that owns assets, and the clients with only a loss ─────────────

def test_a_client_that_owns_assets_is_given_no_computed_return_and_only_its_losses(monkeypatch):
    for client in (ANAND, VAIBHAV):
        assert client.assets and client.income_tax.itr_form is None
        api = FakeApi()
        w = _run(api, client, monkeypatch=monkeypatch)
        assert w["bf_losses"] == 1 and w["itr_filings"] == 0
        called = [p.split("?")[0] for p in api.paths()]
        assert called == ["/api/itr/disallowances/auto-detect-40a3", "/api/itr/bf-losses"], called
        loss = api.bodies("/api/itr/bf-losses")[0]
        assert loss["assessment_year"] == "2025-26" and loss["loss_type"] == "business"
        assert "expiry_assessment_year" not in loss, "how long a loss lives is the engine's to say"


def test_a_client_with_no_facts_gets_only_the_scan(monkeypatch):
    plain = CLIENT["Deshmukh & Sons"]
    assert plain.income_tax is None
    api = FakeApi()
    w = _run(api, plain, monkeypatch=monkeypatch)
    assert [p.split("?")[0] for p in api.paths()] == ["/api/itr/disallowances/auto-detect-40a3"]
    assert w["disallowances_detected"] == 0


def test_the_scan_is_counted(monkeypatch):
    api = FakeApi({("POST", "/api/itr/disallowances/auto-detect-40a3"): lambda body: {"data": {"detected": 3, "items": []}}})
    assert _run(api, CLIENT["Deshmukh & Sons"], monkeypatch=monkeypatch)["disallowances_detected"] == 3


# ── a finding is not a dead run ─────────────────────────────────────────────

@pytest.mark.parametrize("status", [400, 409, 422, 200])
def test_a_refusal_that_is_a_finding_is_reported_and_the_next_item_is_still_tried(monkeypatch, status):
    api = FakeApi({("POST", "/api/itr/bf-losses"): lambda body: (_ for _ in ()).throw(_refusal(status))})
    w = _run(api, ANAND, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "brought-forward loss" in w["returns_refused"][0]
    assert w["bf_losses"] == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_an_answer_that_means_every_later_call_fails_too_stops_the_run(monkeypatch, status):
    api = FakeApi({("POST", "/api/itr/bf-losses"): lambda body: (_ for _ in ()).throw(_refusal(status))})
    with pytest.raises(seeder.ApiRefusal) as stop:
        _run(api, ANAND, monkeypatch=monkeypatch)
    assert stop.value.status == status


@pytest.mark.parametrize("error", [TimeoutError("timed out"), urllib.error.URLError("connection reset")])
def test_a_call_with_no_answer_is_reported_as_that(monkeypatch, error):
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: (_ for _ in ()).throw(error)})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert any("no answer" in m and "may have saved" in m for m in w["returns_refused"]), w["returns_refused"]


def test_the_scan_failing_does_not_stop_the_rest_of_the_client(monkeypatch):
    api = FakeApi({("POST", "/api/itr/disallowances/auto-detect-40a3"): lambda body: (_ for _ in ()).throw(_refusal(422))})
    w = _run(api, ANAND, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "section 40A(3) scan" in w["returns_refused"][0]
    assert w["bf_losses"] == 1


# ── the fixture's facts ─────────────────────────────────────────────────────

def test_every_deduction_the_fixture_holds_has_a_box_in_the_computation():
    for c in FIRM.clients:
        if c.income_tax:
            for section, sub_head, _ in c.income_tax.deductions:
                assert (section, sub_head) in seeder._OLD_REGIME_BOXES, (c.name, section, sub_head)


def test_a_client_with_assets_is_never_given_a_return_unless_it_is_presumptive():
    """The bridge cannot complete for a client with assets until the section 32 block rates are entered by a human."""
    for c in FIRM.clients:
        it = c.income_tax
        if it and it.itr_form and c.assets:
            assert it.presumptive_44ad, f"{c.name} owns assets and has a computed return that needs a section 32 figure"


def test_the_facts_are_dated_inside_the_years_they_belong_to():
    fy_end = f"{int(FY[:4]) + 1}-03-31"
    for c in FIRM.clients:
        it = c.income_tax
        if not it:
            continue
        if it.filed_on:
            assert it.filed_on > fy_end, "a return cannot be filed before its year ends"
        if it.capital_gain:
            g = it.capital_gain
            assert f"{FY[:4]}-04-01" <= g.sale_date <= fy_end and g.purchase_date < g.sale_date
        for loss in it.losses:
            assert loss.assessment_year == "2025-26", "the year BEFORE the books begin is assessed in the year the books begin"
        assert it.savings_interest_paise <= it.other_income_paise, "savings interest is part of the other income"


def test_every_form_the_fixture_names_is_one_the_product_prepares():
    from domain.income_tax.itr_json import ITR_FORMS
    for c in FIRM.clients:
        if c.income_tax and c.income_tax.itr_form:
            assert c.income_tax.itr_form in ITR_FORMS


def test_the_walk_a_fixture_asks_for_is_one_the_filing_workflow_has():
    for c in FIRM.clients:
        if c.income_tax and c.income_tax.itr_form:
            assert c.income_tax.take_it_to in ("partner_review", "filed")


def test_adding_the_facts_moved_no_document():
    """The fixture is drawn from one random stream; a field that drew from it would reshuffle every document."""
    assert (sum(len(c.sales) for c in FIRM.clients), sum(len(c.purchases) for c in FIRM.clients)) == (315, 200)


def test_the_stage_is_the_last_thing_each_client_gets(monkeypatch):
    src = (Path(seeder.__file__)).read_text()
    assert src.index("_gst_returns(api, c, client_id, firm.financial_year") < src.index(
        "_income_tax(api, c, client_id, firm.financial_year, written)")


def test_main_exits_non_zero_when_a_record_was_not_written(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["seed_demo_firm.py", "--api-url", "http://localhost:1", "--token", "t", "--confirm"])
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: {**_written(), "returns_refused": ["Priya Sharma ITR-3 x: y"]})
    assert seeder.main() == 2
    assert "not filed or recorded" in capsys.readouterr().out


# ── what the engine refused is never saved, reviewed or filed ───────────────

@pytest.mark.parametrize("over,said", [
    ({"validation_errors": ["B2B invoice has no GSTIN"]}, "refused the computation"),
    ({"rates_verified": False}, "has not verified its rates for FY 2025-26"),
    ({"regime": ""}, "returned no computation"),
])
def test_a_computation_the_engine_refused_or_could_not_stand_behind_is_a_finding_and_is_never_saved(monkeypatch, over, said):
    api = FakeApi({("POST", "/api/income-tax/compute"): lambda body: {"data": {
        **_comp("new" if body["use_new_regime"] else "old"), **over}}})
    w = _run(api, PRIYA, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and said in w["returns_refused"][0], w["returns_refused"]
    assert not api.bodies("/api/itr/snapshots") and not api.bodies("/api/itr/filings")
    assert w["itr_filings"] == 0 and w["itr_filed"] == 0


# ── what the computation is told, and by whom ───────────────────────────────

def test_the_computation_is_told_the_clients_entity_residence_and_savings_interest(monkeypatch):
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    for body in api.bodies("/api/income-tax/compute"):
        assert body["entity_type"] == "Individual" and body["is_resident"] is True
        assert body["savings_interest_80tta_paise"] == 12_000_00


def test_the_scheme_door_is_told_the_assessee_kind_the_servers_rule_gives_the_entity_type(monkeypatch):
    for entity in ("Proprietorship", "Partnership"):
        client = SimpleNamespace(**{**vars(MEHER), "entity_type": entity})
        api = FakeApi()
        _run(api, client, monkeypatch=monkeypatch)
        assert ("GET", f"/api/income-tax/assessee-kind?entity_type={entity}", None) in api.calls
        assert api.bodies("/api/income-tax/presumptive/44ad")[0]["assessee_kind"] == FakeApi.KIND[entity], entity


def test_the_fakes_entity_table_is_the_real_rule():
    from domain.income_tax.assessee import assessee_kind_for_entity_type
    for entity, kind in FakeApi.KIND.items():
        assert assessee_kind_for_entity_type(entity)[0] == kind, entity


def test_the_stage_runs_in_a_process_that_cannot_import_the_api():
    """The seeder is a script an owner runs with a bare python3. A helper imported from `domain.income_tax` would pull in
    fastapi through `services`, and the first presumptive return would die there (the first draft of this stage did)."""
    import subprocess
    import sys
    code = r"""
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("fastapi", "starlette", "pydantic", "supabase", "httpx", "services"):
            raise ImportError(name + " is blocked: the seeder is a standalone script")
sys.meta_path.insert(0, Block())
sys.path.insert(0, %r)
import importlib.util
from tests import test_the_seeders_income_tax_stage_uses_the_engines_figures_and_stops_where_the_facts_stop as t
import core.ist_clock
core.ist_clock.ist_today = lambda: t.date(2026, 10, 19)
for client in (t.MEHER, t.PRIYA):
    w = t._written()
    t.seeder._income_tax(t.FakeApi(), client, "cid", t.FY, w)
    assert not w["returns_refused"], w["returns_refused"]
    assert w["itr_filings"] == 1
print("ok")
""" % str(_API_ROOT)
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=str(_API_ROOT))
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-600:] or out.stdout


def test_an_entity_type_the_product_has_no_tax_basis_for_is_a_finding_and_not_a_guess(monkeypatch):
    client = SimpleNamespace(**{**vars(MEHER), "entity_type": "Something Else"})
    api = FakeApi()
    w = _run(api, client, monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and not api.bodies("/api/income-tax/presumptive/44ad")


def test_a_client_with_losses_and_a_return_is_refused_because_no_loss_is_set_off_in_the_computation(monkeypatch):
    both = SimpleNamespace(**{**vars(ANAND), "income_tax": SimpleNamespace(
        **{**vars(ANAND.income_tax), "itr_form": "ITR-6"})})
    api = FakeApi()
    w = _run(api, both, monkeypatch=monkeypatch)
    assert w["bf_losses"] == 1, "the loss is still recorded"
    assert len(w["returns_refused"]) == 1 and "not set off" in w["returns_refused"][0]
    assert not api.bodies("/api/income-tax/compute") and w["itr_filings"] == 0


def test_the_register_is_asked_in_the_registers_vocabulary_and_with_the_fixtures_own_asset_type(monkeypatch):
    from routers.income_tax import REGISTER_ASSET_TYPES
    assert PRIYA.income_tax.capital_gain.asset_type in REGISTER_ASSET_TYPES
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    assert api.sent_to("/api/income-tax/capital-gains")[0]["asset_type"] == PRIYA.income_tax.capital_gain.asset_type
    other = SimpleNamespace(**{**vars(PRIYA), "income_tax": SimpleNamespace(**{**vars(PRIYA.income_tax),
        "capital_gain": SimpleNamespace(**{**vars(PRIYA.income_tax.capital_gain), "asset_type": "mutual_funds"})})})
    api = FakeApi()
    _run(api, other, monkeypatch=monkeypatch)
    assert api.sent_to("/api/income-tax/capital-gains")[0]["asset_type"] == "mutual_funds"


def test_a_share_sale_dated_after_today_is_a_finding_and_is_not_recorded(monkeypatch):
    api = FakeApi()
    w = _run(api, PRIYA, today=date(2025, 10, 1), monkeypatch=monkeypatch)
    assert len(w["returns_refused"]) == 1 and "still to come" in w["returns_refused"][0]
    assert not api.sent_to("/api/income-tax/capital-gains") and w["capital_gains"] == 0


def test_a_deduction_is_recorded_as_claimed_on_the_clients_word_and_not_as_proven(monkeypatch):
    api = FakeApi()
    _run(api, PRIYA, monkeypatch=monkeypatch)
    notes = [b["notes"] for b in api.sent_to("/api/itr/deductions")]
    assert len(notes) == 2 and all("no document is attached" in n and "Proof held" not in n for n in notes)

