"use client";

/** Record a payroll disbursement — the bank account the salaries left, the
 *  date, and the reference.
 *
 *  Shared by the firm rail and the client month's Release tab. It writes the
 *  payment journal, so a second copy of it is a second way to post real money. */

import { useState, useEffect } from "react";
import { X } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { toLocalISO } from "@/lib/dateMath";
import { fmtRs } from "@/components/payroll/shared";

/** Only what the modal actually needs. Narrower than the pages' own PayrollRun
 *  types, deliberately: a shared component that demanded every column would
 *  force both callers to carry fields neither of them reads. */
type DisbursableRun = {
  id: string;
  client_id: string;
  month: string;
  total_net_paise?: number;
};

/** Only an ACTIVE account with a linked ledger can post the payment journal. */
type DisburseBankAccount = {
  id: string; bank_name: string; account_no: string;
  coa_account_id: string | null; is_active: boolean;
};


export function DisburseModal({ run, onClose, onDone }: {
  run: DisbursableRun; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [accounts, setAccounts] = useState<DisburseBankAccount[]>([]);
  const [loadingAccts, setLoadingAccts] = useState(true);
  const [accountId, setAccountId] = useState("");
  const [payDate, setPayDate] = useState(() => toLocalISO(new Date()).slice(0, 10));
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.banking.listBankAccounts({ client_id: run.client_id }) as ApiResp<DisburseBankAccount[]>;
        // Only active accounts with a linked ledger account can post the journal.
        const linked = (res.data ?? []).filter((a) => a.is_active && a.coa_account_id);
        setAccounts(linked);
        setAccountId(linked[0]?.id ?? "");
      } catch { setAccounts([]); }
      setLoadingAccts(false);
    })();
  }, [run.client_id]);

  async function save() {
    if (!accountId) { setError("Select a bank account."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.payroll.disburseRun(run.id, {
        bank_account_id: accountId,
        payment_date: payDate || undefined,
        payment_reference: reference.trim() || undefined,
      }) as ApiResp<unknown>;
      if (!res.success) { setError(res.error ?? "Could not record the disbursement."); return; }
      onDone(`Payroll for ${run.month} marked paid.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the disbursement.");
    } finally {
      setSaving(false);
    }
  }

  const netStr = run.total_net_paise != null ? fmtRs(run.total_net_paise) : "—";
  const inputCls = "w-full border rounded-lg px-3 py-2 text-sm";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Mark Payroll Paid — {run.month}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="bg-[#F8FAFC] rounded-lg px-3 py-2 text-xs text-[#475569]">
          Posts <span className="font-medium">Dr Net Salary Payable / Cr Bank</span> for the net pay
          <span className="font-mono"> {netStr}</span>, clearing the payable raised at finalization.
        </div>
        {loadingAccts ? (
          <p className="text-sm text-[#64748B]">Loading bank accounts…</p>
        ) : accounts.length === 0 ? (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            No bank account is linked to a ledger account for this client. Add one under
            Accounting → Bank (with a Ledger Account link) before disbursing salaries.
          </div>
        ) : (
          <>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Pay from bank account *</label>
              <select value={accountId} onChange={(e) => setAccountId(e.target.value)} className={inputCls}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} · ····{a.account_no.slice(-4)}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Payment date</label>
                <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Reference</label>
                <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="NEFT / UTR no." className={inputCls} />
              </div>
            </div>
          </>
        )}
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving || loadingAccts || accounts.length === 0} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Recording…" : "Confirm Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}
