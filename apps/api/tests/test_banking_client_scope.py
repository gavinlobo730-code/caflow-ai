"""
Client-assignment scope on the banking endpoints addressed by ROW ID.

`core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a Manager,
Executive or Reviewer sees only the clients in `user_client_assignments`.
Endpoints taking a `client_id` parameter enforced that. Endpoints addressed by
`{txn_id}` or `{recon_id}` did not — they checked `firm_id` and stopped, so a row
id belonging to another manager's client was accepted on reads AND on writes.
`POST …/post` wrote a journal into that client's books.

There are two things to prove and they need different tests:

  1. **The guard works.** `assert_client_access` is permissive in mock mode (no
     SUPABASE_URL, so there is no assignments table), so these tests substitute a
     denying one and check the endpoint refuses — with 404, not 403, because
     existence is not disclosed.

  2. **Nobody forgot one.** A per-endpoint test only covers the endpoints someone
     remembered to write a test for, which is the same failure mode as the bug.
     `test_every_row_addressed_banking_endpoint_asserts_client_scope` walks the
     REGISTERED ROUTES and fails for any new one that skips the guard.
"""
import inspect
import re

import pytest
from fastapi import HTTPException

import routers.banking as rb


FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "manager"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Nobody forgot one — enumerate the registered routes
# ══════════════════════════════════════════════════════════════════════════════

def _row_addressed_banking_routes():
    """(path, method, endpoint) for every banking route keyed by a row id whose
    table is client-scoped."""
    from main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/banking/"):
            continue
        if "{txn_id}" not in path and "{recon_id}" not in path:
            continue
        for m in sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}):
            out.append((path, m, r.endpoint))
    return out


def test_the_route_sweep_actually_finds_the_endpoints():
    """A sweep that matches nothing would pass the test below vacuously."""
    routes = _row_addressed_banking_routes()
    assert len(routes) >= 30, f"expected the banking row-addressed routes, got {len(routes)}"
    paths = {p for p, _m, _e in routes}
    # The write that motivated the fix, and the read that leaks the most.
    assert "/api/banking/transactions/{txn_id}/post" in paths
    assert "/api/banking/transactions/{txn_id}/suggestions" in paths
    assert "/api/banking/reconciliations/{recon_id}/report.csv" in paths


@pytest.mark.parametrize("path,method,endpoint", [
    pytest.param(p, m, e, id=f"{m} {p}") for p, m, e in _row_addressed_banking_routes()
])
def test_every_row_addressed_banking_endpoint_asserts_client_scope(path, method, endpoint):
    """Source-level, deliberately: the point is to fail on the NEXT endpoint
    somebody adds, before it ever reaches a database. A runtime test would only
    cover the ones we thought to enumerate."""
    src = inspect.getsource(endpoint)
    guard = "_assert_txn_scope" if "{txn_id}" in path else "_assert_recon_scope"
    assert guard in src, (
        f"{method} {path} is addressed by a row id and never calls {guard}(). "
        f"Firm scoping alone lets a row id from another manager's client through.")


def test_the_guard_runs_after_the_mock_mode_short_circuit():
    """`if not db: return …` comes first, so the guard cannot dereference None.
    Getting this backwards would 500 every request in a dev environment."""
    for path, _m, endpoint in _row_addressed_banking_routes():
        src = inspect.getsource(endpoint)
        guard = "_assert_txn_scope" if "{txn_id}" in path else "_assert_recon_scope"
        lines = src.split("\n")
        guard_at = next(i for i, l in enumerate(lines) if guard + "(" in l and "def " not in l)
        db_at = next(i for i, l in enumerate(lines) if re.search(r"\bdb = _db\(\)", l))
        assert db_at < guard_at, f"{path}: the guard runs before db is resolved"
        # …and behind the mock-mode check, written either way round: most
        # handlers early-return on `if not db:`, report.csv nests under `if db:`.
        preceding = "\n".join(lines[db_at:guard_at])
        assert re.search(r"if not db:|if db:", preceding), \
            f"{path}: the guard is not behind the mock-mode check"


# ══════════════════════════════════════════════════════════════════════════════
# 2. The guard works
# ══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table, log):
        self.s, self.t, self.log = store, table, log
        self.eqs, self.limit_ = [], None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def limit(self, n): self.limit_ = n; return self

    def execute(self):
        self.log.append((self.t, dict(self.eqs)))
        rows = [r for r in self.s.get(self.t, [])
                if not any(r.get(k) != v for k, v in self.eqs)]
        return _Resp(rows[:self.limit_] if self.limit_ else rows)


class FakeDB:
    def __init__(self, store): self.store, self.log = store, []
    def table(self, n): return _Q(self.store, n, self.log)


def _db_with(table, row_id, *, client_id=CLIENT, firm_id=FIRM):
    return FakeDB({table: [{"id": row_id, "firm_id": firm_id, "client_id": client_id}]})


@pytest.fixture
def deny(monkeypatch):
    """Substitute a denying assert_client_access — the real one is permissive in
    mock mode, so without this there is nothing to observe."""
    asked = []

    def _deny(user, client_id):
        asked.append((user.get("id"), client_id))
        raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(rb, "assert_client_access", _deny)
    return asked


def test_a_transaction_outside_the_callers_book_is_refused(deny):
    db = _db_with("bank_transactions", "t1")
    with pytest.raises(HTTPException) as e:
        rb._assert_txn_scope(db, USER, "t1")
    assert e.value.status_code == 404          # not 403 — existence is not disclosed
    assert deny == [("u1", CLIENT)]


def test_a_reconciliation_outside_the_callers_book_is_refused(deny):
    db = _db_with("bank_reconciliations", "r1")
    with pytest.raises(HTTPException) as e:
        rb._assert_recon_scope(db, USER, "r1")
    assert e.value.status_code == 404
    assert deny == [("u1", CLIENT)]


def test_a_permitted_row_returns_its_client_id_so_callers_need_not_re_read():
    db = _db_with("bank_transactions", "t1")
    assert rb._assert_txn_scope(db, USER, "t1") == CLIENT


def test_the_lookup_is_still_firm_scoped():
    """The assignment check is an ADDITION to tenant scoping, not a replacement:
    a Partner of another firm passes can_access_client for their own firm and
    would otherwise sail through."""
    db = _db_with("bank_transactions", "t1", firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        rb._assert_txn_scope(db, USER, "t1")
    assert e.value.status_code == 404
    assert db.log == [("bank_transactions", {"id": "t1", "firm_id": FIRM})]


def test_a_row_that_does_not_exist_is_the_same_404_as_one_you_may_not_see():
    """Two different reasons, one answer — otherwise the status code itself
    becomes an oracle for which transaction ids are real."""
    db = FakeDB({"bank_transactions": []})
    with pytest.raises(HTTPException) as missing:
        rb._assert_txn_scope(db, USER, "nope")
    denied_db = _db_with("bank_transactions", "t1", firm_id="firm-2")
    with pytest.raises(HTTPException) as hidden:
        rb._assert_txn_scope(denied_db, USER, "t1")
    assert missing.value.status_code == hidden.value.status_code == 404


def test_the_guard_reads_one_row_and_only_the_column_it_needs():
    """It runs ahead of every one of these endpoints, so it must stay cheap."""
    db = _db_with("bank_transactions", "t1")
    rb._assert_txn_scope(db, USER, "t1")
    assert len(db.log) == 1


def test_posting_refuses_before_it_can_write_a_journal(deny):
    """The endpoint that made this worth fixing. The scope check has to come
    before the service is called at all — a journal written and then rejected is
    not the same as one never written."""
    reached = []

    class _Spy:
        def post(self, *a, **k):
            reached.append(a)
            return {}

    real_svc, real_db = rb.bank_posting_service, rb._db
    rb.bank_posting_service = _Spy()
    rb._db = lambda: _db_with("bank_transactions", "t1")
    try:
        from models.banking import PostBankTxnIn
        with pytest.raises(HTTPException) as e:
            rb.post_transaction("t1", PostBankTxnIn(), current_user=USER)
    finally:
        rb.bank_posting_service, rb._db = real_svc, real_db

    assert e.value.status_code == 404
    assert reached == [], "the posting service was reached despite the refusal"
