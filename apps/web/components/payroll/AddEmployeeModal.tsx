"use client";

/** Create or edit one employee. THE ONLY EMPLOYEE FORM IN THE PRODUCT.
 *
 *  PAY-13. There were two, and they disagreed about what an employee IS. This
 *  one held PAN, UAN, ESIC number, joining date, bank details, gender, DA, EPS
 *  eligibility and Gratuity Act coverage; the client workspace's own inline
 *  form (app/clients/[id]/payroll/page.tsx) held employee code, date of birth
 *  and Aadhaar and NONE of the first list. So which screen a CA happened to
 *  add an employee from decided whether:
 *
 *    * `domain/payroll/ecr.py` would accept them at all — it REFUSES a member
 *      whose UAN is absent or not twelve digits, so a whole EPFO filing
 *      stopped on an employee added from the client screen;
 *    * §192 withheld at the ordinary rate or at §206AA's 20% floor, which is
 *      what a missing PAN costs;
 *    * the §192 projection annualised a mid-year joiner's pay correctly — the
 *      2026-09-01 audit measured ₹1,46,250 of over-deduction on one employee
 *      with no joining date;
 *    * there was a bank account to pay them into.
 *
 *  Neither form could be fixed by adding fields to it: two forms is the
 *  defect. This one takes the UNION and the client screen now opens it, so the
 *  Aadhaar last-4 rule and the employee code stop being reachable from only
 *  one of the two surfaces. `scripts/one-employee-form.test.ts` holds the line.
 *
 *  Every rupee field goes through paiseFromRupeeInput and every percentage
 *  through bpsFromPercentInput — both REFUSE rather than coerce, because
 *  parseFloat("1,25,000") is 1 and a basic salary read wrong is the base for
 *  PF, HRA, gratuity and every month's withholding thereafter. */

import { useState } from "react";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { api } from "@/lib/api";
import { removedEmployeeIdentifiers, type EmployeeIdentifier } from "@/lib/payroll/employeeIdentifiers";
import { PT_STATES, type Client, type Employee } from "@/components/payroll/shared";

export function AddEmployeeModal({
  clients,
  employee,
  lockedClientId,
  teamMember,
  onClose,
  onSaved,
}: {
  clients: Client[];
  employee?: Employee | null;
  /** The client workspace already knows whose payroll this is, so the picker
   *  is shown as a fixed label there. Locking it rather than hiding it: a form
   *  that does not say which client it is adding to is how an employee lands
   *  on the wrong one. */
  lockedClientId?: string;
  /** A NEW employee of the firm's own payroll who IS a team member (POST-A-540): the name box starts from the sign-in's name
   *  (and stays editable, because the two records are linked and never merged) and the employee is created linked to them.
   *  The server asks whether the link is allowed before it writes anything. Ignored on an edit: the link has its own control. */
  teamMember?: { id: string; name: string };
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!employee;
  const clientLocked = !!lockedClientId;
  const [form, setForm] = useState({
    client_id: employee?.client_id ?? lockedClientId ?? clients[0]?.id ?? "",
    name: employee?.name ?? teamMember?.name ?? "",
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
    // TWO EXCEPTIONS THAT COULD NOT BE RECORDED FROM ANYWHERE (PAY-12).
    // Both columns are `NOT NULL DEFAULT true` (migrations 295 and 298), both
    // are read by the engine, and neither was on a model, in the CSV or on a
    // form — so every employee was EPS-eligible and Gratuity-Act-covered
    // forever. Defaulting TRUE here matches the column, so an existing
    // employee's saved value is what shows and a new one starts at the
    // ordinary case.
    eps_eligible: employee?.eps_eligible ?? true,
    gratuity_act_covered: employee?.gratuity_act_covered ?? true,
    // FIXED-TERM EMPLOYMENT (POST-A-526, migration 770). Unticked is "never recorded" or "withdrawn": `save()` sends nothing for the first
    // and `false` for the second, as the PF election does, so an ordinary save never names the new columns.
    fixed_term_employment: employee?.fixed_term_employment === true,
    fixed_term_end_date: employee?.fixed_term_end_date ?? "",
    // THE EMPLOYER'S PF ELECTION (payroll-22, migration 477). Unticked is
    // "never recorded" or "withdrawn" — the server tells them apart and so does
    // `save()` below: it sends nothing for the first and `false` for the second.
    // The date and the reference are text typed here and judged by the server.
    pf_on_actual_wages: employee?.pf_on_actual_wages === true,
    pf_on_actual_wages_from: employee?.pf_on_actual_wages_from ?? "",
    pf_on_actual_wages_reference: employee?.pf_on_actual_wages_reference ?? "",
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
    // THE THREE THE CLIENT SCREEN HELD AND THIS DID NOT (PAY-13).
    // `employee_code` is the identifier the CLIENT uses — EMP001, a number off
    // their previous payroll software — unique per client (migration 333) and
    // what the bulk import is idempotent on, so without it "fix the
    // spreadsheet and upload it again" creates duplicates instead of updating.
    // `date_of_birth` is NOT demographics: Part III of the First Schedule
    // widens the OLD-regime nil band at 60 and again at 80, and
    // domain/payroll/age.py reads it to decide which ladder §192 withholds on.
    employee_code: employee?.employee_code ?? "",
    date_of_birth: employee?.date_of_birth ?? "",
    // AADHAAR IS TYPED IN FULL AND NEVER SENT IN FULL. models/payroll.py says
    // it plainly — "we store ONLY the last 4 digits ... The full value must
    // never reach the backend" — so the twelve digits are validated here and
    // `aadhaar_last4` is what crosses the wire. Blank on edit rather than
    // pre-filled, because the stored value IS only four digits and showing
    // them in a twelve-digit box invites somebody to save those four as the
    // whole number.
    aadhaar: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  // All three dates are optional and every one of them moves money when blank: no date of birth means no age relief, no joining date
  // means a mid-year joiner's tax is spread over twelve months, no start date means PF on actual wages from the first month. Text that is
  // not a date reads as blank, so the save is refused instead (frontend_ux-19).
  const dates = useDateProblems();
  // On an edit, a PAN, UAN, ESI number, bank account number or IFSC on file is corrected and never removed: a box emptied over one is marked
  // where it is, in the server's words, and the Save says it without sending (POST-A-465). The server refuses the same edit whatever is sent.
  const removed = isEdit && employee
    ? removedEmployeeIdentifiers(
        { pan: employee.pan, uan: employee.uan, esi_number: employee.esi_number,
          bank_account_no: employee.bank_account_no, bank_ifsc: employee.bank_ifsc },
        { pan: form.pan, uan: form.uan, esi_number: form.esi_number,
          bank_account_no: form.bank_account_no, bank_ifsc: form.bank_ifsc })
    : [];
  const removedAt = (field: EmployeeIdentifier) => removed.find((r) => r.field === field)?.sentence ?? null;
  const boxClass = (field: EmployeeIdentifier, extra = "") =>
    `w-full border rounded-lg px-3 py-2 text-sm${extra}${removedAt(field) ? " border-state-problem" : ""}`;

  async function save() {
    if (dates.first) { dates.refuseWith(setErr, undefined, ""); return; }
    if (removed.length) { setErr(removed[0].sentence); return; }
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
      setErr(`${rejected.join(", ")} ${rejected.length === 1 ? "is not a number" : "are not numbers"} — type numbers only (an amount may be grouped like 1,25,000; a percentage takes no comma).`);
      return;
    }

    // Aadhaar: twelve digits or nothing. Checked BEFORE the request, because
    // the backend only ever sees four and cannot tell a truncated eleven-digit
    // number from a correct one.
    const aadhaarDigits = form.aadhaar.replace(/\D/g, "");
    if (aadhaarDigits && aadhaarDigits.length !== 12) {
      setErr("Aadhaar must be 12 digits. Only the last 4 are stored.");
      return;
    }

    // The PF election, as the server's three-state column needs it said. An
    // election that is ticked with PF on is sent with its date and reference
    // (blank text clears them on an edit); one that WAS recorded and is now
    // unticked, or whose PF has been switched off, is sent as `false` — a
    // withdrawal; and one never recorded sends nothing, so NULL stays NULL
    // rather than becoming a recorded "no".
    const priorElection = employee?.pf_on_actual_wages === true;
    const electionFields =
      form.pf_applicable && form.pf_on_actual_wages
        ? {
            pf_on_actual_wages: true,
            pf_on_actual_wages_from: form.pf_on_actual_wages_from,
            pf_on_actual_wages_reference: form.pf_on_actual_wages_reference.trim(),
          }
        : priorElection
          ? { pf_on_actual_wages: false }
          : {};

    // Fixed-term employment is sent only when it is recorded or being withdrawn (see the form state).
    const priorFixedTerm = employee?.fixed_term_employment === true;
    const fixedTermFields = form.fixed_term_employment
      ? { fixed_term_employment: true, fixed_term_end_date: form.fixed_term_end_date || undefined }
      : priorFixedTerm
        ? { fixed_term_employment: false }
        : {};

    setSaving(true);
    setErr("");
    try {
      const payload = {
        ...electionFields,
        ...fixedTermFields,
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
        eps_eligible: form.eps_eligible,
        gratuity_act_covered: form.gratuity_act_covered,
        uan: form.uan.trim() || null,
        esi_number: form.esi_number.trim() || null,
        joining_date: form.joining_date || null,
        department: form.department.trim() || null,
        bank_account_no: form.bank_account_no.trim() || null,
        bank_ifsc: form.bank_ifsc.trim().toUpperCase() || null,
        bank_name: form.bank_name.trim() || null,
        // undefined, not null: migration 333 puts a NOT-BLANK check on the
        // code, and Postgres will not read "" as a date. Both columns mean
        // "unknown" when absent.
        employee_code: form.employee_code.trim() || undefined,
        date_of_birth: form.date_of_birth || undefined,
        aadhaar_last4: aadhaarDigits ? aadhaarDigits.slice(-4) : undefined,
      };
      if (isEdit && employee) {
        // client_id can't change on edit (EmployeeUpdateIn has no client_id).
        await api.payroll.updateEmployee(employee.id, payload);
      } else {
        // The link is named only when there is one, so an ordinary create sends what it always sent.
        await api.payroll.createEmployee({ client_id: form.client_id, ...payload, ...(teamMember ? { staff_user_id: teamMember.id } : {}) });
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Failed to ${isEdit ? "update" : "add"} employee.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    // The shared dialog, not a hand-built overlay: the form is tall (identifiers, pay, statutory elections), and the overlay it used to be
    // had no height limit and no scroll, so on a laptop screen the heading, the name box and the save button were out of reach (found by
    // driving it, PRE-A-015). The shared dialog limits its height, scrolls its body, keeps the buttons in view, holds the keyboard
    // inside it and closes on Escape.
    <Modal
      title={isEdit ? "Edit Employee" : "Add Employee"}
      onClose={() => { if (!saving) (onClose)(); }}
      maxWidthClass="max-w-lg"
      footer={(
        <div className="flex gap-2 justify-end">
          <Button disabled={saving} variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : isEdit ? "Update Employee" : "Add Employee"}</Button>
        </div>
      )}
    >
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        {teamMember && !isEdit && (
          <p data-linked-team-member className="text-xs text-ps-body bg-ps-bg border border-ps-border rounded-lg px-3 py-2 mb-3">
            This employee will be linked to the team sign-in of <strong>{teamMember.name}</strong>. The two records stay separate:
            a change to one does not change the other.
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-medium text-ps-body mb-1">Client</label>
            {isEdit || clientLocked ? (
              <div className="w-full border rounded-lg px-3 py-2 text-sm bg-ps-bg text-ps-label">
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
            <label className="block text-xs font-medium text-ps-body mb-1">Name *</label>
            <input aria-label="Name" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">PAN</label>
            <input aria-label="PAN" aria-invalid={removedAt("pan") ? true : undefined} className={boxClass("pan", " uppercase")} value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value }))} maxLength={10} />
            {removedAt("pan") && <p role="alert" className="text-3xs text-state-problem mt-0.5">{removedAt("pan")}</p>}
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Designation</label>
            <input aria-label="Designation" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.designation} onChange={e => setForm(f => ({ ...f, designation: e.target.value }))} />
          </div>
          <div>
            <label htmlFor="employee-code" className="block text-xs font-medium text-ps-body mb-1">Employee Code</label>
            <input id="employee-code" className="w-full border rounded-lg px-3 py-2 text-sm"
              placeholder="e.g. EMP001"
              value={form.employee_code} onChange={e => setForm(f => ({ ...f, employee_code: e.target.value }))} />
            <p className="text-3xs text-ps-hint mt-1">
              The client&apos;s own identifier. The bulk import is idempotent on it.
            </p>
          </div>
          <div>
            <label htmlFor="date-of-birth" className="block text-xs font-medium text-ps-body mb-1">Date of Birth</label>
            <DateInput id="date-of-birth" className="w-full border rounded-lg px-3 py-2 text-sm"
              value={form.date_of_birth} onChange={v => setForm(f => ({ ...f, date_of_birth: v }))}
              onStateChange={dates.watch("dob", "Date of birth")} />
            <p className="text-3xs text-ps-hint mt-1">
              Not demographics — the old regime&apos;s nil band widens at 60 and again at 80.
            </p>
          </div>
          <div>
            <label htmlFor="aadhaar" className="block text-xs font-medium text-ps-body mb-1">Aadhaar</label>
            <input id="aadhaar" inputMode="numeric" maxLength={14} className="w-full border rounded-lg px-3 py-2 text-sm tabular-nums"
              placeholder={employee?.aadhaar_last4 ? `•••• •••• ${employee.aadhaar_last4}` : "12 digits"}
              value={form.aadhaar} onChange={e => setForm(f => ({ ...f, aadhaar: e.target.value }))} />
            <p className="text-3xs text-ps-hint mt-1">
              Only the last 4 digits are stored (UIDAI norms). Leave blank to keep what is on file.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Gender</label>
            <select aria-label="Gender" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.gender} onChange={e => setForm(f => ({ ...f, gender: e.target.value }))}>
              <option value="">Not specified</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
            <p className="text-3xs text-ps-hint mt-1">Used for Maharashtra PT — women earning ≤ ₹25,000/month are exempt.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Basic Salary (Rs/month) *</label>
            <input aria-label="Basic Salary (Rs/month)" type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.basic_rs} onChange={e => setForm(f => ({ ...f, basic_rs: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">HRA %</label>
            <input aria-label="HRA %" type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.hra_percent} onChange={e => setForm(f => ({ ...f, hra_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">DA %</label>
            <input aria-label="DA %" type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.da_percent} onChange={e => setForm(f => ({ ...f, da_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Other Allowances (Rs)</label>
            <input aria-label="Other Allowances (Rs)" type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.other_rs} onChange={e => setForm(f => ({ ...f, other_rs: e.target.value }))} />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="pf" checked={form.pf_applicable} onChange={e => setForm(f => ({ ...f, pf_applicable: e.target.checked }))} />
            {/* The base is the s.2(88) wage aggregate, not basic — see the note on
                the same label in app/payroll/page.tsx. */}
            <label htmlFor="pf" className="text-sm text-ps-body">PF Applicable (12% of PF wages)</label>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="esi" checked={form.esi_applicable} onChange={e => setForm(f => ({ ...f, esi_applicable: e.target.checked }))} />
            <label htmlFor="esi" className="text-sm text-ps-body">ESI Applicable (if &le; Rs 21,000)</label>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-ps-body mb-1">Professional Tax (state)</label>
            <select aria-label="Professional Tax (state)" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.pt_state} onChange={e => setForm(f => ({ ...f, pt_state: e.target.value }))}>
              {PT_STATES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
          </div>
          {/* The two statutory exceptions. Worded as the EXCEPTION (unticking
              is the unusual case) because both columns default true and both
              tests turn on a fact the master cannot hold: EPS on pay AT
              JOINING, gratuity coverage on the headcount when it first
              applied. */}
          <div className="col-span-2 flex items-start gap-2">
            <input type="checkbox" id="eps" className="mt-0.5"
              checked={form.eps_eligible}
              onChange={e => setForm(f => ({ ...f, eps_eligible: e.target.checked }))} />
            <label htmlFor="eps" className="text-sm text-ps-body">
              Member of the Employees&apos; Pension Scheme, 2026
              <span className="block text-2xs text-ps-hint">
                Untick only where the scheme does not reach them: wages above
                the wage ceiling on the day they joined the provident fund
                (from 01-09-2014), and still above it on 17-09-2026. A member
                whose wages on 17-09-2026 were at or below the ceiling is
                brought in by G.S.R. 847(E): tick them. When ticked, 8.33% of
                the wages up to the wage ceiling is diverted from the
                employer&apos;s contribution to the pension fund on the ECR.
              </span>
            </label>
          </div>
          {/* PF ON ACTUAL WAGES (payroll-22). Shown only where PF applies, because
              the server refuses an election beside PF off. The paragraph below
              is the SERVER'S own wording (domain/payroll/pf_wage_election
              SCREEN_NOTICE), pinned here character for character by
              tests/test_pf_on_actual_wages_is_an_election_the_employer_records.py:
              the screen says the employer, not this product, has to establish
              the joint option. */}
          {form.pf_applicable && (
            <div className="col-span-2 rounded-lg border p-3">
              <div className="flex items-start gap-2">
                <input type="checkbox" id="pf-actual" className="mt-0.5"
                  checked={form.pf_on_actual_wages}
                  onChange={e => setForm(f => ({ ...f, pf_on_actual_wages: e.target.checked }))} />
                <label htmlFor="pf-actual" className="text-sm text-ps-body">
                  Contribute PF on actual wages above the ceiling (employer election)
                  <span className="block text-2xs text-ps-hint">
                    This records a statement by the employer that the employee and the
                    employer have jointly opted in writing to contribute on wages above the
                    wage ceiling (paragraph 9(4) of the Employees&apos; Provident Funds Scheme,
                    2026). This product does not check that the option exists, whether it is
                    required here, or whether EPFO will accept it: that is for the employer
                    to establish. Pension (EPS) wages, EDLI wages and the EDLI limit stay at
                    the ceiling, and the higher-pension option under the Pension Scheme is
                    not modelled.
                  </span>
                </label>
              </div>
              {form.pf_on_actual_wages && (
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <label htmlFor="pf-actual-from" className="block text-xs font-medium text-ps-body mb-1">Takes effect from</label>
                    <DateInput id="pf-actual-from" className="w-full border rounded-lg px-3 py-2 text-sm"
                      value={form.pf_on_actual_wages_from}
                      onChange={v => setForm(f => ({ ...f, pf_on_actual_wages_from: v }))}
                      onStateChange={dates.watch("pfFrom", "PF on actual wages takes effect from")} />
                    <p className="text-3xs text-ps-hint mt-0.5">
                      Blank means every month. A month that ends before this date stays on the ceiling.
                    </p>
                  </div>
                  <div>
                    <label htmlFor="pf-actual-ref" className="block text-xs font-medium text-ps-body mb-1">Reference for the joint request</label>
                    <input id="pf-actual-ref" maxLength={200} className="w-full border rounded-lg px-3 py-2 text-sm"
                      value={form.pf_on_actual_wages_reference}
                      onChange={e => setForm(f => ({ ...f, pf_on_actual_wages_reference: e.target.value }))} />
                    <p className="text-3xs text-ps-hint mt-0.5">
                      Where the request is kept. Nothing is uploaded or checked.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="col-span-2 flex items-start gap-2">
            <input type="checkbox" id="gratuity" className="mt-0.5"
              checked={form.gratuity_act_covered}
              onChange={e => setForm(f => ({ ...f, gratuity_act_covered: e.target.checked }))} />
            <label htmlFor="gratuity" className="text-sm text-ps-body">
              Gratuity applies (Code on Social Security, 2020, section 53)
              <span className="block text-2xs text-ps-hint">
                The repealed Payment of Gratuity Act, 1972 reached an
                establishment by headcount (§1(3), and §1(3A) which kept it
                applying once it had); how the Code decides is not read here.
                It decides which limb of IT Act §10(10) exempts a leaver&apos;s
                gratuity — clause (ii) when covered, clause (iii) when not,
                and they are different formulae.
              </span>
            </label>
          </div>
          {/* FIXED-TERM EMPLOYMENT (POST-A-526). Recorded by the employer, never inferred from a short service. The server judges the date. */}
          <div className="col-span-2 flex items-start gap-2">
            <input type="checkbox" id="fixed-term" className="mt-0.5"
              checked={form.fixed_term_employment}
              onChange={e => setForm(f => ({ ...f, fixed_term_employment: e.target.checked }))} />
            <label htmlFor="fixed-term" className="text-sm text-ps-body">
              Fixed-term employment
              <span className="block text-2xs text-ps-hint">
                Where a fixed term expires, the employee is eligible for gratuity
                on at least one year of service under the contract, not five (the
                second proviso to section 53(1) of the Code on Social Security,
                2020, and rule 33(1)(a) of the Social Security (Central) Rules,
                2026), paid pro rata to the service rendered. The settlement asks
                whether the term has expired, and a contract end date that has
                been reached counts. An employee who leaves before the term ends
                is not shown as eligible on one year: the text does not settle it.
                Tick it only for an employee engaged
                on a fixed-term contract.
              </span>
            </label>
          </div>
          {form.fixed_term_employment && (
            <div className="col-span-2">
              <label htmlFor="fixed-term-end" className="block text-xs font-medium text-ps-body mb-1">Contract ends on (optional)</label>
              <DateInput id="fixed-term-end" className="w-full border rounded-lg px-3 py-2 text-sm"
                value={form.fixed_term_end_date}
                onChange={v => setForm(f => ({ ...f, fixed_term_end_date: v }))}
                anchor={form.joining_date || null} notBefore={form.joining_date || null}
                onStateChange={dates.watch("fixedTermEnd", "Contract end date")} />
            </div>
          )}

          {/* Statutory identifiers. Each hint says what is NOT POSSIBLE without
              the field, rather than "optional" — the ECR, the ESIC return and
              the s.192 projection are all finished and all refuse without
              these, and a blank whose consequence is unstated gets left blank. */}
          <div className="col-span-2 border-t pt-3 mt-1">
            <p className="text-xs font-medium text-ps-ink">Statutory identifiers</p>
            <p className="text-2xs text-ps-label">
              Blank is allowed. Each one names what cannot be produced without it.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">UAN</label>
            <input aria-label="UAN" aria-invalid={removedAt("uan") ? true : undefined} className={boxClass("uan")} value={form.uan}
                   onChange={e => setForm(f => ({ ...f, uan: e.target.value }))} maxLength={12} inputMode="numeric" />
            {removedAt("uan") && <p role="alert" className="text-3xs text-state-problem mt-0.5">{removedAt("uan")}</p>}
            <p className="text-3xs text-ps-hint mt-0.5">12 digits. Without it this member cannot go in the EPFO ECR.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">ESIC IP number</label>
            <input aria-label="ESIC IP number" aria-invalid={removedAt("esi_number") ? true : undefined} className={boxClass("esi_number")} value={form.esi_number}
                   onChange={e => setForm(f => ({ ...f, esi_number: e.target.value }))} />
            {removedAt("esi_number") && <p role="alert" className="text-3xs text-state-problem mt-0.5">{removedAt("esi_number")}</p>}
            <p className="text-3xs text-ps-hint mt-0.5">Without it this member cannot go in the ESIC return.</p>
          </div>
          <div>
            <label htmlFor="employee-joining-date" className="block text-xs font-medium text-ps-body mb-1">Joining date</label>
            <DateInput id="employee-joining-date" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.joining_date}
                   onChange={v => setForm(f => ({ ...f, joining_date: v }))}
                   onStateChange={dates.watch("joining", "Joining date")} />
            <p className="text-3xs text-ps-hint mt-0.5">
              Without it a mid-year joiner&apos;s tax is estimated over twelve months, not the months they actually work — which over-deducts.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Department</label>
            <input aria-label="Department" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.department}
                   onChange={e => setForm(f => ({ ...f, department: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Bank account number</label>
            <input aria-label="Bank account number" aria-invalid={removedAt("bank_account_no") ? true : undefined} className={boxClass("bank_account_no")} value={form.bank_account_no}
                   onChange={e => setForm(f => ({ ...f, bank_account_no: e.target.value }))} />
            {removedAt("bank_account_no") && <p role="alert" className="text-3xs text-state-problem mt-0.5">{removedAt("bank_account_no")}</p>}
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">IFSC</label>
            <input aria-label="IFSC" aria-invalid={removedAt("bank_ifsc") ? true : undefined} className={boxClass("bank_ifsc", " uppercase")} value={form.bank_ifsc}
                   onChange={e => setForm(f => ({ ...f, bank_ifsc: e.target.value }))} maxLength={11} />
            {removedAt("bank_ifsc") && <p role="alert" className="text-3xs text-state-problem mt-0.5">{removedAt("bank_ifsc")}</p>}
            <p className="text-3xs text-ps-hint mt-0.5">The account and IFSC are what a salary payment file is built from.</p>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-ps-body mb-1">Bank name</label>
            <input aria-label="Bank name" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.bank_name}
                   onChange={e => setForm(f => ({ ...f, bank_name: e.target.value }))} />
          </div>
        </div>
    </Modal>
  );
}

// ── Payslip Modal ─────────────────────────────────────────────────────────

