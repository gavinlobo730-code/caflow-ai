"""
Match candidates for a whole page, in one pass over each pool.

WHAT WAS WRONG
    Every row on a page searches the SAME pools — the open invoices for this
    client, its customers, its receipts. The queue fetched them once per ROW:
    five sequential Mumbai round trips each, sixty-five for a page of thirteen,
    fired from the browser three at a time. The reader watched the green rows
    arrive a few at a time over several seconds and asked why matching was
    slow. Nothing was wrong with the ranking, which is pure arithmetic; it was
    the fetching, and it was the same mistake CLAUDE.md's reporting rule names
    — a read proportional to the number of ROWS rather than to the answer.

WHAT IS ASSERTED
    1. PARITY. The bulk path returns exactly what asking row by row returns.
       This is the one that matters: a faster path that answers differently is
       not an optimisation. The shared pool is the union of every row's amount
       band, so a row could be offered a document only some OTHER row was
       entitled to; `_in_band` stops that, and is asserted at the level where
       it is observable — see the note on
       test_the_shared_pool_is_filtered_back_to_each_rows_own_band.
    2. THE COUNT. Reads per pool, not per row — asserted as an exact number of
       queries against a counting double, because "it feels faster" is not a
       property a test can hold.
    3. The banded OR is the exact union: nothing outside any row's band comes
       back, and nothing inside one is missed.
"""
import pytest

from services.bank_matching_service import bank_matching_service as svc
import services.bank_matching_service as bms
from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


def _seed_invoice(db, inv_no, total, customer="Acme", inv_id=None):
    db.store.setdefault("customers", [])
    cust = next((c for c in db.store["customers"] if c.get("name") == customer), None)
    if not cust:
        cust = {"id": f"cust-{len(db.store['customers'])+1}", "firm_id": FIRM,
                "client_id": CLIENT, "name": customer}
        db.store["customers"].append(cust)
    db.store.setdefault("client_sales_invoices", []).append({
        "id": inv_id or f"inv-{inv_no}", "firm_id": FIRM, "client_id": CLIENT,
        "invoice_no": inv_no, "invoice_date": "2026-04-01", "total_paise": total,
        "paid_paise": 0, "customer_id": cust["id"], "status": "issued",
        "deleted_at": None,
    })


# ── 1. Parity ─────────────────────────────────────────────────────────────────

def test_the_bulk_path_answers_exactly_as_the_per_row_path_does():
    db = FakeDB()
    _seed_invoice(db, "INV-1", 100_000, "Vertex Solutions")
    _seed_invoice(db, "INV-2", 250_000, "Urban Edge")
    _seed_invoice(db, "INV-3", 999_999, "Silver Oak")
    rows = [
        _seed_txn(db, id="t1", credit_paise=100_000, debit_paise=0, description="VERTEX SOLUTIONS"),
        _seed_txn(db, id="t2", credit_paise=250_000, debit_paise=0, description="URBAN EDGE RETAIL"),
        _seed_txn(db, id="t3", credit_paise=777_000, debit_paise=0, description="NOBODY"),
    ]
    bulk = svc.suggestions_for_many(db, FIRM, CLIENT, rows)
    for t in rows:
        one = svc.suggestions(db, FIRM, t["id"])["suggestions"]
        assert bulk[t["id"]] == one, (
            f"{t['id']}: bulk and per-row disagree.\n bulk={bulk[t['id']]}\n  one={one}")


def test_parity_holds_for_money_out_too():
    db = FakeDB()
    db.store.setdefault("vendors", []).append(
        {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "Om Stationers"})
    db.store.setdefault("purchase_bills", []).append({
        "id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "OMSTA-1",
        "bill_date": "2026-04-01", "total_paise": 38_552, "net_payable_paise": 38_552,
        "vendor_id": "v1", "status": "unpaid", "deleted_at": None,
    })
    rows = [_seed_txn(db, id="d1", debit_paise=38_552, credit_paise=0,
                      description="OM STATIONERS")]
    bulk = svc.suggestions_for_many(db, FIRM, CLIENT, rows)
    assert bulk["d1"] == svc.suggestions(db, FIRM, "d1")["suggestions"]
    assert bulk["d1"], "the bill should have been offered — a vacuous parity proves nothing"


def test_a_mixed_page_keeps_each_direction_to_its_own_pool():
    """A credit must never be offered a BILL, however close the amount."""
    db = FakeDB()
    _seed_invoice(db, "INV-9", 50_000, "Acme")
    db.store.setdefault("vendors", []).append(
        {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "Beta"})
    db.store.setdefault("purchase_bills", []).append({
        "id": "bill-9", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "B-9",
        "bill_date": "2026-04-01", "total_paise": 50_000, "net_payable_paise": 50_000,
        "vendor_id": "v1", "status": "unpaid", "deleted_at": None,
    })
    rows = [_seed_txn(db, id="c1", credit_paise=50_000, debit_paise=0, description="ACME"),
            _seed_txn(db, id="d1", debit_paise=50_000, credit_paise=0, description="BETA")]
    bulk = svc.suggestions_for_many(db, FIRM, CLIENT, rows)
    assert {s["matched_entity_type"] for s in bulk["c1"]} <= {"sales_invoice", "receipt", "journal_entry"}
    assert {s["matched_entity_type"] for s in bulk["d1"]} <= {"purchase_bill", "purchase_payment", "journal_entry"}


def test_the_shared_pool_is_filtered_back_to_each_rows_own_band():
    """`_invoices_from` takes the WHOLE page's pool and must return only the
    documents THIS row is entitled to.

    Asserted here rather than through suggestions_for_many, and the reason is
    worth writing down: rank_suggestions independently rejects anything outside
    the near-match band, so removing `_in_band` changes nothing observable at
    the suggestion level — a test at that level passes either way, which is
    exactly the trap. Verified by making `_in_band` return True and watching
    the end-to-end version stay green.

    So `_in_band` is belt-and-braces against the ranker, and the contract it
    holds is this one: a shared-pool filter returns one row's candidates, and
    that must not depend on a downstream consumer's tolerance."""
    pool = [
        {"id": "inv-SMALL", "invoice_no": "SMALL", "invoice_date": "2026-04-01",
         "total_paise": 500, "paid_paise": 0, "customer_id": "c1", "status": "issued"},
        {"id": "inv-LARGE", "invoice_no": "LARGE", "invoice_date": "2026-04-01",
         "total_paise": 500_000, "paid_paise": 0, "customer_id": "c1", "status": "issued"},
    ]
    parties = {"c1": "Acme"}
    assert [c.entity_id for c in svc._invoices_from(pool, parties, 500)] == ["inv-SMALL"]
    assert [c.entity_id for c in svc._invoices_from(pool, parties, 500_000)] == ["inv-LARGE"]


def test_the_shared_bill_pool_is_filtered_back_too():
    pool = [
        {"id": "b-SMALL", "bill_no": "S", "bill_date": "2026-04-01", "total_paise": 500,
         "net_payable_paise": 500, "vendor_id": "v1", "status": "unpaid"},
        {"id": "b-LARGE", "bill_no": "L", "bill_date": "2026-04-01", "total_paise": 500_000,
         "net_payable_paise": 500_000, "vendor_id": "v1", "status": "unpaid"},
    ]
    parties = {"v1": "Beta"}
    assert [c.entity_id for c in svc._bills_from(pool, parties, 500)] == ["b-SMALL"]
    assert [c.entity_id for c in svc._bills_from(pool, parties, 500_000)] == ["b-LARGE"]


# ── 2. The count ──────────────────────────────────────────────────────────────

class CountingDB(FakeDB):
    """FakeDB that records every table read. The whole change is a claim about
    how many there are, and only a count can hold it."""

    def __init__(self):
        super().__init__()
        self.reads: list[str] = []

    def table(self, name):
        self.reads.append(name)
        return super().table(name)


def test_the_page_reads_each_pool_once_however_many_rows():
    db = CountingDB()
    for i in range(12):
        _seed_invoice(db, f"INV-{i}", 100_000 + i)
    rows = [_seed_txn(db, id=f"t{i}", credit_paise=100_000 + i, debit_paise=0,
                      description="ACME") for i in range(12)]
    db.reads.clear()
    svc.suggestions_for_many(db, FIRM, CLIENT, rows)

    # journals + invoices + customers + receipts. Four, for twelve rows.
    assert db.reads == ["journal_entries", "client_sales_invoices", "customers", "receipts"], \
        f"expected one read per pool, got {db.reads}"


def test_the_same_page_row_by_row_costs_five_reads_each():
    """The negative control for the count above, and the arithmetic behind the
    complaint: 12 rows x 5 = 60 round trips, against 4."""
    db = CountingDB()
    for i in range(12):
        _seed_invoice(db, f"INV-{i}", 100_000 + i)
    rows = [_seed_txn(db, id=f"t{i}", credit_paise=100_000 + i, debit_paise=0,
                      description="ACME") for i in range(12)]
    db.reads.clear()
    for t in rows:
        svc.suggestions(db, FIRM, t["id"])
    assert len(db.reads) == 60, f"expected 5 reads x 12 rows, got {len(db.reads)}"


def test_a_page_of_one_still_reads_no_more_than_before():
    db = CountingDB()
    _seed_invoice(db, "INV-1", 100_000)
    rows = [_seed_txn(db, id="t1", credit_paise=100_000, debit_paise=0, description="ACME")]
    db.reads.clear()
    svc.suggestions_for_many(db, FIRM, CLIENT, rows)
    assert len(db.reads) == 4, f"a single-row page should cost 4 reads, got {db.reads}"


# ── 3. The banded OR ──────────────────────────────────────────────────────────

def test_bands_merge_only_where_they_overlap():
    merged = svc._bands([100, 105, 900_000])
    assert len(merged) == 2, f"adjacent amounts should collapse to one band: {merged}"
    assert merged[0][0] == 100
    assert merged[-1][0] == 900_000


def test_the_or_filter_is_the_exact_union_of_the_bands():
    """Nothing outside every row's band, and nothing inside one missed."""
    db = FakeDB()
    _seed_invoice(db, "IN-LOW", 1_000)          # in the ₹10 row's band
    _seed_invoice(db, "GAP", 50_000)            # between the two bands
    _seed_invoice(db, "IN-HIGH", 900_000)       # in the ₹9,000 row's band
    bands = svc._bands([1_000, 900_000])
    assert len(bands) == 2, "the fixture needs two disjoint bands to be meaningful"
    pool = {r["invoice_no"] for r in svc._fetch_invoice_pool(db, FIRM, CLIENT, bands)}
    assert pool == {"IN-LOW", "IN-HIGH"}, \
        f"the banded OR did not return the exact union: {pool}"


def test_one_band_still_uses_a_plain_range():
    """The single-row query must stay byte-for-byte what it was — an or() there
    would be a needless behaviour change on the most common path."""
    seen = {}

    class _Spy(FakeDB):
        def table(self, name):
            q = super().table(name)
            orig = q.or_

            def _or(expr):
                seen["or"] = expr
                return orig(expr)
            q.or_ = _or
            return q

    db = _Spy()
    _seed_invoice(db, "INV-1", 100_000)
    svc._fetch_invoice_pool(db, FIRM, CLIENT, svc._bands([100_000]))
    assert "or" not in seen, f"a single band should not use or(): {seen}"


# ── The queue carries them ────────────────────────────────────────────────────

def test_the_queue_returns_the_matches_with_the_rows():
    """The point of the whole change: ONE request, matches included."""
    db = FakeDB()
    _seed_invoice(db, "INV-1", 100_000, "Vertex")
    _seed_txn(db, id="t1", credit_paise=100_000, debit_paise=0, description="VERTEX")
    rows = svc.queue(db, FIRM, CLIENT, "for_review", with_suggestions=True)
    assert rows[0]["suggestions"], "the queue was asked for suggestions and returned none"
    assert rows[0]["suggestions"][0]["matched_entity_id"] == "inv-INV-1"


def test_the_queue_leaves_them_out_unless_asked():
    db = FakeDB()
    _seed_invoice(db, "INV-1", 100_000, "Vertex")
    _seed_txn(db, id="t1", credit_paise=100_000, debit_paise=0, description="VERTEX")
    rows = svc.queue(db, FIRM, CLIENT, "for_review")
    assert "suggestions" not in rows[0], \
        "callers that did not ask must not pay for the pools"


def test_a_posted_row_is_not_given_candidates():
    """It has an answer already; ranking documents against it is wasted work."""
    db = FakeDB()
    _seed_invoice(db, "INV-1", 100_000, "Vertex")
    _seed_txn(db, id="t1", credit_paise=100_000, debit_paise=0,
              description="VERTEX", match_status="posted")
    rows = svc.queue(db, FIRM, CLIENT, "all", with_suggestions=True)
    assert rows[0]["suggestions"] == []
