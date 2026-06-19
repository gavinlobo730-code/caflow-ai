"""
Tests — HSN/SAC smart suggestions (UX completion phase).

Covers:
  * _normalize_desc: stable lookup key (lower-cased, whitespace-collapsed)
  * hsn_suggestions: ranked, de-duped by code, singular/plural reason text,
    empty query short-circuits with no DB call
  * _record_hsn_preferences (the "learning" path): inserts a new preference,
    increments + refreshes an existing one, and skips blank description/HSN

CGST Rule 46(g): HSN/SAC is a mandatory tax-invoice field. These suggestions
only reduce manual entry — never used in any GST/journal computation.
"""
import pytest

from routers import sales_invoices


# ---------------------------------------------------------------------------
# Recording fake Supabase query-builder
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table, recorder, controller):
        self._table = table
        self._rec = recorder
        self._ctl = controller
        self._op = "select"
        self._payload = None
        self._filters = {}

    def select(self, *a, **k): self._op = "select"; return self
    def insert(self, payload): self._op = "insert"; self._payload = payload; return self
    def update(self, payload): self._op = "update"; self._payload = payload; return self
    def delete(self): self._op = "delete"; return self
    def eq(self, col, val): self._filters[col] = val; return self

    # chainable no-ops
    def is_(self, *a, **k): return self
    def ilike(self, col, val): self._filters[f"ilike:{col}"] = val; return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        event = {"table": self._table, "op": self._op,
                 "payload": self._payload, "filters": dict(self._filters)}
        self._rec.append(event)
        return self._ctl(event)


class _FakeDB:
    def __init__(self, recorder, controller):
        self._rec = recorder
        self._ctl = controller

    def table(self, name):
        return _Query(name, self._rec, self._ctl)


_USER = {"firm_id": "F1", "auth_user_id": "u1", "email": "u@firm.test", "role": "Partner"}


@pytest.fixture
def fake_db(monkeypatch):
    recorder: list[dict] = []
    holder = {"controller": lambda event: _Resp(data=[])}
    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    return recorder, holder


# ---------------------------------------------------------------------------
# _normalize_desc
# ---------------------------------------------------------------------------

class TestNormalizeDesc:
    @pytest.mark.parametrize("raw,expected", [
        ("  GST   Filing ", "gst filing"),
        ("Audit\tFees", "audit fees"),
        ("GST Filing", "gst filing"),
        ("", ""),
        (None, ""),
    ])
    def test_normalise(self, raw, expected):
        assert sales_invoices._normalize_desc(raw) == expected


# ---------------------------------------------------------------------------
# hsn_suggestions endpoint
# ---------------------------------------------------------------------------

class TestHsnSuggestions:
    def test_empty_query_short_circuits(self, fake_db):
        recorder, holder = fake_db
        resp = sales_invoices.hsn_suggestions(client_id="C1", query="   ", limit=5, current_user=_USER)
        assert resp["success"] is True
        assert resp["data"] == []
        assert recorder == [], "no DB call should be made for an empty query"

    def test_ranked_deduped_and_reason_text(self, fake_db):
        recorder, holder = fake_db
        # Two distinct codes + a duplicate of the top one (must collapse).
        holder["controller"] = lambda e: _Resp(data=[
            {"hsn_sac": "998221", "sample_description": "GST Filing",
             "gst_rate_bps": 1800, "use_count": 47, "last_used_at": "2026-06-19"},
            {"hsn_sac": "998221", "sample_description": "GST filing",
             "gst_rate_bps": 1800, "use_count": 9, "last_used_at": "2026-06-10"},
            {"hsn_sac": "998222", "sample_description": "GST Filing (annual)",
             "gst_rate_bps": 1800, "use_count": 3, "last_used_at": "2026-05-01"},
        ])
        resp = sales_invoices.hsn_suggestions(client_id="C1", query="GST Filing", limit=5, current_user=_USER)

        data = resp["data"]
        assert [d["hsn_sac"] for d in data] == ["998221", "998222"], "deduped, order preserved"
        assert data[0]["reason"] == "Used in 47 previous GST Filing invoices"
        # The DB lookup used the normalised key as an ILIKE filter.
        sel = [e for e in recorder if e["table"] == "hsn_sac_preferences"][0]
        assert sel["filters"]["ilike:description_key"] == "%gst filing%"
        assert sel["filters"]["firm_id"] == "F1"
        assert sel["filters"]["client_id"] == "C1"

    def test_singular_reason_for_one_use(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = lambda e: _Resp(data=[
            {"hsn_sac": "998314", "sample_description": "Audit",
             "gst_rate_bps": 1800, "use_count": 1, "last_used_at": "2026-06-19"},
        ])
        resp = sales_invoices.hsn_suggestions(client_id="C1", query="Audit", limit=5, current_user=_USER)
        assert resp["data"][0]["reason"] == "Used in 1 previous Audit invoice"


# ---------------------------------------------------------------------------
# _record_hsn_preferences  (the learning path)
# ---------------------------------------------------------------------------

class TestRecordPreferences:
    def test_inserts_new_preference(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = lambda e: _Resp(data=[])  # nothing exists yet

        from core.supabase_client import get_supabase
        sales_invoices._record_hsn_preferences(
            get_supabase(), "F1", "C1",
            [{"description": "GST Filing", "hsn_sac": "998221", "gst_rate_bps": 1800}],
        )
        inserts = [e for e in recorder if e["op"] == "insert"]
        assert len(inserts) == 1
        p = inserts[0]["payload"]
        assert p["description_key"] == "gst filing"
        assert p["hsn_sac"] == "998221"
        assert p["use_count"] == 1
        assert p["sample_description"] == "GST Filing"

    def test_increments_existing_preference(self, fake_db):
        recorder, holder = fake_db

        def _ctl(event):
            if event["op"] == "select":
                return _Resp(data=[{"id": "PREF-1", "use_count": 46}])
            return _Resp(data=[{"id": "PREF-1"}])

        holder["controller"] = _ctl
        from core.supabase_client import get_supabase
        sales_invoices._record_hsn_preferences(
            get_supabase(), "F1", "C1",
            [{"description": "GST Filing", "hsn_sac": "998221", "gst_rate_bps": 1800}],
        )
        updates = [e for e in recorder if e["op"] == "update"]
        assert len(updates) == 1
        assert updates[0]["payload"]["use_count"] == 47, "override/repeat bumps the count"
        assert updates[0]["filters"]["id"] == "PREF-1"
        assert "last_used_at" in updates[0]["payload"]

    def test_skips_lines_without_description_or_hsn(self, fake_db):
        recorder, holder = fake_db
        from core.supabase_client import get_supabase
        sales_invoices._record_hsn_preferences(
            get_supabase(), "F1", "C1",
            [
                {"description": "No HSN here", "hsn_sac": "", "gst_rate_bps": 1800},
                {"description": "", "hsn_sac": "998221", "gst_rate_bps": 1800},
            ],
        )
        assert recorder == [], "no DB writes for blank description or blank HSN"
