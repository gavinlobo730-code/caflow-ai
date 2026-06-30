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

export type ClientStatus = "active" | "inactive" | "archived";

export type GSTFilingFrequency = "monthly" | "quarterly";

export interface Client {
  id: string;
  client_name: string;
  entity_type: EntityType;
  pan?: string;   // nullable since migration 133 — PAN is collected during onboarding, not at creation
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
  is_archived?: boolean;
  archived_at?: string | null;
  deleted_at?: string | null;
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
  assignee_id?: string;
  assignee_name?: string;
  assignee_email?: string;
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

export interface FirmUser {
  id: string;
  auth_user_id?: string;
  firm_id?: string;
  full_name?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
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
  documents_pending_review?: number;
  overdue_compliance?: number;
  compliance_due_week?: number;
  compliance_overdue?: number;
  high_risk_clients?: number;
  returns_due_week?: number;
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

export type AccountType = "Asset" | "Liability" | "Equity" | "Revenue" | "Expense";
export type EntryType = "Sales" | "Purchase" | "Payment" | "Receipt" | "Journal" | "Contra" | "Opening";
export type JournalStatus = "draft" | "posted";

export interface Account {
  id: string;
  account_code: string;
  account_name: string;
  account_type: AccountType;
  account_subtype?: string;
  parent_id?: string;
  is_active: boolean;
  client_id?: string;
  firm_id?: string;
}

export interface JournalLine {
  id: string;
  account_id: string;
  account_name?: string;
  debit_paise: number;
  credit_paise: number;
  narration?: string;
}

export interface JournalEntry {
  id: string;
  client_id: string;
  firm_id?: string;
  entry_date: string;
  reference_no?: string;
  narration: string;
  entry_type: EntryType;
  status: JournalStatus;
  is_posted?: boolean;
  lines: JournalLine[];
  total_debit_paise?: number;
  total_credit_paise?: number;
  created_by?: string;
  created_at: string;
}

export interface LedgerLine {
  date: string;
  reference_no?: string;
  narration: string;
  debit_paise: number;
  credit_paise: number;
  running_balance_paise: number;
  entry_id: string;
}

export interface TrialBalanceLine {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: AccountType;
  total_debit_paise: number;
  total_credit_paise: number;
  net_paise: number;
}

export interface TrialBalance {
  as_of_date: string;
  lines: TrialBalanceLine[];
  total_debit_paise: number;
  total_credit_paise: number;
  is_balanced: boolean;
  difference_paise: number;
}

export interface PLSection {
  label: string;
  lines: { account_name: string; amount_paise: number }[];
  total_paise: number;
}

export interface ProfitLoss {
  start_date: string;
  end_date: string;
  revenue: PLSection;
  cost_of_sales: PLSection;
  gross_profit_paise: number;
  operating_expenses: PLSection;
  net_profit_paise: number;
}

export interface BalanceSheetSection {
  label: string;
  lines: { account_name: string; balance_paise: number }[];
  total_paise: number;
}

export interface BalanceSheet {
  as_of_date: string;
  assets: BalanceSheetSection[];
  liabilities: BalanceSheetSection[];
  equity: BalanceSheetSection[];
  total_assets_paise: number;
  total_liabilities_equity_paise: number;
  is_balanced: boolean;
}

// ─── COMPLIANCE RECORD TYPES ───────────────────────────────────────────────

export type ComplianceRecordType = "GST" | "Income Tax" | "TDS" | "MCA" | "Payroll" | "Bookkeeping";
export type ComplianceRecordStatus =
  | "Not Started"
  | "Awaiting Documents"
  | "In Progress"
  | "Ready For Review"
  | "Ready To File"
  | "Filed"
  | "Overdue";

export interface ComplianceRecord {
  id: string;
  firm_id?: string;
  client_id: string;
  client_name?: string;
  compliance_type: ComplianceRecordType;
  period_label: string;
  period_start: string;
  period_end: string;
  status: ComplianceRecordStatus;
  due_date: string;
  assigned_to?: string;
  priority: CompliancePriority;
  notes?: string;
  filed_date?: string;
  acknowledgement_no?: string;
  risk_score: number;
  created_at: string;
  updated_at: string;
}

export interface ClientHealthScore {
  client_id: string;
  client_name: string;
  health_score: number;
  risk_level: "critical" | "high" | "medium" | "low";
  overdue_records: number;
  overdue_tasks: number;
  missing_documents: number;
  breakdown: {
    label: string;
    deduction: number;
  }[];
}

export interface ComplianceFirmSummary {
  due_this_week: number;
  overdue: number;
  ready_for_review: number;
  ready_to_file: number;
  filed_this_month: number;
  high_risk_clients: number;
}

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

export type ITRStatus =
  | "Draft"
  | "Awaiting Docs"
  | "Review Required"
  | "Ready for Review"
  | "Ready to File"
  | "Filed";

export type TDSReturnStatus = "Draft" | "Pending" | "Filed";

// ─── DOCUMENT INTELLIGENCE TYPES ──────────────────────────────────────────

export type ExtractionStatus = "pending" | "processing" | "completed" | "failed";
export type ExtractionProvider = "mock" | "aws_textract" | "google_docai" | "azure_formrec" | "claude_vision";
export type RiskCategory =
  | "AIS_MISMATCH" | "TDS_MISMATCH" | "MISSING_INVOICE" | "GST_MISMATCH"
  | "BANK_RECONCILIATION" | "HIGH_LIABILITY" | "MISSING_FORM16" | "MCA_OVERDUE"
  | "DUPLICATE_ENTRY" | "CLASSIFICATION_ERROR" | "OTHER";
export type RiskResolutionStatus = "open" | "acknowledged" | "resolved" | "false_positive";

export interface DocumentExtraction {
  id: string;
  document_id: string;
  extraction_status: ExtractionStatus;
  provider: ExtractionProvider;
  confidence_score?: number;
  extracted_data?: Record<string, unknown>;
  validation_results?: Record<string, unknown>;
  error_message?: string;
  created_at: string;
}

export interface DocumentRisk {
  id: string;
  document_id: string;
  client_id: string;
  severity: InsightSeverity;
  category: RiskCategory;
  title: string;
  description: string;
  resolution_status: RiskResolutionStatus;
  resolved_at?: string;
  created_at: string;
}

export interface DocumentWithIntelligence extends Document {
  client_name?: string;
  extraction?: DocumentExtraction;
  risks?: DocumentRisk[];
  risk_level?: InsightSeverity;
}

export interface DocumentStats {
  total: number;
  pending_review: number;
  processing: number;
  high_risk: number;
  extraction_failures: number;
}

// ─── RISK ENGINE TYPES ────────────────────────────────────────────────────

export interface RiskItem {
  id: string;
  source: "document" | "compliance" | "task" | "system";
  client_id: string;
  client_name?: string;
  severity: InsightSeverity;
  category: string;
  title: string;
  description: string;
  resolution_status: RiskResolutionStatus;
  created_at: string;
}

export interface RiskStats {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
  resolved: number;
  total_open: number;
}

// ─── AI INSIGHTS V2 TYPES ─────────────────────────────────────────────────

export interface AIInsightV2 {
  id: string;
  client_id?: string;
  client_name?: string;
  category: "compliance" | "accounting" | "document" | "risk" | "performance";
  severity: InsightSeverity;
  title: string;
  description: string;
  recommendation?: string;
  status: InsightStatus;
  created_at: string;
}

// ─── AUTOMATION TYPES ─────────────────────────────────────────────────────

export type AutomationTrigger = "risk_detected" | "document_uploaded" | "compliance_due" | "status_changed" | "deadline_approaching";
export type AutomationAction = "create_task" | "send_notification" | "update_status" | "assign_user" | "create_insight";

export interface AutomationRule {
  id: string;
  name: string;
  trigger_type: AutomationTrigger;
  trigger_config: Record<string, unknown>;
  action_type: AutomationAction;
  action_config: Record<string, unknown>;
  is_enabled: boolean;
  created_at: string;
}

export interface AutomationExecution {
  id: string;
  rule_id: string;
  rule_name?: string;
  status: "success" | "failed" | "skipped";
  trigger_data?: Record<string, unknown>;
  result_data?: Record<string, unknown>;
  error_message?: string;
  executed_at: string;
}

export interface AutomationStats {
  rules_active: number;
  executions_today: number;
  tasks_created: number;
  notifications_sent: number;
}

// ─── NOTIFICATION TYPES ───────────────────────────────────────────────────

export type NotificationType = "task_assigned" | "risk_detected" | "document_processed" | "compliance_due" | "ai_recommendation" | "status_changed";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  severity: InsightSeverity;
  is_read: boolean;
  is_archived?: boolean;
  user_id?: string;
  client_id?: string;
  action_url?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface NotificationStats {
  total: number;
  unread: number;
  by_type: Record<string, number>;
}

// ─── AI COPILOT TYPES ─────────────────────────────────────────────────────

export interface CopilotMessage {
  role: "user" | "assistant";
  content: string;
  suggested_actions?: string[];
}

// ─── PHASE 1.2 — TASK MANAGEMENT EXTENSIONS ──────────────────────────────

export interface TaskTemplate {
  id: string;
  firm_id?: string;
  name: string;
  description?: string;
  default_priority: TaskPriority;
  estimated_hours?: number;
  tags: string[];
  default_assignee_role?: string;
  created_at: string;
  updated_at: string;
}

export interface TaskTag {
  id: string;
  firm_id?: string;
  task_id: string;
  tag: string;
  created_at: string;
}

export interface TaskDependency {
  id: string;
  task_id: string;
  depends_on_task_id: string;
  created_at: string;
}

export type TaskTimelineEventType =
  | "created"
  | "assigned"
  | "reassigned"
  | "status_changed"
  | "priority_changed"
  | "due_date_changed"
  | "comment_added"
  | "completed"
  | "reopened"
  | "recurring_generated";

export interface TaskTimelineEvent {
  id: string;
  task_id: string;
  firm_id?: string;
  event_type: TaskTimelineEventType;
  actor_id?: string;
  actor_name?: string;
  old_value?: Record<string, unknown>;
  new_value?: Record<string, unknown>;
  created_at: string;
}

export type RecurringFrequency = "daily" | "weekly" | "monthly" | "quarterly" | "annual";

export interface RecurringTaskConfig {
  id: string;
  firm_id: string;
  client_id?: string;
  template_id?: string;
  assignee_id?: string;
  title?: string;
  description?: string;
  priority: TaskPriority;
  frequency: RecurringFrequency;
  next_due_date: string;
  last_generated_at?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ─── PHASE 1.2 — TIME TRACKING TYPES ─────────────────────────────────────

export interface TimeEntry {
  id: string;
  firm_id?: string;
  user_id: string;
  task_id?: string;
  client_id?: string;
  engagement_id?: string;
  description?: string;
  started_at: string;
  ended_at?: string;
  duration_minutes?: number;
  is_billable: boolean;
  hourly_rate_paise?: number;
  created_at: string;
  updated_at: string;
}

export interface TimerState {
  is_running: boolean;
  entry?: TimeEntry;
  elapsed_seconds: number;
}

export interface TimeSummaryEntry {
  dimension: string;
  total_minutes: number;
  billable_minutes: number;
  entry_count: number;
}

export interface TimeSummary {
  by_client: TimeSummaryEntry[];
  by_task: TimeSummaryEntry[];
  total_minutes: number;
  billable_minutes: number;
  entry_count: number;
}

// ─── PHASE 1.2 — WORKLOAD TYPES ──────────────────────────────────────────

export interface WorkloadMember {
  user_id: string;
  user_name: string;
  user_email: string;
  role: string;
  active_tasks: number;
  overdue_tasks: number;
  due_this_week: number;
  completed_this_week: number;
  weekly_capacity_hours: number;
  max_concurrent_tasks: number;
  minutes_logged_this_week: number;
  utilisation_pct: number;
  is_overloaded: boolean;
  is_underutilised: boolean;
}

export interface TeamWorkload {
  members: WorkloadMember[];
  total_active_tasks: number;
  total_overdue_tasks: number;
  overloaded_count: number;
  underutilised_count: number;
  avg_utilisation_pct: number;
}

export interface MyWorkloadSummary {
  my_tasks: number;
  due_today: number;
  due_this_week: number;
  overdue: number;
  completed_this_week: number;
  utilisation_pct: number;
}

// ─── PHASE 1.2 — ANALYTICS TYPES ─────────────────────────────────────────

export interface TeamMemberAnalytics {
  user_id: string;
  user_name: string;
  total_minutes: number;
  billable_minutes: number;
  tasks_completed: number;
  tasks_active: number;
  utilisation_pct: number;
}

export interface TeamAnalyticsReport {
  period: string;
  members: TeamMemberAnalytics[];
  total_minutes: number;
  billable_minutes: number;
  avg_utilisation_pct: number;
}

export interface ClientAnalyticsEntry {
  client_id: string;
  client_name: string;
  total_minutes: number;
  billable_minutes: number;
  tasks_completed: number;
  tasks_active: number;
  revenue_paise: number;
}

export interface ClientAnalyticsReport {
  period: string;
  clients: ClientAnalyticsEntry[];
  total_minutes: number;
  total_revenue_paise: number;
}

export interface FirmAnalyticsReport {
  period: string;
  total_minutes: number;
  billable_minutes: number;
  utilisation_pct: number;
  tasks_completed: number;
  tasks_active: number;
  tasks_overdue: number;
  revenue_paise: number;
  outstanding_paise: number;
  invoices_issued: number;
  invoices_paid: number;
}
