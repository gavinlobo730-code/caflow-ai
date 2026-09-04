"use client";

/**
 * The firm's own reading of the state professional-tax notifications.
 *
 * WHY THIS SCREEN EXISTS
 *   Professional tax is levied by twenty-two states, each setting its own slabs
 *   by its own notification on its own cycle. The software models FOUR of them
 *   and reports the rest as gaps rather than deducting zero — which is right,
 *   because Article 276 makes the employer liable to deduct and deposit it, so
 *   a silent nil is a shortfall with interest, not an absence of liability.
 *
 *   Correct, and not a product: the only remedy on offer was that somebody
 *   edits Python. Writing the other eighteen states' slabs from memory would
 *   put eighteen confidently wrong deductions into people's pay, and
 *   maintaining them against notification cycles is a compliance research desk
 *   with no revenue behind it. So the CA records what they READ — once per
 *   firm, reused across every client of that firm.
 *
 * THE WHOLE SET IN ONE SAVE
 *   The bands must start at zero and meet end to start, and the endpoint
 *   refuses a set that does not. A per-band save would let a half-recorded
 *   state exist between two clicks, and during that window a wage in the hole
 *   would come out as a nil deduction — the exact fault this mechanism exists
 *   to avoid importing.
 *
 * Zero business logic here (CLAUDE.md): the backend owns the cover check, the
 * effective-date selection and whether a recorded set may be used at all. This
 * page shows the state of play and posts what the CA typed.
 */
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Trash2, Scale, X, AlertTriangle } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type PTSlabRow } from "@/lib/api/index";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { TableSkeleton } from "@/components/ui/skeleton";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function rupees(paise: number) {
  return "₹" + (paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/** One editable band in the form. Kept as STRINGS until save: every amount goes
 *  through paiseFromRupeeInput, which refuses "1,25,000" rather than reading it
 *  as 1 the way parseFloat does. */
type BandDraft = { from: string; to: string; amount: string };

const EMPTY_BAND: BandDraft = { from: "", to: "", amount: "" };

export default function StatutoryValuesPage() {
  const [rows, setRows] = useState<PTSlabRow[]>([]);
  const [levying, setLevying] = useState<Record<string, string>>({});
  const [modelled, setModelled] = useState<string[]>([]);
  const [recorded, setRecorded] = useState<string[]>([]);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [state, setState] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [reference, setReference] = useState("");
  const [notifiedOn, setNotifiedOn] = useState("");
  const [basis, setBasis] = useState("monthly");
  const [months, setMonths] = useState<number[]>([]);
  const [bands, setBands] = useState<BandDraft[]>([{ ...EMPTY_BAND, from: "0" }]);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.statutoryValues.list();
      if (res.success && res.data) {
        setRows(res.data.pt_slabs ?? []);
        setLevying(res.data.pt_levying_states ?? {});
        setModelled(res.data.pt_modelled_states ?? []);
        setRecorded(res.data.pt_recorded_states ?? []);
        setConflicts(res.data.pt_conflicts ?? []);
      } else {
        setMsg({ type: "err", text: res.error ?? "Could not load the recorded slabs." });
      }
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "The request failed." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function reset() {
    setState(""); setEffectiveFrom(""); setReference(""); setNotifiedOn("");
    setBasis("monthly"); setMonths([]); setNote("");
    setBands([{ ...EMPTY_BAND, from: "0" }]);
  }

  async function save() {
    const code = state.trim().toUpperCase();
    if (!/^[A-Z]{2}$/.test(code)) {
      setMsg({ type: "err", text: 'State must be the two-letter code, e.g. "GJ".' });
      return;
    }
    if (!reference.trim() || !notifiedOn || !effectiveFrom) {
      setMsg({ type: "err", text:
        "The notification reference, its date and the effective-from date are all "
        + "required — a recorded figure that names no source is exactly what this "
        + "screen exists to replace." });
      return;
    }

    // Amounts through the exact parser. It REFUSES rather than coerces: a
    // rejected field is a question for the CA; a coerced one is a wrong
    // deduction nobody sees.
    const parsed: Array<{ from_paise: number; to_paise: number | null; amount_paise: number }> = [];
    for (let i = 0; i < bands.length; i++) {
      const band = bands[i];
      const from = paiseFromRupeeInput(band.from);
      const amount = paiseFromRupeeInput(band.amount);
      const to = band.to.trim() === "" ? null : paiseFromRupeeInput(band.to);
      if (from === null || amount === null || (band.to.trim() !== "" && to === null)) {
        setMsg({ type: "err", text:
          `Band ${i + 1}: the amounts must be plain figures in rupees, without commas.` });
        return;
      }
      parsed.push({ from_paise: from, to_paise: to, amount_paise: amount });
    }

    setSaving(true);
    setMsg(null);
    try {
      const res = await api.statutoryValues.savePtSlabs({
        state: code,
        effective_from: effectiveFrom,
        notification_reference: reference.trim(),
        notification_date: notifiedOn,
        note: note.trim() || null,
        bands: parsed.map(b => ({ ...b, basis,
                                  months: months.length ? months : null })),
      });
      const body = res as unknown as { success?: boolean; error?: string; detail?: string };
      if (body?.success === false) {
        // The server's sentence says WHICH rule the set broke. A generic
        // "couldn't save" would throw away the only useful part.
        setMsg({ type: "err", text: body.error || body.detail || "The set was refused." });
        return;
      }
      setMsg({ type: "ok", text: `Recorded ${parsed.length} band(s) for ${code}.` });
      setShowForm(false);
      reset();
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "The request failed." });
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: PTSlabRow) {
    const ok = await confirmDialog({
      title: `Remove ${row.state} slabs effective ${row.effective_from}?`,
      message: "The whole version goes, not just this band. If nothing earlier "
             + "remains, the state goes back to being reported as a gap on every "
             + "run — which is the correct outcome: an employer deducting on slabs "
             + "nobody stands behind is exactly what the gap says. Runs already "
             + "posted keep what they withheld.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.statutoryValues.removePtSlabs(row.state, row.effective_from);
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "The request failed." });
    }
  }

  // Grouped for display: one card per (state, effective_from), which is what a
  // notification actually is.
  const versions = new Map<string, PTSlabRow[]>();
  for (const row of rows) {
    const key = `${row.state}|${row.effective_from}`;
    versions.set(key, [...(versions.get(key) ?? []), row]);
  }

  const levyingCodes = Object.keys(levying).sort();
  const stillMissing = levyingCodes.filter(
    c => !modelled.includes(c) && !recorded.includes(c));

  // payroll:read is Manager+ (core/permissions.py), and recording one of these
  // deducts from every client of the firm with staff in that state.
  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <div className="p-6 max-w-5xl mx-auto">
        <Link href="/settings" className="inline-flex items-center gap-1 text-sm text-[#64748B] hover:text-[#0F172A] mb-4">
          <ChevronLeft size={15} />Settings
        </Link>

        <div className="flex items-start justify-between mb-5">
          <div className="flex items-start gap-3">
            <Scale size={18} className="text-indigo-500 mt-0.5" />
            <div>
              <h1 className="text-lg font-semibold text-[#0F172A]">Statutory values</h1>
              <p className="text-sm text-[#64748B] mt-0.5 max-w-2xl">
                Your firm&apos;s reading of the state professional-tax notifications, recorded
                once and used for every client with staff in that state. Twenty-two states levy
                it; {modelled.length} are built in and verified against the state Act, and the
                rest are reported as gaps on a run until you record them here.
              </p>
            </div>
          </div>
          <button
            onClick={() => { reset(); setShowForm(true); }}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
          >
            <Plus size={15} />Record a notification
          </button>
        </div>

        {msg && (
          <div className={`mb-4 px-3 py-2 rounded-lg text-sm ${
            msg.type === "ok" ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                              : "bg-red-50 text-red-700 border border-red-200"}`}>
            {msg.text}
          </div>
        )}

        {/* A set recorded against a state the CODE models is never applied, and
            saying so here is the only option that cannot mislead. */}
        {conflicts.length > 0 && (
          <div className="mb-4 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200">
            <p className="flex items-center gap-1.5 text-sm font-medium text-amber-900">
              <AlertTriangle size={14} />Recorded, but not used
            </p>
            <ul className="mt-1 space-y-1">
              {conflicts.map((c, i) => (
                <li key={i} className="text-xs text-amber-800">{c}</li>
              ))}
            </ul>
          </div>
        )}

        {loading ? <TableSkeleton rows={4} /> : (
          <>
            {versions.size === 0 ? (
              <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center">
                <p className="text-sm text-[#64748B]">
                  Nothing recorded yet. This ships empty and is never seeded — each state
                  sets its own slabs by its own notification, and a figure written from
                  memory is a wrong deduction in somebody&apos;s pay.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {Array.from(versions.entries()).sort().map(([key, bandRows]) => {
                  const first = bandRows[0];
                  return (
                    <div key={key} className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
                      <div className="px-4 py-3 flex items-start justify-between border-b border-[#F1F5F9]">
                        <div>
                          <p className="text-sm font-semibold text-[#0F172A]">
                            {first.state} — effective {first.effective_from}
                            {first.basis === "half_yearly" && (
                              <span className="ml-2 text-[10px] font-medium text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                                half-yearly
                              </span>
                            )}
                          </p>
                          {/* The authority, printed beside the figures. It is the
                              reason these numbers may drive a deduction at all. */}
                          <p className="text-xs text-[#64748B] mt-0.5">
                            {first.notification_reference} · notified {first.notification_date}
                            {first.months && first.months.length > 0 &&
                              ` · deducted in ${first.months.map((m: number) => MONTHS[m - 1]).join(", ")}`}
                          </p>
                          {first.note && <p className="text-xs text-[#94A3B8] mt-0.5">{first.note}</p>}
                        </div>
                        <button onClick={() => remove(first)}
                          className="text-[#94A3B8] hover:text-red-600 shrink-0"
                          aria-label="Remove this version">
                          <Trash2 size={15} />
                        </button>
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-[10px] uppercase tracking-wide text-[#94A3B8]">
                            <th className="text-left px-4 py-2">From</th>
                            <th className="text-left px-4 py-2">To</th>
                            <th className="text-right px-4 py-2">Tax</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...bandRows].sort((a, b) => a.from_paise - b.from_paise).map(b => (
                            <tr key={b.id} className="border-t border-[#F8FAFC]">
                              <td className="px-4 py-2 text-[#334155]">{rupees(b.from_paise)}</td>
                              <td className="px-4 py-2 text-[#334155]">
                                {b.to_paise === null
                                  ? <span className="text-[#94A3B8]">and above</span>
                                  : rupees(b.to_paise)}
                              </td>
                              <td className="px-4 py-2 text-right font-medium text-[#0F172A]">
                                {rupees(b.amount_paise)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Which states still deduct nothing. Named rather than counted, so
                a CA can see whether any of them is one of their clients'. */}
            {stillMissing.length > 0 && (
              <div className="mt-5 bg-white border border-[#E2E8F0] rounded-xl p-4">
                <p className="text-sm font-medium text-[#0F172A]">
                  {stillMissing.length} state{stillMissing.length === 1 ? "" : "s"} still
                  deduct nothing
                </p>
                <p className="text-xs text-[#64748B] mt-0.5">
                  An employee in one of these is reported as a gap on the run and has no
                  professional tax withheld. Article 276 makes the employer liable either way.
                </p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {stillMissing.map(code => (
                    <span key={code} className="text-[11px] px-2 py-0.5 rounded bg-[#F1F5F9] text-[#475569]">
                      {levying[code]} ({code})
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {showForm && (
          <div className="fixed inset-0 bg-black/30 flex items-start justify-center p-6 overflow-y-auto z-50">
            <div className="bg-white rounded-xl w-full max-w-2xl my-8">
              <div className="px-5 py-4 flex items-center justify-between border-b border-[#F1F5F9]">
                <h2 className="text-sm font-semibold text-[#0F172A]">Record a notification</h2>
                <button onClick={() => setShowForm(false)} className="text-[#94A3B8] hover:text-[#0F172A]">
                  <X size={16} />
                </button>
              </div>

              <div className="p-5 space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="State code" value={state} onChange={v => setState(v.toUpperCase().slice(0, 2))} placeholder="GJ" />
                  <Field label="Effective from" value={effectiveFrom} onChange={setEffectiveFrom} type="date" />
                  <Field label="Notification reference" value={reference} onChange={setReference} placeholder="PFT-2026/CR-12/Taxation-3" />
                  <Field label="Notification date" value={notifiedOn} onChange={setNotifiedOn} type="date" />
                </div>

                <div>
                  <label className="block text-[11px] text-[#64748B] mb-1">Read against</label>
                  <select value={basis} onChange={e => setBasis(e.target.value)}
                    className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] outline-none focus:border-indigo-400">
                    <option value="monthly">The month&apos;s gross</option>
                    <option value="half_yearly">Six months&apos; gross (half-yearly levy)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] text-[#64748B] mb-1">
                    Deducted in — leave all unticked for every month
                  </label>
                  <div className="flex flex-wrap gap-1">
                    {MONTHS.map((m, i) => (
                      <button key={m} type="button"
                        onClick={() => setMonths(prev => prev.includes(i + 1)
                          ? prev.filter(x => x !== i + 1) : [...prev, i + 1].sort((a, b) => a - b))}
                        className={`text-[11px] px-2 py-1 rounded border ${
                          months.includes(i + 1)
                            ? "bg-indigo-600 text-white border-indigo-600"
                            : "border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC]"}`}>
                        {m}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[11px] text-[#64748B]">
                      Bands — must start at ₹0, meet end to start, and leave the last &quot;To&quot; blank
                    </label>
                    <button type="button" onClick={() => setBands(b => [...b, { ...EMPTY_BAND }])}
                      className="text-[11px] text-indigo-600 hover:underline">+ band</button>
                  </div>
                  <div className="space-y-1.5">
                    {bands.map((band, i) => (
                      <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-1.5 items-center">
                        <input value={band.from} placeholder="From ₹"
                          onChange={e => setBands(b => b.map((x, j) => j === i ? { ...x, from: e.target.value } : x))}
                          className="border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] outline-none focus:border-indigo-400" />
                        <input value={band.to} placeholder="To ₹ (blank = and above)"
                          onChange={e => setBands(b => b.map((x, j) => j === i ? { ...x, to: e.target.value } : x))}
                          className="border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] outline-none focus:border-indigo-400" />
                        <input value={band.amount} placeholder="Tax ₹"
                          onChange={e => setBands(b => b.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))}
                          className="border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] outline-none focus:border-indigo-400" />
                        <button type="button" disabled={bands.length === 1}
                          onClick={() => setBands(b => b.filter((_, j) => j !== i))}
                          className="text-[#94A3B8] hover:text-red-600 disabled:opacity-30">
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <Field label="Note (optional)" value={note} onChange={setNote} placeholder="Anything the next reviewer should know" />
              </div>

              <div className="px-5 py-4 flex items-center justify-end gap-2 border-t border-[#F1F5F9]">
                <button onClick={() => setShowForm(false)}
                  className="px-4 py-1.5 text-sm text-[#475569] hover:bg-[#F8FAFC] rounded-lg">Cancel</button>
                <button onClick={save} disabled={saving}
                  className="px-4 py-1.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  {saving ? "Saving…" : "Record"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </RoleGuard>
  );
}

function Field({ label, value, onChange, placeholder, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-[11px] text-[#64748B] mb-1">{label}</label>
      <input type={type} value={value} placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] text-[#1E293B] outline-none focus:border-indigo-400" />
    </div>
  );
}
