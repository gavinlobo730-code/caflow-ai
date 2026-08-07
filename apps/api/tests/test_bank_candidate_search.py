"""
"Find other matches" (Tier 1.6) — the candidate picker with the amount band lifted.

The point of this feature is reaching a document the RANKED list could never
show, so the tests are mostly about what is reachable and what still is not:

  * direction is a RULE — money arriving cannot settle a purchase bill, however
    the search box is filled in;
  * everything else (text, date, amount, party, type) is a FILTER the CA may
    narrow with, and narrowing must never widen past the rule;
  * the order is TOTAL — two identical searches cannot disagree;
  * the total counts everything matching, not the page, so "narrow it further"
    is visible rather than implied.
"""
import pytest
from fastapi import HTTPException

from domain.banking.matcher import Candidate
from domain.banking.candidate_search import (
    search, describe, allowed_types, CREDIT_TYPES, DEBIT_TYPES, MAX_RESULTS,
)
from services.bank_candidate_search_service import (
    bank_candidate_search_service as svc, FETCH_LIMIT, DEFAULT_WINDOW_DAYS,
)

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "partner"}


def _c(entity_type, entity_id, amount, *, date="2026-04-10", label=None,
       party_name=None, party_id=None, outstanding=None):
    return Candidate(
        entity_type=entity_type, entity_id=entity_id,
        label=label if label is not None else f"{entity_id.upper()} · doc",
        amount_paise=amount, entity_date=date,
        party_name=party_name, party_id=party_id,
        outstanding_paise=outstanding,
    )


def _search(candidates, **kw):
    kw.setdefault("bank_amount_paise", 10_000_00)
    kw.setdefault("bank_date", "2026-04-10")
    kw.setdefault("is_credit", True)
    return search(candidates, **kw)


# ══════════════════════════════════════════════════════════════════════════════
# Direction is a rule, not a filter
# ══════════════════════════════════════════════════════════════════════════════

def test_money_arriving_never_offers_a_purchase_bill():
    """A credit settles a receivable. Offering a payable because the search box
    was empty invites a wrong match that still balances."""
    hits, total = _search([
        _c("sales_invoice", "inv-1", 10_000_00),
        _c("purchase_bill", "bill-1", 10_000_00),
        _c("purchase_payment", "pay-1", 10_000_00),
    ], is_credit=True)
    assert [h.entity_type for h in hits] == ["sales_invoice"]
    assert total == 1


def test_money_leaving_never_offers_a_sales_invoice():
    hits, _ = _search([
        _c("purchase_bill", "bill-1", 10_000_00),
        _c("sales_invoice", "inv-1", 10_000_00),
        _c("receipt", "rec-1", 10_000_00),
    ], is_credit=False)
    assert [h.entity_type for h in hits] == ["purchase_bill"]


def test_a_journal_can_settle_either_direction():
    """A journal entry is not inherently a receivable or a payable, so it stays
    available whichever way the money moved."""
    je = [_c("journal_entry", "je-1", 10_000_00)]
    assert len(_search(je, is_credit=True)[0]) == 1
    assert len(_search(je, is_credit=False)[0]) == 1
    assert "journal_entry" in CREDIT_TYPES and "journal_entry" in DEBIT_TYPES


def test_asking_for_a_type_the_direction_forbids_yields_nothing_not_everything():
    """Narrowing must never widen. entity_type intersects with the rule; it does
    not replace it."""
    hits, total = _search([
        _c("sales_invoice", "inv-1", 10_000_00),
        _c("purchase_bill", "bill-1", 10_000_00),
    ], is_credit=True, entity_type="purchase_bill")
    assert hits == [] and total == 0


def test_allowed_types_names_exactly_what_each_direction_can_settle():
    assert allowed_types(True) == CREDIT_TYPES
    assert allowed_types(False) == DEBIT_TYPES
    assert "purchase_bill" not in CREDIT_TYPES
    assert "sales_invoice" not in DEBIT_TYPES


# ══════════════════════════════════════════════════════════════════════════════
# The band is gone — that is the whole feature
# ══════════════════════════════════════════════════════════════════════════════

def test_a_document_ten_times_the_bank_line_is_still_reachable():
    """rank_suggestions caps candidates at +25% of the bank line. A CA who knows
    the invoice number must still be able to reach a part-payment against a much
    larger invoice."""
    hits, _ = _search([_c("sales_invoice", "inv-1", 1_00_000_00)],
                      bank_amount_paise=10_000_00)
    assert [h.entity_id for h in hits] == ["inv-1"]
    assert hits[0].difference_paise == 90_000_00


def test_a_document_smaller_than_the_bank_line_is_reachable_too():
    """The old band was one-sided — nothing below the bank amount was ever
    fetched. A ₹9,000 invoice against a ₹10,000 deposit (customer overpaid, or
    two invoices in one transfer) is a real thing a CA needs to find."""
    hits, _ = _search([_c("sales_invoice", "inv-1", 9_000_00)],
                      bank_amount_paise=10_000_00)
    assert hits[0].difference_paise == -1_000_00
    assert hits[0].bank_line_is_short is False


# ══════════════════════════════════════════════════════════════════════════════
# Ranking
# ══════════════════════════════════════════════════════════════════════════════

def test_an_exact_amount_outranks_a_nearer_date():
    """Once the band is lifted, "closest amount" stops being a near-tautology.
    An exact match a year away still beats a same-day near-miss."""
    hits, _ = _search([
        _c("sales_invoice", "near-date", 10_000_50, date="2026-04-10"),
        _c("sales_invoice", "exact", 10_000_00, date="2025-04-10"),
    ], bank_amount_paise=10_000_00, bank_date="2026-04-10")
    assert [h.entity_id for h in hits] == ["exact", "near-date"]


def test_among_inexact_the_smallest_gap_either_way_comes_first():
    hits, _ = _search([
        _c("sales_invoice", "far", 15_000_00),
        _c("sales_invoice", "over-by-1", 10_000_01),
        _c("sales_invoice", "under-by-2", 9_999_98),
    ], bank_amount_paise=10_000_00)
    assert [h.entity_id for h in hits] == ["over-by-1", "under-by-2", "far"]


def test_an_equal_gap_is_broken_by_date_proximity():
    """The ids run the other way on purpose — if date proximity dropped out of
    the ranking, the entity_id tiebreak would produce this same order and the
    test would pass while proving nothing."""
    hits, _ = _search([
        _c("sales_invoice", "aaa-distant", 11_000_00, date="2026-01-01"),
        _c("sales_invoice", "zzz-close", 11_000_00, date="2026-04-12"),
    ], bank_amount_paise=10_000_00, bank_date="2026-04-10")
    assert [h.entity_id for h in hits] == ["zzz-close", "aaa-distant"]


def test_the_order_is_total_so_two_identical_searches_never_disagree():
    """Same amount, same date — without the id tiebreak the order would depend on
    fetch order, and paging would silently drop or repeat rows."""
    same = [_c("sales_invoice", x, 10_000_00) for x in ("ccc", "aaa", "bbb")]
    first, _ = _search(list(same))
    second, _ = _search(list(reversed(same)))
    assert [h.entity_id for h in first] == ["aaa", "bbb", "ccc"]
    assert [h.entity_id for h in first] == [h.entity_id for h in second]


def test_a_candidate_with_no_date_ranks_last_rather_than_crashing():
    hits, _ = _search([
        _c("sales_invoice", "dated", 11_000_00, date="2020-01-01"),
        _c("sales_invoice", "undated", 11_000_00, date=None),
    ], bank_amount_paise=10_000_00, bank_date="2026-04-10")
    assert [h.entity_id for h in hits] == ["dated", "undated"]


def test_an_unparseable_date_is_treated_as_no_date_not_an_error():
    hits, _ = _search([_c("sales_invoice", "inv-1", 10_000_00, date="not-a-date")])
    assert [h.entity_id for h in hits] == ["inv-1"]


# ══════════════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════════════

def test_text_search_finds_the_invoice_number_a_ca_types_in():
    """The motivating case: the CA is holding the remittance advice."""
    hits, _ = _search([
        _c("sales_invoice", "inv-1", 55_000_00, label="INV-2026-0042 · Acme"),
        _c("sales_invoice", "inv-2", 10_000_00, label="INV-2026-0099 · Beta"),
    ], q="0042")
    assert [h.entity_id for h in hits] == ["inv-1"]


@pytest.mark.parametrize("typed", ["  acme  ", "ACME", "AcMe", "acme"])
def test_text_search_ignores_case_and_surrounding_space(typed):
    """Both sides have to be folded: a CA pasting "ACME PVT LTD" out of a
    remittance advice is the normal way this box gets filled in."""
    hits, _ = _search([_c("sales_invoice", "inv-1", 10_000_00,
                          label="INV-42 · Acme", party_name="Acme Pvt Ltd")],
                      q=typed)
    assert len(hits) == 1


def test_text_search_matches_the_party_name_not_only_the_label():
    hits, _ = _search([
        _c("sales_invoice", "inv-1", 10_000_00, label="INV-1", party_name="Acme Pvt Ltd"),
        _c("sales_invoice", "inv-2", 10_000_00, label="INV-2", party_name="Beta Ltd"),
    ], q="acme")
    assert [h.entity_id for h in hits] == ["inv-1"]


def test_the_party_filter_is_the_id_not_the_spelling():
    """Two customers can share a trading name; the id is what settlement uses."""
    hits, _ = _search([
        _c("sales_invoice", "inv-1", 10_000_00, party_id="cust-1", party_name="Acme"),
        _c("sales_invoice", "inv-2", 10_000_00, party_id="cust-2", party_name="Acme"),
    ], party_id="cust-2")
    assert [h.entity_id for h in hits] == ["inv-2"]


def test_date_filters_are_inclusive_at_both_ends():
    rows = [_c("sales_invoice", f"inv-{d}", 10_000_00, date=d)
            for d in ("2026-03-31", "2026-04-01", "2026-04-30", "2026-05-01")]
    hits, _ = _search(rows, date_from="2026-04-01", date_to="2026-04-30")
    assert {h.entity_date for h in hits} == {"2026-04-01", "2026-04-30"}


def test_a_dateless_candidate_drops_out_once_a_date_filter_is_given():
    """It cannot be shown to satisfy the filter, and quietly including it would
    make the filter a suggestion rather than a filter."""
    hits, _ = _search([_c("sales_invoice", "undated", 10_000_00, date=None)],
                      date_from="2026-04-01")
    assert hits == []


def test_amount_bounds_filter_on_the_document_not_the_difference():
    rows = [_c("sales_invoice", "small", 5_000_00),
            _c("sales_invoice", "mid", 10_000_00),
            _c("sales_invoice", "big", 50_000_00)]
    hits, _ = _search(rows, min_amount_paise=6_000_00, max_amount_paise=20_000_00)
    assert [h.entity_id for h in hits] == ["mid"]


def test_amount_bounds_are_inclusive():
    rows = [_c("sales_invoice", "at-min", 6_000_00),
            _c("sales_invoice", "at-max", 20_000_00)]
    hits, _ = _search(rows, min_amount_paise=6_000_00, max_amount_paise=20_000_00)
    assert len(hits) == 2


def test_a_zero_bound_is_a_real_filter_not_an_absent_one():
    """0 is falsy; treating it as "unset" would be the same bug that made
    limit=0 mean 200 in the register service."""
    rows = [_c("sales_invoice", "free", 0), _c("sales_invoice", "priced", 10_000_00)]
    assert [h.entity_id for h in _search(list(rows), max_amount_paise=0)[0]] == ["free"]
    assert len(_search(list(rows), min_amount_paise=0)[0]) == 2


def test_filters_combine_as_and_not_or():
    rows = [
        _c("sales_invoice", "both", 10_000_00, date="2026-04-05", party_name="Acme"),
        _c("sales_invoice", "text-only", 10_000_00, date="2025-01-01", party_name="Acme"),
        _c("sales_invoice", "date-only", 10_000_00, date="2026-04-05", party_name="Beta"),
    ]
    hits, _ = _search(rows, q="acme", date_from="2026-04-01")
    assert [h.entity_id for h in hits] == ["both"]


# ══════════════════════════════════════════════════════════════════════════════
# The shortfall, and what it is allowed to mean
# ══════════════════════════════════════════════════════════════════════════════

def test_a_ten_percent_shortfall_is_labelled_as_the_tds_shape():
    """s.194J: ₹1,00,000 invoice, 10% withheld, ₹90,000 remitted."""
    hits, _ = _search([_c("sales_invoice", "inv-1", 1_00_000_00)],
                      bank_amount_paise=90_000_00)
    assert hits[0].tds_rate_bps == 1000
    assert describe(hits[0]) == "Bank line is short by ₹10,000.00 — consistent with 10% TDS"


def test_a_bank_line_LARGER_than_the_document_is_never_called_tds():
    """A deduction cannot make the cash bigger. Labelling an overpayment as TDS
    would invite the CA to book a withholding that was never withheld."""
    hits, _ = _search([_c("sales_invoice", "inv-1", 90_000_00)],
                      bank_amount_paise=1_00_000_00)
    assert hits[0].difference_paise == -10_000_00
    assert hits[0].tds_rate_bps is None
    assert describe(hits[0]) == "Bank line is larger by ₹10,000.00"


def test_a_shortfall_that_is_not_a_tds_rate_is_reported_without_inventing_one():
    hits, _ = _search([_c("sales_invoice", "inv-1", 1_00_000_00)],
                      bank_amount_paise=93_477_00)
    assert hits[0].tds_rate_bps is None
    assert describe(hits[0]) == "Bank line is short by ₹6,523.00"


def test_an_exact_match_says_so_plainly():
    hits, _ = _search([_c("sales_invoice", "inv-1", 10_000_00)],
                      bank_amount_paise=10_000_00)
    assert hits[0].is_exact and describe(hits[0]) == "Exact amount"
    assert hits[0].bank_line_is_short is False


def test_paise_survive_the_description():
    hits, _ = _search([_c("sales_invoice", "inv-1", 10_000_07)],
                      bank_amount_paise=9_999_00)
    assert describe(hits[0]) == "Bank line is short by ₹1.07"


# ══════════════════════════════════════════════════════════════════════════════
# Paging
# ══════════════════════════════════════════════════════════════════════════════

def _many(n, start=0):
    return [_c("sales_invoice", f"inv-{i:03d}", 10_000_00 + i) for i in range(start, start + n)]


def test_the_total_counts_everything_matching_not_the_page():
    """A CA seeing 25 rows needs to know whether that is all of them; a page
    count alone cannot say that."""
    hits, total = _search(_many(40), limit=25)
    assert len(hits) == 25 and total == 40


def test_offset_walks_the_same_order_without_repeating_or_dropping():
    rows = _many(30)
    page1, _ = _search(list(rows), limit=10, offset=0)
    page2, _ = _search(list(rows), limit=10, offset=10)
    page3, _ = _search(list(rows), limit=10, offset=20)
    seen = [h.entity_id for h in page1 + page2 + page3]
    assert len(seen) == 30 and len(set(seen)) == 30


def test_an_offset_past_the_end_is_an_empty_page_not_an_error():
    hits, total = _search(_many(5), limit=10, offset=100)
    assert hits == [] and total == 5


def test_the_page_size_is_capped_however_large_the_caller_asks():
    hits, total = _search(_many(MAX_RESULTS + 50), limit=10_000)
    assert len(hits) == MAX_RESULTS and total == MAX_RESULTS + 50


def test_a_page_size_below_one_still_returns_a_row():
    """limit=0 asking for nothing would read as "no matches", which is a
    different answer."""
    hits, total = _search(_many(5), limit=0)
    assert len(hits) == 1 and total == 5


# ══════════════════════════════════════════════════════════════════════════════
# Service — fetching, scoping and refusals
# ══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table, log):
        self.s, self.t, self.log = store, table, log
        self.eqs, self.gtes, self.ltes = [], [], []
        self.limit_ = None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def is_(self, k, _v): self.eqs.append((k, None)); return self
    def gte(self, k, v): self.gtes.append((k, v)); return self
    def lte(self, k, v): self.ltes.append((k, v)); return self
    def order(self, *_a, **_k): return self
    def limit(self, n): self.limit_ = n; return self

    def execute(self):
        self.log.append((self.t, list(self.eqs), list(self.gtes), list(self.ltes)))
        rows = self.s.get(self.t, [])
        out = []
        for r in rows:
            if any(r.get(k) != v for k, v in self.eqs):
                continue
            if any(str(r.get(k) or "") < v for k, v in self.gtes):
                continue
            if any(str(r.get(k) or "") > v for k, v in self.ltes):
                continue
            out.append(dict(r))
        return _Resp(out[:self.limit_] if self.limit_ else out)


class FakeDB:
    def __init__(self, store): self.store, self.log = store, []
    def table(self, n): return _Q(self.store, n, self.log)


def _store(**over):
    s = {
        "bank_transactions": [{
            "id": "t1", "firm_id": FIRM, "client_id": CLIENT,
            "transaction_date": "2026-04-10", "debit_paise": 0, "credit_paise": 90_000_00,
        }],
        "client_sales_invoices": [{
            "id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None,
            "invoice_no": "INV-2026-0042", "invoice_date": "2026-01-05",
            "total_paise": 1_00_000_00, "paid_paise": 0,
            "customer_id": "cust-1", "status": "issued",
        }],
        "customers": [{"id": "cust-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme Pvt Ltd"}],
        "vendors": [], "receipts": [], "purchase_payments": [],
        "purchase_bills": [], "journal_entries": [],
    }
    s.update(over)
    return s


def test_a_four_month_old_invoice_is_found_when_the_band_would_have_hidden_it():
    """₹90,000 credit against a ₹1,00,000 invoice from January — outside the
    ranked list's reach on amount AND on the fetch window it used."""
    db = FakeDB(_store())
    out = svc.search(db, FIRM, "t1", USER)
    assert [r["matched_entity_id"] for r in out["results"]] == ["inv-1"]
    hit = out["results"][0]
    assert hit["label"] == "INV-2026-0042 · Acme Pvt Ltd"
    assert hit["difference_paise"] == 10_000_00
    assert hit["summary"].endswith("consistent with 10% TDS")
    assert out["direction"] == "credit" and out["amount_paise"] == 90_000_00


def test_every_read_is_scoped_to_the_firm_and_the_client():
    """A free-text search over financial documents is exactly where a missing
    tenant filter surfaces."""
    db = FakeDB(_store())
    svc.search(db, FIRM, "t1", USER)
    doc_reads = [q for q in db.log if q[0] != "bank_transactions"]
    assert doc_reads, "expected the service to read candidate tables"
    for table, eqs, _g, _l in doc_reads:
        keys = dict(eqs)
        assert keys.get("firm_id") == FIRM, table
        assert keys.get("client_id") == CLIENT, table


def test_the_transaction_itself_is_fetched_by_firm_so_another_firms_id_404s():
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, "firm-2", "t1", USER)
    assert e.value.status_code == 404


def test_a_missing_transaction_is_a_404_not_an_empty_result():
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, FIRM, "nope", USER)
    assert e.value.status_code == 404


def test_a_manager_outside_their_book_gets_nothing_even_with_a_valid_txn_id():
    """Only a Partner is firm-wide (core.authz._FIRMWIDE_ROLES). This endpoint is
    addressed by transaction id and answers with a client's open invoices and
    party names, so firm scoping alone would read out another manager's
    receivables to anyone who has a transaction id from their book.

    The check is monkeypatched because it is permissive in mock mode (no
    SUPABASE_URL, so there is no assignments table) — what is under test is that
    the service consults it at all, and refuses when it says no."""
    import services.bank_candidate_search_service as mod

    db = FakeDB(_store())
    asked = []

    def _deny(user, client_id):
        asked.append((user, client_id))
        raise HTTPException(status_code=404, detail="Not found")

    real = mod.assert_client_access
    mod.assert_client_access = _deny
    try:
        with pytest.raises(HTTPException) as e:
            mod.bank_candidate_search_service.search(db, FIRM, "t1", USER)
    finally:
        mod.assert_client_access = real

    assert e.value.status_code == 404       # not 403 — existence is not disclosed
    assert asked == [(USER, CLIENT)]
    # Refused BEFORE any document was read, not after.
    assert [q[0] for q in db.log] == ["bank_transactions"]


def test_asking_for_a_type_this_direction_cannot_settle_is_refused_out_loud():
    """Returning nothing would read as "there are none", which is a different
    and misleading answer."""
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, FIRM, "t1", USER, entity_type="purchase_bill")
    assert e.value.status_code == 422
    assert "cannot settle" in e.value.detail


def test_an_unknown_type_is_refused_before_any_document_is_read():
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, FIRM, "t1", USER, entity_type="pizza")
    assert e.value.status_code == 422
    assert db.log == []


def test_a_backwards_date_range_is_refused_rather_than_silently_empty():
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, FIRM, "t1", USER, date_from="2026-05-01", date_to="2026-04-01")
    assert e.value.status_code == 422


def test_a_minimum_above_the_maximum_is_refused():
    db = FakeDB(_store())
    with pytest.raises(HTTPException) as e:
        svc.search(db, FIRM, "t1", USER, min_amount_paise=500, max_amount_paise=100)
    assert e.value.status_code == 422


def test_documents_are_fetched_by_date_with_no_amount_band_at_all():
    """The band is what hid the answer. If it comes back, this fails."""
    db = FakeDB(_store())
    svc.search(db, FIRM, "t1", USER)
    inv = [q for q in db.log if q[0] == "client_sales_invoices"][0]
    _t, _eqs, gtes, ltes = inv
    bounded = {k for k, _v in gtes} | {k for k, _v in ltes}
    assert bounded == {"invoice_date"}, bounded


def test_draft_cancelled_and_fully_paid_invoices_stay_out_of_reach():
    """These are rules about what the ledger permits, not preferences about what
    to show, so a search box does not get to override them."""
    inv = _store()["client_sales_invoices"][0]
    rows = []
    for i, over in enumerate([{"status": "draft"}, {"status": "cancelled"},
                              {"paid_paise": 1_00_000_00}, {"deleted_at": "2026-04-01"}]):
        r = dict(inv, id=f"inv-{i}")
        r.update(over)
        rows.append(r)
    db = FakeDB(_store(client_sales_invoices=rows))
    out = svc.search(db, FIRM, "t1", USER)
    assert out["results"] == [] and out["total"] == 0


def test_receipts_are_searched_by_date_not_by_exact_amount():
    """suggestions() requires amount equality on receipts, which is right for an
    automatic offer and wrong for a search — the reason someone is searching is
    that the amounts do not line up."""
    db = FakeDB(_store(receipts=[{
        "id": "rec-1", "firm_id": FIRM, "client_id": CLIENT,
        "receipt_no": "RCP-7", "receipt_date": "2026-04-09",
        "amount_paise": 12_345_00,   # nothing like the ₹90,000 bank line
    }], client_sales_invoices=[]))
    out = svc.search(db, FIRM, "t1", USER)
    assert [r["matched_entity_id"] for r in out["results"]] == ["rec-1"]
    assert out["results"][0]["label"] == "Receipt RCP-7"


def test_an_outgoing_line_searches_bills_and_payments_instead():
    store = _store()
    store["bank_transactions"][0].update(debit_paise=50_000_00, credit_paise=0)
    store["purchase_bills"] = [{
        "id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None,
        "bill_no": "PB-9", "bill_date": "2026-04-02", "status": "unpaid",
        "total_paise": 60_000_00, "net_payable_paise": 54_000_00, "vendor_id": "vend-1",
    }]
    store["vendors"] = [{"id": "vend-1", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Ramesh Kumar"}]
    db = FakeDB(store)
    out = svc.search(db, FIRM, "t1", USER)
    assert out["direction"] == "debit"
    assert out["allowed_types"] == list(DEBIT_TYPES)
    assert [r["matched_entity_id"] for r in out["results"]] == ["bill-1"]
    # The payable, not the gross total — that is what leaves the bank.
    assert out["results"][0]["amount_paise"] == 54_000_00


def test_only_posted_journals_are_offered():
    db = FakeDB(_store(client_sales_invoices=[], journal_entries=[{
        "id": "je-1", "firm_id": FIRM, "client_id": CLIENT, "is_posted": False,
        "entry_date": "2026-04-09", "reference_no": "JE-1", "narration": "draft",
        "journal_lines": [{"debit_paise": 90_000_00, "credit_paise": 0}],
    }]))
    out = svc.search(db, FIRM, "t1", USER)
    assert out["results"] == []


def test_the_default_window_is_wide_enough_for_a_quarter_old_invoice():
    db = FakeDB(_store())
    svc.search(db, FIRM, "t1", USER)
    _t, _e, gtes, ltes = [q for q in db.log if q[0] == "client_sales_invoices"][0]
    assert dict(gtes)["invoice_date"] < "2026-01-05" < dict(ltes)["invoice_date"]
    assert DEFAULT_WINDOW_DAYS >= 365


def test_an_explicit_date_filter_narrows_the_fetch_rather_than_only_the_result():
    """Otherwise a narrow search still pays for a 400-day read."""
    db = FakeDB(_store())
    svc.search(db, FIRM, "t1", USER, date_from="2026-04-01", date_to="2026-04-30")
    _t, _e, gtes, ltes = [q for q in db.log if q[0] == "client_sales_invoices"][0]
    assert dict(gtes)["invoice_date"] == "2026-04-01"
    assert dict(ltes)["invoice_date"] == "2026-04-30"


def test_a_full_fetch_is_flagged_so_nothing_matching_reads_differently_from_too_much():
    rows = [dict(_store()["client_sales_invoices"][0], id=f"inv-{i}")
            for i in range(FETCH_LIMIT)]
    db = FakeDB(_store(client_sales_invoices=rows))
    out = svc.search(db, FIRM, "t1", USER)
    assert out["truncated"] is True
    assert out["total"] == FETCH_LIMIT and len(out["results"]) == out["limit"]


def test_a_short_result_set_is_not_flagged_as_truncated():
    db = FakeDB(_store())
    assert svc.search(db, FIRM, "t1", USER)["truncated"] is False


def test_the_endpoint_forwards_every_filter_it_accepts():
    """Eight query parameters is exactly where one gets dropped in the wiring and
    the box silently stops narrowing."""
    import routers.banking as rb

    seen = {}

    class _Spy:
        def search(self, _db, firm_id, txn_id, current_user, **kw):
            seen.update(kw, firm_id=firm_id, txn_id=txn_id, user=current_user["id"])
            return {"results": [], "total": 0}

    real_svc, real_db = rb.bank_candidate_search_service, rb._db
    rb.bank_candidate_search_service = _Spy()
    rb._db = lambda: object()
    try:
        out = rb.transaction_candidate_search(
            "t1", q="acme", date_from="2026-04-01", date_to="2026-04-30",
            min_amount_paise=100, max_amount_paise=900, entity_type="sales_invoice",
            party_id="cust-1", limit=5, offset=10,
            current_user=USER)
    finally:
        rb.bank_candidate_search_service, rb._db = real_svc, real_db

    assert out["success"] is True and out["error"] is None
    assert seen == {
        "firm_id": FIRM, "txn_id": "t1", "user": "u1", "q": "acme",
        "date_from": "2026-04-01", "date_to": "2026-04-30",
        "min_amount_paise": 100, "max_amount_paise": 900,
        "entity_type": "sales_invoice", "party_id": "cust-1",
        "limit": 5, "offset": 10,
    }


def test_the_endpoint_is_registered_where_nothing_swallows_it():
    from main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/banking/transactions/{txn_id}/candidate-search" in paths


def test_a_broken_candidate_table_degrades_to_fewer_results_not_a_500():
    """A search box is not worth a server error."""
    class Exploding(FakeDB):
        def table(self, n):
            if n == "client_sales_invoices":
                raise RuntimeError("relation does not exist")
            return super().table(n)

    db = Exploding(_store(receipts=[{
        "id": "rec-1", "firm_id": FIRM, "client_id": CLIENT,
        "receipt_no": "RCP-7", "receipt_date": "2026-04-09", "amount_paise": 90_000_00,
    }]))
    out = svc.search(db, FIRM, "t1", USER)
    assert out["total"] == 0  # the whole fetch is abandoned, but the call returns
    assert out["results"] == []
