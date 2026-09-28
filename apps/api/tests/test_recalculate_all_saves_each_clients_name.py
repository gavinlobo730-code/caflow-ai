"""Recalculate All saves each client's name on its health row.

health-hub-05: the health list renders `health_scores.client_name` straight off
the row. The per-client calculate has always stamped it; `recalculate_all`
selected only `id` from `clients` and upserted a payload with no name, so a row
it CREATED carried NULL and the list showed "—" until somebody recalculated that
one client by hand. These tests drive `recalculate_all` itself and read what it
upserted.
"""
import routers.health as hl

FIRM = "firm-1"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.cols = None

    def select(self, cols="*", *_a, **_k):
        self.cols = cols
        self.db.selects.append((self.table, cols))
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, payload, *_a, **_k):
        self.db.upserts.append((self.table, payload))
        return self

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        if self.table == "clients":
            # What a SELECT answers: only the columns it asked for.
            wanted = [c.strip() for c in (self.cols or "*").split(",")]
            r.data = [{k: v for k, v in c.items() if "*" in wanted or k in wanted}
                      for c in self.db.clients]
        else:
            r.data = []
        return r


class _Db:
    def __init__(self, clients):
        self.clients = clients
        self.selects, self.upserts = [], []

    def table(self, name):
        return _Query(self, name)


def _run(monkeypatch, clients):
    db = _Db(clients)
    monkeypatch.setattr(hl, "_db", lambda: db)
    monkeypatch.setattr(hl, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(hl, "_calculate_scores_db",
                        lambda db, client_id, firm_id: {"overall_score": 70, "health_grade": "Fair"})
    out = hl.recalculate_all(current_user=PARTNER)
    return db, out


def test_every_recalculated_row_carries_its_clients_name(monkeypatch):
    db, out = _run(monkeypatch, [
        {"id": "c-a", "client_name": "WF-ClientsAdmin QA Test Co"},
        {"id": "c-b", "client_name": "Meridian Traders"},
    ])

    assert out["data"]["updated"] == 2
    saved = {p["client_id"]: p for t, p in db.upserts if t == "health_scores"}
    assert saved["c-a"]["client_name"] == "WF-ClientsAdmin QA Test Co"
    assert saved["c-b"]["client_name"] == "Meridian Traders"


def test_a_client_with_no_name_is_saved_blank_not_null(monkeypatch):
    """The per-client path saves "" for a missing name; the two paths must
    write the same shape into the one row."""
    db, _ = _run(monkeypatch, [{"id": "c-a", "client_name": None}])

    (_t, payload), = [u for u in db.upserts if u[0] == "health_scores"]
    assert payload["client_name"] == ""
