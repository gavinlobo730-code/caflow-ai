import { supabase } from "@/lib/supabase/client";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Standard backend response envelope: { success, data, error }. */
export type ApiResp<T = unknown> = { success: boolean; data: T; error: string | null };

// Phase 4.5.1 — a client_portal_users row (F22 fix: invite_token is single-use,
// never re-sent to the frontend once accepted — the field is present here only
// because inviteContact()'s response carries it once, to build the invite link).
export type PortalContact = {
  id: string; client_id: string; email: string; name: string | null;
  status: "invited" | "active" | "deactivated";
  auth_user_id?: string | null; invite_token?: string | null;
  invited_at?: string | null; activated_at?: string | null; deactivated_at?: string | null;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Perf/UX: bound every request so a cold-starting/unreachable backend fails
// fast with a clear message instead of hanging the UI indefinitely. 45s covers
// a Render cold start; the warm-up ping (AuthContext) usually avoids hitting it.
async function fetchWithTimeout(path: string, options: RequestInit | undefined, token: string | undefined): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 45_000);
  try {
    return await fetch(`${BASE_URL}${path}`, {
      ...options,
      signal: options?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options?.headers ?? {}),
      },
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  let res: Response;
  try {
    res = await fetchWithTimeout(path, options, token);
  } catch (e) {
    // A sleeping Render free-tier instance takes 30-60s to cold-start. The
    // first request either times out (our own AbortError above) or the
    // connection fails outright before any response comes back (TypeError
    // "Failed to fetch" — the same underlying symptom the browser reports as
    // a misleading CORS error, since there's no response to carry a CORS
    // header). Either way nothing was processed server-side, so one retry
    // after a short delay is safe — by then the instance has usually
    // finished waking up.
    const isTimeout = e instanceof DOMException && e.name === "AbortError";
    const isNetworkFailure = e instanceof TypeError;
    if (!isTimeout && !isNetworkFailure) throw e;
    await sleep(5_000);
    try {
      res = await fetchWithTimeout(path, options, token);
    } catch {
      throw new Error("The server is taking too long to respond (it may be waking up). Please retry in a moment.");
    }
  }
  // A long-running bulk action (hundreds of sequential/concurrent calls) can
  // outlive the access token fetched at its start — refresh once and retry
  // rather than surfacing a raw "Token expired" mid-batch. Safe to retry: a
  // 401 means auth rejected the request before any handler ran, so nothing
  // was processed server-side.
  if (res.status === 401) {
    const { data: refreshed } = await supabase.auth.refreshSession();
    const newToken = refreshed.session?.access_token;
    if (newToken && newToken !== token) {
      res = await fetchWithTimeout(path, options, newToken);
    }
  }
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }
  return res.json();
}

/** Fetch a binary endpoint with auth and trigger a browser blob download. */
async function downloadFile(path: string, fallbackFilename: string, extraHeaders?: Record<string, string>): Promise<void> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(extraHeaders ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }

  // Prefer the filename from Content-Disposition, fall back to the provided one
  let filename = fallbackFilename;
  const disposition = res.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="?([^";]+)"?/);
  if (match?.[1]) filename = match[1];

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  clients: {
    list: () => request("/api/clients"),
    getWorkspace: (id: string) => request(`/api/clients/${id}`),
    create: (body: unknown) => request("/api/clients", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) => request(`/api/clients/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    archive: (id: string) => request(`/api/clients/${id}/archive`, { method: "POST" }),
    restore: (id: string) => request(`/api/clients/${id}/restore`, { method: "POST" }),
    permanentDelete: (id: string) => request(`/api/clients/${id}`, { method: "DELETE" }),
  },
  compliance: {
    tasks: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/compliance/tasks${q ? `?${q}` : ""}`);
    },
    calendar: () => request("/api/compliance/calendar"),
    calculateDueDates: (year: number, month: number) =>
      request(`/api/compliance/due-dates/calculate?year=${year}&month=${month}`),
  },
  documents: {
    list: (client_id?: string) => request(`/api/documents${client_id ? `?client_id=${client_id}` : ""}`),
    parse: (formData: FormData) =>
      fetch(`${BASE_URL}/api/documents/parse`, { method: "POST", body: formData }).then((r) => r.json()),
  },
  assistant: {
    ask: (body: { question: string; conversation_history?: unknown[]; client_id?: string }) =>
      request("/api/assistant", { method: "POST", body: JSON.stringify(body) }),
  },
  insights: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/insights${q ? `?${q}` : ""}`);
    },
    updateStatus: (id: string, status: string) =>
      request(`/api/insights/${id}/status?new_status=${status}`, { method: "PATCH" }),
  },
  tasks: {
    list: (params?: { client_id?: string; status?: string; assigned_to?: string; kanban?: boolean }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/tasks${q ? `?${q}` : ""}`);
    },
    kanban: () => request("/api/tasks?kanban=true"),
    create: (body: unknown) => request("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) => request(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    dashboardSummary: () => request("/api/tasks/summary/dashboard"),
  },
  team: {
    list: () => request("/api/team"),
  },
  reminders: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/reminders${q ? `?${q}` : ""}`);
    },
    create: (body: unknown) => request("/api/reminders", { method: "POST", body: JSON.stringify(body) }),
    markSent: (id: string) => request(`/api/reminders/${id}/sent`, { method: "PATCH" }),
  },
  accounting: {
    accounts: () => request("/api/accounting/accounts"),
    createAccount: (data: unknown) => request("/api/accounting/accounts", { method: "POST", body: JSON.stringify(data) }),
    updateAccount: (id: string, data: unknown) => request(`/api/accounting/accounts/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    journal: (params?: Record<string, string>) => request(`/api/accounting/journal${params ? "?" + new URLSearchParams(params) : ""}`),
    createJournalEntry: (data: unknown) => request("/api/accounting/journal", { method: "POST", body: JSON.stringify(data) }),
    postJournalEntry: (id: string) => request(`/api/accounting/journal/${id}/post`, { method: "PATCH" }),
    ledger: (params: Record<string, string>) => request(`/api/accounting/ledger?${new URLSearchParams(params)}`),
    trialBalance: (params?: Record<string, string>) => request(`/api/accounting/trial-balance${params ? "?" + new URLSearchParams(params) : ""}`),
    profitLoss: (params?: Record<string, string>) => request(`/api/accounting/profit-loss${params ? "?" + new URLSearchParams(params) : ""}`),
    balanceSheet: (params?: Record<string, string>) => request(`/api/accounting/balance-sheet${params ? "?" + new URLSearchParams(params) : ""}`),
    scheduleIii: (params?: Record<string, string>) => request(`/api/accounting/schedule-iii${params ? "?" + new URLSearchParams(params) : ""}`),
    cashFlow: (params?: Record<string, string>) => request(`/api/accounting/cash-flow${params ? "?" + new URLSearchParams(params) : ""}`),
    statementAnalysis: (params: Record<string, string>) => request(`/api/accounting/statement-analysis?${new URLSearchParams(params)}`),
    // Phase 3.5 — journal approval queue (Draft → Approve → Post)
    journalsQueue: (params?: Record<string, string>) => request(`/api/accounting/journals${params ? "?" + new URLSearchParams(params) : ""}`),
    postDraftJournal: (journalId: string) => request(`/api/accounting/journals/${journalId}/post`, { method: "POST" }),
    // Multi-Currency Phase 5 — read-only FX reports (empty for INR-only clients).
    fxReports: {
      realized: (params: Record<string, string>) => request(`/api/fx-reports/realized?${new URLSearchParams(params)}`),
      unrealized: (params: Record<string, string>) => request(`/api/fx-reports/unrealized?${new URLSearchParams(params)}`),
      exposure: (params: Record<string, string>) => request(`/api/fx-reports/exposure?${new URLSearchParams(params)}`),
      rateAudit: (params: Record<string, string>) => request(`/api/fx-reports/rate-audit?${new URLSearchParams(params)}`),
      openBalances: (params: Record<string, string>) => request(`/api/fx-reports/open-balances?${new URLSearchParams(params)}`),
    },
  },
  // Stock register + per-item ledger (migration 188). Read-only — all
  // movements are written as a side effect of issuing/receiving documents.
  inventory: {
    items: (params: Record<string, string>) => request(`/api/inventory/items?${new URLSearchParams(params)}`),
    ledger: (serviceCatalogueId: string, params: Record<string, string>) =>
      request(`/api/inventory/items/${serviceCatalogueId}/ledger?${new URLSearchParams(params)}`),
    adjust: (serviceCatalogueId: string, body: unknown) =>
      request(`/api/inventory/items/${serviceCatalogueId}/adjust`, { method: "POST", body: JSON.stringify(body) }),
    writedown: (serviceCatalogueId: string, body: unknown) =>
      request(`/api/inventory/items/${serviceCatalogueId}/writedown`, { method: "POST", body: JSON.stringify(body) }),
  },
  // Multi-Currency (Phase 1/5) — currency master + resolved policy (gates FX UI).
  currencies: {
    list: (params?: Record<string, string>) => request(`/api/currencies${params ? "?" + new URLSearchParams(params) : ""}`),
    policy: (params: Record<string, string>) => request(`/api/currencies/policy?${new URLSearchParams(params)}`),
  },
  // Banking (Phase B.0): all bank mutations go through the backend banking
  // service — the frontend never writes bank rows or journals to Supabase.
  banking: {
    listBankAccounts: (params?: Record<string, string>) => request(`/api/banking/accounts${params ? "?" + new URLSearchParams(params) : ""}`),
    /** Multi-Currency Phase 5 — derived base (+ foreign for FX accounts) balance. */
    accountBalance: (accountId: string, params: Record<string, string>) => request(`/api/banking/accounts/${accountId}/balance?${new URLSearchParams(params)}`),
    listStatements: (params?: Record<string, string>) => request(`/api/banking/statements${params ? "?" + new URLSearchParams(params) : ""}`),
    importStatement: (data: unknown) => request("/api/banking/statements/import", { method: "POST", body: JSON.stringify(data) }),
    /** Upload a CSV/XLSX statement — parsed, normalized & deduped SERVER-SIDE (B.1). */
    uploadStatement: async (form: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}/api/banking/statements/upload`, {
        method: "POST",
        // No Content-Type — the browser sets the multipart boundary.
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      return res.json();
    },
    listTransactions: (params?: Record<string, string>) => request(`/api/banking/transactions${params ? "?" + new URLSearchParams(params) : ""}`),
    setTransactionAccount: (txnId: string, data: unknown) => request(`/api/banking/transactions/${txnId}`, { method: "PATCH", body: JSON.stringify(data) }),
    ignoreTransaction: (txnId: string) => request(`/api/banking/transactions/${txnId}/ignore`, { method: "POST" }),
    postTransaction: (txnId: string, data: unknown) => request(`/api/banking/transactions/${txnId}/post`, { method: "POST", body: JSON.stringify(data) }),
    // B.2 — matching & categorization (suggestions only; no posting)
    queue: (params?: Record<string, string>) => request(`/api/banking/queue${params ? "?" + new URLSearchParams(params) : ""}`),
    suggestions: (txnId: string) => request(`/api/banking/transactions/${txnId}/suggestions`),
    categorize: (txnId: string, data: { category: string }) => request(`/api/banking/transactions/${txnId}/categorize`, { method: "POST", body: JSON.stringify(data) }),
    matchEntity: (txnId: string, data: { matched_entity_type: string; matched_entity_id: string; category?: string }) => request(`/api/banking/transactions/${txnId}/match`, { method: "POST", body: JSON.stringify(data) }),
    unmatch: (txnId: string) => request(`/api/banking/transactions/${txnId}/unmatch`, { method: "POST" }),
    // B.3 — posting engine (explicit, human-initiated; never auto-posts)
    readyToPost: (params?: Record<string, string>) => request(`/api/banking/ready-to-post${params ? "?" + new URLSearchParams(params) : ""}`),
    pending: (params?: Record<string, string>) => request(`/api/banking/pending${params ? "?" + new URLSearchParams(params) : ""}`),
    posted: (params?: Record<string, string>) => request(`/api/banking/posted${params ? "?" + new URLSearchParams(params) : ""}`),
    postingPreview: (txnId: string, data: { bank_account_id?: string; account_id?: string; to_bank_account_id?: string }) => request(`/api/banking/transactions/${txnId}/posting-preview`, { method: "POST", body: JSON.stringify(data) }),
    // B.4 — reconciliation engine (sessions, manual reconcile, tie-out, report)
    reconciliations: {
      list: (params?: Record<string, string>) => request(`/api/banking/reconciliations${params ? "?" + new URLSearchParams(params) : ""}`),
      create: (data: { client_id: string; bank_account_id: string; statement_start_date: string; statement_end_date: string; opening_balance_paise: number; closing_balance_paise: number }) => request("/api/banking/reconciliations", { method: "POST", body: JSON.stringify(data) }),
      get: (id: string) => request(`/api/banking/reconciliations/${id}`),
      update: (id: string, data: { opening_balance_paise?: number; closing_balance_paise?: number; adjustments_paise?: number }) => request(`/api/banking/reconciliations/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
      report: (id: string) => request(`/api/banking/reconciliations/${id}/report`),
      reconcile: (id: string, transaction_ids: string[]) => request(`/api/banking/reconciliations/${id}/reconcile`, { method: "POST", body: JSON.stringify({ transaction_ids }) }),
      unreconcile: (id: string, transaction_ids: string[]) => request(`/api/banking/reconciliations/${id}/unreconcile`, { method: "POST", body: JSON.stringify({ transaction_ids }) }),
      complete: (id: string) => request(`/api/banking/reconciliations/${id}/complete`, { method: "POST" }),
      exportCsv: (id: string) => downloadFile(`/api/banking/reconciliations/${id}/report.csv`, `reconciliation-${id}.csv`),
    },
  },
  complianceRecords: {
    list: (params?: Record<string, string>) => request(`/api/compliance-records${params ? "?" + new URLSearchParams(params) : ""}`),
    get: (id: string) => request(`/api/compliance-records/${id}`),
    create: (data: unknown) => request("/api/compliance-records", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: unknown) => request(`/api/compliance-records/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    clientHealth: (clientId: string) => request(`/api/compliance-records/client/${clientId}/health`),
    firmSummary: () => request("/api/compliance-records/firm/summary"),
  },
  dashboard: {
    summary: () => request("/api/tasks/summary/dashboard"),
  },
  // Phase 4.4 — Compliance & Engagement operations (canonical = compliance_records).
  // Thin wrappers; all due-date/aggregation/workflow logic is server-side.
  // Never auto-submits to any government portal — markFiled records that a
  // CA has confirmed a return was filed, it never files anything itself.
  complianceOps: {
    dashboard: () => request("/api/compliance/dashboard"),
    obligations: (params?: Record<string, string>) =>
      request(`/api/compliance/obligations${params ? "?" + new URLSearchParams(params) : ""}`),
    calendar: (clientId?: string) =>
      request(`/api/compliance/obligations/calendar${clientId ? `?client_id=${clientId}` : ""}`),
    generate: (params?: Record<string, string>) =>
      request(`/api/compliance/obligations/generate${params ? "?" + new URLSearchParams(params) : ""}`, { method: "POST" }),
    assign: (id: string, body: { preparer_id?: string; reviewer_id?: string; approver_id?: string }) =>
      request(`/api/compliance/obligations/${id}/assign`, { method: "POST", body: JSON.stringify(body) }),
    transition: (id: string, status: string) =>
      request(`/api/compliance/obligations/${id}/transition`, { method: "POST", body: JSON.stringify({ status }) }),
    markFiled: (id: string, acknowledgementNo?: string) =>
      request(`/api/compliance/obligations/${id}/mark-filed`, {
        method: "POST", body: JSON.stringify({ acknowledgement_no: acknowledgementNo ?? null }),
      }),
    runEscalations: () => request("/api/compliance/run-escalations", { method: "POST" }),
  },
  // R3.13c — canonical client health engine (Product Bible Ch.16, routers/health.py).
  // Replaces the frontend's direct-Supabase health-score-compute.ts.
  health: {
    client: (clientId: string) => request(`/api/health/clients/${clientId}`),
    scores: () => request("/api/health/scores"),
    calculate: (clientId: string) => request(`/api/health/scores/${clientId}/calculate`, { method: "POST" }),
  },
  // Note: the unversioned `documentIntelligence` wrapper (client-side, unused
  // by any page) that pointed at /api/document-intelligence/* was removed in
  // the R2.8 fix phase — that backend router was a retired, undisclosed 4th
  // extraction generation serving hardcoded fabricated data. Real document
  // extraction lives at /api/document-intelligence-v1 and
  // /api/document-intelligence-v2 (called directly via fetch() from the
  // pages that use them, e.g. app/clients/[id]/purchases/page.tsx).
  risks: {
    list: (params?: Record<string, string>) => request(`/api/risks${params ? "?" + new URLSearchParams(params) : ""}`),
    stats: () => request("/api/risks/stats"),
    clientRisks: (clientId: string) => request(`/api/risks/client/${clientId}`),
    update: (riskId: string, data: unknown) => request(`/api/risks/${riskId}`, { method: "PATCH", body: JSON.stringify(data) }),
    firmScore: () => request("/api/risks/firm/score"),
  },
  aiInsights: {
    list: (params?: Record<string, string>) => request(`/api/ai-insights${params ? "?" + new URLSearchParams(params) : ""}`),
    feed: () => request("/api/ai-insights/feed"),
    generate: (clientId: string) => request(`/api/ai-insights/generate/${clientId}`, { method: "POST" }),
    acknowledge: (id: string) => request(`/api/ai-insights/${id}/acknowledge`, { method: "PATCH" }),
    dismiss: (id: string) => request(`/api/ai-insights/${id}/dismiss`, { method: "PATCH" }),
  },
  automation: {
    rules: () => request("/api/automation/rules"),
    toggleRule: (id: string, enabled: boolean) => request(`/api/automation/rules/${id}/toggle`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    executions: () => request("/api/automation/executions"),
    stats: () => request("/api/automation/stats"),
  },
  notifications: {
    list: (unreadOnly?: boolean) => request(`/api/notifications${unreadOnly ? "?unread_only=true" : ""}`),
    count: () => request("/api/notifications/count"),
    markRead: (id: string) => request(`/api/notifications/${id}/read`, { method: "PATCH" }),
    markAllRead: () => request("/api/notifications/read-all", { method: "PATCH" }),
    stats: () => request("/api/notifications/stats"),
  },
  copilot: {
    chat: (body: { message: string; conversation_history: unknown[]; context?: string }) =>
      request("/api/ai-copilot/chat", { method: "POST", body: JSON.stringify(body) }),
    clientChat: (clientId: string, body: { message: string; conversation_history: unknown[] }) =>
      request(`/api/ai-copilot/client/${clientId}/chat`, { method: "POST", body: JSON.stringify(body) }),
  },
  payroll: {
    // client_id omitted -> every client in the firm (firm-wide dashboard);
    // client_id given -> scoped to one client (per-client workspace).
    listEmployees: (clientId?: string) =>
      request(`/api/payroll/employees${clientId ? `?client_id=${clientId}` : ""}`),
    createEmployee: (body: unknown) =>
      request("/api/payroll/employees", { method: "POST", body: JSON.stringify(body) }),
    updateEmployee: (id: string, body: unknown) =>
      request(`/api/payroll/employees/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    listRuns: (clientId?: string) =>
      request(`/api/payroll/runs${clientId ? `?client_id=${clientId}` : ""}`),
    createRun: (body: { client_id: string; month: string }) =>
      request("/api/payroll/runs", { method: "POST", body: JSON.stringify(body) }),
    getRunSlips: (runId: string) => request(`/api/payroll/runs/${runId}/slips`),
    updateRunStatus: (runId: string, status: string) =>
      request(`/api/payroll/runs/${runId}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    finalizeRun: (runId: string) =>
      request(`/api/payroll/runs/${runId}/finalize`, { method: "POST" }),
    downloadPayslip: (slipId: string, fallbackFilename = `payslip-${slipId}.pdf`) =>
      downloadFile(`/api/payroll/salary-slips/${slipId}/pdf`, fallbackFilename),
  },
  invoices: {
    downloadPdf: (id: string) => downloadFile(`/api/invoices/${id}/pdf`, `invoice-${id}.pdf`),
    runOverdueCheck: () => request("/api/invoices/run-overdue-check", { method: "POST" }),
  },
  timeEntries: {
    exportEntries: (params: { fmt: "csv" | "xlsx"; user_id?: string; client_id?: string; date_from?: string; date_to?: string }) => {
      const q = new URLSearchParams(
        Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== "")) as Record<string, string>
      ).toString();
      return downloadFile(`/api/time-entries/export?${q}`, `time-entries.${params.fmt}`);
    },
  },
  onboarding: {
    /** Start a 10-step Product Bible Ch. 7 onboarding checklist for a client. */
    start: (body: { client_id: string; entity_type?: string; notes?: string }) =>
      request("/api/lifecycle/onboarding/checklist", { method: "POST", body: JSON.stringify(body) }),
    /** Get full onboarding progress for a specific checklist workflow. */
    get: (workflowId: string) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}`),
    /** Update a single step in an onboarding checklist. */
    updateStep: (workflowId: string, stepNumber: number, data: { status: string; notes?: string }) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}/step/${stepNumber}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    /** Trigger go-live verification — completes the onboarding and activates the client. */
    complete: (workflowId: string) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}/complete`, { method: "POST" }),
    /** List all active (non-completed) onboarding checklists for the firm. */
    listActive: (firmId?: string) =>
      request(`/api/lifecycle/onboarding/checklist/active${firmId ? `?firm_id=${firmId}` : ""}`),
  },
  workload: {
    capacityList: () => request("/api/workload/capacity"),
    setCapacity: (body: { user_id: string; weekly_capacity_hours: number; max_concurrent_tasks: number }) =>
      request("/api/workload/capacity", { method: "PUT", body: JSON.stringify(body) }),
  },
  intelligence: {
    complianceRisk: () => request("/api/intelligence/compliance-risk"),
    relationshipHealth: () => request("/api/intelligence/relationship-health"),
    recommendations: () => request("/api/intelligence/recommendations"),
    workloadInsights: () => request("/api/intelligence/workload-insights"),
    journalSuggestions: (client_id?: string) =>
      request(`/api/intelligence/journal-suggestions${client_id ? `?client_id=${client_id}` : ""}`),
    approveJournalSuggestion: (body: unknown) =>
      request("/api/intelligence/journal-suggestions/approve", { method: "POST", body: JSON.stringify(body) }),
  },
  taskExtras: {
    dependencies: (taskId: string) => request(`/api/tasks/${taskId}/dependencies`),
    addDependency: (taskId: string, dependsOnTaskId: string) =>
      request(`/api/tasks/${taskId}/dependencies`, { method: "POST", body: JSON.stringify({ depends_on_task_id: dependsOnTaskId }) }),
    removeDependency: (taskId: string, dependencyId: string) =>
      request(`/api/tasks/${taskId}/dependencies/${dependencyId}`, { method: "DELETE" }),
  },
  // Phase 10 — Workflow Automation Engine
  workflowEngine: {
    listTemplates: (params?: Record<string, string>) =>
      request(`/api/workflows/templates${params ? "?" + new URLSearchParams(params) : ""}`),
    getTemplate: (id: string) => request(`/api/workflows/templates/${id}`),
    createTemplate: (body: unknown) =>
      request("/api/workflows/templates", { method: "POST", body: JSON.stringify(body) }),
    updateTemplate: (id: string, body: unknown) =>
      request(`/api/workflows/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    deleteTemplate: (id: string) =>
      request(`/api/workflows/templates/${id}`, { method: "DELETE" }),
    toggleTemplate: (id: string) =>
      request(`/api/workflows/templates/${id}/toggle`, { method: "POST" }),
    triggerTemplate: (id: string, body?: unknown) =>
      request(`/api/workflows/templates/${id}/trigger`, { method: "POST", body: JSON.stringify(body || {}) }),
    listInstances: (params?: Record<string, string>) =>
      request(`/api/workflows/instances${params ? "?" + new URLSearchParams(params) : ""}`),
    getInstance: (id: string) => request(`/api/workflows/instances/${id}`),
    cancelInstance: (id: string) =>
      request(`/api/workflows/instances/${id}/cancel`, { method: "POST" }),
    listApprovals: (params?: Record<string, string>) =>
      request(`/api/workflows/approvals${params ? "?" + new URLSearchParams(params) : ""}`),
    respondApproval: (id: string, body: { decision: string; response_notes?: string }) =>
      request(`/api/workflows/approvals/${id}/respond`, { method: "POST", body: JSON.stringify(body) }),
    listSchedules: (params?: Record<string, string>) =>
      request(`/api/workflows/schedules${params ? "?" + new URLSearchParams(params) : ""}`),
    createSchedule: (body: unknown) =>
      request("/api/workflows/schedules", { method: "POST", body: JSON.stringify(body) }),
    toggleSchedule: (id: string) =>
      request(`/api/workflows/schedules/${id}/toggle`, { method: "PATCH" }),
    deleteSchedule: (id: string) =>
      request(`/api/workflows/schedules/${id}`, { method: "DELETE" }),
    analytics: (params?: Record<string, string>) =>
      request(`/api/workflows/analytics${params ? "?" + new URLSearchParams(params) : ""}`),
    listFailures: (params?: Record<string, string>) =>
      request(`/api/workflows/failures${params ? "?" + new URLSearchParams(params) : ""}`),
    resolveFailure: (id: string) =>
      request(`/api/workflows/failures/${id}/resolve`, { method: "POST" }),
    executions: (params?: Record<string, string>) =>
      request(`/api/workflows/executions${params ? "?" + new URLSearchParams(params) : ""}`),
  },
  // Phase 13 — AI Memory & Intelligence
  memory: {
    getClientProfile: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/profile`),
    computeClientProfile: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/profile/compute`, { method: "POST" }),
    listProfiles: (params?: Record<string, string>) =>
      request("/api/memory/profiles", { params } as RequestInit),
    getFirmProfile: () =>
      request("/api/memory/firm/profile"),
    listTriggers: (params?: Record<string, string>) =>
      request(`/api/memory/triggers${params ? "?" + new URLSearchParams(params) : ""}`),
    acknowledgeTrigger: (id: string) =>
      request(`/api/memory/triggers/${id}/acknowledge`, { method: "POST" }),
    dismissTrigger: (id: string) =>
      request(`/api/memory/triggers/${id}/dismiss`, { method: "POST" }),
    detectClientTriggers: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/detect`, { method: "POST" }),
    listAnomalies: (params?: Record<string, string>) =>
      request(`/api/memory/anomalies${params ? "?" + new URLSearchParams(params) : ""}`),
    updateAnomalyStatus: (id: string, status: string) =>
      request(`/api/memory/anomalies/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    listYearEndReports: () =>
      request("/api/memory/year-end-reports"),
    getYearEndReport: (clientId: string, fy: string) =>
      request(`/api/memory/year-end-reports/${clientId}/${fy}`),
    runPipeline: () =>
      request("/api/memory/pipeline/run", { method: "POST" }),
  },
  // Client Portal
  portal: {
    getDocumentRequests: (firmId: string, clientId: string) =>
      request(`/api/portal/document-requests?firm_id=${firmId}&client_id=${clientId}`),
    createDocumentRequest: (data: {
      firm_id: string;
      client_id: string;
      title: string;
      description?: string;
      due_date?: string;
      is_urgent?: boolean;
    }) =>
      request("/api/portal/document-requests", { method: "POST", body: JSON.stringify(data) }),
    completeDocumentRequest: (id: string) =>
      request(`/api/portal/document-requests/${id}/complete`, { method: "PUT" }),
    getMessages: (firmId: string, clientId: string) =>
      request(`/api/portal/messages?firm_id=${firmId}&client_id=${clientId}`),
    sendMessage: (data: {
      firm_id: string;
      client_id: string;
      text: string;
      from_ca?: boolean;
    }) =>
      request("/api/portal/messages", { method: "POST", body: JSON.stringify(data) }),
    getDues: (firmId: string, clientId: string) =>
      request(`/api/portal/dues?firm_id=${firmId}&client_id=${clientId}`),
    // Phase 4.5.1 — CA-side multi-contact management
    listContacts: (clientId: string) =>
      request<ApiResp<{ contacts: PortalContact[] }>>(`/api/portal/clients/${clientId}/contacts`),
    inviteContact: (clientId: string, body: { email: string; name?: string }) =>
      request<ApiResp<{ contact: PortalContact }>>(
        `/api/portal/clients/${clientId}/contacts`, { method: "POST", body: JSON.stringify(body) }),
    resendInvite: (contactId: string) =>
      request<ApiResp<{ contact: PortalContact }>>(`/api/portal/contacts/${contactId}/resend`, { method: "POST" }),
    deactivateContact: (contactId: string) =>
      request<ApiResp<{ contact: PortalContact }>>(`/api/portal/contacts/${contactId}/deactivate`, { method: "POST" }),
  },
  // Phase 4.5.1 — client-facing portal self surface (auth = the client's own
  // Supabase session, resolved server-side via get_current_portal_client).
  portalSelf: {
    // All client memberships for the signed-in identity (client switcher source).
    memberships: () => request("/api/portal/memberships"),
    // F22 fix: bind ONE client_portal_users invite by its single-use token.
    // Must be called before that client shows up in memberships().
    acceptInvite: (token: string) =>
      request<ApiResp<{ client_id: string; name?: string }>>(
        "/api/portal/accept-invite", { method: "POST", body: JSON.stringify({ token }) }),
    // me/dashboard select the active client explicitly via X-Portal-Client-Id when
    // the identity belongs to more than one client (no implicit switching).
    me: (clientId?: string) =>
      request("/api/portal/me", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    dashboard: (clientId?: string) =>
      request("/api/portal/dashboard", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    // Phase 4.5.2 — client-facing data surfaces. Each carries the active client
    // via X-Portal-Client-Id (explicit selection; no implicit switching). All
    // data is the firm↔client fee relationship + the client's compliance status.
    invoices: (clientId?: string) =>
      request("/api/portal/self/invoices", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    invoicePdf: (invoiceId: string, clientId?: string) =>
      downloadFile(`/api/portal/self/invoices/${invoiceId}/pdf`, `invoice-${invoiceId}.pdf`,
        clientId ? { "X-Portal-Client-Id": clientId } : undefined),
    dues: (clientId?: string) =>
      request("/api/portal/self/dues", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    statement: (clientId?: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return request(`/api/portal/self/statement${qs ? `?${qs}` : ""}`,
        clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined);
    },
    statementPdf: (clientId?: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return downloadFile(`/api/portal/self/statement/pdf${qs ? `?${qs}` : ""}`, "statement.pdf",
        clientId ? { "X-Portal-Client-Id": clientId } : undefined);
    },
    reminders: (clientId?: string) =>
      request("/api/portal/self/reminders", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    compliance: (clientId?: string) =>
      request("/api/portal/self/compliance", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    // Phase 4.6 — Pay Now: create/reuse a payment link for the client's own invoice.
    payInvoice: (invoiceId: string, clientId?: string) =>
      request(`/api/portal/self/invoices/${invoiceId}/pay`,
        { method: "POST", ...(clientId ? { headers: { "X-Portal-Client-Id": clientId } } : {}) }),
  },
  // Phase 4.6 — Online Payments (staff, accounting-gated). The gateway never does
  // accounting; receipts are created by the existing engine on a verified capture.
  payments: {
    createLink: (invoiceId: string) =>
      request("/api/payments/links", { method: "POST", body: JSON.stringify({ invoice_id: invoiceId }) }),
    listLinks: (invoiceId: string) => request(`/api/payments/links?invoice_id=${invoiceId}`),
    sendLink: (linkId: string) => request(`/api/payments/links/${linkId}/send`, { method: "POST" }),
    history: (invoiceId: string) => request(`/api/payments?invoice_id=${invoiceId}`),
  },
  // Phase 11 — AI Copilot Platform
  copilotV2: {
    listConversations: (params?: Record<string, string>) =>
      request(`/api/copilot/conversations${params ? "?" + new URLSearchParams(params) : ""}`),
    createConversation: (body: unknown) =>
      request("/api/copilot/conversations", { method: "POST", body: JSON.stringify(body) }),
    getConversation: (id: string) => request(`/api/copilot/conversations/${id}`),
    archiveConversation: (id: string) =>
      request(`/api/copilot/conversations/${id}/archive`, { method: "POST" }),
    sendMessage: (conversationId: string, body: unknown) =>
      request(`/api/copilot/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify(body) }),
    rateMessage: (messageId: string, body: unknown) =>
      request(`/api/copilot/messages/${messageId}/feedback`, { method: "POST", body: JSON.stringify(body) }),
    quickChat: (body: unknown) =>
      request("/api/copilot/chat", { method: "POST", body: JSON.stringify(body) }),
    suggestions: (context_type?: string) =>
      request(`/api/copilot/suggestions${context_type ? `?context_type=${context_type}` : ""}`),
    clientIntelligence: (clientId: string) =>
      request(`/api/copilot/intelligence/client/${clientId}`),
    complianceIntelligence: () => request("/api/copilot/intelligence/compliance"),
    workflowIntelligence: () => request("/api/copilot/intelligence/workflows"),
    relationshipIntelligence: () => request("/api/copilot/intelligence/relationships"),
    executiveDashboard: () => request("/api/copilot/executive-dashboard"),
    listRecommendations: (params?: Record<string, string>) =>
      request(`/api/copilot/recommendations${params ? "?" + new URLSearchParams(params) : ""}`),
    actRecommendation: (id: string, body: unknown) =>
      request(`/api/copilot/recommendations/${id}/action`, { method: "POST", body: JSON.stringify(body) }),
    executeAction: (body: unknown) =>
      request("/api/copilot/actions", { method: "POST", body: JSON.stringify(body) }),
  },

  // ── Amendment v1.1 (Batch 7) — Practice / Revenue Operations / Knowledge ──
  // Thin fetch wrappers only. All computation (aging, GST, overdue, visibility)
  // is performed server-side; the frontend fetches + displays.
  practice: {
    get: () => request("/api/practice"),
    provision: () => request("/api/practice/provision", { method: "POST" }),
    /** Partner-only maintenance of the practice client's tax identity (PAN/GSTIN/state). */
    updateIdentity: (body: { pan?: string; gstin?: string; state?: string; state_code?: string }) =>
      request("/api/practice/identity", { method: "PATCH", body: JSON.stringify(body) }),
  },
  // Platform Admin (Super Admin) — cross-firm; gated server-side by the
  // platform_admins allowlist, completely separate from firm RBAC.
  platform: {
    me: () => request<ApiResp<{ is_platform_admin: boolean }>>("/api/platform/me"),
    stats: () => request<ApiResp<{ total_firms: number; active_firms: number; suspended_firms: number; total_users: number; total_clients: number }>>("/api/platform/stats"),
    firms: () => request<ApiResp<Array<{ id: string; name: string; created_at: string; users: number; clients: number; status: string }>>>("/api/platform/firms"),
    firm: (id: string) => request<ApiResp<{ id: string; name: string; email: string; created_at: string; status: string; users: number; clients: number }>>(`/api/platform/firms/${id}`),
    firmUsers: (id: string) => request<ApiResp<Array<{ name: string; email: string; role: string; status: string }>>>(`/api/platform/firms/${id}/users`),
    suspend: (id: string, reason: string) => request(`/api/platform/firms/${id}/suspend`, { method: "POST", body: JSON.stringify({ reason }) }),
    unsuspend: (id: string) => request(`/api/platform/firms/${id}/unsuspend`, { method: "POST" }),
    softDelete: (id: string) => request(`/api/platform/firms/${id}`, { method: "DELETE" }),
    /** PERMANENT hard delete — requires a fresh aal2 (MFA) token. Irreversible. */
    purge: (id: string) => request(`/api/platform/firms/${id}/permanent`, { method: "DELETE" }),
  },
  account: {
    /**
     * Bootstrap a brand-new firm + first Partner user. Runs server-side
     * (service-role) so it is not blocked by the firm-isolation RLS that forbids
     * a firm-less user from inserting a firms row. Seeds the master CoA and
     * provisions the internal client when a PAN is supplied.
     */
    createFirm: (body: {
      firm_name: string;
      firm_email: string;
      partner_name: string;
      pan?: string;
      gstin?: string;
      phone?: string;
      address?: string;
      city?: string;
      state?: string;
      entity_type?: string;
    }) => request<ApiResp<{ firm: { id: string; name: string } }>>(
      "/api/onboarding/firm",
      { method: "POST", body: JSON.stringify(body) },
    ),
    /** Idempotently seed the firm's canonical master CoA (backend = single source of truth). */
    seedCoa: () => request<ApiResp<{ seeded: number; skipped: boolean }>>(
      "/api/onboarding/seed-coa",
      { method: "POST" },
    ),
  },
  billing: {
    listSchedules: (activeOnly?: boolean) =>
      request(`/api/billing/schedules${activeOnly ? "?active_only=true" : ""}`),
    createSchedule: (body: unknown) =>
      request("/api/billing/schedules", { method: "POST", body: JSON.stringify(body) }),
    previewRun: (asOf?: string) =>
      request(`/api/billing/preview-run${asOf ? `?as_of=${asOf}` : ""}`, { method: "POST" }),
    generate: (scheduleId: string) =>
      request(`/api/billing/schedules/${scheduleId}/generate`, { method: "POST" }),
    run: () => request("/api/billing/run", { method: "POST" }),
    arAging: () => request("/api/billing/ar-aging"),
    dashboard: (params?: Record<string, string>) =>
      request(`/api/billing/collections/dashboard${params ? "?" + new URLSearchParams(params) : ""}`),
    sweep: () => request("/api/billing/collections/sweep", { method: "POST" }),
    sendReminders: () => request("/api/billing/collections/send-reminders", { method: "POST" }),
    unbilledWork: (clientId?: string) =>
      request(`/api/billing/unbilled-work${clientId ? `?client_id=${clientId}` : ""}`),
    listCostRates: () => request("/api/billing/staff-cost-rates"),
    setCostRate: (userId: string, costRatePaise: number | null) =>
      request(`/api/billing/staff-cost-rates/${userId}`, {
        method: "PUT", body: JSON.stringify({ cost_rate_paise: costRatePaise }),
      }),
    // Fee Billing (apps/web/app/billing/page.tsx) receipts — only marks the
    // invoice Paid once cumulative receipts cover its total.
    recordFeeReceipt: (invoiceId: string, data: unknown) =>
      request(`/api/billing/fee-invoices/${invoiceId}/receipts`, {
        method: "POST", body: JSON.stringify(data),
      }),
  },
  salesInvoices: {
    list: (clientId: string, params?: Record<string, string>) =>
      request(`/api/sales-invoices/?client_id=${clientId}${params ? "&" + new URLSearchParams(params) : ""}`),
    get: (id: string) => request(`/api/sales-invoices/${id}`),
    issue: (id: string) => request(`/api/sales-invoices/${id}/issue`, { method: "POST" }),
    unposted: (clientId?: string) =>
      request(`/api/sales-invoices/maintenance/unposted${clientId ? `?client_id=${clientId}` : ""}`),
    downloadPdf: (id: string, invoiceNo?: string) =>
      downloadFile(`/api/sales-invoices/${id}/pdf`, `invoice-${invoiceNo ?? id}.pdf`),
    send: (id: string, toEmail?: string) =>
      request(`/api/sales-invoices/${id}/send`, { method: "POST", body: JSON.stringify({ to_email: toEmail ?? null }) }),
    resend: (id: string, toEmail?: string) =>
      request(`/api/sales-invoices/${id}/resend`, { method: "POST", body: JSON.stringify({ to_email: toEmail ?? null }) }),
    deliveries: (id: string) => request(`/api/sales-invoices/${id}/deliveries`),
  },
  hsn: {
    // Smart HSN/SAC lookup — the firm's own library + firm history. Never
    // reads a Caflow-shipped master (HSN/SAC redesign). See routers/hsn.py.
    search: (q: string, opts?: { client_id?: string; type?: string; limit?: number }) => {
      const params = new URLSearchParams({ q });
      if (opts?.client_id) params.set("client_id", opts.client_id);
      if (opts?.type) params.set("type", opts.type);
      if (opts?.limit) params.set("limit", String(opts.limit));
      return request(`/api/hsn/search?${params.toString()}`);
    },
  },
  serviceCatalogue: {
    // Product & Service master (goods + services) — client-owned
    // (migration 182: "Client B must never inherit Client A's products").
    // hsn_sac must be a code from the firm-wide firmHsnLibrary. See
    // routers/service_catalogue.py.
    list: (clientId: string, opts?: { q?: string; include_archived?: boolean; limit?: number }) => {
      const p = new URLSearchParams({ client_id: clientId });
      if (opts?.q) p.set("q", opts.q);
      if (opts?.include_archived) p.set("include_archived", "true");
      if (opts?.limit) p.set("limit", String(opts.limit));
      return request(`/api/service-catalogue/?${p.toString()}`);
    },
    create: (body: unknown) =>
      request("/api/service-catalogue/", { method: "POST", body: JSON.stringify(body) }),
    // One request for a whole CSV import instead of one POST per row.
    // openingBalanceDate is ONE "as of" date for the whole batch (an
    // opening-stock import is a single conversion event, not N independent
    // ones) — omit to let the backend default to each row's client's
    // financial-year start.
    bulkCreate: (services: unknown[], openingBalanceDate?: string) =>
      request("/api/service-catalogue/bulk", {
        method: "POST",
        body: JSON.stringify({ services, opening_balance_date: openingBalanceDate || undefined }),
      }),
    update: (id: string, body: unknown) =>
      request(`/api/service-catalogue/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    // Only succeeds when the item has never been picked into a transaction
    // line (use_count === 0) — the backend rejects (success:false) otherwise
    // with a message pointing at Archive instead. See routers/service_catalogue.py.
    delete: (id: string) =>
      request(`/api/service-catalogue/${id}`, { method: "DELETE" }),
    recordUsed: (id: string) =>
      request(`/api/service-catalogue/${id}/used`, { method: "POST" }),
  },
  firmHsnLibrary: {
    // The firm's own CA-owned, CA-curated HSN/SAC codes — the only source
    // Products/Services and invoice lines select from. Caflow ships no
    // shared master here. See routers/firm_hsn_library.py.
    list: (opts?: { q?: string; hsn_type?: string; include_archived?: boolean; limit?: number }) => {
      const p = new URLSearchParams();
      if (opts?.q) p.set("q", opts.q);
      if (opts?.hsn_type) p.set("hsn_type", opts.hsn_type);
      if (opts?.include_archived) p.set("include_archived", "true");
      if (opts?.limit) p.set("limit", String(opts.limit));
      const qs = p.toString();
      return request(`/api/firm-hsn-library/${qs ? `?${qs}` : ""}`);
    },
    add: (body: unknown) =>
      request("/api/firm-hsn-library/", { method: "POST", body: JSON.stringify(body) }),
    // One request for a whole CSV import instead of one POST per row.
    bulkAdd: (codes: unknown[]) =>
      request("/api/firm-hsn-library/bulk", { method: "POST", body: JSON.stringify({ codes }) }),
    update: (id: string, body: unknown) =>
      request(`/api/firm-hsn-library/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    retire: (id: string) =>
      request(`/api/firm-hsn-library/${id}`, { method: "DELETE" }),
    // Permanent delete — blocked server-side if the code is still referenced
    // anywhere (Product/Service catalogue, any invoice/note/bill line).
    purge: (id: string) =>
      request(`/api/firm-hsn-library/${id}/purge`, { method: "DELETE" }),
    bulkPurge: (ids: string[]) =>
      request("/api/firm-hsn-library/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) }),
  },
  firmHsnRateHistory: {
    // CA-entered, validity-dated GST rate versions per library code
    // (Decision D: mechanism only, never a Caflow-authoritative rate).
    // See routers/firm_hsn_rate_history.py.
    list: (firmHsnLibraryId: string) =>
      request(`/api/firm-hsn-rate-history/?firm_hsn_library_id=${encodeURIComponent(firmHsnLibraryId)}`),
    resolve: (firmHsnLibraryId: string, asOf: string) =>
      request(
        `/api/firm-hsn-rate-history/resolve?firm_hsn_library_id=${encodeURIComponent(firmHsnLibraryId)}&as_of=${encodeURIComponent(asOf)}`,
      ),
    add: (body: unknown) =>
      request("/api/firm-hsn-rate-history/", { method: "POST", body: JSON.stringify(body) }),
    remove: (id: string) =>
      request(`/api/firm-hsn-rate-history/${id}`, { method: "DELETE" }),
  },
  receipts: {
    create: (body: unknown) =>
      request("/api/receipts/", { method: "POST", body: JSON.stringify(body) }),
  },
  knowledge: {
    listArticles: (params?: Record<string, string>) =>
      request(`/api/knowledge/articles${params ? "?" + new URLSearchParams(params) : ""}`),
    createArticle: (body: unknown) =>
      request("/api/knowledge/articles", { method: "POST", body: JSON.stringify(body) }),
    getArticle: (id: string) => request(`/api/knowledge/articles/${id}`),
    listVersions: (id: string) => request(`/api/knowledge/articles/${id}/versions`),
    editArticle: (id: string, content: string) =>
      request(`/api/knowledge/articles/${id}/versions`, { method: "POST", body: JSON.stringify({ content }) }),
    restoreVersion: (id: string, version: number) =>
      request(`/api/knowledge/articles/${id}/restore/${version}`, { method: "POST" }),
    archiveArticle: (id: string) =>
      request(`/api/knowledge/articles/${id}/archive`, { method: "POST" }),
    clientArticles: (clientId: string, query?: string) =>
      request(`/api/clients/${clientId}/knowledge${query ? `?query=${encodeURIComponent(query)}` : ""}`),
  },
  instructions: {
    list: (clientId: string) => request(`/api/clients/${clientId}/instructions`),
    create: (clientId: string, body: unknown) =>
      request(`/api/clients/${clientId}/instructions`, { method: "POST", body: JSON.stringify(body) }),
    update: (clientId: string, id: string, body: unknown) =>
      request(`/api/clients/${clientId}/instructions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    archive: (clientId: string, id: string) =>
      request(`/api/clients/${clientId}/instructions/${id}/archive`, { method: "POST" }),
  },
  // M2: authorization-scoped global search (server enforces client assignment).
  search: (q: string) =>
    request(`/api/search?q=${encodeURIComponent(q)}`) as Promise<
      ApiResp<{ results: { id: string; category: string; title: string; subtitle?: string; href: string }[] }>
    >,
  // M3: client-assignment administration (Partner writes; Manager+ reads).
  assignments: {
    listForUser: (userId: string) =>
      request(`/api/assignments/users/${userId}`) as Promise<ApiResp<{ user_id: string; client_ids: string[] }>>,
    listForClient: (clientId: string) =>
      request(`/api/assignments/clients/${clientId}`) as Promise<ApiResp<{ client_id: string; user_ids: string[] }>>,
    create: (user_id: string, client_id: string) =>
      request("/api/assignments", { method: "POST", body: JSON.stringify({ user_id, client_id }) }),
    bulkCreate: (user_id: string, client_ids: string[]) =>
      request("/api/assignments/bulk", { method: "POST", body: JSON.stringify({ user_id, client_ids }) }),
    remove: (user_id: string, client_id: string) =>
      request(`/api/assignments?user_id=${encodeURIComponent(user_id)}&client_id=${encodeURIComponent(client_id)}`,
              { method: "DELETE" }),
  },
  // M4: governance approval workflows (maker-checker). Executive+ requests;
  // Partner approves/rejects; Manager+ reads.
  approvals: {
    list: (status?: string) =>
      request(`/api/approvals${status ? `?status=${status}` : ""}`) as Promise<
        ApiResp<{ requests: ApprovalRequest[] }>
      >,
    get: (id: string) => request(`/api/approvals/${id}`) as Promise<ApiResp<ApprovalRequest>>,
    create: (request_type: string, payload: Record<string, unknown>) =>
      request("/api/approvals", { method: "POST", body: JSON.stringify({ request_type, payload }) }),
    approve: (id: string) => request(`/api/approvals/${id}/approve`, { method: "POST" }),
    reject: (id: string, reason?: string) =>
      request(`/api/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
    cancel: (id: string) => request(`/api/approvals/${id}/cancel`, { method: "POST" }),
  },
  // Module 9.0/M1: authoritative, append-only audit trail (Partner-only read).
  // Backed by the audit_log table, written server-side by audit_service.log_event
  // across every sensitive mutation (journals, invoices, compliance, clients,
  // users/roles, year-end, GST/TDS, platform actions, …).
  audit: {
    list: (params?: { entity_type?: string; entity_id?: string; actor_id?: string; limit?: number }) => {
      const q = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request(`/api/audit${q ? `?${q}` : ""}`) as Promise<
        ApiResp<{ entries: AuditEntry[]; total: number }>
      >;
    },
  },
  // Firm Branding & Document Customization
  branding: {
    get: () => request("/api/settings/branding"),
    update: (body: unknown) =>
      request("/api/settings/branding", { method: "PUT", body: JSON.stringify(body) }),
    uploadLogo: async (file: File) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE_URL}/api/settings/branding/logo`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      return res.json();
    },
  },
  invoiceSettings: {
    get: () => request("/api/settings/invoice-settings"),
    update: (body: unknown) =>
      request("/api/settings/invoice-settings", { method: "PUT", body: JSON.stringify(body) }),
  },
  invoiceTemplates: {
    list: () => request("/api/settings/invoice-templates"),
    create: (body: unknown) =>
      request("/api/settings/invoice-templates", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) =>
      request(`/api/settings/invoice-templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request(`/api/settings/invoice-templates/${id}`, { method: "DELETE" }),
    setDefault: (id: string) =>
      request(`/api/settings/invoice-templates/${id}/set-default`, { method: "POST" }),
  },
  emailTemplates: {
    list: () => request("/api/settings/email-templates"),
    upsert: (body: unknown) =>
      request("/api/settings/email-templates", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) =>
      request(`/api/settings/email-templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request(`/api/settings/email-templates/${id}`, { method: "DELETE" }),
  },
  // M6: identity administration (audited, server-side; Partner-only writes).
  identity: {
    listUsers: () => request<ApiResp<{
      users: Array<{
        id: string; full_name: string; email: string; role: string;
        is_active?: boolean; created_at?: string; auth_user_id?: string; firm_id?: string;
      }>;
    }>>("/api/identity/users"),
    createUser: (full_name: string, email: string, role: string) =>
      request<ApiResp<{ id: string; invite_token: string }>>(
        "/api/identity/users", { method: "POST", body: JSON.stringify({ full_name, email, role }) }),
    // F21 fix: the only way a users row's auth_user_id can be set — token comes
    // from createUser's response, never from URL params.
    acceptInvite: (token: string) =>
      request<ApiResp<{ firm_id: string; role: string; full_name?: string }>>(
        "/api/identity/accept-invite", { method: "POST", body: JSON.stringify({ token }) }),
    changeRole: (userId: string, role: string) =>
      request(`/api/identity/users/${userId}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
    suspend: (userId: string) => request(`/api/identity/users/${userId}/suspend`, { method: "POST" }),
    reactivate: (userId: string) => request(`/api/identity/users/${userId}/reactivate`, { method: "POST" }),
    forceLogout: (userId: string) => request(`/api/identity/users/${userId}/force-logout`, { method: "POST" }),
    forceLogoutAll: () => request("/api/identity/force-logout-all", { method: "POST" }),
    loginHistory: () =>
      request("/api/identity/login-history") as Promise<ApiResp<{ events: LoginEvent[] }>>,
    recordLoginEvent: (event: "login" | "logout") =>
      request("/api/identity/login-event", { method: "POST", body: JSON.stringify({ event }) }),
  },
};

export type AuditEntry = {
  id: string;
  firm_id: string;
  actor_id?: string | null;
  actor_email?: string | null;
  entity_type: string;
  entity_id?: string | null;
  action: string;
  old_data?: Record<string, unknown> | null;
  new_data?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export type LoginEvent = {
  id: string; user_id?: string; email?: string; event: string;
  ip?: string; user_agent?: string; created_at?: string;
};

export type ApprovalRequest = {
  id: string;
  request_type: string;
  summary?: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  payload?: Record<string, unknown>;
  requested_by_email?: string;
  decided_by_email?: string;
  reason?: string;
  created_at?: string;
};
