"""
Double-entry accounting engine.
All monetary values in paise (integer) — never float.
CGST Act Section 2(59): Input Tax Credit; IT Act Section 44AB: Tax Audit
"""
from datetime import date, datetime
from typing import Optional
from core.exceptions import ValidationError, NotFoundError


# ─── In-memory seed data ──────────────────────────────────────────────────────

MOCK_ACCOUNTS: list[dict] = [
    # Assets
    {"id": "acc-001", "account_code": "1001", "account_name": "Cash in Hand", "account_type": "Asset", "account_subtype": "Current Asset", "parent_id": None, "is_active": True},
    {"id": "acc-002", "account_code": "1002", "account_name": "Bank — HDFC Current Account", "account_type": "Asset", "account_subtype": "Current Asset", "parent_id": None, "is_active": True},
    {"id": "acc-003", "account_code": "1003", "account_name": "Trade Receivables", "account_type": "Asset", "account_subtype": "Current Asset", "parent_id": None, "is_active": True},
    {"id": "acc-004", "account_code": "1004", "account_name": "GST Input Tax Credit", "account_type": "Asset", "account_subtype": "Current Asset", "parent_id": None, "is_active": True},
    {"id": "acc-005", "account_code": "1005", "account_name": "Advance Tax Paid", "account_type": "Asset", "account_subtype": "Current Asset", "parent_id": None, "is_active": True},
    {"id": "acc-006", "account_code": "1101", "account_name": "Office Equipment", "account_type": "Asset", "account_subtype": "Fixed Asset", "parent_id": None, "is_active": True},
    {"id": "acc-007", "account_code": "1102", "account_name": "Furniture & Fixtures", "account_type": "Asset", "account_subtype": "Fixed Asset", "parent_id": None, "is_active": True},
    # Liabilities
    {"id": "acc-008", "account_code": "2001", "account_name": "Trade Payables", "account_type": "Liability", "account_subtype": "Current Liability", "parent_id": None, "is_active": True},
    {"id": "acc-009", "account_code": "2002", "account_name": "GST Output Tax Payable", "account_type": "Liability", "account_subtype": "Current Liability", "parent_id": None, "is_active": True},
    {"id": "acc-010", "account_code": "2003", "account_name": "TDS Payable", "account_type": "Liability", "account_subtype": "Current Liability", "parent_id": None, "is_active": True},
    {"id": "acc-011", "account_code": "2004", "account_name": "Salary Payable", "account_type": "Liability", "account_subtype": "Current Liability", "parent_id": None, "is_active": True},
    {"id": "acc-012", "account_code": "2101", "account_name": "Bank Loan — Term Loan", "account_type": "Liability", "account_subtype": "Long-term Liability", "parent_id": None, "is_active": True},
    # Equity
    {"id": "acc-013", "account_code": "3001", "account_name": "Capital Account", "account_type": "Equity", "account_subtype": "Owner Equity", "parent_id": None, "is_active": True},
    {"id": "acc-014", "account_code": "3002", "account_name": "Retained Earnings", "account_type": "Equity", "account_subtype": "Owner Equity", "parent_id": None, "is_active": True},
    # Income
    {"id": "acc-015", "account_code": "4001", "account_name": "Professional Fees — GST Clients", "account_type": "Income", "account_subtype": "Revenue", "parent_id": None, "is_active": True},
    {"id": "acc-016", "account_code": "4002", "account_name": "Professional Fees — ITR Clients", "account_type": "Income", "account_subtype": "Revenue", "parent_id": None, "is_active": True},
    {"id": "acc-017", "account_code": "4003", "account_name": "Audit Fees", "account_type": "Income", "account_subtype": "Revenue", "parent_id": None, "is_active": True},
    # Expenses
    {"id": "acc-018", "account_code": "5001", "account_name": "Salary Expense", "account_type": "Expense", "account_subtype": "Operating Expense", "parent_id": None, "is_active": True},
    {"id": "acc-019", "account_code": "5002", "account_name": "Office Rent", "account_type": "Expense", "account_subtype": "Operating Expense", "parent_id": None, "is_active": True},
    {"id": "acc-020", "account_code": "5003", "account_name": "Software Subscriptions", "account_type": "Expense", "account_subtype": "Operating Expense", "parent_id": None, "is_active": True},
    {"id": "acc-021", "account_code": "5004", "account_name": "Bank Charges", "account_type": "Expense", "account_subtype": "Operating Expense", "parent_id": None, "is_active": True},
    {"id": "acc-022", "account_code": "5005", "account_name": "Depreciation — Equipment", "account_type": "Expense", "account_subtype": "Non-cash Expense", "parent_id": None, "is_active": True},
]

ACCOUNT_INDEX: dict[str, dict] = {a["id"]: a for a in MOCK_ACCOUNTS}

# All amounts in paise (integer). Never float.
MOCK_JOURNAL_ENTRIES: list[dict] = [
    # JE-001: Opening balance — capital introduced
    {
        "id": "je-001", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-04-01", "reference_no": "OB/2025-26/001",
        "narration": "Opening balance — capital introduced by partner",
        "entry_type": "Opening", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-04-01T09:00:00+05:30",
        "lines": [
            {"id": "jl-001-1", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 50000000, "credit_paise": 0, "narration": "Capital introduced"},
            {"id": "jl-001-2", "account_id": "acc-013", "account_name": "Capital Account", "debit_paise": 0, "credit_paise": 50000000, "narration": "Capital introduced"},
        ],
    },
    # JE-002: Professional fees received from Sharma Enterprises
    {
        "id": "je-002", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-04-05", "reference_no": "INV/2025-26/001",
        "narration": "Professional fees — GST filing for Sharma Enterprises",
        "entry_type": "Receipt", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-04-05T10:00:00+05:30",
        "lines": [
            {"id": "jl-002-1", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 1180000, "credit_paise": 0, "narration": "Payment received"},
            {"id": "jl-002-2", "account_id": "acc-015", "account_name": "Professional Fees — GST Clients", "debit_paise": 0, "credit_paise": 1000000, "narration": "GST filing fees"},
            {"id": "jl-002-3", "account_id": "acc-009", "account_name": "GST Output Tax Payable", "debit_paise": 0, "credit_paise": 180000, "narration": "GST @18% on professional fees"},
        ],
    },
    # JE-003: Office rent paid
    {
        "id": "je-003", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-04-05", "reference_no": "EXP/2025-26/001",
        "narration": "Office rent — MG Road, April 2025",
        "entry_type": "Payment", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-04-05T11:00:00+05:30",
        "lines": [
            {"id": "jl-003-1", "account_id": "acc-019", "account_name": "Office Rent", "debit_paise": 3500000, "credit_paise": 0, "narration": "April rent"},
            {"id": "jl-003-2", "account_id": "acc-010", "account_name": "TDS Payable", "debit_paise": 0, "credit_paise": 350000, "narration": "TDS @10% u/s 194I IT Act"},
            {"id": "jl-003-3", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 0, "credit_paise": 3150000, "narration": "Net rent paid"},
        ],
    },
    # JE-004: Salary paid
    {
        "id": "je-004", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-04-30", "reference_no": "SAL/2025-26/001",
        "narration": "Salary payment — April 2025",
        "entry_type": "Payment", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-04-30T17:00:00+05:30",
        "lines": [
            {"id": "jl-004-1", "account_id": "acc-018", "account_name": "Salary Expense", "debit_paise": 5000000, "credit_paise": 0, "narration": "April salary"},
            {"id": "jl-004-2", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 0, "credit_paise": 5000000, "narration": "Salary transferred"},
        ],
    },
    # JE-005: Professional fees — ITR clients
    {
        "id": "je-005", "client_id": "c-005", "firm_id": "firm-001",
        "entry_date": "2025-05-10", "reference_no": "INV/2025-26/002",
        "narration": "ITR filing fees — Joshi Textiles",
        "entry_type": "Receipt", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-05-10T10:00:00+05:30",
        "lines": [
            {"id": "jl-005-1", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 2360000, "credit_paise": 0, "narration": "Invoice raised"},
            {"id": "jl-005-2", "account_id": "acc-016", "account_name": "Professional Fees — ITR Clients", "debit_paise": 0, "credit_paise": 2000000, "narration": "ITR filing fees"},
            {"id": "jl-005-3", "account_id": "acc-009", "account_name": "GST Output Tax Payable", "debit_paise": 0, "credit_paise": 360000, "narration": "GST @18% on ITR fees"},
        ],
    },
    # JE-006: Payment received from Joshi Textiles
    {
        "id": "je-006", "client_id": "c-005", "firm_id": "firm-001",
        "entry_date": "2025-05-15", "reference_no": "REC/2025-26/001",
        "narration": "Receipt from Joshi Textiles — ITR fees",
        "entry_type": "Receipt", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-05-15T12:00:00+05:30",
        "lines": [
            {"id": "jl-006-1", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 2360000, "credit_paise": 0, "narration": "Payment received"},
            {"id": "jl-006-2", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 0, "credit_paise": 2360000, "narration": "Invoice settled"},
        ],
    },
    # JE-007: GST payment to government
    {
        "id": "je-007", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-05-20", "reference_no": "GST/2025-26/001",
        "narration": "GST payment — April 2025 GSTR-3B",
        "entry_type": "Payment", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-05-20T14:00:00+05:30",
        "lines": [
            {"id": "jl-007-1", "account_id": "acc-009", "account_name": "GST Output Tax Payable", "debit_paise": 540000, "credit_paise": 0, "narration": "Output GST paid"},
            {"id": "jl-007-2", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 0, "credit_paise": 540000, "narration": "GST challan payment"},
        ],
    },
    # JE-008: Software subscription expense
    {
        "id": "je-008", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-05-01", "reference_no": "EXP/2025-26/002",
        "narration": "Software subscription — Winman, Tally",
        "entry_type": "Payment", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-05-01T09:00:00+05:30",
        "lines": [
            {"id": "jl-008-1", "account_id": "acc-020", "account_name": "Software Subscriptions", "debit_paise": 500000, "credit_paise": 0, "narration": "Annual subscription"},
            {"id": "jl-008-2", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 0, "credit_paise": 500000, "narration": "Subscription paid"},
        ],
    },
    # JE-009: Audit fees received — draft
    {
        "id": "je-009", "client_id": "c-002", "firm_id": "firm-001",
        "entry_date": "2025-05-25", "reference_no": "INV/2025-26/003",
        "narration": "Audit fees — Patel & Sons FY 2024-25",
        "entry_type": "Sales", "status": "draft",
        "created_by": "tm-001", "created_at": "2025-05-25T10:00:00+05:30",
        "lines": [
            {"id": "jl-009-1", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 3540000, "credit_paise": 0, "narration": "Audit fee invoice"},
            {"id": "jl-009-2", "account_id": "acc-017", "account_name": "Audit Fees", "debit_paise": 0, "credit_paise": 3000000, "narration": "Audit fees charged"},
            {"id": "jl-009-3", "account_id": "acc-009", "account_name": "GST Output Tax Payable", "debit_paise": 0, "credit_paise": 540000, "narration": "GST @18%"},
        ],
    },
    # JE-010: Bank charges
    {
        "id": "je-010", "client_id": "c-001", "firm_id": "firm-001",
        "entry_date": "2025-05-31", "reference_no": "BNK/2025-26/001",
        "narration": "Bank charges — HDFC May 2025",
        "entry_type": "Journal", "status": "posted",
        "created_by": "tm-001", "created_at": "2025-05-31T18:00:00+05:30",
        "lines": [
            {"id": "jl-010-1", "account_id": "acc-021", "account_name": "Bank Charges", "debit_paise": 50000, "credit_paise": 0, "narration": "Bank service charges"},
            {"id": "jl-010-2", "account_id": "acc-002", "account_name": "Bank — HDFC Current Account", "debit_paise": 0, "credit_paise": 50000, "narration": "Charges debited by bank"},
        ],
    },
]

JOURNAL_INDEX: dict[str, dict] = {e["id"]: e for e in MOCK_JOURNAL_ENTRIES}


def _compute_totals(entry: dict) -> dict:
    """Add total_debit_paise and total_credit_paise to entry dict."""
    total_debit = sum(ln["debit_paise"] for ln in entry["lines"])
    total_credit = sum(ln["credit_paise"] for ln in entry["lines"])
    return {**entry, "total_debit_paise": total_debit, "total_credit_paise": total_credit}


class AccountingService:

    # ── Chart of Accounts ────────────────────────────────────────────────────

    def list_accounts(self) -> list[dict]:
        return list(MOCK_ACCOUNTS)

    def get_account(self, account_id: str) -> dict:
        if account_id not in ACCOUNT_INDEX:
            raise NotFoundError("Account", account_id)
        return ACCOUNT_INDEX[account_id]

    def create_account(self, data: dict) -> dict:
        import uuid as _uuid
        account = {
            "id": f"acc-{_uuid.uuid4().hex[:8]}",
            "account_code": data["account_code"],
            "account_name": data["account_name"],
            "account_type": data["account_type"],
            "account_subtype": data.get("account_subtype"),
            "parent_id": data.get("parent_id"),
            "is_active": True,
            "client_id": data.get("client_id"),
            "firm_id": data.get("firm_id"),
        }
        MOCK_ACCOUNTS.append(account)
        ACCOUNT_INDEX[account["id"]] = account
        return account

    def update_account(self, account_id: str, data: dict) -> dict:
        acc = self.get_account(account_id)
        allowed = {"account_name", "account_subtype", "parent_id", "is_active"}
        for k, v in data.items():
            if k in allowed:
                acc[k] = v
        return acc

    # ── Journal Entries ──────────────────────────────────────────────────────

    def list_journal_entries(
        self,
        client_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        firm_id: Optional[str] = None,
    ) -> list[dict]:
        entries = list(MOCK_JOURNAL_ENTRIES)
        if firm_id:
            entries = [e for e in entries if e.get("firm_id") == firm_id]
        if client_id:
            entries = [e for e in entries if e.get("client_id") == client_id]
        if start_date:
            entries = [e for e in entries if e["entry_date"] >= start_date]
        if end_date:
            entries = [e for e in entries if e["entry_date"] <= end_date]
        return [_compute_totals(e) for e in entries]

    def get_journal_entry(self, entry_id: str) -> dict:
        if entry_id not in JOURNAL_INDEX:
            raise NotFoundError("JournalEntry", entry_id)
        return _compute_totals(JOURNAL_INDEX[entry_id])

    def create_journal_entry(self, data: dict) -> dict:
        import uuid as _uuid
        lines = data.get("lines", [])
        if len(lines) < 2:
            raise ValidationError("lines", "Journal entry must have at least 2 lines")
        total_debit = sum(int(ln["debit_paise"]) for ln in lines)
        total_credit = sum(int(ln["credit_paise"]) for ln in lines)
        if total_debit != total_credit and data.get("status") == "posted":
            raise ValidationError("lines", f"Unbalanced entry: debit {total_debit} != credit {total_credit}")
        entry_id = f"je-{_uuid.uuid4().hex[:8]}"
        enriched_lines = []
        for i, ln in enumerate(lines):
            acc = ACCOUNT_INDEX.get(ln["account_id"], {})
            enriched_lines.append({
                "id": f"{entry_id}-l{i+1}",
                "account_id": ln["account_id"],
                "account_name": acc.get("account_name", ""),
                "debit_paise": int(ln["debit_paise"]),
                "credit_paise": int(ln["credit_paise"]),
                "narration": ln.get("narration", ""),
            })
        entry = {
            "id": entry_id,
            "client_id": data.get("client_id", ""),
            "firm_id": data.get("firm_id"),
            "entry_date": data.get("entry_date", date.today().isoformat()),
            "reference_no": data.get("reference_no"),
            "narration": data.get("narration", ""),
            "entry_type": data.get("entry_type", "Journal"),
            "status": data.get("status", "draft"),
            "lines": enriched_lines,
            "created_by": data.get("created_by"),
            "created_at": datetime.now().isoformat(),
        }
        MOCK_JOURNAL_ENTRIES.append(entry)
        JOURNAL_INDEX[entry_id] = entry
        return _compute_totals(entry)

    def post_journal_entry(self, entry_id: str) -> dict:
        entry = self.get_journal_entry(entry_id)
        if entry["status"] == "posted":
            raise ValidationError("status", "Entry already posted")
        total_debit = sum(int(ln["debit_paise"]) for ln in entry["lines"])
        total_credit = sum(int(ln["credit_paise"]) for ln in entry["lines"])
        if total_debit != total_credit:
            raise ValidationError("lines", f"Cannot post: unbalanced entry debit={total_debit} credit={total_credit}")
        JOURNAL_INDEX[entry_id]["status"] = "posted"
        return _compute_totals(JOURNAL_INDEX[entry_id])

    # ── General Ledger ───────────────────────────────────────────────────────

    def get_ledger(
        self,
        account_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict]:
        self.get_account(account_id)  # raises NotFoundError if missing
        lines: list[dict] = []
        for entry in MOCK_JOURNAL_ENTRIES:
            if entry["status"] != "posted":
                continue
            if start_date and entry["entry_date"] < start_date:
                continue
            if end_date and entry["entry_date"] > end_date:
                continue
            for ln in entry["lines"]:
                if ln["account_id"] == account_id:
                    lines.append({
                        "date": entry["entry_date"],
                        "reference_no": entry.get("reference_no"),
                        "narration": entry["narration"],
                        "debit_paise": int(ln["debit_paise"]),
                        "credit_paise": int(ln["credit_paise"]),
                        "entry_id": entry["id"],
                    })
        # Sort by date, compute running balance in integer paise (never float)
        lines.sort(key=lambda x: x["date"])
        running: int = 0
        for ln in lines:
            running += int(ln["debit_paise"]) - int(ln["credit_paise"])
            ln["running_balance_paise"] = running
        return lines

    # ── Trial Balance ────────────────────────────────────────────────────────

    def get_trial_balance(self, as_of_date: Optional[str] = None) -> dict:
        totals: dict[str, dict] = {}
        for entry in MOCK_JOURNAL_ENTRIES:
            if entry["status"] != "posted":
                continue
            if as_of_date and entry["entry_date"] > as_of_date:
                continue
            for ln in entry["lines"]:
                aid = ln["account_id"]
                if aid not in totals:
                    acc = ACCOUNT_INDEX.get(aid, {})
                    totals[aid] = {
                        "account_id": aid,
                        "account_code": acc.get("account_code", ""),
                        "account_name": acc.get("account_name", ""),
                        "account_type": acc.get("account_type", ""),
                        "total_debit_paise": 0,
                        "total_credit_paise": 0,
                        "net_paise": 0,
                    }
                totals[aid]["total_debit_paise"] += int(ln["debit_paise"])
                totals[aid]["total_credit_paise"] += int(ln["credit_paise"])
        tb_lines = []
        grand_debit: int = 0
        grand_credit: int = 0
        for row in totals.values():
            row["net_paise"] = row["total_debit_paise"] - row["total_credit_paise"]
            tb_lines.append(row)
            grand_debit += row["total_debit_paise"]
            grand_credit += row["total_credit_paise"]
        tb_lines.sort(key=lambda x: x["account_code"])
        difference: int = grand_debit - grand_credit
        return {
            "as_of_date": as_of_date or date.today().isoformat(),
            "lines": tb_lines,
            "total_debit_paise": grand_debit,
            "total_credit_paise": grand_credit,
            "is_balanced": difference == 0,
            "difference_paise": difference,
        }

    # ── Profit & Loss ────────────────────────────────────────────────────────

    def get_profit_loss(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        client_id: Optional[str] = None,
        firm_id: Optional[str] = None,
    ) -> dict:
        # Default: current FY April 1 to today
        today = date.today()
        fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1).isoformat()
        _start = start_date or fy_start
        _end = end_date or today.isoformat()

        income_totals: dict[str, int] = {}
        expense_totals: dict[str, int] = {}

        for entry in MOCK_JOURNAL_ENTRIES:
            if entry["status"] != "posted":
                continue
            if entry["entry_date"] < _start or entry["entry_date"] > _end:
                continue
            if client_id and entry.get("client_id") != client_id:
                continue
            for ln in entry["lines"]:
                aid = ln["account_id"]
                acc = ACCOUNT_INDEX.get(aid, {})
                atype = acc.get("account_type", "")
                # Income: credit increases income; net = total_credit - total_debit
                if atype == "Income":
                    income_totals[aid] = income_totals.get(aid, 0) + int(ln["credit_paise"]) - int(ln["debit_paise"])
                # Expense: debit increases expense; net = total_debit - total_credit
                elif atype == "Expense":
                    expense_totals[aid] = expense_totals.get(aid, 0) + int(ln["debit_paise"]) - int(ln["credit_paise"])

        def _make_pl_section(label: str, totals: dict[str, int]) -> dict:
            lines = []
            for aid, amt in totals.items():
                acc = ACCOUNT_INDEX.get(aid, {})
                lines.append({"account_name": acc.get("account_name", aid), "amount_paise": amt})
            lines.sort(key=lambda x: x["account_name"])
            return {"label": label, "lines": lines, "total_paise": sum(totals.values())}

        revenue_section = _make_pl_section("Revenue", income_totals)
        gross_profit: int = revenue_section["total_paise"]

        # Cost of sales is 0 for a CA firm (services only)
        cos_section = {"label": "Cost of Sales", "lines": [], "total_paise": 0}

        opex_section = _make_pl_section("Operating Expenses", expense_totals)
        net_profit: int = gross_profit - opex_section["total_paise"]

        return {
            "start_date": _start,
            "end_date": _end,
            "revenue": revenue_section,
            "cost_of_sales": cos_section,
            "gross_profit_paise": gross_profit,
            "operating_expenses": opex_section,
            "net_profit_paise": net_profit,
        }

    # ── Balance Sheet ────────────────────────────────────────────────────────

    def get_balance_sheet(
        self,
        as_of_date: Optional[str] = None,
        client_id: Optional[str] = None,
        firm_id: Optional[str] = None,
    ) -> dict:
        _as_of = as_of_date or date.today().isoformat()
        balances: dict[str, int] = {}

        for entry in MOCK_JOURNAL_ENTRIES:
            if entry["status"] != "posted":
                continue
            if entry["entry_date"] > _as_of:
                continue
            for ln in entry["lines"]:
                aid = ln["account_id"]
                balances[aid] = balances.get(aid, 0) + int(ln["debit_paise"]) - int(ln["credit_paise"])

        def _lines_for_type(atype: str) -> list[dict]:
            result = []
            for aid, net in balances.items():
                acc = ACCOUNT_INDEX.get(aid, {})
                if acc.get("account_type") == atype:
                    # Asset: debit balance = positive; Liability/Equity: credit balance = positive
                    bal = net if atype == "Asset" else -net
                    if bal != 0:
                        result.append({"account_name": acc.get("account_name", aid), "balance_paise": bal})
            result.sort(key=lambda x: x["account_name"])
            return result

        def _section(label: str, lines: list[dict]) -> dict:
            return {"label": label, "lines": lines, "total_paise": sum(l["balance_paise"] for l in lines)}

        asset_curr = _lines_for_type("Asset")
        assets = [_section("Assets", asset_curr)]
        total_assets: int = sum(s["total_paise"] for s in assets)

        liab_lines = _lines_for_type("Liability")
        liabilities = [_section("Liabilities", liab_lines)]
        total_liab: int = sum(s["total_paise"] for s in liabilities)

        equity_lines = _lines_for_type("Equity")
        # Add retained earnings from P&L
        pl = self.get_profit_loss(end_date=_as_of)
        net_profit = pl["net_profit_paise"]
        if net_profit != 0:
            equity_lines.append({"account_name": "Net Profit (Current Year)", "balance_paise": net_profit})
        equities = [_section("Equity", equity_lines)]
        total_equity: int = sum(s["total_paise"] for s in equities)

        total_liab_equity: int = total_liab + total_equity
        diff: int = total_assets - total_liab_equity

        return {
            "as_of_date": _as_of,
            "assets": assets,
            "liabilities": liabilities,
            "equity": equities,
            "total_assets_paise": total_assets,
            "total_liabilities_equity_paise": total_liab_equity,
            "is_balanced": diff == 0,
        }

    def get_cash_balance(self) -> int:
        """Return current cash + bank balance in integer paise."""
        ledger = self.get_ledger("acc-002")  # Bank account
        if not ledger:
            return 0
        return int(ledger[-1]["running_balance_paise"])


accounting_service = AccountingService()
