const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }
  return res.json();
}

export const api = {
  clients: {
    list: () => request<import("@/lib/types").ApiResponse<{ clients: import("@/lib/types").Client[]; total: number }>>("/api/clients"),
    getWorkspace: (id: string) => request<import("@/lib/types").ApiResponse<import("@/lib/types").ClientWorkspace>>(`/api/clients/${id}`),
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
};
