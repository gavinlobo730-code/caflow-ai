"use client";

/**
 * §37 AMENDMENTS AND THE EXCEPTION REPORT (GST-13).
 *
 * CGST Act §37: a filed GSTR-1 can NEVER be revised. If an invoice in a filed
 * period is edited, raised late or cancelled, the books move and the return
 * cannot — the correction is declared in a LATER return's amendment tables:
 * 9A for invoices, 9C for credit and debit notes, 10 for B2C-others, each
 * naming the original document so GSTN knows which entry it supersedes.
 *
 * Three finished capabilities sat behind that and no screen reached any:
 *
 *   GET  /gst-workspace/gstr1/exceptions   what the books say now vs the return
 *   GET  /gst-workspace/gstr1/amendments   what THIS period must carry
 *   POST /gst/gstr1/with-amendments        the payload that actually carries it
 *
 * The third is the one that stings. Its own docstring records that the
 * amendment service had worked out the outstanding corrections since it was
 * built, that merge_into_payload could fold them into a payload for just as
 * long, and that NOTHING CONNECTED THE TWO — so the route was written to
 * connect them, and then had no caller either. A CA could be told an amendment
 * was due and had no way to produce the return that declares it.
 *
 * ZERO BUSINESS LOGIC HERE. Which table a correction goes in, whether a window
 * is still open, and what the merged payload contains are all the server's.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  GSTExceptionDoc, GSTHeads, GSTR1AmendmentsReport, GSTR1ExceptionReport,
  GSTR1WithAmendments,
} from "@/lib/api";
// MMYYYY, and NOT the YYYY-MM every other month in this product uses — see
// lib/gst/period. The two transpose, and "202606" is a well-formed six-digit
// string that GSTN reads as month 20.
import { gstPeriodLabel as periodLabel, isGstPeriod as isPeriod } from "@/lib/gst/period";
import { Callout } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { objectWithLists } from "@/lib/api/shape";

function money(paise?: number | null) {
  const p = Number(paise ?? 0);
  const sign = p < 0 ? "−" : "";
  // D5: two decimals. `toLocaleString("en-IN")` with no options
  // defaults to maximumFractionDigits 3 and minimumFractionDigits 0, so a
  // paise figure came out as ₹1,18,000.5 — and with Math.floor/trunc in
  // front of it, as ₹1,18,000 with the paise gone. A column where some rows
  // carry paise and some do not cannot be added up by eye.
  return `${sign}${formatPaise(Math.abs(p))}`;
}

const FIELD =
  "border border-ps-border rounded-lg px-2 py-1.5 text-sm outline-none focus:border-brand";

/** The §37(3)/§16(4) window, as the server graded it. Never recomputed here:
 *  the limit is 30 November following the FY OR the date GSTR-9 was furnished,
 *  whichever is EARLIER, and filing the annual return early shuts it early. */
function WindowBadge({ window: w }: { window?: { status?: string; closes_on?: string } }) {
  if (!w?.status) return null;
  const tone = w.status === "expired" ? "bg-state-problem-surface text-state-problem border-state-problem-border"
    : w.status === "closing_soon" ? "bg-state-attention-surface text-amber-800 border-state-attention-border"
    : "bg-emerald-50 text-emerald-700 border-emerald-200";
  return (
    <span className={`text-3xs px-1.5 py-0.5 rounded-full border ${tone}`}>
      {w.status === "expired" ? "window closed"
        : w.status === "closing_soon" ? "closing soon" : "open"}
      {w.closes_on ? ` · ${w.closes_on}` : ""}
    </span>
  );
}

function HeadRow({ heads }: { heads?: GSTHeads }) {
  if (!heads) return <span className="text-ps-disabled">—</span>;
  return (
    <span className="font-mono text-2xs">
      {money(heads.taxable_paise)}
      <span className="text-ps-hint">
        {" "}· C {money(heads.cgst_paise)} · S {money(heads.sgst_paise)}
        {" "}· I {money(heads.igst_paise)}
        {heads.cess_paise ? ` · Cess ${money(heads.cess_paise)}` : ""}
      </span>
    </span>
  );
}

function DocList({ title, why, docs }: {
  title: string; why: string; docs?: GSTExceptionDoc[];
}) {
  if (!docs?.length) return null;
  return (
    <div className="rounded-xl border border-ps-border p-3">
      <p className="text-xs font-semibold text-ps-ink">
        {title} <span className="text-ps-hint font-normal">· {docs.length}</span>
      </p>
      <p className="text-3xs text-ps-hint mt-0.5 max-w-[80ch]">{why}</p>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-2xs">
          <thead>
            <tr className="text-left text-ps-label border-b border-ps-border">
              <th className="py-1.5 pr-2">Document</th>
              <th className="py-1.5 pr-2">Counterparty</th>
              <th className="py-1.5 pr-2">Declare in</th>
              <th className="py-1.5 pr-2">Filed</th>
              <th className="py-1.5 pr-2">Books</th>
              <th className="py-1.5">Difference</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d, i) => (
              <tr key={`${d.doc_no ?? "row"}-${i}`} className="border-b border-ps-border align-top">
                <td className="py-1.5 pr-2">
                  <span className="font-mono text-ps-ink">{d.doc_no ?? "—"}</span>
                  {d.doc_date && <span className="block text-3xs text-ps-hint">{d.doc_date}</span>}
                  {d.filed_section && d.books_section && (
                    <span className="block text-3xs text-state-attention">
                      {d.filed_section} → {d.books_section}
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-2 text-ps-label">{d.counterparty ?? "—"}</td>
                <td className="py-1.5 pr-2">
                  <span className="text-3xs px-1.5 py-0.5 rounded-full bg-ps-muted text-ps-label">
                    {d.declare_in ?? "—"}
                  </span>
                </td>
                <td className="py-1.5 pr-2"><HeadRow heads={d.filed} /></td>
                <td className="py-1.5 pr-2"><HeadRow heads={d.books} /></td>
                <td className="py-1.5"><HeadRow heads={d.delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AmendmentsTab({ clientId }: { clientId: string }) {
  // Two periods, and they are genuinely different questions: which FILED
  // period to audit for drift, and which period is being PREPARED and must
  // carry the corrections. One control for both would ask the wrong one.
  const [filedPeriod, setFiledPeriod] = useState("");
  const [targetPeriod, setTargetPeriod] = useState("");

  const [exceptions, setExceptions] = useState<GSTR1ExceptionReport | null>(null);
  const [amendments, setAmendments] = useState<GSTR1AmendmentsReport | null>(null);
  const [built, setBuilt] = useState<GSTR1WithAmendments | null>(null);
  const [busy, setBusy] = useState<"exceptions" | "amendments" | "build" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = useCallback(async (
    kind: "exceptions" | "amendments" | "build", period: string,
  ) => {
    setBusy(kind); setErr(null);
    try {
      if (kind === "exceptions") {
        const res = await api.gstWorkspace.gstr1Exceptions(clientId, period);
        if (!res?.success) throw new Error(res?.error ?? "That did not load.");
        setExceptions(res.data);
      } else if (kind === "amendments") {
        const res = await api.gstWorkspace.gstr1Amendments(clientId, period);
        if (!res?.success) throw new Error(res?.error ?? "That did not load.");
        setAmendments(objectWithLists<GSTR1AmendmentsReport>(res.data, "carry_forward", "closing_soon", "expired", "needs_decision", "sections", "source_periods"));
      } else {
        const res = await api.gstReturns.gstr1WithAmendments(
          { client_id: clientId, period });
        if (!res?.success) throw new Error(res?.error ?? "That did not build.");
        setBuilt(res.data);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not work.");
      if (kind === "exceptions") setExceptions(null);
      if (kind === "amendments") setAmendments(null);
      if (kind === "build") setBuilt(null);
    } finally { setBusy(null); }
  }, [clientId]);

  useEffect(() => { setExceptions(null); setBuilt(null); setAmendments(null); }, [clientId]);

  const docs = exceptions?.documents;

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-ps-border bg-ps-bg p-3">
        <p className="text-xs text-ps-body">
          A filed GSTR-1 can never be revised (CGST Act §37). A correction is
          declared in a later return&apos;s amendment tables — <b>9A</b> invoices,
          {" "}<b>9C</b> credit and debit notes, <b>10</b> B2C-others.
        </p>
        <p className="text-3xs text-ps-hint mt-1">
          Nothing on this tab files anything or alters a return.
        </p>
      </div>

      {err && <Callout tone="problem">{err}</Callout>}

      {/* ── 1. What drifted in a period already filed ────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-end gap-2 flex-wrap">
          <label className="text-2xs text-ps-label">
            Filed period to check
            <input value={filedPeriod} placeholder="062026"
              onChange={(e) => setFiledPeriod(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
              inputMode="numeric" className={`${FIELD} block mt-1 w-32`} />
          </label>
          <button onClick={() => run("exceptions", filedPeriod)}
            disabled={busy !== null || !isPeriod(filedPeriod)}
            className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body disabled:opacity-40">
            {busy === "exceptions" ? "Comparing…" : "Compare books to the return"}
          </button>
          {isPeriod(filedPeriod) && (
            <span className="text-2xs text-ps-hint pb-1.5">{periodLabel(filedPeriod)}</span>
          )}
        </div>

        {exceptions && exceptions.status !== "ok" && (
          <div className={`rounded-lg border p-3 ${
            exceptions.status === "payload_missing"
              ? "border-state-attention-border bg-state-attention-surface" : "border-ps-border bg-white"}`}>
            <p className={`text-xs ${
              exceptions.status === "payload_missing" ? "text-amber-800" : "text-ps-label"}`}>
              {exceptions.message}
            </p>
          </div>
        )}

        {exceptions?.status === "ok" && (
          exceptions.clean ? (
            <p className="text-xs px-3 py-2 rounded-lg bg-green-50 text-green-700">
              The books still agree with the {periodLabel(exceptions.period)} return as filed
              {exceptions.arn ? ` (ARN ${exceptions.arn})` : ""}. Nothing to amend.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-3 flex-wrap text-xs">
                <span className="font-semibold text-ps-ink">
                  {exceptions.finding_count} finding{exceptions.finding_count === 1 ? "" : "s"}
                </span>
                {exceptions.arn && <span className="text-ps-hint">ARN {exceptions.arn}</span>}
                {exceptions.totals && (
                  <span className="text-ps-label">
                    Net difference <HeadRow heads={exceptions.totals.delta} />
                  </span>
                )}
              </div>

              {/* Four kinds, four different actions — which is why the server
                  returns them as four lists rather than one. */}
              <DocList
                title="Filed, and no longer in the books"
                why="The most serious of the four: a document was deleted or cancelled after it was declared, and a filed return cannot simply drop it."
                docs={docs?.missing_from_books} />
              <DocList
                title="Now in a different GSTR-1 table"
                why="Amending the value alone would leave it declared in the wrong table — an SEZ supply filed as B2B, say."
                docs={docs?.reclassified} />
              <DocList
                title="Figures changed since filing"
                why="Filed and still present, with different amounts."
                docs={docs?.amount_changed} />
              <DocList
                title="In the books, never filed"
                why="Not an amendment at all — there is no filed entry to supersede, so it belongs in the CURRENT period's ordinary table."
                docs={docs?.missing_from_return} />

              {!!exceptions.b2cs?.changed?.length && (
                <div className="rounded-xl border border-ps-border p-3">
                  <p className="text-xs font-semibold text-ps-ink">
                    B2C-others{" "}
                    <span className="text-ps-hint font-normal">
                      · {exceptions.b2cs.changed.length}
                    </span>
                  </p>
                  <p className="text-3xs text-ps-hint mt-0.5 max-w-[80ch]">
                    {exceptions.b2cs.note}
                  </p>
                  <table className="w-full text-2xs mt-2">
                    <thead>
                      <tr className="text-left text-ps-label border-b border-ps-border">
                        <th className="py-1.5 pr-2">Place of supply</th>
                        <th className="py-1.5 pr-2">Rate</th>
                        <th className="py-1.5 pr-2">Filed</th>
                        <th className="py-1.5 pr-2">Books</th>
                        <th className="py-1.5">Difference</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exceptions.b2cs.changed.map((r, i) => (
                        <tr key={i} className="border-b border-ps-border">
                          <td className="py-1.5 pr-2 text-ps-ink">
                            {(r as { place_of_supply?: string }).place_of_supply ?? "—"}
                          </td>
                          <td className="py-1.5 pr-2">
                            {String((r as { rate?: number }).rate ?? "—")}
                          </td>
                          <td className="py-1.5 pr-2"><HeadRow heads={r.filed} /></td>
                          <td className="py-1.5 pr-2"><HeadRow heads={r.books} /></td>
                          <td className="py-1.5"><HeadRow heads={r.delta} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        )}
      </section>

      {/* ── 2. What the period being prepared has to carry ───────────────── */}
      <section className="space-y-3 border-t border-ps-border pt-5">
        <div className="flex items-end gap-2 flex-wrap">
          <label className="text-2xs text-ps-label">
            Period being prepared
            <input value={targetPeriod} placeholder="072026"
              onChange={(e) => setTargetPeriod(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
              inputMode="numeric" className={`${FIELD} block mt-1 w-32`} />
          </label>
          <button onClick={() => run("amendments", targetPeriod)}
            disabled={busy !== null || !isPeriod(targetPeriod)}
            className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body disabled:opacity-40">
            {busy === "amendments" ? "Checking…" : "What must this return carry?"}
          </button>
          <button onClick={() => run("build", targetPeriod)}
            disabled={busy !== null || !isPeriod(targetPeriod)}
            className="px-3 py-1.5 text-xs rounded-lg bg-brand-dark text-white disabled:opacity-40">
            {busy === "build" ? "Building…" : "Build GSTR-1 with amendments"}
          </button>
        </div>

        {amendments && (
          <div className="space-y-3">
            <p className="text-xs text-ps-body">
              {amendments.counts.amendments
                ? <>Carrying <b>{amendments.counts.amendments}</b> amendment
                    {amendments.counts.amendments === 1 ? "" : "s"} from{" "}
                    {amendments.source_periods.map(periodLabel).join(", ")}.</>
                : <>Nothing outstanding to amend into {periodLabel(amendments.period)}.</>}
              {amendments.as_of && (
                <span className="text-ps-hint"> As at {amendments.as_of}.</span>
              )}
            </p>

            {/* BEYOND REPAIR, AND SAID SO. The §37(3)/§16(4) window has closed
                on these — the output tax stays understated or the credit is
                simply lost, and nothing in the product can fix it. They are
                shown because a CA needs to know, not because there is an
                action. */}
            {!!amendments.expired?.length && (
              <div className="rounded-lg border border-state-problem-border bg-state-problem-surface p-3">
                <p className="text-2xs font-semibold text-state-problem">
                  {amendments.expired.length} period(s) beyond repair — the correction
                  window has closed
                </p>
                {amendments.expired.map((e, i) => (
                  <p key={i} className="text-2xs text-state-problem mt-0.5">
                    · {periodLabel(e.period)} <WindowBadge window={e.window} />
                    {e.window?.reason ? ` — ${e.window.reason}` : ""}
                  </p>
                ))}
              </div>
            )}

            {!!amendments.closing_soon?.length && (
              <div className="rounded-lg border border-state-attention-border bg-state-attention-surface p-3">
                <p className="text-2xs font-semibold text-amber-800">
                  Still fixable, but not for much longer
                </p>
                {amendments.closing_soon.map((e, i) => (
                  <p key={i} className="text-2xs text-amber-800 mt-0.5">
                    · {periodLabel(e.period)} <WindowBadge window={e.window} />
                  </p>
                ))}
              </div>
            )}

            {!!amendments.needs_decision?.length && (
              <div className="rounded-lg border border-state-attention-border bg-state-attention-surface p-3">
                <p className="text-2xs font-semibold text-amber-800">
                  {amendments.needs_decision.length} need your decision
                </p>
                <p className="text-3xs text-amber-800 mt-0.5 max-w-[80ch]">
                  Cancelled after the period was filed. There is no single right answer —
                  amend to nil, or raise a credit note — so nothing here chooses one.
                </p>
              </div>
            )}

            {!!amendments.carry_forward?.length && (
              <div className="rounded-lg border border-ps-border bg-white p-3">
                <p className="text-2xs font-semibold text-ps-ink">
                  {amendments.carry_forward.length} to carry forward, not amend
                </p>
                <p className="text-3xs text-ps-hint mt-0.5 max-w-[80ch]">
                  Raised after their period was filed, so never declared — there is
                  nothing to supersede and they belong in this period&apos;s ordinary
                  tables.
                </p>
              </div>
            )}
          </div>
        )}

        {built && (
          <div className="rounded-xl border border-ps-border p-3 space-y-2">
            <p className="text-xs font-semibold text-ps-ink">
              GSTR-1 for {periodLabel(targetPeriod)}, with amendments merged
            </p>
            <p className="text-2xs text-ps-label">
              Amendment sections in the payload:{" "}
              {built.amendments?.sections?.length
                ? <b>{built.amendments.sections.join(", ")}</b>
                : <span className="text-ps-hint">none</span>}
            </p>
            <p className="text-3xs text-ps-hint max-w-[80ch]">
              Out-of-time corrections are excluded upstream, so nothing here can declare
              an amendment the law no longer allows. Documents needing a decision and
              invoices never declared stay OUT of the payload — neither is an amendment.
            </p>
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              <button
                onClick={() => {
                  const blob = new Blob([JSON.stringify(built.payload ?? {}, null, 2)],
                                        { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `GSTR1-${targetPeriod}-with-amendments.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">
                Download the payload
              </button>
              <span className="text-3xs text-state-attention">
                CA REVIEW REQUIRED — uploading it to gst.gov.in stays a deliberate human act.
              </span>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
