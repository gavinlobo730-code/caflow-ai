"""The practice Compliance dashboard names its clients and its staff.

practice-hub-05: `aggregate_dashboard` keys "Workload by client" and "Workload
by staff" on raw ids and `dashboard()` never resolved them, so the screen showed
a column of UUIDs and the queue had no client at all. `dashboard()` now stamps a
`label` on every workload row and a `client_name` on every queue row — keeping
`key` as the id, so the payload only grows.

Driven on the LIVE branch: clients through the caller's client, staff through
the service-role user repository. The caller's own client is wired to show only
the caller's `users` row, which is what `users_own_row_select` does in
production — a lookup through it would name nobody but the caller.
"""
import pytest

import core.supabase_client as sc
import repositories.user_repository as ur
import services.compliance_obligation_service as svc

FIRM = "firm-1"


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.eqs, self.ins, self.gts = [], [], []
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.eqs.append((c, v))
        return self

    def is_(self, c, v):
        self.eqs.append((c, None))
        return self

    def in_(self, c, vs):
        self.ins.append((c, {str(v) for v in vs}))
        return self

    def gt(self, c, v):
        self.gts.append((c, v))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        out = [r for r in self.rows
               if all(r.get(c) == v for c, v in self.eqs)
               and all(str(r.get(c)) in vs for c, vs in self.ins)
               and all(str(r.get(c)) > str(v) for c, v in self.gts)]
        out.sort(key=lambda r: str(r.get("id")))
        if self._limit:
            out = out[: self._limit]

        class R:
            pass
        r = R()
        r.data = out
        return r


class _Db:
    def __init__(self, tables):
        self.tables = tables
        self.asked = []

    def table(self, name):
        self.asked.append(name)
        return _Query(self.tables[name])


CLIENTS = [
    {"id": "c-1", "firm_id": FIRM, "client_name": "Meridian Traders", "legal_name": "Meridian Traders Pvt Ltd"},
    {"id": "c-2", "firm_id": FIRM, "client_name": None, "legal_name": "Legal Only LLP"},
    {"id": "c-x", "firm_id": "other", "client_name": "Someone Else's Client", "legal_name": None},
]
USERS = [
    {"id": "u-me", "firm_id": FIRM, "full_name": "Caller", "deleted_at": None},
    {"id": "u-prep", "firm_id": FIRM, "full_name": "Asha Menon", "deleted_at": None},
]
RECORDS = [
    {"id": "r1", "client_id": "c-1", "preparer_id": "u-prep", "status": "Pending", "due_date": "2020-01-01"},
    {"id": "r2", "client_id": "c-2", "preparer_id": None, "status": "Pending", "due_date": "2099-01-01"},
    {"id": "r3", "client_id": "c-x", "preparer_id": "u-gone", "status": "Pending", "due_date": "2099-01-01"},
]


@pytest.fixture
def live(monkeypatch):
    service = _Db({"clients": CLIENTS, "users": USERS})
    # What the caller's own client sees of `users`: only themselves.
    callers = _Db({"clients": CLIENTS, "users": [USERS[0]]})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(ur, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: callers)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: service)
    monkeypatch.setattr(svc, "_records_for", lambda firm_id, client_id=None: [dict(r) for r in RECORDS])
    return service, callers


def test_workload_by_client_carries_the_clients_name(live):
    out = svc.dashboard(FIRM)

    labels = {s["key"]: s["label"] for s in out["by_client"]}
    assert labels["c-1"] == "Meridian Traders"
    assert labels["c-2"] == "Legal Only LLP"
    # Another firm's client id never turns into its name.
    assert labels["c-x"] is None


def test_workload_by_staff_carries_the_preparers_name(live):
    out = svc.dashboard(FIRM)

    labels = {s["key"]: s["label"] for s in out["by_staff"]}
    assert labels["u-prep"] == "Asha Menon"
    assert labels["unassigned"] == "Unassigned"
    assert labels["u-gone"] is None


def test_every_queue_row_names_its_client_and_keeps_its_id(live):
    out = svc.dashboard(FIRM)

    rows = {r["id"]: r for r in out["queue"]}
    assert rows["r1"]["client_name"] == "Meridian Traders"
    assert rows["r1"]["client_id"] == "c-1"
    assert "client_name" in rows["r3"] and rows["r3"]["client_name"] is None


def test_the_payload_only_grows(live):
    """`key` stays the id and the summary is untouched, so a consumer written
    against the old shape reads exactly what it read before."""
    out = svc.dashboard(FIRM)

    assert {s["key"] for s in out["by_client"]} == {"c-1", "c-2", "c-x"}
    assert out["summary"]["open_obligations"] == 3
    assert all({"key", "obligations", "overdue", "label"} <= set(s) for s in out["by_staff"])


def test_an_assignment_scoped_caller_is_named_only_their_own_clients(live):
    out = svc.dashboard(FIRM, allowed_client_ids={"c-1"})

    assert [s["key"] for s in out["by_client"]] == ["c-1"]
    assert [r["client_name"] for r in out["queue"]] == ["Meridian Traders"]
