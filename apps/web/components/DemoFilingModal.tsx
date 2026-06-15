"use client";

/**
 * DEMO MODE filing simulation modal (PR-3).
 * Workflow: Prepare → Validate → Simulate Filing → Processing → Demo ARN/SRN.
 * This is a WORKFLOW SIMULATION ONLY — it submits nothing to any portal and
 * generates a deliberately-fake DEMO-/SIM- reference. The DEMO MODE banner is
 * shown on every step.
 */
import { useState } from "react";
import { X, CheckCircle, AlertCircle, Loader, FlaskConical, ArrowRight } from "lucide-react";
import DemoModeBanner from "@/components/DemoModeBanner";
import { formatDate } from "@/lib/services/formatting";
import {
  generateDemoReference,
  validateForDemo,
  DEMO_STATUS_LONG,
} from "@/lib/filing/demoFiling";
import type { ComplianceEntry } from "@/lib/data/compliance";

interface Props {
  entry: ComplianceEntry;
  clientName: string;
  /** Persist the simulated filing; receives the generated demo reference. */
  onConfirmed: (demoReference: string) => Promise<void>;
  onClose: () => void;
}

type Step = "prepare" | "validate" | "processing" | "done";

export default function DemoFilingModal({ entry, clientName, onConfirmed, onClose }: Props) {
  const [step, setStep] = useState<Step>("prepare");
  const [reference, setReference] = useState<string>("");
  const [saveError, setSaveError] = useState<string | null>(null);

  const validation = validateForDemo(entry);
  const canSimulate = validation.errors.length === 0;

  function startSimulation() {
    setStep("processing");
    setSaveError(null);
    const ref = generateDemoReference(entry.compliance_type);
    // Brief processing animation so the simulation feels end-to-end.
    setTimeout(async () => {
      try {
        await onConfirmed(ref);
        setReference(ref);
        setStep("done");
      } catch (e) {
        setSaveError(e instanceof Error ? e.message : "Could not record the simulated filing.");
        setStep("validate");
      }
    }, 1800);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <h2 className="text-base font-semibold text-[#0F172A] flex items-center gap-2">
            <FlaskConical size={16} className="text-amber-600" />
            Simulate Filing — {entry.compliance_type}
          </h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X className="w-5 h-5" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Required banner — always visible */}
          <DemoModeBanner />

          {/* Step indicator */}
          <div className="flex items-center gap-1.5 text-[11px] text-[#94A3B8]">
            {(["Prepare", "Validate", "Simulate", "Done"] as const).map((label, i) => {
              const active =
                (step === "prepare" && i === 0) ||
                (step === "validate" && i === 1) ||
                (step === "processing" && i === 2) ||
                (step === "done" && i === 3);
              const past =
                (i === 0 && step !== "prepare") ||
                (i === 1 && (step === "processing" || step === "done")) ||
                (i === 2 && step === "done");
              return (
                <span key={label} className="flex items-center gap-1.5">
                  <span className={`px-2 py-0.5 rounded-full ${active ? "bg-amber-100 text-amber-700 font-medium" : past ? "bg-green-50 text-green-600" : "bg-[#F1F5F9]"}`}>{label}</span>
                  {i < 3 && <ArrowRight size={10} className="text-[#CBD5E1]" />}
                </span>
              );
            })}
          </div>

          {/* Step 1 — Prepare */}
          {step === "prepare" && (
            <div className="space-y-3">
              <p className="text-sm font-medium text-[#334155]">Prepare Return</p>
              <div className="bg-[#F8FAFC] rounded-lg p-3 text-xs space-y-1.5 text-[#475569]">
                <div className="flex justify-between"><span>Client</span><span className="font-medium text-[#0F172A]">{clientName}</span></div>
                <div className="flex justify-between"><span>Return</span><span className="font-medium text-[#0F172A]">{entry.compliance_type}</span></div>
                <div className="flex justify-between"><span>Period</span><span>{formatDate(entry.period_start)} – {formatDate(entry.period_end)}</span></div>
                <div className="flex justify-between"><span>Due date</span><span>{formatDate(entry.due_date)}</span></div>
              </div>
              <p className="text-xs text-[#64748B]">This is a demonstration of the filing workflow. No return is prepared with real figures and nothing is submitted anywhere.</p>
            </div>
          )}

          {/* Step 2 — Validate */}
          {step === "validate" && (
            <div className="space-y-3">
              <p className="text-sm font-medium text-[#334155]">Validate Return</p>
              {validation.errors.length === 0 && validation.warnings.length === 0 && (
                <p className="text-xs text-green-600 flex items-center gap-1.5"><CheckCircle size={13} /> No validation issues found.</p>
              )}
              {validation.errors.map((e, i) => (
                <p key={`e${i}`} className="text-xs text-red-600 flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {e}</p>
              ))}
              {validation.warnings.map((w, i) => (
                <p key={`w${i}`} className="text-xs text-amber-700 flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {w}</p>
              ))}
              {saveError && <p className="text-xs text-red-600">{saveError}</p>}
            </div>
          )}

          {/* Step 3 — Processing */}
          {step === "processing" && (
            <div className="py-12 text-center space-y-3">
              <Loader className="w-8 h-8 text-amber-600 mx-auto animate-spin" />
              <p className="text-sm text-[#475569]">Simulating filing…</p>
              <p className="text-xs text-[#94A3B8]">Generating a demo reference. Nothing is being submitted.</p>
            </div>
          )}

          {/* Step 4 — Done */}
          {step === "done" && (
            <div className="py-6 text-center space-y-3">
              <CheckCircle className="w-12 h-12 text-green-500 mx-auto" />
              <p className="text-lg font-semibold text-[#0F172A]">{DEMO_STATUS_LONG}</p>
              <div className="inline-block bg-amber-50 border border-amber-200 rounded-lg px-4 py-2">
                <p className="text-[10px] uppercase tracking-wide text-amber-600 font-semibold">Demo Reference</p>
                <p className="text-sm font-mono font-semibold text-amber-800">{reference}</p>
              </div>
              <p className="text-xs text-[#64748B] max-w-xs mx-auto">This is a simulated reference. The return was <strong>not</strong> filed with any government portal.</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-between items-center">
          <button onClick={onClose} className="text-sm text-[#64748B] hover:text-[#334155]">
            {step === "done" ? "Close" : "Cancel"}
          </button>
          {step === "prepare" && (
            <button onClick={() => setStep("validate")} className="px-4 py-2 bg-[#0F172A] text-white text-sm font-medium rounded-lg hover:bg-[#1E293B]">
              Validate Return
            </button>
          )}
          {step === "validate" && (
            <button
              onClick={startSimulation}
              disabled={!canSimulate}
              className="px-5 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1.5"
            >
              <FlaskConical size={14} /> Simulate Filing
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
