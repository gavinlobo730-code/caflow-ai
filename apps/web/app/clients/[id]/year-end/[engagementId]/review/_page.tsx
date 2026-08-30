"use client";

import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, Circle, User, Loader2 } from "lucide-react";
import { yearEndApi, type ReviewStep, type ReviewHistory, type ReviewStatus } from "@/lib/api/yearEnd";
import { Skeleton, FormSkeleton, TimelineSkeleton } from "@/components/ui/skeleton";
import { useEngagementId } from "../_engagementId";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const STEP_LABELS: Record<string, string> = {
  prepared: "Prepared",
  reviewed: "Reviewed",
  approved: "Approved / Locked",
};

const ACTION_BADGE: Record<string, string> = {
  submitted: "bg-amber-100 text-amber-700",
  approved: "bg-green-100 text-green-700",
  revision_requested: "bg-red-100 text-red-700",
  final_approved: "bg-blue-100 text-blue-700",
  locked: "bg-blue-100 text-blue-700",
};

interface ReviewData {
  steps: ReviewStep[];
  history: ReviewHistory[];
}

export default function ReviewPage() {
  // window.location, not useParams(): on the deployed static export every
  // dynamic segment is "_placeholder" (see ../_engagementId.ts).
  const engagementId = useEngagementId();

  const [reviewData, setReviewData] = useState<ReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comment, setComment] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ msg: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await yearEndApi.review.get(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to load review");
      setReviewData(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  async function doAction(action: "submit" | "approve" | "requestRevision" | "finalApprove") {
    setActionLoading(action);
    setActionMsg(null);
    try {
      const c = comment.trim() || undefined;
      let res;
      if (action === "submit") res = await yearEndApi.review.submitForReview(engagementId, c);
      else if (action === "approve") res = await yearEndApi.review.approve(engagementId, c);
      else if (action === "requestRevision") res = await yearEndApi.review.requestRevision(engagementId, c);
      else res = await yearEndApi.review.finalApprove(engagementId, c);
      if (!res.success) throw new Error(res.error ?? "Action failed");
      setComment("");
      setActionMsg({ msg: "Action completed successfully.", ok: true });
      await load();
    } catch (err) {
      setActionMsg({ msg: err instanceof Error ? err.message : "Action failed", ok: false });
    } finally {
      setActionLoading(null);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-5 max-w-2xl">
        {/* Three-step timeline placeholder */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5">
          <Skeleton className="h-3 w-32 mb-4" />
          <div className="flex items-start gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex-1 flex flex-col items-center gap-2">
                <Skeleton className="h-8 w-8 rounded-full" />
                <Skeleton className="h-2.5 w-16" />
              </div>
            ))}
          </div>
        </div>
        {/* Action panel placeholder */}
        <FormSkeleton fields={1} className="bg-white rounded-xl border border-[#F1F5F9] p-5" />
        {/* Review history placeholder */}
        <TimelineSkeleton rows={3} className="bg-white rounded-xl border border-[#F1F5F9] p-5" />
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

  if (!reviewData) return null;

  const { steps, history } = reviewData;

  // Determine current status from history
  const latestHistory = history[0];
  const currentStatus: ReviewStatus = (latestHistory?.to_status ?? "draft") as ReviewStatus;

  return (
    <div className="p-6 space-y-5 max-w-2xl">

      {/* Three-step timeline */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5">
        <p className="text-xs font-semibold text-[#334155] mb-4">Review Timeline</p>
        <div className="flex items-start gap-0 relative">
          {(["prepared", "reviewed", "approved"] as const).map((stepKey, idx) => {
            const step = steps.find((s) => s.step === stepKey);
            const done = !!step?.completed_at;
            return (
              <div key={stepKey} className="flex-1 flex flex-col items-center relative">
                {/* Connector line */}
                {idx < 2 && (
                  <div className={`absolute top-4 left-1/2 w-full h-0.5 ${done ? "bg-green-400" : "bg-[#E2E8F0]"}`} />
                )}
                {/* Icon */}
                <div className={`w-8 h-8 rounded-full flex items-center justify-center z-10 border-2 ${
                  done
                    ? "bg-green-100 border-green-400"
                    : "bg-white border-[#E2E8F0]"
                }`}>
                  {done ? (
                    <CheckCircle2 size={14} className="text-green-600" />
                  ) : (
                    <Circle size={14} className="text-[#CBD5E1]" />
                  )}
                </div>
                {/* Label */}
                <div className="mt-2 text-center px-1">
                  <p className="text-[10px] font-semibold text-[#334155]">{STEP_LABELS[stepKey]}</p>
                  {done && step ? (
                    <>
                      <p className="text-[10px] text-[#475569] mt-0.5">{step.user_name ?? "—"}</p>
                      {step.user_role && <p className="text-[10px] text-[#94A3B8]">{step.user_role}</p>}
                      {step.completed_at && (
                        <p className="text-[10px] text-[#94A3B8]">{timeAgo(step.completed_at)}</p>
                      )}
                      {step.comment && (
                        <p className="text-[10px] text-[#64748B] mt-1 italic max-w-[100px] mx-auto truncate" title={step.comment}>
                          &quot;{step.comment}&quot;
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-[10px] text-[#CBD5E1] mt-0.5">Pending</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Action panel */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-3">
        <p className="text-xs font-semibold text-[#334155]">Your Action</p>

        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Comment (optional)</label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
            placeholder="Add a comment for the reviewer…"
            className="w-full text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        {actionMsg && (
          <div className={`rounded-lg px-4 py-2 text-xs font-medium ${actionMsg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {actionMsg.msg}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {/* Submit for Review — available in draft */}
          {currentStatus === "draft" && (
            <ActionButton
              label="Submit for Review"
              action={() => doAction("submit")}
              loading={actionLoading === "submit"}
              variant="primary"
            />
          )}

          {/* Approve — available in_review */}
          {currentStatus === "in_review" && (
            <>
              <ActionButton
                label="Approve"
                action={() => doAction("approve")}
                loading={actionLoading === "approve"}
                variant="success"
              />
              <ActionButton
                label="Request Revision"
                action={() => doAction("requestRevision")}
                loading={actionLoading === "requestRevision"}
                variant="danger"
              />
            </>
          )}

          {/* Final Approve & Lock — available in approved */}
          {currentStatus === "approved" && (
            <ActionButton
              label="Final Approve & Lock"
              action={() => doAction("finalApprove")}
              loading={actionLoading === "finalApprove"}
              variant="primary"
            />
          )}

          {currentStatus === "locked" && (
            <p className="text-xs text-[#64748B] py-2">This engagement is locked. No further actions available.</p>
          )}
        </div>
      </div>

      {/* Review history */}
      {history.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F8FAFC]">
            <p className="text-xs font-semibold text-[#334155]">Review History</p>
          </div>
          <div className="divide-y divide-[#F8FAFC]">
            {history.map((h) => (
              <div key={h.id} className="px-4 py-3 flex items-start gap-3">
                <div className="w-6 h-6 rounded-full bg-[#F1F5F9] flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User size={10} className="text-[#64748B]" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-xs font-medium text-[#334155]">{h.performed_by}</p>
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${ACTION_BADGE[h.action] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                      {h.action.replace(/_/g, " ")}
                    </span>
                    <span className="text-[10px] text-[#94A3B8]">{timeAgo(h.performed_at)}</span>
                  </div>
                  {h.comment && (
                    <p className="text-[10px] text-[#64748B] mt-0.5 italic">&quot;{h.comment}&quot;</p>
                  )}
                  {h.from_status && (
                    <p className="text-[10px] text-[#CBD5E1] mt-0.5">
                      {h.from_status} → {h.to_status}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ActionButton({
  label,
  action,
  loading,
  variant,
}: {
  label: string;
  action: () => void;
  loading: boolean;
  variant: "primary" | "success" | "danger";
}) {
  const styles = {
    primary: "bg-blue-600 text-white hover:bg-blue-700",
    success: "bg-green-600 text-white hover:bg-green-700",
    danger: "bg-red-100 text-red-700 hover:bg-red-200 border border-red-200",
  };

  return (
    <button
      onClick={action}
      disabled={loading}
      className={`flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg disabled:opacity-50 ${styles[variant]}`}
    >
      {loading && <Loader2 size={11} className="animate-spin" />}
      {label}
    </button>
  );
}
