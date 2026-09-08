"use client";

import { useEffect, useMemo, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

/** One probe for "what can this build demo", shared by every module screen so
 *  no page ever offers a File-demo button the server would refuse. */
export async function fetchFilingDemoCapabilities(): Promise<{ enabled: boolean; flows: string[] }> {
  try {
    const r = await apiFetch("/api/filing-demo/capabilities");
    if (!r.success) return { enabled: false, flows: [] };
    const d = r.data as { enabled?: boolean; flows?: string[] };
    return { enabled: Boolean(d.enabled), flows: d.flows ?? [] };
  } catch {
    // A capability that cannot be confirmed is treated as absent — showing a
    // control on a failed probe is how the dead demo button happened.
    return { enabled: false, flows: [] };
  }
}

/**
 * The one renderer for every filing-demo walk-through.
 *
 * The server (services/filing_demo/) builds each flow as a list of stages in
 * a small fixed vocabulary — summary, table, warning, declaration, signature,
 * otp, transmit, result — in the REAL portal's order for that filing. This
 * component renders whatever it is given, so a new statutory flow is a new
 * server-side definition and zero new UI.
 *
 * Three behaviours are built in rather than per-flow:
 *   - a declaration gates progress until ticked and a signatory is chosen,
 *     exactly as the portals keep their file buttons disabled;
 *   - a signature method with otp=true routes through the otp stage (EVC,
 *     Aadhaar OTP); one with otp=false (DSC/emSigner) skips it;
 *   - the transmit stage plays its steps on a timer and advances itself.
 *
 * THE OTP STAGE HAS NO INPUT, DELIBERATELY. It used to take six digits and
 * accept any of them. The step is real and stays in the sequence — but a box
 * in this app that accepts a portal OTP is a credential-capture surface
 * whatever it is labelled (CLAUDE.md says so about real filing, and a demo
 * that trains the habit is how the habit arrives). It is also the more
 * faithful rendering: the code is typed on gst.gov.in or incometax.gov.in,
 * never in the software that prepared the return, so a field here taught the
 * step in the wrong PLACE. This is the one point where the walk-through is
 * deliberately less imitative than the portal.
 *
 * And FIVE things are unconditional, because they are the terms the demo
 * exists under, and the component has no code path that omits any of them:
 * the DEMO banner never scrolls away; the transmit stage says nothing is
 * being sent while it plays; the result panel says in its own heading that
 * this is what the portal WOULD have shown; the realistic reference always
 * carries its SPECIMEN badge and note; and the truth lines (nothing filed,
 * how to file for real, what changes when it is) always render.
 */

interface Figure { label: string; paise?: number; text?: string }
interface Cell { text?: string; paise?: number }
interface SignatureMethod { key: string; label: string; note: string; otp: boolean }
interface Stage {
  kind: "summary" | "table" | "warning" | "declaration" | "signature" | "otp" | "transmit" | "result";
  title?: string; note?: string; figures?: Figure[]; cta?: string;
  columns?: string[]; rows?: Cell[][]; footer?: Cell[] | null;
  text?: string; signatory_label?: string; signatory_options?: string[];
  methods?: SignatureMethod[]; prompt?: string;
  steps?: { key: string; label: string }[];
  authority?: string; reference_label?: string; specimen?: string;
  specimen_note?: string; filed_line?: string; truth?: string[];
}

export interface FilingDemoScript {
  simulated: boolean; filed: boolean; flow: string;
  title: string; subtitle: string; acknowledgement: string;
  real_channel: { how: string; software_permitted: boolean; note: string };
  /** The registration that gates real filing for this flow, and what the CA
   *  will do differently once it exists. Required server-side — see
   *  services/filing_demo/common.envelope. */
  when_this_is_real: string;
  stages: Stage[]; disclaimer: string;
}

function rupees(paise: number) {
  const sign = paise < 0 ? "-" : "";
  return `${sign}₹${(Math.abs(paise) / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function cell(c: Cell) {
  return c.paise !== undefined ? rupees(c.paise) : (c.text ?? "");
}

const DemoBadge = () => (
  <span className="ml-2 align-middle text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-400 text-amber-950">DEMO</span>
);

export default function FilingDemoWizard({
  flow, clientId, refData, onClose,
}: {
  flow: string;
  clientId: string;
  /** Flow-specific addressing, e.g. { return_id } or { quarter, fy }. */
  refData: Record<string, unknown>;
  onClose: () => void;
}) {
  const [script, setScript] = useState<FilingDemoScript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);

  const [declared, setDeclared] = useState(false);
  const [signatory, setSignatory] = useState("");
  const [method, setMethod] = useState<SignatureMethod | null>(null);
  // No OTP state. There is no OTP field — see the header. Removing the state
  // as well as the input is the point: a component that still holds a
  // six-digit value is one edit away from rendering a box for it again.
  const [done, setDone] = useState(-1);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(`/api/filing-demo/${flow}/preview`, {
          method: "POST",
          body: JSON.stringify({ client_id: clientId, ref: refData }),
        });
        if (cancelled) return;
        if (!r.success) { setError(r.error ?? "Could not start the demo."); return; }
        setScript(r.data as FilingDemoScript);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not start the demo.");
      }
    })();
    return () => { cancelled = true; };
    // refData is stable for the life of one wizard mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, clientId]);

  const stages = useMemo(() => script?.stages ?? [], [script]);
  const stage = stages[idx];

  /** Next stage index, skipping the otp stage when the chosen method needs none. */
  function nextFrom(i: number, chosen: SignatureMethod | null): number {
    let n = i + 1;
    if (stages[n]?.kind === "otp" && chosen && !chosen.otp) n += 1;
    return n;
  }
  const advance = () => setIdx((i) => nextFrom(i, method));
  const back = () => setIdx((i) => {
    let p = i - 1;
    if (stages[p]?.kind === "otp" && method && !method.otp) p -= 1;
    return Math.max(0, p);
  });

  // The transmit stage plays itself. Paced for legibility, not to imitate a
  // real round trip — nothing is being transmitted.
  useEffect(() => {
    if (stage?.kind !== "transmit") return;
    const steps = stage.steps ?? [];
    let cancelled = false;
    const timers = steps.map((_, i) =>
      setTimeout(() => { if (!cancelled) setDone(i); }, 650 * (i + 1)));
    timers.push(setTimeout(() => {
      if (!cancelled) setIdx((i) => i + 1);
    }, 650 * (steps.length + 1)));
    return () => { cancelled = true; timers.forEach(clearTimeout); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage?.kind, idx]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Never scrolls away: whoever glances at this screen — including the
            person who did not watch it start — has to see what it is. */}
        <div className="sticky top-0 px-5 py-3 bg-amber-100 border-b-2 border-amber-400 z-10">
          <p className="text-sm font-bold text-amber-900">DEMO — nothing is being filed</p>
          <p className="text-xs text-amber-900 mt-0.5">
            A walk-through of the real filing sequence. No data leaves PracticeSync
            and no government system is contacted.
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {error && <p className="text-sm text-red-600">{error}</p>}
          {!script && !error && <TableSkeleton rows={5} />}

          {script && (
            <>
              <div className="flex items-baseline justify-between border-b pb-2">
                <p className="text-sm font-semibold text-[#1E293B]">{script.title}</p>
                <p className="text-xs font-mono text-[#64748B]">{script.subtitle}</p>
              </div>

              {stage?.kind === "summary" && (
                <>
                  <p className="text-sm font-semibold text-[#334155]">{stage.title}</p>
                  {stage.note && <p className="text-xs text-[#64748B]">{stage.note}</p>}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                    {(stage.figures ?? []).map((f) => (
                      <div key={f.label}>
                        <p className="text-xs text-[#64748B]">{f.label}</p>
                        <p className="font-medium">
                          {f.paise !== undefined ? rupees(f.paise) : (f.text ?? "")}
                        </p>
                      </div>
                    ))}
                  </div>
                  <button onClick={advance}
                    className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                    {stage.cta ?? "Proceed"}
                  </button>
                </>
              )}

              {stage?.kind === "table" && (
                <>
                  <p className="text-sm font-semibold text-[#334155]">{stage.title}</p>
                  {stage.note && <p className="text-xs text-[#64748B]">{stage.note}</p>}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-[#F8FAFC] text-[#64748B]">
                        <tr>{(stage.columns ?? []).map((c, i) => (
                          <th key={c} className={`px-3 py-2 font-medium ${i === 0 ? "text-left" : "text-right"}`}>{c}</th>
                        ))}</tr>
                      </thead>
                      <tbody>
                        {(stage.rows ?? []).map((row, ri) => (
                          <tr key={ri} className="border-t">
                            {row.map((c, ci) => (
                              <td key={ci} className={`px-3 py-1.5 ${ci === 0 ? "" : "text-right font-mono"}`}>{cell(c)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                      {stage.footer && (
                        <tfoot className="bg-[#F8FAFC] font-semibold">
                          <tr className="border-t-2">
                            {stage.footer.map((c, ci) => (
                              <td key={ci} className={`px-3 py-2 ${ci === 0 ? "" : "text-right font-mono"}`}>{cell(c)}</td>
                            ))}
                          </tr>
                        </tfoot>
                      )}
                    </table>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={advance}
                      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                      {stage.cta ?? "Proceed"}
                    </button>
                    <button onClick={back} className="px-3 py-2 border rounded text-sm">Back</button>
                  </div>
                </>
              )}

              {stage?.kind === "warning" && (
                <>
                  <div className="border-2 border-amber-400 bg-amber-50 rounded p-3">
                    <p className="text-sm font-semibold text-amber-900">{stage.text}</p>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={advance}
                      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                      {stage.cta ?? "Proceed"}
                    </button>
                    <button onClick={back} className="px-3 py-2 border rounded text-sm">Back</button>
                  </div>
                </>
              )}

              {stage?.kind === "declaration" && (
                <>
                  <label className="flex gap-2 items-start text-xs text-[#334155]">
                    <input type="checkbox" checked={declared} className="mt-0.5"
                      onChange={(e) => setDeclared(e.target.checked)} />
                    <span>{stage.text}</span>
                  </label>
                  <div>
                    <label className="text-xs text-[#64748B] block mb-1">{stage.signatory_label}</label>
                    <select value={signatory} onChange={(e) => setSignatory(e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border rounded">
                      <option value="">Select…</option>
                      {(stage.signatory_options ?? []).map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                    {stage.note && <p className="text-[11px] text-amber-800 mt-1">{stage.note}</p>}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        // Reset for any LATER declaration stage: MCA's dual
                        // signature (director's DSC, then the practising
                        // professional's) is two declaration+signature pairs,
                        // and the second must not arrive pre-ticked — each
                        // person affirms their own statement.
                        setDeclared(false); setSignatory("");
                        advance();
                      }}
                      disabled={!declared || !signatory}
                      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-40">
                      Continue
                    </button>
                    <button onClick={back} className="px-3 py-2 border rounded text-sm">Back</button>
                  </div>
                  {(!declared || !signatory) && (
                    <p className="text-[11px] text-[#94A3B8]">
                      The portal keeps this disabled until the declaration is ticked and a
                      signatory chosen. So does the demo.
                    </p>
                  )}
                </>
              )}

              {stage?.kind === "signature" && (
                <>
                  <div className="flex flex-wrap gap-2">
                    {(stage.methods ?? []).map((m) => (
                      <button key={m.key} title={m.note}
                        onClick={() => { setMethod(m); setIdx((i) => nextFrom(i, m)); }}
                        className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                        {m.label}
                      </button>
                    ))}
                    <button onClick={back} className="px-3 py-2 border rounded text-sm">Back</button>
                  </div>
                  <ul className="text-[11px] text-[#64748B] space-y-0.5">
                    {(stage.methods ?? []).map((m) => (
                      <li key={m.key}><strong>{m.label}:</strong> {m.note}</li>
                    ))}
                  </ul>
                </>
              )}

              {stage?.kind === "otp" && (
                <>
                  <p className="text-sm text-[#334155]">{stage.prompt}</p>
                  {/* No input, and the empty boxes say why. The step is shown
                      because it is real; the field is refused because a box
                      in this app that takes a portal OTP is a credential
                      surface whatever it is labelled — and because the code
                      is typed on the portal, not here, so an input would put
                      the step in the wrong place. */}
                  <div className="rounded border-2 border-dashed border-[#CBD5E1] bg-[#F8FAFC] p-3">
                    <div className="flex gap-1.5" aria-hidden="true">
                      {[0, 1, 2, 3, 4, 5].map((i) => (
                        <span key={i}
                          className="w-8 h-9 rounded border border-[#CBD5E1] bg-white" />
                      ))}
                    </div>
                    <p className="text-[11px] text-[#64748B] mt-2">
                      This is the portal&apos;s screen, not one PracticeSync has.
                      Entered on the authority&apos;s own site.
                    </p>
                  </div>
                  {stage.note && <p className="text-[11px] text-amber-800">{stage.note}</p>}
                  <div className="flex gap-2">
                    <button onClick={advance}
                      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                      Continue
                    </button>
                    <button onClick={back} className="px-3 py-2 border rounded text-sm">Back</button>
                  </div>
                </>
              )}

              {stage?.kind === "transmit" && (
                <>
                  <ul className="space-y-2">
                    {(stage.steps ?? []).map((st, i) => (
                      <li key={st.key} className="flex items-center gap-2 text-sm">
                        <span className={`w-4 text-center ${i <= done ? "text-green-600" : "text-[#CBD5E1]"}`}>
                          {i <= done ? "✓" : "○"}
                        </span>
                        <span className={i <= done ? "text-[#334155]" : "text-[#94A3B8]"}>{st.label}</span>
                      </li>
                    ))}
                  </ul>
                  {/* Unconditional. This is the one stage whose appearance
                      most resembles a real upload — ticks appearing one by
                      one — and the one most likely to be screenshotted
                      mid-play. The banner above says it too; this says it
                      inside the frame the ticks are in. */}
                  <p className="text-xs font-semibold text-amber-800 border-t pt-2">
                    Nothing is being sent. These steps are played on a timer to
                    show the portal&apos;s sequence; there is no connection to any
                    government system behind them.
                  </p>
                </>
              )}

              {stage?.kind === "result" && (
                <div className="space-y-3">
                  <div className="rounded border-2 border-green-300 bg-green-50 p-4 space-y-2">
                    {/* The portal's own words, and then immediately whose
                        words they are. "✓ Filing successful" is the single
                        most dangerous string in this product: it is what
                        makes the walk-through recognisable and it is the
                        sentence someone could screenshot. It keeps the badge
                        it always had, and now cannot appear without the line
                        below it — which is rendered here, not supplied by a
                        flow, so no flow can leave it out. */}
                    <p className="text-sm font-bold text-green-800">✓ Filing successful<DemoBadge /></p>
                    <p className="text-xs font-semibold text-amber-800">
                      That is what the portal would say. This is PracticeSync,
                      nothing was sent, and no return has been filed.
                    </p>
                    <div>
                      <p className="text-[11px] text-green-800">{stage.reference_label}</p>
                      <p className="text-lg font-mono font-semibold tracking-wider text-green-900">
                        {stage.specimen}
                        <span className="ml-2 align-middle text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-400 text-amber-950">SPECIMEN</span>
                      </p>
                      <p className="text-[11px] text-amber-800">{stage.specimen_note}</p>
                    </div>
                    <p className="text-xs text-green-800">{stage.filed_line}</p>
                  </div>
                  <div className="rounded border border-amber-300 bg-amber-50 p-3 space-y-1">
                    {(stage.truth ?? []).map((t) => (
                      <p key={t} className="text-xs text-amber-900">{t}</p>
                    ))}
                    <p className="text-xs font-mono text-amber-900 break-all">{script.acknowledgement}</p>
                    <p className="text-xs text-amber-900">{script.disclaimer}</p>
                  </div>
                  <div className="rounded border border-[#E2E8F0] bg-[#F8FAFC] p-3">
                    <p className="text-[11px] font-semibold text-[#334155]">How this is really filed today</p>
                    <p className="text-[11px] text-[#64748B]">{script.real_channel.how}</p>
                    <p className="text-[11px] text-[#64748B] mt-1">
                      {script.real_channel.software_permitted
                        ? "Software IS permitted to transmit this filing in India — that is the API integration on the roadmap."
                        : "No public API lets software transmit this today; the roadmap integration depends on the authority."}
                      {" "}{script.real_channel.note}
                    </p>
                  </div>
                  {/* What changes when this is real. The server requires it of
                      every flow (services/filing_demo/common.envelope will not
                      build without one), so this block has no empty state to
                      design for — and it is the half a CA being shown the
                      product is entitled to: which registration is missing,
                      who has to obtain it, and what they will do differently
                      the day it arrives. */}
                  <div className="rounded border border-[#E2E8F0] bg-white p-3">
                    <p className="text-[11px] font-semibold text-[#334155]">What changes when this is real</p>
                    <p className="text-[11px] text-[#64748B]">{script.when_this_is_real}</p>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t flex justify-between items-center">
          <span className="text-[11px] text-[#94A3B8]">
            {stage?.kind === "result" ? "Nothing was transmitted." : "Step through as the portal would."}
          </span>
          <button onClick={onClose}
            className="px-3 py-1.5 text-sm border rounded hover:bg-[#F8FAFC]">Close</button>
        </div>
      </div>
    </div>
  );
}
