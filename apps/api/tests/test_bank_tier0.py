"""
Banking Tier 0 — the gap-audit fixes.

Covers the five items from docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md:

  0.1  matching-rule CRUD (edit / toggle / delete), firm-scoped
  0.2  a rule suggests an ACCOUNT and a NARRATION, not only a category
  0.3  (frontend-only — the TDS field in the settlement modal)
  0.4  near-amount candidates are ranked instead of filtered out, and a
       TDS-shaped shortfall is recognised
  0.5  un-ignore, and the ignored view

Every money figure here is integer paise (CLAUDE.md). The TDS arithmetic in
matcher.detect_tds_rate_bps is a financial calculation and is unit-tested
directly, including its rounding tolerance.
"""
import pytest
from fastapi import HTTPException

from domain.banking import (
    Candidate, rank_suggestions, match_rule, suggest_category,
    detect_tds_rate_bps, near_match_floor_paise,
    NEAR_MATCH_CONFIDENCE_CAP, TDS_TOLERANCE_PAISE,
)
from models.banking import MatchingRuleIn, MatchingRuleUpdateIn
from services.banking_service import banking_service
from services.bank_matching_service import bank_matching_service
import services.bank_matching_service as bms

from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


def _cand(**kw):
    base = dict(entity_type="sales_invoice", entity_id="i1", label="INV-1",
                amount_paise=10_000_000, entity_date="2026-04-10",
                party_name=None, party_id=None, outstanding_paise=None)
    base.update(kw)
    return Candidate(**base)


# ══════════════════════════════════════════════════════════════════════════════
# 0.4 — near-amount ranking and TDS recognition
# ══════════════════════════════════════════════════════════════════════════════

def test_near_match_floor_is_integer_paise():
    # 25% band on ₹1,00,000.00 → the lowest acceptable line is ₹75,000.00.
    assert near_match_floor_paise(10_000_000) == 7_500_000
    assert near_match_floor_paise(0) == 0
    assert near_match_floor_paise(-5) == 0
    # Odd amount: the band is floor-divided, never floated.
    assert near_match_floor_paise(10_000_001) == 10_000_001 - (10_000_001 * 2500) // 10000


@pytest.mark.parametrize("rate_bps,label", [
    (10, "0.1% — s.194Q / s.194-O"),
    (100, "1% — s.194C individual"),
    (200, "2% — s.194C others"),
    (500, "5% — s.194H"),
    (1000, "10% — s.194J"),
    (2000, "20% — s.206AA, no PAN"),
])
def test_detect_tds_rate_recognises_each_common_rate(rate_bps, label):
    """A ₹1,00,000 invoice settled net of TDS at each statutory rate."""
    invoice = 10_000_000
    shortfall = (invoice * rate_bps) // 10000
    assert detect_tds_rate_bps(invoice, shortfall) == rate_bps, label


def test_detect_tds_absorbs_whole_rupee_rounding():
    """Deductors round the withheld amount to whole rupees, so an exact
    basis-point match is not expected — ±₹1 is inside tolerance."""
    invoice = 9_999_900                       # ₹99,999.00
    exact = (invoice * 1000) // 10000         # ₹9,999.90 → 999990 paise
    assert detect_tds_rate_bps(invoice, exact + TDS_TOLERANCE_PAISE) == 1000
    assert detect_tds_rate_bps(invoice, exact - TDS_TOLERANCE_PAISE) == 1000
    # One paise beyond tolerance is no longer TDS-shaped.
    assert detect_tds_rate_bps(invoice, exact + TDS_TOLERANCE_PAISE + 1) is None


def test_detect_tds_rejects_unrelated_shortfall():
    assert detect_tds_rate_bps(10_000_000, 333_333) is None
    assert detect_tds_rate_bps(10_000_000, 0) is None
    assert detect_tds_rate_bps(0, 100) is None


def test_tds_short_receipt_is_suggested_at_all():
    """THE regression this tier exists for: a ₹1,00,000 invoice paid net of 10%
    TDS under s.194J arrives as a ₹90,000 credit. Under the old exact-amount
    gate this returned zero suggestions — the one correct answer was the one
    answer the CA never saw."""
    invoice = _cand(amount_paise=10_000_000, outstanding_paise=10_000_000,
                    party_name="Acme Pvt Ltd", party_id="cust-1")
    out = rank_suggestions(9_000_000, "2026-04-10", "NEFT ACME PVT LTD", [invoice])

    assert len(out) == 1
    s = out[0]
    assert s.entity_id == "i1"
    assert s.difference_paise == 1_000_000          # ₹10,000 short
    assert s.tds_rate_bps == 1000                   # 10%
    assert any("10% TDS" in r for r in s.reasons)
    assert any("short by" in r for r in s.reasons)
    assert s.party_id == "cust-1"                   # lets the UI open the modal


def test_short_match_never_reaches_high_confidence():
    """'High' must keep meaning 'the amounts agree'. A short line can gather
    every other signal and still stay below the high band."""
    short = _cand(amount_paise=10_000_000, party_name="Acme", party_id="c1",
                  outstanding_paise=10_000_000)
    out = rank_suggestions(9_000_000, "2026-04-10", "neft acme", [short])
    assert out[0].confidence <= NEAR_MATCH_CONFIDENCE_CAP
    assert out[0].confidence_label != "high"


def test_exact_match_outranks_a_short_one():
    exact = _cand(entity_id="exact", amount_paise=9_000_000)
    short = _cand(entity_id="short", amount_paise=10_000_000)
    out = rank_suggestions(9_000_000, "2026-04-10", "NEFT", [short, exact])
    assert [s.entity_id for s in out] == ["exact", "short"]
    assert out[0].difference_paise == 0


def test_shortfall_beyond_the_band_is_excluded():
    """30% short is not a withholding — it is a different transaction."""
    far = _cand(amount_paise=10_000_000)
    assert rank_suggestions(7_000_000, "2026-04-10", "NEFT", [far]) == []


def test_exact_match_still_scores_as_before():
    """The exact-amount path is untouched: same base, same bonuses, same 100."""
    c = _cand(amount_paise=10_000_000, entity_date="2026-04-10",
              party_name="Acme", outstanding_paise=10_000_000)
    s = rank_suggestions(10_000_000, "2026-04-10", "neft from acme", [c])[0]
    assert s.confidence == 100 and s.confidence_label == "high"
    assert s.difference_paise == 0 and s.tds_rate_bps is None


# ── the widened candidate FETCH (the band is useless if the query still
#    filters on exact equality) ────────────────────────────────────────────────

def _seed_invoice(db, invoice_id, total_paise, **kw):
    row = dict(id=invoice_id, firm_id=FIRM, client_id=CLIENT, invoice_no=invoice_id,
               invoice_date="2026-04-10", total_paise=total_paise, paid_paise=0,
               customer_id="cust-1", status="issued", deleted_at=None)
    row.update(kw)
    db.store.setdefault("client_sales_invoices", []).append(row)
    return row


def test_suggestions_fetch_includes_the_short_invoice():
    db = FakeDB()
    _seed_txn(db, id="t1", credit_paise=9_000_000, debit_paise=0,
              description="NEFT ACME PVT LTD")
    _seed_invoice(db, "inv-tds", 10_000_000)       # in band (10% short)
    _seed_invoice(db, "inv-far", 20_000_000)       # out of band
    db.store.setdefault("customers", []).append(
        {"id": "cust-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme Pvt Ltd"})

    res = bank_matching_service.suggestions(db, FIRM, "t1")
    ids = [s["matched_entity_id"] for s in res["suggestions"]]
    assert "inv-tds" in ids
    assert "inv-far" not in ids
    hit = next(s for s in res["suggestions"] if s["matched_entity_id"] == "inv-tds")
    assert hit["difference_paise"] == 1_000_000
    assert hit["tds_rate_bps"] == 1000
    assert hit["party_id"] == "cust-1"


# ══════════════════════════════════════════════════════════════════════════════
# 0.2 — a rule suggests an account and a narration, not only a category
# ══════════════════════════════════════════════════════════════════════════════

def _rule(**kw):
    base = dict(id="r1", firm_id=FIRM, client_id=CLIENT, rule_name="R", is_active=True)
    base.update(kw)
    return base


def test_match_rule_returns_the_full_payload():
    hit = match_rule("BANK CHARGES GST", 50_000, True, [
        _rule(description_pattern="BANK CHARGES", suggested_category="Expense",
              suggested_account_id="acc-bank-charges",
              suggested_narration="Bank charges"),
    ])
    assert hit is not None
    assert hit.category == "Expense"
    assert hit.account_id == "acc-bank-charges"     # previously read by nothing
    assert hit.narration == "Bank charges"
    assert hit.rule_name == "R" and hit.rule_id == "r1"


def test_rule_with_only_an_account_still_fires():
    hit = match_rule("NEFT", 1, True, [_rule(description_pattern="NEFT",
                                             suggested_account_id="acc-1")])
    assert hit is not None and hit.account_id == "acc-1" and hit.category is None


def test_rule_that_suggests_nothing_is_skipped_not_swallowed():
    """An empty rule must not block a later, useful one."""
    hit = match_rule("NEFT ACME", 1, True, [
        _rule(id="empty", description_pattern="NEFT"),
        _rule(id="useful", description_pattern="ACME", suggested_category="Expense"),
    ])
    assert hit is not None and hit.rule_id == "useful"


def test_suggest_category_wrapper_is_unchanged():
    rules = [_rule(description_pattern="RAZORPAY", suggested_category="Sales Receipt")]
    assert suggest_category("NEFT RAZORPAY", 50_000, False, rules) == "Sales Receipt"
    assert suggest_category("ATM WITHDRAWAL", 50_000, False, rules) is None


def test_queue_surfaces_account_and_narration():
    db = FakeDB()
    _seed_txn(db, id="u1", description="HDFC BANK CHARGES", debit_paise=5_000,
              credit_paise=0)
    db.store.setdefault("bank_matching_rules", []).append(_rule(
        description_pattern="BANK CHARGES", suggested_category="Expense",
        suggested_account_id="acc-bank-charges", suggested_narration="Bank charges",
        created_at="2026-01-01"))

    row = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]
    assert row["suggested_category"] == "Expense"
    assert row["suggested_account_id"] == "acc-bank-charges"
    assert row["suggested_narration"] == "Bank charges"
    assert row["suggested_by_rule"] == "R"


def test_queue_prefers_an_existing_category_over_the_rule():
    """The rule proposes; the CA disposes."""
    db = FakeDB()
    _seed_txn(db, id="u1", description="BANK CHARGES", category="Interest",
              debit_paise=5_000, credit_paise=0)
    db.store.setdefault("bank_matching_rules", []).append(_rule(
        description_pattern="BANK CHARGES", suggested_category="Expense",
        created_at="2026-01-01"))
    row = bank_matching_service.queue(db, FIRM, CLIENT, "categorized")[0]
    assert row["suggested_category"] == "Interest"


def test_queue_rule_precedence_is_creation_order():
    """Two rules match; the older one wins, deterministically. The fetch used to
    be unordered, so 'first' depended on whatever order Postgres returned."""
    db = FakeDB()
    _seed_txn(db, id="u1", description="UPI PAYMENT", debit_paise=5_000, credit_paise=0)
    rules = db.store.setdefault("bank_matching_rules", [])
    rules.append(_rule(id="newer", rule_name="Newer", description_pattern="UPI",
                       suggested_category="Other", created_at="2026-06-01"))
    rules.append(_rule(id="older", rule_name="Older", description_pattern="UPI",
                       suggested_category="Expense", created_at="2026-01-01"))
    row = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]
    assert row["suggested_by_rule"] == "Older"
    assert row["suggested_category"] == "Expense"


# ══════════════════════════════════════════════════════════════════════════════
# 0.1 — rule validation and CRUD
# ══════════════════════════════════════════════════════════════════════════════

def test_rule_rejects_an_unknown_category():
    """suggested_category lands on bank_transactions.category, which has a DB
    CHECK. Validate when the rule is written, not when the CA accepts it."""
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R",
                       description_pattern="X", suggested_category="Bank Charges")


def test_rule_requires_at_least_one_condition():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", suggested_category="Expense")


def test_rule_requires_at_least_one_suggestion():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", description_pattern="X")


def test_rule_rejects_an_inverted_amount_range():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", suggested_category="Expense",
                       amount_min_paise=100_000, amount_max_paise=1_000)


def test_rule_rejects_an_unknown_txn_type():
    with pytest.raises(ValueError):
        MatchingRuleIn(client_id=CLIENT, rule_name="R", suggested_category="Expense",
                       description_pattern="X", txn_type="sideways")


def test_rule_accepts_an_amount_range_as_its_only_condition():
    rule = MatchingRuleIn(client_id=CLIENT, rule_name="Big debits",
                          amount_min_paise=1_000_000, suggested_category="Expense")
    assert rule.amount_min_paise == 1_000_000


def test_rule_update_allows_a_bare_toggle():
    """Deactivating must not require re-sending every condition."""
    upd = MatchingRuleUpdateIn(is_active=False)
    assert upd.model_dump(exclude_none=True) == {"is_active": False}


def test_rule_update_still_validates_what_it_is_given():
    with pytest.raises(ValueError):
        MatchingRuleUpdateIn(suggested_category="Not A Category")
    with pytest.raises(ValueError):
        MatchingRuleUpdateIn(amount_min_paise=500, amount_max_paise=100)


# ── router CRUD against a fake DB ────────────────────────────────────────────
# _db() returns None without SUPABASE_URL, so point it at the in-memory fake to
# exercise the real code path rather than the mock early-return.

PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


@pytest.fixture
def rules_db(monkeypatch):
    import core.authz as authz
    import routers.banking as banking_router
    db = FakeDB()
    monkeypatch.setattr(banking_router, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)   # client-ownership is not what these test
    db.store.setdefault("bank_matching_rules", []).append(_rule(
        description_pattern="RAZORPAY", suggested_category="Sales Receipt",
        created_at="2026-01-01"))
    return db, banking_router


def test_update_rule_writes_only_the_supplied_fields(rules_db):
    db, router = rules_db
    res = router.update_rule("r1", MatchingRuleUpdateIn(suggested_category="Other"),
                             current_user=PARTNER)
    assert res["success"] is True
    stored = db.store["bank_matching_rules"][0]
    assert stored["suggested_category"] == "Other"
    assert stored["description_pattern"] == "RAZORPAY"     # untouched


def test_update_rule_toggles_active(rules_db):
    db, router = rules_db
    router.update_rule("r1", MatchingRuleUpdateIn(is_active=False), current_user=PARTNER)
    assert db.store["bank_matching_rules"][0]["is_active"] is False


def test_update_rule_404s_on_another_firms_rule(rules_db):
    db, router = rules_db
    db.store["bank_matching_rules"][0]["firm_id"] = "other-firm"
    with pytest.raises(HTTPException) as ei:
        router.update_rule("r1", MatchingRuleUpdateIn(is_active=False), current_user=PARTNER)
    assert ei.value.status_code == 404


def test_delete_rule_removes_it(rules_db):
    db, router = rules_db
    assert router.delete_rule("r1", current_user=PARTNER)["data"]["deleted"] is True
    assert db.store["bank_matching_rules"] == []


def test_delete_rule_404s_on_another_firms_rule(rules_db):
    db, router = rules_db
    db.store["bank_matching_rules"][0]["firm_id"] = "other-firm"
    with pytest.raises(HTTPException) as ei:
        router.delete_rule("r1", current_user=PARTNER)
    assert ei.value.status_code == 404
    assert len(db.store["bank_matching_rules"]) == 1


def test_list_rules_includes_inactive_ones(rules_db):
    """The rules screen must be able to show — and so reactivate — a rule that
    was switched off. The queue applies its own is_active filter."""
    db, router = rules_db
    db.store["bank_matching_rules"].append(_rule(
        id="r2", rule_name="Off", description_pattern="UPI",
        suggested_category="Other", is_active=False, created_at="2026-02-01"))
    ids = [r["id"] for r in router.list_rules(client_id=CLIENT, current_user=PARTNER)["data"]]
    assert ids == ["r1", "r2"]          # both, in creation order


def test_queue_still_ignores_inactive_rules(rules_db):
    db, _ = rules_db
    db.store["bank_matching_rules"][0]["is_active"] = False
    _seed_txn(db, id="u1", description="UPI RAZORPAY PAYOUT")
    assert bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]["suggested_category"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 0.5 — un-ignore and the ignored view
# ══════════════════════════════════════════════════════════════════════════════

def test_unignore_restores_an_ignored_transaction():
    db = FakeDB()
    _seed_txn(db, id="t1")
    banking_service.ignore(db, FIRM, "t1")
    assert banking_service.unignore(db, FIRM, "t1")["match_status"] == "unmatched"


def test_unignore_restores_a_surviving_match():
    db = FakeDB()
    _seed_txn(db, id="t1", matched_entity_id="inv-1", matched_entity_type="sales_invoice")
    banking_service.ignore(db, FIRM, "t1")
    assert banking_service.unignore(db, FIRM, "t1")["match_status"] == "matched"


def test_unignore_rejects_a_transaction_that_is_not_ignored():
    db = FakeDB()
    _seed_txn(db, id="t1")
    with pytest.raises(HTTPException) as ei:
        banking_service.unignore(db, FIRM, "t1")
    assert ei.value.status_code == 409


def test_ignored_view_lists_ignored_rows():
    db = FakeDB()
    _seed_txn(db, id="live")
    _seed_txn(db, id="gone")
    banking_service.ignore(db, FIRM, "gone")
    ids = lambda st: {t["id"] for t in bank_matching_service.queue(db, FIRM, CLIENT, st)}
    assert ids("ignored") == {"gone"}
    assert ids("unmatched") == {"live"}
    assert ids("all") == {"live", "gone"}


def test_ignored_rows_stay_out_of_the_working_views():
    """An ignored row that still carries a category or a link used to reappear
    under Categorized/Matched as if it were live work."""
    db = FakeDB()
    _seed_txn(db, id="c1", category="Expense")
    _seed_txn(db, id="m1", matched_entity_id="inv-1")
    banking_service.ignore(db, FIRM, "c1")
    banking_service.ignore(db, FIRM, "m1")
    ids = lambda st: {t["id"] for t in bank_matching_service.queue(db, FIRM, CLIENT, st)}
    assert ids("categorized") == set()
    assert ids("matched") == set()
    assert ids("ignored") == {"c1", "m1"}


def test_queue_rejects_an_unknown_view():
    db = FakeDB()
    with pytest.raises(HTTPException) as ei:
        bank_matching_service.queue(db, FIRM, CLIENT, "excluded")
    assert ei.value.status_code == 422
