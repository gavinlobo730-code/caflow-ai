"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  X,
  AlertCircle,
  FileText,
  Send,
  CheckCircle,
  XCircle,
  ChevronDown,
  Loader2,
  Edit3,
  Eye,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

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
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EngagementLetter {
  id: string;
  engagement_number: string;
  title: string;
  status: "Draft" | "Generated" | "Sent" | "Viewed" | "Signed" | "Rejected" | "Expired";
  fee_amount_paise: number;
  recipient_name: string | null;
  recipient_email: string | null;
  lead_id: string | null;
  client_id: string | null;
  template_id: string | null;
  content: string;
  start_date: string | null;
  expiry_date: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  rejected_at: string | null;
  rejection_notes: string | null;
  sign_token: string | null;
  created_at: string;
}

interface EngagementTemplate {
  id: string;
  name: string;
  service_type: string;
  content: string;
  version: number;
  is_default: boolean;
}

type ActiveTab = "all" | "draft" | "sent" | "signed" | "templates";

// ---------------------------------------------------------------------------
// Helpers — integer paise arithmetic (never floating point, per CGST Act)
// ---------------------------------------------------------------------------

function formatPaise(paise: number): string {
  return "₹" + Math.floor(paise / 100).toLocaleString("en-IN");
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function rupeesToPaise(rupeesStr: string): number {
  const n = parseInt(rupeesStr.replace(/[^0-9]/g, ""), 10);
  return isNaN(n) ? 0 : n * 100;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<EngagementLetter["status"], string> = {
  Draft: "bg-gray-100 text-gray-600",
  Generated: "bg-blue-100 text-blue-700",
  Sent: "bg-indigo-100 text-indigo-700",
  Viewed: "bg-purple-100 text-purple-700",
  Signed: "bg-green-100 text-green-700",
  Rejected: "bg-red-100 text-red-700",
  Expired: "bg-orange-100 text-orange-700",
};

function StatusBadge({ status }: { status: EngagementLetter["status"] }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status]}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Service types
// ---------------------------------------------------------------------------

const SERVICE_TYPES = [
  "GST Compliance",
  "Income Tax Return",
  "Tax Audit",
  "ROC Compliance",
  "Bookkeeping",
  "Virtual CFO",
];

// ---------------------------------------------------------------------------
// Stat Card
// ---------------------------------------------------------------------------

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-white rounded-lg border border-[#E2E8F0] px-4 py-3">
      <p className="text-xs text-[#64748B]">{label}</p>
      <p className={`text-2xl font-bold mt-0.5 ${color}`}>{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create Engagement Modal
// ---------------------------------------------------------------------------

interface CreateEngagementModalProps {
  open: boolean;
  onClose: () => void;
  templates: EngagementTemplate[];
  onCreated: (letter: EngagementLetter) => void;
  initialLeadId?: string | null;
  initialName?: string | null;
}

function CreateEngagementModal({ open, onClose, templates, onCreated, initialLeadId, initialName }: CreateEngagementModalProps) {
  const [form, setForm] = useState({
    title: "",
    template_id: "",
    recipient_name: "",
    fee_rupees: "",
    recipient_email: "",
    start_date: "",
    expiry_date: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm({ title: "", template_id: "", recipient_name: initialName ?? "", fee_rupees: "", recipient_email: "", start_date: "", expiry_date: "" });
      setErr(null);
    }
  }, [open, initialName]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const json = await apiFetch("/api/engagement-letters", {
        method: "POST",
        body: JSON.stringify({
          title: form.title.trim(),
          template_id: form.template_id || null,
          recipient_name: form.recipient_name.trim() || null,
          fee_amount_paise: rupeesToPaise(form.fee_rupees),
          recipient_email: form.recipient_email.trim() || null,
          start_date: form.start_date || null,
          expiry_date: form.expiry_date || null,
          // Carry the originating lead so the engagement is linked for lead conversion (H16)
          lead_id: initialLeadId || undefined,
        }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to create engagement");
      // Backend wraps the row as { engagement: {...} } — unwrap it (not the raw data envelope).
      onCreated((json.data as { engagement: EngagementLetter }).engagement);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create engagement");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#182350]/60 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <h2 className="text-base font-semibold text-[#0F172A]">New Engagement Letter</h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {err && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-600">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              {err}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Title *</label>
            <input
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="e.g. GST Compliance — FY 2025-26"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Template</label>
            <div className="relative">
              <select
                value={form.template_id}
                onChange={(e) => setForm({ ...form, template_id: e.target.value })}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 appearance-none"
              >
                <option value="">— No template —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} ({t.service_type})</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8] pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Lead / Client Name</label>
            <input
              value={form.recipient_name}
              onChange={(e) => setForm({ ...form, recipient_name: e.target.value })}
              placeholder="Recipient name"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Fee Amount (₹)</label>
              <input
                type="number"
                min="0"
                value={form.fee_rupees}
                onChange={(e) => setForm({ ...form, fee_rupees: e.target.value })}
                placeholder="e.g. 12000"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Recipient Email</label>
              <input
                type="email"
                value={form.recipient_email}
                onChange={(e) => setForm({ ...form, recipient_email: e.target.value })}
                placeholder="client@example.com"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Start Date</label>
              <input
                type="date"
                value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Expiry Date</label>
              <input
                type="date"
                value={form.expiry_date}
                onChange={(e) => setForm({ ...form, expiry_date: e.target.value })}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg border border-[#E2E8F0] px-4 py-2 text-sm font-medium text-[#475569] hover:bg-[#F8FAFC] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {saving ? "Creating…" : "Create Engagement"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Template Modal (Create / Edit)
// ---------------------------------------------------------------------------

interface TemplateModalProps {
  open: boolean;
  onClose: () => void;
  initial?: EngagementTemplate | null;
  onSaved: (template: EngagementTemplate) => void;
}

function TemplateModal({ open, onClose, initial, onSaved }: TemplateModalProps) {
  const [form, setForm] = useState({ name: "", service_type: SERVICE_TYPES[0], content: "" });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setErr(null);
      if (initial) {
        setForm({ name: initial.name, service_type: initial.service_type, content: initial.content });
      } else {
        setForm({ name: "", service_type: SERVICE_TYPES[0], content: "" });
      }
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      let json;
      if (initial) {
        json = await apiFetch(`/api/engagement-letters/templates/${initial.id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: form.name.trim(), service_type: form.service_type, content: form.content.trim() }),
        });
      } else {
        json = await apiFetch("/api/engagement-letters/templates", {
          method: "POST",
          body: JSON.stringify({ name: form.name.trim(), service_type: form.service_type, content: form.content.trim() }),
        });
      }
      if (!json.success) throw new Error(json.error ?? "Failed to save template");
      // Backend wraps the row as { template: {...} } — unwrap it.
      onSaved((json.data as { template: EngagementTemplate }).template);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save template");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#182350]/60 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <h2 className="text-base font-semibold text-[#0F172A]">
            {initial ? "Edit Template" : "New Template"}
          </h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {err && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-600">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              {err}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Template Name *</label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Standard GST Compliance Letter"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Service Type *</label>
            <div className="relative">
              <select
                value={form.service_type}
                onChange={(e) => setForm({ ...form, service_type: e.target.value })}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 appearance-none"
              >
                {SERVICE_TYPES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8] pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Template Content *</label>
            <textarea
              required
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={10}
              placeholder="Write your template content here…"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-y font-mono"
            />
            <p className="mt-1.5 text-xs text-[#94A3B8]">
              Available merge fields:{" "}
              <code className="bg-[#F1F5F9] px-1 rounded text-[#475569]">
                {"{{client_name}} {{client_pan}} {{client_gstin}} {{firm_name}} {{partner_name}} {{engagement_fee}} {{engagement_date}}"}
              </code>
            </p>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg border border-[#E2E8F0] px-4 py-2 text-sm font-medium text-[#475569] hover:bg-[#F8FAFC] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {saving ? "Saving…" : "Save Template"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Engagement Detail Modal
// ---------------------------------------------------------------------------

interface DetailModalProps {
  letter: EngagementLetter | null;
  onClose: () => void;
  onUpdated: (letter: EngagementLetter) => void;
}

function DetailModal({ letter, onClose, onUpdated }: DetailModalProps) {
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [signedPdfUrl, setSignedPdfUrl] = useState("");
  const [rejectionNotes, setRejectionNotes] = useState("");
  const [showSignInput, setShowSignInput] = useState(false);
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [showSendInput, setShowSendInput] = useState(false);
  const [sendEmail, setSendEmail] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (letter) {
      setActionErr(null);
      setSignedPdfUrl("");
      setRejectionNotes("");
      setShowSignInput(false);
      setShowRejectInput(false);
      setShowSendInput(false);
      setSendEmail(letter.recipient_email ?? "");
    }
  }, [letter]);

  async function doAction(path: string, body?: Record<string, unknown>) {
    setActionLoading(true);
    setActionErr(null);
    try {
      const json = await apiFetch(path, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      });
      if (!json.success) throw new Error(json.error ?? "Action failed");
      // generate/send/sign/reject all return { engagement: {...} } — unwrap the row
      // so the new status flows into both the list row and this modal. Treating the
      // whole envelope as the letter left status/id undefined, so the UI never
      // advanced (the row stayed "Draft" while the backend was already "Generated").
      onUpdated((json.data as { engagement: EngagementLetter }).engagement);
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : "Action failed");
    } finally {
      setActionLoading(false);
    }
  }

  if (!letter) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#182350]/60 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div>
            <p className="text-[10px] font-mono text-[#94A3B8]">{letter.engagement_number}</p>
            <h2 className="text-base font-semibold text-[#0F172A]">{letter.title}</h2>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={letter.status} />
            <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-4">
          {/* Meta row */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
            <div>
              <p className="text-xs text-[#94A3B8]">Recipient</p>
              <p className="text-[#334155] font-medium">{letter.recipient_name ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-[#94A3B8]">Fee</p>
              <p className="text-[#334155] font-medium">{formatPaise(letter.fee_amount_paise)}</p>
            </div>
            <div>
              <p className="text-xs text-[#94A3B8]">Start Date</p>
              <p className="text-[#334155]">{formatDate(letter.start_date)}</p>
            </div>
            <div>
              <p className="text-xs text-[#94A3B8]">Expiry</p>
              <p className="text-[#334155]">{formatDate(letter.expiry_date)}</p>
            </div>
          </div>

          {/* Status timeline */}
          <div className="space-y-1">
            <p className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider">Timeline</p>
            <div className="space-y-1">
              <p className="text-xs text-[#64748B]">Created: {formatDate(letter.created_at)}</p>
              {letter.sent_at && <p className="text-xs text-indigo-600">Sent: {formatDate(letter.sent_at)}</p>}
              {letter.signed_at && <p className="text-xs text-green-600">Signed: {formatDate(letter.signed_at)}</p>}
              {letter.rejected_at && (
                <p className="text-xs text-red-600">
                  Rejected: {formatDate(letter.rejected_at)}
                  {letter.rejection_notes && ` — ${letter.rejection_notes}`}
                </p>
              )}
            </div>
          </div>

          {/* Content preview */}
          {letter.content && (
            <div>
              <p className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-1.5">Content Preview</p>
              <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-4 py-3 text-sm text-[#334155] whitespace-pre-wrap max-h-48 overflow-y-auto font-mono text-xs">
                {letter.content}
              </div>
            </div>
          )}

          {/* Client signing link — shareable for self-serve e-sign (also sent in the email) */}
          {(letter.status === "Sent" || letter.status === "Viewed") && letter.sign_token && (
            <div>
              <p className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-1.5">Client Signing Link</p>
              <div className="flex items-center gap-2">
                <input
                  readOnly
                  value={`${typeof window !== "undefined" ? window.location.origin : ""}/sign/?t=${letter.sign_token}`}
                  className="flex-1 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2 text-xs text-[#475569] outline-none"
                />
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(`${window.location.origin}/sign/?t=${letter.sign_token}`);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  className="shrink-0 rounded-lg border border-[#E2E8F0] px-3 py-2 text-xs font-medium text-[#475569] hover:bg-[#F8FAFC]"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="mt-1 text-xs text-[#94A3B8]">The client can review and e-sign here — no login needed. This link is in the email; share it via WhatsApp too if you like.</p>
            </div>
          )}

          {/* Error */}
          {actionErr && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-600">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              {actionErr}
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-1">
            {letter.status === "Draft" && (
              <button
                disabled={actionLoading}
                onClick={() => doAction(`/api/engagement-letters/${letter.id}/generate`)}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {actionLoading ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
                Mark as Generated
              </button>
            )}

            {letter.status === "Generated" && (
              !showSendInput ? (
                <button
                  disabled={actionLoading}
                  onClick={() => setShowSendInput(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  <Send size={13} />
                  Send to Client
                </button>
              ) : (
                <div className="w-full space-y-2">
                  <label className="text-xs font-medium text-[#334155]">Client email</label>
                  <input
                    type="email"
                    value={sendEmail}
                    onChange={(e) => setSendEmail(e.target.value)}
                    placeholder="client@example.com"
                    className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  />
                  <p className="text-xs text-[#64748B]">
                    The letter will be emailed to this address with a PDF copy attached, then marked as Sent.
                  </p>
                  <div className="flex gap-2">
                    <button
                      disabled={actionLoading || !sendEmail.trim()}
                      onClick={() => doAction(`/api/engagement-letters/${letter.id}/send`, { to_email: sendEmail.trim() })}
                      className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                    >
                      {actionLoading ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                      Send Now
                    </button>
                    <button onClick={() => setShowSendInput(false)} className="rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#475569] hover:bg-[#F8FAFC]">
                      Cancel
                    </button>
                  </div>
                </div>
              )
            )}

            {(letter.status === "Sent" || letter.status === "Viewed") && (
              <>
                {!showSignInput && !showRejectInput && (
                  <>
                    <button
                      onClick={() => { setShowSignInput(true); setShowRejectInput(false); }}
                      className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors"
                    >
                      <CheckCircle size={13} />
                      Mark as Signed
                    </button>
                    <button
                      onClick={() => { setShowRejectInput(true); setShowSignInput(false); }}
                      className="flex items-center gap-1.5 rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-100 border border-red-200 transition-colors"
                    >
                      <XCircle size={13} />
                      Reject
                    </button>
                  </>
                )}

                {showSignInput && (
                  <div className="w-full space-y-2">
                    <label className="text-xs font-medium text-[#334155]">Signed PDF URL (optional)</label>
                    <input
                      value={signedPdfUrl}
                      onChange={(e) => setSignedPdfUrl(e.target.value)}
                      placeholder="https://… (leave blank if none)"
                      className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-green-500 focus:ring-2 focus:ring-green-100"
                    />
                    <div className="flex gap-2">
                      <button
                        disabled={actionLoading}
                        onClick={() => doAction(`/api/engagement-letters/${letter.id}/sign`, { signed_pdf_url: signedPdfUrl || undefined })}
                        className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                      >
                        {actionLoading ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                        Confirm Signed
                      </button>
                      <button onClick={() => setShowSignInput(false)} className="rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#475569] hover:bg-[#F8FAFC]">
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {showRejectInput && (
                  <div className="w-full space-y-2">
                    <label className="text-xs font-medium text-[#334155]">Rejection Notes (optional)</label>
                    <input
                      value={rejectionNotes}
                      onChange={(e) => setRejectionNotes(e.target.value)}
                      placeholder="Reason for rejection…"
                      className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-red-500 focus:ring-2 focus:ring-red-100"
                    />
                    <div className="flex gap-2">
                      <button
                        disabled={actionLoading}
                        onClick={() => doAction(`/api/engagement-letters/${letter.id}/reject`, { rejection_notes: rejectionNotes || undefined })}
                        className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                      >
                        {actionLoading ? <Loader2 size={13} className="animate-spin" /> : <XCircle size={13} />}
                        Confirm Reject
                      </button>
                      <button onClick={() => setShowRejectInput(false)} className="rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#475569] hover:bg-[#F8FAFC]">
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function EngagementsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL is the single source of truth for the active tab. The sidebar
  // (EngagementsPanel) reads the same `?tab=` param, so the two never drift.
  // An unknown or missing param resolves to "all". Deriving instead of
  // storing makes deep-links, refresh and browser back/forward all work with
  // no duplicated React state to keep in sync.
  const tabParam = searchParams.get("tab");
  const activeTab: ActiveTab =
    tabParam === "draft" || tabParam === "sent" || tabParam === "signed" || tabParam === "templates"
      ? tabParam
      : "all";

  // Switching tabs writes the URL (push so back/forward steps through tabs).
  // "all" is the canonical no-param route.
  const setActiveTab = useCallback(
    (tab: ActiveTab) => {
      router.push(tab === "all" ? "/engagements" : `/engagements?tab=${tab}`);
    },
    [router]
  );

  const [letters, setLetters] = useState<EngagementLetter[]>([]);
  const [templates, setTemplates] = useState<EngagementTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [showCreateEngagement, setShowCreateEngagement] = useState(false);
  const [showCreateTemplate, setShowCreateTemplate] = useState(false);
  const [editTemplate, setEditTemplate] = useState<EngagementTemplate | null>(null);
  const [detailLetter, setDetailLetter] = useState<EngagementLetter | null>(null);

  // Incoming lead context (from pipeline "Create Engagement" — H16). Prefills + links the new engagement.
  const [incomingLeadId, setIncomingLeadId] = useState<string | null>(null);
  const [incomingName, setIncomingName] = useState<string | null>(null);

  // On mount, read lead context from query params and auto-open the create modal.
  useEffect(() => {
    const leadId = searchParams.get("lead_id");
    const name = searchParams.get("name");
    const isNew = searchParams.get("new") === "1";
    if (isNew || leadId) {
      setIncomingLeadId(leadId);
      setIncomingName(name);
      setShowCreateEngagement(true);
    }
  }, [searchParams]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [lettersRes, templatesRes] = await Promise.all([
        apiFetch("/api/engagement-letters"),
        apiFetch("/api/engagement-letters/templates"),
      ]);
      if (!lettersRes.success) throw new Error(lettersRes.error ?? "Failed to load engagements");
      if (!templatesRes.success) throw new Error(templatesRes.error ?? "Failed to load templates");
      setLetters((lettersRes.data as { engagements: EngagementLetter[] }).engagements ?? []);
      setTemplates((templatesRes.data as { templates: EngagementTemplate[] }).templates ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Filter letters by active tab
  const filteredLetters = letters.filter((l) => {
    if (activeTab === "all") return true;
    if (activeTab === "draft") return l.status === "Draft" || l.status === "Generated";
    if (activeTab === "sent") return l.status === "Sent" || l.status === "Viewed";
    if (activeTab === "signed") return l.status === "Signed";
    return true;
  });

  // Summary stats
  const draftCount = letters.filter((l) => l.status === "Draft" || l.status === "Generated").length;
  const awaitingCount = letters.filter((l) => l.status === "Sent" || l.status === "Viewed").length;
  const now = new Date();
  const thisMonthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
  const signedThisMonth = letters.filter(
    (l) => l.status === "Signed" && l.signed_at && l.signed_at >= thisMonthStart
  ).length;
  const expiringCount = letters.filter((l) => {
    if (!l.expiry_date || l.status === "Signed" || l.status === "Rejected") return false;
    const expiry = new Date(l.expiry_date);
    const daysUntil = (expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
    return daysUntil >= 0 && daysUntil <= 7;
  }).length;

  const tabs: { id: ActiveTab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "draft", label: "Draft" },
    { id: "sent", label: "Sent" },
    { id: "signed", label: "Signed" },
    { id: "templates", label: "Templates" },
  ];

  function handleLetterAction(action: "generate" | "send", letter: EngagementLetter) {
    setDetailLetter(letter);
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Engagement Letters</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Create, send and track engagement letters for clients and prospects
          </p>
        </div>
        {activeTab === "templates" ? (
          <button
            onClick={() => { setEditTemplate(null); setShowCreateTemplate(true); }}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <Plus size={15} />
            New Template
          </button>
        ) : (
          <button
            onClick={() => setShowCreateEngagement(true)}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <Plus size={15} />
            New Engagement
          </button>
        )}
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Draft" value={draftCount} color="text-[#0F172A]" />
        <StatCard label="Awaiting Signature" value={awaitingCount} color="text-indigo-700" />
        <StatCard label="Signed This Month" value={signedThisMonth} color="text-green-700" />
        <StatCard label="Expiring (7 days)" value={expiringCount} color="text-orange-600" />
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={16} className="text-red-500 shrink-0 mt-0.5" />
          <div className="flex-1 text-sm text-red-700">
            <span className="font-semibold">Error: </span>{error}
          </div>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 shrink-0">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-[#E2E8F0]">
        <div className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-medium transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-b-2 border-blue-600 text-blue-600"
                  : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {tab.label}
              {tab.id === "all" && letters.length > 0 && (
                <span className="ml-1.5 text-xs bg-[#F1F5F9] text-[#475569] rounded-full px-1.5 py-0.5">{letters.length}</span>
              )}
              {tab.id === "templates" && templates.length > 0 && (
                <span className="ml-1.5 text-xs bg-[#F1F5F9] text-[#475569] rounded-full px-1.5 py-0.5">{templates.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12 text-sm text-[#94A3B8] gap-2">
          <Loader2 size={16} className="animate-spin" />
          Loading…
        </div>
      )}

      {/* Templates tab */}
      {!loading && activeTab === "templates" && (
        <div>
          {templates.length === 0 ? (
            <div className="text-center py-16 text-[#94A3B8]">
              <FileText size={32} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm font-medium">No templates yet</p>
              <p className="text-xs mt-1">Create a template to quickly generate engagement letters</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((t) => (
                <div
                  key={t.id}
                  className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3 hover:shadow-sm transition-shadow"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-[#0F172A] leading-tight">{t.name}</p>
                      <span className="inline-block mt-1 text-xs bg-blue-50 text-blue-700 rounded-full px-2 py-0.5 font-medium">
                        {t.service_type}
                      </span>
                    </div>
                    {t.is_default && (
                      <span className="shrink-0 text-[10px] bg-green-50 text-green-600 rounded-full px-1.5 py-0.5 font-medium">
                        Default
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[#64748B] line-clamp-2">{t.content.slice(0, 120)}…</p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => { setEditTemplate(t); setShowCreateTemplate(true); }}
                      className="flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-xs font-medium text-[#475569] hover:bg-[#F8FAFC] transition-colors"
                    >
                      <Edit3 size={11} />
                      Edit
                    </button>
                    <button
                      onClick={() => { setShowCreateEngagement(true); }}
                      className="flex items-center gap-1.5 rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 border border-blue-200 transition-colors"
                    >
                      <Plus size={11} />
                      Use
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Letters table */}
      {!loading && activeTab !== "templates" && (
        <div>
          {filteredLetters.length === 0 ? (
            <div className="text-center py-16 text-[#94A3B8]">
              <FileText size={32} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm font-medium">No engagement letters found</p>
              <p className="text-xs mt-1">
                {activeTab === "all" ? "Create your first engagement letter to get started" : `No letters in "${activeTab}" status`}
              </p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#F1F5F9] bg-[#F8FAFC]">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Engagement #</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Client / Lead</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Title</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Status</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Fee</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Created</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-[#64748B] uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1F5F9]">
                  {filteredLetters.map((letter) => (
                    <tr
                      key={letter.id}
                      className="hover:bg-[#F8FAFC] transition-colors group"
                    >
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setDetailLetter(letter)}
                          className="font-mono text-xs text-blue-600 hover:text-blue-800 hover:underline font-medium"
                        >
                          {letter.engagement_number}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-[#334155]">
                        {letter.recipient_name ?? <span className="text-[#94A3B8]">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setDetailLetter(letter)}
                          className="text-[#0F172A] font-medium hover:text-blue-600 text-left max-w-[200px] truncate block"
                        >
                          {letter.title}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={letter.status} />
                      </td>
                      <td className="px-4 py-3 text-[#334155] font-medium">
                        {letter.fee_amount_paise > 0 ? formatPaise(letter.fee_amount_paise) : <span className="text-[#94A3B8]">—</span>}
                      </td>
                      <td className="px-4 py-3 text-[#64748B] text-xs">
                        {formatDate(letter.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => setDetailLetter(letter)}
                            className="flex items-center gap-1 rounded-md bg-[#F1F5F9] px-2 py-1 text-xs font-medium text-[#475569] hover:bg-[#E2E8F0] transition-colors"
                          >
                            <Eye size={11} />
                            View
                          </button>
                          {letter.status === "Draft" && (
                            <button
                              onClick={() => handleLetterAction("generate", letter)}
                              className="flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
                            >
                              <FileText size={11} />
                              Mark Generated
                            </button>
                          )}
                          {letter.status === "Generated" && (
                            <button
                              onClick={() => handleLetterAction("send", letter)}
                              className="flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
                            >
                              <Send size={11} />
                              Send
                            </button>
                          )}
                          {(letter.status === "Sent" || letter.status === "Viewed") && (
                            <>
                              <button
                                onClick={() => setDetailLetter(letter)}
                                className="flex items-center gap-1 rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100 transition-colors"
                              >
                                <CheckCircle size={11} />
                                Sign
                              </button>
                              <button
                                onClick={() => setDetailLetter(letter)}
                                className="flex items-center gap-1 rounded-md bg-red-50 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-100 transition-colors"
                              >
                                <XCircle size={11} />
                                Reject
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      <CreateEngagementModal
        open={showCreateEngagement}
        onClose={() => {
          setShowCreateEngagement(false);
          setIncomingLeadId(null);
          setIncomingName(null);
        }}
        templates={templates}
        initialLeadId={incomingLeadId}
        initialName={incomingName}
        onCreated={(letter) => {
          setLetters((prev) => [letter, ...prev]);
        }}
      />

      <TemplateModal
        open={showCreateTemplate}
        onClose={() => { setShowCreateTemplate(false); setEditTemplate(null); }}
        initial={editTemplate}
        onSaved={(template) => {
          setTemplates((prev) => {
            const existing = prev.findIndex((t) => t.id === template.id);
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = template;
              return updated;
            }
            return [template, ...prev];
          });
        }}
      />

      <DetailModal
        letter={detailLetter}
        onClose={() => setDetailLetter(null)}
        onUpdated={(updated) => {
          setLetters((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
          setDetailLetter(updated);
        }}
      />
    </div>
  );
}

// useSearchParams() must be inside a Suspense boundary or `next build` fails with
// "useSearchParams() should be wrapped in a suspense boundary" (App Router static rendering).
export default function EngagementsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-12 text-sm text-[#94A3B8] gap-2">
          <Loader2 size={16} className="animate-spin" />
          Loading…
        </div>
      }
    >
      <EngagementsPageInner />
    </Suspense>
  );
}
