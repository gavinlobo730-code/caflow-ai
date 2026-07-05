"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  Circle,
  Clock,
  SkipForward,
  AlertTriangle,
  ChevronRight,
  Loader2,
  Rocket,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/services/formatting";

// ─── Types ─────────────────────────────────────────────────────────────────

type StepStatus = "pending" | "in_progress" | "done" | "skipped";
type WorkflowStatus = "pending" | "in_progress" | "completed" | "stalled";

interface ChecklistStep {
  id: string;
  workflow_id: string;
  step_number: number;
  title: string;
  description: string;
  status: StepStatus;
  notes: string | null;
  completed_at: string | null;
}

interface OnboardingWorkflow {
  id: string;
  firm_id: string;
  client_id: string;
  entity_type: string;
  status: WorkflowStatus;
  progress_pct: number;
  avg_days_for_entity_type: number;
  days_in_progress: number;
  started_at: string;
  completed_at: string | null;
  notes: string | null;
  steps: ChecklistStep[];
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

// ─── Step status config ─────────────────────────────────────────────────────

const STATUS_CONFIG: Record<StepStatus, { label: string; color: string; icon: React.ReactNode }> = {
  pending:     { label: "Pending",     color: "text-[#94A3B8]", icon: <Circle size={18} className="text-[#CBD5E1]" /> },
  in_progress: { label: "In Progress", color: "text-blue-600",  icon: <Clock size={18} className="text-blue-500" /> },
  done:        { label: "Done",        color: "text-green-700", icon: <CheckCircle2 size={18} className="text-green-600" /> },
  skipped:     { label: "Skipped",     color: "text-[#94A3B8]", icon: <SkipForward size={18} className="text-[#94A3B8]" /> },
};

// ─── Progress bar ───────────────────────────────────────────────────────────

function ProgressBar({ pct, stalled }: { pct: number; stalled: boolean }) {
  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs font-medium text-[#64748B]">Progress</span>
        <span className={`text-xs font-bold ${stalled ? "text-orange-600" : "text-[#182350]"}`}>
          {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-[#E2E8F0] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${stalled ? "bg-orange-400" : "bg-[#182350]"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Workflow card (summary list) ───────────────────────────────────────────

function WorkflowCard({
  wf,
  onSelect,
}: {
  wf: OnboardingWorkflow;
  onSelect: (wf: OnboardingWorkflow) => void;
}) {
  const stalled = wf.days_in_progress > wf.avg_days_for_entity_type * 1.5;

  return (
    <button
      onClick={() => onSelect(wf)}
      className="w-full text-left bg-white rounded-xl border border-[#E2E8F0] p-4 hover:border-[#AFD2FA] hover:shadow-sm transition-all space-y-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#0F172A]">
            Client: <span className="font-mono text-[#182350]">{wf.client_id.slice(0, 8)}…</span>
          </p>
          <p className="text-xs text-[#64748B] mt-0.5">
            {wf.entity_type} · Started {formatDate(wf.started_at)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {stalled && (
            <span className="flex items-center gap-1 text-xs font-medium text-orange-600 bg-orange-50 border border-orange-200 rounded-full px-2 py-0.5">
              <AlertTriangle size={11} /> Stalled
            </span>
          )}
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
            wf.status === "completed"
              ? "bg-green-50 text-green-700 border-green-200"
              : "bg-blue-50 text-blue-700 border-blue-200"
          }`}>
            {wf.status === "completed" ? "Completed" : "In Progress"}
          </span>
          <ChevronRight size={14} className="text-[#94A3B8]" />
        </div>
      </div>
      <ProgressBar pct={wf.progress_pct} stalled={stalled} />
      <p className="text-xs text-[#94A3B8]">
        Day {wf.days_in_progress} of ~{wf.avg_days_for_entity_type} avg
      </p>
    </button>
  );
}

// ─── Step row ───────────────────────────────────────────────────────────────

function StepRow({
  step,
  onMarkDone,
  onMarkInProgress,
  onSkip,
  saving,
}: {
  step: ChecklistStep;
  onMarkDone: (stepNumber: number) => void;
  onMarkInProgress: (stepNumber: number) => void;
  onSkip: (stepNumber: number) => void;
  saving: number | null;
}) {
  const isSaving = saving === step.step_number;
  const cfg = STATUS_CONFIG[step.status] || STATUS_CONFIG.pending;

  return (
    <div
      className={`flex items-start gap-3 p-4 rounded-xl border transition-colors ${
        step.status === "done"
          ? "bg-green-50 border-green-200"
          : step.status === "in_progress"
          ? "bg-blue-50 border-blue-200"
          : step.status === "skipped"
          ? "bg-[#F8FAFC] border-[#E2E8F0] opacity-60"
          : "bg-white border-[#E2E8F0]"
      }`}
    >
      {/* Step number + icon */}
      <div className="flex flex-col items-center gap-1 pt-0.5 shrink-0">
        <div className="w-6 h-6 rounded-full bg-[#F1F5F9] flex items-center justify-center text-[10px] font-bold text-[#64748B]">
          {step.step_number}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className={`text-sm font-semibold ${step.status === "done" ? "text-green-800 line-through" : "text-[#0F172A]"}`}>
              {step.title}
            </p>
            <p className="text-xs text-[#64748B] mt-0.5 leading-relaxed">{step.description}</p>
            {step.notes && (
              <p className="text-xs italic text-[#94A3B8] mt-1">{step.notes}</p>
            )}
            {step.completed_at && (
              <p className="text-xs text-green-600 mt-1">
                Completed {new Date(step.completed_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
              </p>
            )}
          </div>
          <div className={`shrink-0 ${cfg.color}`}>{cfg.icon}</div>
        </div>

        {/* Actions */}
        {step.status !== "done" && step.status !== "skipped" && (
          <div className="flex items-center gap-2 mt-3">
            {step.status === "pending" && (
              <button
                onClick={() => onMarkInProgress(step.step_number)}
                disabled={isSaving}
                className="text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-3 py-1.5 hover:bg-blue-100 disabled:opacity-50 transition-colors"
              >
                {isSaving ? <Loader2 size={12} className="animate-spin" /> : "Start"}
              </button>
            )}
            <button
              onClick={() => onMarkDone(step.step_number)}
              disabled={isSaving}
              className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-1.5 hover:bg-green-100 disabled:opacity-50 transition-colors"
            >
              {isSaving ? <Loader2 size={12} className="animate-spin" /> : "Mark Done"}
            </button>
            <button
              onClick={() => onSkip(step.step_number)}
              disabled={isSaving}
              className="text-xs text-[#94A3B8] hover:text-[#64748B] transition-colors"
            >
              Skip
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function OnboardingChecklistPage() {
  const [workflows, setWorkflows] = useState<OnboardingWorkflow[]>([]);
  const [selected, setSelected] = useState<OnboardingWorkflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingStep, setSavingStep] = useState<number | null>(null);
  const [goLiveLoading, setGoLiveLoading] = useState(false);
  const [goLiveError, setGoLiveError] = useState<string | null>(null);

  const fetchWorkflows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.onboarding.listActive() as ApiResponse<OnboardingWorkflow[]>;
      if (!res.success) throw new Error(res.error ?? "Failed to load onboardings");
      setWorkflows(res.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load onboardings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWorkflows();
  }, [fetchWorkflows]);

  async function refreshSelected(workflowId: string) {
    try {
      const res = await api.onboarding.get(workflowId) as ApiResponse<OnboardingWorkflow>;
      if (res.success) {
        setSelected(res.data);
        setWorkflows((prev) => prev.map((w) => w.id === workflowId ? res.data : w));
      }
    } catch {
      // Non-fatal refresh failure
    }
  }

  async function handleStepUpdate(stepNumber: number, status: StepStatus) {
    if (!selected) return;
    setSavingStep(stepNumber);
    setGoLiveError(null);
    try {
      const res = await api.onboarding.updateStep(selected.id, stepNumber, { status }) as ApiResponse<ChecklistStep>;
      if (!res.success) throw new Error(res.error ?? "Update failed");
      await refreshSelected(selected.id);
    } catch (e) {
      setGoLiveError(e instanceof Error ? e.message : "Step update failed");
    } finally {
      setSavingStep(null);
    }
  }

  async function handleGoLive() {
    if (!selected) return;
    setGoLiveLoading(true);
    setGoLiveError(null);
    try {
      const res = await api.onboarding.complete(selected.id) as ApiResponse<OnboardingWorkflow>;
      if (!res.success) throw new Error(res.error ?? "Go-live failed");
      setSelected(res.data);
      setWorkflows((prev) => prev.map((w) => w.id === selected.id ? res.data : w));
    } catch (e) {
      setGoLiveError(e instanceof Error ? e.message : "Go-live verification failed");
    } finally {
      setGoLiveLoading(false);
    }
  }

  const stalled = selected
    ? selected.days_in_progress > selected.avg_days_for_entity_type * 1.5
    : false;

  const allMandatoryDone = selected
    ? [1, 2, 3, 4, 5, 8, 9, 10].every((n) => {
        const s = selected.steps.find((st) => st.step_number === n);
        return s && (s.status === "done" || s.status === "skipped");
      })
    : false;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-[#94A3B8] mb-1">
            <Link href="/clients" className="hover:text-[#475569]">Clients</Link>
            <ChevronRight size={12} />
            <span>Onboarding</span>
          </div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Client Onboarding</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            10-step checklist to onboard new clients into your CA firm
          </p>
        </div>
        <button
          onClick={fetchWorkflows}
          className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] rounded-lg px-3 py-1.5 hover:bg-[#F8FAFC] transition-colors"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {selected ? (
        /* ── Detail View ──────────────────────────────────────────────── */
        <div className="space-y-4">
          {/* Back + summary */}
          <div className="flex items-start justify-between gap-3">
            <button
              onClick={() => { setSelected(null); setGoLiveError(null); }}
              className="text-sm text-[#64748B] hover:text-[#334155] transition-colors"
            >
              ← All Onboardings
            </button>
            <div className="text-right text-xs text-[#94A3B8]">
              Day {selected.days_in_progress} / ~{selected.avg_days_for_entity_type} avg days ({selected.entity_type})
            </div>
          </div>

          {/* Progress */}
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-2">
            <ProgressBar pct={selected.progress_pct} stalled={stalled} />
            {stalled && (
              <div className="flex items-center gap-2 text-sm text-orange-700 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
                <AlertTriangle size={14} />
                Onboarding is taking longer than usual ({selected.days_in_progress} days vs ~{selected.avg_days_for_entity_type} avg). Consider following up.
              </div>
            )}
            {selected.status === "completed" && (
              <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
                <CheckCircle2 size={14} />
                Client successfully onboarded and activated.
              </div>
            )}
          </div>

          {/* Steps */}
          <div className="space-y-2">
            {selected.steps.map((step) => (
              <StepRow
                key={step.id || step.step_number}
                step={step}
                onMarkDone={(n) => handleStepUpdate(n, "done")}
                onMarkInProgress={(n) => handleStepUpdate(n, "in_progress")}
                onSkip={(n) => handleStepUpdate(n, "skipped")}
                saving={savingStep}
              />
            ))}
          </div>

          {/* Go-Live button */}
          {selected.status !== "completed" && (
            <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-[#0F172A]">Go-Live Verification</h3>
                <p className="text-xs text-[#64748B] mt-0.5">
                  Mandatory steps: 1, 2, 3, 4, 5, 8, 9, 10. Optional: 6 (Accounting Setup), 7 (Relationship Intelligence).
                </p>
              </div>
              {goLiveError && (
                <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  {goLiveError}
                </div>
              )}
              <button
                onClick={handleGoLive}
                disabled={goLiveLoading || !allMandatoryDone}
                className="flex items-center gap-2 rounded-lg bg-[#182350] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#0f1a3d] disabled:opacity-40 transition-colors"
              >
                {goLiveLoading ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Rocket size={15} />
                )}
                {goLiveLoading ? "Verifying…" : "Activate Client (Go Live)"}
              </button>
              {!allMandatoryDone && (
                <p className="text-xs text-[#94A3B8]">
                  Complete all mandatory steps to activate.
                </p>
              )}
            </div>
          )}
        </div>
      ) : (
        /* ── List View ────────────────────────────────────────────────── */
        <div className="space-y-3">
          {loading && (
            <div className="flex items-center justify-center py-16 text-[#94A3B8]">
              <Loader2 size={24} className="animate-spin mr-2" />
              Loading onboardings…
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}
          {!loading && !error && workflows.length === 0 && (
            <div className="text-center py-16 text-[#94A3B8]">
              <p className="text-sm font-medium">No active onboardings</p>
              <p className="text-xs mt-1">Convert a lead from the Pipeline to start an onboarding workflow.</p>
              <Link
                href="/pipeline"
                className="inline-flex items-center gap-1 mt-4 text-sm text-[#182350] font-medium hover:underline"
              >
                Go to Pipeline <ChevronRight size={14} />
              </Link>
            </div>
          )}
          {!loading && workflows.map((wf) => (
            <WorkflowCard key={wf.id} wf={wf} onSelect={setSelected} />
          ))}
        </div>
      )}
    </div>
  );
}
