"use client";

import { useState, useEffect, FormEvent } from "react";
import { X } from "lucide-react";
import type { Client } from "@/lib/types";
import type { CreateClientInput } from "@/lib/data/clients";

const ENTITY_TYPES = [
  "Proprietorship", "Partnership", "LLP", "Private Limited",
  "Public Limited", "Trust", "Society", "Individual",
];

const STATES = [
  { code: "01", name: "Jammu & Kashmir" }, { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" }, { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" }, { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" }, { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" }, { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" }, { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" }, { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" }, { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" }, { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" }, { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" }, { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" }, { code: "24", name: "Gujarat" },
  { code: "27", name: "Maharashtra" }, { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" }, { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" }, { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (client: Client) => void;
  editClient?: Client | null;
}

const EMPTY: CreateClientInput = {
  client_name: "", entity_type: "Proprietorship", pan: "",
  gstin: "", mobile: "", email: "", city: "", state: "Maharashtra",
  state_code: "27", pincode: "", address_line1: "",
  gst_filing_frequency: "monthly", notes: "",
};

export function ClientFormModal({ open, onClose, onSaved, editClient }: Props) {
  const [form, setForm] = useState<CreateClientInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (editClient) {
      setForm({
        client_name: editClient.client_name,
        entity_type: editClient.entity_type,
        pan: editClient.pan,
        gstin: editClient.gstin ?? "",
        mobile: editClient.mobile ?? "",
        email: editClient.email ?? "",
        city: editClient.city ?? "",
        state: editClient.state ?? "Maharashtra",
        state_code: editClient.state_code ?? "27",
        pincode: editClient.pincode ?? "",
        address_line1: editClient.address_line1 ?? "",
        gst_filing_frequency: editClient.gst_filing_frequency ?? "monthly",
        notes: editClient.notes ?? "",
      });
    } else {
      setForm(EMPTY);
    }
    setError(null);
  }, [editClient, open]);

  function set(field: keyof CreateClientInput, value: string) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function handleStateChange(name: string) {
    const s = STATES.find(s => s.name === name);
    setForm(f => ({ ...f, state: name, state_code: s?.code ?? "" }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    // Validate PAN — IT Act format: AAAAA9999A
    if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(form.pan)) {
      setError("Invalid PAN format. Expected: AAAAA9999A (e.g. ABCDE1234F)");
      return;
    }
    // Validate GSTIN if provided — CGST Act Section 25
    if (form.gstin && !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(form.gstin)) {
      setError("Invalid GSTIN format. Expected: 27AAAAA9999A1ZB");
      return;
    }

    setSaving(true);
    try {
      const { createClient, updateClient } = await import("@/lib/data/clients");
      let saved: Client;
      if (editClient) {
        saved = await updateClient(editClient.id, form);
      } else {
        saved = await createClient(form);
      }
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save client");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <div>
            <h2 className="text-base font-semibold text-[#0F172A]">
              {editClient ? "Edit Client" : "Add New Client"}
            </h2>
            <p className="text-xs text-[#64748B] mt-0.5">
              {editClient ? "Update client details" : "Register a new client with your firm"}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#F1F5F9] text-[#94A3B8]">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Row 1 */}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#334155] mb-1">Client / Business Name *</label>
              <input
                required value={form.client_name}
                onChange={e => set("client_name", e.target.value)}
                placeholder="e.g. Sharma Enterprises"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Entity Type *</label>
              <select
                required value={form.entity_type}
                onChange={e => set("entity_type", e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                {ENTITY_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">GST Filing Frequency</label>
              <select
                value={form.gst_filing_frequency}
                onChange={e => set("gst_filing_frequency", e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                <option value="monthly">Monthly</option>
                <option value="quarterly">Quarterly</option>
              </select>
            </div>
          </div>

          {/* Tax IDs */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">PAN *</label>
              <input
                required value={form.pan}
                onChange={e => set("pan", e.target.value.toUpperCase())}
                placeholder="ABCDE1234F"
                maxLength={10}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">GSTIN</label>
              <input
                value={form.gstin}
                onChange={e => set("gstin", e.target.value.toUpperCase())}
                placeholder="27ABCDE1234F1ZB"
                maxLength={15}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>

          {/* Contact */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Mobile</label>
              <input
                value={form.mobile}
                onChange={e => set("mobile", e.target.value)}
                placeholder="+91 98765 43210"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Email</label>
              <input
                type="email" value={form.email}
                onChange={e => set("email", e.target.value)}
                placeholder="client@business.in"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {/* Address */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Address</label>
            <input
              value={form.address_line1}
              onChange={e => set("address_line1", e.target.value)}
              placeholder="Street address"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">City</label>
              <input
                value={form.city}
                onChange={e => set("city", e.target.value)}
                placeholder="Mumbai"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">State</label>
              <select
                value={form.state}
                onChange={e => handleStateChange(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                {STATES.map(s => <option key={s.code} value={s.name}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Pincode</label>
              <input
                value={form.pincode}
                onChange={e => set("pincode", e.target.value)}
                placeholder="400001"
                maxLength={6}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={e => set("notes", e.target.value)}
              rows={2}
              placeholder="Any additional notes about this client..."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button" onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC]"
            >
              Cancel
            </button>
            <button
              type="submit" disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {saving ? "Saving…" : editClient ? "Save Changes" : "Add Client"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
