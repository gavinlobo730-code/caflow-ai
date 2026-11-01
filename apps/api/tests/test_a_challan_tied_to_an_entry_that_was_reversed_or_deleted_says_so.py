"""POST-A-272 (the stale link) — a challan tied to a ledger entry that was later reversed or deleted says so, in the server's words.

WHAT WAS WRONG
    A challan is tied to the entry that paid it by `tds_challans.journal_entry_id` (migration 568). The column is cleared when the entry is
    hard-deleted (ON DELETE SET NULL), but a posted entry is never hard-deleted: it is REVERSED (a reversal is appended and the original is
    flagged) or soft-deleted. The link then still pointed at an entry that no longer records the payment, and the Challans tab went on saying
    "Tied to an entry": a false statement about the ledger, on a statutory register.

WHAT THIS PINS
    STATE     for each tied challan the entry is read for this firm AND client and is live, reversed, deleted, or missing (no such entry of this
              client, which is also what another client's entry id reads as); an untied challan gets no link;
    WORDS     each state has the server's own label (and a note that tells the CA what to do for the three that are not live), and a failed read
              of the ledger marks every tied challan UNKNOWN with its own words: a failed read is never a live link;
    SURFACES  the challan list carries the link on each tied row, over a whole window, and the candidates answer carries it for the dialog;
    NEVER     the link is not cleared, the entry is not touched, and nothing is posted by reading it.
    RECOVERY  an entry that no longer records a payment (a draft, a reversed original, the reversal that undid it, a deleted one) is
              not OFFERED as the payment, is REFUSED if named, and reads as such beside a tied challan: one rule
              (`remittance_match.entry_state`) for all three, so "take the link back and tie it again" is not met by the entry that was
              just undone. The shared candidate query serves ESI and professional tax too; their candidates follow the same rule.
"""
import uuid

import pytest

import routers.tds_workspace as tw
from services import tds_challan_ledger_service as svc
from services import tds_register_lists_service as lists
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _id(n: int) -> str:
    return str(uuid.UUID(int=n))


LIVE, REVERSED, DELETED, OTHER_CLIENT, GONE = (_id(i) for i in (1, 2, 3, 4, 5))


def _entry(db, je, client, *, reversed_=False, deleted=None):
    db.seed("journal_entries", {"id": je, "firm_id": FIRM, "client_id": client, "entry_date": "2026-07-07", "reference_no": f"R-{je[-2:]}",
                                "narration": "TDS paid", "is_reversed": reversed_, "deleted_at": deleted})


def _challan(db, cid, link, client=A, no="CH"):
    return db.seed("tds_challans", {"id": cid, "firm_id": FIRM, "client_id": client, "section": "194C", "total_paise": 100_000_00,
                                    "payment_date": "2026-07-07", "challan_no": no, "journal_entry_id": link,
                                    "financial_year": "2026-27", "quarter": "Q2"})


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    _entry(db, LIVE, A)
    _entry(db, REVERSED, A, reversed_=True)
    _entry(db, DELETED, A, deleted="2026-07-08T00:00:00+00:00")
    _entry(db, OTHER_CLIENT, B)
    wire_e2e(monkeypatch, db, [tw])
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: True)
    return db


def states(db, ids):
    return svc.entry_states(db, firm_id=FIRM, client_id=A, entry_ids=ids)


# ── the state of an entry ────────────────────────────────────────────────────────────────────────────────────────────

def test_an_entry_is_live_reversed_deleted_or_missing(world):
    assert states(world, [LIVE, REVERSED, DELETED, GONE]) == {LIVE: "live", REVERSED: "reversed", DELETED: "deleted", GONE: "missing"}


def test_another_clients_entry_reads_as_missing_and_is_never_described(world):
    assert states(world, [OTHER_CLIENT]) == {OTHER_CLIENT: "missing"}
    assert svc.entry_states(world, firm_id="another-firm", client_id=A, entry_ids=[LIVE]) == {LIVE: "missing"}


def test_a_deleted_entry_that_was_also_reversed_reads_as_deleted(world):
    _entry(world, _id(9), A, reversed_=True, deleted="2026-07-09T00:00:00+00:00")
    assert states(world, [_id(9)]) == {_id(9): "deleted"}


def test_more_entries_than_one_request_holds_are_all_read(world):
    ids = [_id(1000 + i) for i in range(250)]
    for i in ids[::2]:
        _entry(world, i, A)
    out = states(world, ids)
    assert len(out) == 250 and {out[i] for i in ids[::2]} == {"live"} and {out[i] for i in ids[1::2]} == {"missing"}


def test_nothing_asked_reads_nothing(world):
    assert states(world, []) == {} and states(world, [None, ""]) == {}


# ── the words on a row ───────────────────────────────────────────────────────────────────────────────────────────────

def rows_for(db, *links):
    rows = [_challan(db, _id(100 + n), link, no=f"CH-{n}") for n, link in enumerate(links)]
    svc.annotate_links(db, firm_id=FIRM, client_id=A, rows=rows)
    return rows


def test_a_live_link_says_tied_and_has_no_note(world):
    row, = rows_for(world, LIVE)
    assert row["ledger_link"] == {"state": "live", "label": "Tied to an entry", "note": None}


@pytest.mark.parametrize("link,state,label", [
    (REVERSED, "reversed", "Tied to an entry that was reversed"),
    (DELETED, "deleted", "Tied to an entry that was deleted"),
    (GONE, "missing", "Tied to an entry that can no longer be found"),
])
def test_a_link_to_an_entry_that_no_longer_records_the_payment_says_so_and_what_to_do(world, link, state, label):
    row, = rows_for(world, link)
    assert row["ledger_link"]["state"] == state and row["ledger_link"]["label"] == label
    note = row["ledger_link"]["note"]
    assert "Take the link back" in note
    if state != "missing":
        assert "the tax was deposited" in note
    assert row["journal_entry_id"] == link, "the link itself is not cleared by reading it"


def test_an_untied_challan_gets_no_link(world):
    row, = rows_for(world, None)
    assert "ledger_link" not in row


def test_a_failed_read_of_the_ledger_marks_every_tied_challan_unknown_and_never_live(world, monkeypatch):
    seen = []
    import core.observability as obs
    monkeypatch.setattr(svc, "entry_states", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **k: seen.append(k.get("operation")))
    a, b = rows_for(world, LIVE, REVERSED)
    for row in (a, b):
        assert row["ledger_link"]["state"] == "unknown" and "not checked just now" in row["ledger_link"]["label"]
        assert "could not be read just now" in row["ledger_link"]["note"]
    assert seen == ["tds_challan_ledger_service.annotate_links"]


def test_no_tied_challan_means_no_read_of_the_ledger(world, monkeypatch):
    monkeypatch.setattr(svc, "entry_states", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read the ledger for nothing")))
    rows_for(world, None, None)


# ── the surfaces ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_challan_list_carries_the_link_on_each_tied_row_over_the_whole_window(world):
    _challan(world, _id(201), LIVE, no="L"); _challan(world, _id(202), REVERSED, no="R"); _challan(world, _id(203), None, no="N")
    out = lists.challans(world, FIRM, A, from_date=None, to_date=None, limit=50, offset=0)
    by_no = {c["challan_no"]: c for c in out["challans"]}
    assert by_no["L"]["ledger_link"]["state"] == "live" and by_no["R"]["ledger_link"]["state"] == "reversed"
    assert "ledger_link" not in by_no["N"]


def test_the_candidates_answer_carries_the_link_for_the_dialog(world):
    ch = _challan(world, _id(301), REVERSED)
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=ch)
    assert out["journal_entry_id"] == REVERSED and out["ledger_link"]["state"] == "reversed"
    untied = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=_challan(world, _id(302), None))
    assert untied["ledger_link"] is None


def test_reading_the_link_posts_nothing_and_changes_no_challan(world):
    ch = _challan(world, _id(401), DELETED)
    before_entries, before_lines = world.rows("journal_entries"), world.rows("journal_lines")
    lists.challans(world, FIRM, A, from_date=None, to_date=None, limit=50, offset=0)
    svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=ch)
    assert world.rows("journal_entries") == before_entries and world.rows("journal_lines") == before_lines
    assert next(r for r in world.rows("tds_challans") if r["id"] == ch["id"])["journal_entry_id"] == DELETED


def test_a_stale_link_can_be_taken_back_and_the_challan_tied_again(world):
    ch = _challan(world, _id(501), REVERSED)
    done = svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=ch, actor=USER)
    assert done["was"] == REVERSED
    fresh = next(r for r in world.rows("tds_challans") if r["id"] == ch["id"])
    assert fresh["journal_entry_id"] is None
    rows = [fresh]
    svc.annotate_links(world, firm_id=FIRM, client_id=A, rows=rows)
    assert "ledger_link" not in rows[0]


# ── an entry that no longer records a payment is never the payment ─────────────────────────────────────────────────────

ACC_TDS, ACC_BANK = "acc-tds", "acc-bank"
DRAFT, REVERSAL, GOOD, OLD = (_id(i) for i in (11, 12, 13, 14))


def _debiting(db, je, client=A, *, date="2026-07-07", **flags):
    """An entry that debits TDS Payable by the challan's amount, with whatever flags the case needs (the row's own columns)."""
    db.seed("journal_entries", {"id": je, "firm_id": FIRM, "client_id": client, "entry_date": date, "reference_no": f"R-{je[-2:]}",
                                "narration": "TDS paid", "is_posted": True, "is_reversed": False, "reversal_of": None,
                                "deleted_at": None, **flags})
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": ACC_TDS, "debit_paise": 100_000_00, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": ACC_BANK, "debit_paise": 0, "credit_paise": 100_000_00})


@pytest.fixture
def ledger(world):
    world.seed("chart_of_accounts", {"id": ACC_TDS, "firm_id": FIRM, "client_id": A, "account_name": "TDS Payable", "is_active": True})
    world.seed("chart_of_accounts", {"id": ACC_BANK, "firm_id": FIRM, "client_id": A, "account_name": "Bank", "is_active": True})
    return world


def _offered(db, ch):
    return [c["journal_entry_id"] for c in svc.payment_candidates(db, firm_id=FIRM, client_id=A, challan=ch)["candidates"]]


def test_a_reversed_original_a_draft_a_reversal_and_a_deleted_entry_are_not_offered_as_the_payment(ledger):
    _debiting(ledger, REVERSED, is_reversed=True)
    _debiting(ledger, DRAFT, is_posted=False)
    _debiting(ledger, REVERSAL, reversal_of=REVERSED)
    _debiting(ledger, DELETED, deleted_at="2026-07-08T00:00:00+00:00")
    _debiting(ledger, GOOD)
    ch = _challan(ledger, _id(601), None)
    assert _offered(ledger, ch) == [GOOD]


def test_the_recovery_after_a_reversal_is_offered_the_replacement_and_not_the_entry_that_was_undone(ledger):
    """The path the stale-link note sends a CA down: take the link back, then tie the entry that now records the payment."""
    _debiting(ledger, OLD, is_reversed=True)
    _debiting(ledger, REVERSAL, reversal_of=OLD)
    _debiting(ledger, GOOD)
    ch = _challan(ledger, _id(602), OLD)
    assert svc.payment_candidates(ledger, firm_id=FIRM, client_id=A, challan=ch)["ledger_link"]["state"] == "reversed"
    svc.unlink_payment(ledger, firm_id=FIRM, client_id=A, challan=ch, actor=USER)
    fresh = next(r for r in ledger.rows("tds_challans") if r["id"] == ch["id"])
    assert _offered(ledger, fresh) == [GOOD]
    svc.link_payment(ledger, firm_id=FIRM, client_id=A, challan=fresh, journal_entry_id=GOOD, actor=USER)
    tied = next(r for r in ledger.rows("tds_challans") if r["id"] == ch["id"])
    assert tied["journal_entry_id"] == GOOD


@pytest.mark.parametrize("je,flags,words", [
    (REVERSED, {"is_reversed": True}, "was reversed"),
    (DRAFT, {"is_posted": False}, "still a draft"),
    (REVERSAL, {"reversal_of": OLD}, "undid another entry"),
    (DELETED, {"deleted_at": "2026-07-08T00:00:00+00:00"}, "was deleted"),
])
def test_naming_an_entry_that_records_no_payment_is_refused_in_words_and_changes_nothing(ledger, je, flags, words):
    _debiting(ledger, je, **flags)
    ch = _challan(ledger, _id(603), None)
    with pytest.raises(svc.LinkRefused) as e:
        svc.link_payment(ledger, firm_id=FIRM, client_id=A, challan=ch, journal_entry_id=je, actor=USER)
    assert words in e.value.sentence and e.value.status == 422
    assert next(r for r in ledger.rows("tds_challans") if r["id"] == ch["id"])["journal_entry_id"] is None


def test_a_tied_draft_or_reversal_reads_as_such_and_never_as_live(ledger):
    _debiting(ledger, DRAFT, is_posted=False)
    _debiting(ledger, REVERSAL, reversal_of=OLD)
    _debiting(ledger, GOOD)
    assert states(ledger, [DRAFT, REVERSAL, GOOD]) == {DRAFT: "draft", REVERSAL: "reversal", GOOD: "live"}
    a, b = rows_for(ledger, DRAFT, REVERSAL)
    assert a["ledger_link"]["label"] == "Tied to an entry that is still a draft" and "Post the entry" in a["ledger_link"]["note"]
    assert b["ledger_link"]["label"] == "Tied to an entry that is itself a reversal" and "Take the link back" in b["ledger_link"]["note"]


def test_the_one_rule_orders_deleted_over_reversed_over_reversal_over_draft_and_reads_an_absent_key_as_ordinary():
    from domain.payroll.remittance_match import entry_state as st
    assert st({"deleted_at": "x", "is_reversed": True, "is_posted": False}) == "deleted"
    assert st({"is_reversed": True, "reversal_of": "y", "is_posted": False}) == "reversed"
    assert st({"reversal_of": "y", "is_posted": False}) == "reversal"
    assert st({"is_posted": False}) == "draft"
    assert st({}) == "live" and st({"is_posted": True}) == "live" and st({"is_posted": None}) == "live"


def test_every_query_that_feeds_the_rule_selects_the_columns_it_reads():
    """An absent key reads as an ordinary entry, so a narrower select would switch the rule off without a sound."""
    import inspect
    from domain.payroll import remittance_match as rm
    from services import statutory_remittance_service as esi
    assert rm.ENTRY_STATE_COLUMNS == ("is_posted", "is_reversed", "reversal_of")
    # Either names the tuple or spells the same columns as a literal (the two reads in the remittance service do the second, so the
    # backend column check can read them: a string built from the tuple is invisible to it and counts against its budget).
    literal = '"' + "id, deleted_at, " + ", ".join(rm.ENTRY_STATE_COLUMNS) + '"'
    for fn in (esi.entries_clearing_account, esi.entry_states, esi.link_payment, svc._entry):
        source = inspect.getsource(fn)
        assert "ENTRY_STATE_COLUMNS" in source or literal in source, f"{fn.__name__} does not select the columns entry_state reads"
    # the TDS challan's reader is the remittance register's one, not a second copy of it
    assert "remittances.entry_states(" in inspect.getsource(svc.entry_states)
