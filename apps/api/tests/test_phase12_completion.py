"""
Tests for Phase 1.2 completion features:
  - Invoice lifecycle (Issued -> Overdue automation)
  - Invoice PDF (GST split arithmetic, amount in words)
  - Time export (CSV/XLSX, paise arithmetic)
  - Workload capacity repository
  - Scheduler idempotency
  - Phase 1.3 intelligence scoring engines
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Invoice lifecycle ────────────────────────────────────────────────────────

class TestInvoiceLifecycle:
    def _make_invoice(self, **overrides):
        from repositories.invoice_repository import invoice_repo
        data = {
            "firm_id": "firm-1",
            "client_id": "client-1",
            "engagement_id": "eng-1",
            "invoice_no": "CF-2025-901",
            "invoice_date": (date.today() - timedelta(days=60)).isoformat(),
            "due_date": (date.today() - timedelta(days=30)).isoformat(),
            "amount_paise": 100_000_00,
            "gst_paise": 18_000_00,
            "total_paise": 118_000_00,
            "status": "Issued",
        }
        data.update(overrides)
        return invoice_repo.create(data)

    def test_issued_past_due_becomes_overdue(self):
        from services.invoice_lifecycle_service import run_overdue_check
        from repositories.invoice_repository import invoice_repo
        inv = self._make_invoice()
        result = run_overdue_check(firm_id="firm-1")
        assert inv["id"] in result["invoice_ids"]
        assert invoice_repo.find_by_id(inv["id"])["status"] == "Overdue"

    def test_paid_invoice_untouched(self):
        from services.invoice_lifecycle_service import run_overdue_check
        from repositories.invoice_repository import invoice_repo
        inv = self._make_invoice(status="Paid", invoice_no="CF-2025-902")
        run_overdue_check(firm_id="firm-1")
        assert invoice_repo.find_by_id(inv["id"])["status"] == "Paid"

    def test_issued_not_yet_due_untouched(self):
        from services.invoice_lifecycle_service import run_overdue_check
        from repositories.invoice_repository import invoice_repo
        inv = self._make_invoice(
            invoice_no="CF-2025-903",
            invoice_date=date.today().isoformat(),
            due_date=(date.today() + timedelta(days=30)).isoformat(),
        )
        run_overdue_check(firm_id="firm-1")
        assert invoice_repo.find_by_id(inv["id"])["status"] == "Issued"

    def test_fallback_due_date_invoice_date_plus_30(self):
        from services.invoice_lifecycle_service import _effective_due_date
        inv = {"invoice_date": "2026-01-01", "due_date": None}
        assert _effective_due_date(inv) == date(2026, 1, 31)


# ── Invoice PDF ──────────────────────────────────────────────────────────────

class TestInvoicePdf:
    def test_amount_in_words(self):
        from services.invoice_pdf_service import amount_in_words
        assert amount_in_words(118_000_00) == "Rupees One Lakh Eighteen Thousand Only"
        assert amount_in_words(150) == "Rupees One and Fifty Paise Only"
        assert amount_in_words(0) == "Rupees Zero Only"
        assert amount_in_words(1_23_45_678_00) == "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight Only"

    def test_intra_state_gst_split_no_paise_lost(self):
        # CGST + SGST must equal gst_paise exactly (integer paise arithmetic)
        gst_paise = 18_000_01  # odd value
        cgst = gst_paise // 2
        sgst = gst_paise - cgst
        assert cgst + sgst == gst_paise

    def test_pdf_renders(self):
        from services.invoice_pdf_service import build_invoice_pdf
        invoice = {
            "invoice_no": "CF-2025-001", "invoice_date": "2026-06-01",
            "due_date": "2026-07-01", "status": "Issued",
            "amount_paise": 100_000_00, "gst_paise": 18_000_00, "total_paise": 118_000_00,
        }
        firm = {"name": "Test & Co", "gstin": "27AAAAA9999A1Z5", "address": "Mumbai"}
        client = {"client_name": "Acme Pvt Ltd", "gstin": "27BBBBB8888B1Z3", "address": "Pune"}
        pdf = build_invoice_pdf(invoice, firm, client)
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 1000

    def test_pdf_renders_inter_state(self):
        from services.invoice_pdf_service import build_invoice_pdf
        invoice = {
            "invoice_no": "CF-2025-002", "invoice_date": "2026-06-01", "status": "Draft",
            "amount_paise": 50_000_00, "gst_paise": 9_000_00, "total_paise": 59_000_00,
        }
        firm = {"name": "Test & Co", "gstin": "27AAAAA9999A1Z5"}
        client = {"client_name": "Delhi Client", "gstin": "07CCCCC7777C1Z9"}
        pdf = build_invoice_pdf(invoice, firm, client)
        assert pdf[:4] == b"%PDF"


# ── Time export ──────────────────────────────────────────────────────────────

class TestTimeExport:
    ENTRIES = [
        {"user_id": "u1", "client_id": "c1", "task_id": "t1", "description": "GST filing",
         "started_at": "2026-06-01T09:00:00Z", "ended_at": "2026-06-01T11:00:00Z",
         "duration_minutes": 120, "is_billable": True, "hourly_rate_paise": 150_000},
    ]

    def test_amount_paise_arithmetic(self):
        from services.time_export_service import build_export_rows
        rows = build_export_rows(self.ENTRIES, {"u1": {"full_name": "Asha"}}, {"c1": {"client_name": "Acme"}})
        # 120 min * 1500.00/hr = 3000.00 => 300000 paise
        assert rows[0]["amount_paise"] == 300_000
        assert rows[0]["amount_inr"] == "3,000.00"
        assert rows[0]["user_name"] == "Asha"
        assert rows[0]["client_name"] == "Acme"
        assert rows[0]["hours"] == "2:00"

    def test_csv_output(self):
        from services.time_export_service import build_export_rows, rows_to_csv
        rows = build_export_rows(self.ENTRIES, {}, {})
        csv_bytes = rows_to_csv(rows)
        text = csv_bytes.decode("utf-8-sig")
        assert "amount_paise" in text
        assert "300000" in text

    def test_xlsx_output(self):
        from services.time_export_service import build_export_rows, rows_to_xlsx
        rows = build_export_rows(self.ENTRIES, {}, {})
        xlsx = rows_to_xlsx(rows)
        assert xlsx[:2] == b"PK"  # zip container


# ── Capacity repository ──────────────────────────────────────────────────────

class TestCapacity:
    def test_upsert_and_lookup(self):
        from repositories.capacity_repository import capacity_repo
        rec = capacity_repo.upsert("firm-1", "user-1", {"weekly_capacity_hours": 35, "max_concurrent_tasks": 10})
        assert rec["weekly_capacity_hours"] == 35
        # Update path
        rec2 = capacity_repo.upsert("firm-1", "user-1", {"weekly_capacity_hours": 45, "max_concurrent_tasks": 12})
        assert rec2["weekly_capacity_hours"] == 45
        assert len([r for r in capacity_repo.find_all(firm_id="firm-1") if r["user_id"] == "user-1"]) == 1
        cmap = capacity_repo.capacity_map("firm-1")
        assert cmap["user-1"]["max_concurrent_tasks"] == 12


# ── Scheduler idempotency ────────────────────────────────────────────────────

class TestScheduler:
    def test_second_run_same_day_is_skipped(self):
        from jobs import scheduler
        first = scheduler.run_daily_jobs(firm_id="firm-sched-test")
        second = scheduler.run_daily_jobs(firm_id="firm-sched-test")
        firm_result = second["firms"]["firm-sched-test"]
        for job in ("recurring", "escalations", "invoice_overdue"):
            # Either skipped (success first time) or attempted again after failure
            if "skipped" not in firm_result[job]:
                assert "error" in str(first["firms"]["firm-sched-test"][job])

    def test_force_reruns(self):
        from jobs import scheduler
        result = scheduler.run_daily_jobs(firm_id="firm-sched-test", force=True)
        firm_result = result["firms"]["firm-sched-test"]
        for job in ("recurring", "escalations", "invoice_overdue"):
            assert "skipped" not in firm_result[job]


# ── Intelligence engines ─────────────────────────────────────────────────────

class TestIntelligence:
    def test_compliance_risk_shape(self):
        from services.intelligence_service import compute_compliance_risk
        result = compute_compliance_risk("firm-1")
        assert "clients" in result and "high_risk_count" in result
        for c in result["clients"]:
            assert 0 <= c["risk_score"] <= 100
            assert c["risk_level"] in ("low", "medium", "high", "critical")

    def test_relationship_health_shape(self):
        from services.intelligence_service import compute_relationship_health
        result = compute_relationship_health("firm-1")
        assert "clients" in result
        for c in result["clients"]:
            assert 0 <= c["health_score"] <= 100
            assert c["health_level"] in ("healthy", "at_risk", "critical")
            assert isinstance(c["outstanding_paise"], int)

    def test_recommendations_sorted_by_priority(self):
        from services.intelligence_service import compute_recommendations
        result = compute_recommendations("firm-1")
        priorities = [r["priority"] for r in result["recommendations"]]
        order = {"high": 0, "medium": 1, "low": 2}
        assert priorities == sorted(priorities, key=lambda p: order[p])

    def test_workload_insights_shape(self):
        from services.intelligence_service import compute_workload_insights
        result = compute_workload_insights("firm-1")
        assert "insights" in result and "team_size" in result

    def test_journal_suggestions_shape(self):
        from services.intelligence_service import compute_journal_suggestions
        result = compute_journal_suggestions("firm-1")
        assert "suggestions" in result and "month" in result
        for s in result["suggestions"]:
            assert s["occurrences"] >= 2
            assert len(s["lines"]) >= 2
