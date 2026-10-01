"use client";

/**
 * FORM GST ITC-04 — goods sent to a job worker and received back (GST-30).
 *
 * CGST Rule 45(3) has the principal report, in a statement of its own, the
 * goods sent for job work and the goods that came back. A manufacturer client
 * had the challans entered and the statement typed out again from them; and
 * because a challan held ONE date for the whole of its goods coming back, "one
 * challan sent, part returned" could not be recorded at all.
 *
 * THIS SCREEN DECIDES NOTHING. Which challans are on the form, which window
 * carries them, what is still with the job worker and the s.143 date for it are
 * `domain/gst/itc_04.py`'s answers, served by the sales-cycle router. The form's
 * numbering and column names are `[S]`-graded there and the sentence saying so
 * is rendered here, not omitted.
 *
 * WHICH PERIOD APPLIES IS NOT CHOSEN. Rule 45(3)'s cadence turns on the
 * principal's own preceding-year turnover and on a limit this product does not
 * hold, so every reading's windows are listed and the CA opens the one that
 * applies. A turnover on record is shown as context and is not turned into an
 * answer.
 *
 * IT IS PREPARE-ONLY. ITC-04 is furnished on the GST portal by the principal;
 * nothing here reaches a portal, posts a journal or moves stock.
 *
 * A FAILED READ IS NOT AN EMPTY STATEMENT. An empty "still with the job worker"
 * list means every lot is back, so a silent failure is a false clean result — a
 * failure is said, in one line.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Clock, Factory } from "lucide-react";
import {
  api,
  type DeemedSupplyClock,
  type Itc04Balance,
  type Itc04Gap,
  type Itc04Reading,
  type Itc04Statement,
  type Itc04Table4Row,
  type Itc04Table5aRow,
  type Itc04Window,
} from "@/lib/api";
import { arrayOrEmpty, objectOrNull, objectWithLists } from "@/lib/api/shape";
import { YearPicker } from "@/components/ui/year-picker";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { formatPaise } from "@/lib/money/format";
import { BLANK_LOT, clockText, clockTone, lotBody, type LotForm } from "@/lib/gst/itc04";

const TONE_CLASS = {
  problem: "text-state-problem",
  attention: "text-state-attention",
  neutral: "text-ps-body",
} as const;

type Msg = { type: "ok" | "err"; text: string } | null;
type BalanceLine = Itc04Balance["lines"][number];

function ClockLine({ clock }: { clock: DeemedSupplyClock | null }) {
  // A balance served with no clock is NOT one with no deadline.
  if (!clock) {
    return <span className="text-xs text-state-attention">The s.143 clock was not served for this challan.</span>;
  }
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${TONE_CLASS[clockTone(clock)]}`}>
      {clock.overdue === true ? <AlertTriangle size={11} /> : <Clock size={11} />}
      {clockText({ ...clock, gaps: arrayOrEmpty<string>(clock.gaps) })}
    </span>
  );
}

export function Itc04Panel({ clientId, onChanged }: {
  clientId: string;
  /** Called after a lot is recorded, so a challan list on the same screen can
   *  reload — the last lot marks the challan received back. */
  onChanged?: () => void;
}) {
  const [year, setYear] = useState(() => financialYearChoicesAround()[0] ?? "");
  const [windowKey, setWindowKey] = useState<string | null>(null);
  const [st, setSt] = useState<Itc04Statement | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [lotFor, setLotFor] = useState<string | null>(null);
  const [lot, setLot] = useState<LotForm>({ ...BLANK_LOT });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || !year) return;
    setLoading(true);
    setFailed(false);
    try {
      const r = await api.salesCycle.itc04(clientId, year, windowKey);
      // `objectWithLists`, not `r.data`: `{}` is truthy and `.map` on a missing
      // list would throw. The lists nested inside a table or a reading are
      // read through `arrayOrEmpty` below, because naming them here is not enough.
      const got = r.success
        ? objectWithLists<Itc04Statement>(r.data, "readings", "outstanding", "gaps")
        : null;
      setSt(got);
      setFailed(got === null);
    } catch {
      setSt(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, year, windowKey]);

  useEffect(() => { void load(); }, [load]);

  async function record(line: BalanceLine, challanId: string) {
    const built = lotBody(clientId, line.challan_line_id, lot);
    if (!built.ok) {
      setMsg({ type: "err", text: built.error });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.salesCycle.recordChallanReturn(challanId, built.body);
      if (!res.success) {
        setMsg({ type: "err", text: res.error || "That return was refused." });
        return;
      }
      setMsg({
        type: "ok",
        text: res.data?.challan_marked_received_back
          ? "Recorded. That was the last lot — the challan is now marked received back and its s.143 clock has stopped."
          : "Recorded. What is still outstanding is below.",
      });
      setLotFor(null);
      setLot({ ...BLANK_LOT });
      await load();
      onChanged?.();
    } catch {
      setMsg({ type: "err", text: "Couldn't record that return. Nothing was saved." });
    } finally {
      setSaving(false);
    }
  }

  const readings = arrayOrEmpty<Itc04Reading>(st?.readings);
  const owed = arrayOrEmpty<Itc04Balance>(st?.outstanding);
  // Each nested object is checked where it is read: `{}` passes `objectWithLists`
  // and a missing `period` or `table_4` would otherwise throw on its first field.
  const period = objectOrNull<Itc04Statement["period"]>(st?.period);
  const sel = objectOrNull<NonNullable<Itc04Statement["selected_window"]>>(st?.selected_window);
  const t4 = objectOrNull<NonNullable<Itc04Statement["table_4"]>>(st?.table_4);
  const t5 = objectOrNull<NonNullable<Itc04Statement["table_5a"]>>(st?.table_5a);
  const t5b = objectOrNull<Itc04Statement["table_5b"]>(st?.table_5b);
  const t5c = objectOrNull<Itc04Statement["table_5c"]>(st?.table_5c);

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex flex-wrap items-center gap-3">
        <Factory size={14} className="text-ps-label" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-ps-ink text-sm">
            FORM GST ITC-04 — goods sent for job work
          </h3>
          <p className="text-xs text-ps-label">
            Derived from the job-work challans entered. Rule 45(3) · prepared here,
            furnished on the GST portal by the principal.
          </p>
        </div>
        <YearPicker kind="fy" value={year} label="Financial year"
                    onChange={(y) => { setYear(y); setWindowKey(null); }} />
      </div>

      {msg && (
        <p className={`px-5 py-2 text-xs ${msg.type === "ok" ? "text-state-ready" : "text-state-problem"}`}
           role={msg.type === "err" ? "alert" : "status"}>
          {msg.text}
        </p>
      )}

      {loading && !st && <p className="px-5 py-4 text-sm text-ps-hint">Loading…</p>}

      {failed && (
        <p className="px-5 py-4 text-xs text-state-attention" role="alert">
          Couldn&apos;t read the ITC-04 working. An empty list below would have meant
          every lot is back — this is not that.
        </p>
      )}

      {st && (
        <>
          {/* WHICH PERIOD IS NOT CHOSEN — said where the windows are. */}
          <div className="px-5 py-3 border-b border-ps-border space-y-1">
            <p className="text-xs text-ps-body">{period?.refusal}</p>
            {period?.preceding_year_aato_paise != null && (
              <p className="text-xs text-ps-label">
                Aggregate turnover on record for the preceding year:{" "}
                {formatPaise(period.preceding_year_aato_paise)}. Shown for context;
                it does not choose a reading.
              </p>
            )}
          </div>

          <div className="px-5 py-3 border-b border-ps-border space-y-3">
            {readings.map((reading) => (
              <div key={reading.cadence}>
                <p className="text-xs font-medium text-ps-ink">{reading.label}</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  {arrayOrEmpty<Itc04Window>(reading.windows).map((w) => (
                    <button
                      key={w.key}
                      type="button"
                      onClick={() => setWindowKey(w.key)}
                      aria-pressed={windowKey === w.key}
                      className={`rounded border px-3 py-1.5 text-left text-xs ${
                        windowKey === w.key
                          ? "border-brand bg-ps-hover" : "border-ps-border bg-white hover:bg-ps-hover"}`}
                    >
                      <span className="block font-medium text-ps-ink">{w.label}</span>
                      <span className="block text-ps-label">
                        due {w.due_date} · {w.table_4_rows ?? 0} sent · {w.table_5a_rows ?? 0} returned
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {sel && t4 && t5 && (
            <div className="px-5 py-3 border-b border-ps-border space-y-4">
              <p className="text-xs text-ps-label">
                {sel.label} · {sel.start} to {sel.end}
                {" "}· due {sel.due_date}
              </p>

              <div>
                <h4 className="text-sm font-semibold text-ps-ink">{t4.title}</h4>
                {arrayOrEmpty<Itc04Table4Row>(t4.rows).length === 0
                  ? <p className="text-xs text-ps-hint mt-1">No job-work challan was issued in this window.</p>
                  : (
                    <div className="overflow-x-auto mt-1">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-ps-label border-b border-ps-border">
                            <th className="text-left font-medium py-1 pr-3">Job worker</th>
                            <th className="text-left font-medium py-1 pr-3">Challan</th>
                            <th className="text-left font-medium py-1 pr-3">Type</th>
                            <th className="text-left font-medium py-1 pr-3">Description</th>
                            <th className="text-left font-medium py-1 pr-3">HSN</th>
                            <th className="text-right font-medium py-1 pr-3">Quantity</th>
                            <th className="text-right font-medium py-1 pr-3">Taxable value</th>
                            <th className="text-right font-medium py-1">Rate (I / C / S)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {arrayOrEmpty<Itc04Table4Row>(t4.rows).map((r) => (
                            <tr key={r.challan_line_id} className="border-b border-ps-border last:border-0 align-top">
                              <td className="py-1 pr-3 text-ps-body">
                                {r.job_worker?.name || "—"}
                                <span className="block text-ps-hint">
                                  {r.job_worker?.gstin || (r.job_worker?.state_code ? `State ${r.job_worker.state_code}` : "not identified")}
                                </span>
                              </td>
                              <td className="py-1 pr-3 text-ps-body">{r.challan_no} · {r.challan_date}</td>
                              <td className="py-1 pr-3 text-ps-body">{r.type_of_goods ?? "—"}</td>
                              <td className="py-1 pr-3 text-ps-body">{r.description}</td>
                              <td className="py-1 pr-3 text-ps-body">{r.hsn_sac || "—"}</td>
                              <td className="py-1 pr-3 text-right font-mono tabular-nums text-ps-body">
                                {r.quantity} {r.uqc ?? ""}
                              </td>
                              <td className="py-1 pr-3 text-right font-mono tabular-nums text-ps-body">
                                {formatPaise(r.taxable_value_paise)}
                              </td>
                              <td className="py-1 text-right text-ps-body">
                                {r.igst_rate} / {r.cgst_rate} / {r.sgst_rate}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                {arrayOrEmpty<Itc04Gap>(t4.gaps).map((g, i) => (
                  <p key={i} className="text-xs text-state-attention mt-1">
                    {g.challan_no ? `${g.challan_no}: ` : ""}{g.reason}
                  </p>
                ))}
              </div>

              <div>
                <h4 className="text-sm font-semibold text-ps-ink">{t5.title}</h4>
                {arrayOrEmpty<Itc04Table5aRow>(t5.rows).length === 0
                  ? <p className="text-xs text-ps-hint mt-1">No goods came back in this window.</p>
                  : (
                    <div className="overflow-x-auto mt-1">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-ps-label border-b border-ps-border">
                            <th className="text-left font-medium py-1 pr-3">Original challan</th>
                            <th className="text-left font-medium py-1 pr-3">Job worker&apos;s challan</th>
                            <th className="text-left font-medium py-1 pr-3">Nature of work</th>
                            <th className="text-left font-medium py-1 pr-3">Came back</th>
                            <th className="text-left font-medium py-1 pr-3">Description</th>
                            <th className="text-right font-medium py-1 pr-3">Quantity</th>
                            <th className="text-right font-medium py-1">Lost / wasted</th>
                          </tr>
                        </thead>
                        <tbody>
                          {arrayOrEmpty<Itc04Table5aRow>(t5.rows).map((r, i) => (
                            <tr key={`${r.challan_line_id}-${r.returned_on}-${i}`}
                                className="border-b border-ps-border last:border-0 align-top">
                              <td className="py-1 pr-3 text-ps-body">{r.original_challan_no} · {r.original_challan_date}</td>
                              <td className="py-1 pr-3 text-ps-body">
                                {r.job_worker_challan_no
                                  ? `${r.job_worker_challan_no}${r.job_worker_challan_date ? ` · ${r.job_worker_challan_date}` : ""}`
                                  : "not recorded"}
                              </td>
                              <td className="py-1 pr-3 text-ps-body">{r.nature_of_job_work || "not recorded"}</td>
                              <td className="py-1 pr-3 text-ps-body">
                                {r.returned_on}
                                {r.derived_from_whole_challan_return && (
                                  <span className="block text-ps-hint">whole challan, not itemised</span>
                                )}
                              </td>
                              <td className="py-1 pr-3 text-ps-body">{r.description}</td>
                              <td className="py-1 pr-3 text-right font-mono tabular-nums text-ps-body">
                                {r.quantity} {r.uqc ?? ""}
                              </td>
                              <td className="py-1 text-right font-mono tabular-nums text-ps-body">
                                {r.lost_or_wasted_quantity}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                {arrayOrEmpty<Itc04Gap>(t5.gaps).map((g, i) => (
                  <p key={i} className="text-xs text-state-attention mt-1">
                    {g.challan_no ? `${g.challan_no}: ` : ""}{g.reason}
                  </p>
                ))}
              </div>

              <p className="text-xs text-ps-hint">{t5b?.reason}</p>
              <p className="text-xs text-ps-hint">{t5c?.reason}</p>
            </div>
          )}

          {/* WHAT IS STILL WITH THE JOB WORKER, and the s.143 date for it. */}
          <div className="px-5 py-3 border-b border-ps-border">
            <h4 className="text-sm font-semibold text-ps-ink">Still with the job worker</h4>
            <p className="text-xs text-ps-label">
              As at {st.as_of}. A lot coming back reduces what is left; it does not move the
              day the goods were sent out, which is the day s.143(3) deems them supplied.
            </p>
            {owed.length === 0 && !failed && (
              <p className="text-xs text-ps-hint mt-2">Nothing is outstanding on any job-work challan.</p>
            )}
            <div className="mt-2 space-y-3">
              {owed.map((b) => (
                <div key={b.challan_id} className="rounded border border-ps-border p-3">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="font-mono text-sm text-ps-ink">{b.challan_no}</span>
                    <span className="text-xs text-ps-label">
                      sent {b.challan_date} to {b.job_worker?.name || "a job worker not named"}
                    </span>
                    <ClockLine clock={objectOrNull<DeemedSupplyClock>(b.clock)} />
                  </div>
                  <table className="w-full text-xs mt-2">
                    <thead>
                      <tr className="text-ps-label border-b border-ps-border">
                        <th className="text-left font-medium py-1 pr-3">Line</th>
                        <th className="text-right font-medium py-1 pr-3">Sent</th>
                        <th className="text-right font-medium py-1 pr-3">Back</th>
                        <th className="text-right font-medium py-1 pr-3">Lost / wasted</th>
                        <th className="text-right font-medium py-1 pr-3">Outstanding</th>
                        <th className="text-right font-medium py-1 pr-3">Taxable value at stake</th>
                        <th className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {arrayOrEmpty<BalanceLine>(b.lines).map((l) => (
                        <tr key={l.challan_line_id} className="border-b border-ps-border last:border-0 align-top">
                          <td className="py-1 pr-3 text-ps-body">{l.description}</td>
                          <td className="py-1 pr-3 text-right font-mono tabular-nums">{l.sent} {l.uqc ?? ""}</td>
                          <td className="py-1 pr-3 text-right font-mono tabular-nums">{l.returned}</td>
                          <td className="py-1 pr-3 text-right font-mono tabular-nums">{l.lost_or_wasted}</td>
                          <td className="py-1 pr-3 text-right font-mono tabular-nums text-ps-ink">{l.outstanding}</td>
                          <td className="py-1 pr-3 text-right font-mono tabular-nums">
                            {formatPaise(l.taxable_value_at_stake_paise)}
                          </td>
                          <td className="py-1 text-right">
                            <button
                              type="button"
                              className="text-brand hover:underline"
                              onClick={() => {
                                setLotFor(lotFor === l.challan_line_id ? null : l.challan_line_id);
                                setLot({ ...BLANK_LOT });
                                setMsg(null);
                              }}
                            >
                              Record a lot
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {arrayOrEmpty<BalanceLine>(b.lines).filter((l) => l.challan_line_id === lotFor).map((l) => (
                    <div key={l.challan_line_id} className="mt-3 grid gap-2 sm:grid-cols-3 text-xs">
                      <label className="space-y-1">
                        <span className="text-ps-label">Came back on</span>
                        <input type="date" value={lot.returned_on}
                               onChange={(e) => setLot({ ...lot, returned_on: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-ps-label">Quantity returned</span>
                        <input inputMode="decimal" value={lot.returned}
                               onChange={(e) => setLot({ ...lot, returned: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-ps-label">Lost or wasted</span>
                        <input inputMode="decimal" value={lot.wasted}
                               onChange={(e) => setLot({ ...lot, wasted: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-ps-label">Job worker&apos;s challan no.</span>
                        <input value={lot.job_worker_challan_no}
                               onChange={(e) => setLot({ ...lot, job_worker_challan_no: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-ps-label">Job worker&apos;s challan date</span>
                        <input type="date" value={lot.job_worker_challan_date}
                               onChange={(e) => setLot({ ...lot, job_worker_challan_date: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-ps-label">Nature of the job work</span>
                        <input value={lot.nature_of_job_work}
                               onChange={(e) => setLot({ ...lot, nature_of_job_work: e.target.value })}
                               className="block w-full rounded border border-ps-border px-2 py-1" />
                      </label>
                      <div className="sm:col-span-3 flex items-center gap-3">
                        <button type="button" disabled={saving}
                                onClick={() => void record(l, b.challan_id)}
                                className="rounded bg-brand px-3 py-1.5 text-white disabled:opacity-50">
                          {saving ? "Recording…" : "Record this lot"}
                        </button>
                        <p className="text-ps-hint">
                          More than was sent is refused, not trimmed. Lost or wasted
                          quantity is kept and is not taken off what is outstanding.
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <div className="px-5 py-3 bg-ps-bg space-y-1">
            {arrayOrEmpty<string>(st.gaps).map((g, i) => (
              <p key={i} className="text-xs text-ps-hint">{g}</p>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
