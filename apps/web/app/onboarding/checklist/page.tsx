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
import { Callout } from "@/components/ui/callout";

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
  pending:     { label: "Pending",     color: "text-ps-hint", icon: <Circle size={18} className="text-ps-disabled" /> },
  in_progress: { label: "In Progress", color: "text-blue-600",  icon: <Clock size={18} className="text-blue-500" /> },
  done:        { label: "Done",        color: "text-green-700", icon: <CheckCircle2 size={18} className="text-green-600" /> },
  skipped:     { label: "Skipped",     color: "text-ps-hint", icon: <SkipForward size={18} className="text-ps-hint" /> },
};

// ─── Progress bar ───────────────────────────────────────────────────────────

function ProgressBar({ pct, stalled }: { pct: number; stalled: boolean }) {
  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs font-medium text-ps-label">Progress</span>
        <span className={`text-xs font-bold ${stalled ? "text-orange-600" : "text-brand"}`}>
          {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-ps-border overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${stalled ? "bg-orange-400" : "bg-brand"}`}
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
      className="w-full text-left bg-white rounded-xl border border-ps-border p-4 hover:border-brand-light hover:shadow-sm transition-all space-y-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-ps-ink">
            Client: <span className="font-mono text-brand">{wf.client_id.slice(0, 8)}…</span>
          </p>
          <p className="text-xs text-ps-label mt-0.5">
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
          <ChevronRight size={14} className="text-ps-hint" />
        </div>
      </div>
      <ProgressBar pct={wf.progress_pct} stalled={stalled} />
      <p className="text-xs text-ps-hint">
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
          ? "bg-ps-bg border-ps-border opacity-60"
          : "bg-white border-ps-border"
      }`}
    >
      {/* Step number + icon */}
      <div className="flex flex-col items-center gap-1 pt-0.5 shrink-0">
        <div className="w-6 h-6 rounded-full bg-ps-muted flex items-center justify-center text-3xs font-bold text-ps-label">
          {step.step_number}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className={`text-sm font-semibold ${step.status === "done" ? "text-green-800 line-through" : "text-ps-ink"}`}>
              {step.title}
            </p>
            <p className="text-xs text-ps-label mt-0.5 leading-relaxed">{step.description}</p>
            {step.notes && (
              <p className="text-xs italic text-ps-hint mt-1">{step.notes}</p>
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
              className="text-xs text-ps-hint hover:text-ps-label transition-colors"
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
          <div className="flex items-center gap-2 text-xs text-ps-hint mb-1">
            <Link href="/clients" className="hover:text-ps-label">Clients</Link>
            <ChevronRight size={12} />
            <span>Onboarding</span>
          </div>
          <h1 className="text-xl font-semibold text-ps-ink">Client Onboarding</h1>
          <p className="text-sm text-ps-label mt-0.5">
            10-step checklist to onboard new clients into your CA firm
          </p>
        </div>
        <button
          onClick={fetchWorkflows}
          className="flex items-center gap-1.5 text-sm text-ps-label hover:text-ps-body border border-ps-border rounded-lg px-3 py-1.5 hover:bg-ps-bg transition-colors"
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
              className="text-sm text-ps-label hover:text-ps-body transition-colors"
            >
              ← All Onboardings
            </button>
            <div className="text-right text-xs text-ps-hint">
              Day {selected.days_in_progress} / ~{selected.avg_days_for_entity_type} avg days ({selected.entity_type})
            </div>
          </div>

          {/* Progress */}
          <div className="bg-white rounded-xl border border-ps-border p-4 space-y-2">
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
            <div className="bg-white rounded-xl border border-ps-border p-4 space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-ps-ink">Go-Live Verification</h3>
                <p className="text-xs text-ps-label mt-0.5">
                  Mandatory steps: 1, 2, 3, 4, 5, 8, 9, 10. Optional: 6 (Accounting Setup), 7 (Relationship Intelligence).
                </p>
              </div>
              {goLiveError && <Callout tone="problem">{goLiveError}</Callout>}
              <button
                onClick={handleGoLive}
                disabled={goLiveLoading || !allMandatoryDone}
                className="flex items-center gap-2 rounded-lg bg-brand text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#0f1a3d] disabled:opacity-40 transition-colors"
              >
                {goLiveLoading ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Rocket size={15} />
                )}
                {goLiveLoading ? "Verifying…" : "Activate Client (Go Live)"}
              </button>
              {!allMandatoryDone && (
                <p className="text-xs text-ps-hint">
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
            <div className="flex items-center justify-center py-16 text-ps-hint">
              <Loader2 size={24} className="animate-spin mr-2" />
              Loading onboardings…
            </div>
          )}
          {error && <Callout tone="problem">{error}</Callout>}
          {!loading && !error && workflows.length === 0 && (
            <div className="text-center py-16 text-ps-hint">
              <p className="text-sm font-medium">No active onboardings</p>
              <p className="text-xs mt-1">Convert a lead from the Pipeline to start an onboarding workflow.</p>
              <Link
                href="/pipeline"
                className="inline-flex items-center gap-1 mt-4 text-sm text-brand font-medium hover:underline"
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
