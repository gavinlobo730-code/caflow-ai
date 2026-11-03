"""A bank debit equal to a recorded TDS challan is PROPOSED as its payment, and passing it ties the challan (ledger POST-A-272, migration 578).

WHAT WAS WRONG
    A recorded TDS challan can be tied to the ledger entry that paid it, by hand. Nothing OFFERED the bank line that paid it: the tax leaves
    the bank on a statement line, the queue proposes a line from a rule, a document, a transfer or the account's history, and none of them
    knows a challan, so the line waited for the CA to code it TDS Payable and the challan waited to be tied to the entry that made.

WHAT THIS HOLDS
    * THE PURE PROPOSAL (`domain/banking/entry.from_challan`): a debit whose amount is the total of EXACTLY ONE recorded, untied challan paid
      within the window of the line's date is proposed on the ledger the challan's section clears; it is NEVER READY (an amount is not a
      payment, and "Pass N ready" must never reach it); two challans of one amount, a credit, another amount, a date outside the window, an
      unreadable date and a chart with no such account each get no draft at all.
    * THE RANK: a challan outranks a same-grade transfer and history and yields to a rule and a document, and a READY draft of any source
      beats it (the grade first, as for every source).
    * REDRAFT writes it on the open line, from a read of the client's untied challans made ONCE per chunk; a challan already tied, another
      client's challan and a challan of a client whose chart has no TDS Payable account are not offered; a challan proposed to an earlier
      line of the chunk is not offered to a later one.
    * PASSING IT applies the ledger the way a person's choice does, posts through the ordinary bank posting, and then ties the challan to
      the entry that posting made, through the challan's own door (which asks the questions a hand-made tie asks). A tie that cannot be made
      never undoes the pass: the line is in the books, and the answer says in words that the challan was not tied.
    * "Pass N ready" never passes it, and a trusted rule's sweep never reaches it (both read the grade).
    * A CHALLAN RECORDED, RETRACTED, TIED OR UNTIED marks the client's open lines stale, so the next look at the queue re-proposes them.
"""
from __future__ import annotations

import pytest

from domain.banking import entry as E
import services.bank_entry_service as bes
from services.bank_entry_service import bank_entry_service as svc
from tests.test_bank_entry_service import _db, _line, _row, _state, _quiet, poster  # noqa: F401  (fixtures and helpers)
from tests.test_bank_matching import FIRM, CLIENT

TDS, TDS_SAL = "acc-tds", "acc-tds-sal"
OTHER_CLIENT = "client-other"


def _chart(db):
    db.store["chart_of_accounts"] += [
        {"id": TDS, "firm_id": FIRM, "client_id": CLIENT, "account_name": "TDS Payable", "account_type": "Liability",
         "account_code": "2310", "is_active": True},
        {"id": TDS_SAL, "firm_id": FIRM, "client_id": CLIENT, "account_name": "TDS Payable - Salary", "account_type": "Liability",
         "account_code": "2311", "is_active": True},
    ]


def _challan(db, cid="ch-1", total=500_000, paid="2026-04-15", section="194C", no="0123456", client=CLIENT, tied=None):
    row = {"id": cid, "firm_id": FIRM, "client_id": client, "challan_no": no, "payment_date": paid, "total_paise": total,
           "section": section, "journal_entry_id": tied}
    db.store.setdefault("tds_challans", []).append(row)
    return row


def _world(**challan):
    db = _db()
    _chart(db)
    _challan(db, **challan)
    return db


# ── the pure proposal ───────────────────────────────────────────────────────────────────────────────────

def _c(**kw):
    base = {"id": "c1", "challan_no": "0123", "payment_date": "2026-04-15", "total_paise": 500_000, "account_id": "a1",
            "account_name": "TDS Payable"}
    base.update(kw)
    return base


def _t(**kw):
    base = {"debit_paise": 500_000, "credit_paise": 0, "transaction_date": "2026-04-15"}
    base.update(kw)
    return base


def test_exactly_one_challan_of_the_amount_inside_the_window_is_proposed_never_ready():
    d = E.from_challan(_t(), [_c()])
    assert d is not None and d.source == E.SOURCE_CHALLAN and d.grade == E.GRADE_PROPOSED
    assert (d.account_id, d.entity_type, d.entity_id) == ("a1", "tds_challan", "c1")
    assert "0123" in d.label and "Dr TDS Payable / Cr Bank" in d.reason and "not tied to the ledger yet" in d.reason


@pytest.mark.parametrize("label,txn,challans", [
    ("a credit", _t(debit_paise=0, credit_paise=500_000), [_c()]),
    ("a line carrying a credit as well as the debit", _t(credit_paise=100), [_c()]),
    ("another amount", _t(debit_paise=500_001), [_c()]),
    ("a date a day past the window", _t(transaction_date="2026-04-23"), [_c()]),
    ("a date a day before the window", _t(transaction_date="2026-04-07"), [_c()]),
    ("an unreadable line date", _t(transaction_date="soon"), [_c()]),
    ("an unreadable challan date", _t(), [_c(payment_date="")]),
    ("a challan with no ledger account", _t(), [_c(account_id=None)]),
    ("two challans of that amount", _t(), [_c(), _c(id="c2", challan_no="0999")]),
    ("no challan at all", _t(), []),
])
def test_everything_else_gets_no_draft(label, txn, challans):
    assert E.from_challan(txn, challans) is None, label


def test_the_edge_of_the_window_is_inside_it_and_the_window_is_the_challan_lists_own():
    from domain.payroll import remittance_match
    assert E.CHALLAN_WINDOW_DAYS == remittance_match.DEFAULT_WINDOW_DAYS == 7
    assert E.from_challan(_t(transaction_date="2026-04-22"), [_c()]) is not None
    assert E.from_challan(_t(transaction_date="2026-04-08"), [_c()]) is not None


def test_two_challans_of_one_amount_one_of_them_outside_the_window_is_still_exactly_one():
    assert E.from_challan(_t(), [_c(), _c(id="c2", payment_date="2026-01-01")]).entity_id == "c1"


def _d(source, grade, label="x"):
    return E.Draft(source=source, grade=grade, label=label, reason="r")


def test_a_challan_outranks_a_proposed_transfer_and_history_and_yields_to_a_rule_and_a_document():
    ch, tr, hi = _d("challan", "proposed"), _d("transfer", "proposed"), _d("history", "proposed")
    assert E.choose(None, None, tr, hi, ch) is ch
    assert E.choose(_d("rule", "proposed"), None, tr, hi, ch).source == "rule"
    assert E.choose(None, _d("document", "proposed"), tr, hi, ch).source == "document"
    # the grade comes first: a READY draft of any source beats the challan
    assert E.choose(None, None, _d("transfer", "ready"), hi, ch).source == "transfer"
    assert E.choose(None, None, None, _d("history", "ready"), ch).source == "history"


def test_choose_still_works_with_the_four_arguments_every_old_caller_passes():
    assert E.choose(None, None, None, None) is None
    assert E.choose(_d("rule", "ready"), None, None, None).source == "rule"


def test_the_source_vocabulary_has_five_words():
    assert E.SOURCES == ("rule", "document", "history", "transfer", "challan")


# ── redraft ─────────────────────────────────────────────────────────────────────────────────────────────

def test_redraft_writes_the_proposal_on_the_open_line_as_proposed():
    db = _world()
    _line(db, "t1", "BY CLG TDS CHALLAN", debit=500_000)
    svc.redraft(db, FIRM, CLIENT)
    r = _row(db, "t1")
    assert (r["draft_source"], r["draft_grade"]) == ("challan", "proposed")
    assert (r["draft_account_id"], r["draft_entity_type"], r["draft_entity_id"]) == (TDS, "tds_challan", "ch-1")
    assert "0123456" in r["draft_label"] and _state(db, "t1") == E.PROPOSED


def test_a_salary_challan_is_proposed_on_the_salary_ledger_and_no_other():
    db = _world(section="192")
    _line(db, "t1", "TDS", debit=500_000)
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_account_id"] == TDS_SAL


def test_a_salary_challan_and_another_in_one_chunk_each_get_the_ledger_their_own_section_clears():
    db = _world(section="192", cid="ch-sal", total=500_000, no="S1")
    _challan(db, cid="ch-other", total=700_000, section="194C", no="O1")
    _line(db, "t1", "TDS SAL", debit=500_000)
    _line(db, "t2", "TDS OTHER", debit=700_000)
    svc.redraft(db, FIRM, CLIENT)
    assert (_row(db, "t1")["draft_account_id"], _row(db, "t2")["draft_account_id"]) == (TDS_SAL, TDS)


def test_a_credit_a_tied_challan_another_clients_challan_and_a_chart_without_the_account_get_nothing():
    for label, build in (
        ("a credit", lambda: (_world(), dict(debit=0, credit=500_000))),
        ("a tied challan", lambda: (_world(tied="je-1"), dict(debit=500_000))),
        ("another client's challan", lambda: (_world(client=OTHER_CLIENT), dict(debit=500_000))),
    ):
        db, kw = build()
        _line(db, "t1", "TDS", **kw)
        svc.redraft(db, FIRM, CLIENT)
        assert _row(db, "t1")["draft_source"] is None, label
    db = _db()                                       # a chart with no TDS Payable account at all
    _challan(db)
    _line(db, "t1", "TDS", debit=500_000)
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_source"] is None


def test_the_challans_are_read_once_per_chunk_and_not_at_all_for_a_chunk_of_receipts():
    db = _world()
    reads = []
    real = db.table

    def table(name):
        if name == "tds_challans":
            reads.append(name)
        return real(name)

    db.table = table
    _line(db, "t1", "TDS", debit=500_000)
    _line(db, "t2", "TDS", debit=700_000)
    _line(db, "t3", "TDS", debit=900_000)
    svc.redraft(db, FIRM, CLIENT)
    assert len(reads) == 1, "one read of the challans for the whole chunk"
    db2 = _world()
    reads.clear()
    db2.table = lambda name: (reads.append(name), real(name))[1] if name == "tds_challans" else real(name)
    _line(db2, "r1", "CREDIT", debit=0, credit=500_000)
    svc.redraft(db2, FIRM, CLIENT)
    assert reads == [], "a chunk with no debit never reads the challans"


def test_two_lines_of_one_amount_in_one_chunk_do_not_both_claim_the_one_challan():
    db = _world()
    _line(db, "t1", "TDS A", debit=500_000, transaction_date="2026-04-15")
    _line(db, "t2", "TDS B", debit=500_000, transaction_date="2026-04-16")
    svc.redraft(db, FIRM, CLIENT)
    sources = sorted(str(_row(db, t)["draft_source"]) for t in ("t1", "t2"))
    assert sources == ["None", "challan"], sources


def test_a_failed_read_of_the_challans_means_no_proposal_and_not_a_failed_redraft(monkeypatch):
    db = _world()
    _line(db, "t1", "TDS", debit=500_000)
    real = db.table

    def table(name):
        if name == "tds_challans":
            raise RuntimeError("the register could not be read")
        return real(name)

    db.table = table
    out = svc.redraft(db, FIRM, CLIENT)
    assert out["drafted"] == 1 and _row(db, "t1")["draft_source"] is None


def test_a_rule_and_a_ready_history_outrank_the_challan_on_the_same_line():
    from tests.test_bank_entry_service import _rule
    db = _world()
    _rule(db, pattern="TDS", account="acc-charges")
    _line(db, "t1", "TDS CHALLAN", debit=500_000)
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_source"] == "rule"


# ── passing it ──────────────────────────────────────────────────────────────────────────────────────────

class _PostingPoster:
    """bank_posting_service.post, standing in: posts the line (marks it, and makes the entry Dr <the line's ledger> / Cr Bank) the way the
    real one does, so the challan's tie can ask the ledger the questions it asks."""

    def __init__(self):
        self.calls = []

    def __call__(self, db, firm_id, txn_id, bank_account_id=None, account_id=None, to_bank_account_id=None, actor_id=None,
                 gst_rate_bps=None, is_interstate=False, actor_auth_id=None):
        row = next(r for r in db.store["bank_transactions"] if r["id"] == txn_id)
        self.calls.append({"txn_id": txn_id, "account_id": row.get("account_id")})
        je = f"je-{txn_id}"
        db.store.setdefault("journal_entries", []).append({
            "id": je, "firm_id": firm_id, "client_id": row["client_id"], "entry_date": row["transaction_date"], "reference_no": txn_id,
            "is_posted": True, "is_reversed": False, "reversal_of": None, "deleted_at": None})
        db.store.setdefault("journal_lines", []).append({
            "journal_entry_id": je, "account_id": row["account_id"], "debit_paise": row["debit_paise"], "credit_paise": 0})
        row.update({"match_status": "posted", "posted_journal_id": je, "posted_by": actor_id})
        return {"id": txn_id, "status": "posted", "match_status": "posted", "posted_journal_id": je}


@pytest.fixture
def posting(monkeypatch):
    p = _PostingPoster()
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    return p


@pytest.fixture
def audit_goes_to_the_same_database(monkeypatch):
    holder = {}
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: holder["db"])
    return holder


def _passed_world(audit):
    db = _world()
    audit["db"] = db
    _line(db, "t1", "BY CLG TDS CHALLAN", debit=500_000)
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_source"] == "challan"
    return db


ACTOR = dict(actor_id="user-1", actor_auth_id="auth-1")


def test_passing_the_proposal_posts_on_the_challans_ledger_and_ties_the_challan_to_that_entry(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    out = svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert out["status"] == "passed" and "challan_tie" not in out, out
    assert posting.calls == [{"txn_id": "t1", "account_id": TDS}], "the line was posted on TDS Payable, by the ordinary bank posting"
    assert next(c for c in db.store["tds_challans"] if c["id"] == "ch-1")["journal_entry_id"] == "je-t1"
    log = [r for r in db.store.get("audit_log", []) if r.get("entity_type") == "tds_challan"]
    assert log and log[0]["action"] == "link_payment" and log[0]["actor_id"] == "auth-1", "the tie is audited as the person who passed"


def test_a_tie_that_cannot_be_made_never_undoes_the_pass_and_says_so(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    # somebody tied the challan by hand between the proposal and the pass
    next(c for c in db.store["tds_challans"] if c["id"] == "ch-1")["journal_entry_id"] = "je-elsewhere"
    out = svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert out["status"] == "passed", out
    assert "challan was not tied" in out["reason"] and "already tied" in out["reason"]
    assert out["challan_tie"] in out["reason"]
    assert _row(db, "t1")["match_status"] == "posted"
    assert next(c for c in db.store["tds_challans"] if c["id"] == "ch-1")["journal_entry_id"] == "je-elsewhere"


def test_a_challan_that_has_left_the_register_does_not_stop_the_pass(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    db.store["tds_challans"].clear()
    out = svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert out["status"] == "passed" and "no longer in the register" in out["reason"], out


def test_a_failed_posting_leaves_the_challan_untied_and_restores_the_line(monkeypatch, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    from fastapi import HTTPException

    def refuse(*a, **k):
        raise HTTPException(status_code=422, detail="the year is locked")

    monkeypatch.setattr(bes.bank_posting_service, "post", refuse)
    out = svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert out["status"] == "failed" and "locked" in out["reason"]
    assert next(c for c in db.store["tds_challans"] if c["id"] == "ch-1")["journal_entry_id"] is None
    assert _row(db, "t1")["account_id"] is None, "the machine's coding was taken back"


def test_a_line_the_ca_coded_themselves_is_posted_as_coded_and_ties_nothing(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    _row(db, "t1")["account_id"] = TDS
    out = svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert out["status"] == "passed" and "challan_tie" not in out
    assert next(c for c in db.store["tds_challans"] if c["id"] == "ch-1")["journal_entry_id"] is None


def test_pass_ready_never_passes_a_challan_proposal(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    out = svc.pass_ready(db, FIRM, CLIENT, actor_id="user-1")
    assert posting.calls == [] and _row(db, "t1")["match_status"] != "posted", out


def test_tying_the_challan_marks_the_other_open_lines_stale(posting, audit_goes_to_the_same_database):
    db = _passed_world(audit_goes_to_the_same_database)
    _line(db, "t2", "TDS AGAIN", debit=500_000, transaction_date="2026-04-16", drafted_at="2026-04-16T00:00:00Z")
    svc.pass_entry(db, FIRM, "t1", **ACTOR)
    assert _row(db, "t2")["drafted_at"] is None, "a line still proposing the tied challan must be re-proposed"


# ── the register's changes mark the queue stale ─────────────────────────────────────────────────────────

def test_every_change_to_the_register_that_moves_a_proposal_marks_the_clients_lines_stale():
    """Recorded, retracted, tied, untied: each calls `_bank_proposals_may_have_changed` after its change. A rule over the four handlers, so a
    fifth that moves the register's ties is a test to extend and not a silent omission."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "routers" / "tds_workspace.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    calls = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
             and any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_bank_proposals_may_have_changed" for n in ast.walk(fn))}
    assert calls == {"create_challan", "retract_challan", "link_challan_payment", "unlink_challan_payment"}, calls


def test_the_helper_marks_the_lines_stale_and_never_raises(monkeypatch):
    import routers.tds_workspace as tw
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    seen = []
    import services.bank_draft_staleness as staleness
    monkeypatch.setattr(staleness, "mark_stale", lambda db, firm, client: seen.append((firm, client)))
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: object())
    tw._bank_proposals_may_have_changed("f", "c")
    assert seen == [("f", "c")]

    def boom(db, firm, client):
        raise RuntimeError("down")

    monkeypatch.setattr(staleness, "mark_stale", boom)
    tw._bank_proposals_may_have_changed("f", "c")           # does not raise
