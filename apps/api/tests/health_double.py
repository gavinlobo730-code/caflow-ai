"""A stand-in for the health engine's stored scores (`repositories/health_scores_repository`) for tests whose fixture clients carry a
`health_score`: the number on a fixture client is taken as that client's stored score, and a client without a number has no row,
which is how a client nobody has calculated looks; a fixture may also carry `health_is_critical` / `health_is_at_risk` / `health_calculated_at`, stored beside
the score the way the engine stores them. Not a test module: a helper, so five test files do not each grow a copy.

It keeps the repository's CONTRACT as well as its answers, because a reader that asked the wrong firm, or none, gets "no rows" from
the real thing and a swallowed error besides, which looks exactly like a firm nobody has scored yet: a read for no firm raises, and a
read for a firm other than the one the scores belong to finds none of them."""
from __future__ import annotations


class StoredScoresFrom:
    def __init__(self, clients, firm_id="f1"):
        self.clients = list(clients)
        self.firm_id = firm_id
        self.asked: list = []

    def find_all(self, firm_id=None, client_id=None):
        if not firm_id:
            raise ValueError("the stored health scores are read for a firm")
        self.asked.append((firm_id, client_id))
        if firm_id != self.firm_id:
            return []
        rows = []
        for c in self.clients:
            if not isinstance(c.get("health_score"), int) or isinstance(c.get("health_score"), bool):
                continue
            if client_id is not None and c["id"] != client_id:
                continue
            row = {"client_id": c["id"], "overall_score": c["health_score"]}
            # The engine's stored verdict, for a fixture that wants one the score alone would not give (a hard override).
            for stored, key in (("is_critical", "health_is_critical"), ("is_at_risk", "health_is_at_risk"),
                                ("last_calculated_at", "health_calculated_at")):
                if key in c:
                    row[stored] = c[key]
            rows.append(row)
        return rows


class CappedAtMaxRows:
    """A database whose every response is cut at PostgREST's `db-max-rows` (1,000), the way the real one answers a read that was not
    told to page: a firm of more clients than that is read whole only by a read that pages."""
    def __init__(self, db, cap=1000):
        self.db, self.cap = db, cap

    def table(self, name):
        return _CappedQuery(self.db.table(name), self.cap)


class _CappedQuery:
    def __init__(self, query, cap):
        self.query, self.cap = query, cap

    def __getattr__(self, name):
        attribute = getattr(self.query, name)
        if not callable(attribute):
            return attribute

        def call(*args, **kwargs):
            out = attribute(*args, **kwargs)
            if name == "execute":
                out.data = (out.data or [])[:self.cap]
                return out
            return self if out is self.query else out
        return call
