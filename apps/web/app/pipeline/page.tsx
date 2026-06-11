"use client";

import { useState, useEffect, useCallback } from "react";
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
} from "lucide-react";
import Link from "next/link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage = "Lead" | "Proposal Sent" | "Negotiation" | "Onboarded";
type Source = "Referral" | "Website" | "Walk-in" | "LinkedIn";
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

const STAGES: Stage[] = ["Lead", "Proposal Sent", "Negotiation", "Onboarded"];
const SOURCES: Source[] = ["Referral", "Website", "Walk-in", "LinkedIn"];
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
    bg: "bg-[#0e1017]",
    header: "bg-white/[0.06] border-white/[0.07]",
    badge: "bg-white/[0.08] text-white/65",
  },
  "Proposal Sent": {
    bg: "bg-blue-50",
    header: "bg-blue-100 border-blue-200",
    badge: "bg-blue-200 text-blue-800",
  },
  Negotiation: {
    bg: "bg-yellow-50",
    header: "bg-yellow-100 border-yellow-200",
    badge: "bg-yellow-200 text-yellow-800",
  },
  Onboarded: {
    bg: "bg-green-50",
    header: "bg-green-100 border-green-200",
    badge: "bg-green-200 text-green-800",
  },
};

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const LS_KEY = "practicesync_pipeline";

function loadLeads(): Lead[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Lead[];
  } catch {
    return [];
  }
}

function saveLeads(leads: Lead[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, JSON.stringify(leads));
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
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
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
  onSave: (lead: Lead) => void;
  initial?: Lead | null;
}

const EMPTY_FORM = {
  name: "",
  phone: "",
  email: "",
  businessName: "",
  entityType: "Proprietorship" as EntityType,
  estimatedMonthlyFeeRupees: "",
  source: "Referral" as Source,
  notes: "",
  lastContactDate: new Date().toISOString().split("T")[0],
  nextFollowUpDate: "",
};

function AddLeadModal({ open, onClose, onSave, initial }: ModalProps) {
  const [form, setForm] = useState(EMPTY_FORM);

  useEffect(() => {
    if (open) {
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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
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
    onSave(lead);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-[#131620] rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.05]">
          <h2 className="text-base font-semibold text-white/85">
            {initial ? "Edit Lead" : "Add Lead"}
          </h2>
          <button
            onClick={onClose}
            className="text-white/30 hover:text-white/55"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-white/65 mb-1">
              Contact Name *
            </label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Full name"
              className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Phone + Email */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Phone *
              </label>
              <input
                required
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="10-digit mobile"
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Email
              </label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="email@example.com"
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          {/* Business Name */}
          <div>
            <label className="block text-xs font-medium text-white/65 mb-1">
              Business Name *
            </label>
            <input
              required
              value={form.businessName}
              onChange={(e) =>
                setForm({ ...form, businessName: e.target.value })
              }
              placeholder="Business / firm name"
              className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Entity Type + Source */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Entity Type *
              </label>
              <select
                value={form.entityType}
                onChange={(e) =>
                  setForm({ ...form, entityType: e.target.value as EntityType })
                }
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                {ENTITY_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Source *
              </label>
              <select
                value={form.source}
                onChange={(e) =>
                  setForm({ ...form, source: e.target.value as Source })
                }
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                {SOURCES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Monthly fee */}
          <div>
            <label className="block text-xs font-medium text-white/65 mb-1">
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
              className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Last Contact Date
              </label>
              <input
                type="date"
                value={form.lastContactDate}
                onChange={(e) =>
                  setForm({ ...form, lastContactDate: e.target.value })
                }
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-white/65 mb-1">
                Next Follow-up Date
              </label>
              <input
                type="date"
                value={form.nextFollowUpDate}
                onChange={(e) =>
                  setForm({ ...form, nextFollowUpDate: e.target.value })
                }
                className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs font-medium text-white/65 mb-1">
              Notes
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={3}
              placeholder="Any additional context…"
              className="w-full rounded-lg border border-white/[0.07] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-none"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg border border-white/[0.07] px-4 py-2 text-sm font-medium text-white/55 hover:bg-[#0e1017] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              {initial ? "Save Changes" : "Add Lead"}
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
    <div className="bg-[#131620] rounded-lg border border-white/[0.07] p-4 space-y-3 shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white/85 leading-tight">
            {lead.name}
          </p>
          <p className="text-xs text-white/40 truncate mt-0.5">
            {lead.businessName}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => onEdit(lead)}
            className="text-xs text-white/30 hover:text-white/55 px-1.5 py-0.5 rounded hover:bg-white/[0.06] transition-colors"
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(lead.id)}
            className="text-white/20 hover:text-red-500 transition-colors"
            aria-label="Delete lead"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Meta */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs text-white/40">
          <span className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-[10px] font-medium">
            {lead.entityType}
          </span>
          <span className="px-1.5 py-0.5 bg-[#0e1017] text-white/55 rounded text-[10px] font-medium">
            {lead.source}
          </span>
        </div>

        {lead.phone && (
          <div className="flex items-center gap-1.5 text-xs text-white/40">
            <Phone size={11} className="shrink-0" />
            <span>{lead.phone}</span>
          </div>
        )}

        {lead.email && (
          <div className="flex items-center gap-1.5 text-xs text-white/40">
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

        <div className="flex items-center gap-1.5 text-xs text-white/30">
          <Calendar size={11} className="shrink-0" />
          <span>Last: {formatDate(lead.lastContactDate)}</span>
        </div>

        {lead.nextFollowUpDate && (
          <div
            className={`flex items-center gap-1.5 text-xs font-medium ${
              overdue ? "text-red-600" : "text-white/40"
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
        {lead.stage === "Onboarded" ? (
          <button
            onClick={() => onConvert(lead)}
            className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-700 transition-colors"
          >
            <UserCheck size={12} />
            Convert to Client
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
// Convert to Client confirmation modal
// ---------------------------------------------------------------------------

interface ConvertModalProps {
  lead: Lead | null;
  onClose: () => void;
}

function ConvertModal({ lead, onClose }: ConvertModalProps) {
  if (!lead) return null;

  const params = new URLSearchParams({
    name: lead.name,
    phone: lead.phone,
    email: lead.email,
    businessName: lead.businessName,
    entityType: lead.entityType,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-[#131620] rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
            <UserCheck size={18} className="text-green-700" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white/85">
              Convert to Client
            </h2>
            <p className="text-xs text-white/40">
              {lead.name} · {lead.businessName}
            </p>
          </div>
        </div>

        <p className="text-sm text-white/55">
          This will pre-fill the Add Client form with{" "}
          <strong>{lead.name}&apos;s</strong> details. You can complete the remaining
          fields (PAN, GSTIN, etc.) on the Clients page.
        </p>

        <div className="flex gap-3 pt-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-lg border border-white/[0.07] px-4 py-2 text-sm font-medium text-white/55 hover:bg-[#0e1017] transition-colors"
          >
            Cancel
          </button>
          <Link
            href={`/clients?${params.toString()}&addNew=1`}
            className="flex-1 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 transition-colors text-center"
            onClick={onClose}
          >
            Go to Clients
          </Link>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PipelinePage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editLead, setEditLead] = useState<Lead | null>(null);
  const [convertLead, setConvertLead] = useState<Lead | null>(null);

  // Load from localStorage on mount
  useEffect(() => {
    setLeads(loadLeads());
  }, []);

  const persist = useCallback((updated: Lead[]) => {
    setLeads(updated);
    saveLeads(updated);
  }, []);

  function handleSave(lead: Lead) {
    setLeads((prev) => {
      const idx = prev.findIndex((l) => l.id === lead.id);
      const updated =
        idx >= 0
          ? prev.map((l, i) => (i === idx ? lead : l))
          : [lead, ...prev];
      saveLeads(updated);
      return updated;
    });
  }

  function handleMoveNext(lead: Lead) {
    const next = nextStage(lead.stage);
    if (!next) return;
    persist(leads.map((l) => (l.id === lead.id ? { ...l, stage: next } : l)));
  }

  function handleDelete(id: string) {
    persist(leads.filter((l) => l.id !== id));
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
          <div className="flex items-center gap-2 text-xs text-white/30 mb-1">
            <Link href="/clients" className="hover:text-white/55">
              Clients
            </Link>
            <ChevronRight size={12} />
            <span>Pipeline</span>
          </div>
          <h1 className="text-xl font-semibold text-white/85">
            Prospect Pipeline
          </h1>
          <p className="text-sm text-white/40 mt-0.5">
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
        <div className="bg-[#131620] rounded-lg border border-white/[0.05] px-4 py-3">
          <p className="text-xs text-white/40">Total Leads</p>
          <p className="text-xl font-bold text-white/85 mt-0.5">
            <Users size={14} className="inline mr-1 text-blue-500" />
            {totalLeads}
          </p>
        </div>
        <div className="bg-[#131620] rounded-lg border border-white/[0.05] px-4 py-3">
          <p className="text-xs text-white/40">Est. MRR (if all convert)</p>
          <p className="text-xl font-bold text-green-700 mt-0.5">
            {formatRupees(estimatedMRRPaise)}
          </p>
        </div>
        {STAGES.map((stage) => {
          const count = leads.filter((l) => l.stage === stage).length;
          return (
            <div
              key={stage}
              className="bg-[#131620] rounded-lg border border-white/[0.05] px-4 py-3"
            >
              <p className="text-xs text-white/40">{stage}</p>
              <p className="text-xl font-bold text-white/85 mt-0.5">{count}</p>
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

      {/* Kanban board */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((stage) => {
          const stageLeads = leads.filter((l) => l.stage === stage);
          const colors = STAGE_COLORS[stage];
          return (
            <div
              key={stage}
              className={`rounded-xl border ${colors.header} overflow-hidden`}
            >
              {/* Column header */}
              <div className={`px-4 py-3 border-b ${colors.header}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-white/75">
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
                  <div className="text-center py-10 text-xs text-white/30">
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
      />
    </div>
  );
}
