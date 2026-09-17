"""
A reconciliation reads its own period, not the account's whole history.

WHAT WAS WRONG (BANK-07, second half)
    `bank_reconciliation_service` had two reads proportional to the LEDGER
    rather than to the ANSWER, which is the rule CLAUDE.md states under
    "Reporting performance" and measured in production at 54.34s against 2.15s
    on the same client.

      * `_account_txns` fetched every transaction the account had ever carried
        and `_classify` then discarded most of them in Python. A client three
        years into an engagement shipped three years of statement lines across
        the Singapore-to-Mumbai hop to answer a question about one month.

      * `_index_account_txns` was worse in kind: it resolved the handful of ids
        a CA had just ticked by reading the WHOLE account. The answer there is
        `len(txn_ids)` rows.

THE FINDING'S OBVIOUS FIX WOULD HAVE BEEN WRONG, WHICH IS WHY THIS FILE EXISTS
    "Apply the period predicate in the query" is the natural reading, and it
    breaks the `reconciled` bucket — the one bucket `_classify` deliberately
    does NOT date-filter. A cheque written on 28 March and cleared on 3 April
    is claimed by the April session and belongs to it whatever its own date
    says. A plain BETWEEN would take its amount out of the tie-out and out of
    the certified summary, silently, which is the failure the screen exists to
    prevent.

    So the predicate is the UNION of what the four buckets need — claimed by
    this session (any date) OR dated in the period — and the tests below pin
    BOTH limbs, because a fix that kept only the second would pass every
    ordinary fixture and fail exactly on the out-of-period cheque.

`_classify` IS UNCHANGED AND STILL FILTERS IN PYTHON
    It is the definition of the four buckets. Narrowing the fetch must not
    become a second, quieter copy of it, so the test that matters most here is
    the one asserting the narrowed fetch and the unbounded one produce
    IDENTICAL buckets on a fixture carrying a row in each limb.
"""
from __future__ import annotations

import pytest

import services.bank_reconciliation_service as brs
from services.bank_reconciliation_service import bank_reconciliation_service as svc
from tests.test_bank_reconciliation import FakeDB

FIRM, CLIENT, BA = "firm-1", "client-1", "ba-1"
START, END = "2025-04-01", "2025-04-30"


def _txn(tid, *, date, credit=0, debit=0, posted=True, recon_id=None):
    return {
        "id": tid, "firm_id": FIRM, "client_id": CLIENT, "statement_id": "stmt-1",
        "transaction_date": date, "description": f"txn {tid}", "reference_no": tid.upper(),
        "debit_paise": debit, "credit_paise": credit,
        "match_status": "posted" if posted else "matched",
        "posted_journal_id": f"je-{tid}" if posted else None,
        "reconciliation_id": recon_id, "reconciled": bool(recon_id),
    }


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(brs.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": "coa-bank"},
    ]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": START, "statement_to": END},
    ]
    d.store["bank_reconciliations"] = []
    return d


def _session(db):
    """The RAW row, not `create_session`'s view.

    `_session_view` renames the period columns for the API, and every internal
    caller of `_classify` / `_session_txns` passes what `_get_session` returned.
    Passing the view here would test a shape the service never sees.
    """
    created = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                                 opening_balance_paise=0, closing_balance_paise=0,
                                 actor_id="user-1")
    return svc._get_session(db, FIRM, created["id"])


# ── The two limbs ─────────────────────────────────────────────────────────────

def test_a_line_dated_in_the_period_is_read(db):
    db.store["bank_transactions"] = [_txn("t-in", date="2025-04-10", credit=50000)]
    s = _session(db)
    assert [t["id"] for t in svc._session_txns(db, FIRM, s)] == ["t-in"]


def test_a_line_outside_the_period_is_not_read(db):
    """The whole point. Before this, every one of these crossed the wire."""
    db.store["bank_transactions"] = [
        _txn("t-in", date="2025-04-10", credit=50000),
        _txn("t-old", date="2023-07-15", credit=11111),
        _txn("t-later", date="2025-09-02", credit=22222),
    ]
    s = _session(db)
    assert [t["id"] for t in svc._session_txns(db, FIRM, s)] == ["t-in"]


def test_a_line_this_session_already_claimed_is_read_whatever_its_date(db):
    """The out-of-period cheque, and the reason a plain BETWEEN is wrong.

    Written 28 March, cleared 3 April, claimed by the April session. `_classify`
    puts it in `reconciled`, which has no date filter, so the fetch must carry
    it or the tie-out loses its amount with nothing to say so.
    """
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t-in", date="2025-04-10", credit=50000),
        _txn("t-cheque", date="2025-03-28", credit=70000, recon_id=s["id"]),
    ]
    got = {t["id"] for t in svc._session_txns(db, FIRM, s)}
    assert got == {"t-in", "t-cheque"}


def test_another_sessions_out_of_period_claim_is_not_read(db):
    """The first limb is `this` session, not `any` session — otherwise the
    narrowing gives back every reconciled line the account ever had."""
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t-in", date="2025-04-10", credit=50000),
        _txn("t-theirs", date="2024-01-05", credit=70000, recon_id="some-other-session"),
    ]
    assert [t["id"] for t in svc._session_txns(db, FIRM, s)] == ["t-in"]


# ── The buckets do not move ───────────────────────────────────────────────────

def test_the_narrowed_fetch_and_the_whole_account_classify_identically(db):
    """The property that makes this safe, on a fixture with a row in each limb.

    If these ever disagree, the narrowing has become a second copy of
    `_classify` — which is the thing not to do.
    """
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t-in", date="2025-04-10", credit=50000),
        _txn("t-cheque", date="2025-03-28", credit=70000, recon_id=s["id"]),
        _txn("t-unposted", date="2025-04-12", credit=30000, posted=False),
        _txn("t-old", date="2023-07-15", credit=11111),
        _txn("t-later", date="2025-09-02", credit=22222),
        _txn("t-theirs", date="2024-01-05", credit=70000, recon_id="other"),
    ]
    narrow = svc._classify(s, svc._session_txns(db, FIRM, s))
    whole = svc._classify(s, svc._account_txns(db, FIRM, BA))
    for bucket in ("reconciled", "unreconciled", "exceptions", "not_passed"):
        assert [t["id"] for t in narrow[bucket]] == [t["id"] for t in whole[bucket]], bucket


# ── The id lookup is proportional to the ids ──────────────────────────────────

def test_the_id_lookup_reads_only_the_ids_asked_about(db):
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t1", date="2025-04-10", credit=50000),
        _txn("t2", date="2025-04-11", credit=60000),
        _txn("t-old", date="2023-07-15", credit=11111),
    ]
    by_id = svc._index_account_txns(db, FIRM, s, ["t1"])
    assert set(by_id) == {"t1"}


def test_the_id_lookup_still_drops_an_unposted_line(db):
    """Unchanged in MEANING: the caller's 422 says "not a posted transaction
    for this account", and an unposted id must still miss the index so it
    still gets that message rather than being silently reconciled."""
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t-unposted", date="2025-04-10", credit=50000, posted=False),
    ]
    assert svc._index_account_txns(db, FIRM, s, ["t-unposted"]) == {}


def test_the_id_lookup_asks_for_nothing_when_given_nothing(db):
    s = _session(db)
    db.store["bank_transactions"] = [_txn("t1", date="2025-04-10", credit=50000)]
    assert svc._index_account_txns(db, FIRM, s, []) == {}


def test_reconcile_still_tells_the_two_refusals_apart(db):
    """The date check stays at the CALL SITE, because "not a posted transaction
    for this account" and "outside the statement period" are different things a
    CA has to act on differently. Folding the date into the lookup would give
    the first message for both."""
    s = _session(db)
    db.store["bank_transactions"] = [
        _txn("t-outside", date="2025-03-01", credit=50000),
        _txn("t-unposted", date="2025-04-10", credit=50000, posted=False),
    ]
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as outside:
        svc.reconcile(db, FIRM, s["id"], ["t-outside"], actor_id="user-1")
    assert "outside the statement period" in outside.value.detail

    with pytest.raises(HTTPException) as unposted:
        svc.reconcile(db, FIRM, s["id"], ["t-unposted"], actor_id="user-1")
    assert "not a posted transaction" in unposted.value.detail


# ── The unbounded read keeps its one honest caller ────────────────────────────

def test_the_opening_balance_accumulation_still_sees_every_period(db):
    """`_account_txns` is NOT deleted and must not be narrowed: the
    opening-balance suggestion accumulates reconciled closing balances across
    every completed session, so it has no single period to be bounded by. The
    rule is about the size of the ANSWER, and that answer genuinely spans the
    account's history."""
    db.store["bank_transactions"] = [
        _txn("t-old", date="2023-07-15", credit=11111),
        _txn("t-in", date="2025-04-10", credit=50000),
    ]
    got = {t["id"] for t in svc._account_txns(db, FIRM, BA)}
    assert got == {"t-old", "t-in"}
