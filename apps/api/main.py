from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from core.exceptions import PermissionDeniedError

load_dotenv()

import os
import logging
import sentry_sdk

_logger = logging.getLogger("caflow.main")
logging.basicConfig(level=logging.INFO)

_SENTRY_DSN = os.environ.get("SENTRY_DSN")
if _SENTRY_DSN:
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.environ.get("ENVIRONMENT", "production"),
        traces_sample_rate=1.0,
        send_default_pii=False,
    )

# ── CORS origins — parse before router imports so value is fixed early ─────────
# Handles comma-separated values, accidental newlines, surrounding quotes,
# and trailing slashes that would cause silent origin mismatches.
def _parse_origins(raw: str) -> list[str]:
    origins = []
    for part in raw.replace("\n", ",").replace(";", ",").split(","):
        o = part.strip().strip('"').strip("'").rstrip("/")
        if o:
            origins.append(o)
    return origins

_ALLOWED_ORIGINS = _parse_origins(
    os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://caflow-ai.pages.dev",
    )
)
_logger.info("CORS allowed origins: %s", _ALLOWED_ORIGINS)

from routers import clients, compliance, documents, assistant, insights, tasks, workflows, reminders, team
from routers import accounting, compliance_records
from routers import document_intelligence, risks, ai_insights, automation, notifications, ai_copilot
from routers import gst, tds, income_tax
from routers import task_templates, task_extras, task_recurring
from routers import time_tracking, workload, analytics, engagements, invoices
from routers import intelligence
from routers import scheduler_status, audit, onboarding
from routers import search
from routers import assignments
from routers import approvals
from routers import identity
from routers import customers, vendors, sales_invoices, receipts, credit_notes
from routers import purchase_bills, purchase_payments, document_intelligence_v1
from routers import gst_workspace, tds_workspace, mca_workspace, document_intelligence_v2
from routers import payroll, fixed_assets, banking
from routers import timeline
# Phase 14 routers that existed but were never mounted (production-readiness fix)
from routers import einvoice, eway_bill, tally_migration, xbrl_engine, itr_workspace, form_26as, gst_portal
# Phase 6 — Year End
from routers import year_end, year_end_checklist, year_end_adjustments
from routers import year_end_statements, year_end_notes, year_end_reviews
from routers import year_end_exports, year_end_mappings
# Phase 7 — Unified Intelligence Layer
from routers.lifecycle import router as lifecycle_router
from routers.relationships import router as relationships_router
from routers.health import router as health_router
# Phase 10 — Workflow Automation Engine
from routers.workflow_builder import router as workflow_builder_router
# Phase 11 — AI Copilot Platform
from routers.ai_copilot_v2 import router as ai_copilot_v2_router
# Phase 13 — AI Memory & Intelligence
from routers.memory_intelligence import router as memory_intelligence_router
# Client Portal
from routers.portal import router as portal_router

app = FastAPI(title="PracticeSync AI API", version="2.0.0")

# CORSMiddleware MUST be registered first so it wraps all response paths,
# including error responses produced by exception handlers below.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    return JSONResponse(
        status_code=403,
        content={"success": False, "data": None, "error": str(exc)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Catch-all: ensures unhandled 500s are returned as JSONResponse so they
    # travel back through CORSMiddleware and carry the CORS header.
    _logger.exception("Unhandled exception for %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": "Internal server error"},
    )

# Amendment v1.1 Batch 2.1 — Guardrail G1 (by-id): client-scoped routers reject
# non-Partner access to the internal practice client (client_id in path/query).
# Applied at include time (the only reliable mechanism — router.dependencies
# post-hoc does not apply to already-decorated routes). Portal is excluded
# (separate auth audience); firm-level routers are excluded (no client_id surface).
from services.internal_client_service import require_client_access
_CLIENT_GUARD = [Depends(require_client_access)]

app.include_router(clients.router, dependencies=_CLIENT_GUARD)
app.include_router(compliance.router, dependencies=_CLIENT_GUARD)
app.include_router(documents.router, dependencies=_CLIENT_GUARD)
app.include_router(assistant.router)
app.include_router(insights.router, dependencies=_CLIENT_GUARD)
app.include_router(tasks.router, dependencies=_CLIENT_GUARD)
app.include_router(workflows.router, dependencies=_CLIENT_GUARD)
app.include_router(reminders.router, dependencies=_CLIENT_GUARD)
app.include_router(team.router)
app.include_router(accounting.router, dependencies=_CLIENT_GUARD)
app.include_router(compliance_records.router, dependencies=_CLIENT_GUARD)
app.include_router(document_intelligence.router, dependencies=_CLIENT_GUARD)
app.include_router(risks.router, dependencies=_CLIENT_GUARD)
app.include_router(ai_insights.router, dependencies=_CLIENT_GUARD)
app.include_router(automation.router)
app.include_router(notifications.router)
app.include_router(ai_copilot.router, dependencies=_CLIENT_GUARD)
app.include_router(gst.router, dependencies=_CLIENT_GUARD)
app.include_router(tds.router, dependencies=_CLIENT_GUARD)
app.include_router(income_tax.router, dependencies=_CLIENT_GUARD)
app.include_router(task_templates.router, dependencies=_CLIENT_GUARD)
app.include_router(task_extras.router)
app.include_router(task_recurring.router, dependencies=_CLIENT_GUARD)
app.include_router(time_tracking.router, dependencies=_CLIENT_GUARD)
app.include_router(workload.router)
app.include_router(analytics.router, dependencies=_CLIENT_GUARD)
app.include_router(engagements.router, dependencies=_CLIENT_GUARD)
app.include_router(invoices.router, dependencies=_CLIENT_GUARD)
app.include_router(intelligence.router, dependencies=_CLIENT_GUARD)
app.include_router(scheduler_status.router)
app.include_router(audit.router)
app.include_router(onboarding.router)
app.include_router(search.router)  # M2: authorization-scoped global search
app.include_router(assignments.router)  # M3: client-assignment administration
app.include_router(approvals.router)  # M4: governance approval workflows
app.include_router(identity.router)  # M6: identity administration (audited, server-side)
# Phase 14 — Tax/XBRL/integrations routers (previously written but never mounted;
# their frontend pages were dead 404s until now). All client-scoped → guarded.
app.include_router(itr_workspace.router, dependencies=_CLIENT_GUARD)
app.include_router(xbrl_engine.router, dependencies=_CLIENT_GUARD)
app.include_router(form_26as.router, dependencies=_CLIENT_GUARD)
app.include_router(einvoice.router, dependencies=_CLIENT_GUARD)
app.include_router(eway_bill.router, dependencies=_CLIENT_GUARD)
app.include_router(tally_migration.router, dependencies=_CLIENT_GUARD)
app.include_router(gst_portal.router, dependencies=_CLIENT_GUARD)
app.include_router(customers.router, dependencies=_CLIENT_GUARD)
app.include_router(vendors.router, dependencies=_CLIENT_GUARD)
app.include_router(sales_invoices.router, dependencies=_CLIENT_GUARD)
app.include_router(receipts.router, dependencies=_CLIENT_GUARD)
app.include_router(credit_notes.router, dependencies=_CLIENT_GUARD)
app.include_router(purchase_bills.router, dependencies=_CLIENT_GUARD)
app.include_router(purchase_payments.router, dependencies=_CLIENT_GUARD)
app.include_router(document_intelligence_v1.router, dependencies=_CLIENT_GUARD)
app.include_router(gst_workspace.router, dependencies=_CLIENT_GUARD)
app.include_router(tds_workspace.router, dependencies=_CLIENT_GUARD)
app.include_router(mca_workspace.router, dependencies=_CLIENT_GUARD)
app.include_router(document_intelligence_v2.router, dependencies=_CLIENT_GUARD)
app.include_router(payroll.router, dependencies=_CLIENT_GUARD)
app.include_router(fixed_assets.router, dependencies=_CLIENT_GUARD)
app.include_router(banking.router, dependencies=_CLIENT_GUARD)
app.include_router(timeline.router, dependencies=_CLIENT_GUARD)
# Phase 6 — Year End routers (client-scoped reads guarded by G1)
app.include_router(year_end.router, prefix="/api", dependencies=_CLIENT_GUARD)
app.include_router(year_end_checklist.router, prefix="/api")
app.include_router(year_end_adjustments.router, prefix="/api")
app.include_router(year_end_statements.router, prefix="/api")
app.include_router(year_end_notes.router, prefix="/api")
app.include_router(year_end_reviews.router, prefix="/api")
app.include_router(year_end_exports.router, prefix="/api", dependencies=_CLIENT_GUARD)
app.include_router(year_end_mappings.router, prefix="/api")
# Phase 7 — Unified Intelligence Layer
app.include_router(lifecycle_router)
app.include_router(relationships_router, dependencies=_CLIENT_GUARD)
app.include_router(health_router, dependencies=_CLIENT_GUARD)
# Phase 10 — Workflow Automation Engine
app.include_router(workflow_builder_router)
# Phase 11 — AI Copilot Platform
app.include_router(ai_copilot_v2_router, dependencies=_CLIENT_GUARD)
# Phase 13 — AI Memory & Intelligence
app.include_router(memory_intelligence_router, dependencies=_CLIENT_GUARD)
# Client Portal
app.include_router(portal_router)
# Amendment v1.1 — Practice (firm-as-internal-client), Partner-only
from routers.practice import router as practice_router
app.include_router(practice_router)
# Amendment v1.1 Batch 3 — Billing / Revenue Operations, Partner-only
from routers.billing import router as billing_router
app.include_router(billing_router)
# Amendment v1.1 Batch 6 — Knowledge Base + Client Instructions. The client-scoped
# endpoints (/api/clients/{client_id}/...) are gated by require_client_access (G1);
# firm /api/knowledge endpoints carry no client_id so the guard is a no-op there.
from routers.knowledge import router as knowledge_router
app.include_router(knowledge_router, dependencies=_CLIENT_GUARD)


# Phase 10B — Workflow Scheduler (daily jobs + workflow schedule runner)
from jobs.scheduler import start_scheduler, run_due_schedules
start_scheduler()

# Phase 13 — AI Memory Scheduler
from jobs.memory_job import start_memory_scheduler
start_memory_scheduler()


@app.get("/")
def root():
    from models.common import api_response
    return api_response(True, {"message": "PracticeSync AI API v2.0", "docs": "/docs"})


@app.get("/health")
def healthcheck():
    from models.common import api_response
    return api_response(True, {"status": "ok"})
