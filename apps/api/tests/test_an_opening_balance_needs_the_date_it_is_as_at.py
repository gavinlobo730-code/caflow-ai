"""
BANK-27 — an opening balance with no as-at date, and what it does to a register.

WHAT WAS WRONG
    `bank_accounts.opening_balance_paise` is a balance AS AT
    `opening_balance_date`, and domain/banking/register.py's note 2 says so:
    "a transaction dated before the opening balance is already in it". The
    implementation is conditional on HAVING the date —

        precedes = bool(opening_date and d and d < opening_date)

    — so with no date `precedes` is false for every row and each one is added
    to a figure that may already contain it. The running balance is then wrong
    by exactly their total.

    Worse, note 3's self-check turns against itself. `balance_delta_paise` is
    the bank's own stated balance minus OUR running one, so with the running
    one wrong the register "stops agreeing with the statement" at a line that
    is perfectly fine, and the Bank Book tells the CA to go looking for a
    missing or duplicated transaction that does not exist.

    And `opening_balance_date` was `Optional[str] = None` with nothing tying it
    to the balance, so the pair was reachable from the create form, from PATCH,
    and from the API directly.

WHAT IS ASSERTED
    1. The arithmetic: the same books with and without the date give DIFFERENT
       balances, and the one without is wrong by the pre-opening line. This is
       the finding, stated as a number rather than as a policy.
    2. The divergence is fabricated too — the register accuses an innocent line.
    3. The pair is refused at creation and on the merged state of a PATCH.
    4. An account that ALREADY has the pair is not locked out: it reports the
       gap, on the register and on the account row, and still answers.
    5. A zero opening balance needs no date — nothing is double-counted by
       adding a row to zero, and demanding one there would be noise.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from domain.banking.register import (build_register, summarise, opening_balance_gap,
                                     OPENING_DATE_MISSING, OPENING_DATE_REQUIRED)
from models.banking import BankAccountIn
from tests.test_bank_register_service import _db, _txn, _reg, FIRM, CLIENT


# ── 1. the arithmetic ────────────────────────────────────────────────────────

def _books():
    """₹1,000 opening as at 1 April, and one ₹500 receipt dated 31 MARCH — the
    day before. That receipt is already inside the ₹1,000."""
    return [
        {"id": "old", "transaction_date": "2026-03-31", "credit_paise": 50000,
         "debit_paise": 0, "created_at": "a"},
        {"id": "new", "transaction_date": "2026-04-05", "credit_paise": 20000,
         "debit_paise": 0, "created_at": "b"},
    ]


def test_without_the_date_the_pre_opening_line_is_counted_twice():
    with_date = build_register(_books(), opening_balance_paise=100000,
                               opening_balance_date="2026-04-01")
    without = build_register(_books(), opening_balance_paise=100000,
                             opening_balance_date=None)

    assert [l.balance_paise for l in with_date] == [100000, 120000], (
        "the 31 March receipt is shown but not added — the opening figure has it")
    assert [l.balance_paise for l in without] == [150000, 170000]
    # The whole defect in one number: ₹500 of somebody's money, twice.
    assert without[-1].balance_paise - with_date[-1].balance_paise == 50000


def test_without_the_date_the_summary_counts_it_as_a_deposit_of_the_period():
    with_date = summarise(build_register(_books(), opening_balance_paise=100000,
                                         opening_balance_date="2026-04-01"),
                          opening_balance_paise=100000)
    without = summarise(build_register(_books(), opening_balance_paise=100000,
                                       opening_balance_date=None),
                        opening_balance_paise=100000)
    assert with_date["deposits_paise"] == 20000
    assert without["deposits_paise"] == 70000
    assert with_date["precedes_opening_count"] == 1
    assert without["precedes_opening_count"] == 0, (
        "and nothing on the screen says the line was folded in")


def test_without_the_date_the_register_accuses_an_innocent_line():
    """The bank's own stated balance is compared against our running one. With
    the running one wrong from the first row, the FIRST divergence — the one
    the Bank Book presents as diagnostic — is a line with nothing wrong."""
    books = _books()
    books[1]["balance_paise"] = 120000        # what the bank actually said
    with_date = build_register(books, opening_balance_paise=100000,
                               opening_balance_date="2026-04-01")
    without = build_register(books, opening_balance_paise=100000,
                             opening_balance_date=None)
    assert with_date[1].balance_delta_paise == 0, "we agree with the bank"
    assert without[1].balance_delta_paise == -50000, (
        "and without the date we 'disagree' by the pre-opening receipt")


# ── 2. the rule, in one place ────────────────────────────────────────────────

@pytest.mark.parametrize("paise,date_,gap", [
    (100000, "2026-04-01", None),
    (100000, None,         OPENING_DATE_MISSING),
    (100000, "",           OPENING_DATE_MISSING),
    (0,      None,         None),          # nothing to double-count against zero
    (0,      "2026-04-01", None),
    (None,   None,         None),
])
def test_the_gap_is_exactly_a_balance_without_a_date(paise, date_, gap):
    assert opening_balance_gap(paise, date_) == gap


# ── 3. refused going forward ─────────────────────────────────────────────────

def _account_in(**kw):
    base = dict(client_id=CLIENT, bank_name="HDFC Bank", account_no="50100123456789")
    base.update(kw)
    return BankAccountIn(**base)


def test_creating_an_account_with_a_balance_and_no_date_is_refused():
    with pytest.raises(ValidationError) as e:
        _account_in(opening_balance_paise=100000)
    assert OPENING_DATE_REQUIRED in str(e.value)


def test_creating_one_with_both_or_with_neither_is_fine():
    assert _account_in(opening_balance_paise=100000,
                       opening_balance_date="2026-04-01").opening_balance_date == "2026-04-01"
    assert _account_in().opening_balance_paise == 0


class _PatchDB:
    """Enough of the client for update_bank_account: one bank_accounts row it
    reads and would write back."""

    def __init__(self, row):
        self.row, self.written = dict(row), None

    def table(self, name):
        assert name == "bank_accounts", name
        return self

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def update(self, payload):
        self.written = payload
        self.row.update(payload)
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = [self.row]
        return r


def _patch(monkeypatch, stored, sent):
    from routers import banking as R
    from models.banking import BankAccountUpdateIn
    db = _PatchDB({"id": "ba-1", "firm_id": FIRM, "client_id": CLIENT, **stored})
    monkeypatch.setattr(R, "_db", lambda: db)
    monkeypatch.setattr(R, "assert_client_access", lambda *_a, **_k: None)
    R.update_bank_account("ba-1", BankAccountUpdateIn(**sent),
                          current_user={"firm_id": FIRM, "id": "u1"})
    return db


def test_a_patch_is_judged_on_the_merged_state_not_the_payload(monkeypatch):
    """The half a per-field validator cannot see. BankAccountUpdateIn carries
    only what changed, so setting a balance on an account whose STORED date is
    null is valid field by field and lands the very pair creation refuses."""
    with pytest.raises(HTTPException) as e:
        _patch(monkeypatch,
               stored={"opening_balance_paise": 0, "opening_balance_date": None},
               sent={"opening_balance_paise": 100000})
    assert e.value.status_code == 422
    assert OPENING_DATE_REQUIRED in str(e.value.detail)


def test_the_same_patch_against_an_account_that_has_a_date_goes_through(monkeypatch):
    """The negative control for the one above, in the product rather than in a
    mutated tree: the guard must refuse the PAIR, not the field."""
    db = _patch(monkeypatch,
                stored={"opening_balance_paise": 0, "opening_balance_date": "2026-04-01"},
                sent={"opening_balance_paise": 100000})
    assert db.written == {"opening_balance_paise": 100000}


def test_a_patch_that_sends_both_together_goes_through(monkeypatch):
    db = _patch(monkeypatch,
                stored={"opening_balance_paise": 0, "opening_balance_date": None},
                sent={"opening_balance_paise": 100000, "opening_balance_date": "2026-04-01"})
    assert db.written == {"opening_balance_paise": 100000,
                          "opening_balance_date": "2026-04-01"}


# ── 4. an account that already has the pair still answers ────────────────────

def test_the_register_reports_the_gap_rather_than_refusing_to_draw():
    """A refusal here would lock the CA out of the account they need to fix.
    So the register computes what it can and SAYS what it could not — the same
    shape as the unbilled-dues and MSME disclosures."""
    db = _db(opening=100000, opening_date=None)
    _txn(db, "a", "2026-04-05", credit=20000)
    out = _reg(db)
    assert out["account"]["opening_balance_gap"] == OPENING_DATE_MISSING
    assert out["lines"], "and it still draws the register"


def test_an_account_with_a_date_carries_no_gap():
    db = _db(opening=100000, opening_date="2026-04-01")
    _txn(db, "a", "2026-04-05", credit=20000)
    assert _reg(db)["account"]["opening_balance_gap"] is None


def test_the_account_list_says_it_too_because_that_is_where_it_is_fixed():
    from routers import banking as R

    rows = [{"id": "ba-1", "opening_balance_paise": 100000, "opening_balance_date": None,
             "coa_account_id": None},
            {"id": "ba-2", "opening_balance_paise": 100000,
             "opening_balance_date": "2026-04-01", "coa_account_id": None},
            {"id": "ba-3", "opening_balance_paise": 0, "opening_balance_date": None,
             "coa_account_id": None}]

    class _NoCoa:
        def table(self, _n):
            raise AssertionError("no ledger ids, so no query should be made")

    out = R._annotate_accounts(_NoCoa(), FIRM, rows)
    assert [r["opening_balance_gap"] for r in out] == [OPENING_DATE_MISSING, None, None]


def test_the_two_sentences_are_different_answers_to_different_questions():
    """One refuses a write and says what to type; the other explains an account
    that already exists. Collapsing them would either lecture the person typing
    or tell the person reading to type something they cannot reach from here."""
    assert OPENING_DATE_REQUIRED != OPENING_DATE_MISSING
    assert "Set the opening balance date" in OPENING_DATE_MISSING
    assert "needs the date it is the balance as at" in OPENING_DATE_REQUIRED
