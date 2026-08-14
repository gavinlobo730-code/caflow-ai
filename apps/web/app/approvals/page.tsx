"use client";

import { useState, useEffect, useCallback } from "react";
import { ShieldCheck, Check, X, Clock, Loader2, Ban, Lock } from "lucide-react";
import Link from "next/link";
import { api, type ApprovalRequest } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { ListSkeleton } from "@/components/ui/skeleton";

function isMfaError(msg: string) {
  return msg.toLowerCase().includes("multi-factor") || msg.toLowerCase().includes("mfa");
}

// Module 9.0 M4 — Governance Approval Inbox (maker-checker).
// Partners approve/reject; everyone with access sees pending + history.
const STATUS_STYLE: Record<string, string> = {
  pending: "bg-amber-50 text-amber-700",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
  cancelled: "bg-gray-100 text-gray-500",
};

export default function ApprovalsPage() {
  // Maker/checker, read off the matrix instead of restated as a role:
  //   approval:approve = Partner only (the checker)
  //   approval:request = Executive and up (the maker, who may also cancel)
  // Splitting them fixes the Reviewer case — Reviewer held neither, but the old
  // `!isPartner` branch still offered them Cancel, which the API answers 403.
  const { can } = usePermissions();
  const canApprove = can("approval", "approve");
  const canRequest = can("approval", "request");

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

      {error && (isMfaError(error) ? (
        <div className="flex flex-col items-center gap-3 py-14 text-center">
          <div className="w-12 h-12 rounded-full bg-amber-50 flex items-center justify-center">
            <Lock size={20} className="text-amber-600" />
          </div>
          <div>
            <p className="text-[14px] font-semibold text-[#182350]">Multi-factor authentication required</p>
            <p className="text-[12px] text-gray-500 mt-1 max-w-xs mx-auto">
              This area contains sensitive approval workflows. Enable MFA to continue.
            </p>
          </div>
          <Link
            href="/settings/security"
            className="mt-1 px-4 py-2 rounded-lg bg-[#182350] text-white text-[12.5px] font-medium hover:bg-[#1e2d5e] transition-colors"
          >
            Set Up MFA
          </Link>
        </div>
      ) : (
        <div className="text-[12px] text-red-600 mb-3">{error}</div>
      ))}

      {!error && loading ? (
        <ListSkeleton rows={4} />
      ) : !error && items.length === 0 ? (
        <div className="py-12 text-center text-[12px] text-gray-400">
          <Clock size={22} className="mx-auto mb-2 opacity-40" />
          No {tab} approvals.
        </div>
      ) : !error ? (
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
                {r.status === "pending" && canApprove && (
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
                {r.status === "pending" && !canApprove && canRequest && (
                  <button disabled={busy === r.id} onClick={() => act(r.id, "cancel")}
                    className="flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 disabled:opacity-60">
                    <Ban size={12} /> Cancel
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
