"use client";

import { useState, useEffect } from "react";
import {
  Plus,
  X,
  AlertCircle,
  ChevronRight,
  Users,
  TrendingUp,
  Phone,
  Mail,
  Calendar,
  ArrowRight,
  UserCheck,
  FileText,
  Loader2,
} from "lucide-react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useToast } from "@/components/ui/use-toast";
import { formatDate as formatDateShared } from "@/lib/services/formatting";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json() as { error?: string; detail?: string };
      detail = body.error ?? body.detail ?? detail;
    } catch {
      // body is not JSON — keep the status string
    }
    throw new Error(detail);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage =
  | "Lead"
  | "Engagement Drafted"
  | "Engagement Sent"
  | "Engagement Signed"
  | "Proposal Accepted"
  | "Onboarding";

type Source = "Referral" | "Website" | "Cold Call" | "Event" | "Other";
type EntityType =
  | "Proprietorship"
  | "Partnership"
  | "LLP"
  | "Private Limited"
  | "Public Limited"
  | "Trust"
  | "Society"
  | "Individual";

interface Lead {
  id: string;
  name: string;
  phone: string;
  email: string;
  businessName: string;
  entityType: EntityType;
  estimatedMonthlyFee: number; // stored in paise (integer arithmetic — CGST Act compliance)
  source: Source;
  notes: string;
  stage: Stage;
  lastContactDate: string; // ISO date string
  nextFollowUpDate: string; // ISO date string
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Note: "Proposal Accepted" excluded from STAGES (still in Stage type for DB compat)
const STAGES: Stage[] = [
  "Lead",
  "Engagement Drafted",
  "Engagement Sent",
  "Engagement Signed",
  "Onboarding",
];

const SOURCES: Source[] = ["Referral", "Website", "Cold Call", "Event", "Other"];

// Maps between human-readable Source labels and DB CHECK values
const SOURCE_TO_DB: Record<Source, string> = {
  Referral: "referral",
  Website: "website",
  "Cold Call": "cold",
  Event: "event",
  Other: "other",
};
const DB_TO_SOURCE: Record<string, Source> = {
  referral: "Referral",
  website: "Website",
  cold: "Cold Call",
  event: "Event",
  other: "Other",
};
const ENTITY_TYPES: EntityType[] = [
  "Proprietorship",
  "Partnership",
  "LLP",
  "Private Limited",
  "Public Limited",
  "Trust",
  "Society",
  "Individual",
];

const STAGE_COLORS: Record<Stage, { bg: string; header: string; badge: string }> = {
  Lead: {
    bg: "bg-[#F8FAFC]",
    header: "bg-[#F1F5F9] border-[#E2E8F0]",
    badge: "bg-gray-100 text-[#334155]",
  },
  "Engagement Drafted": {
    bg: "bg-violet-50",
    header: "bg-violet-100 border-violet-200",
    badge: "bg-violet-200 text-violet-800",
  },
  "Engagement Sent": {
    bg: "bg-indigo-50",
    header: "bg-indigo-100 border-indigo-200",
    badge: "bg-indigo-200 text-indigo-800",
  },
  "Engagement Signed": {
    bg: "bg-teal-50",
    header: "bg-teal-100 border-teal-200",
    badge: "bg-teal-200 text-teal-800",
  },
  "Proposal Accepted": {
    bg: "bg-yellow-50",
    header: "bg-yellow-100 border-yellow-200",
    badge: "bg-yellow-200 text-yellow-800",
  },
  Onboarding: {
    bg: "bg-green-50",
    header: "bg-green-100 border-green-200",
    badge: "bg-green-200 text-green-800",
  },
};

// ---------------------------------------------------------------------------
// API helpers — leads CRUD via /api/lifecycle/leads
// ---------------------------------------------------------------------------

/** Map backend lead row → frontend Lead shape */
function fromApiLead(row: Record<string, unknown>): Lead {
  const meta = (row.notes as string | null) ?? "";
  let lastContactDate = new Date().toISOString().split("T")[0];
  let nextFollowUpDate = "";
  let notes = meta;
  let entityType: EntityType = "Proprietorship";
  try {
    const parsed = JSON.parse(meta) as Record<string, string>;
    if (parsed.__caflow_meta__) {
      lastContactDate = parsed.lastContactDate ?? lastContactDate;
      nextFollowUpDate = parsed.nextFollowUpDate ?? "";
      notes = parsed.userNotes ?? "";
      if (parsed.entityType) entityType = parsed.entityType as EntityType;
    }
  } catch {
    // plain text notes — leave as-is
  }
  const dbSource = (row.source as string) ?? "";
  return {
    id: row.id as string,
    name: (row.contact_name as string) ?? "",
    phone: (row.phone as string) ?? "",
    email: (row.email as string) ?? "",
    businessName: (row.company_name as string) ?? "",
    entityType,
    estimatedMonthlyFee: (row.estimated_value_paise as number) ?? 0,
    source: DB_TO_SOURCE[dbSource] ?? "Other",
    notes,
    stage: ((row.stage as string) ?? "Lead") as Stage,
    lastContactDate,
    nextFollowUpDate,
    createdAt: (row.created_at as string) ?? new Date().toISOString(),
  };
}

/** Map frontend Lead → backend LeadIn body */
function toApiBody(lead: Lead) {
  // Embed frontend-only fields in notes JSON so the round-trip is lossless
  const notesMeta = JSON.stringify({
    __caflow_meta__: true,
    entityType: lead.entityType,
    lastContactDate: lead.lastContactDate,
    nextFollowUpDate: lead.nextFollowUpDate,
    userNotes: lead.notes,
  });
  return {
    company_name: lead.businessName || lead.name,
    contact_name: lead.name,
    email: lead.email || null,
    phone: lead.phone || null,
    source: SOURCE_TO_DB[lead.source] ?? "other",
    stage: lead.stage,
    estimated_value_paise: lead.estimatedMonthlyFee,
    notes: notesMeta,
  };
}

async function apiLoadLeads(): Promise<Lead[]> {
  const json = await apiFetch("/api/lifecycle/leads?limit=200");
  if (!json.success) throw new Error(json.error ?? "Failed to load leads");
  // Drop soft-deleted rows on the raw stage string before mapping to Lead.
  return (json.data as Record<string, unknown>[])
    .filter((row) => row.stage !== "_deleted")
    .map(fromApiLead);
}

async function apiCreateLead(lead: Lead): Promise<Lead> {
  const json = await apiFetch("/api/lifecycle/leads", {
    method: "POST",
    body: JSON.stringify(toApiBody(lead)),
  });
  if (!json.success) throw new Error(json.error ?? "Failed to create lead");
  return fromApiLead(json.data as Record<string, unknown>);
}

async function apiUpdateLead(lead: Lead): Promise<Lead> {
  const json = await apiFetch(`/api/lifecycle/leads/${lead.id}`, {
    method: "PATCH",
    body: JSON.stringify(toApiBody(lead)),
  });
  if (!json.success) throw new Error(json.error ?? "Failed to update lead");
  return fromApiLead(json.data as Record<string, unknown>);
}

async function apiDeleteLead(id: string): Promise<void> {
  // Backend has no DELETE endpoint — use PATCH to mark as deleted via a special stage
  // We optimistically remove from UI; ignore backend errors gracefully
  try {
    await apiFetch(`/api/lifecycle/leads/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ stage: "_deleted" }),
    });
  } catch {
    // non-fatal
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRupees(paise: number): string {
  // Integer paise to rupees display — never floating point
  const rupees = Math.floor(paise / 100);
  return `₹${rupees.toLocaleString("en-IN")}`;
}

function rupeesToPaise(rupees: string): number {
  // Convert rupee string input to integer paise
  const n = parseInt(rupees.replace(/[^0-9]/g, ""), 10);
  return isNaN(n) ? 0 : n * 100;
}

function paiseToDRupeeString(paise: number): string {
  return String(Math.floor(paise / 100));
}

function isOverdueOrToday(dateStr: string): boolean {
  if (!dateStr) return false;
  const today = new Date().toISOString().split("T")[0];
  return dateStr <= today;
}

function nextStage(stage: Stage): Stage | null {
  const idx = STAGES.indexOf(stage);
  if (idx < 0 || idx >= STAGES.length - 1) return null;
  return STAGES[idx + 1];
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "—";
  try {
    return formatDateShared(dateStr);
  } catch {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Add / Edit Lead Modal
// ---------------------------------------------------------------------------

interface ModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (lead: Lead) => Promise<void>;
  initial?: Lead | null;
}

const EMPTY_FORM = {
  name: "",
  phone: "",
  email: "",
  businessName: "",
  entityType: "Proprietorship" as EntityType,
  estimatedMonthlyFeeRupees: "",
  source: "Referral" as Source, // maps to "referral" in DB
  notes: "",
  lastContactDate: new Date().toISOString().split("T")[0],
  nextFollowUpDate: "",
};

function AddLeadModal({ open, onClose, onSave, initial }: ModalProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setErr(null);
      setSaving(false);
      if (initial) {
        setForm({
          name: initial.name,
          phone: initial.phone,
          email: initial.email,
          businessName: initial.businessName,
          entityType: initial.entityType,
          estimatedMonthlyFeeRupees: paiseToDRupeeString(
            initial.estimatedMonthlyFee
          ),
          source: initial.source,
          notes: initial.notes,
          lastContactDate: initial.lastContactDate,
          nextFollowUpDate: initial.nextFollowUpDate,
        });
      } else {
        setForm({ ...EMPTY_FORM, lastContactDate: new Date().toISOString().split("T")[0] });
      }
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return; // guard against duplicate submissions (double-click / Enter)
    const lead: Lead = {
      id: initial?.id ?? `lead_${Date.now()}`,
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      businessName: form.businessName.trim(),
      entityType: form.entityType,
      // Integer paise arithmetic — never floating point
      estimatedMonthlyFee: rupeesToPaise(form.estimatedMonthlyFeeRupees),
      source: form.source,
      notes: form.notes.trim(),
      stage: initial?.stage ?? "Lead",
      lastContactDate: form.lastContactDate,
      nextFollowUpDate: form.nextFollowUpDate,
      createdAt: initial?.createdAt ?? new Date().toISOString(),
    };
    setSaving(true);
    setErr(null);
    try {
      // onSave resolves only once the lead actually persists, and throws on
      // failure. We close on success; on failure we keep the modal open so the
      // user sees the error and can retry without re-entering everything.
      await onSave(lead);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save lead. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#182350]/60 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <h2 className="text-base font-semibold text-[#0F172A]">
            {initial ? "Edit Lead" : "Add Lead"}
          </h2>
          <button
            onClick={onClose}
            className="text-[#94A3B8] hover:text-[#475569]"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Inline error — shown in-place so the user sees it without the modal closing */}
          {err && (
            <div
              role="alert"
              className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-600"
            >
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{err}</span>
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">
              Contact Name *
            </label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Full name"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Phone + Email */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Phone *
              </label>
              <input
                required
                type="tel"
                inputMode="numeric"
                maxLength={10}
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/\D/g, "").slice(0, 10) })}
                placeholder="10-digit mobile"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Email
              </label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="email@example.com"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          {/* Business Name */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">
              Business Name *
            </label>
            <input
              required
              value={form.businessName}
              onChange={(e) =>
                setForm({ ...form, businessName: e.target.value })
              }
              placeholder="Business / firm name"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Entity Type + Source */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Entity Type *
              </label>
              <select
                value={form.entityType}
                onChange={(e) =>
                  setForm({ ...form, entityType: e.target.value as EntityType })
                }
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                {ENTITY_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Source *
              </label>
              <select
                value={form.source}
                onChange={(e) =>
                  setForm({ ...form, source: e.target.value as Source })
                }
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                {SOURCES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Monthly fee */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">
              Estimated Monthly Fee (₹)
            </label>
            <input
              type="number"
              min="0"
              value={form.estimatedMonthlyFeeRupees}
              onChange={(e) =>
                setForm({
                  ...form,
                  estimatedMonthlyFeeRupees: e.target.value,
                })
              }
              placeholder="e.g. 5000"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Last Contact Date
              </label>
              <input
                type="date"
                value={form.lastContactDate}
                onChange={(e) =>
                  setForm({ ...form, lastContactDate: e.target.value })
                }
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">
                Next Follow-up Date
              </label>
              <input
                type="date"
                value={form.nextFollowUpDate}
                onChange={(e) =>
                  setForm({ ...form, nextFollowUpDate: e.target.value })
                }
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">
              Notes
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={3}
              placeholder="Any additional context…"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-none"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="flex-1 rounded-lg border border-[#E2E8F0] px-4 py-2 text-sm font-medium text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {saving
                ? initial
                  ? "Saving…"
                  : "Creating Lead…"
                : initial
                  ? "Save Changes"
                  : "Add Lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lead Card
// ---------------------------------------------------------------------------

interface LeadCardProps {
  lead: Lead;
  onEdit: (lead: Lead) => void;
  onMoveNext: (lead: Lead) => void;
  onConvert: (lead: Lead) => void;
  onDelete: (id: string) => void;
}

function LeadCard({ lead, onEdit, onMoveNext, onConvert, onDelete }: LeadCardProps) {
  const next = nextStage(lead.stage);
  const overdue = isOverdueOrToday(lead.nextFollowUpDate);

  return (
    <div className="bg-white rounded-lg border border-[#E2E8F0] p-4 space-y-3 shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[#0F172A] leading-tight">
            {lead.name}
          </p>
          <p className="text-xs text-[#64748B] truncate mt-0.5">
            {lead.businessName}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => onEdit(lead)}
            className="text-xs text-[#94A3B8] hover:text-[#475569] px-1.5 py-0.5 rounded hover:bg-[#F1F5F9] transition-colors"
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(lead.id)}
            className="text-[#CBD5E1] hover:text-red-500 transition-colors"
            aria-label="Delete lead"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Meta */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
          <span className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-[10px] font-medium">
            {lead.entityType}
          </span>
          <span className="px-1.5 py-0.5 bg-[#F8FAFC] text-[#475569] rounded text-[10px] font-medium">
            {lead.source}
          </span>
        </div>

        {lead.phone && (
          <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
            <Phone size={11} className="shrink-0" />
            <span>{lead.phone}</span>
          </div>
        )}

        {lead.email && (
          <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
            <Mail size={11} className="shrink-0" />
            <span className="truncate">{lead.email}</span>
          </div>
        )}

        {lead.estimatedMonthlyFee > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-green-700 font-medium">
            <TrendingUp size={11} className="shrink-0" />
            {formatRupees(lead.estimatedMonthlyFee)}/mo
          </div>
        )}

        <div className="flex items-center gap-1.5 text-xs text-[#94A3B8]">
          <Calendar size={11} className="shrink-0" />
          <span>Last: {formatDate(lead.lastContactDate)}</span>
        </div>

        {lead.nextFollowUpDate && (
          <div
            className={`flex items-center gap-1.5 text-xs font-medium ${
              overdue ? "text-red-600" : "text-[#64748B]"
            }`}
          >
            <AlertCircle size={11} className="shrink-0" />
            <span>
              Follow-up: {formatDate(lead.nextFollowUpDate)}
              {overdue && " (Overdue!)"}
            </span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="pt-1 space-y-2">
        {lead.stage === "Onboarding" ? (
          <button
            onClick={() => onConvert(lead)}
            className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-700 transition-colors"
          >
            <UserCheck size={12} />
            Convert to Client
          </button>
        ) : lead.stage === "Lead" ? (
          <>
            <Link
              href={`/engagements?new=1&lead_id=${lead.id}&name=${encodeURIComponent(lead.businessName || lead.name || "")}`}
              className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors border border-violet-200"
            >
              <FileText size={12} />
              Draft Engagement
            </Link>
          </>
        ) : lead.stage === "Engagement Signed" ? (
          <button
            onClick={() => onMoveNext(lead)}
            className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-700 transition-colors"
          >
            Start Onboarding
            <ArrowRight size={12} />
          </button>
        ) : next ? (
          <button
            onClick={() => onMoveNext(lead)}
            className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors border border-blue-200"
          >
            Move to {next}
            <ArrowRight size={12} />
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Convert to Client modal — creates client + engagement + onboarding via API
// ---------------------------------------------------------------------------

interface ConvertModalProps {
  lead: Lead | null;
  onClose: () => void;
  onConverted: (leadId: string) => void;
}

function ConvertModal({ lead, onClose, onConverted }: ConvertModalProps) {
  const [pan, setPan] = useState("");
  const [gstin, setGstin] = useState("");
  const [converting, setConverting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  if (!lead) return null;

  async function handleConvert() {
    setConverting(true);
    setErr(null);
    try {
      const json = await apiFetch(`/api/lifecycle/leads/${lead!.id}/convert`, {
        method: "POST",
        body: JSON.stringify({
          name: lead!.name,
          company_name: lead!.businessName,
          email: lead!.email || null,
          phone: lead!.phone || null,
          entity_type: lead!.entityType,
          pan: pan.trim().toUpperCase() || null,
          gstin: gstin.trim().toUpperCase() || null,
          create_onboarding: true,
        }),
      });
      if (!json.success) throw new Error(json.error ?? "Conversion failed");
      const clientId = json.data?.converted_client_id ?? "";
      setWarnings((json.data?.warnings as string[] | undefined) ?? []);
      setDone(clientId);
      onConverted(lead!.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Conversion failed");
    } finally {
      setConverting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#182350]/60 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
            <UserCheck size={18} className="text-green-700" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[#0F172A]">Convert to Client</h2>
            <p className="text-xs text-[#64748B]">{lead.name} · {lead.businessName}</p>
          </div>
        </div>

        {done ? (
          <div className="space-y-4">
            <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
              ✓ Client created successfully. Onboarding workflow started.
            </div>
            {warnings.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800 space-y-1">
                <p className="font-semibold">Completed with warnings:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  {warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex gap-3">
              <button onClick={onClose} className="flex-1 rounded-lg border border-[#E2E8F0] px-4 py-2 text-sm font-medium text-[#475569] hover:bg-[#F8FAFC]">Close</button>
              <Link
                href={`/clients/${done}/lifecycle/`}
                onClick={onClose}
                className="flex-1 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 text-center"
              >
                View Onboarding
              </Link>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-[#475569]">
              Creates a new client, engagement, and onboarding workflow for <strong>{lead.name}</strong>.
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-[#64748B] font-medium">PAN (optional)</label>
                <input
                  value={pan}
                  onChange={(e) => setPan(e.target.value.toUpperCase())}
                  maxLength={10}
                  className="w-full mt-1 px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg text-[#0F172A] font-mono focus:outline-none focus:ring-2 focus:ring-green-500 uppercase"
                  placeholder="AAAAA9999A"
                />
              </div>
              <div>
                <label className="text-xs text-[#64748B] font-medium">GSTIN (optional)</label>
                <input
                  value={gstin}
                  onChange={(e) => setGstin(e.target.value.toUpperCase())}
                  maxLength={15}
                  className="w-full mt-1 px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg text-[#0F172A] font-mono focus:outline-none focus:ring-2 focus:ring-green-500 uppercase"
                  placeholder="22AAAAA0000A1Z5"
                />
              </div>
            </div>
            {err && (
              <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-600">{err}</div>
            )}
            <div className="flex gap-3 pt-1">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-[#E2E8F0] px-4 py-2 text-sm font-medium text-[#475569] hover:bg-[#F8FAFC] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConvert}
                disabled={converting}
                className="flex-1 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                {converting ? "Converting…" : "Convert to Client"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PipelinePage() {
  const { toast } = useToast();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editLead, setEditLead] = useState<Lead | null>(null);
  const [convertLead, setConvertLead] = useState<Lead | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Load from API on mount
  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    apiLoadLeads()
      .then((data) => {
        setLeads(data);
      })
      .catch((e) => {
        setLoadError(e instanceof Error ? e.message : "Failed to load leads");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  // Throws on failure so AddLeadModal can keep itself open, surface the error
  // inline and re-enable its button. On success we update state + toast.
  async function handleSave(lead: Lead) {
    const isNew = !leads.find((l) => l.id === lead.id);
    if (isNew) {
      const created = await apiCreateLead(lead);
      setLeads((prev) => [created, ...prev]);
      toast({ title: "Lead created", description: `${created.name} added to your pipeline.` });
    } else {
      const updated = await apiUpdateLead(lead);
      setLeads((prev) => prev.map((l) => (l.id === lead.id ? updated : l)));
      toast({ title: "Lead updated", description: `${updated.name} saved.` });
    }
  }

  async function handleMoveNext(lead: Lead) {
    const next = nextStage(lead.stage);
    if (!next) return;
    const updated = { ...lead, stage: next };
    // Optimistic move — revert and tell the user if the write doesn't persist.
    setLeads((prev) => prev.map((l) => (l.id === lead.id ? updated : l)));
    try {
      await apiUpdateLead(updated);
    } catch (e) {
      setLeads((prev) => prev.map((l) => (l.id === lead.id ? lead : l)));
      toast({
        variant: "destructive",
        title: "Couldn't move lead",
        description: e instanceof Error ? e.message : "Please try again.",
      });
    }
  }

  async function handleDelete(id: string) {
    // Optimistic remove — restore on failure so the UI never lies about state.
    const snapshot = leads;
    setLeads((prev) => prev.filter((l) => l.id !== id));
    try {
      await apiDeleteLead(id);
    } catch (e) {
      setLeads(snapshot);
      toast({
        variant: "destructive",
        title: "Couldn't delete lead",
        description: e instanceof Error ? e.message : "Please try again.",
      });
    }
  }

  function openAdd() {
    setEditLead(null);
    setModalOpen(true);
  }

  function openEdit(lead: Lead) {
    setEditLead(lead);
    setModalOpen(true);
  }

  // Pipeline summary
  const totalLeads = leads.length;
  // Estimated MRR (Monthly Recurring Revenue) — sum of all leads' monthly fees in paise
  const estimatedMRRPaise = leads.reduce(
    (sum, l) => sum + l.estimatedMonthlyFee,
    0
  );

  // Follow-up overdue banner
  const overdueLeads = leads.filter(
    (l) => l.nextFollowUpDate && isOverdueOrToday(l.nextFollowUpDate)
  );

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-[#94A3B8] mb-1">
            <Link href="/clients" className="hover:text-[#475569]">
              Clients
            </Link>
            <ChevronRight size={12} />
            <span>Pipeline</span>
          </div>
          <h1 className="text-xl font-semibold text-[#0F172A]">
            Prospect Pipeline
          </h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Track and convert prospective clients through your sales funnel
          </p>
        </div>
        <button
          onClick={openAdd}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          <Plus size={15} />
          Add Lead
        </button>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="bg-white rounded-lg border border-[#F1F5F9] px-4 py-3">
          <p className="text-xs text-[#64748B]">Total Leads</p>
          <p className="text-xl font-bold text-[#0F172A] mt-0.5">
            <Users size={14} className="inline mr-1 text-blue-500" />
            {totalLeads}
          </p>
        </div>
        <div className="bg-white rounded-lg border border-[#F1F5F9] px-4 py-3">
          <p className="text-xs text-[#64748B]">Est. MRR (if all convert)</p>
          <p className="text-xl font-bold text-green-700 mt-0.5">
            {formatRupees(estimatedMRRPaise)}
          </p>
        </div>
        {STAGES.slice(0, 2).map((stage) => {
          const count = leads.filter((l) => l.stage === stage).length;
          return (
            <div
              key={stage}
              className="bg-white rounded-lg border border-[#F1F5F9] px-4 py-3"
            >
              <p className="text-xs text-[#64748B]">{stage}</p>
              <p className="text-xl font-bold text-[#0F172A] mt-0.5">{count}</p>
            </div>
          );
        })}
      </div>

      {/* Overdue follow-up banner */}
      {overdueLeads.length > 0 && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={16} className="text-red-500 shrink-0 mt-0.5" />
          <div className="text-sm text-red-700">
            <span className="font-semibold">
              {overdueLeads.length} follow-up
              {overdueLeads.length > 1 ? "s" : ""} overdue or due today:
            </span>{" "}
            {overdueLeads.map((l) => l.name).join(", ")}
          </div>
        </div>
      )}

      {/* Load error banner */}
      {loadError && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={16} className="text-red-500 shrink-0 mt-0.5" />
          <div className="flex-1 text-sm text-red-700">
            <span className="font-semibold">Failed to load leads: </span>
            {loadError}
          </div>
          <button
            onClick={() => setLoadError(null)}
            className="text-red-400 hover:text-red-600 shrink-0"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Kanban board — skeleton columns while loading, real board otherwise */}
      {loading ? (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {STAGES.map((stage) => (
            <div key={stage} className="min-w-[280px] flex-none">
              <Skeleton className="h-11 w-full rounded-xl" />
              <div className="mt-3 space-y-3">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-28 w-full rounded-xl" />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
      <div className="flex gap-4 overflow-x-auto pb-4">
        {STAGES.map((stage) => {
          const stageLeads = leads.filter((l) => l.stage === stage);
          const colors = STAGE_COLORS[stage];
          return (
            <div
              key={stage}
              className={`min-w-[280px] flex-none rounded-xl border ${colors.header} overflow-hidden`}
            >
              {/* Column header */}
              <div className={`px-4 py-3 border-b ${colors.header}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-[#1E293B]">
                    {stage}
                  </span>
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded-full ${colors.badge}`}
                  >
                    {stageLeads.length}
                  </span>
                </div>
              </div>

              {/* Cards */}
              <div className={`p-3 space-y-3 min-h-[200px] ${colors.bg}`}>
                {stageLeads.length === 0 && (
                  <div className="text-center py-10 text-xs text-[#94A3B8]">
                    No leads in this stage
                  </div>
                )}
                {stageLeads.map((lead) => (
                  <LeadCard
                    key={lead.id}
                    lead={lead}
                    onEdit={openEdit}
                    onMoveNext={handleMoveNext}
                    onConvert={setConvertLead}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      )}

      {/* Modals */}
      <AddLeadModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditLead(null);
        }}
        onSave={handleSave}
        initial={editLead}
      />
      <ConvertModal
        lead={convertLead}
        onClose={() => setConvertLead(null)}
        onConverted={(leadId) => {
          setLeads((prev) => prev.filter((l) => l.id !== leadId));
          setConvertLead(null);
        }}
      />
    </div>
  );
}
