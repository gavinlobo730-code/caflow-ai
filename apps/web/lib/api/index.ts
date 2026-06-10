import { supabase } from "@/lib/supabase/client";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }
  return res.json();
}

/** Fetch a binary endpoint with auth and trigger a browser blob download. */
async function downloadFile(path: string, fallbackFilename: string): Promise<void> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
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
  workflows: {
    list: () => request("/api/workflows"),
    get: (id: string) => request(`/api/workflows/${id}`),
    instantiate: (id: string, body: unknown) =>
      request(`/api/workflows/${id}/instantiate`, { method: "POST", body: JSON.stringify(body) }),
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
    ledger: (accountId: string, params?: Record<string, string>) => request(`/api/accounting/ledger?account_id=${accountId}${params ? "&" + new URLSearchParams(params) : ""}`),
    trialBalance: (asOfDate?: string) => request(`/api/accounting/trial-balance${asOfDate ? "?as_of_date=" + asOfDate : ""}`),
    profitLoss: (params?: Record<string, string>) => request(`/api/accounting/profit-loss${params ? "?" + new URLSearchParams(params) : ""}`),
    balanceSheet: (params?: Record<string, string>) => request(`/api/accounting/balance-sheet${params ? "?" + new URLSearchParams(params) : ""}`),
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
  documentIntelligence: {
    list: (client_id?: string) => request(`/api/document-intelligence/documents${client_id ? `?client_id=${client_id}` : ""}`),
    stats: () => request("/api/document-intelligence/stats"),
    getExtraction: (docId: string) => request(`/api/document-intelligence/${docId}/extraction`),
    triggerExtraction: (docId: string) => request(`/api/document-intelligence/${docId}/extract`, { method: "POST" }),
    getRisks: (docId: string) => request(`/api/document-intelligence/${docId}/risks`),
    resolveRisk: (docId: string, riskId: string) => request(`/api/document-intelligence/${docId}/risks/${riskId}/resolve`, { method: "POST" }),
  },
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
};
