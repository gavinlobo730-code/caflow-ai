"""
Guard PLACEMENT — the trap this sweep hit four separate times.

A scope check is only worth what its position makes it worth. Two placements
turn a correct check into no check at all:

  A. The check sits AFTER an early `return` on a mock/short-circuit branch, so
     the branch that returns real data never runs it. Found in
     currencies.get_currency_policy, then — by scanning for the pattern rather
     than waiting to trip over it — in timeline, receipts and purchase_payments.

     The sting in A is that `_USE_MOCK` is exactly the mode the in-memory CI job
     runs in, so a guard placed below a mock branch is precisely the guard no
     test can exercise.

  B. The check sits INSIDE a `try` whose handler swallows Exception into a
     non-raising response. HTTPException IS an Exception, so the denial is
     downgraded — to a 500 in einvoice.py, to a soft `success: false` 200 in
     hsn.py. Both are covered by their own routers' test files; this file
     covers A.

An AST scan for both patterns across every router is what turned this from
three anecdotes into a checked class. It also produced one FALSE positive worth
recording: compliance_records.create_compliance_record catches a TUPLE,
`(ValidationError, KeyError)`, which does not catch HTTPException — so its
in-try check is fine.
"""
import pytest
from fastapi import HTTPException

import routers.timeline as tl
import routers.receipts as rcp
import routers.purchase_payments as pp

FIRM, OTHER = "firm-1", "firm-2"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}


@pytest.fixture
def only_mine(monkeypatch):
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client",
                        lambda user, cid: (not cid) or cid == MINE)
    for mod in (rcp, pp):
        if hasattr(mod, "can_access_client"):
            monkeypatch.setattr(mod, "can_access_client",
                                lambda user, cid: (not cid) or cid == MINE)


# ── timeline: the check used to sit below the mock branch ────────────────────

def test_timeline_denies_unassigned_client_in_mock_mode(monkeypatch, only_mine):
    """MOCK MODE specifically: the check used to sit below this branch's
    `return`, so the whole in-memory test run exercised the unguarded path."""
    monkeypatch.setattr(tl, "_USE_MOCK", True)
    import services.timeline_service as ts
    monkeypatch.setattr(ts, "MOCK_TIMELINE_EVENTS", [
        {"id": "e1", "client_id": THEIRS, "firm_id": FIRM, "created_at": "2026-01-01",
         "category": "tax", "severity": "info"},
    ], raising=False)

    with pytest.raises(HTTPException) as exc:
        tl.list_timeline_events(client_id=THEIRS, current_user=USER)
    assert exc.value.status_code == 404


def test_timeline_allows_assigned_client_in_mock_mode(monkeypatch, only_mine):
    monkeypatch.setattr(tl, "_USE_MOCK", True)
    import services.timeline_service as ts
    monkeypatch.setattr(ts, "MOCK_TIMELINE_EVENTS", [
        {"id": "e1", "client_id": MINE, "firm_id": FIRM, "created_at": "2026-01-01",
         "category": "tax", "severity": "info"},
    ], raising=False)

    # Every optional arg passed explicitly: calling the handler directly leaves
    # FastAPI's Query defaults as Query OBJECTS, which are truthy — so the
    # optional filters would all fire and match nothing, and limit/offset are
    # used as ints.
    resp = tl.list_timeline_events(client_id=MINE, current_user=USER,
                                   category=None, severity=None,
                                   financial_year=None, limit=50, offset=0)
    assert resp["success"] is True
    assert [e["id"] for e in resp["data"]] == ["e1"]


# ── receipts / purchase_payments: mock branches that diverged ────────────────

def test_receipts_mock_branch_enforces_assignment(monkeypatch, only_mine):
    """The mock branch checked neither firm nor assignment — it diverged from
    the real branch on the one thing the resolver exists to do."""
    monkeypatch.setattr(rcp, "_USE_MOCK", True)
    monkeypatch.setattr(rcp, "MOCK_RECEIPTS",
                        [{"id": "r1", "firm_id": FIRM, "client_id": THEIRS}], raising=False)

    with pytest.raises(HTTPException) as exc:
        rcp._assert_receipt_scope(USER, "r1")
    assert exc.value.status_code == 404


def test_receipts_mock_branch_enforces_firm(monkeypatch, only_mine):
    monkeypatch.setattr(rcp, "_USE_MOCK", True)
    monkeypatch.setattr(rcp, "MOCK_RECEIPTS",
                        [{"id": "r1", "firm_id": OTHER, "client_id": MINE}], raising=False)

    with pytest.raises(HTTPException) as exc:
        rcp._assert_receipt_scope(USER, "r1")
    assert exc.value.status_code == 404


def test_receipts_mock_branch_allows_own_assigned_row(monkeypatch, only_mine):
    monkeypatch.setattr(rcp, "_USE_MOCK", True)
    monkeypatch.setattr(rcp, "MOCK_RECEIPTS",
                        [{"id": "r1", "firm_id": FIRM, "client_id": MINE}], raising=False)

    assert rcp._assert_receipt_scope(USER, "r1")["id"] == "r1"


def test_purchase_payments_mock_branch_enforces_assignment(monkeypatch, only_mine):
    """This one DID check the firm — but not the assignment, so it still
    diverged from the real branch below it."""
    monkeypatch.setattr(pp, "_USE_MOCK", True)
    monkeypatch.setattr(pp, "MOCK_PURCHASE_PAYMENTS",
                        [{"id": "p1", "firm_id": FIRM, "client_id": THEIRS}], raising=False)

    with pytest.raises(HTTPException) as exc:
        pp._assert_payment_scope(USER, "p1")
    assert exc.value.status_code == 404


def test_purchase_payments_mock_branch_allows_own_assigned_row(monkeypatch, only_mine):
    monkeypatch.setattr(pp, "_USE_MOCK", True)
    monkeypatch.setattr(pp, "MOCK_PURCHASE_PAYMENTS",
                        [{"id": "p1", "firm_id": FIRM, "client_id": MINE}], raising=False)

    assert pp._assert_payment_scope(USER, "p1")["id"] == "p1"


# ── the scan itself, kept as a standing check ───────────────────────────────

def test_no_scope_check_sits_inside_a_swallowing_try():
    """Pattern B, as a regression test rather than a one-off scan.

    A check inside a `try` whose handler catches bare Exception (and neither
    re-raises nor lets HTTPException past) is silently downgraded. A tuple
    except like `(ValidationError, KeyError)` does NOT catch HTTPException and
    is therefore fine — that distinction is the whole check.
    """
    import ast, os
    ROUTERS = os.path.join(os.path.dirname(__file__), "..", "routers")
    CHECKS = {"assert_client_access", "can_access_client",
              "assert_partner_for_internal_id"}
    offenders = []

    for fname in sorted(os.listdir(ROUTERS)):
        if not fname.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(ROUTERS, fname)).read())
        for t in ast.walk(tree):
            if not isinstance(t, ast.Try):
                continue
            body_calls = [n for b in t.body for n in ast.walk(b)
                          if isinstance(n, ast.Call)
                          and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) in CHECKS]
            if not body_calls:
                continue
            http_passthrough = any(
                getattr(h.type, "id", None) == "HTTPException"
                and any(isinstance(x, ast.Raise) for x in ast.walk(h))
                for h in t.handlers)
            for h in t.handlers:
                name = getattr(h.type, "id", None) or getattr(h.type, "attr", None)
                # h.type None = bare `except:`; a Tuple has neither id nor attr
                # but also cannot be Exception, so it is not an offender.
                if h.type is not None and name not in ("Exception", "BaseException"):
                    continue
                if any(isinstance(x, ast.Raise) and x.exc is None for x in ast.walk(h)):
                    continue
                if http_passthrough:
                    continue
                offenders.append(f"{fname}:{body_calls[0].lineno}")
                break

    assert not offenders, (
        "a client-scope check sits inside a try whose handler swallows "
        f"Exception, so the 404 is downgraded: {offenders}")
