"""
Batch 3.1 follow-up — POST /api/practice/provision also seeds the firm CoA (so
existing firms become fully operational, not just new ones).
"""
import routers.practice as practice


class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, data): self._data = data
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def maybe_single(self): return self
    def execute(self): return _Result(self._data)


class _DB:
    def table(self, _name):
        return _Query({"name": "Firm A", "pan": "AAAAA1111A", "gstin": None})


def test_provision_endpoint_seeds_coa_and_provisions(monkeypatch):
    calls = {"coa": 0, "provision": 0}
    monkeypatch.setattr(practice, "_USE_MOCK", False)
    monkeypatch.setattr(practice, "_db", lambda: _DB())
    monkeypatch.setattr(practice, "seed_firm_coa",
                        lambda fid: (calls.__setitem__("coa", calls["coa"] + 1) or {"seeded": 32, "skipped": False}))
    monkeypatch.setattr(practice, "provision",
                        lambda *a, **k: (calls.__setitem__("provision", calls["provision"] + 1) or "INT-1"))

    resp = practice.provision_practice(current_user={"firm_id": "F1", "role": "Partner"})

    assert calls["coa"] == 1, "CoA must be seeded during provisioning"
    assert calls["provision"] == 1, "internal client must be provisioned"
    assert resp["success"] is True
    assert resp["data"]["internal_client_id"] == "INT-1"
    assert resp["data"]["coa_seeded"] == 32
