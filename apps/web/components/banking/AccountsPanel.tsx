"use client";
// Accounts panel: bank accounts, statement import, the column mapper
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// It was a tab for a few hours and is now a panel the Entries screen opens:
// adding an account and importing a statement are SETUP, done once and then
// occasionally, and a tab put them in the month's working sequence. The
// Entries toolbar's "Import statement" opens BankImportModal directly; the
// "Accounts" link opens this. `onChanged` tells the caller an import or an
// account change happened, so it can propose for the new lines at once.

import { useEffect, useState, useCallback, useRef } from "react";
import { Plus, RefreshCw, Upload, CheckCircle, X, FileText, Pencil, Landmark } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { api, ApiRefusal } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";

import { getBankStatements, getBankTransactions, BankStatement, BankTransaction } from "@/lib/data/bankStatements";
import { fmt, BankAccount } from "@/components/banking/shared";

export function BankAccounts({ clientId, onChanged }: { clientId: string; onChanged?: () => void }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  // {id: {deletable, blocked_by, reason}} — decides whether Delete is offered at
  // all, and what the disabled one says when it is not. `reason` is the SERVER's
  // sentence, the same one the DELETE refuses with: it names the statute, the
  // duty-holder and the date the duty lapses (services/bank_erasure.py). This
  // panel used to compose its own from blocked_by, which meant two wordings of
  // one refusal and neither of them naming a law.
  const [deletability, setDeletability] = useState<Record<string, { deletable: boolean; blocked_by: string[]; reason?: string | null }>>({});
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  // null = closed, "new" = create form, BankAccount = edit that account.
  const [accountModal, setAccountModal] = useState<BankAccount | "new" | null>(null);
  const [selectedStmt, setSelectedStmt] = useState<string | null>(null);
  const [stmtTxns, setStmtTxns] = useState<BankTransaction[]>([]);
  const [txnsLoading, setTxnsLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);

  // Loads BOTH the imported statements and the client's bank accounts — the
  // account list drives the import + reconciliation account pickers.
  const loadStatements = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const [stmts, accRes, delRes] = await Promise.all([
        getBankStatements(clientId),
        // include_inactive: this table is the only place a deactivated account can
        // be seen or reactivated, and its opening balance stays in the GL, so
        // hiding it left money on the balance sheet with no account to explain it.
        // The pickers below filter to activeAccounts themselves.
        api.banking.listBankAccounts({ client_id: clientId, include_inactive: "true" }) as Promise<{ success: boolean; data: BankAccount[] }>,
        (api.banking.bankAccountsDeletable({ client_id: clientId }) as Promise<{ success: boolean; data: Record<string, { deletable: boolean; blocked_by: string[]; reason?: string | null }> }>)
          .catch(() => ({ success: false, data: {} })),
      ]);
      setStatements(stmts);
      setAccounts(accRes.success ? (accRes.data ?? []) : []);
      setDeletability(delRes.success ? (delRes.data ?? {}) : {});
    } catch (e) {
      // Was a bare `/* skip */`, which read as "an empty statement list" — the
      // same screen a client with nothing imported yet gets. Say which it is.
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not load statements." });
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { loadStatements(); }, [loadStatements]);

  async function deactivateAccount(a: BankAccount) {
    setRowBusy(true);
    try {
    if (!confirm(`Deactivate ${a.bank_name} (····${a.account_no.slice(-4)})? Existing statements and reconciliations keep it — it just won't be selectable for new imports. You can reactivate it later by editing it.`)) return;
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: false }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not deactivate the account." }); return; }
      setMsg({ type: "ok", text: "Bank account deactivated." });
      loadStatements(); onChanged?.();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not deactivate the account." }); }
  } finally { setRowBusy(false); }
  }

  async function reactivateAccount(a: BankAccount) {
    setRowBusy(true);
    try {
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: true }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not reactivate the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} reactivated.` });
      loadStatements(); onChanged?.();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not reactivate the account." }); }
  } finally { setRowBusy(false); }
  }

  async function deleteAccount(a: BankAccount) {
    setRowBusy(true);
    try {
    if (!confirm(`Permanently delete ${a.bank_name} (····${a.account_no.slice(-4)})?\n\n`
      + `This account has no statements, no reconciliations and nothing posted to its `
      + `ledger, so there is no history to keep. Its ledger account goes with it if `
      + `nothing else uses it. This cannot be undone.`)) return;
    try {
      const res = await api.banking.deleteBankAccount(a.id) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not delete the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} deleted.` });
      loadStatements(); onChanged?.();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not delete the account." }); }
  } finally { setRowBusy(false); }
  }

  async function deleteStatement(st: BankStatement) {
    // BANK-06. The wrong file, the wrong client, the wrong month. There was no
    // way back: the statement stayed in the register for ever and its lines
    // kept surfacing in the match queue — and it could not be imported over,
    // because the import dedupes on a unique (client_id, import_hash).
    //
    // Whether it MAY go is the server's decision, not this dialog's: a
    // statement lines have been posted off is the voucher for those entries
    // (Companies Act s. 128(5)) and is refused with that sentence, shown here
    // verbatim.
    if (!confirm(`Remove the ${st.bank_name} statement for ${st.statement_from} → ${st.statement_to}?\n\n`
      + `Its ${st.row_count} imported lines go with it, so the right file can be `
      + `imported in its place. A statement with lines already posted, matched or `
      + `reconciled cannot be removed — the server will say so.`)) return;
    setRowBusy(true);
    try {
      const res = await api.banking.deleteStatement(st.id) as { success: boolean; error: string | null; detail?: string };
      if (!res.success) {
        setMsg({ type: "err", text: res.detail ?? res.error ?? "Could not remove the statement." });
        return;
      }
      setMsg({ type: "ok", text: `Statement removed — ${st.row_count} lines withdrawn.` });
      setSelectedStmt(null);
      loadStatements(); onChanged?.();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not remove the statement." });
    } finally { setRowBusy(false); }
  }

  const activeAccounts = accounts.filter((a) => a.is_active);

  async function openStatement(id: string) {
    setSelectedStmt(id); setTxnsLoading(true);
    try {
      setStmtTxns(await getBankTransactions(id));
    } catch (e) {
      setStmtTxns([]);
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not load this statement." });
    } finally {
      setTxnsLoading(false);
    }
  }

  const STATUS_COLORS: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    reviewed: "bg-blue-100 text-blue-700",
    posted: "bg-green-100 text-green-700",
  };

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <X size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* ── Bank accounts ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-4 py-3 border-b border-[#F1F5F9] flex items-center justify-between">
          <p className="text-xs font-semibold text-[#334155] flex items-center gap-1.5"><Landmark size={13} /> Bank Accounts</p>
          <button onClick={() => setAccountModal("new")} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> Add Account
          </button>
        </div>
        {loading ? (
          <TableSkeleton cols={6} rows={2} />
        ) : accounts.length === 0 ? (
          <div className="text-center py-8 px-4 space-y-1">
            <p className="text-sm text-[#64748B]">No bank accounts yet.</p>
            <p className="text-xs text-[#94A3B8]">Add a bank account to import its statements and run reconciliations.</p>
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-2.5 text-left font-semibold">Bank</th><th className="px-3 py-2.5 text-left font-semibold">Account No.</th><th className="px-3 py-2.5 text-left font-semibold">Type</th><th className="px-3 py-2.5 text-left font-semibold">Ledger Account</th><th className="px-3 py-2.5 text-right font-semibold">Opening Bal.</th><th className="px-4 py-2.5 text-right font-semibold">Actions</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {accounts.map((a) => (
                <tr key={a.id} className={`hover:bg-[#F8FAFC] ${a.is_active ? "" : "opacity-50"}`}>
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">
                    {a.bank_name}
                    {!a.is_active && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#94A3B8]">inactive</span>}
                    {a.ifsc && <div className="text-[10px] text-[#94A3B8] font-mono">{a.ifsc}</div>}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">{a.account_no}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{a.account_type}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">
                    {a.coa_account_id
                      ? (a.ledger_account_code
                          ? <span className="font-mono text-[11px]">{a.ledger_account_code} · {a.ledger_account_name}</span>
                          : "Linked")
                      : <span className="text-amber-600">Not linked</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#334155]">
                    {fmt(a.opening_balance_paise)}
                    {/* The backend's sentence, not a guess from the columns —
                        an opening balance with no as-at date makes every
                        balance on this account wrong by the total of whatever
                        predates it. */}
                    {a.opening_balance_gap && (
                      <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 font-sans"
                            title={a.opening_balance_gap}>no date</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <button onClick={() => setAccountModal(a)} className="text-[#4338CA] hover:text-[#3730A3] inline-flex items-center gap-1"><Pencil size={11} /> Edit</button>
                    {a.is_active
                      ? <button disabled={rowBusy} onClick={() => deactivateAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Deactivate</button>
                      : <button disabled={rowBusy} onClick={() => reactivateAccount(a)} className="ml-3 text-[#059669] hover:text-[#047857]">Reactivate</button>}
                    {/* Delete is offered only for an account with no footprint.
                        When it is blocked the button stays, disabled, carrying the
                        reason — "why can't I delete this?" is the question a
                        missing button leaves unanswered. */}
                    {deletability[a.id]?.deletable ? (
                      <button disabled={rowBusy} onClick={() => deleteAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Delete</button>
                    ) : deletability[a.id] ? (
                      <span className="ml-3 text-[#CBD5E1] cursor-not-allowed"
                            title={deletability[a.id].reason
                              || `Cannot be deleted because ${deletability[a.id].blocked_by.join("; ")}. Deactivate it instead — that keeps its history.`}>Delete</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{statements.length} bank statement{statements.length !== 1 ? "s" : ""} imported</p>
        <div className="flex gap-2">
          <button onClick={loadStatements} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => activeAccounts.length === 0 ? setAccountModal("new") : setShowImport(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            title={activeAccounts.length === 0 ? "Add a bank account first" : "Import a statement for one of your bank accounts"}
          >
            <Upload size={12} /> Import Statement
          </button>
        </div>
      </div>

      {loading ? (
        <TableSkeleton cols={7} rows={3} />
      ) : statements.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <FileText size={32} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No bank statements imported yet</p>
          <button onClick={() => setShowImport(true)} className="text-xs text-blue-600 hover:underline">Import your first statement</button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-3 text-left font-semibold">Bank</th><th className="px-3 py-3 text-left font-semibold">Account No.</th><th className="px-3 py-3 text-left font-semibold">Period</th><th className="px-3 py-3 text-right font-semibold">Credits</th><th className="px-3 py-3 text-right font-semibold">Debits</th><th className="px-3 py-3 text-left font-semibold">Status</th><th className="px-4 py-3 text-left font-semibold">Action</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {statements.map((s) => (
                <tr key={s.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">{s.bank_name}</td>
                  <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">{s.account_number ?? "—"}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{s.statement_from} → {s.statement_to}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-green-700">{fmt(s.total_credits_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-red-700">{fmt(s.total_debits_paise)}</td>
                  <td className="px-3 py-2.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[s.import_status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>{s.import_status}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <button onClick={() => selectedStmt === s.id ? setSelectedStmt(null) : openStatement(s.id)} className="text-xs text-blue-600 hover:underline">
                      {selectedStmt === s.id ? "Hide" : "View"} ({s.row_count} txns)
                    </button>
                    <button
                      onClick={() => deleteStatement(s)}
                      disabled={rowBusy}
                      title="Remove a statement imported by mistake"
                      className="text-xs text-red-600 hover:underline ml-3 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Statement transactions inline view */}
      {selectedStmt && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">Transactions</p>
            {txnsLoading && <RefreshCw size={13} className="animate-spin text-[#94A3B8]" />}
          </div>
          {!txnsLoading && stmtTxns.length > 0 && (
            <div className="overflow-x-auto max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white"><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-2 text-left font-semibold">Date</th><th className="px-3 py-2 text-left font-semibold">Description</th><th className="px-3 py-2 text-right font-semibold">Debit</th><th className="px-3 py-2 text-right font-semibold">Credit</th><th className="px-3 py-2 text-left font-semibold">Status</th></tr></thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {stmtTxns.map((t) => (
                    <tr key={t.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-4 py-2 text-[#64748B] whitespace-nowrap">{t.transaction_date}</td>
                      <td className="px-3 py-2 text-[#334155] max-w-xs truncate">{t.description}</td>
                      <td className="px-3 py-2 text-right font-mono text-red-700">{t.debit_paise > 0 ? fmt(t.debit_paise) : "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-green-700">{t.credit_paise > 0 ? fmt(t.credit_paise) : "—"}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${t.match_status === "posted" ? "bg-green-100 text-green-700" : t.match_status === "matched" ? "bg-blue-100 text-blue-700" : t.match_status === "ignored" ? "bg-[#F1F5F9] text-[#94A3B8]" : "bg-amber-100 text-amber-700"}`}>{t.match_status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!txnsLoading && stmtTxns.length === 0 && <div className="text-center py-8 text-[#94A3B8] text-sm">No transactions found.</div>}
        </div>
      )}

      {showImport && (
        <BankImportModal
          clientId={clientId}
          accounts={activeAccounts}
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); loadStatements(); onChanged?.(); }}
          onManageAccounts={() => { setShowImport(false); setAccountModal("new"); }}
        />
      )}
      {accountModal && (
        <BankAccountModal
          clientId={clientId}
          account={accountModal === "new" ? null : accountModal}
          onClose={() => setAccountModal(null)}
          onSaved={() => { setAccountModal(null); setMsg({ type: "ok", text: "Bank account saved." }); loadStatements(); onChanged?.(); }}
        />
      )}
    </div>
  );
}

// ── Bank Account Modal (create / edit) ─────────────────────────────────────
// A bank account is the entity a statement is imported against and a
// reconciliation session is opened for. coa_account_id links it to a
// chart-of-accounts ledger account so postings hit the right GL account and
// the opening balance flows to the books (backend auto-syncs on save).

interface CoaAccountLite { id: string; account_code: string; account_name: string; account_type: string; account_subtype?: string | null }

export function BankAccountModal({ clientId, account, onClose, onSaved }: {
  clientId: string; account: BankAccount | null; onClose: () => void; onSaved: () => void;
}) {
  const editing = !!account;
  const [bankName, setBankName] = useState(account?.bank_name ?? "HDFC Bank");
  const [accountNo, setAccountNo] = useState(account?.account_no ?? "");
  const [ifsc, setIfsc] = useState(account?.ifsc ?? "");
  const [accountType, setAccountType] = useState(account?.account_type ?? "Current");
  const [openingBal, setOpeningBal] = useState(account ? (account.opening_balance_paise / 100).toString() : "");
  const [openingDate, setOpeningDate] = useState(account?.opening_balance_date ?? "");
  const [coaId, setCoaId] = useState(account?.coa_account_id ?? "");
  const [isActive, setIsActive] = useState(account?.is_active ?? true);
  const [coaAccounts, setCoaAccounts] = useState<CoaAccountLite[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      // ASSET **OR** LIABILITY, because an overdraft is not an asset (BANK-02).
      // bank_accounts.account_type has allowed 'Cash Credit' and 'Overdraft'
      // since migration 054 and this form offers both — but the picker filtered
      // `account_type = "Asset"`, so a CA who created an OD account could not
      // point it at a liability ledger even by hand. Migration 342 creates the
      // right one automatically and re-classifies the existing ones; this is
      // what lets the manual picker agree with it.
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, account_subtype")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .in("account_type", ["Asset", "Liability"])
        .order("account_code").order("id"));
      setCoaAccounts((data as CoaAccountLite[]) ?? []);
    })();
  }, [clientId]);

  async function save() {
    if (!bankName.trim()) { setError("Bank name is required."); return; }
    if (!editing && !accountNo.trim()) { setError("Account number is required."); return; }
    // An opening balance read wrong is wrong for the life of the account: every
    // reconciliation after it starts from this number.
    const openingPaise = paiseFromRupeeInput(openingBal || "0");
    if (openingPaise === null) {
      setError("Opening balance must be an amount in rupees, e.g. 125000 or "
               + "125000.50 — without commas.");
      return;
    }
    // BANK-27. An opening balance is a balance AS AT a date. Without one the
    // Bank Book counts every transaction on the account, including the ones
    // this figure already contains, so the running balance is wrong by their
    // total and the check against the bank's own stated balance diverges at
    // an innocent line. The API refuses this too — asked here so the CA is
    // told beside the field rather than after a round trip.
    if (openingPaise !== 0 && !openingDate) {
      setError("An opening balance needs the date it is the balance as at — "
               + "usually the day this client's books begin. Without it the Bank "
               + "Book cannot tell which transactions the figure already includes.");
      return;
    }
    setSaving(true); setError(null);
    try {
      const res = (editing
        ? await api.banking.updateBankAccount(account!.id, {
            bank_name: bankName.trim(), ifsc: ifsc.trim() || null, account_type: accountType,
            opening_balance_paise: openingPaise, opening_balance_date: openingDate || null,
            coa_account_id: coaId || null, is_active: isActive,
          })
        : await api.banking.createBankAccount({
            client_id: clientId, bank_name: bankName.trim(), account_no: accountNo.trim(),
            ifsc: ifsc.trim() || null, account_type: accountType,
            opening_balance_paise: openingPaise, opening_balance_date: openingDate || null,
            coa_account_id: coaId || null,
          })
      ) as { success: boolean; error: string | null };
      if (!res.success) { setError(res.error ?? "Could not save the bank account."); return; }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the bank account.");
    } finally {
      setSaving(false);
    }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";
  const labelCls = "block text-xs font-medium text-[#475569] mb-1";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">{editing ? "Edit Bank Account" : "Add Bank Account"}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className={labelCls}>Bank Name *</label>
            {/* Plain text, no datalist. The ten-bank suggestion list rendered a
                dropdown arrow that read as a closed picker, and India has some
                1,500 banks — co-operative and regional ones especially are what a
                CA's smaller clients actually bank with. */}
            <input value={bankName} onChange={(e) => setBankName(e.target.value)} className={inputCls} placeholder="e.g. Saraswat Co-operative Bank" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Account Number *</label>
              <input value={accountNo} onChange={(e) => setAccountNo(e.target.value)} disabled={editing} className={`${inputCls} font-mono ${editing ? "bg-[#F8FAFC] text-[#94A3B8]" : ""}`} placeholder="50100XXXXXXX" />
            </div>
            <div>
              <label className={labelCls}>IFSC</label>
              <input value={ifsc} onChange={(e) => setIfsc(e.target.value.toUpperCase())} maxLength={11} className={`${inputCls} font-mono`} placeholder="HDFC0001234" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Account Type</label>
              <select value={accountType} onChange={(e) => setAccountType(e.target.value)} className={inputCls}>
                {["Current","Savings","Cash Credit","Overdraft"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className={labelCls}>Opening Balance (₹)</label>
              <input type="number" step="0.01" value={openingBal} onChange={(e) => setOpeningBal(e.target.value)} className={inputCls} placeholder="0.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>
                Opening Balance Date{openingBal && openingBal !== "0" ? " *" : ""}
              </label>
              <input type="date" value={openingDate} onChange={(e) => setOpeningDate(e.target.value)} className={inputCls} />
              {openingBal && openingBal !== "0" && !openingDate && (
                <p className="mt-1 text-[11px] text-amber-700">
                  The date this balance is as at — usually the day the books begin.
                  Without it the Bank Book adds transactions the figure already includes.
                </p>
              )}
            </div>
            {editing && (
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-2 text-xs text-[#475569]">
                  <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="accent-[#4338CA]" /> Active
                </label>
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Ledger Account (GL link)</label>
            <select value={coaId} onChange={(e) => setCoaId(e.target.value)} className={inputCls}>
              <option value="">— Not linked —</option>
              {coaAccounts.map((c) => <option key={c.id} value={c.id}>{c.account_code} · {c.account_name}</option>)}
            </select>
            <p className="text-[10px] text-[#94A3B8] mt-1">Links this bank account to a chart-of-accounts asset account so postings and the opening balance hit the right GL account.</p>
          </div>
        </div>
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Saving…" : editing ? "Save Changes" : "Add Account"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Statement column mapping (audit Tier 3.2) ──────────────────────────────
// The six auto-detected layouts cover HDFC, SBI, ICICI, Axis and two generic
// shapes. Everything else used to stop dead at "Unsupported bank statement
// format". These types are the shape of the way past it.

type StatementMapping = Record<string, number | null>;

interface StatementInspection {
  headers: string[];
  sample_rows: string[][];
  total_rows: number;
  detected_format: string;
  detected_fits: boolean;
  proposed_mapping: StatementMapping | null;
  saved_mapping: StatementMapping | null;
  header_fingerprint: string;
}

interface BalanceCheck {
  checked: boolean;
  agrees?: boolean;
  order?: string;
  note?: string;
  reason?: string;
  rows_checked?: number;
  disagreeing_rows?: number;
}

/** Whether the parse matches the totals the BANK printed on the statement.
 *  Free wherever the bank prints a "Grand Total" row, which most Indian
 *  statements do — see apps/api/domain/banking/tie_out.py for why this is not
 *  the same question as `BalanceCheck`, which only asks whether the rows agree
 *  with each other. */
interface TotalsCheck {
  checked: boolean;
  agrees?: boolean;
  label?: string;
  gap?: string;
  reason?: string;
  /** The statement prints SEVERAL totals rows and none is a grand total, so
   *  which of them totals the whole statement cannot be told from the file.
   *  Not the same as printing none, and the CA is told which it is. */
  ambiguous?: boolean;
}

interface ImportResult {
  imported: number;
  duplicates_skipped: number;
  total_rows: number;
  /** Did ANYTHING confirm the parse — the statement's own totals, or the two
   *  balances? An unverified import and a verified one must not look the same. */
  verified?: boolean;
  verification_gap?: string | null;
  totals_check?: TotalsCheck;
  /** This statement went in although its own printed totals disagreed with the
   *  lines read from it, on a written reason now stored against it. */
  totals_mismatch_acknowledged?: boolean;
}

interface StatementPreview {
  headers: string[];
  total_rows: number;
  parsed_count: number;
  skipped_count: number;
  rows: {
    transaction_date: string; description: string; reference_no: string | null;
    debit_paise: number; credit_paise: number; balance_paise: number;
  }[];
  balance_check: BalanceCheck;
  totals_check?: TotalsCheck;
}

/** The fields a statement row can carry. Order is the order they are asked for. */
const MAPPING_FIELDS: { key: string; label: string; hint: string; required?: boolean }[] = [
  { key: "date",    label: "Date",        hint: "the transaction date", required: true },
  { key: "desc",    label: "Description", hint: "narration / particulars", required: true },
  { key: "ref",     label: "Reference",   hint: "cheque or UTR number" },
  { key: "debit",   label: "Debit",       hint: "money out (withdrawals)" },
  { key: "credit",  label: "Credit",      hint: "money in (deposits)" },
  { key: "amount",  label: "Amount",      hint: "one column for both directions" },
  { key: "drcr",    label: "Dr/Cr",       hint: "which way the Amount goes" },
  { key: "balance", label: "Balance",     hint: "running balance after the row" },
];

const EMPTY_MAPPING: StatementMapping = {
  date: null, desc: null, ref: null, debit: null,
  credit: null, amount: null, drcr: null, balance: null,
};

/** Drop the unmapped fields — the server reads an absent key as "not present". */
function cleanMapping(m: StatementMapping): StatementMapping {
  return Object.fromEntries(Object.entries(m).filter(([, v]) => v !== null && v !== undefined));
}

/** Is this the dead end the mapper exists for, rather than a network fault?
 *
 *  The backend raises two different sentences for it — "Unsupported bank
 *  statement format" when nothing matches, and "layout doesn't match the
 *  detected 'x' format" when an adapter is picked and then fails to fit. Both
 *  are the same problem to a CA, and both list the banks we do support, which
 *  is the phrase they reliably share. */
function looksLikeAFormatProblem(message: string): boolean {
  const m = message.toLowerCase();
  return m.includes("unsupported bank statement format")
    || m.includes("layout doesn't match")
    || m.includes("could not identify")
    || m.includes("no transactions found");
}

// ── Bank Import Modal ──────────────────────────────────────────────────────

export function BankImportModal({ clientId, accounts, onClose, onImported, onManageAccounts }: {
  clientId: string; accounts: BankAccount[]; onClose: () => void; onImported: () => void; onManageAccounts: () => void;
}) {
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // ── Column mapping (audit Tier 3.2) ──────────────────────────────────────
  // Six statement layouts are auto-detected. Every other bank — Kotak, IDFC
  // First, PNB, Canara, and every co-operative bank — used to stop at
  // "Unsupported bank statement format" with nothing the CA could do. Now that
  // error opens this: say where the columns are, once, and it is remembered
  // for the account.
  const [mapping, setMapping] = useState<StatementMapping | null>(null);
  const [inspected, setInspected] = useState<StatementInspection | null>(null);
  const [preview, setPreview] = useState<StatementPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [remember, setRemember] = useState(true);
  const [overrideBalance, setOverrideBalance] = useState(false);
  // BANK-01. The statement's own totals row disagreeing with the lines read
  // from it used to be the end of the road: the refusal came back, and the only
  // way past it was to edit the bank's file by hand. A CA who has compared the
  // two figures themselves can now say why and import — the reason is stored on
  // the statement (migration 354) and the import is NOT reported as verified.
  // This is revealed by the server's refusal, never offered up front: a box
  // that is always there is a box people tick without reading.
  const [totalsRefusal, setTotalsRefusal] = useState<string | null>(null);
  const [ackReason, setAckReason] = useState("");
  const ackReady = ackReason.trim().length >= 10;

  // ── The tie-out, and reading a scan ──────────────────────────────────────
  // The two balances PRINTED on the statement. The server checks
  // opening + credits - debits == closing before importing anything, which is
  // the only thing that proves every line was read. Optional for a file we can
  // parse; REQUIRED for a scan, because there a model did the reading.
  const [openingRs, setOpeningRs] = useState("");
  const [closingRs, setClosingRs] = useState("");
  const [allowVision, setAllowVision] = useState(false);

  const account = accounts.find((a) => a.id === accountId);
  const isImage = /\.(jpe?g|png|webp)$/i.test(file?.name ?? "");
  const couldBeAScan = isImage || /\.pdf$/i.test(file?.name ?? "");
  const openingPaise = openingRs.trim() ? paiseFromRupeeInput(openingRs) : null;
  const closingPaise = closingRs.trim() ? paiseFromRupeeInput(closingRs) : null;
  // ONE request at a time, from ANY control in this dialog.
  //
  // Each button used to be disabled only by its OWN flag, so "Map columns" and
  // "Import" could both be in flight at once — the screenshot that found this
  // showed "Reading…" and "Importing…" side by side. That is not cosmetic here:
  // startMapping and runPreview both call setInspected/setMapping/setPreview,
  // so a read landing mid-import rewrites the dialog under a running upload,
  // and whichever finishes second overwrites the other's error message. The
  // import is a WRITE; the CA has to be able to tell which outcome they are
  // looking at.
  const busy = checking || importing;
  const balancesTyped = openingRs.trim() !== "" || closingRs.trim() !== "";
  const balancesBad = balancesTyped && (openingPaise === null || closingPaise === null);

  function resetMapping() {
    setMapping(null); setInspected(null); setPreview(null); setOverrideBalance(false);
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f); setError(null); setResult(null); resetMapping(); setAllowVision(false);
      // A reason written about one statement must not follow a different file.
      setTotalsRefusal(null); setAckReason("");
    }
  }

  function baseForm(): FormData {
    const form = new FormData();
    if (file) form.append("file", file);
    form.append("client_id", clientId);
    return form;
  }

  /** Open the mapper: read the file's header row and pre-fill what we can. */
  async function startMapping() {
    if (!file || !account) return;
    setChecking(true); setError(null);
    try {
      const form = baseForm();
      form.append("bank_account_id", account.id);
      const res = (await api.banking.inspectStatement(form)) as { success: boolean; data: StatementInspection };
      const info = res.data;
      setInspected(info);
      // A saved mapping for this exact layout wins; then the detected adapter,
      // but ONLY when it actually fits — prefilling a layout the server has
      // just rejected would hand the CA the error to confirm.
      setMapping({ ...EMPTY_MAPPING, ...(info.saved_mapping ?? info.proposed_mapping ?? {}) });
      setPreview(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the file.");
    } finally {
      setChecking(false);
    }
  }

  /** Parse with the mapping and show what it produces — nothing is imported. */
  async function runPreview() {
    if (!file || !mapping) return;
    setChecking(true); setError(null); setOverrideBalance(false);
    try {
      const form = baseForm();
      form.append("column_mapping", JSON.stringify(cleanMapping(mapping)));
      const res = (await api.banking.previewStatement(form)) as { success: boolean; data: StatementPreview };
      setPreview(res.data);
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "Could not read the file with that mapping.");
    } finally {
      setChecking(false);
    }
  }

  async function handleImport() {
    if (!account) { setError("Select a bank account."); return; }
    if (!file) { setError("Select a statement file (.csv, .xlsx or .pdf), or a scan."); return; }
    if (balancesBad) { setError("Enter both balances as plain amounts, e.g. 1,30,000.00"); return; }
    if (balancesTyped && (openingPaise === null || closingPaise === null)) {
      setError("Give BOTH the opening and closing balance — one alone cannot check anything.");
      return;
    }
    setImporting(true); setError(null);
    try {
      // Server-side parse + normalize + dedup (bank-specific adapters, fail-loud,
      // integer-paise) — the browser sends the raw file, no client-side parsing.
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      form.append("bank_account_id", account.id);
      form.append("bank_name", account.bank_name);
      if (account.account_no) form.append("account_number", account.account_no);
      if (mapping) {
        form.append("column_mapping", JSON.stringify(cleanMapping(mapping)));
        form.append("save_mapping", remember ? "true" : "false");
      }
      // Integer paise, parsed by lib/money/rupeeInput — the one parser
      // (CLAUDE.md). Both or neither: one alone cannot check anything.
      if (openingPaise !== null && closingPaise !== null) {
        form.append("opening_balance_paise", String(openingPaise));
        form.append("closing_balance_paise", String(closingPaise));
      }
      if (allowVision) form.append("allow_vision", "true");
      // Only ever sent for the refusal the CA is looking at, and only once it
      // is substantive — the server refuses a shorter one, and refuses it
      // outright when there is nothing to acknowledge.
      if (totalsRefusal && ackReady) form.append("acknowledge_totals_mismatch", ackReason.trim());
      const res = (await api.banking.uploadStatement(form)) as {
        success: boolean; data: ImportResult; error?: string;
      };
      if (!res.success) { setError(res.error ?? "Import failed."); setImporting(false); return; }
      setResult(res.data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Import failed";
      setError(message);
      // The refusal's CODE, not its wording — see lib/api ApiRefusal. This one
      // has a way past, so show it rather than leaving the CA to edit the
      // bank's file.
      if (err instanceof ApiRefusal && err.code === "totals_mismatch") setTotalsRefusal(message);
      // The format errors are the ones the mapper exists for, so go straight
      // there rather than leaving the CA at a dead end with an explanation.
      if (!mapping && looksLikeAFormatProblem(message)) void startMapping();
    } finally {
      setImporting(false);
    }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className={`bg-white rounded-xl shadow-xl w-full p-6 space-y-4 ${inspected ? "max-w-3xl max-h-[90vh] overflow-y-auto" : "max-w-md"}`}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">
            {inspected ? "Map the statement columns" : "Import Bank Statement"}
          </h3>
          <button onClick={onClose} disabled={importing} aria-label="Close"
                  className="text-[#94A3B8] hover:text-[#475569] disabled:opacity-40"><X size={16} /></button>
        </div>

        {result ? (
          <>
            {/* LEAD WITH THE OUTCOME, NOT THE COUNTER.
                Re-uploading a statement that is already in produced a green
                tick over the words "0 transactions imported", which reads as a
                failure — the CA's next move is to try again. Both numbers were
                accurate; the headline was answering "what did this click add?"
                when the question in the CA's head is "is this statement in?".
                Nothing was rejected here, so nothing is coloured as a problem;
                what changes is which sentence is the big one. */}
            <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-center space-y-1">
              <CheckCircle size={20} className="text-green-600 mx-auto" />
              {result.imported === 0 && result.duplicates_skipped > 0 ? (
                <>
                  <p className="text-sm font-medium text-green-700">Already imported — nothing new to add</p>
                  <p className="text-xs text-green-600">
                    All {result.duplicates_skipped} line{result.duplicates_skipped === 1 ? " was" : "s were"} already in this client&apos;s books.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium text-green-700">{result.imported} transaction{result.imported === 1 ? "" : "s"} imported</p>
                  {result.duplicates_skipped > 0 && (
                    <p className="text-xs text-green-600">{result.duplicates_skipped} line{result.duplicates_skipped === 1 ? " was" : "s were"} already in and {result.duplicates_skipped === 1 ? "was" : "were"} skipped</p>
                  )}
                </>
              )}
            </div>
            {/* Say what checked it. A verified import and an unverified one
                looked identical before, which is how a half-read statement
                becomes a client's cash position. */}
            {result.verified ? (
              <p className="text-xs text-green-700 text-center">
                {result.totals_check?.agrees
                  ? <>Checked against the statement&apos;s own &ldquo;{result.totals_check.label}&rdquo; row — every line was read.</>
                  : <>Checked against the opening and closing balances — every line was read.</>}
              </p>
            ) : result.totals_mismatch_acknowledged ? (
              // Its own branch, because it is not the same thing as "nothing
              // checked it". Something DID check it and disagreed, and somebody
              // decided to import anyway — that is a stronger statement than a
              // gap and it is now on the statement row and the client timeline.
              <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                Imported over the statement&apos;s own totals, on the reason you gave.
                It is recorded against this statement. {result.verification_gap}
              </p>
            ) : (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                {result.verification_gap
                  ?? "Nothing confirmed that every line was read."}{" "}
                Compare the totals against the statement before you rely on these figures.
              </p>
            )}
            <div className="flex justify-end">
              <button onClick={onImported} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Done</button>
            </div>
          </>
        ) : (
          <>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Bank Account *</label>
                {accounts.length === 0 ? (
                  <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                    No active bank accounts. <button onClick={onManageAccounts} className="underline font-medium">Add one first</button>.
                  </div>
                ) : (
                  <select value={accountId} onChange={(e) => setAccountId(e.target.value)} className={inputCls}>
                    {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} · ····{a.account_no.slice(-4)}</option>)}
                  </select>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Statement File * <span className="font-normal text-[#94A3B8]">(.csv, .xlsx or .pdf)</span></label>
                <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx,.pdf,.jpg,.jpeg,.png,.webp" onChange={handleFile} className="hidden" />
                <button onClick={() => fileRef.current?.click()} disabled={busy} className="disabled:opacity-40 w-full border-2 border-dashed border-[#E2E8F0] rounded-lg py-4 text-sm text-[#64748B] hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center gap-2">
                  <Upload size={16} /> {file ? file.name : "Click to select a statement file"}
                </button>
                <p className="text-[10px] text-[#94A3B8] mt-1">The file is parsed on the server — HDFC / SBI / ICICI / Axis are auto-detected. Any other bank: use <span className="font-medium">Map columns</span> once and we&apos;ll remember it. Amounts stay exact.</p>
              </div>

              {/* The two figures printed on the statement. The server checks
                  opening + credits - debits == closing before importing
                  anything — the only thing that proves every line was read. */}
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">
                  Statement balances
                  <span className="font-normal text-[#94A3B8]">
                    {allowVision
                      ? " — needed for a scan only if it prints no totals"
                      : " — optional; they say this file is the whole period"}
                  </span>
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <input value={openingRs} onChange={(e) => setOpeningRs(e.target.value)}
                         placeholder="Opening e.g. 1,00,000.00" className={inputCls} inputMode="decimal" />
                  <input value={closingRs} onChange={(e) => setClosingRs(e.target.value)}
                         placeholder="Closing e.g. 1,30,000.00" className={inputCls} inputMode="decimal" />
                </div>
                <p className="text-[10px] text-[#94A3B8] mt-1">
                  {balancesBad
                    ? "Enter plain amounts — 1,30,000.00"
                    : "If the statement prints its own totals we check against those automatically. Give both balances as well and nothing imports unless the lines also add up from one to the other."}
                </p>
              </div>

              {/* Only offered for a file that could BE a scan. A CSV never needs
                  it, and a text PDF is parsed properly without it — the server
                  tries the real parsers first and never sends a readable file
                  to a model. */}
              {couldBeAScan && (
                <label className="flex items-start gap-2 text-xs text-[#475569] cursor-pointer">
                  <input type="checkbox" checked={allowVision} className="mt-0.5"
                         onChange={(e) => setAllowVision(e.target.checked)} />
                  <span>
                    Read this with AI if it is a scan or a photo
                    <span className="block text-[10px] text-[#94A3B8]">
                      {isImage
                        ? "A photograph has to be read this way."
                        : "Only used if the PDF has no readable text — a normal PDF is parsed exactly, without AI."}
                      {" Nothing is imported unless the figures add up — to the statement\u2019s own totals if it prints them, otherwise to the balances above, which we\u2019ll then ask for."}
                    </span>
                  </span>
                </label>
              )}
            </div>

            {inspected && mapping && (
              <div className="space-y-3 border-t border-[#E2E8F0] pt-3">
                <p className="text-xs text-[#475569]">
                  This bank&apos;s layout isn&apos;t one we recognise. Tell us which column holds
                  what — once. {account ? <>We&apos;ll remember it for <span className="font-medium">{account.bank_name}</span> and use it next time.</> : null}
                </p>

                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {MAPPING_FIELDS.map((f) => (
                    <div key={f.key}>
                      <label className="block text-[11px] font-medium text-[#475569]">
                        {f.label}{f.required && <span className="text-red-500"> *</span>}
                        <span className="font-normal text-[#94A3B8]"> — {f.hint}</span>
                      </label>
                      <select
                        value={mapping[f.key] ?? ""}
                        onChange={(e) => {
                          const v = e.target.value === "" ? null : Number(e.target.value);
                          setMapping({ ...mapping, [f.key]: v });
                          setPreview(null);          // the mapping changed; the old check no longer describes it
                          setOverrideBalance(false);
                        }}
                        className="w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">— not in this file —</option>
                        {inspected.headers.map((h, i) => (
                          <option key={i} value={i}>{i + 1}. {h || `(column ${i + 1})`}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                <p className="text-[10px] text-[#94A3B8]">
                  Use either <span className="font-medium">Debit + Credit</span>, or a single{" "}
                  <span className="font-medium">Amount</span> with a <span className="font-medium">Dr/Cr</span> column — not both.
                </p>

                <div className="flex items-center gap-3">
                  <button onClick={runPreview} disabled={busy}
                          className="text-xs px-3 py-1.5 border border-blue-200 text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 disabled:opacity-40">
                    {checking ? "Checking…" : "Check this mapping"}
                  </button>
                  <label className="flex items-center gap-1.5 text-[11px] text-[#475569]">
                    <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                    Remember this layout for this account
                  </label>
                </div>

                {preview && (
                  <div className="space-y-2">
                    {/* The bank's own running balance is what verifies the mapping.
                        A swapped Debit/Credit parses perfectly and inverts the
                        client's cash — no column-label check could catch it. */}
                    {preview.balance_check.checked && preview.balance_check.agrees && (
                      <p className="text-xs text-green-700 bg-green-50 border border-green-100 rounded px-3 py-2">
                        ✓ Checked against the bank&apos;s own balance column across{" "}
                        {preview.balance_check.rows_checked} row{preview.balance_check.rows_checked === 1 ? "" : "s"} — every
                        movement agrees.{preview.balance_check.note ? ` ${preview.balance_check.note}` : ""}
                      </p>
                    )}
                    {preview.balance_check.checked && preview.balance_check.agrees === false && (
                      <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 space-y-1.5">
                        <p className="font-medium">This mapping disagrees with the bank&apos;s own balances.</p>
                        <p>{preview.balance_check.reason}</p>
                        <label className="flex items-center gap-1.5">
                          <input type="checkbox" checked={overrideBalance} onChange={(e) => setOverrideBalance(e.target.checked)} />
                          Import anyway — I have checked the rows below and they are right
                        </label>
                      </div>
                    )}
                    {!preview.balance_check.checked && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-3 py-2">
                        This statement has no balance column, so the mapping could not be
                        checked arithmetically. Read the rows below before importing.
                      </p>
                    )}
                    {/* The statement's own totals — a second, independent check.
                        The balance column says the rows agree with each other;
                        this says they agree with what the bank printed. */}
                    {preview.totals_check?.checked && preview.totals_check.agrees && (
                      <p className="text-xs text-green-700 bg-green-50 border border-green-100 rounded px-3 py-2">
                        ✓ Adds up to the statement&apos;s own &ldquo;{preview.totals_check.label}&rdquo; row.
                      </p>
                    )}
                    {preview.totals_check?.checked && preview.totals_check.agrees === false && (
                      <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
                        {preview.totals_check.reason}
                      </p>
                    )}
                    {/* Printing several totals rows with no grand total is not
                        the same as printing none, and saying "no totals" in
                        front of a statement that visibly has them sends the CA
                        looking for a parsing bug. */}
                    {preview.totals_check?.ambiguous && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-3 py-2">
                        {preview.totals_check.gap}
                      </p>
                    )}

                    <p className="text-[11px] text-[#475569]">
                      {preview.parsed_count} of {preview.total_rows} rows read
                      {preview.skipped_count > 0 && <span className="text-amber-700"> · {preview.skipped_count} skipped</span>}
                    </p>
                    <div className="overflow-x-auto border border-[#E2E8F0] rounded-lg">
                      <table className="w-full text-[11px]">
                        <thead className="bg-[#F8FAFC] text-[#64748B]">
                          <tr>
                            <th className="text-left px-2 py-1.5">Date</th>
                            <th className="text-left px-2 py-1.5">Description</th>
                            <th className="text-right px-2 py-1.5">Debit</th>
                            <th className="text-right px-2 py-1.5">Credit</th>
                            <th className="text-right px-2 py-1.5">Balance</th>
                          </tr>
                        </thead>
                        <tbody>
                          {preview.rows.map((r, i) => (
                            <tr key={i} className="border-t border-[#F1F5F9]">
                              <td className="px-2 py-1.5 whitespace-nowrap">{r.transaction_date}</td>
                              <td className="px-2 py-1.5 max-w-[18rem] truncate" title={r.description}>{r.description}</td>
                              <td className="px-2 py-1.5 text-right">{r.debit_paise ? formatPaise(r.debit_paise) : ""}</td>
                              <td className="px-2 py-1.5 text-right">{r.credit_paise ? formatPaise(r.credit_paise) : ""}</td>
                              <td className="px-2 py-1.5 text-right text-[#64748B]">{r.balance_paise ? formatPaise(r.balance_paise) : ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {error && !totalsRefusal && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

            {/* The one refusal in this import with a way past it (BANK-01). It
                is shown only after the server has refused, so the reason is
                written about a mismatch the CA can see, with both figures in
                front of them. */}
            {totalsRefusal && (
              <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 space-y-2">
                <p>{totalsRefusal}</p>
                <label className="block font-medium">
                  Why is this file right?
                  <textarea
                    value={ackReason}
                    onChange={(e) => setAckReason(e.target.value)}
                    rows={2}
                    placeholder="e.g. the export is filtered to one page; the printed total covers the whole month"
                    className="mt-1 w-full px-2 py-1.5 font-normal border border-amber-200 rounded focus:outline-none focus:ring-2 focus:ring-amber-400"
                  />
                </label>
                <p className="text-[11px] text-amber-700">
                  {ackReady
                    ? "This is stored against the statement, beside the difference it explains, and the import will not be reported as checked."
                    : "At least 10 characters — this goes on the record."}
                </p>
              </div>
            )}
            <div className="flex gap-3 justify-end">
              {/* Closing mid-import would unmount the dialog with the upload still
                  in flight: the write continues server-side and the CA never
                  learns whether 292 transactions landed, so the honest thing is
                  to make them wait for the answer. A read is abandonable —
                  nothing has been written — so Cancel stays live for that. */}
              <button onClick={onClose} disabled={importing}
                      className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">Cancel</button>
              {!inspected && file && (
                <button onClick={startMapping} disabled={busy || !account}
                        className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">
                  {checking ? "Reading…" : "Map columns"}
                </button>
              )}
              <button
                onClick={handleImport}
                disabled={
                  busy || !file || accounts.length === 0
                  // With the mapper open, importing is gated on a check having
                  // been run: the preview IS the safety argument for skipping
                  // the column-label validation, so importing without it would
                  // give up the guard and gain nothing.
                  || (!!inspected && !preview)
                  || (!!preview && preview.balance_check.agrees === false && !overrideBalance)
                  // Refused on the statement's own totals: the button is now
                  // "Import anyway", and it needs the reason first.
                  || (!!totalsRefusal && !ackReady)
                }
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
              >
                {importing ? "Importing…" : totalsRefusal ? "Import anyway" : "Import"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

