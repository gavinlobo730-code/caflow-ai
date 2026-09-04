from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from core.exceptions import PermissionDeniedError, unhandled_failure

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
        # Performance tracing OFF. This is an error-reporting install, not an
        # APM one: what it exists to surface is capture_posting_failure() —
        # swallowed exceptions in fail-soft financial-posting code, the class
        # of bug that lost five sales invoices' COGS journals for weeks (task
        # #244). At 1.0 every request became a transaction, and the scheduler
        # alone now ticks once a minute — roughly 43k transactions a month
        # before a single user request, against a free-tier allowance of about
        # 10k. Exhausting the quota makes Sentry DROP events, including the
        # errors this is here for, so a sample rate meant to buy insight
        # silently buys blindness instead. Raise it deliberately, with a paid
        # plan, if anyone actually wants latency data.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        # No request bodies, headers or user records. The posting-failure tags
        # set in core/observability.py are the ONLY app data that reaches
        # Sentry, and they are chosen explicitly there — this flag does not
        # govern them.
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

from core.urls import default_allowed_origins

_ALLOWED_ORIGINS = _parse_origins(
    os.environ.get("ALLOWED_ORIGINS") or default_allowed_origins()
)
_logger.info("CORS allowed origins: %s", _ALLOWED_ORIGINS)

from routers import clients, compliance, documents, assistant, insights, tasks, reminders, team
from routers import accounting, compliance_records
from routers import currencies  # Multi-Currency Phase 1 (read-only currency master + policy)
from routers import fx_reports  # Multi-Currency Phase 5 (read-only FX reporting)
from routers import risks, ai_insights, automation, notifications, ai_copilot
from routers import gst, tds, income_tax
from routers import task_templates, task_extras, task_recurring
from routers import time_tracking, workload, analytics, engagements, invoices
from routers import reports  # unified transaction feed for /reports + /client-portal
from routers import intelligence
from routers import scheduler_status, audit, onboarding, reconciliation
from routers import search
from routers import dsc  # H6: DSC (Digital Signature Certificate) backend
from routers import assignments
from routers import approvals
from routers import identity
from routers import customers, vendors, sales_invoices, receipts, credit_notes, customer_statements, debit_notes
from routers import sales_debit_notes, purchase_credit_notes  # CGST §34(3) increase-side correction notes
from routers import hsn  # HSN/SAC smart lookup (search firm_hsn_library merged with firm history)
from routers import service_catalogue  # Product & Service master (Batch 6; goods+services)
from routers import inventory  # Stock register + per-item ledger (migration 188)
from routers import firm_hsn_library  # Firm-owned, CA-curated HSN/SAC library (HSN/SAC redesign)
from routers import firm_hsn_rate_history  # Per-firm rate history, mechanism only (Decision D)
from routers import recurring_invoices
from routers import compliance_ops
from routers import purchase_bills, purchase_payments, document_intelligence_v1
from routers import party_credits
from routers import gst_workspace, tds_workspace, mca_workspace, document_intelligence_v2
from routers import payroll, fixed_assets, banking
from routers import timeline
from routers import engagement_letters
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
from routers import portal_access, portal_self, portal_data
# Phase 4.6 — Online Payments (links + public gateway webhook)
from routers import payments

app = FastAPI(title="PracticeSync AI API", version="2.0.0")


def _failure_response(request: Request, exc: Exception) -> JSONResponse:
    """The body both catch-alls return.

    WHY THIS IS NOT ALWAYS "Internal server error"
        core.exceptions.document_failure_detail turns a database refusal into a
        sentence a CA can act on, and FIVE routers call it. Everywhere else the
        refusal fell through to here and became 500 "Internal server error",
        with the sentence naming what was wrong written to a log the CA cannot
        read. Walking a client with foreign suppliers through a year hit that
        on an engagement: a CHECK constraint refused the row, and the CA was
        told the server had a problem.

        Nothing about a refused CHECK is internal, and 500 says "this might
        work next time" about a request that never can.

    unhandled_failure speaks only where the exception carries a SQLSTATE it
    recognises and returns None otherwise — so a KeyError, a timeout or a bug
    still gets "Internal server error", which for those is the honest answer.
    The exception is logged either way: the CA gets a sentence, support still
    gets the traceback.
    """
    _logger.exception("Unhandled exception for %s %s", request.method, request.url)
    spoken = None
    try:
        spoken = unhandled_failure(exc)
    except Exception:                                        # noqa: BLE001
        # This runs while reporting a failure and must never become a second
        # one. Losing the better wording is survivable; losing the response
        # is not.
        _logger.exception("unhandled_failure raised while classifying")
    status, message = spoken if spoken else (500, "Internal server error")
    return JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": message},
    )


# Middleware ordering (Starlette applies the LAST-added as the OUTERMOST):
#   _carry_user_token  ->  CORSMiddleware  ->  _errors_with_cors  ->  routes
# _errors_with_cors is INNERMOST, so any unhandled exception it converts to a
# JSONResponse travels back OUT through CORSMiddleware and carries the CORS
# headers. This matters because FastAPI's built-in catch-all `Exception` handler
# runs in Starlette's ServerErrorMiddleware, which sits OUTSIDE CORS — a raw 500
# there reaches the browser with no Access-Control-Allow-Origin header and shows
# up as an opaque "Failed to fetch" instead of a readable error.
@app.middleware("http")
async def _errors_with_cors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:                                 # noqa: BLE001
        return _failure_response(request, exc)


# `expose_headers` is NOT cosmetic. A browser lets script read only the seven
# CORS-safelisted response headers unless the server names the others here, and
# the web app is on Cloudflare Pages while this API is on Render — every request
# is cross-origin. So `Content-Disposition` was invisible to `lib/api`'s
# downloadFile across all twelve download endpoints: it reads the header for the
# filename, never found it, and silently used its own fallback. That is why a
# downloaded payslip arrived named for the month rather than the person.
# `X-Payslip-Problems` is the bulk-payslip zip saying which employees it could
# not render; unreadable, it would be the same as not sending it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Payslip-Problems"],
)


@app.middleware("http")
async def _carry_user_token(request: Request, call_next):
    """M6 JWT cutover: stash the caller's bearer token for the request so the
    request-scoped Supabase client (get_supabase) can run as the end user when
    USE_USER_JWT is enabled. No-op when the header is absent (background jobs)."""
    from core.supabase_client import set_request_token, reset_request_token
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    token = auth[7:].strip() if auth and auth[:7].lower() == "bearer " else None
    handle = set_request_token(token)
    try:
        return await call_next(request)
    finally:
        reset_request_token(handle)


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
    return _failure_response(request, exc)

# Amendment v1.1 Batch 2.1 — Guardrail G1 (by-id): client-scoped routers reject
# non-Partner access to the internal practice client (client_id in path/query).
# Applied at include time (the only reliable mechanism — router.dependencies
# post-hoc does not apply to already-decorated routes). Portal is excluded
# (separate auth audience); firm-level routers are excluded (no client_id surface).
from services.internal_client_service import require_client_access
_CLIENT_GUARD = [Depends(require_client_access)]

# M6 MFA enforcement: sensitive firm-administration routers require an aal2
# (MFA-satisfied) token for MFA-required roles when REQUIRE_MFA is enabled.
# No-op pass-through while the flag is off, so it ships dark.
from core.auth import mfa_guard
_MFA_GUARD = [Depends(mfa_guard)]

app.include_router(clients.router, dependencies=_CLIENT_GUARD)
app.include_router(compliance.router, dependencies=_CLIENT_GUARD)
app.include_router(documents.router, dependencies=_CLIENT_GUARD)
app.include_router(assistant.router)
app.include_router(insights.router, dependencies=_CLIENT_GUARD)
app.include_router(tasks.router, dependencies=_CLIENT_GUARD)
# The legacy Phase-2 workflows router was DELETED in R2.7 (audit F11): its
# GET /{workflow_id} catch-all shadowed every single-segment GET on the
# /api/workflows prefix (/templates, /instances, /approvals, /schedules,
# /analytics, /failures, /executions all 404'd), and all three of its
# endpoints returned hardcoded, never-persisted data with zero frontend
# callers. The real engine is workflow_builder_router (registered below).
app.include_router(reminders.router, dependencies=_CLIENT_GUARD)
app.include_router(team.router)
app.include_router(accounting.router, dependencies=_CLIENT_GUARD)
# Multi-Currency Phase 1 — read-only currency master + policy resolution. The
# guard is a no-op for the global master list (no client_id) and enforces
# client-assignment scope for the /policy route (which carries client_id).
app.include_router(currencies.router, dependencies=_CLIENT_GUARD)
app.include_router(fx_reports.router, dependencies=_CLIENT_GUARD)
app.include_router(compliance_records.router, dependencies=_CLIENT_GUARD)
# routers/document_intelligence.py (unversioned /api/document-intelligence) is
# RETIRED as of the R2.8 fix phase (audit F19): it's a 4th, undisclosed
# extraction generation serving hardcoded fabricated data (fake confidence
# scores, fake GSTINs/TDS figures) verbatim via GET /{doc_id}/extraction —
# exactly the class of fabrication R2.8 eliminated in v1/v2. It had zero
# frontend callers and its demo doc-NNN IDs never collide with real
# (UUID-keyed) documents, so unmounting it is a no-op for real traffic.
# document-intelligence-v1 / document-intelligence-v2 are the real,
# audited replacements — see routers/document_intelligence_v1.py and
# routers/document_intelligence_v2.py.
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
app.include_router(reports.router, dependencies=_CLIENT_GUARD)
app.include_router(engagements.router, dependencies=_CLIENT_GUARD)
app.include_router(engagement_letters.router, dependencies=_CLIENT_GUARD)
app.include_router(invoices.router, dependencies=_CLIENT_GUARD)
app.include_router(intelligence.router, dependencies=_CLIENT_GUARD)
app.include_router(scheduler_status.router)
app.include_router(audit.router)
# task #244: "Verify Books" — Partner-only, no _CLIENT_GUARD (client_id lives
# in the request body/query per endpoint, not a uniform path param — each
# handler calls assert_client_access itself, same posture as audit.router above).
app.include_router(reconciliation.router)
app.include_router(onboarding.router)
app.include_router(search.router)  # M2: authorization-scoped global search
# H6: DSC tracker — firm-level settings resource (no client_id surface), so NO _CLIENT_GUARD
app.include_router(dsc.router)
app.include_router(assignments.router, dependencies=_MFA_GUARD)  # M3: client-assignment administration
app.include_router(approvals.router)  # M4: governance approval workflows; MFA enforced per-action (approve/reject) not on read endpoints
app.include_router(identity.router, dependencies=_MFA_GUARD)  # M6: identity administration (audited, server-side)
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
app.include_router(hsn.router, dependencies=_CLIENT_GUARD)
app.include_router(service_catalogue.router, dependencies=_CLIENT_GUARD)
app.include_router(inventory.router, dependencies=_CLIENT_GUARD)
app.include_router(firm_hsn_library.router, dependencies=_CLIENT_GUARD)
app.include_router(firm_hsn_rate_history.router, dependencies=_CLIENT_GUARD)
app.include_router(receipts.router, dependencies=_CLIENT_GUARD)
app.include_router(credit_notes.router, dependencies=_CLIENT_GUARD)
app.include_router(debit_notes.router, dependencies=_CLIENT_GUARD)
app.include_router(sales_debit_notes.router, dependencies=_CLIENT_GUARD)
app.include_router(purchase_credit_notes.router, dependencies=_CLIENT_GUARD)
app.include_router(customer_statements.router, dependencies=_CLIENT_GUARD)
app.include_router(recurring_invoices.router, dependencies=_CLIENT_GUARD)
app.include_router(compliance_ops.router, dependencies=_CLIENT_GUARD)
app.include_router(purchase_bills.router, dependencies=_CLIENT_GUARD)
app.include_router(purchase_payments.router, dependencies=_CLIENT_GUARD)
app.include_router(party_credits.router, dependencies=_CLIENT_GUARD)
app.include_router(document_intelligence_v1.router, dependencies=_CLIENT_GUARD)
app.include_router(gst_workspace.router, dependencies=_CLIENT_GUARD)
# Filing-demo walk-throughs (services/filing_demo/) — read-only, portal-
# faithful, cannot transmit. Same client guard as every client-scoped router.
from routers import filing_demo as filing_demo_router  # noqa: E402
app.include_router(filing_demo_router.router, dependencies=_CLIENT_GUARD)
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
# Phase 4.5.1 — portal foundation. Like portal_router, these use a separate auth
# audience (CA rbac for invites; get_current_portal_client for the client surface)
# and are intentionally NOT behind the staff _CLIENT_GUARD.
app.include_router(portal_access.router)
app.include_router(portal_self.router)
# Phase 4.5.2 — client-facing portal data surfaces (invoices, canonical dues,
# statements, reminders, compliance). Client-authenticated; NOT behind _CLIENT_GUARD.
app.include_router(portal_data.router)
# Phase 4.6 — Online Payments. Staff endpoints carry their own accounting rbac;
# the gateway webhook is public (signature-verified). NOT behind _CLIENT_GUARD.
app.include_router(payments.router)
# Public engagement-letter signing — a prospect reviews and e-signs via a
# tokenized link (no login; the unguessable sign_token is the credential).
# Intentionally public, like the hosted payment link. NOT behind _CLIENT_GUARD.
from routers import engagement_sign_public
app.include_router(engagement_sign_public.router)
# Amendment v1.1 — Practice (firm-as-internal-client), Partner-only
from routers.practice import router as practice_router
app.include_router(practice_router, dependencies=_MFA_GUARD)
# Amendment v1.1 Batch 3 — Billing / Revenue Operations, Partner-only
from routers.billing import router as billing_router
app.include_router(billing_router, dependencies=_MFA_GUARD)

# Platform Admin (Super Admin) — ABOVE firms, separate from firm RBAC. Its own
# allowlist-based auth (require_platform_admin); no firm guard applies.
from routers.platform import router as platform_router
app.include_router(platform_router)
# Amendment v1.1 Batch 6 — Knowledge Base + Client Instructions. The client-scoped
# endpoints (/api/clients/{client_id}/...) are gated by require_client_access (G1);
# firm /api/knowledge endpoints carry no client_id so the guard is a no-op there.
from routers.knowledge import router as knowledge_router
app.include_router(knowledge_router, dependencies=_CLIENT_GUARD)

# Firm Branding & Document Customization — firm-level settings (no client_id surface).
# MFA guard applied: branding mutations are irreversible and firm-wide.
from routers.branding import router as branding_router
app.include_router(branding_router)


# Beta hardening (Phase F) — validate configuration at boot so missing env vars are
# visible immediately in the logs rather than surfacing as opaque runtime errors.
try:
    from core.config_validation import validate_config
    validate_config()
except Exception:
    _logger.exception("config validation failed")

# task #244 — boot-time schema-drift guard: fails /health (see below) if a
# migration the deployed code depends on was never applied to this database.
# See core/schema_guard.py's module docstring for the incident this closes.
try:
    from core.schema_guard import run_startup_check
    _SCHEMA_DRIFT = run_startup_check()
except Exception:
    _logger.exception("schema drift check failed")
    _SCHEMA_DRIFT = {"checked": False, "missing": []}

# Phase 10B — Workflow Scheduler (daily jobs + workflow schedule runner)
from jobs.scheduler import start_scheduler, run_due_schedules, log_scheduler_startup_health
start_scheduler()
# H11: emit a clear startup health line so operators see at boot whether the
# scheduler is actually enabled/running (otherwise compliance reminders + recurring
# jobs silently never run). Non-fatal — never blocks app start.
try:
    log_scheduler_startup_health()
except Exception:
    _logger.exception("scheduler startup health check failed")

# task #155: H11 only ever LOGGED the stale state above. Act on it — if this
# process is starting after 06:00 IST and today's jobs have not run, the timer
# fired while the instance was asleep (GitHub's wake cron is best-effort and
# runs late or not at all), and APScheduler will not catch up on its own. Runs
# the outstanding jobs on a background thread; each is idempotent and skipped if
# it already succeeded today. Non-fatal — never blocks app start.
try:
    from jobs.scheduler import run_catchup_if_stale
    run_catchup_if_stale()
except Exception:
    _logger.exception("scheduler catch-up check failed")

# Phase 13 — the AI memory pipeline is job #11 of run_daily_jobs above, not a
# thread started here (task #158). Its old 24-hour sleep loop ran the whole
# pipeline again on every cold start and never once on the nightly schedule it
# advertised. Do not re-add a start_memory_scheduler() call.


@app.get("/")
def root():
    from models.common import api_response
    return api_response(True, {"message": "PracticeSync AI API v2.0", "docs": "/docs"})


@app.get("/health")
def healthcheck():
    from fastapi.responses import JSONResponse
    from models.common import api_response

    # task #244: a deploy whose code depends on a migration that was never
    # applied to this database fails its own health check instead of going
    # live and silently corrupting data — Render's healthCheckPath will not
    # cut traffic over to an unhealthy deploy. See core/schema_guard.py.
    if _SCHEMA_DRIFT.get("missing"):
        return JSONResponse(
            status_code=503,
            content=api_response(
                False,
                {"status": "schema_drift", "missing_columns": _SCHEMA_DRIFT["missing"]},
                "Deployed code depends on database columns that don't exist — a migration "
                "was committed but never applied. See scripts/db/apply_migrations.py.",
            ),
        )
    return api_response(True, {"status": "ok"})
