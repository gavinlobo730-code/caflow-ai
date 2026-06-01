// Shared domain types — all pages import from here, never define locally

export type EntityType =
  | "Proprietorship"
  | "Partnership"
  | "LLP"
  | "Private Limited"
  | "Public Limited"
  | "Trust"
  | "Society"
  | "Individual";

export type ClientStatus = "active" | "inactive";

export type GSTFilingFrequency = "monthly" | "quarterly";

export interface Client {
  id: string;
  client_name: string;
  entity_type: EntityType;
  pan: string;
  gstin?: string;
  mobile?: string;
  email?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  pincode?: string;
  state_code?: string;
  gst_filing_frequency: GSTFilingFrequency;
  status: ClientStatus;
  assigned_to?: string;
  notes?: string;
  created_at: string;
}

export type ComplianceType =
  | "GSTR1"
  | "GSTR3B"
  | "GSTR9"
  | "ITR"
  | "TDS24Q"
  | "TDS26Q"
  | "ADVANCE_TAX"
  | "TCS_RETURN"
  | "OTHER";

export type ComplianceStatus =
  | "pending"
  | "in_progress"
  | "filed"
  | "overdue"
  | "not_applicable";

export type CompliancePriority = "critical" | "high" | "medium" | "low";

export interface ComplianceTask {
  id: string;
  client_id: string;
  compliance_type: ComplianceType;
  period_start: string;
  period_end: string;
  due_date: string;
  status: ComplianceStatus;
  priority: CompliancePriority;
  days_remaining: number;
  assigned_to?: string;
  notes?: string;
}

export type DocumentType =
  | "FORM16"
  | "GST_INVOICE"
  | "BANK_STATEMENT"
  | "AIS"
  | "FORM26AS"
  | "TDS_CERTIFICATE"
  | "RENTAL_AGREEMENT"
  | "CAPITAL_GAINS_STATEMENT"
  | "OTHER";

export type ReviewStatus = "pending_review" | "approved" | "rejected";

export interface Document {
  id: string;
  client_id: string;
  document_type: DocumentType;
  file_name: string;
  file_path: string;
  financial_year?: string;
  extracted_json?: Record<string, unknown>;
  confidence_score?: number;
  review_status: ReviewStatus;
  upload_date: string;
}

export type InsightType =
  | "MISSING_INVOICE"
  | "TDS_MISMATCH"
  | "DEADLINE_APPROACHING"
  | "ITC_MISMATCH"
  | "TURNOVER_THRESHOLD"
  | "PAYMENT_DELAY"
  | "RECONCILIATION_GAP"
  | "OTHER";

export type InsightSeverity = "critical" | "high" | "medium" | "low" | "info";

export type InsightStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export interface AIInsight {
  id: string;
  client_id: string;
  insight_type: InsightType;
  severity: InsightSeverity;
  title: string;
  description: string;
  recommended_action?: string;
  status: InsightStatus;
  created_at: string;
}

export interface ActivityLog {
  id: string;
  client_id?: string;
  actor_id?: string;
  action: string;
  description: string;
  entity_type?: string;
  entity_id?: string;
  created_at: string;
}

export interface ClientWorkspace {
  profile: Client;
  compliance_tasks: ComplianceTask[];
  upcoming_deadlines: ComplianceTask[];
  documents: Document[];
  recent_activity: ActivityLog[];
  ai_insights: AIInsight[];
  summary: {
    total_tasks: number;
    overdue_count: number;
    pending_count: number;
    filed_count: number;
    document_count: number;
    open_insights: number;
  };
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

// ─── WORKFLOW TYPES ────────────────────────────────────────────────────────

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "waiting_client"
  | "review_required"
  | "completed";

export type TaskPriority = "low" | "medium" | "high" | "critical";

export interface WorkflowStep {
  step_order: number;
  step_name: string;
  step_description?: string;
  required: boolean;
  default_assignee_role?: string;
  estimated_hours?: number;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  compliance_type?: string;
  is_template: boolean;
  steps: WorkflowStep[];
}

export interface Task {
  id: string;
  client_id: string;
  client_name?: string;
  workflow_id?: string;
  workflow_step_id?: string;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  urgency?: string;
  assigned_to?: string;
  due_date?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface KanbanBoard {
  todo: Task[];
  in_progress: Task[];
  waiting_client: Task[];
  review_required: Task[];
  completed: Task[];
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  assigned_open_tasks: number;
  completed_tasks: number;
  workload_pct: number;
}

export interface DashboardSummary {
  active_clients: number;
  tasks_due_today: number;
  overdue_tasks: number;
  waiting_client: number;
  review_required: number;
  total_open_tasks: number;
}

export interface Reminder {
  id: string;
  task_id?: string;
  client_id?: string;
  reminder_type: "email" | "whatsapp" | "system";
  scheduled_for: string;
  sent_at?: string;
  status: "pending" | "sent" | "failed";
  message?: string;
  created_at: string;
}

// ─── ACCOUNTING TYPES ──────────────────────────────────────────────────────

export type TransactionType = "credit" | "debit";

export interface Transaction {
  id: string;
  date: string;
  description: string;
  type: TransactionType;
  amount_paise: number;
  amount_display: string;
  category: string;
}

// ─── MODULE STATUS TYPES ───────────────────────────────────────────────────

export type GSTReturnStatus =
  | "Draft"
  | "Awaiting Docs"
  | "Ready for Review"
  | "Approved"
  | "Ready to File"
  | "Filed";

export type ITRStatus =
  | "Draft"
  | "Awaiting Docs"
  | "Review Required"
  | "Ready for Review"
  | "Ready to File"
  | "Filed";

export type TDSReturnStatus = "Draft" | "Pending" | "Filed";
