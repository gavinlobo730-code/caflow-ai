"use client";

/** Create or edit one employee.
 *
 *  Every rupee field goes through paiseFromRupeeInput and every percentage
 *  through bpsFromPercentInput — both REFUSE rather than coerce, because
 *  parseFloat("1,25,000") is 1 and a basic salary read wrong is the base for
 *  PF, HRA, gratuity and every month's withholding thereafter. */

import { useState } from "react";
import { X } from "lucide-react";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { api } from "@/lib/api";
import { PT_STATES, type Client, type Employee } from "@/components/payroll/shared";

export function AddEmployeeModal({
  clients,
  employee,
  onClose,
  onSaved,
}: {
  clients: Client[];
  employee?: Employee | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!employee;
  const [form, setForm] = useState({
    client_id: employee?.client_id ?? clients[0]?.id ?? "",
    name: employee?.name ?? "",
    pan: employee?.pan ?? "",
    gender: employee?.gender ?? "",
    designation: employee?.designation ?? "",
    basic_rs: employee ? String(employee.basic_paise / 100) : "",
    hra_percent: employee ? String(employee.hra_percent ?? 0) : "40",
    da_percent: employee ? String(employee.da_percent ?? 0) : "10",
    other_rs: employee ? String((employee.other_allowances_paise ?? 0) / 100) : "0",
    pf_applicable: employee?.pf_applicable ?? false,
    esi_applicable: employee?.esi_applicable ?? false,
    pt_state: employee?.pt_applicable ? (employee.pt_state ?? "NONE") : "NONE",
    // The identifiers three FINISHED statutory outputs need and no screen
    // collected. domain/payroll/ecr.py refuses a member whose UAN is absent or
    // not 12 digits; esic.py needs the IP number; the s.192 projection needs
    // the joining date or it annualises a mid-year joiner's pay and
    // over-deducts (the 2026-09-01 audit measured Rs 1,46,250 on one
    // employee). The API has always accepted all of them — models/payroll.py
    // EmployeeIn — so this is the form catching up with the engine.
    uan: employee?.uan ?? "",
    esi_number: employee?.esi_number ?? "",
    joining_date: employee?.joining_date ?? "",
    department: employee?.department ?? "",
    bank_account_no: employee?.bank_account_no ?? "",
    bank_ifsc: employee?.bank_ifsc ?? "",
    bank_name: employee?.bank_name ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!form.name || !form.basic_rs) { setErr("Name and Basic Salary are required."); return; }

    // The exact parsers, and they REFUSE rather than coerce.
    //
    // These four fields used to be `parseFloat(x) || 0`, which CLAUDE.md
    // records as removed from all 61 money call sites — this form was missed.
    // parseFloat("1,25,000") is 1, so a CA typing an amount the way Indian
    // amounts are grouped set a basic salary of ONE RUPEE, and everything
    // downstream — HRA, DA, the PF wage, the s.192 projection, the payslip —
    // followed it without complaint. parseFloat("") is NaN, which
    // JSON.stringify sends as null. The CSV importer eleven hundred lines
    // below already carries the comment explaining this; the form beside it
    // did not.
    //
    // A percentage goes through the same parser and comes back in basis
    // points; the API takes a percent, and _percent_of reads it with
    // Decimal(str(...)), so 4050 bps -> 40.5 is exact on both sides.
    const basicPaise = paiseFromRupeeInput(form.basic_rs);
    const otherPaise = paiseFromRupeeInput(form.other_rs);
    const hraBps = bpsFromPercentInput(form.hra_percent);
    const daBps = bpsFromPercentInput(form.da_percent);
    const rejected = [
      basicPaise === null ? "Basic Salary" : null,
      otherPaise === null ? "Other Allowances" : null,
      hraBps === null ? "HRA %" : null,
      daBps === null ? "DA %" : null,
    ].filter((f): f is string => f !== null);
    if (basicPaise === null || otherPaise === null || hraBps === null || daBps === null) {
      setErr(`${rejected.join(", ")} ${rejected.length === 1 ? "is not a number" : "are not numbers"} — type digits only, without commas.`);
      return;
    }

    setSaving(true);
    setErr("");
    try {
      const payload = {
        name: form.name,
        pan: form.pan.toUpperCase() || null,
        gender: form.gender || null,
        designation: form.designation || null,
        basic_paise: basicPaise,
        hra_percent: hraBps / 100,
        da_percent: daBps / 100,
        other_allowances_paise: otherPaise,
        pf_applicable: form.pf_applicable,
        esi_applicable: form.esi_applicable,
        // Professional Tax — state-specific slab, computed server-side (R2.10).
        pt_applicable: form.pt_state !== "NONE",
        pt_state: form.pt_state === "NONE" ? null : form.pt_state,
        uan: form.uan.trim() || null,
        esi_number: form.esi_number.trim() || null,
        joining_date: form.joining_date || null,
        department: form.department.trim() || null,
        bank_account_no: form.bank_account_no.trim() || null,
        bank_ifsc: form.bank_ifsc.trim().toUpperCase() || null,
        bank_name: form.bank_name.trim() || null,
      };
      if (isEdit && employee) {
        // client_id can't change on edit (EmployeeUpdateIn has no client_id).
        await api.payroll.updateEmployee(employee.id, payload);
      } else {
        await api.payroll.createEmployee({ client_id: form.client_id, ...payload });
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Failed to ${isEdit ? "update" : "add"} employee.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-[#0F172A]">{isEdit ? "Edit Employee" : "Add Employee"}</h2>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
            {isEdit ? (
              <div className="w-full border rounded-lg px-3 py-2 text-sm bg-[#F8FAFC] text-[#64748B]">
                {clients.find(c => c.id === form.client_id)?.client_name ?? "—"}
              </div>
            ) : (
              <div className="w-full">
                <ClientLookup
                  clients={clients}
                  value={form.client_id}
                  onChange={(id) => setForm(f => ({ ...f, client_id: id }))}
                  ariaLabel="Client"
                  placeholder="Select client…"
                />
              </div>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Name *</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">PAN</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm uppercase" value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value }))} maxLength={10} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Designation</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.designation} onChange={e => setForm(f => ({ ...f, designation: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Gender</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.gender} onChange={e => setForm(f => ({ ...f, gender: e.target.value }))}>
              <option value="">Not specified</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
            <p className="text-[10px] text-[#94A3B8] mt-1">Used for Maharashtra PT — women earning ≤ ₹25,000/month are exempt.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Basic Salary (Rs/month) *</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.basic_rs} onChange={e => setForm(f => ({ ...f, basic_rs: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">HRA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.hra_percent} onChange={e => setForm(f => ({ ...f, hra_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">DA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.da_percent} onChange={e => setForm(f => ({ ...f, da_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Other Allowances (Rs)</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.other_rs} onChange={e => setForm(f => ({ ...f, other_rs: e.target.value }))} />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="pf" checked={form.pf_applicable} onChange={e => setForm(f => ({ ...f, pf_applicable: e.target.checked }))} />
            <label htmlFor="pf" className="text-sm text-[#334155]">PF Applicable (12% of basic)</label>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="esi" checked={form.esi_applicable} onChange={e => setForm(f => ({ ...f, esi_applicable: e.target.checked }))} />
            <label htmlFor="esi" className="text-sm text-[#334155]">ESI Applicable (if &le; Rs 21,000)</label>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Professional Tax (state)</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.pt_state} onChange={e => setForm(f => ({ ...f, pt_state: e.target.value }))}>
              {PT_STATES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
          </div>

          {/* Statutory identifiers. Each hint says what is NOT POSSIBLE without
              the field, rather than "optional" — the ECR, the ESIC return and
              the s.192 projection are all finished and all refuse without
              these, and a blank whose consequence is unstated gets left blank. */}
          <div className="col-span-2 border-t pt-3 mt-1">
            <p className="text-xs font-medium text-[#0F172A]">Statutory identifiers</p>
            <p className="text-[11px] text-[#64748B]">
              Blank is allowed. Each one names what cannot be produced without it.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">UAN</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.uan}
                   onChange={e => setForm(f => ({ ...f, uan: e.target.value }))} maxLength={12} inputMode="numeric" />
            <p className="text-[10px] text-[#94A3B8] mt-0.5">12 digits. Without it this member cannot go in the EPFO ECR.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">ESIC IP number</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.esi_number}
                   onChange={e => setForm(f => ({ ...f, esi_number: e.target.value }))} />
            <p className="text-[10px] text-[#94A3B8] mt-0.5">Without it this member cannot go in the ESIC return.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Joining date</label>
            <input type="date" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.joining_date}
                   onChange={e => setForm(f => ({ ...f, joining_date: e.target.value }))} />
            <p className="text-[10px] text-[#94A3B8] mt-0.5">
              Without it a mid-year joiner&apos;s tax is estimated over twelve months, not the months they actually work — which over-deducts.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Department</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.department}
                   onChange={e => setForm(f => ({ ...f, department: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Bank account number</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.bank_account_no}
                   onChange={e => setForm(f => ({ ...f, bank_account_no: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">IFSC</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm uppercase" value={form.bank_ifsc}
                   onChange={e => setForm(f => ({ ...f, bank_ifsc: e.target.value }))} maxLength={11} />
            <p className="text-[10px] text-[#94A3B8] mt-0.5">The account and IFSC are what a salary payment file is built from.</p>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Bank name</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.bank_name}
                   onChange={e => setForm(f => ({ ...f, bank_name: e.target.value }))} />
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : isEdit ? "Update Employee" : "Add Employee"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Payslip Modal ─────────────────────────────────────────────────────────

