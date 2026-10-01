"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, Sunrise } from "lucide-react";
import { api } from "@/lib/api";
import type { PracticeDigestPayload } from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { digestClientHref, digestSectionHref } from "@/lib/insights/digestLinks";
import { cn } from "@/lib/utils";
import { GapList } from "@/components/ui/callout";

/**
 * Today — what needs attention across the clients you can see (ai-25).
 *
 * NOTHING HERE IS COMPUTED. Every count is read by the server off an existing
 * check (the compliance-risk engine, the overdue-task read, the nightly books
 * check's stored findings) and equals what that check reports; the sentence at
 * the top is a model's wording of those counts when something needs attention
 * and the plain sentence otherwise. `summary_source` says which, and the label
 * says it in words: the NUMBERS are always rule-based, and "worded by AI" appears
 * only when a model actually wrote the sentence and every figure in it was one of
 * the checks'. With the model down this panel still renders, as plain text — it
 * does not depend on one.
 *
 * THREE KINDS OF "NOTHING". `attention` is something to look at, `clear` is a
 * check that ran and found nothing, `unknown` is a check nobody ran (or could not
 * be read) — rendered as "not known", never as 0, because a morning list that said
 * "0 findings" over a sweep that never ran would tell a CA their books are sound.
 * What the digest does NOT cover is listed under it on every load, so a short list
 * is not read as a clean one.
 */

const STATUS_CHIP: Record<string, string> = {
  attention: "bg-sev-high-surface text-sev-high border-sev-high-border",
  clear: "bg-sev-ok-surface text-sev-ok border-sev-ok-border",
  unknown: "bg-ps-muted text-ps-hint border-ps-border",
};

const STATUS_WORD: Record<string, string> = {
  attention: "Look at",
  clear: "Clear",
  unknown: "Not known",
};

export function DigestPanel() {
  const [digest, setDigest] = useState<PracticeDigestPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(null);
    try {
      const res = await api.intelligence.digest();
      const d = res?.success
        ? objectWithLists<PracticeDigestPayload>(res.data, "items", "gaps") : null;
      setDigest(d);
      if (!d) setFailed("The digest could not be read just now.");
    } catch (e) {
      setDigest(null);
      setFailed(e instanceof Error && e.message ? e.message : "The digest could not be read just now.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden" data-testid="digest-panel">
      <div className="px-5 py-4 border-b border-ps-border flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-ps-body flex items-center gap-2">
            <Sunrise size={13} className="text-ps-hint shrink-0" />
            Today
          </p>
          <p className="text-3xs text-ps-hint mt-0.5">
            What needs attention across the clients you can see. Every count comes from an
            existing check and equals what that check reports.
            {digest?.scoped && " Narrowed to the clients assigned to you."}
          </p>
        </div>
        <button
          onClick={load}
          aria-label="Refresh the digest"
          className="shrink-0 p-1.5 rounded-lg border border-ps-border text-ps-hint hover:text-brand hover:bg-ps-bg transition-colors"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <p className="px-5 py-4 text-xs text-ps-hint">Loading…</p>}

      {!loading && failed && (
        <p className="px-5 py-4 text-xs text-ps-label">{failed}</p>
      )}

      {!loading && digest && (
        <div>
          <div className="px-5 py-4 border-b border-ps-border">
            <p className="text-xs text-ps-ink leading-relaxed">{digest.summary}</p>
            <p className="text-3xs text-ps-hint mt-1.5">
              Counts: rule-based.{" "}
              {digest.summary_source === "model"
                ? "The sentence above was worded by AI from those counts and adds none."
                : "The sentence above is plain text built from those counts."}
            </p>
          </div>

          <div className="divide-y divide-ps-border">
            {digest.items.map((it) => {
              const sectionHref = digestSectionHref(it.key);
              const clients = arrayOrEmpty<PracticeDigestPayload["items"][number]["clients"][number]>(it.clients);
              const more = it.clients_total - clients.length;
              return (
                <div key={it.key} className="px-5 py-3 flex items-start gap-3">
                  <span className={cn(
                    "shrink-0 text-3xs font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wide",
                    STATUS_CHIP[it.status] ?? STATUS_CHIP.unknown,
                  )}>
                    {STATUS_WORD[it.status] ?? "Not known"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-ps-ink">
                      {sectionHref
                        ? <Link href={sectionHref} className="hover:text-brand">{it.headline}</Link>
                        : it.headline}
                    </p>
                    {clients.length > 0 && (
                      <p className="text-3xs text-ps-hint mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
                        {clients.map((c) => (
                          <Link key={c.client_id} href={digestClientHref(it.key, c.client_id)}
                            className="hover:text-brand">
                            {c.client_name} ({c.count})
                          </Link>
                        ))}
                        {more > 0 && <span>and {more} more</span>}
                      </p>
                    )}
                    <p className="text-3xs text-ps-hint mt-0.5">From {it.source}.</p>
                  </div>
                </div>
              );
            })}
          </div>

          {digest.gaps.length > 0 && (
            <details className="px-5 py-3 border-t border-ps-border">
              <summary className="text-3xs text-ps-label cursor-pointer">
                What this digest does not cover ({digest.gaps.length})
              </summary>
              {/* The shared list, tone `withheld`: the digest deliberately says
                  nothing here because it cannot derive it — a nil meaning "we
                  cannot see it", not "there was none". */}
              <GapList gaps={digest.gaps} tone="withheld" bulleted className="mt-2" />
            </details>
          )}
        </div>
      )}
    </div>
  );
}
