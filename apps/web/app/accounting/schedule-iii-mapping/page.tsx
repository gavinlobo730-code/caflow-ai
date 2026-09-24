"use client";

/**
 * Schedule III Mapping — where a CA says which line of the statutory financial
 * statements an account presents on.
 *
 * TWO THINGS WERE WRONG HERE UNTIL 11-09-2026, and they compounded.
 *
 * 1. THE MENU WAS HARDCODED, and had drifted from the engine in both
 *    directions. It offered five captions the classifier had never heard of —
 *    Capital Work in Progress, Goodwill & Intangibles, Long-term and Short-term
 *    Provisions, Deferred Tax Asset — so a CA could pick one and the statement
 *    would ignore it. And it SPELLED five others differently ("Employee
 *    Benefits Expense" here, "Employee Benefit Expense" in the engine), which
 *    is how nine of the fifty mapped accounts in production ended up silently
 *    discarded. The list now comes from the module that does the classifying,
 *    so there is no second copy to drift.
 *
 * 2. THE SCREEN WAS READ-ONLY. The only way to set a mapping was to re-import
 *    the whole chart of accounts, and the page said so in an amber box. A
 *    screen named after a decision that cannot be made on it is a report.
 *
 * Reads go direct over PostgREST (RLS), which is the house pattern. WRITES go
 * through the API so rbac() runs and the caption is validated against the same
 * vocabulary the statements use.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, GitBranch } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { Callout } from "@/components/ui/callout";

interface CoaRow {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  tax_category: string | null;
  schedule_iii_mapping: string | null;
  is_active: boolean;
}

interface CaptionSection {
  heading: string;
  items: string[];
}

interface CaptionsResponse {
  success: boolean;
  error?: string | null;
  data?: { sections: CaptionSection[]; residual: string[] };
}

const UNMAPPED = "__unmapped__";


export default function ScheduleIIIMappingPage() {
  const [accounts, setAccounts] = useState<CoaRow[]>([]);
  const [sections, setSections] = useState<CaptionSection[]>([]);
  const [residual, setResidual] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const fid = await getFirmId();
        const sb = getSupabaseClient();
        const [coa, caps] = await Promise.all([
          sb.from("chart_of_accounts")
            .select("id, account_code, account_name, account_type, tax_category, schedule_iii_mapping, is_active")
            .eq("firm_id", fid)
            .is("client_id", null)
            .order("account_code"),
          api.accounting.scheduleIiiCaptions() as Promise<CaptionsResponse>,
        ]);
        if (coa.error) throw new Error(coa.error.message);
        if (!caps.success) throw new Error(caps.error ?? "Could not load the Schedule III captions");
        setAccounts((coa.data ?? []) as CoaRow[]);
        setSections(caps.data?.sections ?? []);
        setResidual(caps.data?.residual ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const allCaptions = sections.flatMap(s => s.items);

  const setMapping = useCallback(async (acc: CoaRow, next: string) => {
    const value = next === UNMAPPED ? "" : next;
    const previous = acc.schedule_iii_mapping;
    setSaving(acc.id);
    setSaveError(null);
    // Optimistic, then reverted on refusal. The alternative — waiting on a
    // Singapore round trip per select — makes mapping fifty accounts feel broken.
    setAccounts(rows => rows.map(r => (r.id === acc.id ? { ...r, schedule_iii_mapping: value || null } : r)));
    try {
      const res = (await api.accounting.updateAccount(
        acc.id, { schedule_iii_mapping: value })) as
        { success: boolean; error?: string | null; detail?: string };
      // The router answers a refusal as HTTP 200 with {success:false}. An
      // unchecked call would show the CA a mapping the server declined —
      // exactly the bug the GST filing path had.
      if (!res.success) throw new Error(res.detail ?? res.error ?? "The server declined the change");
    } catch (e) {
      setAccounts(rows => rows.map(r => (r.id === acc.id ? { ...r, schedule_iii_mapping: previous } : r)));
      setSaveError(`${acc.account_name}: ${e instanceof Error ? e.message : "could not save"}`);
    } finally {
      setSaving(null);
    }
  }, []);

  const active = accounts.filter(a => a.is_active);
  const unmapped = active.filter(a => !a.schedule_iii_mapping);
  // An account whose stored mapping is not a caption the engine serves. It is
  // NOT the same as unmapped: somebody decided, and the decision is not being
  // honoured — which is worth saying out loud rather than showing as a blank.
  const unrecognised = active.filter(
    a => a.schedule_iii_mapping && !allCaptions.includes(a.schedule_iii_mapping));

  if (loading) return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
    </div>
  );
  if (error) return <div className="p-6"><div className="bg-state-problem-surface text-state-problem rounded-lg px-5 py-4 text-sm">{error}</div></div>;

  const picker = (acc: CoaRow) => (
    <select
      value={acc.schedule_iii_mapping && allCaptions.includes(acc.schedule_iii_mapping)
        ? acc.schedule_iii_mapping : UNMAPPED}
      disabled={saving === acc.id}
      onChange={e => setMapping(acc, e.target.value)}
      className="text-2xs border border-ps-border rounded-md px-2 py-1 bg-white max-w-[210px] disabled:opacity-50"
    >
      <option value={UNMAPPED}>— not mapped —</option>
      {sections.map(s => (
        <optgroup key={s.heading} label={s.heading}>
          {s.items.map(c => <option key={c} value={c}>{c}</option>)}
        </optgroup>
      ))}
    </select>
  );

  const row = (acc: CoaRow) => (
    <tr key={acc.id} className="hover:bg-ps-bg">
      <td className="px-4 py-2 font-mono text-3xs text-ps-hint w-16">{acc.account_code}</td>
      <td className="px-3 py-2 font-medium text-ps-ink">{acc.account_name}</td>
      <td className="px-3 py-2 text-ps-label">{acc.account_type}</td>
      <td className="px-3 py-2 text-ps-label">{acc.tax_category ?? "—"}</td>
      <td className="px-4 py-2 text-right">{picker(acc)}</td>
    </tr>
  );

  const group = (heading: string, rows: CoaRow[], note?: string) => (
    <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
      <div className="px-4 py-2.5 border-b border-ps-bg flex items-center justify-between">
        <span className="text-xs font-semibold text-ps-body">{heading}</span>
        <span className="text-3xs text-ps-hint">{rows.length} account{rows.length !== 1 ? "s" : ""}</span>
      </div>
      {note && <div className="px-4 py-1.5 text-3xs text-ps-hint border-b border-ps-bg">{note}</div>}
      {rows.length === 0 ? (
        <div className="px-4 py-2 text-3xs text-ps-hint italic">No accounts mapped</div>
      ) : (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-ps-bg">{rows.map(row)}</tbody>
        </table>
      )}
    </div>
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink flex items-center gap-2">
            <GitBranch size={18} className="text-blue-600" /> Schedule III Mapping
          </h1>
          <p className="text-xs text-ps-label mt-0.5">
            {active.length - unmapped.length} of {active.length} active accounts mapped
            {" · "}a mapping here decides where the balance presents on the statutory statements
          </p>
        </div>
        <Link href="/accounting/account-groups" className="text-xs text-blue-600 hover:underline">
          View accounts →
        </Link>
      </div>

      {saveError && <Callout tone="problem">{saveError}</Callout>}

      {unrecognised.length > 0 && (
        <div className="bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
          <p className="text-xs font-medium text-amber-800">
            {unrecognised.length} account{unrecognised.length !== 1 ? "s carry" : " carries"} a
            mapping this version does not present
          </p>
          <p className="text-xs text-state-attention mt-0.5">
            The choice is recorded but the statements fall back to the account&apos;s subtype.
            Re-pick below to make it count: {unrecognised.map(a => a.schedule_iii_mapping).filter((v, i, s) => s.indexOf(v) === i).join(", ")}
          </p>
        </div>
      )}

      <div className="space-y-3">
        {unmapped.length > 0 && group(
          "Not mapped",
          unmapped,
          "These present wherever the account's subtype happens to land them — which is a default, not a decision.")}

        {sections.map(({ heading, items }) => (
          <div key={heading} className="space-y-2">
            <h2 className="text-xs font-semibold text-ps-label uppercase tracking-wider mb-1 mt-4">{heading}</h2>
            {items.map(caption => group(
              caption,
              active.filter(a => a.schedule_iii_mapping === caption),
              residual.includes(caption)
                ? "A residual line — Schedule III's \"Other\" bucket. Right for what genuinely belongs there, and a place balances land by default."
                : undefined))}
          </div>
        ))}
      </div>
    </div>
  );
}
