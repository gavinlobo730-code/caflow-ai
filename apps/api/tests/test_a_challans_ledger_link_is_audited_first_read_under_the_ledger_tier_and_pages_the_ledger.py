"""POST-A-272, fixes from the independent review of migration 568: the challan's ledger link is recorded before it is made, one entry cannot
be won by two challans in a race, the ledger is read only by someone who may read it, and a busy client's month is read whole.

WHAT WAS WRONG (each is a finding of the review; the first mock-mode guards for them are here, the database half is in
`test_573_a_challans_ledger_link_is_unique_and_a_ledger_link_names_an_entry_of_its_own_client_pg.py`)
    AUDIT      the link and its removal were audited AFTER the write by `audit_service.log_event`, which swallows its failures: a link the
               ledger reads as "the tax was paid" could stand with no account of who made it. Both are written first now, as the AUTH id, and
               refused with a 503 ("Nothing changed") when the log cannot be written; a write that then loses a race says so in a second entry.
    RACE       "one entry cannot pay two challans" was a read followed by a write. The write that loses to the unique index (23505) is
               answered with the same sentence and status as the read, not a generic fault, and any OTHER failure is still a failure.
    TIER       the candidates route returned the reference, narration and amount of the client's ledger entries under the TDS read tier
               alone, so a member the Team grid had blocked from Accounting could read journal narrations through a TDS screen.
    PAGING     the candidate reader asked for every entry in a month and every line of those entries in two single requests: PostgREST cuts
               a response at 1,000 rows and says nothing, and an id list in the URL stops being a query at a few hundred ids.
    MUTANTS    five assertions the first tests did not make (an entry that CREDITS TDS Payable; which of own, shared and another client's
               account is read; an inactive account; the firm and the client on the two privileged updates).
"""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.tds_workspace as tw
import tests.e2e_harness as harness
from core.auth import get_current_user
from services import statutory_remittance_service as remit
from services import tds_challan_ledger_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
OTHER_FIRM = "22222222-2222-2222-2222-222222222222"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ACC_TDS, ACC_RENT, ACC_BANK = "acc-tds", "acc-rent", "acc-bank"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _id(n: int) -> str:
    return str(uuid.UUID(int=n))


JE_PAY, JE_ACCRUAL, JE_OTHER = _id(1), _id(2), _id(3)
CH_1, CH_2, CH_B, CH_FOREIGN = _id(11), _id(12), _id(13), _id(14)


def _entry(db, je, client, date="2026-07-07", firm=FIRM):
    db.seed("journal_entries", {"id": je, "firm_id": firm, "client_id": client, "entry_date": date, "reference_no": f"R-{je[-2:]}",
                                "narration": "TDS", "deleted_at": None})


def _lines(db, je, debit_account, credit_account, paise):
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": debit_account, "debit_paise": paise, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": credit_account, "debit_paise": 0, "credit_paise": paise})


def _challan(db, cid, client=A, firm=FIRM, link=None, no="CH"):
    return db.seed("tds_challans", {"id": cid, "firm_id": firm, "client_id": client, "section": "194C", "total_paise": 100_000_00,
                                    "payment_date": "2026-07-07", "challan_no": no, "journal_entry_id": link,
                                    "financial_year": "2026-27", "quarter": "Q2"})


def _rows(db, table):
    return list(db.rows(table))


def _link_of(db, cid):
    return next(r for r in db.rows("tds_challans") if r["id"] == cid)["journal_entry_id"]


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    for acc, name in ((ACC_TDS, "TDS Payable"), (ACC_RENT, "Rent"), (ACC_BANK, "Bank")):
        db.seed("chart_of_accounts", {"id": acc, "firm_id": FIRM, "client_id": A, "account_name": name, "is_active": True})
    _entry(db, JE_PAY, A); _lines(db, JE_PAY, ACC_TDS, ACC_BANK, 100_000_00)
    # An ACCRUAL: Dr Rent / Cr TDS Payable. It has a line on the TDS Payable account, and it is a CREDIT, so it is not a payment of the tax.
    _entry(db, JE_ACCRUAL, A); _lines(db, JE_ACCRUAL, ACC_RENT, ACC_TDS, 100_000_00)
    _entry(db, JE_OTHER, A, date="2026-07-08"); _lines(db, JE_OTHER, ACC_TDS, ACC_BANK, 7_00)
    _challan(db, CH_1, no="CH-1")
    _challan(db, CH_2, no="CH-2")
    _challan(db, CH_B, client=B, no="CH-B")
    _challan(db, CH_FOREIGN, firm=OTHER_FIRM, no="CH-F")
    wire_e2e(monkeypatch, db, [tw])
    monkeypatch.setattr(tw, "can_access_client", lambda user, client_id: True)
    return db


def _row(db, cid):
    return next(r for r in db.rows("tds_challans") if r["id"] == cid)


# ───────────────────────────── the audit entry comes first ─────────────────────────────

def test_the_audit_entry_is_written_before_the_link_is_made_and_names_the_person(world, monkeypatch):
    order = []
    real_audit, real_priv = svc._write_audit_or_refuse, svc.privileged_for
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **k: (order.append("audit"), real_audit(**k))[1])
    monkeypatch.setattr(svc, "privileged_for", lambda db: (order.append("update"), real_priv(db))[1])
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    assert order == ["audit", "update"]
    entry, = _rows(world, "audit_log")
    assert (entry["action"], entry["actor_id"], entry["actor_email"], entry["entity_type"], entry["entity_id"]) == (
        "link_payment", "au1", "p@example.test", "tds_challan", CH_1), "audited as the AUTH id, the audit log's flavour of actor"
    assert entry["old_data"] == {"journal_entry_id": None} and entry["new_data"] == {"journal_entry_id": JE_PAY}
    assert entry["metadata"] == {"client_id": A, "challan_no": "CH-1"}


def test_the_audit_entry_for_taking_a_link_back_is_written_before_it_is_taken(world, monkeypatch):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    order = []
    real_audit, real_priv = svc._write_audit_or_refuse, svc.privileged_for
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **k: (order.append("audit"), real_audit(**k))[1])
    monkeypatch.setattr(svc, "privileged_for", lambda db: (order.append("update"), real_priv(db))[1])
    svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), actor=USER)
    assert order == ["audit", "update"]
    last = _rows(world, "audit_log")[-1]
    assert (last["action"], last["old_data"], last["new_data"]) == ("unlink_payment", {"journal_entry_id": JE_PAY}, {"journal_entry_id": None})


class _BrokenLog:
    def table(self, _name):
        raise RuntimeError("audit_log is unavailable")


def test_when_the_audit_entry_cannot_be_written_nothing_is_linked_and_the_answer_says_why(world, monkeypatch):
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: _BrokenLog())
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    assert refused.value.status == 503 and "audit log" in refused.value.sentence and "Nothing changed" in refused.value.sentence
    assert _link_of(world, CH_1) is None


def test_when_the_audit_entry_cannot_be_written_the_link_is_not_taken_back(world, monkeypatch):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: _BrokenLog())
    with pytest.raises(svc.LinkRefused) as refused:
        svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), actor=USER)
    assert refused.value.status == 503 and "Nothing changed" in refused.value.sentence
    assert _link_of(world, CH_1) == JE_PAY


def test_a_refusal_before_the_write_leaves_no_audit_entry(world):
    """The log records what was asked of a request that got as far as the write; a request refused for what it is leaves nothing."""
    with pytest.raises(svc.LinkRefused):
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_ACCRUAL, actor=USER)
    with pytest.raises(svc.LinkRefused):
        svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), actor=USER)         # nothing to take back
    assert _rows(world, "audit_log") == []


def test_a_link_that_loses_a_race_says_in_the_log_that_it_was_not_applied(world):
    stale = dict(_row(world, CH_1))
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=stale, journal_entry_id=JE_OTHER, actor=USER)
    assert refused.value.status == 409
    assert [e["action"] for e in _rows(world, "audit_log")] == ["link_payment", "link_payment", "link_payment_not_applied"]
    assert _link_of(world, CH_1) == JE_PAY


def test_a_stale_unlink_says_in_the_log_that_it_was_not_applied(world):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    stale = dict(_row(world, CH_1))
    svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), actor=USER)
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_OTHER, actor=USER)
    with pytest.raises(svc.LinkRefused):
        svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=stale, actor=USER)
    assert [e["action"] for e in _rows(world, "audit_log")][-2:] == ["unlink_payment", "unlink_payment_not_applied"]
    assert _link_of(world, CH_1) == JE_OTHER


# ───────────────────────────── the database's unique index wins a race ─────────────────────────────

class _UpdateRaises:
    """The privileged client, whose update is refused by the database with `exc`."""

    def __init__(self, exc):
        self._exc = exc

    def table(self, _name):
        return self

    def update(self, _payload):
        return self

    def eq(self, *_a):
        return self

    def is_(self, *_a):
        return self

    def execute(self):
        raise self._exc


class _UniqueViolation(Exception):
    code = "23505"


def test_a_write_that_loses_to_the_unique_index_is_the_same_409_as_the_read(world, monkeypatch):
    monkeypatch.setattr(svc, "privileged_for", lambda db: _UpdateRaises(_UniqueViolation(
        {"code": "23505", "message": 'duplicate key value violates unique constraint "uq_tds_challans_journal_entry"'})))
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    assert refused.value.status == 409 and "another challan just now" in refused.value.sentence
    assert [e["action"] for e in _rows(world, "audit_log")] == ["link_payment", "link_payment_not_applied"]


def test_any_other_failure_of_the_write_is_still_a_failure(world, monkeypatch):
    monkeypatch.setattr(svc, "privileged_for", lambda db: _UpdateRaises(RuntimeError("connection reset")))
    with pytest.raises(RuntimeError):
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)


@pytest.mark.parametrize("text, expected", [
    ("23505", True), ("duplicate key value violates unique constraint", True), ("permission denied for table x 42501", False),
    ("connection reset", False),
])
def test_a_unique_violation_is_told_from_any_other_failure(text, expected):
    assert svc._is_unique_violation(RuntimeError(text)) is expected


# ───────────────────────────── the five assertions the first tests did not make ─────────────────────────────

def test_an_entry_that_credits_tds_payable_is_not_the_payment(world):
    """An accrual has a line on the account and it is a CREDIT: a check that accepts a debit of zero ties the challan to the accrual."""
    with pytest.raises(svc.LinkRefused) as refused:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_ACCRUAL, actor=USER)
    assert 'does not debit "TDS Payable"' in refused.value.sentence and _link_of(world, CH_1) is None
    offered = [c["journal_entry_id"] for c in svc.payment_candidates(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1))["candidates"]]
    assert JE_ACCRUAL not in offered and JE_PAY in offered


def _chart(db, rows):
    db._tables["chart_of_accounts"] = []
    for i, (client, active) in enumerate(rows):
        db.seed("chart_of_accounts", {"id": f"acct-{i}", "firm_id": FIRM, "client_id": client, "account_name": "TDS Payable", "is_active": active})
    db.seed("chart_of_accounts", {"id": "acct-other-name", "firm_id": FIRM, "client_id": A, "account_name": "TDS Payable - Salary", "is_active": True})


@pytest.mark.parametrize("rows, expected", [
    ([(B, True)], None),                                          # only ANOTHER client's account: not this client's to clear
    ([(None, True)], "acct-0"),                                   # a firm-level account is allowed on any of the firm's entries
    ([(None, True), (A, True)], "acct-1"),                        # this client's own account wins over the shared one
    ([(B, True), (None, True)], "acct-1"),                        # another client's account is neither
    ([(A, False)], None),                                         # an account switched off is not one to clear
    ([(A, False), (None, True)], "acct-1"),
    ([(A, False), (B, True)], None),
])
def test_which_account_a_challan_clears_is_this_clients_own_then_the_shared_one_and_only_an_active_one(world, rows, expected):
    _chart(world, rows)
    assert svc.liability_account_id(world, firm_id=FIRM, client_id=A, section="194C") == expected


def test_the_firm_and_the_client_of_the_challan_are_named_in_the_link_update(world):
    """The challan is passed in by the caller: the update must itself name the firm and the client it was read for."""
    with pytest.raises(svc.LinkRefused) as other_client:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_B), journal_entry_id=JE_PAY, actor=USER)
    assert other_client.value.status == 409 and _link_of(world, CH_B) is None
    with pytest.raises(svc.LinkRefused) as other_firm:
        svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_FOREIGN), journal_entry_id=JE_PAY, actor=USER)
    assert other_firm.value.status == 409 and _link_of(world, CH_FOREIGN) is None


def test_the_firm_and_the_client_of_the_challan_are_named_in_the_unlink_update(world):
    for cid, client, firm in ((CH_B, B, FIRM), (CH_FOREIGN, A, OTHER_FIRM)):
        _row(world, cid)["journal_entry_id"] = JE_PAY
        with pytest.raises(svc.LinkRefused) as refused:
            svc.unlink_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, cid), actor=USER)
        assert refused.value.status == 409 and _link_of(world, cid) == JE_PAY, (client, firm)


# ───────────────────────────── the route reads the ledger, so it asks for the ledger tier ─────────────────────────────

def _names(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}


def _route(path, method):
    return next(r for r in tw.router.routes if getattr(r, "path", "") == f"/api/tds-workspace{path}" and method in r.methods)


def test_the_candidates_and_the_link_routes_ask_the_accounting_read_tier_and_the_unlink_does_not():
    cand = _names(_route("/challans/{challan_id}/ledger-candidates", "GET"))
    link = _names(_route("/challans/{challan_id}/link-payment", "POST"))
    unlink = _names(_route("/challans/{challan_id}/unlink-payment", "POST"))
    assert {"rbac_tds_read", "rbac_accounting_read"} <= cand
    assert {"rbac_tds_compute", "rbac_accounting_read"} <= link
    assert "rbac_tds_compute" in unlink and "rbac_accounting_read" not in unlink, "taking a link back reads no ledger"


@pytest.fixture
def http(world, monkeypatch):
    state = {"user": dict(USER)}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app, raise_server_exceptions=False)


def _deny_accounting(monkeypatch):
    import core.permissions as perms
    real = perms.can_user
    monkeypatch.setattr(perms, "can_user", lambda user, resource, action: False if resource == "accounting" else real(user, resource, action))


def test_a_member_blocked_from_accounting_cannot_read_the_ledger_through_the_tds_screen(http, world, monkeypatch):
    _deny_accounting(monkeypatch)
    cand = http.get(f"/api/tds-workspace/challans/{CH_1}/ledger-candidates")
    link = http.post(f"/api/tds-workspace/challans/{CH_1}/link-payment", json={"journal_entry_id": JE_PAY})
    assert cand.status_code == 403 and link.status_code == 403
    assert "narration" not in cand.text and _link_of(world, CH_1) is None and _rows(world, "audit_log") == []


def test_a_member_who_may_read_accounting_reads_the_candidates_as_before(http):
    r = http.get(f"/api/tds-workspace/challans/{CH_1}/ledger-candidates")
    assert r.status_code == 200 and [c["journal_entry_id"] for c in r.json()["data"]["candidates"]][:1] == [JE_PAY]


def test_a_member_blocked_from_accounting_can_still_take_a_link_back(http, world, monkeypatch):
    svc.link_payment(world, firm_id=FIRM, client_id=A, challan=_row(world, CH_1), journal_entry_id=JE_PAY, actor=USER)
    _deny_accounting(monkeypatch)
    r = http.post(f"/api/tds-workspace/challans/{CH_1}/unlink-payment")
    assert r.status_code == 200 and _link_of(world, CH_1) is None


def test_the_routes_link_and_unlink_audit_once_each_as_the_person(http, world):
    http.post(f"/api/tds-workspace/challans/{CH_1}/link-payment", json={"journal_entry_id": JE_PAY})
    http.post(f"/api/tds-workspace/challans/{CH_1}/unlink-payment")
    assert [(e["action"], e["actor_id"], e["entity_id"]) for e in _rows(world, "audit_log")] == [
        ("link_payment", "au1", CH_1), ("unlink_payment", "au1", CH_1)], "once each: the router no longer writes a second, swallowing entry"


def test_a_failed_audit_reaches_the_caller_as_a_503_with_the_services_words(http, world, monkeypatch):
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: _BrokenLog())
    r = http.post(f"/api/tds-workspace/challans/{CH_1}/link-payment", json={"journal_entry_id": JE_PAY})
    assert r.status_code == 503 and "Nothing changed" in r.json()["detail"] and _link_of(world, CH_1) is None


# ───────────────────────────── a busy client's month is read whole ─────────────────────────────

@pytest.fixture
def capped(monkeypatch):
    """PostgREST as hosted: a response is cut at 1,000 rows without a word, and an id list that rides in the URL has a limit (the gateway's 400
    comes back as an exception, here at 150 ids, the size `core.db_paging.IN_CHUNK` keeps a request under)."""
    real = harness._Query.execute

    def execute(self):
        if self._op == "select":
            for kind, _col, val in self._filters:
                if kind == "in" and len(val) > 150:
                    raise RuntimeError(f"the id list made the URL too long ({len(val)} ids)")
        out = real(self)
        if self._op == "select" and isinstance(out.data, list) and len(out.data) > 1000:
            out.data = out.data[:1000]
        return out

    monkeypatch.setattr(harness._Query, "execute", execute)


def test_the_entry_that_paid_the_challan_is_found_among_more_than_a_thousand_in_its_month(capped):
    db = FakeDB()
    db.seed("chart_of_accounts", {"id": ACC_TDS, "firm_id": FIRM, "client_id": A, "account_name": "TDS Payable", "is_active": True})
    n = 1240
    for i in range(1, n + 1):                                     # a busy client: entries that touch other accounts, all in the window
        _entry(db, _id(1000 + i), A); _lines(db, _id(1000 + i), ACC_RENT, ACC_BANK, 500_00)
    paid = _id(9_999_999)                                         # sorts after every other entry and is inserted last
    _entry(db, paid, A); _lines(db, paid, ACC_TDS, ACC_BANK, 100_000_00)
    found = remit.entries_clearing_account(db, firm_id=FIRM, client_id=A, account_id=ACC_TDS, amount_paise=100_000_00, paid_on="2026-07-07")
    assert [c["journal_entry_id"] for c in found] == [paid]


def test_a_thousand_and_more_debits_of_the_account_itself_are_all_considered(capped):
    """Not only the entries are paged: the lines of the shortlisted entries are too."""
    db = FakeDB()
    db.seed("chart_of_accounts", {"id": ACC_TDS, "firm_id": FIRM, "client_id": A, "account_name": "TDS Payable", "is_active": True})
    n = 1100
    for i in range(1, n + 1):
        _entry(db, _id(1000 + i), A); _lines(db, _id(1000 + i), ACC_TDS, ACC_BANK, 1_00)
    exact = _id(9_999_999)
    _entry(db, exact, A); _lines(db, exact, ACC_TDS, ACC_BANK, 100_000_00)
    found = remit.entries_clearing_account(db, firm_id=FIRM, client_id=A, account_id=ACC_TDS, amount_paise=100_000_00, paid_on="2026-07-07")
    assert found and found[0]["journal_entry_id"] == exact, "the entry for the exact amount ranks first among 1,101 candidates"
