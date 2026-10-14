"""Pairing two bank lines as one transfer calls a function only the service role may execute (POST-A-222).

WHAT WAS WRONG
    Migration 258 grants EXECUTE on `pair_bank_transfer` and `unpair_bank_transfer` to `service_role` ALONE, on purpose:
    a SECURITY DEFINER function taking a firm id must not be callable by `authenticated`, which could pass any firm's.
    `bank_transfer_service.pair` / `unpair` called them with the CALLER'S client. With `USE_USER_JWT` on (production's
    default) that client is `authenticated`, so the call was refused with "permission denied for function" for every
    signed-in user, the route answered 422 "Could not pair the transfer", and a transfer could never be paired. The
    mock-mode tests used a fake that accepts any caller, and the real-database tests call the function as the
    administrator, so nothing saw it. (Found by the independent review of migration 486, 14-10-2026.)

WHAT THIS ASSERTS
    * `pair` and `unpair` call the function through `rpc_db` when one is given, and never through the caller's client;
    * a caller's client that REFUSES the call (as `authenticated` does) is not asked: pairing succeeds through the service
      client alone;
    * both routes hand the service client in, and the pair route checks the caller's reach of BOTH transactions, because
      the function checks the firm and that the two share a client and the route is what checks the caller's own reach.
"""
from __future__ import annotations

import inspect
import re

import pytest

from routers import banking
from services.bank_transfer_service import bank_transfer_service

FIRM = "firm-1"


class _Rpc:
    def __init__(self, owner, name): self.owner, self.name = owner, name

    def execute(self):
        if self.owner.refuses:
            raise RuntimeError(f"permission denied for function {self.name}")
        self.owner.calls.append(self.name)

        class _R: data = []
        return _R()


class _Client:
    def __init__(self, refuses=False):
        self.refuses, self.calls = refuses, []

    def rpc(self, name, params): return _Rpc(self, name)


@pytest.fixture(autouse=True)
def _no_reads(monkeypatch):
    # what comes back after the call is not under test: `get` reads the caller's client
    monkeypatch.setattr(bank_transfer_service, "get", lambda db, firm, txn: {"id": txn})
    monkeypatch.setattr(bank_transfer_service, "_log", lambda *a, **k: None)


def test_pairing_calls_the_function_through_the_service_client_and_never_the_callers():
    caller, service = _Client(refuses=True), _Client()

    bank_transfer_service.pair(caller, FIRM, "out", "in", actor_id="auth-1", rpc_db=service)

    assert service.calls == ["pair_bank_transfer"] and caller.calls == []


def test_unpairing_calls_the_function_through_the_service_client_and_never_the_callers():
    caller, service = _Client(refuses=True), _Client()

    bank_transfer_service.unpair(caller, FIRM, "out", actor_id="auth-1", rpc_db=service)

    assert service.calls == ["unpair_bank_transfer"] and caller.calls == []


def test_the_premise_a_callers_own_client_is_refused_the_function():
    """What production did: with no service client the caller's is used, and `authenticated` is refused."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        bank_transfer_service.pair(_Client(refuses=True), FIRM, "out", "in")
    assert e.value.status_code == 422 and "permission denied" in e.value.detail


@pytest.mark.parametrize("fn,name", [(banking.pair_transfer, "pair_transfer"),
                                     (banking.unpair_transfer, "unpair_transfer")])
def test_both_routes_hand_the_service_client_in(fn, name):
    src = inspect.getsource(fn)
    assert re.search(r"rpc_db\s*=\s*_service_db\(\)", src), f"{name} calls the function with the caller's own client"


def test_the_pair_route_checks_the_callers_reach_of_both_transactions():
    src = inspect.getsource(banking.pair_transfer)
    assert "_assert_txn_scope(db, current_user, txn_id)" in src
    assert "_assert_txn_scope(db, current_user, data.counterpart_id)" in src, \
        "the counterpart is a row id in the BODY: without this check the function would pair a line of a client the " \
        "caller cannot reach, as the service role"
