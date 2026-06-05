from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from dotenv import load_dotenv
from core.exceptions import PermissionDeniedError
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

from routers import clients, compliance, documents, assistant, insights, tasks, workflows, reminders, team
from routers import accounting, compliance_records
from routers import document_intelligence, risks, ai_insights, automation, notifications, ai_copilot
from routers import gst
from routers import tds
from routers import income_tax

load_dotenv()

app = FastAPI(title="CAflow AI API", version="2.0.0")

import os
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    return JSONResponse(
        status_code=403,
        content={"success": False, "data": None, "error": str(exc)},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"success": False, "data": None, "error": "Validation error", "details": exc.errors()},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logging.getLogger("caflow").error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/")
def root():
    from models.common import api_response
    return api_response(True, {"message": "CAflow AI API v2.0", "docs": "/docs"})

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
