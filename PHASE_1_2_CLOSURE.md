# Phase 1.2 Closure — Practice Management & Team Scaling

All production blockers identified in the CTO audit are now implemented.

## 1. Recurring Task Scheduler
- `jobs/scheduler.py` — APScheduler daily run at 06:00 IST (env-gated `ENABLE_SCHEDULER=true`),
  started/stopped from FastAPI lifecycle in `main.py`.
- Per firm, per day: recurring task generation (assignment rules applied inside
  `recurring_task_service`), escalation rules, invoice overdue transitions.
- Idempotency: `scheduler_runs` table logs every job; jobs already successful
  today are skipped. Recurring generation is additionally idempotent via
  `last_generated_at`.
- External-cron alternative: `POST /api/tasks/trigger-scheduler-run` (idempotent,
  `?force=true` to re-run) — use this with multi-worker gunicorn deployments.

## 2. Invoice PDF Generation
- `services/invoice_pdf_service.py` — GST tax invoice per Rule 46, CGST Rules 2017:
  firm name/address/GSTIN/PAN, client details, invoice no/date/due date,
  SAC 998211, taxable value, CGST+SGST (intra-state) or IGST (inter-state) split
  by GSTIN state codes, amount in words (Indian system), reverse-charge declaration.
- `GET /api/invoices/{id}/pdf` — download endpoint (invoice.read RBAC, firm-scoped).
- Integer paise throughout; intra-state split loses zero paise (CGST = floor half,
  SGST = remainder).

## 3. Automatic Invoice Lifecycle
- `services/invoice_lifecycle_service.py` — Issued invoices past due_date →
  Overdue; fallback due date = invoice_date + 30 days; Partner notified.
- Generated invoices now carry `due_date` (invoice_date + 30-day credit period).
- `POST /api/invoices/run-overdue-check` + daily scheduler integration.
- Migration `006_phase12_completion.sql` adds `fee_invoices.due_date` + index.

## 4. Time Tracking Export
- `services/time_export_service.py` — CSV (UTF-8 BOM for Excel) and XLSX export.
- `GET /api/time-entries/export?fmt=csv|xlsx&user_id=&client_id=&date_from=&date_to=`
  (time_entry.report RBAC — Manager+).
- Amounts computed as integer paise (`minutes * rate // 60`); display column derived.

## 5. Task Dependency & Template UX
- Frontend now surfaces task dependencies (blocked-by add/remove) and the
  template library, wired to existing `task_extras` / `task_templates` endpoints.

## 6. Workload Capacity Management
- `user_capacity` table (migration 006): weekly_capacity_hours, max_concurrent_tasks
  per user, unique per firm/user.
- `GET /api/workload/capacity`, `PUT /api/workload/capacity` (workload.write — Manager+).
- `GET /api/workload` now computes utilisation from minutes logged this week vs
  configured capacity (fallback: task count vs max_concurrent_tasks), with
  capacity-aware overload and underutilisation detection.

## Tests
`tests/test_phase12_completion.py` — 19 tests covering invoice lifecycle
transitions, PDF rendering and GST split arithmetic, amount-in-words, time
export paise arithmetic and CSV/XLSX output, capacity upsert, scheduler
idempotency, and intelligence engine score bounds. Full suite: 408+ passing;
the 8 pre-existing failures on main are unchanged.
