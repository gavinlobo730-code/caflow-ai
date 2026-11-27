"use client";

import { useState, useEffect, useCallback } from "react";
import { ShieldCheck, Check, X, Clock, Loader2, Ban, Lock } from "lucide-react";
import Link from "next/link";
import { api, type ApprovalRequest } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { ListSkeleton } from "@/components/ui/skeleton";
import { MFA_SETUP_HREF, isMfaRefusal } from "@/lib/auth/mfaRefusal";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { confirmDialog, promptDialog } from "@/components/ui/confirm-dialog";
import { AUTHENTICATOR_RESET, askedWithText } from "@/lib/auth/authenticatorReset";
import { formatRelativeTime } from "@/lib/services/formatting";
import { pageFrameClass } from "@/components/ui/page-frame";
import { ACCESS_REQUEST } from "@/lib/access/accessRequest";
import { pairWords } from "@/lib/access/permissionGroups";

// Module 9.0 M4 — Governance Approval Inbox (maker-checker).
// Partners approve/reject; everyone with access sees pending + history.
const STATUS_STYLE: Record<string, string> = {
  pending: "bg-state-attention-surface text-state-attention",
  approved: "bg-state-ready-surface text-state-ready",
  rejected: "bg-state-problem-surface text-state-problem",
  cancelled: "bg-state-done-surface text-state-done",
};

/** The permission a request for access asks for, in a person's words ("See payroll"), from the pair the server stored. */
function accessWords(r: ApprovalRequest): string {
  const resource = typeof r.payload?.resource === "string" ? r.payload.resource : "";
  const action = typeof r.payload?.action === "string" ? r.payload.action : "";
  return resource && action ? pairWords(resource, action) : (r.summary || "access");
}

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
  // A refused decision is shown BESIDE the list, which is reloaded: a load failure replaces the list, a refused action
  // does not.
  const [actionError, setActionError] = useState<string | null>(null);

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
    const request = items.find((x) => x.id === id);
    if (action === "approve" && request?.request_type === AUTHENTICATOR_RESET) {
      // Removing somebody's second factor cannot be taken back, and the person is only as safe as the check made here: the
      // request says WHO asked and WHY, and only a Partner can establish that it really was them. Asked before the click
      // does anything, and a "no" leaves the request exactly as it was.
      const who = typeof request.payload?.target_name === "string" ? request.payload.target_name : "this person";
      const ok = await confirmDialog({
        title: "Reset this authenticator?",
        message: `This removes every authenticator ${who} has; their next sign-in is a password and a new authenticator, though a sign-in they already have open may carry on until it expires. Approve only after you have confirmed with ${who}, by a call or in person, that they asked for it.`,
        confirmLabel: "Reset authenticator",
        danger: true,
      });
      if (!ok) return;
    }
    if (action === "approve" && request?.request_type === ACCESS_REQUEST) {
      // An approval switches the permission on at once, so the Partner is told in a person's words what it is and for whom
      // before the click does anything. A "no" leaves the request exactly as it was.
      const who = typeof request.payload?.user_name === "string" ? request.payload.user_name : "this person";
      const what = accessWords(request);
      const ok = await confirmDialog({
        title: "Give this access?",
        message: `${who} will be allowed to: ${what}. It takes effect straight away and is recorded in the audit log. You can take it back at any time from Team, under Permissions.`,
        confirmLabel: "Give access",
      });
      if (!ok) return;
    }
    // A declined request for access tells the asker the reason given, so the Partner is asked for one (it may be left
    // empty) and whatever they typed is what is sent: a stock phrase would be shown to the asker as a Partner's own words.
    let declineReason: string | undefined = "Rejected by Partner";
    if (action === "reject" && request?.request_type === ACCESS_REQUEST) {
      const who = typeof request.payload?.user_name === "string" ? request.payload.user_name : "The person who asked";
      const typed = await promptDialog({
        title: "Decline this request?",
        message: `${who} is told it was declined, with the reason you give here. You can leave the reason empty.`,
        label: "Reason (optional)",
        confirmLabel: "Decline",
        multiline: true,
      });
      if (typed === null) return;
      declineReason = typed.trim() || undefined;
    }
    setBusy(id); setError(null); setActionError(null);
    try {
      if (action === "approve") await api.approvals.approve(id);
      else if (action === "reject") await api.approvals.reject(id, declineReason);
      else await api.approvals.cancel(id);
      await load();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Action failed";
      // Show the list as it is NOW: a refused decision (somebody else decided first, or the action failed and the
      // request is back to pending) leaves the page showing a stale row otherwise. A refusal to sign in without a second
      // factor keeps its own panel.
      await load();
      if (isMfaRefusal(message)) setError(message);
      else setActionError(message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={pageFrameClass("data")}>
      <PageHeader
        icon={<ShieldCheck size={18} className="text-brand" />}
        title="Approvals"
        subtitle="Requests wait here for someone who may approve them: a member of staff asking for access to a part of the product, or a request to reset a lost authenticator app. Every decision is recorded in the audit log."
        className="mb-4"
      />

      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {(["pending", "history"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setActionError(null); }}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px capitalize ${
              tab === t ? "border-brand text-brand" : "border-transparent text-gray-500"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {error && (isMfaRefusal(error) ? (
        <div className="flex flex-col items-center gap-3 py-14 text-center">
          <div className="w-12 h-12 rounded-full bg-state-attention-surface flex items-center justify-center">
            <Lock size={20} className="text-amber-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-brand">Set up your authenticator app</p>
            <p className="text-xs text-gray-500 mt-1 max-w-xs mx-auto">
              This area contains sensitive approval workflows. Add an authenticator app to continue.
            </p>
          </div>
          <Link
            href={MFA_SETUP_HREF}
            className="mt-1 px-4 py-2 rounded-lg bg-brand text-white text-xs font-medium hover:bg-brand-dark transition-colors"
          >
            Set Up MFA
          </Link>
        </div>
      ) : (
        <div className="text-xs text-red-600 mb-3">{error}</div>
      ))}

      {actionError && <div role="alert" className="text-xs text-state-problem mb-3">{actionError}</div>}

      {!error && loading ? (
        <ListSkeleton rows={4} />
      ) : !error && items.length === 0 ? (
        <div className="py-12 text-center text-xs text-ps-hint">
          <Clock size={22} className="mx-auto mb-2 opacity-40" />
          No {tab} approvals.
        </div>
      ) : !error ? (
        <div className="space-y-2">
          {items.map((r) => (
            // On a phone the request's words take the row and its actions wrap under them; side by side the summary was squeezed
            // to its first few letters (POST-A-131).
            <div key={r.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 flex-1 basis-56">
                <p className="text-sm font-medium text-brand truncate">
                  {r.request_type === ACCESS_REQUEST && typeof r.payload?.user_name === "string"
                    ? `${r.payload.user_name} asks to: ${accessWords(r)}`
                    : r.summary || r.request_type}
                </p>
                <p className="text-2xs text-ps-hint mt-0.5 break-words">
                  <span className="font-mono">{r.request_type}</span>
                  {r.requested_by_email ? ` · by ${r.requested_by_email}` : ""}
                  {r.reason ? ` · ${r.reason}` : ""}
                </p>
                {r.request_type === ACCESS_REQUEST && (
                  <p className="text-2xs text-gray-500 mt-0.5 break-words" data-access-request-detail>
                    {typeof r.payload?.user_role === "string" ? `${r.payload.user_role}. ` : ""}
                    {typeof r.payload?.asked_from === "string" && r.payload.asked_from ? `Asked from the ${r.payload.asked_from} screen. ` : ""}
                    {typeof r.payload?.note === "string" && r.payload.note ? `Their note: ${r.payload.note}` : "No note given."}
                  </p>
                )}
                {r.request_type === AUTHENTICATOR_RESET && typeof r.payload?.reason === "string" && (
                  <p className="text-2xs text-gray-500 mt-0.5">Reason given: {r.payload.reason}</p>
                )}
                {r.request_type === AUTHENTICATOR_RESET && r.status === "pending" && (
                  <p className="text-2xs text-gray-500 mt-0.5">
                    {r.created_at ? `Asked ${formatRelativeTime(r.created_at)}. ` : ""}{askedWithText(r.payload?.asker_aal)}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-2xs px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_STYLE[r.status] ?? ""}`}>
                  {r.status}
                </span>
                {r.status === "pending" && canApprove && (
                  <>
                    <Button variant="plain" size="none" spinner={false} disabled={busy === r.id} onClick={() => act(r.id, "approve")}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-brand text-white disabled:opacity-60">
                      {busy === r.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Approve
                    </Button>
                    <Button variant="plain" size="none" disabled={busy === r.id} onClick={() => act(r.id, "reject")}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 disabled:opacity-60">
                      <X size={12} /> Reject
                    </Button>
                  </>
                )}
                {r.status === "pending" && !canApprove && canRequest && (
                  <Button variant="plain" size="none" disabled={busy === r.id} onClick={() => act(r.id, "cancel")}
                    className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 disabled:opacity-60">
                    <Ban size={12} /> Cancel
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
