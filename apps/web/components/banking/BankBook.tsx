"use client";
// Bank Book — the register: the bank ledger with a running balance
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md),
// and the same day out of the Bank module's tabs altogether: it is a report,
// and it is rendered by app/clients/[id]/reports/bank-book/page.tsx. The Bank
// screen links to it. Behaviour here is unchanged by either move.

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Download, Landmark } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";
import { fmt, BankAccount } from "@/components/banking/shared";

// ── Bank register (Tier 1.1) ───────────────────────────────────────────────
// The ledger view of one account. READ-ONLY by design: posted journals are
// immutable in this system, so an edit box here would promise something the
// ledger refuses — corrections are reversals, made in the journal.
//
// Every figure below comes from the server (CLAUDE.md: no business logic in the
// frontend). This component sorts nothing and sums nothing; `balance_paise` on
// each line is the running balance as computed in date order, which is the only
// order in which a running balance means anything.

interface RegisterLine {
  transaction_id: string;
  transaction_date: string | null;
  description: string;
  reference_no: string | null;
  debit_paise: number;
  credit_paise: number;
  amount_paise: number;
  balance_paise: number;
  cleared: "" | "C" | "R";
  category: string | null;
  match_status: string | null;
  posted_journal_id: string | null;
  statement_balance_paise: number | null;
  balance_delta_paise: number | null;
  precedes_opening: boolean;
}
interface RegisterDivergence {
  index: number; transaction_id: string; transaction_date: string | null;
  description: string; computed_balance_paise: number;
  statement_balance_paise: number | null; delta_paise: number;
}
interface RegisterSummary {
  opening_balance_paise: number; deposits_paise: number; withdrawals_paise: number;
  closing_balance_paise: number; line_count: number; uncleared_count: number;
  pending_count: number; reconciled_count: number; unposted_count: number;
  precedes_opening_count: number;
}
interface RegisterPayload {
  account: {
    id: string; bank_name: string; account_no: string; account_type: string;
    currency: string; opening_balance_paise: number; opening_balance_date: string | null;
  } | null;
  lines: RegisterLine[];
  summary: RegisterSummary;
  divergence: RegisterDivergence | null;
  view_opening_balance_paise: number;
  filtered_count: number;
  total_count: number;
  limit: number;
  offset: number;
}

type RegisterStatus = "all" | "uncleared" | "pending" | "reconciled" | "unposted" | "needs_review";
type RegisterSort = "date" | "amount" | "description" | "balance" | "cleared";

const REGISTER_STATUSES: { id: RegisterStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "uncleared", label: "Uncleared" },
  { id: "pending", label: "Cleared (C)" },
  { id: "reconciled", label: "Reconciled (R)" },
  { id: "unposted", label: "Not posted" },
  { id: "needs_review", label: "Needs review" },
];

const PAGE_SIZE = 100;

export function BankRegister({ clientId }: { clientId: string }) {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [bankAccountId, setBankAccountId] = useState("");
  const [data, setData] = useState<RegisterPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [status, setStatus] = useState<RegisterStatus>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<RegisterSort>("date");
  const [desc, setDesc] = useState(false);
  const [page, setPage] = useState(0);

  // Load the client's bank accounts, then default to the first active one.
  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    (async () => {
      try {
        const supabase = getSupabaseClient();
        const { data: rows } = await selectAll(() => supabase
          .from("bank_accounts")
          .select("id, bank_name, account_no, ifsc, account_type, opening_balance_paise, opening_balance_date, coa_account_id, currency, is_active")
          .eq("client_id", clientId)
          .order("bank_name")
          .order("id"));
        const list = ((rows as BankAccount[]) ?? []).filter((a) => a.is_active);
        setAccounts(list);
        setBankAccountId((prev) => prev || (list[0]?.id ?? ""));
      } catch {
        setAccounts([]);
      }
    })();
  }, [clientId]);

  const load = useCallback(async () => {
    if (!bankAccountId) { setData(null); return; }
    setLoading(true); setLoadError(null);
    try {
      const res = (await api.banking.register({
        bank_account_id: bankAccountId,
        client_id: clientId,
        ...(dateFrom ? { date_from: dateFrom } : {}),
        ...(dateTo ? { date_to: dateTo } : {}),
        ...(status !== "all" ? { status } : {}),
        ...(search.trim() ? { q: search.trim() } : {}),
        sort,
        desc: String(desc),
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      })) as { success: boolean; data: RegisterPayload; error: string | null };
      if (!res.success) throw new Error(res.error ?? "Couldn't load the register.");
      setData(res.data);
    } catch (e) {
      setData(null);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the register.");
    } finally {
      setLoading(false);
    }
  }, [bankAccountId, clientId, dateFrom, dateTo, status, search, sort, desc, page]);
  useEffect(() => { load(); }, [load]);

  // Changing what is being looked at returns to the first page; changing the
  // page must not.
  useEffect(() => { setPage(0); }, [bankAccountId, dateFrom, dateTo, status, search, sort, desc]);

  function toggleSort(col: RegisterSort) {
    if (sort === col) setDesc((d) => !d);
    else { setSort(col); setDesc(col === "date" ? false : true); }
  }

  function exportCsv() {
    if (!data) return;
    const rows = [
      ["Date", "Description", "Reference", "Category", "Withdrawal", "Deposit", "Balance", "Cleared", "Posted"],
      ...data.lines.map((l) => [
        l.transaction_date ?? "", l.description, l.reference_no ?? "", l.category ?? "",
        l.debit_paise ? (l.debit_paise / 100).toFixed(2) : "",
        l.credit_paise ? (l.credit_paise / 100).toFixed(2) : "",
        (l.balance_paise / 100).toFixed(2),
        l.cleared || "", l.posted_journal_id ? "Yes" : "No",
      ]),
    ];
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    // Leading BOM so Excel reads the ₹ and Indian names as UTF-8.
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `register-${data.account?.account_no ?? "account"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const filtersActive = !!(dateFrom || dateTo || status !== "all" || search.trim());
  const summary = data?.summary;
  const totalPages = data ? Math.max(1, Math.ceil(data.filtered_count / PAGE_SIZE)) : 1;

  // A plain function, not a component: declaring a component inside the render
  // gives it a new identity every keystroke, so React remounts these headers and
  // the search box loses focus mid-typing.
  //
  // The alignment classes are spelled out rather than built as `text-${align}` —
  // Tailwind scans source text, so an interpolated class name only survives by
  // accident (because some other line in this file happens to use it).
  const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
  const sortHead = (col: RegisterSort, label: string, align: keyof typeof ALIGN = "left") => (
    <th key={col} className={`px-3 py-2 font-medium ${ALIGN[align]} whitespace-nowrap`}>
      <button onClick={() => toggleSort(col)} className="inline-flex items-center gap-1 hover:text-[#334155]">
        {label}{sort === col && <span className="text-[9px]">{desc ? "▼" : "▲"}</span>}
      </button>
    </th>
  );

  if (accounts.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center max-w-3xl mx-auto">
        <Landmark size={24} className="mx-auto text-[#CBD5E1]" />
        <p className="text-sm text-[#94A3B8] mt-2">No bank account yet.</p>
        <p className="text-[11px] text-[#94A3B8] mt-1">
          Add one from <strong>Bank › Entries › Accounts</strong>, then import a statement —
          the register builds itself from what the bank sent.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Account + filters */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-3 flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">Account</span>
          <select value={bankAccountId} onChange={(e) => setBankAccountId(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs">
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.bank_name} · ****{a.account_no.slice(-4)}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">From</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">To</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">Show</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as RegisterStatus)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs">
            {REGISTER_STATUSES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <label className="block flex-1 min-w-[160px]">
          <span className="text-[10px] font-medium text-[#64748B]">Search</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Narration, reference or category"
            className="mt-1 block w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <div className="flex items-center gap-2">
          {filtersActive && (
            <button onClick={() => { setDateFrom(""); setDateTo(""); setStatus("all"); setSearch(""); }}
              className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
              Clear
            </button>
          )}
          <button onClick={load} disabled={loading}
            className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] inline-flex items-center gap-1">
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
          <button onClick={exportCsv} disabled={!data || data.lines.length === 0}
            className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] inline-flex items-center gap-1 disabled:opacity-40">
            <Download size={11} /> CSV
          </button>
        </div>
      </div>

      {/* The self-check the bank makes possible: our running balance against the
          balance column the statement itself carried. */}
      {data?.divergence && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <p className="text-xs font-semibold text-amber-900">
            This register stops agreeing with the statement on {data.divergence.transaction_date}
          </p>
          <p className="text-[11px] text-amber-800 mt-1">
            After “{data.divergence.description}” the bank says the balance was{" "}
            <span className="font-mono">{fmt(data.divergence.statement_balance_paise ?? 0)}</span>;
            from the imported lines it works out to{" "}
            <span className="font-mono">{fmt(data.divergence.computed_balance_paise)}</span> — a
            difference of <span className="font-mono font-semibold">{fmt(Math.abs(data.divergence.delta_paise))}</span>.
          </p>
          <p className="text-[11px] text-amber-700 mt-1">
            Usually a missing, duplicated or misdated line, or an opening balance that needs
            correcting under Bank › Entries › Accounts. Only the first mismatch is shown — every balance after
            it inherits the same difference.
          </p>
        </div>
      )}

      {summary && summary.precedes_opening_count > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-2.5">
          <p className="text-[11px] text-blue-800">
            {summary.precedes_opening_count} transaction{summary.precedes_opening_count === 1 ? " is" : "s are"} dated
            before this account&apos;s opening balance
            {data?.account?.opening_balance_date ? ` (${data.account.opening_balance_date})` : ""} and{" "}
            {summary.precedes_opening_count === 1 ? "is" : "are"} shown but not added to the running
            balance — the opening figure already includes {summary.precedes_opening_count === 1 ? "it" : "them"}.
          </p>
        </div>
      )}

      {/* Totals for the WHOLE account, not the filtered page. */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Opening balance", value: fmt(summary.opening_balance_paise), tone: "text-[#0F172A]" },
            { label: "Deposits", value: fmt(summary.deposits_paise), tone: "text-green-700" },
            { label: "Withdrawals", value: fmt(summary.withdrawals_paise), tone: "text-red-700" },
            { label: "Closing balance", value: fmt(summary.closing_balance_paise), tone: "text-[#0F172A] font-semibold" },
          ].map((c) => (
            <div key={c.label} className="bg-white rounded-xl border border-[#F1F5F9] px-4 py-3">
              <p className="text-[10px] text-[#94A3B8] uppercase tracking-wide">{c.label}</p>
              <p className={`text-sm font-mono mt-0.5 ${c.tone}`}>{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? <TableSkeleton cols={6} rows={8} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : !data || data.lines.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center">
          <p className="text-sm text-[#94A3B8]">
            {filtersActive ? "Nothing matches these filters." : "No transactions on this account yet."}
          </p>
          {!filtersActive && (
            <p className="text-[11px] text-[#94A3B8] mt-1">Import a statement from <strong>Bank › Entries</strong>.</p>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B] border-b border-[#F1F5F9]">
                <tr>
                  {sortHead("date", "Date")}
                  {sortHead("description", "Description")}
                  <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Category</th>
                  {sortHead("cleared", "✓", "center")}
                  {sortHead("amount", "Withdrawal", "right")}
                  <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Deposit</th>
                  {sortHead("balance", "Balance", "right")}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {/* The balance immediately before the first row shown. Without it
                    a filtered register does not visibly add up. */}
                {page === 0 && (
                  <tr className="bg-[#FCFCFD] text-[#64748B]">
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      {filtersActive || sort !== "date" || desc ? "Balance before this view" : "Opening balance"}
                    </td>
                    <td className="px-3 py-1.5" colSpan={5} />
                    <td className="px-3 py-1.5 text-right font-mono">{fmt(data.view_opening_balance_paise)}</td>
                  </tr>
                )}
                {data.lines.map((l) => (
                  <tr key={l.transaction_id}
                      className={`hover:bg-[#F8FAFC] ${l.precedes_opening ? "text-[#94A3B8]" : ""}`}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-[#475569]">{l.transaction_date ?? "—"}</td>
                    <td className="px-3 py-1.5 min-w-[220px]">
                      <span className="text-[#1E293B]">{l.description}</span>
                      {l.reference_no && <span className="text-[10px] text-[#94A3B8] ml-1.5">{l.reference_no}</span>}
                      {!l.posted_journal_id && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-[#F1F5F9] text-[#64748B] ml-1.5">not posted</span>
                      )}
                      {l.precedes_opening && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-blue-50 text-blue-700 ml-1.5">before opening</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-[#64748B] whitespace-nowrap">{l.category ?? "—"}</td>
                    <td className="px-3 py-1.5 text-center">
                      {l.cleared === "R" ? (
                        <span title="Reconciled — part of a completed reconciliation"
                              className="text-[10px] font-semibold text-green-700">R</span>
                      ) : l.cleared === "C" ? (
                        <span title="Cleared — claimed by a reconciliation still in progress"
                              className="text-[10px] font-semibold text-amber-600">C</span>
                      ) : <span className="text-[#CBD5E1]">—</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-red-700 whitespace-nowrap">
                      {l.debit_paise ? fmt(l.debit_paise) : ""}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-green-700 whitespace-nowrap">
                      {l.credit_paise ? fmt(l.credit_paise) : ""}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono whitespace-nowrap ${
                      l.balance_paise < 0 ? "text-red-700" : "text-[#0F172A]"}`}>
                      {fmt(l.balance_paise)}
                      {!!l.balance_delta_paise && (
                        <span title={`The statement said ${fmt(l.statement_balance_paise ?? 0)} here`}
                              className="ml-1 text-[9px] text-amber-600">≠</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-3 py-2 border-t border-[#F1F5F9] flex items-center justify-between text-[11px] text-[#64748B]">
            <span>
              {data.filtered_count === data.total_count
                ? `${data.total_count} transaction${data.total_count === 1 ? "" : "s"}`
                : `${data.filtered_count} of ${data.total_count}`}
              {summary && summary.unposted_count > 0 && ` · ${summary.unposted_count} not yet posted`}
            </span>
            {totalPages > 1 && (
              <span className="flex items-center gap-2">
                <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
                  className="px-2 py-1 border border-[#E2E8F0] rounded disabled:opacity-40 hover:bg-[#F8FAFC]">Previous</button>
                <span>Page {page + 1} of {totalPages}</span>
                <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                  className="px-2 py-1 border border-[#E2E8F0] rounded disabled:opacity-40 hover:bg-[#F8FAFC]">Next</button>
              </span>
            )}
          </div>
        </div>
      )}

      <p className="text-[10px] text-[#94A3B8] text-center">
        The register is read-only. A posted journal cannot be edited — correct it with a
        reversal from the Accounting workspace, and the register will follow.
      </p>
    </div>
  );
}

