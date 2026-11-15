"""A bank line records WHO matched or paired it by the member's internal id, and every audit and timeline row names their sign-in id
(POST-A-377).

WHAT WAS WRONG
    `bank_transactions.matched_by` and `transfer_paired_by` have no key, and they were written with BOTH ids: the match and pair routes
    passed the caller's sign-in id, while passing a drafted line (the bank pass path, and the trusted-rule sweep) passed the internal one.
    The same pass path handed that internal id on to three functions that also write `audit_log.actor_id`, which takes the sign-in id
    everywhere else, so "everything this person did" missed their passed lines; and the client timeline's actor was the sign-in id in 68
    writers and the internal id in nine.

WHAT IT DOES NOW
    The two bank columns hold `users.id`, beside `posted_by` on the same row, which has always held it. The match and pair services take
    both ids and use each for its own column; the routes and the pass path hand them both. The audit rows and the timeline rows name the
    sign-in id. `tests/test_a_bare_person_column_takes_the_id_it_holds.py` is the rule over the whole tree; these tests drive the code.
"""
from __future__ import annotations

import pytest

import services.bank_matching_service as bms
from services.bank_matching_service import bank_matching_service
from services.bank_transfer_service import bank_transfer_service
from services.bank_entry_service import bank_entry_service
from tests.test_bank_matching import CLIENT, FIRM, FakeDB, _seed_entity, _seed_txn

INTERNAL, SIGN_IN = "users-id-1", "auth-id-1"


@pytest.fixture
def heard(monkeypatch):
    """What the audit log and the timeline were told."""
    said = {"audit": [], "timeline": []}
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: said["audit"].append(k.get("actor_id")))
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: said["timeline"].append(k.get("actor_id")))
    return said


def test_a_match_records_the_internal_id_and_audits_the_sign_in_id(heard):
    db = FakeDB(); _seed_txn(db); _seed_entity(db, "client_sales_invoices", "inv-1")
    bank_matching_service.match(db, FIRM, "t1", "sales_invoice", "inv-1", actor_id=INTERNAL, actor_auth_id=SIGN_IN)
    assert db.store["bank_transactions"][0]["matched_by"] == INTERNAL
    assert heard["audit"] == [SIGN_IN] and heard["timeline"] == [SIGN_IN]


class _Rpc:
    def __init__(self, calls, name, params):
        self.calls, self.name, self.params = calls, name, params

    def execute(self):
        self.calls.append((self.name, self.params))

        class _R:
            data = []
        return _R()


class _Service:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        return _Rpc(self.calls, name, params)


def test_a_pair_records_the_internal_id_and_audits_the_sign_in_id(monkeypatch):
    service, logged = _Service(), []
    monkeypatch.setattr(bank_transfer_service, "get", lambda db, firm, txn: {"id": txn})
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: logged.append(k.get("actor_id")))
    bank_transfer_service.pair(service, FIRM, "out", "in", actor_id=INTERNAL, actor_auth_id=SIGN_IN, rpc_db=service)
    (name, params), = service.calls
    assert name == "pair_bank_transfer" and params["p_actor_id"] == INTERNAL     # the function writes it into transfer_paired_by
    assert logged == [SIGN_IN, SIGN_IN]                                           # one audit row for each side of the pair


def test_an_unpair_audits_the_sign_in_id(monkeypatch):
    service, logged = _Service(), []
    monkeypatch.setattr(bank_transfer_service, "get", lambda db, firm, txn: {"id": txn})
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: logged.append(k.get("actor_id")))
    bank_transfer_service.unpair(service, FIRM, "out", actor_auth_id=SIGN_IN, rpc_db=service)
    assert logged == [SIGN_IN]


@pytest.mark.parametrize("source, called", [("document", "match"), ("transfer", "pair")])
def test_passing_a_drafted_line_hands_on_both_ids(monkeypatch, source, called):
    """The pass path is where the internal id reached the audit log: it now passes each id to the parameter that takes it."""
    seen = {}
    monkeypatch.setattr(bms.bank_matching_service, "match", lambda *a, **k: seen.update(match=k))
    import services.bank_entry_service as bes
    monkeypatch.setattr(bes.bank_transfer_service, "pair", lambda *a, **k: seen.update(pair=k))
    txn = {"id": "t1", "client_id": CLIENT, "draft_source": source, "draft_grade": "ready", "draft_entity_type": "sales_invoice",
           "draft_entity_id": "other", "credit_paise": 0, "debit_paise": 100}
    bank_entry_service._apply_draft(None, FIRM, txn, INTERNAL, SIGN_IN)
    assert seen[called]["actor_id"] == INTERNAL and seen[called]["actor_auth_id"] == SIGN_IN


def test_passing_a_drafted_line_tags_its_party_with_the_sign_in_id(monkeypatch):
    """The party tag's only person is its audit row, so it is the sign-in id."""
    seen = {}
    import services.bank_entry_service as bes
    monkeypatch.setattr(bes.bank_payee_service, "apply_rule_party", lambda *a, **k: seen.update(k))
    monkeypatch.setattr(bes.banking_service, "set_account", lambda *a, **k: None)
    txn = {"id": "t1", "client_id": CLIENT, "draft_source": "rule", "draft_account_id": "acc-1", "draft_payee_type": "vendor",
           "draft_payee_id": "v-1"}
    bank_entry_service._apply_draft(None, FIRM, txn, INTERNAL, SIGN_IN)
    assert seen.get("actor_id") == SIGN_IN


def test_the_match_and_pair_routes_hand_on_both_ids(monkeypatch):
    """Through the real handlers: the route passes the caller's internal id for the column and their sign-in id for the audit row."""
    import routers.banking as rb
    seen = {}
    monkeypatch.setattr(rb, "_db", lambda: object())
    monkeypatch.setattr(rb, "_service_db", lambda: None)
    monkeypatch.setattr(rb, "_assert_txn_scope", lambda *a, **k: None)
    monkeypatch.setattr(rb.bank_matching_service, "match", lambda *a, **k: seen.update(match=k) or {})
    monkeypatch.setattr(rb.bank_transfer_service, "pair", lambda *a, **k: seen.update(pair=k) or {})
    monkeypatch.setattr(rb.bank_transfer_service, "unpair", lambda *a, **k: seen.update(unpair=k) or {})
    user = {"firm_id": FIRM, "id": INTERNAL, "auth_user_id": SIGN_IN, "role": "Partner"}
    rb.match_transaction("t1", rb.MatchIn(matched_entity_type="sales_invoice", matched_entity_id="inv-1"), current_user=user)
    rb.pair_transfer("t1", rb.BankTransferPairIn(counterpart_id="t2"), current_user=user)
    rb.unpair_transfer("t1", current_user=user)
    for k in ("match", "pair"):
        assert seen[k]["actor_id"] == INTERNAL and seen[k]["actor_auth_id"] == SIGN_IN, (k, seen[k])
    assert seen["unpair"]["actor_auth_id"] == SIGN_IN and "actor_id" not in seen["unpair"]
