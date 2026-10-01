"use client";

/**
 * The first-run checklist on the dashboard (market_and_trust-16).
 *
 * It replaces a welcome card of five links that appeared ONCE after onboarding
 * (`?welcome=1`) and was gone for good — so a firm that closed the tab after adding a
 * client could not see what was still ahead of it. This stays until the firm has done
 * the four things, and ticks itself.
 *
 * THE SERVER DECIDES, THE SCREEN DRAWS. `GET /api/onboarding/status` computes every
 * tick from the firm's own rows, says whether the card is `visible`, and says which step
 * is next; nothing here counts a row or reads a table. `readFirstRun` turns the payload
 * into something a `.map` cannot throw on (`lib/api/shape.ts`).
 *
 * THREE STATES PER STEP. A step the server could not read is "could not check", not an
 * empty circle: an empty circle tells a firm to repeat what it may already have done.
 *
 * ONLY PARTNER AND MANAGER ARE ASKED. The endpoint is `firm:read`; an Executive or a
 * Reviewer gets a refusal, and so does a failed call — both render nothing. That is a
 * prompt and not a statement, so silence on failure does not present an unknown as a
 * value, and a role that cannot act on setup is not shown a setup card.
 *
 * THE ONE THING KEPT IN THE BROWSER is whether THIS person has collapsed the card on
 * THIS device — a per-viewer convenience, like a remembered tab, and not a record of
 * anything. It is read in an effect (this app is a static export: nothing may touch
 * `window` during render), every access is in a try/catch (a private window or blocked
 * site data throws), and collapsing leaves one line with the progress on it, so the card
 * is never hidden. A "dismiss for good" would need a column; none was available.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, ChevronDown, ChevronUp, Circle, HelpCircle } from "lucide-react";
import { api } from "@/lib/api";
import { objectOrNull } from "@/lib/api/shape";
import { hrefFor, readFirstRun, shouldShow, type FirstRunChecklist, type FirstRunStep } from "@/lib/onboarding/firstRun";
import { cn } from "@/lib/utils";

const COLLAPSED_KEY = "ps.firstRun.collapsed";

function StepIcon({ done }: { done: boolean | null }) {
  if (done === true) return <CheckCircle2 size={18} className="text-emerald-600 shrink-0" aria-hidden="true" />;
  if (done === null) return <HelpCircle size={18} className="text-ps-hint shrink-0" aria-hidden="true" />;
  return <Circle size={18} className="text-ps-hint shrink-0" aria-hidden="true" />;
}

function stateWord(done: boolean | null): string {
  return done === true ? "Done" : done === null ? "Could not be checked" : "Not done yet";
}

function Row({ step, isNext }: { step: FirstRunStep; isNext: boolean }) {
  const href = hrefFor(step.id);
  return (
    <li
      data-step={step.id}
      data-done={step.done === null ? "unknown" : String(step.done)}
      className={cn(
        "flex items-start gap-3 rounded-lg px-3 py-2.5",
        isNext ? "bg-blue-50/70 ring-1 ring-blue-100" : "",
      )}
    >
      <span className="mt-0.5"><StepIcon done={step.done} /></span>
      <div className="min-w-0 flex-1">
        <p className={cn("text-sm font-semibold", step.done === true ? "text-ps-hint line-through" : "text-ps-ink")}>
          {step.title}
          <span className="sr-only"> — {stateWord(step.done)}</span>
        </p>
        {step.done !== true && step.why ? (
          <p className="mt-0.5 text-xs leading-snug text-ps-hint">{step.why}</p>
        ) : null}
        {step.done === null ? (
          <p className="mt-0.5 text-xs text-ps-hint">We could not check this one just now.</p>
        ) : null}
      </div>
      {step.done !== true && href ? (
        <Link
          href={href}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
            isNext ? "bg-brand text-white hover:bg-brand-dark" : "border border-ps-border text-ps-ink hover:bg-ps-muted",
          )}
        >
          {isNext ? "Start here" : "Open"} <ArrowRight size={12} aria-hidden="true" />
        </Link>
      ) : null}
    </li>
  );
}

export function FirstRunChecklist() {
  // The payload, narrowed to an object at the setter; the checklist is READ out of it
  // below, so nothing renders from a field of `r.data` directly.
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await api.firstRun.status();
        if (live) setPayload(r && r.success ? objectOrNull<Record<string, unknown>>(r.data) : null);
      } catch {
        // A refusal (not a Partner or Manager) and a failed call render the same thing:
        // nothing. See the header.
        if (live) setPayload(null);
      }
    })();
    return () => { live = false; };
  }, []);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSED_KEY) === "1");
    } catch {
      // storage unavailable: the card simply opens expanded
    }
  }, []);

  const checklist: FirstRunChecklist | null = useMemo(() => readFirstRun(payload), [payload]);

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      // a convenience, never a requirement
    }
  }

  if (!shouldShow(checklist)) return null;

  const pct = checklist.total > 0 ? Math.round((checklist.done_count / checklist.total) * 100) : 0;

  return (
    <section
      aria-labelledby="first-run-heading"
      data-first-run="true"
      className="rounded-2xl border border-ps-border bg-white p-5 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="first-run-heading" className="text-base font-semibold text-ps-ink">
            Getting started with PracticeSync
          </h2>
          <p className="mt-0.5 text-xs text-ps-hint">
            {checklist.done_count} of {checklist.total} done. Each step ticks itself when it happens.
          </p>
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!collapsed}
          aria-controls="first-run-steps"
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ps-border px-2 py-1 text-xs text-ps-hint hover:bg-ps-muted"
        >
          {collapsed ? <>Show <ChevronDown size={12} aria-hidden="true" /></> : <>Hide <ChevronUp size={12} aria-hidden="true" /></>}
        </button>
      </div>

      <div
        className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-ps-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={checklist.total}
        aria-valuenow={checklist.done_count}
        aria-label="Setup progress"
      >
        <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} />
      </div>

      {!collapsed ? (
        <ol id="first-run-steps" className="mt-3 space-y-1">
          {checklist.steps.map((step) => (
            <Row key={step.id} step={step} isNext={step.id === checklist.next_step} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}
