"use client";
/**
 * Bank — three tabs, one working screen.
 *
 *   Entries    the work. Every statement line becomes a Receipt, Payment or
 *              Contra, is proposed for by the machine, and is PASSED by the
 *              CA. Importing a statement and managing the bank accounts are
 *              reached from here too — they are setup, not a step.
 *   Reconcile  the BRS — statement against books, signed off per period
 *   Rules      what the machine proposes, and what it may pass on its own
 *
 * Rebuilt 2026-09-03 around ENTRIES — docs/architecture/09-bank-entries.md —
 * as five tabs, and collapsed to three the same day after first use: Accounts
 * was setup wearing a tab, and Bank Book was a report (it now lives under
 * Reports › Bank Book). This file is the shell only; each tab is its own file
 * under components/banking/. The chart of accounts is loaded once here because
 * Entries and Rules both read it.
 */
import { useCallback, useEffect, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import type { Account } from "@/components/banking/shared";
import { EntriesTab } from "@/components/banking/EntriesTab";
import { BankReconciliation } from "@/components/banking/ReconcileTab";
import { RulesTab } from "@/components/banking/RulesTab";

type BankTab = "entries" | "reconcile" | "rules";

const TABS: { id: BankTab; label: string; title: string }[] = [
  { id: "entries",   label: "Entries",   title: "Turn statement lines into entries and pass them" },
  { id: "reconcile", label: "Reconcile", title: "Bank Reconciliation Statement" },
  { id: "rules",     label: "Rules",     title: "What the machine proposes, and what it may pass on its own" },
];

export default function BankPage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<BankTab>("entries");
  const [accounts, setAccounts] = useState<Account[]>([]);

  const loadAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { data, error } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
        // firm_id explicitly, not RLS alone (CLAUDE.md: the app-layer filter is
        // the primary isolation control; the policy is defence in depth).
        .eq("firm_id", firmId)
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .order("account_code")
        .order("id"));
      if (error) throw error;
      setAccounts((data as Account[]) ?? []);
    } catch {
      // A failed load leaves the pickers empty; each tab shows its own state.
      setAccounts([]);
    }
  }, [clientId]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit" role="tablist" aria-label="Bank">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} title={t.title}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "entries"   && <EntriesTab clientId={clientId} accounts={accounts} />}
        {tab === "reconcile" && <BankReconciliation clientId={clientId} />}
        {tab === "rules"     && <RulesTab clientId={clientId} accounts={accounts} />}
      </div>
    </div>
  );
}
