"""POST-A-272 (first slice) — a recorded TDS challan can be tied to the ledger entry that paid it.

WHAT WAS WRONG
    `tds_challans` held the challan's own facts and nothing that says whether the ledger knows the tax was paid, so after a deposit was
    recorded TDS Payable kept its whole credit until somebody passed a bank line by hand, nothing offered the entry whose amount equals a
    recorded challan, and nothing said a challan had no entry behind it. ESI and professional tax already had the link (migration 365).

WHAT THIS PINS
    CANDIDATES   the entries that DEBIT the account the challan's section belongs to, inside a week of its payment date, best first, each
                 with a reason sentence: a salary challan reads "TDS Payable - Salary" and every other section "TDS Payable" (two distinct
                 accounts; one is a substring of the other); a client with no such account, and a challan with no payment date, get a
                 sentence and no list.
    LINK         refused in words unless the challan has no link, the entry is a live entry of THIS client, it debits the right account, and
                 no other challan holds it; the update names "no link yet" as its condition so a second click ties nothing; and never
                 a posting: no journal entry or line is written.
    UNLINK       takes the link back, refuses when there is none, and a stale read changes nothing.
    ROUTES       an unreachable or missing challan is the same 404; a bad id is a 422 before anything is read; the link and its removal
                 are audited as the person.
"""
import uuid

import pytest
from fastapi import HTTPException

import routers.tds_workspace as tw
from services import tds_challan_ledger_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ACC_OTHER, ACC_SAL, ACC_RENT, ACC_BANK = "acc-tds", "acc-tds-sal", "acc-rent", "acc-bank"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _id(n: int) -> str:
    return str(uuid.UUID(int=n))


JE_TDS, JE_SAL, JE_RENT, JE_B, JE_DEL, JE_FAR = (_id(i) for i in (1, 2, 3, 4, 5, 6))
CH_194C, CH_192, CH_B, CH_NODATE = (_id(i) for i in (11, 12, 13, 14))


def _entry(db, je, client, date, deleted=None):
    db.seed("journal_entries", {"id": je, "firm_id": FIRM, "client_id": client, "entry_date": date, "reference_no": f"R-{je[-2:]}",
                                "narration": "TDS paid", "deleted_at": deleted})


def _lines(db, je, debit_account, paise):
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": debit_account, "debit_paise": paise, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": ACC_BANK, "debit_paise": 0, "credit_paise": paise})


def _challan(db, cid, client, section, total, date, link=None, no="CH-1"):
    db.seed("tds_challans", {"id": cid, "firm_id": FIRM, "client_id": client, "section": section, "total_paise": total,
                             "payment_date": date, "challan_no": no, "journal_entry_id": link, "financial_year": "2026-27", "quarter": "Q2"})


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    for acc, name in ((ACC_OTHER, "TDS Payable"), (ACC_SAL, "TDS Payable - Salary"), (ACC_RENT, "Rent"), (ACC_BANK, "Bank")):
        db.seed("chart_of_accounts", {"id": acc, "firm_id": FIRM, "client_id": A, "account_name": name, "is_active": True})
    _entry(db, JE_TDS, A, "2026-07-07"); _lines(db, JE_TDS, ACC_OTHER, 100_000_00)
    _entry(db, JE_SAL, A, "2026-07-10"); _lines(db, JE_SAL, ACC_SAL, 50_000_00)
    _entry(db, JE_RENT, A, "2026-07-07"); _lines(db, JE_RENT, ACC_RENT, 100_000_00)
    _entry(db, JE_B, B, "2026-07-07"); _lines(db, JE_B, ACC_OTHER, 100_000_00)
    _entry(db, JE_DEL, A, "2026-07-07", deleted="2026-07-08T00:00:00+00:00"); _lines(db, JE_DEL, ACC_OTHER, 100_000_00)
    _entry(db, JE_FAR, A, "2026-09-30"); _lines(db, JE_FAR, ACC_OTHER, 100_000_00)
    _challan(db, CH_194C, A, "194C", 100_000_00, "2026-07-07", no="CH-194C")
    _challan(db, CH_192, A, "192", 50_000_00, "2026-07-10", no="CH-192")
    _challan(db, CH_B, B, "194C", 100_000_00, "2026-07-07", no="CH-B")
    wire_e2e(monkeypatch, db, [tw])
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: True)
    return db


def get(db, cid):
    return next(r for r in db.rows("tds_challans") if r["id"] == cid)


# ───────────────────────────── candidates ─────────────────────────────

def test_a_non_salary_challan_is_offered_the_entry_that_debited_tds_payable_that_week(world):
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C))
    assert out["account_name"] == "TDS Payable" and out["gap"] is None
    ids = [c["journal_entry_id"] for c in out["candidates"]]
    assert ids == [JE_TDS], "only the entry that debits TDS Payable inside the week: not rent, not another client's, not a deleted one, not September's"
    top = out["candidates"][0]
    assert top["grade"] == "exact" and "₹1,00,000.00 left the bank" in top["reason"]


def test_a_salary_challan_reads_the_salary_account_and_not_the_other_one(world):
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=get(world, CH_192))
    assert out["account_name"] == "TDS Payable - Salary"
    assert [c["journal_entry_id"] for c in out["candidates"]] == [JE_SAL]
    assert svc.account_name_for("192") == "TDS Payable - Salary"
    for section in ("194C", "194J", "194I", "206C", None, ""):
        assert svc.account_name_for(section) == "TDS Payable", section


def test_a_client_with_no_such_account_gets_a_sentence_and_no_list(world):
    world._tables["chart_of_accounts"] = [r for r in world.rows("chart_of_accounts") if r["account_name"] != "TDS Payable"]
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C))
    assert out["candidates"] == [] and 'no "TDS Payable" account' in out["gap"]


def test_a_challan_with_no_payment_date_has_no_window_to_look_in(world):
    _challan(world, CH_NODATE, A, "194C", 1, None)
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=get(world, CH_NODATE))
    assert out["candidates"] == [] and "no payment date" in out["gap"]


def test_an_already_tied_challan_says_which_entry(world):
    get(world, CH_194C)["journal_entry_id"] = JE_TDS
    out = svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C))
    assert out["journal_entry_id"] == JE_TDS


# ───────────────────────────── link ─────────────────────────────

def test_linking_ties_the_challan_and_posts_nothing(world):
    before = (len(world.rows("journal_entries")), len(world.rows("journal_lines")))
    done = svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_TDS, actor=USER)
    assert done["journal_entry_id"] == JE_TDS and done["entry_date"] == "2026-07-07"
    assert get(world, CH_194C)["journal_entry_id"] == JE_TDS
    assert (len(world.rows("journal_entries")), len(world.rows("journal_lines"))) == before, "a link is never a posting"


@pytest.mark.parametrize("what, entry, challan, status, words", [
    ("another client's entry", JE_B, CH_194C, 422, "not an entry of this client"),
    ("a deleted entry", JE_DEL, CH_194C, 422, "was deleted, so it cannot be the payment"),
    ("an entry that does not exist", _id(99), CH_194C, 422, "not an entry of this client"),
    ("an entry that debits something else", JE_RENT, CH_194C, 422, 'does not debit "TDS Payable"'),
    ("the salary entry for a non-salary challan", JE_SAL, CH_194C, 422, 'does not debit "TDS Payable"'),
    ("the non-salary entry for a salary challan", JE_TDS, CH_192, 422, 'does not debit "TDS Payable - Salary"'),
])
def test_a_link_that_cannot_be_the_payment_is_refused_in_words_and_changes_nothing(world, what, entry, challan, status, words):
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, challan), journal_entry_id=entry, actor=USER)
    assert refused.value.status == status and words in refused.value.sentence, what
    assert get(world, challan)["journal_entry_id"] is None


def test_a_challan_that_is_already_tied_is_refused_with_a_409(world):
    get(world, CH_194C)["journal_entry_id"] = JE_TDS
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_FAR, actor=USER)
    assert refused.value.status == 409 and "already tied" in refused.value.sentence
    assert get(world, CH_194C)["journal_entry_id"] == JE_TDS


def test_one_entry_cannot_be_the_payment_of_two_challans(world):
    _challan(world, _id(15), A, "194J", 100_000_00, "2026-07-07", no="CH-194J")
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_TDS, actor=USER)
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, _id(15)), journal_entry_id=JE_TDS, actor=USER)
    assert refused.value.status == 409 and "CH-194C" in refused.value.sentence
    assert get(world, _id(15))["journal_entry_id"] is None


def test_the_second_of_two_simultaneous_links_ties_nothing(world):
    stale = dict(get(world, CH_194C))                              # the second request read the challan before the first tied it
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_TDS, actor=USER)
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=stale, journal_entry_id=JE_FAR, actor=USER)
    assert refused.value.status == 409
    assert get(world, CH_194C)["journal_entry_id"] == JE_TDS, "the first link stands"


def test_a_challan_of_another_client_is_not_tied_through_this_client(world):
    with pytest.raises(svc.LinkRefused):
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_B), journal_entry_id=JE_B, actor=USER)
    assert get(world, CH_B)["journal_entry_id"] is None


# ───────────────────────────── unlink ─────────────────────────────

def test_unlinking_takes_the_link_back_and_leaves_the_entry(world):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_TDS, actor=USER)
    done = svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), actor=USER)
    assert done["was"] == JE_TDS and get(world, CH_194C)["journal_entry_id"] is None
    assert any(e["id"] == JE_TDS for e in world.rows("journal_entries")), "the entry is untouched"


def test_unlinking_a_challan_with_no_link_is_refused(world):
    with pytest.raises(svc.LinkRefused) as refused:
        svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), actor=USER)
    assert refused.value.status == 409


def test_a_stale_unlink_changes_nothing(world):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_TDS, actor=USER)
    stale = dict(get(world, CH_194C))
    svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), actor=USER)
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=get(world, CH_194C), journal_entry_id=JE_FAR, actor=USER)
    with pytest.raises(svc.LinkRefused) as refused:
        svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=stale, actor=USER)       # it still believes JE_TDS is the link
    assert refused.value.status == 409
    assert get(world, CH_194C)["journal_entry_id"] == JE_FAR


# ───────────────────────────── routes ─────────────────────────────

def test_the_routes_link_unlink_and_audit_as_the_person(world):
    got = tw.challan_ledger_candidates(uuid.UUID(CH_194C), USER, USER)
    assert got["success"] and [c["journal_entry_id"] for c in got["data"]["candidates"]] == [JE_TDS]
    linked = tw.link_challan_payment(uuid.UUID(CH_194C), tw.LinkChallanPaymentRequest(journal_entry_id=uuid.UUID(JE_TDS)), USER, USER)
    assert linked["data"]["journal_entry_id"] == JE_TDS and get(world, CH_194C)["journal_entry_id"] == JE_TDS
    tw.unlink_challan_payment(uuid.UUID(CH_194C), USER)
    assert get(world, CH_194C)["journal_entry_id"] is None
    events = world.rows("audit_log")
    assert [(e["action"], e["actor_id"], e["entity_id"]) for e in events] == [
        ("link_payment", "au1", CH_194C), ("unlink_payment", "au1", CH_194C)], "audited as the AUTH id, the audit log's flavour of actor"
    assert events[0]["old_data"] == {"journal_entry_id": None} and events[0]["new_data"] == {"journal_entry_id": JE_TDS}


def test_a_missing_challan_and_one_the_caller_may_not_see_say_the_same_words(world, monkeypatch):
    missing = HTTPException
    with pytest.raises(missing) as a:
        tw.challan_ledger_candidates(uuid.UUID(_id(404)), USER, USER)
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: client_id != B)
    with pytest.raises(missing) as b:
        tw.challan_ledger_candidates(uuid.UUID(CH_B), USER, USER)
    assert (a.value.status_code, a.value.detail) == (b.value.status_code, b.value.detail) == (404, "Not found")


def test_a_refusal_reaches_the_caller_as_the_services_status_and_sentence(world):
    with pytest.raises(HTTPException) as refused:
        tw.link_challan_payment(uuid.UUID(CH_194C), tw.LinkChallanPaymentRequest(journal_entry_id=uuid.UUID(JE_RENT)), USER, USER)
    assert refused.value.status_code == 422 and 'does not debit "TDS Payable"' in refused.value.detail


def test_a_malformed_id_is_a_422_before_anything_is_read():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        tw.LinkChallanPaymentRequest(journal_entry_id="not-a-uuid")


def test_mock_mode_keeps_no_ledger_and_says_so(monkeypatch):
    monkeypatch.setattr(tw, "_USE_MOCK", True)
    with pytest.raises(HTTPException) as refused:
        tw.link_challan_payment(uuid.UUID(CH_194C), tw.LinkChallanPaymentRequest(journal_entry_id=uuid.UUID(JE_TDS)), USER, USER)
    assert refused.value.status_code == 409 and "Mock mode keeps no ledger" in refused.value.detail
