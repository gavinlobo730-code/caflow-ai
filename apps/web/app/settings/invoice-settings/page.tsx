"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Hash, CreditCard, Save } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";

// ── Types ──────────────────────────────────────────────────────────────────
interface InvoiceSettings {
  id?: string;
  prefix: string;
  include_financial_year: boolean;
  sequence_length: number;
  starting_number: number;
  manual_override_allowed: boolean;
  bank_name: string;
  account_number: string;
  account_holder: string;
  ifsc_code: string;
  upi_id: string;
  upi_qr_url: string;
  footer_text: string;
}

const DEFAULT: InvoiceSettings = {
  prefix: "INV",
  include_financial_year: true,
  sequence_length: 3,
  starting_number: 1,
  manual_override_allowed: false,
  bank_name: "",
  account_number: "",
  account_holder: "",
  ifsc_code: "",
  upi_id: "",
  upi_qr_url: "",
  footer_text: "",
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

// ── Invoice Number Preview ─────────────────────────────────────────────────
function InvoiceNumberPreview({ settings, seq = 1 }: { settings: InvoiceSettings; seq?: number }) {
  const now = new Date();
  const fy = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const fyPart = settings.include_financial_year ? `-${fy}` : "";
  const seqStr = String(seq).padStart(settings.sequence_length, "0");
  return (
    <div className="bg-[#F8FAFC] rounded-lg border border-[#E2E8F0] px-4 py-3 text-center">
      <p className="text-xs text-[#94A3B8] mb-1">Next invoice number</p>
      <p className="text-xl font-mono font-bold text-[#0F172A]">
        {settings.prefix || "INV"}{fyPart}-{seqStr}
      </p>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function InvoiceSettingsPage() {
  const { user } = useAuth();
  const [form, setForm] = useState<InvoiceSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const showToast = (message: string, type: "success" | "error") => setToast({ message, type });

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await api.invoiceSettings.get() as ApiResp<{ invoice_settings: InvoiceSettings }>;
      if (res.success && res.data.invoice_settings && Object.keys(res.data.invoice_settings).length > 0) {
        setForm({ ...DEFAULT, ...res.data.invoice_settings });
      }
    } catch {
      showToast("Failed to load invoice settings", "error");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  function update<K extends keyof InvoiceSettings>(field: K, value: InvoiceSettings[K]) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSave() {
    const prefix = form.prefix.trim().toUpperCase();
    if (!prefix || !/^[A-Z0-9\-/]+$/.test(prefix)) {
      showToast("Prefix must be 1–10 uppercase alphanumeric characters", "error");
      return;
    }
    if (form.sequence_length < 3 || form.sequence_length > 6) {
      showToast("Sequence length must be between 3 and 6", "error");
      return;
    }
    if (form.ifsc_code && !/^[A-Z]{4}0[A-Z0-9]{6}$/.test(form.ifsc_code.trim().toUpperCase())) {
      showToast("IFSC code must be in valid RBI format (e.g. HDFC0001234)", "error");
      return;
    }

    setSaving(true);
    try {
      await api.invoiceSettings.update({
        prefix,
        include_financial_year: form.include_financial_year,
        sequence_length: form.sequence_length,
        starting_number: form.starting_number,
        manual_override_allowed: form.manual_override_allowed,
        bank_name: form.bank_name.trim() || null,
        account_number: form.account_number.trim() || null,
        account_holder: form.account_holder.trim() || null,
        ifsc_code: form.ifsc_code.trim().toUpperCase() || null,
        upi_id: form.upi_id.trim() || null,
        upi_qr_url: form.upi_qr_url.trim() || null,
        footer_text: form.footer_text.trim() || null,
      });
      showToast("Invoice settings saved", "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="p-6 max-w-3xl mx-auto space-y-5">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

        <div>
          <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1">
            <ChevronLeft size={13} /> Settings
          </Link>
          <h1 className="text-xl font-semibold text-[#0F172A]">Invoice Settings</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Configure invoice numbering, payment details, and footer text.</p>
        </div>

        {/* ── Invoice Numbering ────────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <Hash size={15} className="text-[#64748B]" />
            <h2 className="text-sm font-semibold text-[#0F172A]">Invoice Numbering</h2>
          </div>
          <div className="px-5 py-4 space-y-4">
            {loading ? (
              <div className="py-6 text-center text-sm text-[#94A3B8]">Loading…</div>
            ) : (
              <>
                <InvoiceNumberPreview settings={form} seq={form.starting_number} />

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium text-[#64748B] block mb-1">Prefix <span className="text-red-500">*</span></label>
                    <input
                      type="text"
                      value={form.prefix}
                      onChange={(e) => update("prefix", e.target.value.toUpperCase().slice(0, 10))}
                      placeholder="INV"
                      className="w-full text-sm font-mono text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                    />
                    <p className="text-xs text-[#94A3B8] mt-1">Up to 10 uppercase characters (e.g. INV, CF, GST)</p>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[#64748B] block mb-1">Sequence Digits</label>
                    <select
                      value={form.sequence_length}
                      onChange={(e) => update("sequence_length", Number(e.target.value))}
                      className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                    >
                      {[3, 4, 5, 6].map((n) => (
                        <option key={n} value={n}>{n} digits ({String(1).padStart(n, "0")} to {String(10 ** n - 1).padStart(n, "0")})</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[#64748B] block mb-1">Starting Number</label>
                    <input
                      type="number"
                      min={1}
                      value={form.starting_number}
                      onChange={(e) => update("starting_number", Math.max(1, Number(e.target.value)))}
                      className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                    />
                    <p className="text-xs text-[#94A3B8] mt-1">Use this to continue from a previous system's sequence</p>
                  </div>
                </div>

                <div className="flex items-center justify-between py-2 border-t border-[#F1F5F9]">
                  <div>
                    <p className="text-sm text-[#334155]">Include Financial Year</p>
                    <p className="text-xs text-[#94A3B8]">Adds the Indian financial year (e.g. 2025) to the number</p>
                  </div>
                  <button
                    onClick={() => update("include_financial_year", !form.include_financial_year)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      form.include_financial_year ? "bg-blue-600" : "bg-[#CBD5E1]"
                    }`}
                  >
                    <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                      form.include_financial_year ? "translate-x-4.5" : "translate-x-0.5"
                    }`} />
                  </button>
                </div>

                <div className="flex items-center justify-between py-2 border-t border-[#F1F5F9]">
                  <div>
                    <p className="text-sm text-[#334155]">Allow Manual Override</p>
                    <p className="text-xs text-[#94A3B8]">Let managers manually set an invoice number on creation</p>
                  </div>
                  <button
                    onClick={() => update("manual_override_allowed", !form.manual_override_allowed)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      form.manual_override_allowed ? "bg-blue-600" : "bg-[#CBD5E1]"
                    }`}
                  >
                    <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                      form.manual_override_allowed ? "translate-x-4.5" : "translate-x-0.5"
                    }`} />
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── Payment Details ──────────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <CreditCard size={15} className="text-[#64748B]" />
            <h2 className="text-sm font-semibold text-[#0F172A]">Payment Details</h2>
          </div>
          <div className="px-5 py-4 space-y-4">
            <p className="text-xs text-[#94A3B8]">These details appear on every invoice so clients can pay you directly.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">Bank Name</label>
                <input
                  type="text"
                  value={form.bank_name}
                  onChange={(e) => update("bank_name", e.target.value)}
                  placeholder="e.g. HDFC Bank"
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">Account Holder</label>
                <input
                  type="text"
                  value={form.account_holder}
                  onChange={(e) => update("account_holder", e.target.value)}
                  placeholder="e.g. Gavin Lobo & Associates"
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">Account Number</label>
                <input
                  type="text"
                  value={form.account_number}
                  onChange={(e) => update("account_number", e.target.value)}
                  placeholder="e.g. 50100123456789"
                  className="w-full text-sm font-mono text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">IFSC Code</label>
                <input
                  type="text"
                  value={form.ifsc_code}
                  onChange={(e) => update("ifsc_code", e.target.value.toUpperCase())}
                  placeholder="e.g. HDFC0001234"
                  maxLength={11}
                  className="w-full text-sm font-mono text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">UPI ID</label>
                <input
                  type="text"
                  value={form.upi_id}
                  onChange={(e) => update("upi_id", e.target.value)}
                  placeholder="e.g. firm@okaxis"
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">UPI QR Code URL</label>
                <input
                  type="url"
                  value={form.upi_qr_url}
                  onChange={(e) => update("upi_qr_url", e.target.value)}
                  placeholder="https://example.com/qr.png"
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-[#64748B] block mb-1">Invoice Footer Text</label>
              <textarea
                value={form.footer_text}
                onChange={(e) => update("footer_text", e.target.value)}
                rows={2}
                placeholder="e.g. Thank you for your business. Payment is due within 15 days. CGST registered under GSTIN 27AAAAA9999A1Z1."
                className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] resize-none"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </div>
    </RoleGuard>
  );
}
