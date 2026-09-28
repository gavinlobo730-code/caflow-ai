"""An archived client instruction leaves the live list.

`knowledge_service.update_instruction` has always accepted `is_archived`, and
`list_client_instructions` never asked for it — there was no column to ask
(migration 430 adds it). Once archive can be written, a reader that does not
filter it makes the button change nothing anybody can see, so the list is
asked here, on the LIVE branch, against a table fake that applies the filters
the query actually sends.
"""
from __future__ import annotations

import pytest

import services.knowledge_service as kb

FIRM, CLIENT = "firm-1", "client-1"
PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.patch = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        hit = [r for r in self.rows if all(r.get(c) == v for c, v in self.filters)]
        if self.patch is not None:
            for r in hit:
                r.update(self.patch)

        class R:
            pass
        out = R()
        out.data = hit
        return out


@pytest.fixture
def rows(monkeypatch):
    table = [
        {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "title": "Keep", "is_archived": False},
        {"id": "i2", "firm_id": FIRM, "client_id": CLIENT, "title": "Retire", "is_archived": False},
    ]

    class _Db:
        def table(self, name):
            assert name == "client_instructions"
            return _Query(table)

    monkeypatch.setattr(kb, "_USE_MOCK", False)
    monkeypatch.setattr(kb, "_db", lambda: _Db())
    monkeypatch.setattr(kb, "_assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(kb, "_emit_instruction_event", lambda *a, **k: None)
    return table


def test_an_archived_instruction_leaves_the_list(rows):
    assert {r["id"] for r in kb.list_client_instructions(PARTNER, CLIENT)} == {"i1", "i2"}

    archived = kb.update_instruction(PARTNER, CLIENT, "i2", {"is_archived": True})

    assert archived["is_archived"] is True
    assert [r["id"] for r in kb.list_client_instructions(PARTNER, CLIENT)] == ["i1"]


def test_the_list_asks_the_database_for_live_instructions_only(rows, monkeypatch):
    sent = []

    class _Recording(_Query):
        def execute(self):
            sent.extend(self.filters)
            return super().execute()

    class _Db:
        def table(self, name):
            return _Recording(rows)

    monkeypatch.setattr(kb, "_db", lambda: _Db())
    kb.list_client_instructions(PARTNER, CLIENT)

    assert ("is_archived", False) in sent
    assert ("firm_id", FIRM) in sent
