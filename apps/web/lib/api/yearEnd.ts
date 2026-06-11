/**
 * Year End API client
 * All calls go through the shared request helper in lib/api/index.ts pattern.
 */

import { supabase } from "@/lib/supabase/client";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
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

// ── Types ─────────────────────────────────────────────────────────────────

export type EngagementStatus = "draft" | "in_review" | "approved" | "locked";

export interface YearEndEngagement {
  id: string;
  client_id: string;
  financial_year: string;
  status: EngagementStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export type ChecklistItemStatus = "not_started" | "in_progress" | "complete" | "na";

export interface ChecklistItem {
  id: string;
  engagement_id: string;
  category: string;
  label: string;
  status: ChecklistItemStatus;
  notes: string | null;
  completed_by: string | null;
  completed_at: string | null;
  sort_order: number;
}

export type AdjustmentType =
  | "accrual"
  | "prepayment"
  | "provision"
  | "reclassification"
  | "depreciation_adj"
  | "manual";

export type AdjustmentStatus = "draft" | "submitted" | "approved" | "posted";

export interface Adjustment {
  id: string;
  engagement_id: string;
  type: AdjustmentType;
  description: string;
  debit_account_id: string;
  credit_account_id: string;
  debit_account_name?: string;
  credit_account_name?: string;
  amount_paise: number;
  adj_date: string;
  notes: string | null;
  status: AdjustmentStatus;
  created_at: string;
}

export interface FinancialStatementVersion {
  id: string;
  engagement_id: string;
  version_number: number;
  generated_at: string;
  generated_by: string | null;
  balance_sheet: Record<string, unknown>;
  profit_loss: Record<string, unknown>;
  is_balanced: boolean;
}

export interface NoteToAccount {
  id: string;
  engagement_id: string;
  note_number: number;
  type: "auto" | "manual";
  title: string;
  content: string | null;
  is_locked: boolean;
  updated_at: string;
}

export type ReviewStatus = "draft" | "in_review" | "approved" | "locked";

export interface ReviewStep {
  step: "prepared" | "reviewed" | "approved";
  user_name: string | null;
  user_role: string | null;
  completed_at: string | null;
  comment: string | null;
}

export interface ReviewHistory {
  id: string;
  engagement_id: string;
  action: string;
  performed_by: string;
  performed_at: string;
  comment: string | null;
  from_status: ReviewStatus | null;
  to_status: ReviewStatus;
}

export interface ExportRecord {
  id: string;
  engagement_id: string;
  export_type: "financial_statements" | "notes" | "complete_pack";
  version_number: number;
  generated_by: string;
  generated_at: string;
  download_url: string | null;
  is_draft: boolean;
}

export interface YearEndEvent {
  id: string;
  engagement_id: string;
  event_type: string;
  description: string;
  actor: string | null;
  created_at: string;
}

// ── API functions ─────────────────────────────────────────────────────────

export const yearEndApi = {
  engagements: {
    list: (client_id: string) =>
      request<{ success: boolean; data: YearEndEngagement[]; error: string | null }>(
        `/api/year-end/engagements?client_id=${client_id}`
      ),
    create: (body: { client_id: string; financial_year: string }) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        "/api/year-end/engagements",
        { method: "POST", body: JSON.stringify(body) }
      ),
    get: (id: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${id}`
      ),
  },

  checklist: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: ChecklistItem[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/checklist`
      ),
    updateItem: (engagementId: string, itemId: string, body: { status?: ChecklistItemStatus; notes?: string }) =>
      request<{ success: boolean; data: ChecklistItem; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/checklist/${itemId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      ),
    submitForReview: (engagementId: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/checklist/submit`,
        { method: "POST" }
      ),
  },

  adjustments: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: Adjustment[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/adjustments`
      ),
    create: (
      engagementId: string,
      body: {
        type: AdjustmentType;
        description: string;
        debit_account_id: string;
        credit_account_id: string;
        amount_paise: number;
        adj_date: string;
        notes?: string;
      }
    ) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/adjustments`,
        { method: "POST", body: JSON.stringify(body) }
      ),
    submit: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/adjustments/${adjId}/submit`,
        { method: "POST" }
      ),
    approve: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/adjustments/${adjId}/approve`,
        { method: "POST" }
      ),
    post: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/adjustments/${adjId}/post`,
        { method: "POST" }
      ),
  },

  financialStatements: {
    getLive: (engagementId: string) =>
      request<{ success: boolean; data: { balance_sheet: Record<string, unknown>; profit_loss: Record<string, unknown>; is_balanced: boolean }; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/financial-statements/live`
      ),
    versions: (engagementId: string) =>
      request<{ success: boolean; data: FinancialStatementVersion[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/financial-statements/versions`
      ),
    createSnapshot: (engagementId: string) =>
      request<{ success: boolean; data: FinancialStatementVersion; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/financial-statements/snapshot`,
        { method: "POST" }
      ),
  },

  notes: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: NoteToAccount[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/notes`
      ),
    generateAll: (engagementId: string) =>
      request<{ success: boolean; data: NoteToAccount[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/notes/generate`,
        { method: "POST" }
      ),
    update: (engagementId: string, noteId: string, body: { content: string }) =>
      request<{ success: boolean; data: NoteToAccount; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/notes/${noteId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      ),
    lock: (engagementId: string, noteId: string) =>
      request<{ success: boolean; data: NoteToAccount; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/notes/${noteId}/lock`,
        { method: "POST" }
      ),
  },

  review: {
    get: (engagementId: string) =>
      request<{ success: boolean; data: { steps: ReviewStep[]; history: ReviewHistory[] }; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/review`
      ),
    submitForReview: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/review/submit`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    approve: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/review/approve`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    requestRevision: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/review/request-revision`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    finalApprove: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/review/final-approve`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
  },

  exports: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: ExportRecord[]; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/exports`
      ),
    generate: (engagementId: string, exportType: "financial_statements" | "notes" | "complete_pack") =>
      request<{ success: boolean; data: ExportRecord; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/exports/generate`,
        { method: "POST", body: JSON.stringify({ export_type: exportType }) }
      ),
  },

  dashboard: {
    get: (engagementId: string) =>
      request<{
        success: boolean;
        data: {
          engagement: YearEndEngagement;
          checklist_total: number;
          checklist_complete: number;
          adjustments_count: number;
          adjustments_total_paise: number;
          current_version: number | null;
          statements_generated_at: string | null;
          recent_events: YearEndEvent[];
        };
        error: string | null;
      }>(`/api/year-end/engagements/${engagementId}/dashboard`),
  },
};
