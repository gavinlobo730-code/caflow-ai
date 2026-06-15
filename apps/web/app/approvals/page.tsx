"use client";

import { useState, useEffect, useCallback } from "react";
import { ShieldCheck, Check, X, Clock, Loader2, Ban } from "lucide-react";
import { api, type ApprovalRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";

// Module 9.0 M4 — Governance Approval Inbox (maker-checker).
// Partners approve/reject; everyone with access sees pending + history.
const STATUS_STYLE: Record<string, string> = {
  pending: "bg-amber-50 text-amber-700",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
  cancelled: "bg-gray-100 text-gray-500",
};

export default function ApprovalsPage() {
  const { userRole } = useAuth();
  const isPartner = userRole === "Partner";

  const [tab, setTab] = useState<"pending" | "history">("pending");
  const [items, setItems] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.approvals.list(tab === "pending" ? "pending" : undefined);
      let rows = r.data?.requests ?? [];
      if (tab === "history") rows = rows.filter((x) => x.status !== "pending");
      setItems(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  async function act(id: string, action: "approve" | "reject" | "cancel") {
    setBusy(id); setError(null);
    try {
      if (action === "approve") await api.approvals.approve(id);
      else if (action === "reject") await api.approvals.reject(id, "Rejected by Partner");
      else await api.approvals.cancel(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center gap-2 mb-1">
        <ShieldCheck size={18} className="text-[#182350]" />
        <h1 className="text-lg font-semibold text-[#182350]">Approvals</h1>
      </div>
      <p className="text-[12px] text-gray-500 mb-4">
        Sensitive actions (user &amp; role changes, client assignments, master Chart-of-Accounts changes)
        require Partner approval. Every decision is recorded in the audit log.
      </p>

      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {(["pending", "history"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-[13px] font-medium border-b-2 -mb-px capitalize ${
              tab === t ? "border-[#182350] text-[#182350]" : "border-transparent text-gray-500"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {error && <div className="text-[12px] text-red-600 mb-3">{error}</div>}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : items.length === 0 ? (
        <div className="py-12 text-center text-[12px] text-gray-400">
          <Clock size={22} className="mx-auto mb-2 opacity-40" />
          No {tab} approvals.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((r) => (
            <div key={r.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-[#182350] truncate">{r.summary || r.request_type}</p>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  <span className="font-mono">{r.request_type}</span>
                  {r.requested_by_email ? ` · by ${r.requested_by_email}` : ""}
                  {r.reason ? ` · ${r.reason}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_STYLE[r.status] ?? ""}`}>
                  {r.status}
                </span>
                {r.status === "pending" && isPartner && (
                  <>
                    <button disabled={busy === r.id} onClick={() => act(r.id, "approve")}
                      className="flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-lg bg-[#182350] text-white disabled:opacity-60">
                      {busy === r.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Approve
                    </button>
                    <button disabled={busy === r.id} onClick={() => act(r.id, "reject")}
                      className="flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 disabled:opacity-60">
                      <X size={12} /> Reject
                    </button>
                  </>
                )}
                {r.status === "pending" && !isPartner && (
                  <button disabled={busy === r.id} onClick={() => act(r.id, "cancel")}
                    className="flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 disabled:opacity-60">
                    <Ban size={12} /> Cancel
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
