from fastapi import FastAPI, Request
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
from routers import customers, vendors, sales_invoices, receipts, credit_notes
from routers import purchase_bills, purchase_payments, document_intelligence_v1
from routers import gst_workspace, tds_workspace, mca_workspace, document_intelligence_v2
from routers import payroll, fixed_assets, banking
from routers import timeline
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

app.include_router(clients.router)
app.include_router(compliance.router)
app.include_router(documents.router)
app.include_router(assistant.router)
app.include_router(insights.router)
app.include_router(tasks.router)
app.include_router(workflows.router)
app.include_router(reminders.router)
app.include_router(team.router)
app.include_router(accounting.router)
app.include_router(compliance_records.router)
app.include_router(document_intelligence.router)
app.include_router(risks.router)
app.include_router(ai_insights.router)
app.include_router(automation.router)
app.include_router(notifications.router)
app.include_router(ai_copilot.router)
app.include_router(gst.router)
app.include_router(tds.router)
app.include_router(income_tax.router)
app.include_router(task_templates.router)
app.include_router(task_extras.router)
app.include_router(task_recurring.router)
app.include_router(time_tracking.router)
app.include_router(workload.router)
app.include_router(analytics.router)
app.include_router(engagements.router)
app.include_router(invoices.router)
app.include_router(intelligence.router)
app.include_router(scheduler_status.router)
app.include_router(audit.router)
app.include_router(onboarding.router)
app.include_router(customers.router)
app.include_router(vendors.router)
app.include_router(sales_invoices.router)
app.include_router(receipts.router)
app.include_router(credit_notes.router)
app.include_router(purchase_bills.router)
app.include_router(purchase_payments.router)
app.include_router(document_intelligence_v1.router)
app.include_router(gst_workspace.router)
app.include_router(tds_workspace.router)
app.include_router(mca_workspace.router)
app.include_router(document_intelligence_v2.router)
app.include_router(payroll.router)
app.include_router(fixed_assets.router)
app.include_router(banking.router)
app.include_router(timeline.router)
# Phase 6 — Year End routers
app.include_router(year_end.router, prefix="/api")
app.include_router(year_end_checklist.router, prefix="/api")
app.include_router(year_end_adjustments.router, prefix="/api")
app.include_router(year_end_statements.router, prefix="/api")
app.include_router(year_end_notes.router, prefix="/api")
app.include_router(year_end_reviews.router, prefix="/api")
app.include_router(year_end_exports.router, prefix="/api")
app.include_router(year_end_mappings.router, prefix="/api")
# Phase 7 — Unified Intelligence Layer
app.include_router(lifecycle_router)
app.include_router(relationships_router)
app.include_router(health_router)
# Phase 10 — Workflow Automation Engine
app.include_router(workflow_builder_router)
# Phase 11 — AI Copilot Platform
app.include_router(ai_copilot_v2_router)
# Phase 13 — AI Memory & Intelligence
app.include_router(memory_intelligence_router)
# Client Portal
app.include_router(portal_router)
# Amendment v1.1 — Practice (firm-as-internal-client), Partner-only
from routers.practice import router as practice_router
app.include_router(practice_router)


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
