"""
Marking a chart-of-accounts row as holding unbilled dues has to reach a
FIRM-LEVEL account (client_id IS NULL), not only a row scoped to the one
client on screen.

CLAUDE.md: "A chart_of_accounts row with client_id IS NULL is a firm-level
account and is allowed on any of that firm's entries." A client whose whole
chart is firm-level therefore has real asset/liability accounts to mark, and
`services/ageing_schedule_service._write()` used to scope the update with
`.eq("client_id", client_id)` — which never matches a NULL column in Postgres,
so the write silently touched zero rows and the CA's mark was lost with no
error at all.

The fake below models exactly the two predicates the fixed query issues
(`eq` and `or_`), the same shape tests/test_bank_account_first_coding.py uses
for the identical PostgREST fallback-account pattern elsewhere in this
codebase.
"""
import pytest
from fastapi import HTTPException

from services import ageing_schedule_service

FIRM = "firm-1"
CLIENT = "client-1"
OTHER_CLIENT = "client-2"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    """Enough PostgREST to run _write()'s "account" branch for real: eq, or_,
    update, execute. `or_` handles only the one expression this path builds
    and raises on anything else — a double that quietly matched nothing would
    make a lost write indistinguishable from a correct one."""

    def __init__(self, store, table):
        self.store, self.table = store, table
        self._pred, self._payload = [], None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, k, v):
        self._pred.append(lambda r, k=k, v=v: r.get(k) == v)
        return self

    def or_(self, expr):
        expect = f"client_id.eq.{CLIENT},client_id.is.null"
        if expr != expect:
            raise AssertionError(f"the fake does not model or_({expr!r})")
        self._pred.append(lambda r: r.get("client_id") in (None, CLIENT))
        return self

    def execute(self):
        rows = [r for r in self.store.setdefault(self.table, [])
                if all(p(r) for p in self._pred)]
        for r in rows:
            r.update(self._payload)
        return _Resp(rows)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _account(db, id, *, client_id):
    row = dict(id=id, firm_id=FIRM, client_id=client_id,
               account_code="1801", account_name="Accrued Income",
               account_type="Asset", is_active=True, unbilled_dues_side=None)
    db.store.setdefault("chart_of_accounts", []).append(row)
    return row


def test_a_firm_level_account_can_be_marked():
    db = FakeDB()
    row = _account(db, "acc-firm-wide", client_id=None)

    out = ageing_schedule_service.classify(
        db, FIRM, CLIENT, "account", "acc-firm-wide",
        {"unbilled_dues_side": "receivable"})

    assert out["set"] == {"unbilled_dues_side": "receivable"}
    assert row["unbilled_dues_side"] == "receivable", (
        "the update reached zero rows — the old .eq('client_id', client_id) "
        "filter never matches a NULL column")


def test_a_client_scoped_account_can_still_be_marked():
    db = FakeDB()
    row = _account(db, "acc-own", client_id=CLIENT)

    ageing_schedule_service.classify(
        db, FIRM, CLIENT, "account", "acc-own", {"unbilled_dues_side": "payable"})

    assert row["unbilled_dues_side"] == "payable"


def test_another_clients_account_is_not_touched():
    """Tenancy is not loosened by this fix — only the firm-wide (NULL) case is
    added to what one client's review may reach. The write matches nothing, so
    classify() reports it as not found rather than silently succeeding."""
    db = FakeDB()
    row = _account(db, "acc-other-client", client_id=OTHER_CLIENT)

    with pytest.raises(HTTPException) as e:
        ageing_schedule_service.classify(
            db, FIRM, CLIENT, "account", "acc-other-client",
            {"unbilled_dues_side": "payable"})
    assert e.value.status_code == 404

    assert row["unbilled_dues_side"] is None
