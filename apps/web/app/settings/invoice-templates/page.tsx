"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Star, Trash2, Check } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";

// ── Types ──────────────────────────────────────────────────────────────────
interface InvoiceTemplate {
  id: string;
  name: string;
  template_type: "classic" | "modern" | "professional_ca" | "corporate" | "minimal";
  logo_position: "left" | "center" | "right";
  header_style: "standard" | "compact" | "full";
  footer_style: "standard" | "minimal" | "detailed";
  signature_placement: "left" | "center" | "right" | "none";
  is_active: boolean;
  is_default: boolean;
  created_at: string;
}

const TEMPLATE_DESCRIPTIONS: Record<InvoiceTemplate["template_type"], { label: string; desc: string; accent: string }> = {
  classic: { label: "Classic", desc: "Traditional layout with header, itemized table, and signature block", accent: "bg-slate-100 text-slate-700" },
  modern: { label: "Modern", desc: "Clean lines, bold typography, contemporary look for modern firms", accent: "bg-blue-50 text-blue-700" },
  professional_ca: { label: "Professional CA", desc: "CA-specific with ICAI branding guidelines and compliance fields", accent: "bg-indigo-50 text-indigo-700" },
  corporate: { label: "Corporate", desc: "Formal layout suited for corporate clients and large engagements", accent: "bg-gray-100 text-gray-700" },
  minimal: { label: "Minimal", desc: "Stripped-back design focusing on the numbers and key details only", accent: "bg-green-50 text-green-700" },
};

const LOGO_POSITIONS = ["left", "center", "right"] as const;
const SIG_PLACEMENTS = ["left", "center", "right", "none"] as const;

// ── Toast ──────────────────────────────────────────────────────────────────
function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-sm font-medium ${
      type === "success" ? "bg-green-600 text-white" : "bg-red-600 text-white"
    }`}>
      <span>{message}</span>
      <button onClick={onClose} className="opacity-70 hover:opacity-100 text-lg leading-none">×</button>
    </div>
  );
}

// ── Create Modal ────────────────────────────────────────────────────────────
function CreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<InvoiceTemplate["template_type"]>("classic");
  const [logoPos, setLogoPos] = useState<"left" | "center" | "right">("left");
  const headerStyle = "standard";
  const footerStyle = "standard";
  const [sigPlacement, setSigPlacement] = useState<"left" | "center" | "right" | "none">("right");
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate() {
    if (!name.trim()) { setError("Template name is required"); return; }
    setSaving(true);
    try {
      await api.invoiceTemplates.create({
        name: name.trim(),
        template_type: type,
        logo_position: logoPos,
        header_style: headerStyle,
        footer_style: footerStyle,
        signature_placement: sigPlacement,
        is_default: isDefault,
      });
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create template");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-[#F1F5F9]">
          <h3 className="text-sm font-semibold text-[#0F172A]">New Invoice Template</h3>
        </div>
        <div className="px-6 py-4 space-y-4">
          {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          <div>
            <label className="text-xs font-medium text-[#64748B] block mb-1">Template Name <span className="text-red-500">*</span></label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => { setName(e.target.value); setError(""); }}
              placeholder="e.g. Standard Client Invoice"
              className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[#64748B] block mb-2">Layout Style</label>
            <div className="grid grid-cols-1 gap-2">
              {(Object.entries(TEMPLATE_DESCRIPTIONS) as [InvoiceTemplate["template_type"], (typeof TEMPLATE_DESCRIPTIONS)[keyof typeof TEMPLATE_DESCRIPTIONS]][]).map(([key, info]) => (
                <button
                  key={key}
                  onClick={() => setType(key)}
                  className={`flex items-start gap-3 p-3 rounded-lg border text-left transition-colors ${
                    type === key ? "border-blue-500 bg-blue-50" : "border-[#E2E8F0] hover:bg-[#F8FAFC]"
                  }`}
                >
                  <div className={`mt-0.5 px-2 py-0.5 rounded text-xs font-medium ${info.accent}`}>{info.label}</div>
                  <p className="text-xs text-[#64748B] mt-0.5">{info.desc}</p>
                  {type === key && <Check size={14} className="ml-auto shrink-0 text-blue-600 mt-0.5" />}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-[#64748B] block mb-1">Logo Position</label>
              <select value={logoPos} onChange={(e) => setLogoPos(e.target.value as typeof logoPos)} className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 bg-[#F8FAFC]">
                {LOGO_POSITIONS.map((p) => <option key={p} value={p} className="capitalize">{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-[#64748B] block mb-1">Signature</label>
              <select value={sigPlacement} onChange={(e) => setSigPlacement(e.target.value as typeof sigPlacement)} className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 bg-[#F8FAFC]">
                {SIG_PLACEMENTS.map((p) => <option key={p} value={p} className="capitalize">{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} className="w-4 h-4 text-blue-600 rounded" />
            <span className="text-sm text-[#334155]">Set as default template</span>
          </label>
        </div>
        <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-1.5 border border-[#E2E8F0] text-[#475569] text-sm rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={handleCreate} disabled={saving} className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Creating…" : "Create Template"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Template Card ──────────────────────────────────────────────────────────
function TemplateCard({
  template,
  onSetDefault,
  onDelete,
}: {
  template: InvoiceTemplate;
  onSetDefault: () => void;
  onDelete: () => void;
}) {
  const info = TEMPLATE_DESCRIPTIONS[template.template_type];
  return (
    <div className={`bg-white rounded-xl border overflow-hidden ${template.is_default ? "border-blue-300 ring-2 ring-blue-100" : "border-[#F1F5F9]"}`}>
      <div className="px-5 py-4 flex items-start justify-between">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 px-2 py-0.5 rounded text-xs font-medium ${info.accent}`}>{info.label}</div>
          <div>
            <p className="text-sm font-semibold text-[#0F172A]">{template.name}</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">{info.desc}</p>
          </div>
        </div>
        {template.is_default && (
          <span className="flex items-center gap-1 px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-medium rounded-full shrink-0">
            <Star size={10} fill="currentColor" /> Default
          </span>
        )}
      </div>

      <div className="px-5 pb-3 flex flex-wrap gap-2 text-xs text-[#64748B]">
        <span className="px-2 py-0.5 bg-[#F8FAFC] rounded border border-[#E2E8F0]">Logo: {template.logo_position}</span>
        <span className="px-2 py-0.5 bg-[#F8FAFC] rounded border border-[#E2E8F0]">Header: {template.header_style}</span>
        <span className="px-2 py-0.5 bg-[#F8FAFC] rounded border border-[#E2E8F0]">Footer: {template.footer_style}</span>
        <span className="px-2 py-0.5 bg-[#F8FAFC] rounded border border-[#E2E8F0]">Signature: {template.signature_placement}</span>
      </div>

      <div className="px-5 py-3 border-t border-[#F8FAFC] flex items-center gap-2">
        {!template.is_default && (
          <button onClick={onSetDefault} className="flex items-center gap-1.5 px-3 py-1 text-xs text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors">
            <Star size={11} /> Set as Default
          </button>
        )}
        {!template.is_default && (
          <button onClick={onDelete} className="flex items-center gap-1.5 px-3 py-1 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors ml-auto">
            <Trash2 size={11} /> Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function InvoiceTemplatesPage() {
  const { user } = useAuth();
  const [templates, setTemplates] = useState<InvoiceTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const showToast = (message: string, type: "success" | "error") => setToast({ message, type });

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await api.invoiceTemplates.list() as ApiResp<{ templates: InvoiceTemplate[] }>;
      if (res.success) setTemplates(res.data.templates ?? []);
      setLoadError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load templates";
      showToast(msg, "error");
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  async function handleSetDefault(id: string) {
    try {
      await api.invoiceTemplates.setDefault(id);
      showToast("Default template updated", "success");
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to update default", "error");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this template? This cannot be undone.")) return;
    try {
      await api.invoiceTemplates.delete(id);
      showToast("Template deleted", "success");
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to delete", "error");
    }
  }

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="p-6 max-w-3xl mx-auto space-y-5">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
        {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={load} />}

        <div>
          <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1">
            <ChevronLeft size={13} /> Settings
          </Link>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-[#0F172A]">Invoice Templates</h1>
              <p className="text-sm text-[#64748B] mt-0.5">Choose a layout style for your invoices and engagement documents.</p>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Plus size={14} /> New Template
            </button>
          </div>
        </div>

        {loading ? (
          <div className="py-12 text-center text-sm text-[#94A3B8]">Loading templates…</div>
        ) : loadError ? (
          <div className="py-12 text-center space-y-3">
            <p className="text-sm text-red-600 font-medium">{loadError}</p>
            <button
              onClick={() => load()}
              className="inline-flex items-center gap-1.5 px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-sm text-[#334155]"
            >
              Retry
            </button>
          </div>
        ) : templates.length === 0 ? (
          <div className="py-12 text-center space-y-3">
            <p className="text-sm text-[#64748B]">No invoice templates yet.</p>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              <Plus size={14} /> Create your first template
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {templates.map((t) => (
              <TemplateCard
                key={t.id}
                template={t}
                onSetDefault={() => handleSetDefault(t.id)}
                onDelete={() => handleDelete(t.id)}
              />
            ))}
          </div>
        )}
      </div>
    </RoleGuard>
  );
}
