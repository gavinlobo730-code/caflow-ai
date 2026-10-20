"""A stand-in for the health engine's stored scores (`repositories/health_scores_repository`) for tests whose fixture clients carry a
`health_score`: the number on a fixture client is taken as that client's stored score, and a client without a number has no row,
which is how a client nobody has calculated looks. Not a test module: a helper, so five test files do not each grow a copy.

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
        return [{"client_id": c["id"], "overall_score": c["health_score"]}
                for c in self.clients if isinstance(c.get("health_score"), int) and not isinstance(c.get("health_score"), bool)
                and (client_id is None or c["id"] == client_id)]
