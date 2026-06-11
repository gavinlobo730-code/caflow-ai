"use client";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Plus, X, Loader2 } from "lucide-react";
import { yearEndApi, type Adjustment, type AdjustmentType, type AdjustmentStatus } from "@/lib/api/yearEnd";

/** Format paise → ₹ Indian number format */
function fmt(paise: number): string {
  if (paise === 0) return "₹0";
  return (
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(paise / 100)
  );
}

const TYPE_LABELS: Record<AdjustmentType, string> = {
  accrual: "Accrual",
  prepayment: "Prepayment",
  provision: "Provision",
  reclassification: "Reclassification",
  depreciation_adj: "Depreciation Adj",
  manual: "Manual",
};

const TYPE_BADGE: Record<AdjustmentType, string> = {
  accrual: "bg-blue-100 text-blue-700",
  prepayment: "bg-purple-100 text-purple-700",
  provision: "bg-orange-100 text-orange-700",
  reclassification: "bg-cyan-100 text-cyan-700",
  depreciation_adj: "bg-red-100 text-red-700",
  manual: "bg-[#F1F5F9] text-[#475569]",
};

const STATUS_BADGE: Record<AdjustmentStatus, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  submitted: "bg-amber-100 text-amber-700",
  approved: "bg-green-100 text-green-700",
  posted: "bg-blue-100 text-blue-700",
};

const STATUS_LABEL: Record<AdjustmentStatus, string> = {
  draft: "Draft",
  submitted: "Pending Review",
  approved: "Approved",
  posted: "Posted",
};

const ADJ_TYPES: AdjustmentType[] = [
  "accrual", "prepayment", "provision", "reclassification", "depreciation_adj", "manual",
];

export default function AdjustmentsPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await yearEndApi.adjustments.list(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to load");
      setAdjustments(res.data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, ok: boolean) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 4000);
  }

  async function handleAction(adjId: string, action: "submit" | "approve" | "post") {
    setActionId(adjId);
    try {
      let res;
      if (action === "submit") res = await yearEndApi.adjustments.submit(engagementId, adjId);
      else if (action === "approve") res = await yearEndApi.adjustments.approve(engagementId, adjId);
      else res = await yearEndApi.adjustments.post(engagementId, adjId);
      if (!res.success) throw new Error(res.error ?? "Action failed");
      setAdjustments((prev) => prev.map((a) => (a.id === adjId ? res.data : a)));
      showToast("Action completed successfully", true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Action failed", false);
    } finally {
      setActionId(null);
    }
  }

  const totalPaise = adjustments.reduce((s, a) => s + a.amount_paise, 0);

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-14 rounded-xl bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      {toast && (
        <div className={`rounded-lg px-4 py-3 text-xs font-medium border ${toast.ok ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-700"}`}>
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {adjustments.length} adjustment{adjustments.length !== 1 ? "s" : ""}
          {adjustments.length > 0 && <span className="text-[#94A3B8] font-normal"> · Total {fmt(totalPaise)}</span>}
        </p>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
        >
          <Plus size={12} /> New Adjustment
        </button>
      </div>

      {/* New Adjustment Form */}
      {showForm && (
        <AdjustmentForm
          engagementId={engagementId}
          onSaved={(adj) => {
            setAdjustments((prev) => [adj, ...prev]);
            setShowForm(false);
            showToast("Adjustment created", true);
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Table */}
      {adjustments.length > 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-left font-semibold">Description</th>
                  <th className="px-3 py-3 text-left font-semibold">Debit</th>
                  <th className="px-3 py-3 text-left font-semibold">Credit</th>
                  <th className="px-3 py-3 text-right font-semibold">Amount</th>
                  <th className="px-3 py-3 text-left font-semibold">Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {adjustments.map((adj) => (
                  <tr key={adj.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5">
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${TYPE_BADGE[adj.type]}`}>
                        {TYPE_LABELS[adj.type]}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-[#334155] max-w-[180px] truncate">{adj.description}</td>
                    <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">
                      {adj.debit_account_name ?? adj.debit_account_id}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">
                      {adj.credit_account_name ?? adj.credit_account_id}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#0F172A]">
                      {fmt(adj.amount_paise)}
                    </td>
                    <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">{adj.adj_date}</td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${STATUS_BADGE[adj.status]}`}>
                        {STATUS_LABEL[adj.status]}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      {actionId === adj.id ? (
                        <Loader2 size={12} className="animate-spin text-[#94A3B8]" />
                      ) : (
                        <AdjActions adj={adj} onAction={(a) => handleAction(adj.id, a)} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : !showForm ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-14">
          <p className="text-sm text-[#64748B]">No adjustments yet</p>
          <p className="text-xs text-[#94A3B8] mt-1">Click &quot;+ New Adjustment&quot; to create one</p>
        </div>
      ) : null}

      {/* Register totals */}
      {adjustments.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-4 py-3">
          <p className="text-xs font-semibold text-[#334155] mb-2">Adjustment Register — Totals</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <RegisterTotal label="Total" value={fmt(totalPaise)} />
            <RegisterTotal label="Draft" value={fmt(adjustments.filter((a) => a.status === "draft").reduce((s, a) => s + a.amount_paise, 0))} />
            <RegisterTotal label="Pending Review" value={fmt(adjustments.filter((a) => a.status === "submitted").reduce((s, a) => s + a.amount_paise, 0))} />
            <RegisterTotal label="Posted" value={fmt(adjustments.filter((a) => a.status === "posted").reduce((s, a) => s + a.amount_paise, 0))} />
          </div>
        </div>
      )}
    </div>
  );
}

function RegisterTotal({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-[#94A3B8]">{label}</p>
      <p className="text-sm font-semibold text-[#0F172A] font-mono">{value}</p>
    </div>
  );
}

function AdjActions({
  adj,
  onAction,
}: {
  adj: Adjustment;
  onAction: (action: "submit" | "approve" | "post") => void;
}) {
  if (adj.status === "draft") {
    return (
      <button onClick={() => onAction("submit")} className="text-xs text-blue-600 hover:underline">
        Submit
      </button>
    );
  }
  if (adj.status === "submitted") {
    return (
      <button onClick={() => onAction("approve")} className="text-xs text-green-600 hover:underline">
        Approve
      </button>
    );
  }
  if (adj.status === "approved") {
    return (
      <button onClick={() => onAction("post")} className="text-xs text-blue-600 hover:underline">
        Post to Journal
      </button>
    );
  }
  return <span className="text-[10px] text-[#94A3B8]">—</span>;
}

// ── New Adjustment Form ────────────────────────────────────────────────────

function AdjustmentForm({
  engagementId,
  onSaved,
  onCancel,
}: {
  engagementId: string;
  onSaved: (adj: Adjustment) => void;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [type, setType] = useState<AdjustmentType>("accrual");
  const [description, setDescription] = useState("");
  const [debitAccount, setDebitAccount] = useState("");
  const [creditAccount, setCreditAccount] = useState("");
  const [amountStr, setAmountStr] = useState("");
  const [adjDate, setAdjDate] = useState(today);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!description.trim()) { setError("Description is required"); return; }
    if (!debitAccount.trim()) { setError("Debit account is required"); return; }
    if (!creditAccount.trim()) { setError("Credit account is required"); return; }
    const amountRupees = parseFloat(amountStr || "0");
    if (amountRupees <= 0) { setError("Amount must be greater than zero"); return; }
    // All monetary amounts stored in paise — multiply by 100 (integer arithmetic)
    const amount_paise = Math.round(amountRupees * 100);
    if (!adjDate) { setError("Date is required"); return; }

    setSaving(true);
    setError(null);
    try {
      const res = await yearEndApi.adjustments.create(engagementId, {
        type,
        description: description.trim(),
        debit_account_id: debitAccount.trim(),
        credit_account_id: creditAccount.trim(),
        amount_paise,
        adj_date: adjDate,
        notes: notes.trim() || undefined,
      });
      if (!res.success) throw new Error(res.error ?? "Failed to create adjustment");
      onSaved(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">New Year-End Adjustment</h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]">
          <X size={16} />
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Type *</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as AdjustmentType)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {ADJ_TYPES.map((t) => (
              <option key={t} value={t}>{TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-[#475569] mb-1">Description *</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Accrual for outstanding salary — March"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Debit Account *</label>
          <input
            value={debitAccount}
            onChange={(e) => setDebitAccount(e.target.value)}
            placeholder="e.g. 5001 / Salary Expense"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Credit Account *</label>
          <input
            value={creditAccount}
            onChange={(e) => setCreditAccount(e.target.value)}
            placeholder="e.g. 2001 / Salary Payable"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Amount (₹) *</label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amountStr}
            onChange={(e) => setAmountStr(e.target.value)}
            placeholder="0.00"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
          <input
            type="date"
            value={adjDate}
            onChange={(e) => setAdjDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="col-span-2 lg:col-span-3">
          <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional supporting notes"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-3 justify-end">
        <button
          onClick={onCancel}
          className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
        >
          {saving && <Loader2 size={12} className="animate-spin" />}
          {saving ? "Saving…" : "Create Adjustment"}
        </button>
      </div>
    </div>
  );
}
