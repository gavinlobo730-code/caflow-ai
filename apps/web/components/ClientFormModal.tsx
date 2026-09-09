"use client";

import { useState, useEffect, FormEvent } from "react";
import { X } from "lucide-react";
import type { Client } from "@/lib/types";
import type { CreateClientInput } from "@/lib/data/clients";

import { INDIAN_STATES } from "@/lib/constants/indianStates";
const ENTITY_TYPES = [
  "Proprietorship", "Partnership", "LLP", "Private Limited",
  "Public Limited", "Trust", "Society", "Individual",
];

// THE CANONICAL LIST, not a fifth copy. This held 31 of the 36 live codes —
// Dadra & Nagar Haveli and Daman & Diu (26), Lakshadweep (31), Puducherry (34),
// Andaman & Nicobar (35) and Ladakh (38) were absent — on the CLIENT master,
// where state_code is the field every downstream document reads to decide
// CGST+SGST against IGST. A client in Ladakh could not be onboarded with a
// state code at all. The names here were identical to the canonical ones, so
// this is purely additive and orphans no stored value.
const STATES = INDIAN_STATES;

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
  gst_filing_frequency: "monthly", gst_advance_tax_applicable: false, notes: "",
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
        pan: editClient.pan ?? "",
        gstin: editClient.gstin ?? "",
        mobile: editClient.mobile ?? "",
        email: editClient.email ?? "",
        city: editClient.city ?? "",
        state: editClient.state ?? "Maharashtra",
        state_code: editClient.state_code ?? "27",
        pincode: editClient.pincode ?? "",
        address_line1: editClient.address_line1 ?? "",
        gst_filing_frequency: editClient.gst_filing_frequency ?? "monthly",
        gst_advance_tax_applicable: Boolean(
          (editClient as { gst_advance_tax_applicable?: boolean | null }).gst_advance_tax_applicable),
        notes: editClient.notes ?? "",
      });
    } else {
      setForm(EMPTY);
    }
    setError(null);
  }, [editClient, open]);

  function set(field: keyof CreateClientInput, value: string | boolean) {
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
      <div className="absolute inset-0 bg-[#F8FAFC]/60" onClick={onClose} />

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

          {/* GSTR-1 Tables 11A and 11B. Off by default, which is the right
              default: Notification 66/2017-Central Tax removed the charge on
              advances for GOODS, so most registered persons have no Table 11 at
              all. A supplier of SERVICES turns it on (CGST s.13(2)).

              The column has existed since migration 286 and the return builder
              has read it since; nothing ever wrote it, so Table 11 was empty
              for every client on the platform and no screen said whether that
              meant "no advances" or "not switched on". */}
          <label className="flex items-start gap-2 text-sm text-[#334155] cursor-pointer">
            <input
              type="checkbox"
              checked={Boolean(form.gst_advance_tax_applicable)}
              onChange={e => set("gst_advance_tax_applicable", e.target.checked)}
              className="mt-0.5 rounded"
            />
            <span>
              Advances received bear GST
              <span className="block text-xs text-[#64748B]">
                CGST s.13(2) — tax on an advance is due when it is received for a
                SUPPLY OF SERVICES. Notification 66/2017-Central Tax removed the
                charge for goods, where the liability arises at the invoice. Turn
                this on and the receipt form asks for the rate and place of
                supply an advance is declared at in GSTR-1 Table 11A.
              </span>
            </span>
          </label>

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
                placeholder="27ABCDE1234F1Z5"
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
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-gray-900 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {saving ? "Saving…" : editClient ? "Save Changes" : "Add Client"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
