# Invoice Generation Implementation

## Overview
Complete invoice generation system from engagements and time entries with full RBAC integration.

## Files Created

### 1. Repository: `apps/api/repositories/invoice_repository.py`
- **InvoiceRepository class** with CRUD operations
- **Key methods:**
  - `find_all()` - List invoices with filters (firm_id, client_id, engagement_id, status, date range)
  - `find_by_id()` / `find_by_id_or_raise()` - Get single invoice
  - `create()` - Insert new invoice record
  - `update()` - Modify invoice
  - `change_status()` - Transition status (Draft → Issued → Paid → Overdue)
  - `delete()` - Remove invoice (Draft only)
  - `list_for_engagement()` - Get invoices for specific engagement
  - `generate_next_invoice_number()` - Generate sequential invoice numbers: `{firm_code}-{fiscal_year}-{seq}`

### 2. Service: `apps/api/services/invoice_generation_service.py`
- **Three invoice generation methods:**

#### `generate_invoice_from_engagement(engagement_id, invoice_month)`
- Generates invoice from fixed-fee engagement
- Calculation:
  - `amount_paise` = engagement.fee_paise
  - `gst_paise` = (amount_paise * 18) // 100 (SAC 998211 - CA services)
  - `total_paise` = amount_paise + gst_paise
- Sets status to "Draft"
- Returns invoice_id

#### `generate_invoice_from_time_entries(engagement_id, invoice_month, billable_only=True)`
- Generates invoice from time tracking entries
- Aggregates all time_entries for engagement in given month
- Filters by is_billable if requested
- Calculation:
  - `total_minutes` = sum of all duration_minutes
  - `amount_paise` = (total_minutes * hourly_rate_paise) // 60
  - `gst_paise` = (amount_paise * 18) // 100
  - `total_paise` = amount_paise + gst_paise
- Sets status to "Draft"
- Returns invoice_id

#### `generate_recurring_invoice(engagement_id, invoice_month)`
- Generates invoice only if billing cycle period has elapsed
- Checks last invoice date vs billing_cycle (Monthly/Quarterly/Annual)
- Returns invoice_id if generated, None if not yet due

### 3. Router: `apps/api/routers/invoices.py`
- **Prefix:** `/api/invoices`
- **Endpoints:**
  - `GET /api/invoices` - List invoices (filters: engagement_id, client_id, status, date_from, date_to)
  - `GET /api/invoices/{invoice_id}` - Get single invoice
  - `POST /api/invoices/from-engagement/{engagement_id}` - Generate from fixed fee
  - `POST /api/invoices/from-time/{engagement_id}` - Generate from time entries (query: billable_only)
  - `PATCH /api/invoices/{invoice_id}/status` - Change status
  - `DELETE /api/invoices/{invoice_id}` - Delete (Draft only)
- **RBAC:** All endpoints require `invoice.read` or `invoice.write` permission

## Files Modified

### 1. `apps/api/core/permissions.py`
- Added "invoice" resource with read/write permissions:
  - `invoice.read` - AT_LEAST_MANAGER (Manager, Partner)
  - `invoice.write` - PARTNER_ONLY

### 2. `apps/api/main.py`
- Imported invoices router
- Registered router with app

### 3. `apps/api/mock_data.py`
- Added MOCK_INVOICES list with sample data
- Added INVOICE_INDEX for mock lookups

## Test Coverage

### Monetary Calculations (Integer Paise)
1. **Fixed Fee Test:** ₹5,000 → ₹5,900 with 18% GST
   - Input: 500,000 paise
   - GST: (500,000 * 18) // 100 = 90,000 paise
   - Total: 590,000 paise (₹5,900) ✓

2. **Time-Based Test:** 60 minutes @ ₹1,000/hour → ₹1,180 with GST
   - Input: 60 minutes, ₹100,000/hour
   - Amount: (60 * 100,000) // 60 = 100,000 paise
   - GST: (100,000 * 18) // 100 = 18,000 paise
   - Total: 118,000 paise (₹1,180) ✓

### Invoice Number Generation
- Format: `{firm_code}-{fiscal_year}-{seq:03d}`
- Example: `CF-2026-001`, `CF-2026-002`
- Fiscal year (India): April 1 - March 31
- For date 2026-06-10 → FY 2026 (since June > April)

### Status Transitions
- Draft → Issued → Paid ✓
- All transitions allowed via PATCH endpoint
- Valid statuses: Draft, Issued, Paid, Overdue

### Delete Protection
- Only Draft invoices can be deleted ✓
- Issued/Paid/Overdue invoices cannot be deleted
- Returns 400 error with descriptive message

## Database Schema Requirements

### Tables (assumed to exist)
- `fee_invoices` - id, firm_id, client_id, engagement_id, invoice_no, invoice_date, amount_paise, gst_paise, total_paise, status, created_at, updated_at
- `fee_engagements` - id, firm_id, client_id, service_type, fee_paise, billing_cycle, start_date, end_date, status
- `time_entries` - id, firm_id, user_id, task_id, client_id, engagement_id, duration_minutes, is_billable, hourly_rate_paise

## Key Design Decisions

1. **Integer Paise Arithmetic:** All monetary calculations use integer division to avoid floating-point errors
2. **Fiscal Year Calculation:** March 31 cutoff for Indian financial year
3. **Invoice Number Sequencing:** Scoped per fiscal year and firm
4. **GST Rate:** Fixed at 18% (SAC 998211 - Professional services by Chartered Accountants)
5. **Status Workflow:** Simple linear progression (Draft → Issued → Paid)
6. **Mock Support:** Repository supports both mock and real Supabase backends seamlessly

## RBAC & Security

- All endpoints protected by rbac("invoice", "read/write")
- firm_id isolation - users can only see/modify invoices for their firm
- Status changes require write permission
- Deletion restricted to Draft invoices only
- Access denied errors return 403 Forbidden
