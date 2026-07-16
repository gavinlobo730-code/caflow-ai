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

// Matches the year_end_checklists_status_check CHECK constraint (migration
// 155) — the router's _VALID_ITEM_STATUSES, not 067's original (unused)
// 'not_started'/'na' vocabulary.
export type ChecklistItemStatus = "pending" | "in_progress" | "complete" | "not_applicable";

export interface ChecklistItem {
  id: string;
  engagement_id: string;
  category: string;
  item_label: string;
  status: ChecklistItemStatus;
  notes: string | null;
  completed_by: string | null;
  completed_at: string | null;
  sequence_no: number;
}

export type AdjustmentType =
  | "accrual"
  | "prepayment"
  | "provision"
  | "reclassification"
  | "depreciation_adj"
  | "manual";

// Matches the year_end_adjustments status CHECK constraint (migration 067).
export type AdjustmentStatus = "draft" | "pending_review" | "approved" | "posted" | "rejected";

export interface Adjustment {
  id: string;
  engagement_id: string;
  adjustment_type: AdjustmentType;
  description: string;
  debit_account_id: string;
  credit_account_id: string;
  debit_account_name?: string;
  credit_account_name?: string;
  amount_paise: number;
  adjustment_date: string;
  reference_no: string | null;
  status: AdjustmentStatus;
  created_at: string;
}

// Matches routers/year_end_statements.py:list_versions's actual SELECT — a
// lightweight row that deliberately omits the (potentially large)
// statement_data JSONB blob. Fetch a specific version's full data via
// getVersion() below, not from this list.
export interface FinancialStatementVersion {
  id: string;
  engagement_id: string;
  version_number: number;
  version_label: string | null;
  notes: string | null;
  trial_balance_hash: string | null;
  created_by: string | null;
  created_at: string;
}

// The generate_financial_statements() return shape (services/
// year_end_financial_service.py) — Schedule III line items come back as flat
// {line_code: amount_paise} dicts (BS_EQUITY_LIABILITY_LINES/BS_ASSET_LINES/
// PL_INCOME_LINES/PL_EXPENSE_LINES), not pre-grouped or labelled; the
// frontend maps line codes to Schedule III groups/labels for display.
export interface FinancialStatementSnapshotData {
  balance_sheet: {
    equity_and_liabilities: Record<string, number>;
    assets: Record<string, number>;
    total_equity_and_liabilities_paise: number;
    total_assets_paise: number;
    is_balanced: boolean;
  };
  profit_loss: {
    income: Record<string, number>;
    expenses: Record<string, number>;
    total_income_paise?: number;
    total_expense_paise?: number;
    profit_before_tax_paise: number;
    tax_expense_paise: number;
    profit_after_tax_paise: number;
  };
  trial_balance_hash: string;
  fy_start: string;
  fy_end: string;
}

// GET .../versions/{id} and the snapshot-create response both return a full
// financial_statement_versions row: the lightweight fields above plus
// statement_data.
export type FinancialStatementVersionDetail = FinancialStatementVersion & {
  statement_data: FinancialStatementSnapshotData;
};

export interface NoteToAccount {
  id: string;
  engagement_id: string;
  sequence_no: number;
  note_number: number; // alias for sequence_no, set by router
  note_type: string;
  type: "auto" | "manual"; // derived from is_auto_generated
  title: string;
  content: string | null;
  is_locked: boolean;
  is_auto_generated: boolean;
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
  version_number?: number;
  generated_by?: string;
  generated_at?: string;
  created_by: string;
  created_at: string;
  download_url: string | null;
  is_draft?: boolean;
  storage_path?: string;
  financial_year?: string;
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
        `/api/year-end/${engagementId}/checklist`
      ),
    updateItem: (engagementId: string, itemId: string, body: { status?: ChecklistItemStatus; notes?: string }) =>
      request<{ success: boolean; data: ChecklistItem; error: string | null }>(
        `/api/year-end/${engagementId}/checklist/${itemId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      ),
    // There is no checklist-specific submit endpoint on the backend — "Submit
    // for Review" from the Checklist tab is the same draft -> in_review
    // transition as the Review tab's Submit button (routers/
    // year_end_reviews.py::submit_for_review), just triggered from here too.
    submitForReview: (engagementId: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews/submit-for-review`,
        { method: "POST" }
      ),
  },

  adjustments: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: Adjustment[]; error: string | null }>(
        `/api/year-end/${engagementId}/adjustments`
      ),
    create: (
      engagementId: string,
      body: {
        adjustment_type: AdjustmentType;
        description: string;
        debit_account_id: string;
        credit_account_id: string;
        amount_paise: number;
        adjustment_date: string;
        reference_no?: string;
      }
    ) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/${engagementId}/adjustments`,
        { method: "POST", body: JSON.stringify(body) }
      ),
    submit: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/${engagementId}/adjustments/${adjId}/submit`,
        { method: "POST" }
      ),
    approve: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/${engagementId}/adjustments/${adjId}/approve`,
        { method: "POST" }
      ),
    post: (engagementId: string, adjId: string) =>
      request<{ success: boolean; data: Adjustment; error: string | null }>(
        `/api/year-end/${engagementId}/adjustments/${adjId}/post`,
        { method: "POST" }
      ),
  },

  financialStatements: {
    // Backend route is GET /api/year-end/{engagement_id}/financial-statements
    // (registered by routers/year_end_statements.py, prefix "/year-end" — it
    // never has an "engagements/" segment and there is no "/live" suffix
    // route at all). The handler itself generates the statements fresh from
    // the GL on every call (see generate_financial_statements in
    // services/year_end_financial_service.py) — it IS the live view; saved
    // snapshots are the separate /financial-statements/versions endpoint.
    getLive: (engagementId: string) =>
      request<{ success: boolean; data: FinancialStatementSnapshotData; error: string | null }>(
        `/api/year-end/${engagementId}/financial-statements`
      ),
    versions: (engagementId: string) =>
      request<{ success: boolean; data: FinancialStatementVersion[]; error: string | null }>(
        `/api/year-end/${engagementId}/financial-statements/versions`
      ),
    // versions() above deliberately omits statement_data (list_versions'
    // own SELECT excludes it) — fetch a specific version's full Balance
    // Sheet/P&L data on demand via this endpoint (get_version, which does
    // select("*")) when the CA picks it from the version dropdown.
    getVersion: (engagementId: string, versionId: string) =>
      request<{ success: boolean; data: FinancialStatementVersionDetail; error: string | null }>(
        `/api/year-end/${engagementId}/financial-statements/versions/${versionId}`
      ),
    createSnapshot: (engagementId: string) =>
      request<{ success: boolean; data: FinancialStatementVersionDetail; error: string | null }>(
        `/api/year-end/${engagementId}/financial-statements/snapshot`,
        { method: "POST" }
      ),
  },

  notes: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: NoteToAccount[]; error: string | null }>(
        `/api/year-end/${engagementId}/notes`
      ),
    generateAll: (engagementId: string) =>
      request<{ success: boolean; data: NoteToAccount[]; error: string | null }>(
        `/api/year-end/${engagementId}/notes/generate`,
        { method: "POST" }
      ),
    update: (engagementId: string, noteId: string, body: { content: string }) =>
      request<{ success: boolean; data: NoteToAccount; error: string | null }>(
        `/api/year-end/${engagementId}/notes/${noteId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      ),
    lock: (engagementId: string, noteId: string) =>
      request<{ success: boolean; data: NoteToAccount; error: string | null }>(
        `/api/year-end/${engagementId}/notes/${noteId}/lock`,
        { method: "POST" }
      ),
  },

  review: {
    get: (engagementId: string) =>
      request<{ success: boolean; data: { steps: ReviewStep[]; history: ReviewHistory[] }; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews`
      ),
    submitForReview: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews/submit-for-review`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    approve: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews/approve`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    requestRevision: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews/request-revision`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
    finalApprove: (engagementId: string, comment?: string) =>
      request<{ success: boolean; data: YearEndEngagement; error: string | null }>(
        `/api/year-end/engagements/${engagementId}/reviews/final-approve`,
        { method: "POST", body: JSON.stringify({ comment }) }
      ),
  },

  exports: {
    list: (engagementId: string) =>
      request<{ success: boolean; data: ExportRecord[]; error: string | null }>(
        `/api/year-end/${engagementId}/exports`
      ),
    // routers/year_end_exports.py has no generic "generate" endpoint — it's
    // 3 separate handlers, one per export type, each building a different
    // PDF (generate_financial_statements_pdf / generate_notes_pdf /
    // generate_complete_pack_pdf). export_type in the body was never read.
    generate: (engagementId: string, exportType: "financial_statements" | "notes" | "complete_pack") => {
      const path = exportType === "financial_statements" ? "financial-statements"
        : exportType === "notes" ? "notes"
        : "complete-pack";
      return request<{ success: boolean; data: ExportRecord; error: string | null }>(
        `/api/year-end/${engagementId}/exports/${path}`,
        { method: "POST" }
      );
    },
    // Export records don't carry a download URL — generating one only
    // records the storage path; a signed URL (1hr expiry) is minted on
    // demand by this endpoint.
    download: (engagementId: string, exportId: string) =>
      request<{ success: boolean; data: { download_url: string; expires_in_seconds: number }; error: string | null }>(
        `/api/year-end/${engagementId}/exports/${exportId}/download`
      ),
  },
};
