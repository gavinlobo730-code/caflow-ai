from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
from dotenv import load_dotenv
import anthropic
import os
from datetime import date, timedelta

load_dotenv()

app = FastAPI(title="CAflow AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MOCK_CLIENTS = [
    {
        "id": "1",
        "name": "Sharma Enterprises",
        "gstin": "27AABCS1429B1ZB",
        "pan": "AABCS1429B",
        "contact": "+91 98765 43210",
        "email": "sharma@sharmaenterprises.in",
        "compliance_summary": {
            "gstr1_status": "pending",
            "gstr1_due_date": (date.today() + timedelta(days=3)).isoformat(),
            "gstr3b_status": "filed",
            "gstr3b_due_date": (date.today() + timedelta(days=18)).isoformat(),
        }
    },
    {
        "id": "2",
        "name": "Patel & Sons",
        "gstin": "27AAPCS4229B1ZC",
        "pan": "AAPCS4229B",
        "contact": "+91 98765 43211",
        "email": "patel@patelandsons.in",
        "compliance_summary": {
            "gstr1_status": "filed",
            "gstr1_due_date": (date.today() - timedelta(days=5)).isoformat(),
            "gstr3b_status": "pending",
            "gstr3b_due_date": (date.today() + timedelta(days=8)).isoformat(),
        }
    },
    {
        "id": "3",
        "name": "Mehta Consulting",
        "gstin": "27AACCS7829B1ZD",
        "pan": "AACCS7829B",
        "contact": "+91 98765 43212",
        "email": "mehta@mehtaconsulting.in",
        "compliance_summary": {
            "gstr1_status": "overdue",
            "gstr1_due_date": (date.today() - timedelta(days=2)).isoformat(),
            "gstr3b_status": "overdue",
            "gstr3b_due_date": (date.today() - timedelta(days=10)).isoformat(),
        }
    },
    {
        "id": "4",
        "name": "Desai Traders",
        "gstin": "27AADCS9929B1ZE",
        "pan": "AADCS9929B",
        "contact": "+91 98765 43213",
        "email": "desai@desaitraders.in",
        "compliance_summary": {
            "gstr1_status": "filed",
            "gstr1_due_date": (date.today() - timedelta(days=15)).isoformat(),
            "gstr3b_status": "filed",
            "gstr3b_due_date": (date.today() - timedelta(days=10)).isoformat(),
        }
    },
    {
        "id": "5",
        "name": "Joshi Textiles",
        "gstin": "27AAJCS3329B1ZF",
        "pan": "AAJCS3329B",
        "contact": "+91 98765 43214",
        "email": "joshi@joshitextiles.in",
        "compliance_summary": {
            "gstr1_status": "filed",
            "gstr1_due_date": (date.today() - timedelta(days=5)).isoformat(),
            "gstr3b_status": "filed",
            "gstr3b_due_date": (date.today() - timedelta(days=5)).isoformat(),
            "itr_status": "pending",
            "itr_due_date": (date.today() + timedelta(days=12)).isoformat(),
        }
    },
]


def api_response(success: bool, data: Any = None, error: Optional[str] = None) -> dict:
    return {"success": success, "data": data, "error": error}


@app.get("/")
def root():
    return api_response(True, {"message": "CAflow AI API running"})


@app.post("/api/parse-document")
async def parse_document(
    file: UploadFile = File(...),
    document_type: str = Form(...)
):
    # TODO: Replace mock with Claude API vision call
    if document_type not in ("form16", "gst_invoice"):
        raise HTTPException(status_code=400, detail="document_type must be 'form16' or 'gst_invoice'")

    if document_type == "form16":
        fields = {
            "employee_name": "Rajesh Kumar Sharma",
            "pan": "ABCRS1234D",
            "employer_name": "TechCorp India Pvt Ltd",
            "employer_tan": "MUMB12345C",
            "assessment_year": "2024-25",
            "financial_year": "2023-24",
            "gross_salary_paise": 120000000,
            "gross_salary_display": "₹12,00,000",
            "total_tds_paise": 18500000,
            "total_tds_display": "₹1,85,000",
            "standard_deduction_paise": 5000000,
            "standard_deduction_display": "₹50,000",
            "net_taxable_income_paise": 115000000,
            "net_taxable_income_display": "₹11,50,000",
        }
    else:
        fields = {
            "supplier_name": "Hindustan Goods Suppliers Pvt Ltd",
            "gstin": "27AABCH1234B1ZA",
            "invoice_number": "HGS/2024-25/001234",
            "invoice_date": "2024-03-15",
            "taxable_value_paise": 10000000,
            "taxable_value_display": "₹1,00,000",
            "cgst_rate": "9%",
            "cgst_paise": 900000,
            "cgst_display": "₹9,000",
            "sgst_rate": "9%",
            "sgst_paise": 900000,
            "sgst_display": "₹9,000",
            "igst_rate": "0%",
            "igst_paise": 0,
            "igst_display": "₹0",
            "total_amount_paise": 11800000,
            "total_amount_display": "₹1,18,000",
            "hsn_code": "8471",
            "place_of_supply": "Maharashtra (27)",
        }

    return api_response(True, {"fields": fields})


class ConversationMessage(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    question: str
    conversation_history: Optional[List[ConversationMessage]] = []


@app.post("/api/assistant")
async def assistant(request: AssistantRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are a GST and Income Tax expert assistant for Indian Chartered Accountants. "
        "Answer questions accurately citing the relevant section of the CGST Act 2017, "
        "IGST Act, or Income Tax Act 1961. Always end your answer with: "
        "Source: [Act name], Section [number]. "
        "If unsure, say so — never guess on tax matters."
    )

    messages = [
        {"role": m.role, "content": m.content}
        for m in (request.conversation_history or [])
    ]
    messages.append({"role": "user", "content": request.question})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    full_answer = response.content[0].text
    source = ""
    if "Source:" in full_answer:
        parts = full_answer.rsplit("Source:", 1)
        answer = parts[0].strip()
        source = "Source:" + parts[1].strip()
    else:
        answer = full_answer

    return api_response(True, {"answer": answer, "source": source})


@app.get("/api/compliance-calendar")
def compliance_calendar():
    today = date.today()
    events = [
        {
            "client_name": "Sharma Enterprises",
            "gstin": "27AABCS1429B1ZB",
            "return_type": "GSTR-1",
            "due_date": (today + timedelta(days=3)).isoformat(),
            "status": "pending",
        },
        {
            "client_name": "Patel & Sons",
            "gstin": "27AAPCS4229B1ZC",
            "return_type": "GSTR-3B",
            "due_date": (today + timedelta(days=8)).isoformat(),
            "status": "pending",
        },
        {
            "client_name": "Mehta Consulting",
            "gstin": "27AACCS7829B1ZD",
            "return_type": "GSTR-1",
            "due_date": (today - timedelta(days=2)).isoformat(),
            "status": "overdue",
        },
        {
            "client_name": "Mehta Consulting",
            "gstin": "27AACCS7829B1ZD",
            "return_type": "GSTR-3B",
            "due_date": (today - timedelta(days=10)).isoformat(),
            "status": "overdue",
        },
        {
            "client_name": "Joshi Textiles",
            "gstin": "27AAJCS3329B1ZF",
            "return_type": "ITR",
            "due_date": (today + timedelta(days=12)).isoformat(),
            "status": "pending",
        },
        {
            "client_name": "Desai Traders",
            "gstin": "27AADCS9929B1ZE",
            "return_type": "GSTR-1",
            "due_date": (today - timedelta(days=15)).isoformat(),
            "status": "filed",
        },
        {
            "client_name": "Desai Traders",
            "gstin": "27AADCS9929B1ZE",
            "return_type": "GSTR-3B",
            "due_date": (today - timedelta(days=10)).isoformat(),
            "status": "filed",
        },
    ]
    return api_response(True, {"events": events})


@app.get("/api/clients")
def get_clients():
    return api_response(True, {"clients": MOCK_CLIENTS})
