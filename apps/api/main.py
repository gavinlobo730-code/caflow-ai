from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routers import clients, compliance, documents, assistant, insights, tasks, workflows, reminders, team
from routers import accounting, compliance_records

load_dotenv()

app = FastAPI(title="CAflow AI API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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


@app.get("/")
def root():
    from models.common import api_response
    return api_response(True, {"message": "CAflow AI API v2.0", "docs": "/docs"})
