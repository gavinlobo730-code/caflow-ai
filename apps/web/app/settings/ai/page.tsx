"use client";

/**
 * Is the AI answering? — the screen that ends "nobody can say" (ai-06).
 *
 * WHAT WAS WRONG
 *   The Groq default was changed on 29-09-2026 after a live `model_not_found`, to
 *   a name nobody had called, and no successful live call was recorded anywhere.
 *   The assistant, the invoice reader and the copilot all depend on it, and the
 *   first person to find out whether it worked would have been a CA in front of a
 *   client. This page says what each provider has been SEEN to do, in words, and
 *   has one button that asks.
 *
 * WHAT IT DOES NOT DO — and says
 *   It does not decide anything. Every word, label and tone is the server's
 *   (`/api/ai-status`), including the sentence for a failure; the browser holds no
 *   vocabulary of statuses. The one thing it is careful about is the difference
 *   between three states that look alike: UNVERIFIED (nobody has asked since the
 *   server started — NOT a fault), FAILING (the last attempt did not answer) and
 *   a history that could not be READ (which is not an empty history). An unknown
 *   status word is drawn as unverified, never as ok.
 *
 * A CHECK COSTS A REQUEST. "Check now" makes ONE small real call to ONE provider
 * (a failing provider can spend the gateway's forty seconds and `lib/api` gives up
 * at forty-five), so the two providers are asked one after the other and each
 * answer is shown as it arrives. Nothing about any client is sent.
 *
 * Partner only, like the security posture: it reports what the deployment is
 * configured with and spends the firm's AI allowance.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, Cpu, Loader2, RefreshCw } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { Callout } from "@/components/ui/callout";
import { TableSkeleton } from "@/components/ui/skeleton";
import {
  api,
  type AiProbeAnswer,
  type AiProbeResult,
  type AiProviderName,
  type AiProviderState,
  type AiStatus,
} from "@/lib/api/index";
import { arrayOrEmpty, objectOrNull, objectWithLists } from "@/lib/api/shape";
import { formatIstLabelled } from "@/lib/dates/formatIst";

const CHIP: Record<string, string> = {
  ready: "bg-state-ready-surface text-state-ready",
  problem: "bg-state-problem-surface text-state-problem",
  attention: "bg-state-attention-surface text-state-attention",
  neutral: "bg-ps-bg text-ps-label",
};

function asStatus(data: unknown): AiStatus | null {
  return objectWithLists<AiStatus>(data, "providers", "not_covered");
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-2 sm:grid-cols-[14rem_1fr] sm:gap-3">
      <dt className="text-xs text-ps-label">{label}</dt>
      <dd className="text-sm text-ps-body">{children}</dd>
    </div>
  );
}

function when(at: string | null | undefined): string {
  return formatIstLabelled(at, "never");
}

function seen(s: { model?: string | null; at?: string | null; latency_ms?: number | null;
                   total_tokens?: number | null } | null | undefined): React.ReactNode {
  if (!s) return <span className="text-ps-label">none</span>;
  return (
    <>
      {when(s.at)}
      {s.model ? <span className="text-ps-label"> · <span className="font-mono">{s.model}</span></span> : null}
      {s.latency_ms != null ? <span className="text-ps-label"> · {s.latency_ms} ms</span> : null}
      {s.total_tokens != null ? <span className="text-ps-label"> · {s.total_tokens} tokens</span> : null}
    </>
  );
}

function ProviderCard({
  p, busy, result, onCheck,
}: {
  p: AiProviderState;
  busy: boolean;
  result: AiProbeResult | null;
  onCheck: () => void;
}) {
  const chip = CHIP[p.status_tone] ?? CHIP.attention;
  const fallbacks = arrayOrEmpty<string>(p.fallback_models);
  const attempt = p.this_process?.last_attempt ?? null;
  const firm = p.this_firm;
  return (
    <section aria-label={`${p.label} status`}
             className="overflow-hidden rounded-xl border border-ps-border bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ps-border px-5 py-4">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-ps-ink">{p.label}</h2>
          <span className={"rounded-full px-2 py-0.5 text-xs font-medium " + chip}>{p.status_label}</span>
        </div>
        <button type="button" onClick={onCheck} disabled={busy || !p.configured}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <RefreshCw size={13} aria-hidden />}
          {busy ? "Asking…" : "Check now"}
        </button>
      </div>

      <div className="px-5 py-2">
        {result && (
          <div className="py-2">
            <Callout tone={result.tone ?? "attention"}>
              {result.state === "ok" ? (
                <>
                  Answered in {result.latency_ms ?? "—"} ms
                  {result.answered_by ? <> using <span className="font-mono">{result.answered_by}</span></> : null}
                  {result.total_tokens != null ? <> ({result.total_tokens} tokens)</> : null}.
                  {result.answered_by && result.answered_by !== result.model
                    ? <> The configured model <span className="font-mono">{result.model}</span> did not answer; a fallback did.</>
                    : null}
                </>
              ) : (
                result.sentence ?? "The check did not complete."
              )}
            </Callout>
          </div>
        )}
        <dl className="divide-y divide-ps-border">
          <Fact label="Model asked for"><span className="font-mono">{p.model}</span></Fact>
          <Fact label="Fallback models">
            {fallbacks.length > 0
              ? <span className="font-mono">{fallbacks.join(", ")}</span>
              : <span className="text-ps-label">none configured — if this model is retired, nothing else is tried</span>}
          </Fact>
          <Fact label="Last answer this server saw">{seen(p.this_process?.last_success)}</Fact>
          <Fact label="Last attempt this server saw">
            {seen(attempt)}
            {attempt && attempt.outcome !== "ok" && attempt.outcome !== "truncated"
              ? <span className="text-state-problem"> · {attempt.outcome}</span> : null}
          </Fact>
          {firm ? (
            <>
              <Fact label="Last answered for this firm">{seen(firm.last_answered)}</Fact>
              <Fact label="Last attempt for this firm">{seen(firm.last_attempt)}</Fact>
            </>
          ) : (
            <Fact label="This firm&apos;s history">
              <span className="text-ps-label">{p.this_firm_unread ?? "Not read."}</span>
            </Fact>
          )}
        </dl>
      </div>
    </section>
  );
}

export default function AiStatusPage() {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, AiProbeResult | null>>({});

  const load = useCallback(async () => {
    try {
      const res = await api.aiStatus.get();
      if (!res.success) { setError(res.error || "Could not read the AI status."); return; }
      const next = asStatus(res.data);
      if (!next) { setError("The server answered with something unreadable."); return; }
      setError(null);
      setStatus(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the AI status.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function check(provider: AiProviderName) {
    setBusy((b) => ({ ...b, [provider]: true }));
    setResults((r) => ({ ...r, [provider]: null }));
    try {
      const res = await api.aiStatus.probe(provider);
      if (!res.success) {
        setError(res.error || "The check could not be run.");
        return;
      }
      const answer = objectOrNull<AiProbeAnswer>(res.data);
      const result = objectOrNull<AiProbeResult>(answer?.result);
      if (!answer || !result) { setError("The server answered with something unreadable."); return; }
      setError(null);
      setResults((r) => ({ ...r, [provider]: result }));
      const next = asStatus(answer.status);
      if (next) setStatus(next);
    } catch (e) {
      // A 429 arrives as a thrown refusal carrying the server's own sentence.
      setError(e instanceof Error ? e.message : "The check could not be run.");
    } finally {
      setBusy((b) => ({ ...b, [provider]: false }));
    }
  }

  async function checkBoth() {
    // One at a time: each can take as long as the gateway's whole budget.
    for (const p of arrayOrEmpty<AiProviderState>(status?.providers)) {
      if (p.configured) await check(p.provider);
    }
  }

  const providers = arrayOrEmpty<AiProviderState>(status?.providers);
  const anyBusy = Object.values(busy).some(Boolean);

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="mx-auto max-w-ps-data space-y-4 p-6">
        <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-ps-label hover:text-ps-body">
          <ChevronLeft size={13} /> Settings
        </Link>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Cpu size={17} className="text-blue-600" aria-hidden />
            <h1 className="text-lg font-semibold text-ps-ink">AI status</h1>
          </div>
          {providers.some((p) => p.configured) && (
            <button type="button" onClick={checkBoth} disabled={anyBusy}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-ps-border px-3 py-1.5 text-xs font-medium text-ps-body hover:bg-ps-bg disabled:opacity-50">
              {anyBusy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <RefreshCw size={13} aria-hidden />}
              Check every provider
            </button>
          )}
        </div>
        <p className="max-w-2xl text-xs text-ps-label">
          Whether the assistant, the copilot and the invoice and notice readers can reach
          their AI providers. &quot;Check now&quot; sends one short fixed request — nothing
          about any client — and tells you in words if it did not answer.
        </p>

        {error && <Callout tone="problem">{error}</Callout>}

        {!status && !error && <TableSkeleton cols={2} rows={5} />}

        {status && (
          <>
            <div className="space-y-4">
              {providers.map((p) => (
                <ProviderCard key={p.provider} p={p} busy={!!busy[p.provider]}
                              result={results[p.provider] ?? null}
                              onCheck={() => void check(p.provider)} />
              ))}
            </div>
            {arrayOrEmpty<string>(status.not_covered).length > 0 && (
              <Callout tone="note" title="What this does not tell you">
                <ul className="space-y-1.5">
                  {arrayOrEmpty<string>(status.not_covered).map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </Callout>
            )}
          </>
        )}
      </div>
    </RoleGuard>
  );
}
