"use client";

import { useState, useEffect, useCallback } from "react";
import {
  MessageSquare,
  Send,
  Copy,
  Check,
  ChevronRight,
  Users,
  History,
  ExternalLink,
  X,
  Plus,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Client } from "@/lib/types/index";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TemplateId =
  | "gstr1_reminder"
  | "gstr3b_reminder"
  | "document_collection"
  | "payment_reminder"
  | "itr_filing";

interface Template {
  id: TemplateId;
  label: string;
  description: string;
  variables: string[];
  body: string;
}

interface MessageHistoryEntry {
  id: string;
  clientName: string;
  clientPhone: string;
  templateLabel: string;
  message: string;
  sentAt: string; // ISO
}

interface ComposedMessage {
  client: Client;
  message: string;
  copied: boolean;
}

// ---------------------------------------------------------------------------
// Templates — pre-built messages for common CA firm workflows
// ---------------------------------------------------------------------------

const TEMPLATES: Template[] = [
  {
    id: "gstr1_reminder",
    label: "GSTR-1 Due Reminder",
    description: "Remind client to share sales data before GSTR-1 due date",
    // CGST Act Section 37 — GSTR-1 filing obligation
    variables: ["client_name", "period", "due_date", "data_deadline", "firm_name"],
    body: "Dear {client_name},\n\nYour GSTR-1 for {period} is due on {due_date}. Please share your sales invoices and data by {data_deadline} to ensure timely filing.\n\nFor any queries, feel free to reach out.\n\nRegards,\n{firm_name}",
  },
  {
    id: "gstr3b_reminder",
    label: "GSTR-3B Due Reminder",
    description: "Remind client about GSTR-3B payment and filing",
    // CGST Act Section 39 — GSTR-3B filing obligation
    variables: ["client_name", "period", "due_date", "firm_name"],
    body: "Dear {client_name},\n\nYour GSTR-3B for {period} is due on {due_date}. Please ensure your GST liability is paid and data is shared with us at the earliest.\n\nRegards,\n{firm_name}",
  },
  {
    id: "document_collection",
    label: "Document Collection",
    description: "Request documents from client for a specific purpose",
    variables: ["client_name", "document_list", "purpose", "firm_name"],
    body: "Dear {client_name},\n\nTo proceed with {purpose}, we require the following documents from you:\n\n{document_list}\n\nKindly share them at the earliest. Thank you for your cooperation.\n\nRegards,\n{firm_name}",
  },
  {
    id: "payment_reminder",
    label: "Fee Payment Reminder",
    description: "Remind client about outstanding professional fee",
    variables: ["client_name", "amount", "month", "firm_name"],
    body: "Dear {client_name},\n\nThis is a gentle reminder that your professional fee of ₹{amount} for {month} is due.\n\nKindly arrange the payment at your earliest convenience. Please contact us if you have any queries.\n\nRegards,\n{firm_name}",
  },
  {
    id: "itr_filing",
    label: "ITR Filing Reminder",
    description: "Remind client about income tax return filing",
    // IT Act Section 139 — ITR filing obligation
    variables: ["client_name", "ay", "due_date", "firm_name"],
    body: "Dear {client_name},\n\nYour Income Tax Return (ITR) for Assessment Year {ay} needs to be filed by {due_date}. Please confirm your income details and share the required documents with us.\n\nRegards,\n{firm_name}",
  },
];

// ---------------------------------------------------------------------------
// localStorage helpers — message history (max 20)
// ---------------------------------------------------------------------------

const LS_HISTORY_KEY = "practicesync_wa_history";
const MAX_HISTORY = 20;

function loadHistory(): MessageHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(LS_HISTORY_KEY);
    return raw ? (JSON.parse(raw) as MessageHistoryEntry[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(entries: MessageHistoryEntry[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(
    LS_HISTORY_KEY,
    JSON.stringify(entries.slice(0, MAX_HISTORY))
  );
}

function addToHistory(entry: Omit<MessageHistoryEntry, "id">): void {
  const existing = loadHistory();
  const newEntry: MessageHistoryEntry = { ...entry, id: `wa_${Date.now()}` };
  saveHistory([newEntry, ...existing]);
}

// ---------------------------------------------------------------------------
// Helper: replace template variables
// ---------------------------------------------------------------------------

function fillTemplate(template: string, vars: Record<string, string>): string {
  let result = template;
  for (const [key, value] of Object.entries(vars)) {
    result = result.replaceAll(`{${key}}`, value || `{${key}}`);
  }
  return result;
}

function buildWhatsAppUrl(phone: string, message: string): string {
  // Normalize phone: remove spaces, dashes, leading zeros; add +91 if Indian number
  let normalized = phone.replace(/[\s\-().]/g, "");
  if (normalized.startsWith("0")) normalized = normalized.slice(1);
  if (/^\d{10}$/.test(normalized)) normalized = `91${normalized}`;
  return `https://wa.me/${normalized}?text=${encodeURIComponent(message)}`;
}

// ---------------------------------------------------------------------------
// Supabase: fetch clients
// ---------------------------------------------------------------------------

async function fetchClients(): Promise<Client[]> {
  try {
    const sb = getSupabaseClient();
    const { data, error } = await sb
      .from("clients")
      .select("*")
      .is("deleted_at", null)
      .order("client_name");
    if (error || !data) return [];
    return data as Client[];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Variable input component
// ---------------------------------------------------------------------------

function VariableForm({
  variables,
  values,
  onChange,
}: {
  variables: string[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  const LABELS: Record<string, string> = {
    client_name: "Client Name",
    period: "Period (e.g. May 2026)",
    due_date: "Due Date",
    data_deadline: "Data Deadline (2 days before due)",
    firm_name: "Your Firm Name",
    document_list: "Document List",
    purpose: "Purpose",
    amount: "Amount (₹)",
    month: "Month (e.g. May 2026)",
    ay: "Assessment Year (e.g. 2026-27)",
  };

  return (
    <div className="space-y-3">
      {variables.map((v) => (
        <div key={v}>
          <label className="block text-xs font-medium text-[#334155] mb-1">
            {LABELS[v] ?? v.replaceAll("_", " ")}
          </label>
          {v === "document_list" ? (
            <textarea
              value={values[v] ?? ""}
              onChange={(e) => onChange(v, e.target.value)}
              rows={3}
              placeholder="e.g. • Bank statements\n• Purchase bills\n• Salary slips"
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-none"
            />
          ) : (
            <input
              value={values[v] ?? ""}
              onChange={(e) => onChange(v, e.target.value)}
              placeholder={`Enter ${LABELS[v] ?? v}`}
              className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single composed message card (for bulk view)
// ---------------------------------------------------------------------------

function BulkMessageCard({
  item,
  onCopy,
  onOpen,
  onRemove,
}: {
  item: ComposedMessage;
  onCopy: () => void;
  onOpen: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="bg-white rounded-lg border border-[#E2E8F0] p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#0F172A]">
            {item.client.client_name}
          </p>
          <p className="text-xs text-[#64748B]">
            {item.client.mobile ?? "No phone"} · {item.client.entity_type}
          </p>
        </div>
        <button
          onClick={onRemove}
          className="text-[#CBD5E1] hover:text-red-500 transition-colors"
          aria-label="Remove"
        >
          <X size={14} />
        </button>
      </div>

      <pre className="text-xs text-[#334155] bg-[#F8FAFC] rounded-lg p-3 whitespace-pre-wrap font-sans leading-relaxed">
        {item.message}
      </pre>

      <div className="flex gap-2">
        <button
          onClick={onCopy}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            item.copied
              ? "bg-green-50 text-green-700 border border-green-200"
              : "bg-[#F8FAFC] text-[#475569] border border-[#E2E8F0] hover:bg-[#F1F5F9]"
          }`}
        >
          {item.copied ? (
            <Check size={12} />
          ) : (
            <Copy size={12} />
          )}
          {item.copied ? "Copied!" : "Copy"}
        </button>
        {item.client.mobile && (
          <button
            onClick={onOpen}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-600 text-white hover:bg-green-700 transition-colors"
          >
            <ExternalLink size={12} />
            Open in WhatsApp
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type Tab = "compose" | "bulk" | "history";

export default function WhatsAppPage() {
  const [activeTab, setActiveTab] = useState<Tab>("compose");
  const [clients, setClients] = useState<Client[]>([]);
  const [loadingClients, setLoadingClients] = useState(true);

  // Compose tab state
  const [selectedTemplate, setSelectedTemplate] = useState<Template>(TEMPLATES[0]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [variableValues, setVariableValues] = useState<Record<string, string>>({});
  const [composedMessage, setComposedMessage] = useState("");
  const [copied, setCopied] = useState(false);

  // Bulk tab state
  const [bulkTemplate, setBulkTemplate] = useState<Template>(TEMPLATES[0]);
  const [bulkVars, setBulkVars] = useState<Record<string, string>>({});
  const [selectedClientIds, setSelectedClientIds] = useState<Set<string>>(new Set());
  const [bulkMessages, setBulkMessages] = useState<ComposedMessage[]>([]);
  const [bulkGenerated, setBulkGenerated] = useState(false);

  // History tab state
  const [history, setHistory] = useState<MessageHistoryEntry[]>([]);

  // Load clients + history
  useEffect(() => {
    setLoadingClients(true);
    void fetchClients().then((data) => {
      setClients(data);
      setLoadingClients(false);
    });
    setHistory(loadHistory());
  }, []);

  // Auto-fill client_name when client selected in compose tab
  useEffect(() => {
    if (!selectedClientId) return;
    const client = clients.find((c) => c.id === selectedClientId);
    if (!client) return;
    setVariableValues((prev) => ({
      ...prev,
      client_name: client.client_name,
    }));
  }, [selectedClientId, clients]);

  // Compose message live preview
  useEffect(() => {
    setComposedMessage(fillTemplate(selectedTemplate.body, variableValues));
  }, [selectedTemplate, variableValues]);

  // When template changes, reset variable values (keep firm_name)
  function handleTemplateChange(t: Template) {
    setSelectedTemplate(t);
    setVariableValues((prev) => ({
      firm_name: prev.firm_name ?? "",
      client_name: prev.client_name ?? "",
    }));
    setCopied(false);
  }

  function handleVarChange(key: string, value: string) {
    setVariableValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCopy(msg: string) {
    try {
      await navigator.clipboard.writeText(msg);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select text
    }
  }

  function handleOpenWhatsApp(phone: string, message: string, client: Client, template: Template) {
    window.open(buildWhatsAppUrl(phone, message), "_blank");
    // Record in history
    addToHistory({
      clientName: client.client_name,
      clientPhone: phone,
      templateLabel: template.label,
      message,
      sentAt: new Date().toISOString(),
    });
    setHistory(loadHistory());
  }

  // ---------------------------------------------------------------------------
  // Bulk handlers
  // ---------------------------------------------------------------------------

  function toggleBulkClient(id: string) {
    setSelectedClientIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setBulkGenerated(false);
  }

  function selectAllClients() {
    setSelectedClientIds(new Set(clients.map((c) => c.id)));
    setBulkGenerated(false);
  }

  function clearAllClients() {
    setSelectedClientIds(new Set());
    setBulkGenerated(false);
  }

  function generateBulkMessages() {
    const selected = clients.filter((c) => selectedClientIds.has(c.id));
    const messages: ComposedMessage[] = selected.map((client) => {
      const vars = { ...bulkVars, client_name: client.client_name };
      return {
        client,
        message: fillTemplate(bulkTemplate.body, vars),
        copied: false,
      };
    });
    setBulkMessages(messages);
    setBulkGenerated(true);
  }

  const handleBulkCopy = useCallback(
    async (idx: number) => {
      try {
        await navigator.clipboard.writeText(bulkMessages[idx].message);
        setBulkMessages((prev) =>
          prev.map((m, i) => (i === idx ? { ...m, copied: true } : m))
        );
        setTimeout(() => {
          setBulkMessages((prev) =>
            prev.map((m, i) => (i === idx ? { ...m, copied: false } : m))
          );
        }, 2000);
      } catch {
        // ignore
      }
    },
    [bulkMessages]
  );

  function handleBulkOpen(idx: number) {
    const item = bulkMessages[idx];
    if (!item.client.mobile) return;
    handleOpenWhatsApp(item.client.mobile, item.message, item.client, bulkTemplate);
  }

  function handleBulkRemove(idx: number) {
    setBulkMessages((prev) => prev.filter((_, i) => i !== idx));
  }

  function handleClearHistory() {
    saveHistory([]);
    setHistory([]);
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const selectedClient = clients.find((c) => c.id === selectedClientId);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-[#94A3B8] mb-1">
            <Link href="/notifications" className="hover:text-[#475569]">
              Notifications
            </Link>
            <ChevronRight size={12} />
            <span>WhatsApp Reminders</span>
          </div>
          <h1 className="text-xl font-semibold text-[#0F172A]">
            WhatsApp Reminder Templates
          </h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Compose and send WhatsApp messages to clients via WhatsApp Web
          </p>
        </div>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
        <MessageSquare size={16} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-sm text-blue-700">
          Messages open in WhatsApp Web — no API or business verification required.
          Click &ldquo;Open in WhatsApp&rdquo; to send directly from your phone or browser.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {(["compose", "bulk", "history"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors capitalize flex items-center gap-1.5 ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {tab === "compose" && <Send size={13} />}
            {tab === "bulk" && <Users size={13} />}
            {tab === "history" && <History size={13} />}
            {tab === "compose" ? "Compose" : tab === "bulk" ? "Bulk Send" : "History"}
            {tab === "history" && history.length > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#64748B] font-medium">
                {history.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* COMPOSE TAB                                                          */}
      {/* ------------------------------------------------------------------ */}
      {activeTab === "compose" && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          {/* Left: config */}
          <div className="space-y-4">
            {/* Template selector */}
            <div>
              <label className="block text-xs font-semibold text-[#334155] mb-2">
                Select Template
              </label>
              <div className="space-y-2">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => handleTemplateChange(t)}
                    className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
                      selectedTemplate.id === t.id
                        ? "border-blue-500 bg-blue-50"
                        : "border-[#E2E8F0] bg-white hover:bg-[#F8FAFC]"
                    }`}
                  >
                    <p
                      className={`text-sm font-medium ${
                        selectedTemplate.id === t.id
                          ? "text-blue-800"
                          : "text-[#1E293B]"
                      }`}
                    >
                      {t.label}
                    </p>
                    <p className="text-xs text-[#64748B] mt-0.5">
                      {t.description}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {/* Client selector */}
            <div>
              <label className="block text-xs font-semibold text-[#334155] mb-1">
                Select Client
              </label>
              {loadingClients ? (
                <div className="text-xs text-[#94A3B8] py-2">Loading clients…</div>
              ) : (
                <select
                  value={selectedClientId}
                  onChange={(e) => setSelectedClientId(e.target.value)}
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                >
                  <option value="">— Select a client —</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.client_name} {c.mobile ? `(${c.mobile})` : "(no phone)"}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Variables */}
            <div>
              <label className="block text-xs font-semibold text-[#334155] mb-2">
                Fill Variables
              </label>
              <VariableForm
                variables={selectedTemplate.variables}
                values={variableValues}
                onChange={handleVarChange}
              />
            </div>
          </div>

          {/* Right: preview + send */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-[#334155] mb-2">
                Message Preview
              </label>
              <div className="bg-[#e8f8e8] rounded-xl p-4 min-h-[200px] border border-green-200">
                <pre className="text-sm text-[#1E293B] whitespace-pre-wrap font-sans leading-relaxed">
                  {composedMessage}
                </pre>
              </div>
            </div>

            {/* Edit message directly */}
            <div>
              <label className="block text-xs font-semibold text-[#334155] mb-1">
                Edit Message (optional)
              </label>
              <textarea
                value={composedMessage}
                onChange={(e) => setComposedMessage(e.target.value)}
                rows={8}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-none font-mono"
              />
            </div>

            {/* Actions */}
            <div className="flex flex-col gap-2">
              <button
                onClick={() => void handleCopy(composedMessage)}
                className={`flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
                  copied
                    ? "bg-green-50 text-green-700 border border-green-200"
                    : "bg-[#F1F5F9] text-[#334155] hover:bg-white/[0.08] border border-[#E2E8F0]"
                }`}
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
                {copied ? "Copied to clipboard!" : "Copy Message"}
              </button>

              {selectedClient?.mobile ? (
                <button
                  onClick={() =>
                    handleOpenWhatsApp(
                      selectedClient.mobile!,
                      composedMessage,
                      selectedClient,
                      selectedTemplate
                    )
                  }
                  className="flex items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 transition-colors"
                >
                  <ExternalLink size={15} />
                  Open in WhatsApp
                </button>
              ) : (
                <div className="text-xs text-[#94A3B8] text-center py-1">
                  {selectedClientId
                    ? "Selected client has no phone number"
                    : "Select a client to enable WhatsApp send"}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* BULK TAB                                                             */}
      {/* ------------------------------------------------------------------ */}
      {activeTab === "bulk" && (
        <div className="space-y-5">
          {/* Template + variables */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[#334155] mb-2">
                  Template
                </label>
                <div className="space-y-2">
                  {TEMPLATES.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => {
                        setBulkTemplate(t);
                        setBulkVars({});
                        setBulkGenerated(false);
                      }}
                      className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
                        bulkTemplate.id === t.id
                          ? "border-blue-500 bg-blue-50"
                          : "border-[#E2E8F0] bg-white hover:bg-[#F8FAFC]"
                      }`}
                    >
                      <p
                        className={`text-sm font-medium ${
                          bulkTemplate.id === t.id
                            ? "text-blue-800"
                            : "text-[#1E293B]"
                        }`}
                      >
                        {t.label}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Shared variables (exclude client_name — auto-filled per client) */}
              <div>
                <label className="block text-xs font-semibold text-[#334155] mb-2">
                  Shared Variables
                </label>
                <p className="text-xs text-[#94A3B8] mb-2">
                  Client name is auto-filled for each client
                </p>
                <VariableForm
                  variables={bulkTemplate.variables.filter(
                    (v) => v !== "client_name"
                  )}
                  values={bulkVars}
                  onChange={(key, value) =>
                    setBulkVars((prev) => ({ ...prev, [key]: value }))
                  }
                />
              </div>
            </div>

            {/* Client multi-select */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-semibold text-[#334155]">
                  Select Clients ({selectedClientIds.size} selected)
                </label>
                <div className="flex gap-2">
                  <button
                    onClick={selectAllClients}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    All
                  </button>
                  <button
                    onClick={clearAllClients}
                    className="text-xs text-[#94A3B8] hover:underline"
                  >
                    Clear
                  </button>
                </div>
              </div>

              {loadingClients ? (
                <div className="text-xs text-[#94A3B8]">Loading clients…</div>
              ) : clients.length === 0 ? (
                <div className="text-xs text-[#94A3B8]">No clients found</div>
              ) : (
                <div className="border border-[#E2E8F0] rounded-lg overflow-hidden max-h-80 overflow-y-auto">
                  {clients.map((client, idx) => (
                    <label
                      key={client.id}
                      className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-[#F8FAFC] transition-colors ${
                        idx > 0 ? "border-t border-[#F1F5F9]" : ""
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedClientIds.has(client.id)}
                        onChange={() => toggleBulkClient(client.id)}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-[#0F172A]">
                          {client.client_name}
                        </p>
                        <p className="text-xs text-[#64748B]">
                          {client.mobile ?? "No phone"} · {client.entity_type}
                        </p>
                      </div>
                      {!client.mobile && (
                        <span className="text-[10px] text-red-600 font-medium">
                          No phone
                        </span>
                      )}
                    </label>
                  ))}
                </div>
              )}

              <button
                onClick={generateBulkMessages}
                disabled={selectedClientIds.size === 0}
                className="w-full mt-3 flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Plus size={15} />
                Generate Messages ({selectedClientIds.size})
              </button>
            </div>
          </div>

          {/* Generated messages */}
          {bulkGenerated && bulkMessages.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-[#334155]">
                  Generated Messages ({bulkMessages.length})
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {bulkMessages.map((item, idx) => (
                  <BulkMessageCard
                    key={`${item.client.id}-${idx}`}
                    item={item}
                    onCopy={() => void handleBulkCopy(idx)}
                    onOpen={() => handleBulkOpen(idx)}
                    onRemove={() => handleBulkRemove(idx)}
                  />
                ))}
              </div>
            </div>
          )}

          {bulkGenerated && bulkMessages.length === 0 && (
            <div className="text-center py-10 text-sm text-[#94A3B8]">
              All messages removed
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* HISTORY TAB                                                          */}
      {/* ------------------------------------------------------------------ */}
      {activeTab === "history" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-[#64748B]">
              Last {Math.min(history.length, MAX_HISTORY)} messages sent
            </p>
            {history.length > 0 && (
              <button
                onClick={handleClearHistory}
                className="flex items-center gap-1.5 text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded hover:bg-red-50 transition-colors"
              >
                <Trash2 size={12} />
                Clear History
              </button>
            )}
          </div>

          {history.length === 0 ? (
            <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-16 text-center space-y-3">
              <History className="w-10 h-10 text-gray-200 mx-auto" />
              <p className="text-sm font-medium text-[#475569]">
                No messages sent yet
              </p>
              <p className="text-xs text-[#94A3B8]">
                Messages you send via WhatsApp Web will appear here
              </p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden divide-y divide-[#F8FAFC]">
              {history.map((entry) => (
                <div key={entry.id} className="px-5 py-4 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-[#0F172A]">
                        {entry.clientName}
                      </p>
                      <p className="text-xs text-[#64748B]">
                        {entry.clientPhone} · {entry.templateLabel}
                      </p>
                    </div>
                    <p className="text-xs text-[#94A3B8] shrink-0">
                      {new Date(entry.sentAt).toLocaleDateString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>
                  <pre className="text-xs text-[#475569] bg-[#F8FAFC] rounded-lg p-3 whitespace-pre-wrap font-sans leading-relaxed">
                    {entry.message}
                  </pre>
                  {entry.clientPhone && (
                    <button
                      onClick={() =>
                        window.open(
                          buildWhatsAppUrl(entry.clientPhone, entry.message),
                          "_blank"
                        )
                      }
                      className="flex items-center gap-1.5 text-xs text-green-700 hover:text-green-800 font-medium"
                    >
                      <ExternalLink size={11} />
                      Resend via WhatsApp
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
