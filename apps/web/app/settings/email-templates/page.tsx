"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Mail, Save } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";

// ── Types ──────────────────────────────────────────────────────────────────
type TemplateType = "invoice" | "engagement" | "document_request" | "reminder";

interface EmailTemplate {
  id?: string;
  template_type: TemplateType;
  subject: string;
  body: string;
  is_active: boolean;
}

const TEMPLATE_TABS: { type: TemplateType; label: string; desc: string }[] = [
  { type: "invoice", label: "Invoice", desc: "Sent when an invoice is issued or a payment reminder is due." },
  { type: "engagement", label: "Engagement", desc: "Sent when an engagement letter is ready for client review." },
  { type: "document_request", label: "Document Request", desc: "Sent when you request documents from a client." },
  { type: "reminder", label: "Reminder", desc: "Sent for upcoming compliance deadlines and due date reminders." },
];

const MERGE_FIELDS = [
  { field: "{{firm_name}}", label: "Firm Name" },
  { field: "{{client_name}}", label: "Client Name" },
  { field: "{{invoice_number}}", label: "Invoice #" },
  { field: "{{invoice_amount}}", label: "Invoice Amount" },
  { field: "{{due_date}}", label: "Due Date" },
  { field: "{{financial_year}}", label: "Financial Year" },
  { field: "{{portal_link}}", label: "Portal Link" },
];

const DEFAULT_TEMPLATES: Record<TemplateType, Omit<EmailTemplate, "id">> = {
  invoice: {
    template_type: "invoice",
    subject: "Invoice {{invoice_number}} from {{firm_name}}",
    body: `Dear {{client_name}},

Please find attached Invoice {{invoice_number}} for professional services rendered during {{financial_year}}.

Amount Due: {{invoice_amount}}
Payment Due: {{due_date}}

You can view and download your invoice through our secure client portal:
{{portal_link}}

For any queries, please reply to this email.

With regards,
{{firm_name}}`,
    is_active: true,
  },
  engagement: {
    template_type: "engagement",
    subject: "Engagement Letter from {{firm_name}} — Action Required",
    body: `Dear {{client_name}},

Please review and sign the engagement letter from {{firm_name}} for {{financial_year}}.

Access your engagement letter here:
{{portal_link}}

This letter outlines the scope of services, fees, and responsibilities. Kindly review and provide your electronic signature at your earliest convenience.

With regards,
{{firm_name}}`,
    is_active: true,
  },
  document_request: {
    template_type: "document_request",
    subject: "Documents Required — {{firm_name}}",
    body: `Dear {{client_name}},

To complete your compliance filings for {{financial_year}}, we require the following documents from you.

Please upload the requested documents through your secure client portal by {{due_date}}:
{{portal_link}}

If you have any questions about what is required, please don't hesitate to reach out.

With regards,
{{firm_name}}`,
    is_active: true,
  },
  reminder: {
    template_type: "reminder",
    subject: "Compliance Reminder — {{due_date}} | {{firm_name}}",
    body: `Dear {{client_name}},

This is a reminder that your compliance obligation is due on {{due_date}}.

Please log in to the client portal to review the status and upload any pending documents:
{{portal_link}}

If you have already taken care of this, please disregard this message.

With regards,
{{firm_name}}`,
    is_active: true,
  },
};

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

// ── Template Editor ────────────────────────────────────────────────────────
function TemplateEditor({
  templateType,
  initial,
  onSave,
}: {
  templateType: TemplateType;
  initial: Omit<EmailTemplate, "id"> | null;
  onSave: (data: Omit<EmailTemplate, "id">) => Promise<void>;
}) {
  const [subject, setSubject] = useState(initial?.subject ?? DEFAULT_TEMPLATES[templateType].subject);
  const [body, setBody] = useState(initial?.body ?? DEFAULT_TEMPLATES[templateType].body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave() {
    if (!subject.trim()) { setError("Subject is required"); return; }
    if (!body.trim()) { setError("Body is required"); return; }
    setSaving(true);
    setError("");
    try {
      await onSave({ template_type: templateType, subject: subject.trim(), body: body.trim(), is_active: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function insertMergeField(field: string) {
    setBody((b) => b + field);
  }

  function resetToDefault() {
    const def = DEFAULT_TEMPLATES[templateType];
    setSubject(def.subject);
    setBody(def.body);
  }

  return (
    <div className="space-y-4">
      {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      <div>
        <label className="text-xs font-medium text-[#64748B] block mb-1">Subject <span className="text-red-500">*</span></label>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Email subject line"
          className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium text-[#64748B]">Body <span className="text-red-500">*</span></label>
          <button onClick={resetToDefault} className="text-xs text-[#94A3B8] hover:text-[#475569] transition-colors">
            Reset to default
          </button>
        </div>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={10}
          className="w-full text-sm text-[#0F172A] font-mono border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] resize-none"
        />
      </div>

      <div>
        <p className="text-xs font-medium text-[#64748B] mb-2">Insert merge field</p>
        <div className="flex flex-wrap gap-1.5">
          {MERGE_FIELDS.map(({ field }) => (
            <button
              key={field}
              onClick={() => insertMergeField(field)}
              title={`Insert ${field}`}
              className="px-2.5 py-1 text-xs bg-[#F1F5F9] text-[#475569] rounded-md hover:bg-blue-50 hover:text-blue-700 border border-transparent hover:border-blue-200 transition-colors font-mono"
            >
              {field}
            </button>
          ))}
        </div>
        <p className="text-xs text-[#94A3B8] mt-1.5">Merge fields are replaced with real values when the email is sent.</p>
      </div>

      <div className="flex justify-end pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          <Save size={14} />
          {saving ? "Saving…" : "Save Template"}
        </button>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function EmailTemplatesPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<TemplateType>("invoice");
  const [templates, setTemplates] = useState<Record<TemplateType, EmailTemplate | null>>({
    invoice: null,
    engagement: null,
    document_request: null,
    reminder: null,
  });
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const showToast = (message: string, type: "success" | "error") => setToast({ message, type });

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await api.emailTemplates.list() as ApiResp<{ templates: EmailTemplate[] }>;
      if (res.success) {
        const map: Record<TemplateType, EmailTemplate | null> = {
          invoice: null, engagement: null, document_request: null, reminder: null,
        };
        for (const t of res.data.templates ?? []) {
          map[t.template_type] = t;
        }
        setTemplates(map);
      }
    } catch {
      showToast("Failed to load email templates", "error");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  async function handleSave(data: Omit<EmailTemplate, "id">) {
    await api.emailTemplates.upsert(data);
    showToast("Email template saved", "success");
    await load();
  }

  const activeTabInfo = TEMPLATE_TABS.find((t) => t.type === activeTab)!;

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="p-6 max-w-3xl mx-auto space-y-5">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

        <div>
          <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1">
            <ChevronLeft size={13} /> Settings
          </Link>
          <h1 className="text-xl font-semibold text-[#0F172A]">Email Templates</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Customize the emails sent to clients for invoices, engagements, and reminders.</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          {/* Tabs */}
          <div className="border-b border-[#F1F5F9] overflow-x-auto">
            <div className="flex px-2 pt-2 gap-1 min-w-max">
              {TEMPLATE_TABS.map((tab) => (
                <button
                  key={tab.type}
                  onClick={() => setActiveTab(tab.type)}
                  className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap ${
                    activeTab === tab.type
                      ? "bg-[#F8FAFC] border border-b-0 border-[#E2E8F0] text-[#0F172A]"
                      : "text-[#64748B] hover:text-[#334155]"
                  }`}
                >
                  <Mail size={13} />
                  {tab.label}
                  {templates[tab.type] ? (
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 ml-0.5" title="Saved" />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-[#CBD5E1] ml-0.5" title="Using default" />
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="px-5 py-4">
            <p className="text-xs text-[#94A3B8] mb-4">{activeTabInfo.desc}</p>
            {loading ? (
              <div className="py-8 text-center text-sm text-[#94A3B8]">Loading…</div>
            ) : (
              <TemplateEditor
                key={activeTab}
                templateType={activeTab}
                initial={templates[activeTab]}
                onSave={handleSave}
              />
            )}
          </div>
        </div>
      </div>
    </RoleGuard>
  );
}
