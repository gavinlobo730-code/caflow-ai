"""
Workflow template engine.
Defines standard CA practice workflows with realistic steps.
"""
from typing import Optional
import uuid
from datetime import datetime, timezone


WORKFLOW_TEMPLATES = [
    {
        "id": "wf-tpl-001",
        "name": "GST Monthly Filing",
        "description": "End-to-end monthly GST compliance workflow covering document collection through filing",
        "compliance_type": "GENERAL",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Collect Sales Invoices", "step_description": "Gather all B2B and B2C sales invoices for the month", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 2, "step_name": "Collect Purchase Invoices", "step_description": "Gather all purchase invoices and verify ITC eligibility", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 3, "step_name": "Reconcile with GSTR-2B", "step_description": "Match purchase data against GSTR-2B auto-populated data. Ref: CGST Act Section 38", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.5},
            {"step_order": 4, "step_name": "Prepare GSTR-1", "step_description": "Enter outward supply details — HSN summary, B2B invoices, B2C summary", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.5},
            {"step_order": 5, "step_name": "CA Review — GSTR-1", "step_description": "CA to review GSTR-1 data before filing. Verify HSN codes and tax rates.", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 6, "step_name": "File GSTR-1", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\nFile GSTR-1 only after explicit CA approval click", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 7, "step_name": "Prepare GSTR-3B", "step_description": "Compute tax liability, ITC utilization, and cash payment required", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 8, "step_name": "CA Review — GSTR-3B", "step_description": "CA to verify tax payable and ITC claimed before filing", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 9, "step_name": "Tax Payment", "step_description": "Generate challan and make GST payment if liability exists. Ref: CGST Act Section 49", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 10, "step_name": "File GSTR-3B", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\nFile GSTR-3B only after explicit CA approval", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
        ],
    },
    {
        "id": "wf-tpl-002",
        "name": "GSTR-1 Filing",
        "description": "Outward supplies return — monthly or quarterly",
        "compliance_type": "GSTR1",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Collect Sales Data", "step_description": "Gather all sales invoices, credit notes, debit notes for the period", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 2, "step_name": "Classify Supplies", "step_description": "Classify into B2B, B2C, exports, exempt, nil-rated. Verify HSN codes.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 3, "step_name": "Data Entry / Upload", "step_description": "Enter invoice-level details or upload JSON/Excel", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.5},
            {"step_order": 4, "step_name": "CA Review", "step_description": "Review HSN summary, tax rates, place of supply. Verify against books.", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 5, "step_name": "File GSTR-1", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.25},
        ],
    },
    {
        "id": "wf-tpl-003",
        "name": "GSTR-3B Filing",
        "description": "Monthly summary return with tax payment",
        "compliance_type": "GSTR3B",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Compute Tax Liability", "step_description": "Calculate output tax from GSTR-1. Verify IGST, CGST, SGST breakup.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 2, "step_name": "Verify ITC", "step_description": "Reconcile eligible ITC against GSTR-2B. Apply Section 17(5) restrictions.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 3, "step_name": "Compute Net Tax Payable", "step_description": "Net liability = Output tax − ITC. Calculate cash payment required.", "required": True, "default_assignee_role": "staff", "estimated_hours": 0.5},
            {"step_order": 4, "step_name": "CA Review", "step_description": "CA to verify all figures before payment and filing", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 5, "step_name": "Make GST Payment", "step_description": "Generate PMT-06 challan and pay via net banking. Ref: CGST Act Section 49.", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 6, "step_name": "File GSTR-3B", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.25},
        ],
    },
    {
        "id": "wf-tpl-004",
        "name": "ITR Filing",
        "description": "Income Tax Return filing workflow for individuals and entities",
        "compliance_type": "ITR",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Collect Documents", "step_description": "Gather Form 16, Form 26AS, AIS, bank statements, investment proofs", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 2, "step_name": "Download AIS / Form 26AS", "step_description": "Download Annual Information Statement and verify TDS credits. Ref: IT Act Section 203AA", "required": True, "default_assignee_role": "staff", "estimated_hours": 0.5},
            {"step_order": 3, "step_name": "Compute Income", "step_description": "Compute income under all 5 heads: Salary, House Property, Business, Capital Gains, Other Sources", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 4, "step_name": "Compute Deductions", "step_description": "Apply Chapter VI-A deductions: 80C, 80D, 80G, 80TTA etc. Verify limits.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 5, "step_name": "Compute Tax Liability", "step_description": "Compute tax under old vs new regime. Recommend optimal regime.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 6, "step_name": "Client Review", "step_description": "Share computation sheet with client for approval. Wait for response.", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 7, "step_name": "Pay Advance Tax / Self-Assessment Tax", "step_description": "If tax payable > ₹10,000, generate Challan 280. Ref: IT Act Section 140A", "required": False, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 8, "step_name": "Prepare ITR", "step_description": "Select correct ITR form. Fill all schedules. Verify prefilled data.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.5},
            {"step_order": 9, "step_name": "CA Review", "step_description": "Final review of ITR before filing. Verify all figures match computation.", "required": True, "default_assignee_role": "manager", "estimated_hours": 1.0},
            {"step_order": 10, "step_name": "File ITR", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\nFile only after explicit client and CA approval", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.25},
            {"step_order": 11, "step_name": "E-Verify ITR", "step_description": "E-verify via Aadhaar OTP or Net Banking within 30 days. Ref: IT Act Section 140", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.25},
        ],
    },
    {
        "id": "wf-tpl-005",
        "name": "TDS Return Filing",
        "description": "Quarterly TDS return (Form 24Q / 26Q)",
        "compliance_type": "TDS26Q",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Collect TDS Data", "step_description": "Gather payment details, PAN of deductees, TDS amounts for the quarter", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 2, "step_name": "Prepare FVU File", "step_description": "Prepare e-TDS return using NSDL FVU software. Validate file.", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.5},
            {"step_order": 3, "step_name": "Verify Challans", "step_description": "Match TDS challans (OLTAS) with deduction details. Ref: IT Act Section 200", "required": True, "default_assignee_role": "staff", "estimated_hours": 1.0},
            {"step_order": 4, "step_name": "CA Review", "step_description": "Review FVU file and deductee details before submission", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 5, "step_name": "File TDS Return", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\nUpload to TRACES / Income Tax portal", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
            {"step_order": 6, "step_name": "Issue Form 16 / 16A", "step_description": "Generate and issue TDS certificates to deductees. Ref: IT Act Section 203", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
        ],
    },
    {
        "id": "wf-tpl-006",
        "name": "Annual GST Return (GSTR-9)",
        "description": "Annual reconciliation and return filing",
        "compliance_type": "GSTR9",
        "is_template": True,
        "steps": [
            {"step_order": 1, "step_name": "Compile Annual Data", "step_description": "Aggregate all monthly GSTR-1 and GSTR-3B data for the full financial year", "required": True, "default_assignee_role": "staff", "estimated_hours": 4.0},
            {"step_order": 2, "step_name": "Annual ITC Reconciliation", "step_description": "Reconcile total ITC claimed in GSTR-3B vs GSTR-2A/2B. Identify reversals.", "required": True, "default_assignee_role": "staff", "estimated_hours": 3.0},
            {"step_order": 3, "step_name": "Turnover Reconciliation", "step_description": "Reconcile GST turnover with books of accounts and financial statements", "required": True, "default_assignee_role": "staff", "estimated_hours": 2.0},
            {"step_order": 4, "step_name": "Prepare GSTR-9", "step_description": "Fill all 19 tables of GSTR-9. Verify HSN summary.", "required": True, "default_assignee_role": "staff", "estimated_hours": 3.0},
            {"step_order": 5, "step_name": "CA Review", "step_description": "Senior CA review of annual return. Cross-check with financials.", "required": True, "default_assignee_role": "owner", "estimated_hours": 2.0},
            {"step_order": 6, "step_name": "File GSTR-9", "step_description": "# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT", "required": True, "default_assignee_role": "manager", "estimated_hours": 0.5},
        ],
    },
]


def get_all_templates() -> list[dict]:
    return WORKFLOW_TEMPLATES


def get_template_by_id(template_id: str) -> dict | None:
    return next((t for t in WORKFLOW_TEMPLATES if t["id"] == template_id), None)


def get_template_by_compliance_type(compliance_type: str) -> dict | None:
    return next((t for t in WORKFLOW_TEMPLATES if t["compliance_type"] == compliance_type), None)


def instantiate_workflow_tasks(
    template_id: str,
    client_id: str,
    assigned_to: str,
    base_due_date: str,
) -> list[dict]:
    """Create a list of task dicts from a workflow template for a specific client."""
    template = get_template_by_id(template_id)
    if not template:
        return []
    tasks = []
    for step in template["steps"]:
        tasks.append({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "workflow_id": template_id,
            "workflow_step_id": f"{template_id}-step-{step['step_order']}",
            "title": step["step_name"],
            "description": step.get("step_description", ""),
            "status": "todo",
            "priority": "high" if step["step_order"] <= 2 else "medium",
            "assigned_to": assigned_to,
            "due_date": base_due_date,
            "completed_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return tasks
