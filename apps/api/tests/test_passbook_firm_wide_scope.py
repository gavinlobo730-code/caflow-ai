"""
A firm-wide report must never be served from per-client buckets.

THE BUG THIS PINS
    account_period_balances.client_id is NOT NULL — the passbook is keyed per
    client, and SupabaseLedgerSource.fetch_buckets filters
    .eq("client_id", client_id).

    Every reporting router treats client_id=None as "all clients", and the
    legacy path honours that by simply not filtering. The passbook path did not:
    with client_id=None it matched NO buckets and returned a report of ZEROES,
    while the legacy replay for the identical request returned the real figures.

    The failure was silent in the worst way. An empty bucket set raises nothing,
    so _serve's "degrade to legacy on error" fallback never fired — mode "on"
    served the empty result as if it were the answer. Nothing logged, nothing
    500'd, and a Trial Balance that should read 138000 read 0.

    Found by comparing firm-wide Trial Balance against its own legacy path while
    adding the Cash Flow fast path, which would have inherited it.

WHAT THE FIX IS
    _passbook_applicable now requires a client_id, so firm-wide reports fall
    back to the replay. Slower for a report nothing in the app currently asks
    for, and right. Summing every client's buckets is a different query with a
    different correctness argument; it is not smuggled in here.
"""
from __future__ import annotations

import pytest

from domain.reporting.service import ReportingService
from domain.reporting.sources import InMemoryLedgerSource, SupabaseLedgerSource
from tests.test_passbook_read_path import CLIENT, FIRM, _DB
from tests.test_cash_flow_passbook_equivalence import _seed_store

FY = ("2026-04-01", "2027-03-31")
AS_OF = "2027-03-31"


def _svc() -> ReportingService:
    return ReportingService(SupabaseLedgerSource(_DB(_seed_store())))


# Each entry: a label, and a callable taking (svc, client_id) -> report dict.
REPORTS = [
    ("trial_balance", lambda s, c: s.trial_balance(FIRM, c, AS_OF)),
    ("profit_loss", lambda s, c: s.profit_loss(FIRM, c, *FY)),
    ("balance_sheet", lambda s, c: s.balance_sheet(FIRM, c, AS_OF)),
    ("cash_flow", lambda s, c: s.cash_flow_statement(FIRM, c, *FY)),
]


@pytest.mark.parametrize("name,call", REPORTS, ids=[r[0] for r in REPORTS])
def test_a_firm_wide_report_matches_the_legacy_replay(monkeypatch, name, call):
    """The whole bug in one assertion, for all four reports. With client_id=None
    the fast path must produce what the replay produces — which, since the
    buckets cannot answer a firm-wide question at all, means falling back to it."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = call(_svc(), None)
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    fast = call(_svc(), None)

    assert fast == legacy, f"firm-wide {name} differs from its own legacy result"


@pytest.mark.parametrize("name,call", REPORTS, ids=[r[0] for r in REPORTS])
def test_the_firm_wide_numbers_are_not_all_zero(monkeypatch, name, call):
    """Vacuity guard, and the shape of the original symptom. Equality above would
    also hold if BOTH paths returned zeroes; the bug was specifically that the
    fast one did. These fixtures have a real ledger, so a firm-wide report of
    nothing is the defect, not a valid answer."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    out = call(_svc(), None)
    numbers = [v for v in out.values() if isinstance(v, int)]

    assert any(v != 0 for v in numbers), (
        f"firm-wide {name} came back all zeroes — the passbook answered a "
        f"question its per-client buckets cannot answer: {out}")


def test_the_client_scoped_report_still_uses_the_passbook(monkeypatch):
    """The gate must be surgical. Requiring client_id would be a cheap way to
    disable the passbook entirely; this proves the scoped path — the one every
    accounting page actually asks for — still takes it."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    svc = _svc()
    assert svc._passbook_applicable("accrual", CLIENT) is True
    assert svc._passbook_applicable("accrual", None) is False


def test_the_gate_still_rejects_what_it_rejected_before():
    """The client_id condition is added to the existing ones, not substituted
    for them: cash basis and non-Supabase sources must still be excluded."""
    svc = _svc()
    assert svc._passbook_applicable("cash", CLIENT) is False

    in_memory = ReportingService(InMemoryLedgerSource(accounts=[], entries=[]))
    assert in_memory._passbook_applicable("accrual", CLIENT) is False


def test_the_buckets_really_cannot_answer_a_firm_wide_question(monkeypatch):
    """Names the root cause rather than only the symptom. fetch_buckets filters
    on client_id, so asking it for None yields nothing — which is why the gate,
    not a smarter fallback, is the fix. If this ever starts returning buckets,
    the per-client assumption has changed and the gate should be revisited."""
    source = SupabaseLedgerSource(_DB(_seed_store()))

    assert source.fetch_buckets(FIRM, CLIENT), "the fixture has no buckets at all"
    assert source.fetch_buckets(FIRM, None) == {}
