"""
apex-overview-practice-01 — a GST filing-frequency switch (Rule 61A) reuses
the SAME period_start keys the OLD frequency's obligations already occupy
(both monthly and quarterly GSTR-1/GSTR-3B/PMT-06 start on the 1st of a
month), so generate_for_engagement/generate_default_for_client's narrow
(obligation_type, period_start) dedup key treated a stale MONTHLY row as
"already generated" and silently skipped the correct QUARTERLY one.

Confirmed live via audit_log on Apex Trading Solutions: monthly obligations
generated 04-07-2026, switched to quarterly 29-08-2026 — every one of the 8
quarterly GSTR1/GSTR3B rows collided with a stale monthly row at the same
period_start and was skipped, while PMT-06 (a new obligation_type under
monthly, so nothing to collide with) generated its 8 rows fine. The result: a
self-contradictory compliance calendar mixing a monthly-shaped GSTR-3B row
with a quarterly-shaped PMT-06 row for the same period.

_reconcile_stale_gst_obligations (compliance_obligation_service.py) is the
fix: it compares existing GSTR1/GSTR3B/PMT06 rows against the freshly
computed spec set on the WIDER (obligation_type, period_start, period_end)
key, soft-deletes a stale "Not Started" row so its period_start is freed for
the correctly-shaped replacement, and leaves a row that already has real work
on it untouched — reporting it as a named gap instead.
"""
import pytest

import services.compliance_obligation_service as ob
from repositories.compliance_records_repository import compliance_records_repo
from repositories.client_repository import client_repo
from repositories.engagement_repository import engagement_repo
from mock_data import MOCK_COMPLIANCE_RECORDS, MOCK_CLIENTS, CLIENT_INDEX, MOCK_ENGAGEMENTS, ENGAGEMENT_INDEX

FIRM = "F-APEX"
FY = "2025-26"
GSTIN = "27AAPFU0939F1ZV"  # real, check-digit-valid fixture GSTIN


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    clients_snapshot = list(MOCK_CLIENTS)
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    MOCK_CLIENTS[:] = clients_snapshot
    CLIENT_INDEX.clear()
    CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})


def _client(client_id, freq="monthly"):
    return client_repo.create({
        "id": client_id, "firm_id": FIRM, "client_name": "Apex Trading Solutions",
        "gstin": GSTIN, "gst_filing_frequency": freq,
    })


def _records(client_id):
    return compliance_records_repo.find_all(firm_id=FIRM, client_id=client_id)


def _by_type(client_id, obligation_type):
    return sorted(
        (r for r in _records(client_id) if r.get("obligation_type") == obligation_type),
        key=lambda r: r["period_start"],
    )


# ── Fallback path (generate_default_for_client) — Apex had no active engagement ──

def test_switching_monthly_to_quarterly_replaces_the_stale_monthly_rows():
    _client("apex", freq="monthly")
    first = ob.generate_default_for_client(FIRM, "apex", FY)
    assert first["generated"] == 25          # 12 GSTR1 + 12 GSTR3B + 1 GSTR9, all Not Started
    assert len(_records("apex")) == 25

    # Switch to quarterly — exactly what routers/clients.py's PATCH does.
    CLIENT_INDEX["apex"]["gst_filing_frequency"] = "quarterly"

    second = ob.generate_default_for_client(FIRM, "apex", FY)

    # 4 quarterly GSTR1 + 4 quarterly GSTR3B + 8 PMT06 = 16 new rows.
    # GSTR9 is unaffected (same spec either way) and is the one skip.
    assert second["generated"] == 16, second
    assert second["skipped"] == 1, second

    recs = _records("apex")
    assert len(recs) == 17                    # 25 - 24 stale monthly + 16 new
    assert {r["obligation_type"] for r in recs} == {"GSTR1", "GSTR3B", "PMT06", "GSTR9"}

    gstr1 = _by_type("apex", "GSTR1")
    assert len(gstr1) == 4, "one per quarter, not one per month"
    assert all(r["due_date"][8:10] == "13" for r in gstr1), \
        "quarterly GSTR-1 is due the 13th (Rule 61A) — a leftover monthly row is due the 11th"

    gstr3b = _by_type("apex", "GSTR3B")
    assert len(gstr3b) == 4
    assert all(r["due_date"][8:10] in ("22", "24") for r in gstr3b), \
        "quarterly GSTR-3B is due the 22nd/24th — a leftover monthly row is due the 20th"

    pmt06 = _by_type("apex", "PMT06")
    assert len(pmt06) == 8

    # The self-contradiction the finding named: no row is left over from the
    # monthly schedule sitting beside the quarterly ones for the same period.
    # (GSTR9 also starts 1 Apr — the annual return spans the whole FY either
    # way — so it is expected here too and is not part of what changed.)
    q1_start = "2025-04-01"
    q1_rows = [r for r in recs if r["period_start"] == q1_start]
    assert {r["obligation_type"] for r in q1_rows} == {"GSTR1", "GSTR3B", "PMT06", "GSTR9"}
    q1_gstr1 = next(r for r in q1_rows if r["obligation_type"] == "GSTR1")
    assert q1_gstr1["period_end"] == "2025-06-30", "a quarter, not a month"


def test_a_stale_row_with_real_work_is_left_alone_and_named_as_a_gap():
    _client("apex-2", freq="monthly")
    ob.generate_default_for_client(FIRM, "apex-2", FY)

    # A CA has started on April's monthly GSTR-1 before the client moved to
    # QRMP — this row must not be silently thrown away.
    april_gstr1 = next(r for r in _by_type("apex-2", "GSTR1") if r["period_start"] == "2025-04-01")
    compliance_records_repo.update(april_gstr1["id"], {"status": "Awaiting Documents"})

    CLIENT_INDEX["apex-2"]["gst_filing_frequency"] = "quarterly"
    res = ob.generate_default_for_client(FIRM, "apex-2", FY)

    # The row is untouched...
    still_there = compliance_records_repo.find_by_id(april_gstr1["id"])
    assert still_there is not None
    assert still_there["status"] == "Awaiting Documents"
    assert still_there["period_end"] == "2025-04-30"   # still the monthly shape

    # ...and reported so a CA knows to act on it by hand.
    assert res.get("statutory_gaps"), res
    assert any("Awaiting Documents" in g for g in res["statutory_gaps"])

    # The Q1 GSTR-1 quarterly spec could not be inserted at the same
    # period_start (it would collide with the still-live monthly row in the
    # database's own partial unique index) — so it is correctly ABSENT, not
    # silently duplicated.
    q1_gstr1_rows = [r for r in _records("apex-2")
                    if r["obligation_type"] == "GSTR1" and r["period_start"] == "2025-04-01"]
    assert len(q1_gstr1_rows) == 1
    assert q1_gstr1_rows[0]["id"] == april_gstr1["id"]

    # But Q1 GSTR-3B (no real work on its April row) reconciled normally.
    q1_gstr3b = next(r for r in _records("apex-2")
                     if r["obligation_type"] == "GSTR3B" and r["period_start"] == "2025-04-01")
    assert q1_gstr3b["period_end"] == "2025-06-30"

    # And every OTHER quarter, untouched by the blocked April row, reconciled too.
    gstr1_periods = {r["period_start"] for r in _by_type("apex-2", "GSTR1")}
    assert gstr1_periods == {"2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"}


def test_re_running_after_a_frequency_switch_is_idempotent():
    """The reconciliation must not re-fire (and re-name the same gap) on
    every later sweep once the frequency has already settled."""
    _client("apex-3", freq="monthly")
    ob.generate_default_for_client(FIRM, "apex-3", FY)
    CLIENT_INDEX["apex-3"]["gst_filing_frequency"] = "quarterly"
    ob.generate_default_for_client(FIRM, "apex-3", FY)

    third = ob.generate_default_for_client(FIRM, "apex-3", FY)
    assert third["generated"] == 0
    assert third["skipped"] == 17
    assert "statutory_gaps" not in third or not third["statutory_gaps"]
    assert len(_records("apex-3")) == 17


def test_switching_quarterly_to_monthly_is_the_same_reconciliation_reversed():
    _client("apex-4", freq="quarterly")
    first = ob.generate_default_for_client(FIRM, "apex-4", FY)
    assert first["generated"] == 17    # 4 + 4 + 8 + 1

    CLIENT_INDEX["apex-4"]["gst_filing_frequency"] = "monthly"
    second = ob.generate_default_for_client(FIRM, "apex-4", FY)

    recs = _records("apex-4")
    assert {r["obligation_type"] for r in recs} == {"GSTR1", "GSTR3B", "GSTR9"}
    assert len(_by_type("apex-4", "GSTR1")) == 12
    assert len(_by_type("apex-4", "GSTR3B")) == 12
    # PMT06 has no monthly-frequency spec at all, so its 8 rows are simply
    # stale now (nothing new ever claims their period_start) and are gone.
    assert _by_type("apex-4", "PMT06") == []


# ── Engagement path (generate_for_engagement) — the other of the two functions
# the finding named ─────────────────────────────────────────────────────────

def _engagement(client_id, firm=FIRM):
    return engagement_repo.create({
        "firm_id": firm, "client_id": client_id, "service_type": "GST Compliance",
        "fee_paise": 500000, "billing_cycle": "Monthly", "start_date": "2025-04-01",
        "status": "Active",
    })


def test_generate_for_engagement_reconciles_the_same_way():
    _client("apex-eng", freq="monthly")
    eng = _engagement("apex-eng")
    first = ob.generate_for_engagement(FIRM, eng, FY)
    assert first["generated"] == 25

    CLIENT_INDEX["apex-eng"]["gst_filing_frequency"] = "quarterly"
    second = ob.generate_for_engagement(FIRM, eng, FY)
    assert second["generated"] == 16
    assert second["skipped"] == 1

    recs = _records("apex-eng")
    assert len(recs) == 17
    assert len(_by_type("apex-eng", "GSTR1")) == 4
    assert len(_by_type("apex-eng", "PMT06")) == 8
    # Engagement linkage survives on the newly-generated rows.
    assert all(r["engagement_id"] == eng["id"] for r in recs)
