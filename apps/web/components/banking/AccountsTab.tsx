"use client";
// Accounts tab: bank accounts, statement import, the column mapper
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// The 4,964-line page was the reason small changes went unreviewed; each tab
// is its own file now. Behaviour here is unchanged by the move.

import { useEffect, useState, useCallback, useRef } from "react";
import { Plus, RefreshCw, Upload, CheckCircle, X, FileText, Pencil, Landmark } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";

import { getBankStatements, getBankTransactions, BankStatement, BankTransaction } from "@/lib/data/bankStatements";
import { fmt, BankAccount } from "@/components/banking/shared";

export function BankAccounts({ clientId }: { clientId: string }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  // {id: {deletable, blocked_by}} — decides whether Delete is offered at all,
  // and what the disabled one says when it is not.
  const [deletability, setDeletability] = useState<Record<string, { deletable: boolean; blocked_by: string[] }>>({});
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  // null = closed, "new" = create form, BankAccount = edit that account.
  const [accountModal, setAccountModal] = useState<BankAccount | "new" | null>(null);
  const [selectedStmt, setSelectedStmt] = useState<string | null>(null);
  const [stmtTxns, setStmtTxns] = useState<BankTransaction[]>([]);
  const [txnsLoading, setTxnsLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

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
        (api.banking.bankAccountsDeletable({ client_id: clientId }) as Promise<{ success: boolean; data: Record<string, { deletable: boolean; blocked_by: string[] }> }>)
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
    if (!confirm(`Deactivate ${a.bank_name} (····${a.account_no.slice(-4)})? Existing statements and reconciliations keep it — it just won't be selectable for new imports. You can reactivate it later by editing it.`)) return;
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: false }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not deactivate the account." }); return; }
      setMsg({ type: "ok", text: "Bank account deactivated." });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not deactivate the account." }); }
  }

  async function reactivateAccount(a: BankAccount) {
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: true }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not reactivate the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} reactivated.` });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not reactivate the account." }); }
  }

  async function deleteAccount(a: BankAccount) {
    if (!confirm(`Permanently delete ${a.bank_name} (····${a.account_no.slice(-4)})?\n\n`
      + `This account has no statements, no reconciliations and nothing posted to its `
      + `ledger, so there is no history to keep. Its ledger account goes with it if `
      + `nothing else uses it. This cannot be undone.`)) return;
    try {
      const res = await api.banking.deleteBankAccount(a.id) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not delete the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} deleted.` });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not delete the account." }); }
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
                  <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(a.opening_balance_paise)}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <button onClick={() => setAccountModal(a)} className="text-[#4338CA] hover:text-[#3730A3] inline-flex items-center gap-1"><Pencil size={11} /> Edit</button>
                    {a.is_active
                      ? <button onClick={() => deactivateAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Deactivate</button>
                      : <button onClick={() => reactivateAccount(a)} className="ml-3 text-[#059669] hover:text-[#047857]">Reactivate</button>}
                    {/* Delete is offered only for an account with no footprint.
                        When it is blocked the button stays, disabled, carrying the
                        reason — "why can't I delete this?" is the question a
                        missing button leaves unanswered. */}
                    {deletability[a.id]?.deletable ? (
                      <button onClick={() => deleteAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Delete</button>
                    ) : deletability[a.id] ? (
                      <span className="ml-3 text-[#CBD5E1] cursor-not-allowed"
                            title={`Cannot be deleted because ${deletability[a.id].blocked_by.join("; ")}. Deactivate it instead — that keeps its history.`}>Delete</span>
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
          onImported={() => { setShowImport(false); loadStatements(); }}
          onManageAccounts={() => { setShowImport(false); setAccountModal("new"); }}
        />
      )}
      {accountModal && (
        <BankAccountModal
          clientId={clientId}
          account={accountModal === "new" ? null : accountModal}
          onClose={() => setAccountModal(null)}
          onSaved={() => { setAccountModal(null); setMsg({ type: "ok", text: "Bank account saved." }); loadStatements(); }}
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

interface CoaAccountLite { id: string; account_code: string; account_name: string; account_type: string }

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
      // Only Asset accounts can be a bank's GL account (Bank/Cash sit under Assets).
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .eq("account_type", "Asset")
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
              <label className={labelCls}>Opening Balance Date</label>
              <input type="date" value={openingDate} onChange={(e) => setOpeningDate(e.target.value)} className={inputCls} />
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
  const [result, setResult] = useState<{ imported: number; duplicates_skipped: number; total_rows: number } | null>(null);
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

  const account = accounts.find((a) => a.id === accountId);

  function resetMapping() {
    setMapping(null); setInspected(null); setPreview(null); setOverrideBalance(false);
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) { setFile(f); setError(null); setResult(null); resetMapping(); }
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
    if (!file) { setError("Select a statement file (.csv or .xlsx)."); return; }
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
      const res = (await api.banking.uploadStatement(form)) as {
        success: boolean; data: { imported: number; duplicates_skipped: number; total_rows: number }; error?: string;
      };
      if (!res.success) { setError(res.error ?? "Import failed."); setImporting(false); return; }
      setResult(res.data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Import failed";
      setError(message);
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
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>

        {result ? (
          <>
            <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-center space-y-1">
              <CheckCircle size={20} className="text-green-600 mx-auto" />
              <p className="text-sm font-medium text-green-700">{result.imported} transaction{result.imported === 1 ? "" : "s"} imported</p>
              {result.duplicates_skipped > 0 && (
                <p className="text-xs text-green-600">{result.duplicates_skipped} duplicate{result.duplicates_skipped === 1 ? "" : "s"} skipped (already imported)</p>
              )}
            </div>
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
                <label className="block text-xs font-medium text-[#475569] mb-1">Statement File * <span className="font-normal text-[#94A3B8]">(.csv or .xlsx)</span></label>
                <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx" onChange={handleFile} className="hidden" />
                <button onClick={() => fileRef.current?.click()} className="w-full border-2 border-dashed border-[#E2E8F0] rounded-lg py-4 text-sm text-[#64748B] hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center gap-2">
                  <Upload size={16} /> {file ? file.name : "Click to select a statement file"}
                </button>
                <p className="text-[10px] text-[#94A3B8] mt-1">The file is parsed on the server — HDFC / SBI / ICICI / Axis are auto-detected. Any other bank: use <span className="font-medium">Map columns</span> once and we&apos;ll remember it. Amounts stay exact.</p>
              </div>
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
                  <button onClick={runPreview} disabled={checking}
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

            {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
            <div className="flex gap-3 justify-end">
              <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
              {!inspected && file && (
                <button onClick={startMapping} disabled={checking || !account}
                        className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">
                  {checking ? "Reading…" : "Map columns"}
                </button>
              )}
              <button
                onClick={handleImport}
                disabled={
                  importing || !file || accounts.length === 0
                  // With the mapper open, importing is gated on a check having
                  // been run: the preview IS the safety argument for skipping
                  // the column-label validation, so importing without it would
                  // give up the guard and gain nothing.
                  || (!!inspected && !preview)
                  || (!!preview && preview.balance_check.agrees === false && !overrideBalance)
                }
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
              >
                {importing ? "Importing…" : "Import"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

