"use client";

/**
 * What the AI cost this firm, and the allowance it is held to — the second half of
 * `/settings/ai` (ai-17).
 *
 * THE SERVER DECIDES, THE SCREEN SHOWS. Every figure is a count the server summed
 * (`/api/ai-status/usage`); the words for a reached allowance are the server's own
 * (`standing.sentence`, the very sentence a refused call gets); what a limit may be is
 * the server's to judge (`PUT /api/ai-status/budget` answers a refusal in words). The
 * browser's only job with a typed limit is to turn text into a whole number or into
 * "no limit", and to refuse to send what is not a number.
 *
 * THREE THINGS THAT LOOK ALIKE AND ARE NOT, KEPT APART:
 *   * NO LIMIT (a blank box, `null`) — never zero, and zero is refused by the server;
 *   * NOT READ (`unread` set, `usage` null) — the usage could not be fetched, which is not
 *     "nothing was used";
 *   * POSSIBLY SHORT (`truncated`) — a grouped answer reached the row cap.
 *
 * TOKENS AND PAGES, NOT RUPEES. The server holds no provider price and neither does this
 * screen; nothing here is a cost.
 *
 * THE ALLOWANCE IS MEASURED AGAINST THE CURRENT MONTH even while an older month is on
 * screen, and the panel says so, because "where does this month stand" is the question
 * a Partner looking at September is really asking.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { Callout } from "@/components/ui/callout";
import { Input, Select } from "@/components/ui/field";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api, type AiAllowancePart, type AiUsage, type AiUsageByDay, type AiUsageByFeature } from "@/lib/api/index";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { formatIstLabelled } from "@/lib/dates/formatIst";

const COUNT = new Intl.NumberFormat("en-IN");

/** A count as the Indian grouping writes it; a figure nobody holds is a dash, never 0. */
function count(n: number | null | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? COUNT.format(n) : "—";
}

type Parsed = { ok: true; value: number | null } | { ok: false };

/** Text to "no limit" (blank), a whole number, or refused. It judges nothing about the
 *  size: the server owns what a limit may be, including that zero is not one. */
function parseLimit(text: string): Parsed {
  const t = text.replace(/[,\s]/g, "");
  if (t === "") return { ok: true, value: null };
  if (!/^[0-9]+$/.test(t)) return { ok: false };
  const n = Number(t);
  return Number.isSafeInteger(n) ? { ok: true, value: n } : { ok: false };
}

function asUsage(data: unknown): AiUsage | null {
  return objectWithLists<AiUsage>(data, "choices", "not_covered");
}

function Part({ label, unit, part }: { label: string; unit: string; part: AiAllowancePart }) {
  const limited = part.limit != null;
  return (
    <div className="rounded-lg border border-ps-border bg-white px-4 py-3">
      <div className="text-xs text-ps-label">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-ps-ink">{count(part.used)}</div>
      <div className="text-xs text-ps-body">
        {limited
          ? <>of {count(part.limit)} {unit}{part.reached
              ? <span className="text-state-problem"> · reached</span>
              : <span className="text-ps-label"> · {count(part.remaining)} left</span>}</>
          : <span className="text-ps-label">{unit} used · no limit set</span>}
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th scope="col" className={"px-3 py-2 text-xs font-medium text-ps-label " + (right ? "text-right" : "text-left")}>
      {children}
    </th>
  );
}

function Num({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2 text-right text-sm tabular-nums text-ps-body">{children}</td>;
}

export function AiUsagePanel() {
  const [data, setData] = useState<AiUsage | null>(null);
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [tokenText, setTokenText] = useState("");
  const [pageText, setPageText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  /** Put the boxes back to what the server says the allowance is. */
  const fillBoxes = useCallback((u: AiUsage | null) => {
    const limits = u?.allowance?.limits;
    setTokenText(limits?.monthly_tokens != null ? String(limits.monthly_tokens) : "");
    setPageText(limits?.monthly_pages != null ? String(limits.monthly_pages) : "");
  }, []);

  const load = useCallback(async (which: string | undefined, refillBoxes: boolean) => {
    try {
      const res = await api.aiStatus.usage(which);
      if (!res.success) { setError(res.error || "Could not read the AI usage."); return; }
      const next = asUsage(res.data);
      if (!next) { setError("The server answered with something unreadable."); return; }
      setError(null);
      setData(next);
      if (refillBoxes) fillBoxes(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the AI usage.");
    }
  }, [fillBoxes]);

  useEffect(() => { void load(undefined, true); }, [load]);

  function chooseMonth(key: string) {
    const which = key === data?.current_month?.key ? undefined : key;
    setMonth(which);
    setSaved(false);
    void load(which, false);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaved(false);
    const tokens = parseLimit(tokenText);
    const pages = parseLimit(pageText);
    if (!tokens.ok || !pages.ok) {
      setSaveError("A limit is a whole number, like 5,000,000. Leave a box empty for no limit.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await api.aiStatus.setBudget(tokens.value, pages.value);
      if (!res.success) { setSaveError(res.error || "The allowance could not be saved."); return; }
      const next = asUsage(res.data);
      if (!next) { setSaveError("The server answered with something unreadable."); return; }
      setSaved(true);
      fillBoxes(next);
      // The answer is for the current month; reload the month on screen if it is another.
      if (month) await load(month, false); else setData(next);
    } catch (err) {
      // A 422 arrives as a thrown refusal carrying the server's own sentence.
      setSaveError(err instanceof Error ? err.message : "The allowance could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) return <Callout tone="problem">{error}</Callout>;
  if (!data) return <TableSkeleton cols={2} rows={4} />;

  const choices = arrayOrEmpty<{ key: string; label: string }>(data.choices);
  const standing = data.allowance?.standing ?? null;
  const usage = data.usage;
  const features = arrayOrEmpty<AiUsageByFeature>(usage?.by_feature);
  const days = arrayOrEmpty<AiUsageByDay>(usage?.by_day);
  const viewingOther = data.month?.key !== data.current_month?.key;

  return (
    <section aria-label="AI use and allowance" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">AI use and allowance</h2>
          <p className="mt-0.5 max-w-2xl text-xs text-ps-label">
            What this firm&apos;s calls to the AI came to, in tokens and pages, and an optional
            monthly limit. Months run from the 1st to the last day, India time.
          </p>
        </div>
        <label className="text-xs text-ps-label">
          <span className="mb-1 block">Month</span>
          <Select size="sm" value={data.month?.key ?? ""} onChange={(e) => chooseMonth(e.target.value)}>
            {choices.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </Select>
        </label>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}
      {data.unread && <Callout tone="attention">{data.unread}</Callout>}

      {standing?.sentence && <Callout tone="problem">{standing.sentence}</Callout>}

      {standing && (
        <div>
          <div className="mb-2 text-xs text-ps-label">
            Allowance for {data.current_month?.label ?? "this month"}
            {viewingOther ? " (measured against the current month, not the one chosen above)" : ""}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Part label="Tokens" unit="tokens" part={standing.tokens} />
            <Part label="Pages read from pictures and scans" unit="pages" part={standing.pages} />
          </div>
        </div>
      )}

      {data.allowance && (
        <form onSubmit={save} className="rounded-xl border border-ps-border bg-white px-5 py-4"
              aria-label="Set the monthly allowance">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-ps-label">
              Monthly token limit
              <Input inputMode="numeric" autoComplete="off" value={tokenText}
                     onChange={(e) => { setTokenText(e.target.value); setSaved(false); }}
                     placeholder="No limit" className="mt-1" />
            </label>
            <label className="block text-xs font-medium text-ps-label">
              Monthly page limit
              <Input inputMode="numeric" autoComplete="off" value={pageText}
                     onChange={(e) => { setPageText(e.target.value); setSaved(false); }}
                     placeholder="No limit" className="mt-1" />
            </label>
          </div>
          <p className="mt-2 text-xs text-ps-label">
            Leave a box empty for no limit. When a limit is reached the assistant and the readers
            say so in words and send nothing to the provider until the month turns or a Partner
            raises it. The &quot;Check now&quot; buttons above are never refused.
            {data.allowance.updated_at ? <> Last changed {formatIstLabelled(data.allowance.updated_at, "—")}.</> : null}
          </p>
          {saveError && <div className="mt-3"><Callout tone="problem">{saveError}</Callout></div>}
          {saved && !saveError && <div className="mt-3"><Callout tone="note">Allowance saved.</Callout></div>}
          <div className="mt-3">
            <button type="submit" disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50">
              {saving ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <Save size={13} aria-hidden />}
              {saving ? "Saving…" : "Save allowance"}
            </button>
          </div>
        </form>
      )}

      {usage && (
        <>
          {usage.truncated && (
            <Callout tone="attention">
              This month has more separate groupings than one answer can carry, so the figures
              below may be short.
            </Callout>
          )}
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Calls", usage.totals.calls],
              ["Answered", usage.totals.answered],
              ["Failed attempts", usage.totals.failed],
              ["Refused for the allowance", usage.totals.refused],
              ["Tokens", usage.totals.tokens],
              ["of which reasoning", usage.totals.reasoning_tokens],
              ["Pages", usage.totals.pages],
              ["Attempts in all", usage.totals.attempts],
            ].map(([label, n]) => (
              <div key={String(label)} className="rounded-lg border border-ps-border bg-white px-4 py-3">
                <dt className="text-xs text-ps-label">{label}</dt>
                <dd className="mt-0.5 text-base font-semibold tabular-nums text-ps-ink">{count(n as number)}</dd>
              </div>
            ))}
          </dl>

          <div className="overflow-x-auto rounded-xl border border-ps-border bg-white">
            <table className="min-w-full divide-y divide-ps-border">
              <caption className="sr-only">Use by feature</caption>
              <thead className="bg-ps-bg">
                <tr>
                  <Th>Feature</Th><Th>Provider</Th><Th>Models</Th>
                  <Th right>Calls</Th><Th right>Failed</Th><Th right>Tokens</Th><Th right>Pages</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {features.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-4 text-sm text-ps-label">
                    No call was recorded for this firm in {data.month?.label ?? "this month"}.
                  </td></tr>
                )}
                {features.map((f) => (
                  <tr key={`${f.provider}/${f.feature}`}>
                    <td className="px-3 py-2 font-mono text-xs text-ps-ink">{f.feature ?? "—"}</td>
                    <td className="px-3 py-2 text-sm text-ps-body">{f.provider ?? "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs text-ps-label">{arrayOrEmpty<string>(f.models).join(", ") || "—"}</td>
                    <Num>{count(f.calls)}</Num><Num>{count(f.failed)}</Num>
                    <Num>{count(f.tokens)}</Num><Num>{count(f.pages)}</Num>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {days.length > 0 && (
            <details className="rounded-xl border border-ps-border bg-white">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ps-ink">Day by day</summary>
              <div className="overflow-x-auto border-t border-ps-border">
                <table className="min-w-full divide-y divide-ps-border">
                  <caption className="sr-only">Use by day</caption>
                  <thead className="bg-ps-bg">
                    <tr><Th>Day</Th><Th right>Calls</Th><Th right>Failed</Th><Th right>Tokens</Th><Th right>Pages</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-ps-border">
                    {days.map((d) => (
                      <tr key={d.day}>
                        <td className="px-3 py-2 text-sm text-ps-body">{d.day}</td>
                        <Num>{count(d.calls)}</Num><Num>{count(d.failed)}</Num>
                        <Num>{count(d.tokens)}</Num><Num>{count(d.pages)}</Num>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      )}

      {data.first_recorded_at && (
        <p className="text-xs text-ps-label">
          The first call recorded for this firm was {formatIstLabelled(data.first_recorded_at, "—")}.
        </p>
      )}

      {arrayOrEmpty<string>(data.not_covered).length > 0 && (
        <Callout tone="note" title="What this does not tell you">
          <ul className="space-y-1.5">
            {arrayOrEmpty<string>(data.not_covered).map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </Callout>
      )}
    </section>
  );
}
