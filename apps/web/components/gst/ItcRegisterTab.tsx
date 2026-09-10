"use client";

/**
 * THE RECLAIMABLE HALF OF GSTR-3B TABLE 4, AND TABLE 11 ADVANCES (GST-13).
 *
 * Four finished endpoints that no screen reached:
 *
 *   GET  /gst-workspace/itc/register            what 4(B)(2) and 4(D)(1) declare
 *   POST /gst-workspace/itc/register/reversal   classify a journal as a reversal
 *   POST /gst-workspace/itc/register/reclaim    …and its reclaim
 *   GET  /gst-workspace/gstr1/advances          GSTR-1 Table 11
 *
 * IT REGISTERS A JOURNAL, IT DOES NOT POST ONE. Giving credit back is a real
 * movement — a credit to GST Input — and that posting already has a home: the
 * CA raises it as a manual journal like any other entry, through the one
 * posting kernel. What was missing was never a way to POST the reversal; it
 * was a way to say WHAT IT WAS. A journal crediting GST Input could be a
 * Rule 37 reversal, a cancelled bill, or a plain correction, and the return
 * has to tell them apart.
 *
 * ONLY THE RECLAIMABLE ONES. Rules 38, 42, 43 and §17(5) are PERMANENT
 * reversals — Table 4(B)(1) — derived from the documents themselves (a
 * cancelled bill, blocked credit on a line). Registering one here would
 * double-count it, which is why the reason list is short and fixed.
 *
 * TABLE 11 IS NAMED AND NOT COMPUTED, and the panel says so in the server's
 * own words. A Table 11 row needs the place of supply and the tax RATE of a
 * supply that has not happened yet; a receipt records an amount, a customer
 * and a date. Inventing a rate would invent a liability on a filed return.
 */

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type {
  GSTR1Advances, ITCHeads, ITCRegisterPeriod, ITCRegisterRow,
} from "@/lib/api";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { gstPeriodLabel, isGstPeriod } from "@/lib/gst/period";

function money(paise?: number | null) {
  const p = Number(paise ?? 0);
  return `₹${Math.trunc(p / 100).toLocaleString("en-IN")}`;
}

const FIELD =
  "border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[13px] outline-none focus:border-blue-400";

/** The reclaimable reasons, and ONLY those. Kept in step with
 *  services/itc_register_service.RECLAIMABLE_REASONS — a reason this list
 *  offers that the server rejects is a form that fails on submit, and a
 *  permanent-reversal reason offered here would be a double count in 4(B)(1). */
const REASONS: { code: string; label: string; note: string }[] = [
  { code: "rule_37", label: "Rule 37 — supplier unpaid 180 days",
    note: "Credit taken on a bill not paid within 180 days of the invoice date. Reclaimable on payment." },
  { code: "rule_37a", label: "Rule 37A — supplier did not pay the tax",
    note: "The supplier filed GSTR-1 but not GSTR-3B by 30 September. Reclaimable when they do." },
  { code: "section_16_2b", label: "§16(2)(b) — goods or services not received",
    note: "Credit taken before receipt. Reclaimable on receipt." },
  { code: "section_16_2c", label: "§16(2)(c) — tax not paid to Government",
    note: "Reclaimable once the supplier's tax reaches the Government." },
  { code: "other", label: "Other reclaimable reversal",
    note: "Anything else that will come back. NOT for Rules 38/42/43 or §17(5) — those are permanent, Table 4(B)(1), and derived from the documents." },
];

const HEADS: { key: keyof ITCHeads; label: string }[] = [
  { key: "igst_paise", label: "IGST" },
  { key: "cgst_paise", label: "CGST" },
  { key: "sgst_paise", label: "SGST" },
  { key: "cess_paise", label: "Cess" },
];

function HeadTotals({ totals }: { totals?: Partial<ITCHeads> }) {
  return (
    <span className="font-mono text-[11px] text-[#475569]">
      {HEADS.map((h) => `${h.label} ${money(totals?.[h.key])}`).join(" · ")}
    </span>
  );
}

function RegisterTable({ rows, title, table, empty }: {
  rows: ITCRegisterRow[]; title: string; table: string; empty: string;
}) {
  return (
    <div className="rounded-xl border border-[#E2E8F0] p-3">
      <p className="text-[12px] font-semibold text-[#1E293B]">
        {title} <span className="text-[#94A3B8] font-normal">· Table {table}</span>
      </p>
      {rows.length === 0 ? (
        <p className="text-[11px] text-[#94A3B8] mt-2">{empty}</p>
      ) : (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                <th className="py-1.5 pr-2">Reason</th>
                <th className="py-1.5 pr-2">Journal</th>
                {HEADS.map((h) => (
                  <th key={h.key} className="py-1.5 pr-2 text-right">{h.label}</th>
                ))}
                <th className="py-1.5">Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-[#F1F5F9]">
                  <td className="py-1.5 pr-2 text-[#1E293B]">
                    {REASONS.find((x) => x.code === r.reason_code)?.label
                      ?? r.reason_code ?? "—"}
                  </td>
                  <td className="py-1.5 pr-2 font-mono text-[10px] text-[#94A3B8]">
                    {r.journal_entry_id?.slice(0, 8) ?? "—"}
                  </td>
                  {HEADS.map((h) => (
                    <td key={h.key} className="py-1.5 pr-2 text-right font-mono">
                      {money(r[h.key])}
                    </td>
                  ))}
                  <td className="py-1.5 text-[#64748B]">{r.notes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function ItcRegisterTab({ clientId }: { clientId: string }) {
  const [period, setPeriod] = useState("");
  const [register, setRegister] = useState<ITCRegisterPeriod | null>(null);
  const [advances, setAdvances] = useState<GSTR1Advances | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  // The form. `kind` decides which endpoint takes it, and the two need
  // different things: a reversal names a REASON, a reclaim names the reversal
  // it brings back.
  const [kind, setKind] = useState<"reversal" | "reclaim">("reversal");
  const [journalId, setJournalId] = useState("");
  const [reason, setReason] = useState("rule_37");
  const [reverses, setReverses] = useState("");
  const [purchaseBillId, setPurchaseBillId] = useState("");
  const [notes, setNotes] = useState("");
  const [amounts, setAmounts] = useState<Record<string, string>>({});

  const load = useCallback(async (p: string) => {
    setBusy("load"); setErr(null); setOk(null);
    try {
      const [reg, adv] = await Promise.all([
        api.gstWorkspace.itcRegister(clientId, p),
        api.gstWorkspace.gstr1Advances(clientId, p),
      ]);
      if (!reg?.success) throw new Error(reg?.error ?? "The register did not load.");
      setRegister(reg.data);
      // The advances panel is supplementary: a failure there must not hide the
      // register, which is the figure a return depends on.
      setAdvances(adv?.success ? adv.data : null);
    } catch (e) {
      setRegister(null); setAdvances(null);
      setErr(e instanceof Error ? e.message : "That did not load.");
    } finally { setBusy(null); }
  }, [clientId]);

  const typed = HEADS.map((h) => ({
    key: h.key,
    paise: (amounts[h.key] ?? "").trim() === ""
      ? 0 : paiseFromRupeeInput(amounts[h.key] ?? ""),
  }));
  const anyBad = typed.some((t) => t.paise === null);
  const total = typed.reduce((n, t) => n + (t.paise ?? 0), 0);

  async function record() {
    setBusy("record"); setErr(null); setOk(null);
    try {
      const heads = Object.fromEntries(
        typed.map((t) => [t.key, t.paise ?? 0])) as unknown as Partial<ITCHeads>;
      const res = kind === "reversal"
        ? await api.gstWorkspace.itcRegisterReversal({
            client_id: clientId, journal_entry_id: journalId.trim(), period,
            reason_code: reason,
            purchase_bill_id: purchaseBillId.trim() || undefined,
            notes: notes.trim() || undefined, ...heads,
          })
        : await api.gstWorkspace.itcRegisterReclaim({
            client_id: clientId, journal_entry_id: journalId.trim(), period,
            reverses_id: reverses.trim(),
            notes: notes.trim() || undefined, ...heads,
          });
      if (!res?.success) throw new Error(res?.error ?? "That was not recorded.");
      setOk(kind === "reversal"
        ? "Recorded. It will be declared in GSTR-3B Table 4(B)(2)."
        : "Recorded. It will be declared in GSTR-3B Table 4(D)(1).");
      setJournalId(""); setReverses(""); setPurchaseBillId(""); setNotes("");
      setAmounts({});
      await load(period);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That was not recorded.");
    } finally { setBusy(null); }
  }

  const canRecord = isGstPeriod(period) && journalId.trim() !== "" && !anyBad
    && total > 0 && (kind === "reversal" || reverses.trim() !== "");

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3">
        <p className="text-[12px] text-[#334155]">
          Reclaimable ITC reversals (Table <b>4(B)(2)</b>) and the reclaims that
          bring them back (Table <b>4(D)(1)</b>).
        </p>
        <p className="text-[10px] text-[#94A3B8] mt-1 max-w-[90ch]">
          Nothing here posts to the ledger. The CA raises the journal like any other
          entry; this says what it <i>was</i>, so the return can declare it — and a row
          claiming more than its journal actually moved is refused. Rules 38, 42, 43 and
          §17(5) are permanent reversals and belong in 4(B)(1), derived from the
          documents; registering one here would double-count it.
        </p>
      </div>

      <div className="flex items-end gap-2 flex-wrap">
        <label className="text-[11px] text-[#64748B]">
          Period
          <input value={period} placeholder="062026"
            onChange={(e) => setPeriod(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
            inputMode="numeric" className={`${FIELD} block mt-1 w-32`} />
        </label>
        <button onClick={() => load(period)}
          disabled={busy !== null || !isGstPeriod(period)}
          className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
          {busy === "load" ? "Loading…" : "Load the register"}
        </button>
        {isGstPeriod(period) && (
          <span className="text-[11px] text-[#94A3B8] pb-1.5">{gstPeriodLabel(period)}</span>
        )}
      </div>

      {err && <p className="text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}
      {ok && <p className="text-[12px] px-3 py-2 rounded-lg bg-green-50 text-green-700">{ok}</p>}

      {register && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-[#E2E8F0] p-2.5">
              <p className="text-[10px] text-[#94A3B8]">Reversed · Table 4(B)(2)</p>
              <HeadTotals totals={register.reversal_totals} />
            </div>
            <div className="rounded-lg border border-[#E2E8F0] p-2.5">
              <p className="text-[10px] text-[#94A3B8]">Reclaimed · Table 4(D)(1)</p>
              <HeadTotals totals={register.reclaim_totals} />
            </div>
          </div>

          <RegisterTable rows={register.reversals} title="Reversals" table="4(B)(2)"
            empty="Nothing reclaimable was reversed in this period." />
          <RegisterTable rows={register.reclaims} title="Reclaims" table="4(D)(1)"
            empty="Nothing was reclaimed in this period." />
        </div>
      )}

      {/* ── Recording one ────────────────────────────────────────────────── */}
      {isGstPeriod(period) && (
        <div className="rounded-xl border border-[#E2E8F0] p-3 space-y-3">
          <div className="flex items-center gap-2">
            {(["reversal", "reclaim"] as const).map((k) => (
              <button key={k} onClick={() => { setKind(k); setErr(null); setOk(null); }}
                className={`px-2.5 py-1 text-[12px] rounded-lg border ${
                  kind === k ? "bg-[#1E293B] text-white border-[#1E293B]"
                             : "border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC]"}`}>
                {k === "reversal" ? "Record a reversal" : "Record a reclaim"}
              </button>
            ))}
          </div>

          <p className="text-[10px] text-[#94A3B8] max-w-[90ch]">
            {kind === "reversal"
              ? "Point at a journal already posted for this reversal and say which rule it was under. The server checks it against the GST Input movement on that journal and refuses a row the ledger cannot support."
              : "Point at a journal already posted for the reclaim and name the reversal it brings back. Refused if it would reclaim more than that reversal still has outstanding — credit can only come back once."}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <label className="text-[11px] text-[#64748B]">
              Journal entry id
              <input value={journalId} onChange={(e) => setJournalId(e.target.value)}
                placeholder="the posted journal this classifies"
                className={`${FIELD} w-full mt-1`} />
            </label>

            {kind === "reversal" ? (
              <label className="text-[11px] text-[#64748B]">
                Reason
                <select value={reason} onChange={(e) => setReason(e.target.value)}
                  className={`${FIELD} w-full mt-1`}>
                  {REASONS.map((r) => (
                    <option key={r.code} value={r.code}>{r.label}</option>
                  ))}
                </select>
                <span className="block text-[10px] text-[#94A3B8] mt-0.5">
                  {REASONS.find((r) => r.code === reason)?.note}
                </span>
              </label>
            ) : (
              <label className="text-[11px] text-[#64748B]">
                Reverses which register row?
                <select value={reverses} onChange={(e) => setReverses(e.target.value)}
                  className={`${FIELD} w-full mt-1`}>
                  <option value="">— pick the reversal —</option>
                  {(register?.reversals ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {REASONS.find((x) => x.code === r.reason_code)?.label ?? r.reason_code}
                      {" · "}{money((r.igst_paise ?? 0) + (r.cgst_paise ?? 0)
                                    + (r.sgst_paise ?? 0) + (r.cess_paise ?? 0))}
                    </option>
                  ))}
                </select>
                {!register?.reversals?.length && (
                  <span className="block text-[10px] text-amber-700 mt-0.5">
                    Load a period that has a reversal first — a reclaim has to name one.
                  </span>
                )}
              </label>
            )}

            {kind === "reversal" && (
              <label className="text-[11px] text-[#64748B]">
                Purchase bill (optional)
                <input value={purchaseBillId} onChange={(e) => setPurchaseBillId(e.target.value)}
                  className={`${FIELD} w-full mt-1`} />
              </label>
            )}

            <label className="text-[11px] text-[#64748B]">
              Note
              <input value={notes} onChange={(e) => setNotes(e.target.value)}
                className={`${FIELD} w-full mt-1`} />
            </label>
          </div>

          <div className="grid grid-cols-4 gap-3">
            {HEADS.map((h) => {
              const bad = (amounts[h.key] ?? "").trim() !== ""
                && paiseFromRupeeInput(amounts[h.key] ?? "") === null;
              return (
                <label key={h.key} className="text-[11px] text-[#64748B]">
                  {h.label}
                  <input value={amounts[h.key] ?? ""} type="text" inputMode="decimal"
                    onChange={(e) => setAmounts((a) => ({ ...a, [h.key]: e.target.value }))}
                    className={`${FIELD} w-full mt-1 text-right ${bad ? "border-red-300" : ""}`} />
                  {bad && <span className="text-[10px] text-red-600">Not an amount.</span>}
                </label>
              );
            })}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[11px] text-[#64748B]">
              Total <span className="font-mono text-[#1E293B]">{money(total)}</span>
              {total === 0 && !anyBad && (
                <span className="text-[#94A3B8]"> · a nil row declares nothing</span>
              )}
            </span>
            <button onClick={record} disabled={busy !== null || !canRecord}
              className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
              {busy === "record" ? "Recording…" : "Record"}
            </button>
          </div>
        </div>
      )}

      {/* ── Table 11 advances ────────────────────────────────────────────── */}
      {advances && (
        <div className="rounded-xl border border-[#E2E8F0] p-3 space-y-2 border-t">
          <p className="text-[12px] font-semibold text-[#1E293B]">
            Advances against no invoice — GSTR-1 Table 11
            <span className="text-[#94A3B8] font-normal"> · {advances.count}</span>
          </p>

          {/* NOT COMPUTED, AND THE SERVER SAYS SO IN THE PAYLOAD. An empty
              Table 11 has two very different meanings and this is which. */}
          {!advances.table_11_computed && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5">
              <p className="text-[11px] font-semibold text-amber-800">
                Table 11 is not computed here
              </p>
              <p className="text-[11px] text-amber-800 mt-0.5 max-w-[90ch]">{advances.why}</p>
              {advances.rule && (
                <p className="text-[10px] text-amber-700 mt-1">{advances.rule}</p>
              )}
            </div>
          )}

          {advances.unadjusted_advances.length === 0 ? (
            <p className="text-[11px] text-[#94A3B8]">
              No unadjusted advances in {gstPeriodLabel(advances.period)}.
            </p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                  <th className="py-1.5 pr-2">Receipt</th>
                  <th className="py-1.5 pr-2">Date</th>
                  <th className="py-1.5 pr-2">Customer</th>
                  <th className="py-1.5 pr-2 text-right">Received</th>
                  <th className="py-1.5 text-right">Unadjusted</th>
                </tr>
              </thead>
              <tbody>
                {advances.unadjusted_advances.map((a) => (
                  <tr key={a.receipt_id} className="border-b border-[#F1F5F9]">
                    <td className="py-1.5 pr-2 font-mono text-[#1E293B]">{a.receipt_no ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-[#64748B]">{a.receipt_date ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-[#475569]">
                      {a.customer_name ?? "—"}
                      {a.customer_gstin && (
                        <span className="block text-[10px] text-[#94A3B8] font-mono">
                          {a.customer_gstin}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">{money(a.amount_paise)}</td>
                    <td className="py-1.5 text-right font-mono text-amber-700">
                      {money(a.unadjusted_paise)}
                    </td>
                  </tr>
                ))}
                <tr className="font-semibold text-[#1E293B]">
                  <td className="py-1.5 pr-2" colSpan={4}>Total unadjusted</td>
                  <td className="py-1.5 text-right font-mono">
                    {money(advances.total_unadjusted_paise)}
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
