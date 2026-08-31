"use client";

/**
 * The employee's own §192 declaration — Form 12BB (Rule 26C).
 *
 * WHAT THIS FORM IS
 *   Rule 26C requires "the assessee" to furnish particulars of the claims they
 *   make against salary, in Form 12BB, to "the person responsible for paying".
 *   The employee makes the claim; the employer checks the proofs and withholds
 *   accordingly. So this is the employee's statement, filed by the employee.
 *
 * WHAT IT DOES NOT DO
 *   It computes no tax and applies no statutory rule. Which reliefs a regime
 *   allows, the Chapter VI-A caps, the §10(13A) formula, the Rule 26C PAN
 *   thresholds — all of that lives in apps/api
 *   (domain/payroll/declarations.py) and is reported back to the CA on the
 *   verification screen. Duplicating any of it here would drift, and the drift
 *   would be invisible because both numbers look reasonable.
 *
 *   The one thing this form asserts is the SHAPE of Form 12BB: rent asks for a
 *   landlord, a home loan asks for a lender. Those are boxes on the prescribed
 *   form, not computations.
 *
 * WRITES
 *   Straight to Supabase, under the policies migration 297 added — the same
 *   identity model the portal already uses to READ payslips and leave. An
 *   employee reaches their own declaration and no other's, may declare an
 *   amount but never verify it, and cannot touch it once the CA has been
 *   through the proofs.
 *
 * All monetary values are integer paise in the database.
 */

import { useState, useEffect, useCallback } from "react";
import { Loader2, Lock, Save } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

type Regime = "new" | "old";

type Item = {
  id?: string;
  section: string;
  label: string;
  amount_declared_paise: number;
  amount_verified_paise: number;
  status: string;
};

type Declaration = {
  id?: string;
  firm_id: string;
  client_id: string;
  employee_id: string;
  fy: string;
  regime: Regime;
  status: string;
  rent_paid_declared_paise: number;
  landlord_name: string;
  landlord_address: string;
  landlord_pan: string;
  rent_is_metro: boolean;
  lta_declared_paise: number;
  home_loan_interest_declared_paise: number;
  lender_name: string;
  lender_pan: string;
  other_income_declared_paise: number;
  house_property_loss_declared_paise: number;
  proofs_verified: boolean;
};

/** The Chapter VI-A heads payroll can give effect to. Anything else is claimed
 *  in the return instead — the backend refuses a section it does not compute,
 *  rather than granting a deduction under one nobody checked. */
const SECTIONS: ReadonlyArray<{ code: string; label: string; hint: string }> = [
  { code: "80C", label: "§80C", hint: "PPF, ELSS, LIC, home-loan principal, tuition fees, 5-year FD" },
  { code: "80CCD(1B)", label: "§80CCD(1B)", hint: "Additional NPS, over and above §80C" },
  { code: "80CCD(2)", label: "§80CCD(2)", hint: "Your employer's NPS contribution" },
  { code: "80D-self", label: "§80D — self and family", hint: "Health insurance premium" },
  { code: "80D-parents", label: "§80D — parents", hint: "Health insurance premium for parents" },
  { code: "80TTA", label: "§80TTA", hint: "Interest on a savings account (report the interest below too)" },
];

function currentFy(): string {
  const now = new Date();
  const start = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

function paiseToRupees(paise: number): string {
  return paise ? String(Math.floor(paise / 100)) : "";
}

/** Rupees typed into a box -> integer paise, without floating-point
 *  multiplication (0.1 * 100 is 10.000000000000002). */
function rupeesToPaise(text: string): number {
  const cleaned = (text ?? "").replace(/[^\d.]/g, "");
  if (!cleaned) return 0;
  const [whole, frac = ""] = cleaned.split(".");
  return Number(whole || "0") * 100 + Number((frac + "00").slice(0, 2));
}

export function TaxDeclarationTab({ employeeId, onToast }: {
  employeeId: string;
  onToast: (message: string) => void;
}) {
  const fy = currentFy();
  const [decl, setDecl] = useState<Declaration | null>(null);
  const [items, setItems] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const sb = getSupabaseClient();
      const { data: emp, error: empErr } = await sb
        .from("payroll_employees")
        .select("id, firm_id, client_id")
        .eq("id", employeeId)
        .maybeSingle();
      if (empErr) throw empErr;

      const { data: existing, error } = await sb
        .from("payroll_it_declarations")
        .select("*")
        .eq("employee_id", employeeId)
        .eq("fy", fy)
        .maybeSingle();
      if (error) throw error;

      if (existing) {
        setDecl(existing as Declaration);
        const { data: rows } = await sb
          .from("payroll_it_declaration_items")
          .select("*")
          .eq("declaration_id", existing.id);
        const seed: Record<string, string> = {};
        for (const r of ((rows ?? []) as Item[])) {
          seed[r.section] = paiseToRupees(r.amount_declared_paise);
        }
        setItems(seed);
      } else {
        setDecl({
          firm_id: emp?.firm_id ?? "",
          client_id: emp?.client_id ?? "",
          employee_id: employeeId,
          fy,
          // §115BAC(1A) is the default regime, so an employee who has not
          // chosen sees the position they are already being withheld on.
          regime: "new",
          status: "draft",
          rent_paid_declared_paise: 0,
          landlord_name: "", landlord_address: "", landlord_pan: "",
          rent_is_metro: false,
          lta_declared_paise: 0,
          home_loan_interest_declared_paise: 0,
          lender_name: "", lender_pan: "",
          other_income_declared_paise: 0,
          house_property_loss_declared_paise: 0,
          proofs_verified: false,
        });
        setItems({});
      }
    } catch (e) {
      console.error("load declaration:", e);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [employeeId, fy]);

  useEffect(() => { void load(); }, [load]);

  const set = <K extends keyof Declaration>(key: K, value: Declaration[K]) =>
    setDecl((d) => (d ? { ...d, [key]: value } : d));

  const save = async () => {
    if (!decl) return;
    setSaving(true);
    try {
      const sb = getSupabaseClient();
      const payload = { ...decl, status: "submitted" };
      delete (payload as { id?: string }).id;
      const { data: saved, error } = await sb
        .from("payroll_it_declarations")
        .upsert(payload, { onConflict: "employee_id,fy" })
        .select("id")
        .single();
      if (error) throw error;

      // Replaced wholesale, not merged: a declaration states the whole year's
      // intent, and merging would leave a withdrawn investment in place.
      await sb.from("payroll_it_declaration_items")
        .delete().eq("declaration_id", saved.id);
      const lines = SECTIONS
        .map((s) => ({ section: s.code, paise: rupeesToPaise(items[s.code] ?? "") }))
        .filter((l) => l.paise > 0)
        .map((l) => ({
          firm_id: decl.firm_id,
          declaration_id: saved.id,
          section: l.section,
          label: "",
          amount_declared_paise: l.paise,
          amount_verified_paise: 0,
          status: "declared",
        }));
      if (lines.length) {
        const { error: itemErr } = await sb
          .from("payroll_it_declaration_items").insert(lines);
        if (itemErr) throw itemErr;
      }
      onToast("Declaration submitted. Your firm will verify the proofs.");
      await load();
    } catch (e) {
      console.error("save declaration:", e);
      onToast("Could not save your declaration. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[#64748B] py-10 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading your declaration…
      </div>
    );
  }
  if (loadFailed || !decl) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-8 text-center text-sm text-[#B91C1C]">
        Could not load your declaration.
        <button onClick={() => void load()} className="underline ml-1">Try again</button>.
      </div>
    );
  }

  const locked = decl.proofs_verified;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-[#0F172A]">
            Tax declaration — {fy}
          </h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            Form 12BB. What you tell your employer here decides how much tax is
            deducted from your salary each month.
          </p>
        </div>

        {locked && (
          <div className="mx-5 mt-4 flex gap-2.5 text-xs bg-[#F0FDF4] border border-[#BBF7D0] rounded-lg p-3">
            <Lock className="w-3.5 h-3.5 text-[#047857] shrink-0 mt-0.5" />
            <p className="text-[#065F46]">
              Your proofs have been verified, so this is now read-only. Ask your
              payroll contact if something needs to change.
            </p>
          </div>
        )}

        <div className="px-5 py-4 space-y-5">
          {/* Regime */}
          <fieldset disabled={locked}>
            <legend className="text-xs font-medium text-[#334155] mb-2">
              Which tax regime should your employer use?
            </legend>
            <div className="space-y-2">
              {([
                { v: "new" as const, t: "New regime (default)",
                  d: "Lower slab rates. No HRA, no leave-travel exemption, and no §80C, §80D or §24(b) relief." },
                { v: "old" as const, t: "Old regime",
                  d: "Higher slab rates, but your investments, rent and home-loan interest reduce your tax." },
              ]).map((o) => (
                <label key={o.v}
                  className={`flex gap-2.5 items-start border rounded-lg p-3 cursor-pointer ${
                    decl.regime === o.v ? "border-[#2563EB] bg-[#EFF6FF]" : "border-[#E2E8F0]"}`}>
                  <input type="radio" name="regime" className="mt-1"
                    checked={decl.regime === o.v}
                    onChange={() => set("regime", o.v)} />
                  <span>
                    <span className="text-sm text-[#0F172A]">{o.t}</span>
                    <span className="block text-xs text-[#64748B] mt-0.5">{o.d}</span>
                  </span>
                </label>
              ))}
            </div>
            {decl.regime === "old" && (
              <p className="text-xs text-[#78350F] bg-[#FFFBEB] border border-[#FDE68A] rounded-lg p-3 mt-2">
                Telling your employer you want the old regime changes how tax is
                deducted from your salary. It is not the same as choosing the old
                regime in your tax return — if you have business or professional
                income you must also file Form 10-IEA by the due date, or your
                return is assessed on the new regime whatever this says.
              </p>
            )}
          </fieldset>

          {/* House rent — §10(13A) */}
          <Section title="House rent" note="Form 12BB asks for your landlord's details alongside the rent.">
            <Money label="Rent paid in the year" disabled={locked}
              value={paiseToRupees(decl.rent_paid_declared_paise)}
              onChange={(v) => set("rent_paid_declared_paise", rupeesToPaise(v))} />
            <Text label="Landlord's name" disabled={locked}
              value={decl.landlord_name}
              onChange={(v) => set("landlord_name", v)} />
            <Text label="Landlord's address" disabled={locked}
              value={decl.landlord_address}
              onChange={(v) => set("landlord_address", v)} />
            <Text label="Landlord's PAN" disabled={locked}
              hint="Form 12BB requires this once the year's rent passes ₹1,00,000 (Rule 26C)."
              value={decl.landlord_pan}
              onChange={(v) => set("landlord_pan", v.toUpperCase())} />
            <label className="flex items-center gap-2 text-sm text-[#334155]">
              <input type="checkbox" checked={decl.rent_is_metro} disabled={locked}
                onChange={(e) => set("rent_is_metro", e.target.checked)} />
              I live in Delhi, Mumbai, Kolkata or Chennai
            </label>
          </Section>

          {/* LTA — §10(5) */}
          <Section title="Leave travel">
            <Money label="Leave travel claimed" disabled={locked}
              value={paiseToRupees(decl.lta_declared_paise)}
              onChange={(v) => set("lta_declared_paise", rupeesToPaise(v))} />
          </Section>

          {/* §24(b) */}
          <Section title="Home loan interest"
                   note="Form 12BB asks for the lender's details alongside the interest.">
            <Money label="Interest paid in the year" disabled={locked}
              value={paiseToRupees(decl.home_loan_interest_declared_paise)}
              onChange={(v) => set("home_loan_interest_declared_paise", rupeesToPaise(v))} />
            <Text label="Lender's name" disabled={locked}
              value={decl.lender_name} onChange={(v) => set("lender_name", v)} />
            <Text label="Lender's PAN" disabled={locked}
              value={decl.lender_pan} onChange={(v) => set("lender_pan", v.toUpperCase())} />
          </Section>

          {/* Chapter VI-A */}
          <Section title="Investments and deductions">
            {SECTIONS.map((s) => (
              <Money key={s.code} label={s.label} hint={s.hint} disabled={locked}
                value={items[s.code] ?? ""}
                onChange={(v) => setItems((prev) => ({ ...prev, [s.code]: v }))} />
            ))}
          </Section>

          {/* §192(2B) */}
          <Section title="Other income"
                   note="Telling your employer about other income means tax on it is deducted from your salary, instead of you paying it later.">
            <Money label="Other income (interest, and so on)" disabled={locked}
              value={paiseToRupees(decl.other_income_declared_paise)}
              onChange={(v) => set("other_income_declared_paise", rupeesToPaise(v))} />
            <Money label="Loss from house property" disabled={locked}
              hint="Enter this as a positive number."
              value={paiseToRupees(decl.house_property_loss_declared_paise)}
              onChange={(v) => set("house_property_loss_declared_paise", rupeesToPaise(v))} />
          </Section>

          {!locked && (
            <div className="flex justify-end pt-1">
              <button onClick={() => void save()} disabled={saving}
                className="inline-flex items-center gap-2 bg-[#0F172A] text-white text-sm px-4 py-2 rounded-lg disabled:opacity-60">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                Submit declaration
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Small field primitives ─────────────────────────────────────────────────

function Section({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <div className="border-t border-[#F1F5F9] pt-4 space-y-3">
      <div>
        <h3 className="text-sm font-medium text-[#0F172A]">{title}</h3>
        {note && <p className="text-xs text-[#94A3B8] mt-0.5">{note}</p>}
      </div>
      {children}
    </div>
  );
}

function Money({ label, hint, value, onChange, disabled }: {
  label: string; hint?: string; value: string;
  onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-sm text-[#334155]">{label}</span>
      {hint && <span className="block text-xs text-[#94A3B8]">{hint}</span>}
      <div className="mt-1 flex items-center border border-[#E2E8F0] rounded-lg overflow-hidden
                      focus-within:border-[#2563EB]">
        <span className="px-2.5 text-sm text-[#94A3B8] bg-[#F8FAFC] py-2">₹</span>
        <input inputMode="decimal" value={value} disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 px-3 py-2 text-sm text-right tabular-nums outline-none disabled:bg-[#F8FAFC]" />
      </div>
    </label>
  );
}

function Text({ label, hint, value, onChange, disabled }: {
  label: string; hint?: string; value: string;
  onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-sm text-[#334155]">{label}</span>
      {hint && <span className="block text-xs text-[#94A3B8]">{hint}</span>}
      <input value={value} disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm
                   outline-none focus:border-[#2563EB] disabled:bg-[#F8FAFC]" />
    </label>
  );
}
