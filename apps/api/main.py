import os
import logging
import sys
from dotenv import load_dotenv

# load_dotenv first so env vars are available to everything below
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from core.exceptions import PermissionDeniedError

app = FastAPI(title="CAflow AI API", version="2.0.0", redirect_slashes=False)

# CORS must be added before exception handlers and routers so it wraps
# the entire request lifecycle — including error responses.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
logging.getLogger("caflow").info(f"CORS allowed origins: {_ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cors_headers(request: Request) -> dict:
    """Return CORS headers for the request origin if it is in the allowed list."""
    origin = request.headers.get("origin", "")
    if origin in _ALLOWED_ORIGINS or "*" in _ALLOWED_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    return {}


# Exception handlers explicitly inject CORS headers so that error responses
# (401, 403, 422, 500) are never blocked by the browser, even if the
# middleware layer short-circuits before adding them.
@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    return JSONResponse(
        status_code=403,
        content={"success": False, "data": None, "error": str(exc)},
        headers=_cors_headers(request),
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic v2 exc.errors() can include non-JSON-serializable ctx objects (e.g. ValueError instances).
    # Sanitize by converting ctx values to strings before returning.
    def _sanitize(errors: list) -> list:
        out = []
        for err in errors:
            e = dict(err)
            if "ctx" in e:
                e["ctx"] = {k: str(v) for k, v in e["ctx"].items()}
            out.append(e)
        return out

    return JSONResponse(
        status_code=422,
        content={"success": False, "data": None, "error": "Validation error", "details": _sanitize(exc.errors())},
        headers=_cors_headers(request),
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logging.getLogger("caflow").error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": "Internal server error"},
        headers=_cors_headers(request),
    )

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
# Phase 3 — GST/TDS/MCA Workspace + Document Intelligence v2
from routers import gst_workspace, tds_workspace, mca_workspace, document_intelligence_v2
from routers import payroll, fixed_assets, banking
from routers import timeline

app.include_router(clients.router)
app.include_router(compliance.router)
app.include_router(documents.router)
app.include_router(assistant.router)
app.include_router(insights.router)
app.include_router(tasks.router)
app.include_router(task_templates.router)
app.include_router(task_extras.router)
app.include_router(task_recurring.router)
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
app.include_router(time_tracking.router)
app.include_router(workload.router)
app.include_router(analytics.router)
app.include_router(engagements.router)
app.include_router(invoices.router)
app.include_router(intelligence.router)
app.include_router(scheduler_status.router)
app.include_router(audit.router)
app.include_router(onboarding.router)
# Phase 2 — Sales, Purchases, Double-Entry Cycle
app.include_router(customers.router)
app.include_router(vendors.router)
app.include_router(sales_invoices.router)
app.include_router(receipts.router)
app.include_router(credit_notes.router)
app.include_router(purchase_bills.router)
app.include_router(purchase_payments.router)
app.include_router(document_intelligence_v1.router)
# Phase 3
app.include_router(gst_workspace.router)
app.include_router(tds_workspace.router)
app.include_router(mca_workspace.router)
app.include_router(document_intelligence_v2.router)
app.include_router(payroll.router)
app.include_router(fixed_assets.router)
app.include_router(banking.router)
app.include_router(timeline.router)


@app.get("/")
def root():
    from models.common import api_response
    return api_response(True, {"message": "CAflow AI API v2.0", "docs": "/docs"})

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# Daily automation scheduler (recurring tasks, escalations, invoice lifecycle).
# Only runs when ENABLE_SCHEDULER=true — see jobs/scheduler.py.
@app.on_event("startup")
def _start_scheduler():
    from jobs.scheduler import start_scheduler
    start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler():
    from jobs.scheduler import stop_scheduler
    stop_scheduler()
