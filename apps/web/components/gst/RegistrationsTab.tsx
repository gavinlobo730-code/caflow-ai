"use client";

/**
 * The GST registrations a client holds (GST-20).
 *
 * WHAT WAS MISSING
 *   `clients.gstin` held exactly one, and both return tables were
 *   UNIQUE (client_id, period) — so a client registered in more than one state
 *   could not hold both registrations' returns whatever the code did. CGST Act
 *   s.25(1) requires registration in EVERY State or Union territory from which
 *   a taxable supply is made and s.25(2)'s proviso allows one per place of
 *   business, so a manufacturer with a depot, a services firm with two offices
 *   or an e-commerce seller holding warehouse-state registrations is an
 *   ordinary client, not an edge case. The CA's only route was a second fake
 *   "client" per GSTIN, which splits ONE entity's accounting across two
 *   ledgers and breaks every client-scoped report.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Whether a GSTIN is well formed,
 * which state it belongs to, whether the client already holds it and which
 * registration types file GSTR-1 and GSTR-3B at all are
 * `domain/gst/registrations.py`'s answers, served by
 * /api/client-gst-registrations.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { Plus, AlertTriangle, X, Info } from "lucide-react";
import { api, type ClientGstRegistration, type GstRegistrationKinds,
         type ClientGstTurnover } from "@/lib/api";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { YearPicker } from "@/components/ui/year-picker";
import { formatPaise } from "@/lib/money/format";
import { Cmp08Panel } from "@/components/gst/Cmp08Panel";
import { Gstr8Panel } from "@/components/gst/Gstr8Panel";
import { Gstr4AnnualPanel } from "@/components/gst/Gstr4AnnualPanel";

type Msg = { type: "ok" | "err"; text: string } | null;

const BLANK = {
  gstin: "",
  registration_type: "regular",
  filing_frequency: "monthly",
  trade_name: "",
  effective_from: "",
  composition_category: "",
};

/** Underscores out, first letter up — the same derivation the day book uses on
 *  a journal source, rather than a label map that would be a second copy of
 *  the server's list. */
function pretty(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : value;
}

export default function RegistrationsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<ClientGstRegistration[]>([]);
  const [kinds, setKinds] = useState<GstRegistrationKinds | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  /** Which registration is having its s.29 end date recorded, and the date so
   *  far. A real date control rather than a text prompt: the column is a DATE
   *  and a typed "31/03/2027" reaches the server as a 400 the CA cannot act on. */
  const [closing, setClosing] = useState<{ id: string; on: string } | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  // GST-17 — the aggregate turnover Table 12's HSN digit requirement reads on.
  const [turnover, setTurnover] = useState<ClientGstTurnover | null>(null);
  const [tvForm, setTvForm] = useState({ fy: "", amount: "", note: "" });
  const [tvSaving, setTvSaving] = useState(false);

  // ONE flag, derived from every action on this tab. Two independent ones let
  // the Record button start while Add is still running, and the two requests
  // fight over the same screen — `scripts/concurrent-actions.test.ts` states
  // the rule and caught exactly that when the turnover panel was added.
  const busy = saving || tvSaving || busyId !== null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.clientGstRegistrations.list(clientId);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the registrations.");
      setRows(arrayOrEmpty(res.data));
      setLoadFailed(false);
    } catch {
      // Not swallowed into an empty list: on this tab "none" reads as an
      // invitation to add the primary a second time.
      setRows([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  const loadTurnover = useCallback(async () => {
    try {
      const res = await api.clientGstRegistrations.turnover(clientId);
      if (res.success && res.data) {
        setTurnover(objectWithLists<ClientGstTurnover>(res.data, "years"));
        // Open on the year that GOVERNS, which is the one a CA is here to
        // record — not on "this year", whose figure is not known until it ends.
        setTvForm((f) => f.fy ? f : { ...f, fy: res.data!.governing_financial_year });
      }
    } catch { /* the panel says it could not read rather than showing nothing */ }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadTurnover(); }, [loadTurnover]);

  async function saveTurnover() {
    const paise = paiseFromRupeeInput(tvForm.amount);
    if (paise === null) {
      setMsg({ type: "err", text: "Enter the aggregate turnover in rupees." });
      return;
    }
    setTvSaving(true);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.recordTurnover({
        client_id: clientId,
        financial_year: tvForm.fy,
        aggregate_turnover_paise: paise,
        source_note: tvForm.note.trim() || null,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't record the turnover.");
      setTvForm((f) => ({ ...f, amount: "", note: "" }));
      setMsg({ type: "ok", text: `Aggregate turnover recorded for FY ${tvForm.fy}.` });
      await loadTurnover();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't record the turnover." });
    } finally {
      setTvSaving(false);
    }
  }

  useEffect(() => {
    let alive = true;
    api.clientGstRegistrations.kinds()
      .then((r) => { if (alive && r.success && r.data) setKinds(objectWithLists<GstRegistrationKinds>(r.data, "registration_types", "composition_categories")); })
      .catch(() => { /* the pickers fall back to what is already selected */ });
    return () => { alive = false; };
  }, []);

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      const chosenType = kinds?.registration_types?.find(
        t => t.value === form.registration_type);
      const res = await api.clientGstRegistrations.create({
        client_id: clientId,
        gstin: form.gstin.trim().toUpperCase(),
        registration_type: form.registration_type,
        filing_frequency: form.filing_frequency,
        trade_name: form.trade_name.trim() || null,
        effective_from: form.effective_from || null,
        composition_category: chosenType?.files_cmp08
          ? (form.composition_category || null) : null,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't add the registration.");
      setShowForm(false);
      setForm(BLANK);
      setMsg({ type: "ok", text: "Registration added. Its returns are prepared separately." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't add the registration." });
    } finally {
      setSaving(false);
    }
  }

  async function handleClose(r: ClientGstRegistration, on: string) {
    if (!on) return;
    setBusyId(r.id ?? null);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.close(r.id as string, clientId, on);
      if (!res.success) throw new Error(res.error ?? "Couldn't record the cancellation.");
      setClosing(null);
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't record the cancellation." });
    } finally {
      setBusyId(null);
    }
  }

  async function handleWithdraw(r: ClientGstRegistration) {
    const ok = await confirmDialog({
      title: `Remove ${r.gstin}?`,
      message: "Only for a registration recorded in error. If it was real and has "
             + "ended, record the cancellation date instead — the returns for the "
             + "periods it was live are still owed.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    setBusyId(r.id ?? null);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.remove(r.id as string, clientId);
      if (!res.success) throw new Error(res.error ?? "Couldn't remove the registration.");
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't remove the registration." });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">GST registrations</h2>
          <p className="text-2xs text-ps-label mt-1 max-w-2xl">
            One client, one legal person — and as many GSTINs as it is registered
            under. CGST Act s.25(1) makes registration state-wise and s.25(2)
            allows one per place of business, so each registration prepares and
            files its own GSTR-1 and GSTR-3B. The primary is the GSTIN on the
            client record; add the rest here.
          </p>
        </div>
        <button onClick={() => { setForm(BLANK); setShowForm(true); }} disabled={busy}
          className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50 flex items-center gap-1.5">
          <Plus size={13} /> Add a registration
        </button>
      </div>

      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.type === "ok"
          ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
          : "bg-state-problem-surface border border-state-problem-border text-state-problem"}`}>
          {msg.text}
        </div>
      )}

      {/* AGGREGATE TURNOVER (GST-17).
          Beside the registrations because it is the same kind of fact: a
          thing about the client's own registration status that no book of
          theirs can answer. CGST s.2(6) is computed on the PAN, all-India,
          and includes exempt supplies and exports, so a second registration's
          supplies count toward it — which is exactly why it is typed here and
          not summed from this client's ledger. */}
      <div className="rounded-lg border border-ps-border bg-white p-4 space-y-3">
        <div>
          <h3 className="text-xs font-semibold text-ps-ink">Aggregate turnover</h3>
          <p className="text-2xs text-ps-label mt-1 max-w-2xl">
            CGST Act s.2(6) aggregate turnover, per financial year. GSTR-1 Table
            12&apos;s minimum HSN digits come off the <strong>preceding</strong>{" "}
            year&apos;s figure (Notification 78/2020-Central Tax): six digits above
            ₹5 crore, four on B2B at or below it. It is computed on the PAN,
            all-India, and includes exempt supplies, exports and inter-State
            supplies between distinct persons — so it cannot be read off this
            client&apos;s books.
          </p>
        </div>

        {turnover && (
          <div className={`rounded-lg px-3 py-2 text-2xs flex items-start gap-1.5 ${
            turnover.governing_turnover_paise === null
              ? "bg-state-attention-surface border border-state-attention-border text-amber-900"
              : "bg-ps-bg border border-ps-border text-ps-label"}`}>
            <Info size={12} className="shrink-0 mt-0.5" />
            <span>
              A return prepared today is governed by{" "}
              <strong>FY {turnover.governing_financial_year}</strong>.{" "}
              {/* The server's own sentence. Re-wording it here would give one
                  gap two descriptions. */}
              {turnover.note ?? "Recorded."}
            </span>
          </div>
        )}

        {turnover && turnover.years.length > 0 && (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-ps-hint border-b border-ps-border">
                <th className="py-1.5 font-semibold">Financial year</th>
                <th className="py-1.5 font-semibold text-right">Aggregate turnover</th>
                <th className="py-1.5 font-semibold">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-border">
              {turnover.years.map((y) => (
                <tr key={y.id}>
                  <td className="py-1.5 font-mono text-ps-body">{y.financial_year}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-ps-body">
                    {formatPaise(y.aggregate_turnover_paise)}
                  </td>
                  <td className="py-1.5 text-ps-label">{y.source_note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="flex items-end gap-2 flex-wrap">
          <label className="text-xs">
            <span className="block text-ps-body font-medium mb-1">Financial year</span>
            <YearPicker value={tvForm.fy} onChange={v => setTvForm(f => ({ ...f, fy: v }))}
            count={8} size="sm" className="w-auto" />
          </label>
          <label className="text-xs">
            <span className="block text-ps-body font-medium mb-1">Aggregate turnover (₹)</span>
            <input value={tvForm.amount} inputMode="decimal"
              onChange={(e) => setTvForm(f => ({ ...f, amount: e.target.value }))}
              aria-label="Aggregate turnover in rupees"
              placeholder="e.g. 6,50,00,000"
              className="px-2.5 py-1.5 border border-ps-border rounded-lg w-44" />
          </label>
          <label className="text-xs flex-1 min-w-[12rem]">
            <span className="block text-ps-body font-medium mb-1">Where it came from</span>
            <input value={tvForm.note}
              onChange={(e) => setTvForm(f => ({ ...f, note: e.target.value }))}
              aria-label="Source of the turnover figure"
              placeholder="GSTR-9 Table 5N, audited accounts, …"
              className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
          </label>
          <button onClick={saveTurnover} disabled={busy || !tvForm.fy || !tvForm.amount.trim()}
            className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50">
            {tvSaving ? "Saving…" : "Record"}
          </button>
        </div>
      </div>

      {loadFailed && (
        <div className="bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2 text-xs text-amber-900 flex gap-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>The registrations could not be read, so this list is not the whole of them. Reload before adding one.</span>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-ps-hint">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-ps-hint">
          No GSTIN is recorded for this client. Record it on the client record first —
          a GST return cannot be prepared without one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-ps-border text-ps-hint text-left">
                <th className="py-2 font-semibold">GSTIN</th>
                <th className="py-2 font-semibold">State</th>
                <th className="py-2 font-semibold">Type</th>
                <th className="py-2 font-semibold">Frequency</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-border">
              {rows.map((r) => (
                <Fragment key={r.gstin}>
                <tr className="align-top">
                  <td className="py-2">
                    <span className="font-mono text-ps-ink">{r.gstin}</span>
                    {r.trade_name && (
                      <span className="block text-3xs text-ps-label">{r.trade_name}</span>
                    )}
                    {/* The primary is the client record's own GSTIN, so it is
                        shown and never editable here. */}
                    {r.is_primary && (
                      <span className="inline-block mt-0.5 px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-3xs">
                        Primary
                      </span>
                    )}
                  </td>
                  <td className="py-2 font-mono text-ps-label">{r.state_code}</td>
                  <td className="py-2">
                    {pretty(r.registration_type)}
                    {/* A registration that files a DIFFERENT form says which
                        one — offering it a GSTR-3B screen offers a return it
                        must not file. */}
                    {r.other_return_form && (
                      <span className="block text-3xs text-amber-800 max-w-xs flex gap-1 mt-0.5">
                        <Info size={10} className="shrink-0 mt-0.5" />{r.other_return_form}
                      </span>
                    )}
                  </td>
                  <td className="py-2">{pretty(r.filing_frequency)}</td>
                  <td className="py-2">
                    {r.effective_to
                      ? <span className="text-ps-label">
                          Cancelled {String(r.effective_to).slice(0, 10)}
                          {/* s.29: a cancelled registration still owes the returns
                              for every period it was live, so it stays listed. */}
                          <span className="block text-3xs text-ps-hint">
                            Returns for the periods it was live are still owed
                          </span>
                        </span>
                      : <span className="text-emerald-700">Active</span>}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {!r.is_primary && (
                      <>
                        {!r.effective_to && closing?.id !== r.id && (
                          <button onClick={() => setClosing({ id: r.id as string, on: "" })}
                            disabled={busy}
                            className="px-2 py-1 text-2xs border border-ps-border rounded hover:bg-ps-bg disabled:opacity-40">
                            Cancelled…
                          </button>
                        )}
                        {closing?.id === r.id && (
                          <span className="inline-flex items-center gap-1">
                            <input type="date" value={closing.on} autoFocus
                              aria-label={`Date ${r.gstin} was cancelled or surrendered`}
                              onChange={(e) => setClosing({ id: r.id as string, on: e.target.value })}
                              className="px-1.5 py-1 text-2xs border border-ps-border rounded" />
                            <button onClick={() => handleClose(r, closing.on)}
                              disabled={busy || !closing.on}
                              className="px-2 py-1 text-2xs bg-brand text-white rounded hover:bg-brand-dark disabled:opacity-40">
                              Record
                            </button>
                            <button onClick={() => setClosing(null)} disabled={busy}
                              className="px-1.5 py-1 text-2xs text-ps-hint hover:text-ps-body">
                              Cancel
                            </button>
                          </span>
                        )}
                        <button onClick={() => handleWithdraw(r)} disabled={busy}
                          className="ml-1 px-2 py-1 text-2xs text-ps-hint hover:text-red-600 disabled:opacity-40">
                          Remove
                        </button>
                      </>
                    )}
                  </td>
                </tr>
                {/* A composition registration never files GSTR-1/3B — CMP-08
                    is the return it DOES owe, so it is offered right here
                    rather than on a return screen it must not open. Not for
                    a cancelled one: s.29 closes it, but the returns it still
                    owes are for periods already past, not a fresh quarter. */}
                {r.files_cmp08 && !r.effective_to && (
                  <tr>
                    <td colSpan={6} className="pb-2">
                      <Cmp08Panel clientId={clientId} gstin={r.gstin} />
                    </td>
                  </tr>
                )}
                {/* A s.52 e-commerce operator files GSTR-8, never GSTR-1/3B —
                    same reasoning as CMP-08 above. */}
                {r.files_gstr8 && !r.effective_to && (
                  <tr>
                    <td colSpan={6} className="pb-2">
                      <Gstr8Panel clientId={clientId} gstin={r.gstin} />
                    </td>
                  </tr>
                )}
                {/* The same COMPOSITION registration that files CMP-08 also
                    files GSTR-4 Annual — a separate boolean and a separate
                    panel, never inferred from files_cmp08 coinciding today. */}
                {r.files_gstr4_annual && !r.effective_to && (
                  <tr>
                    <td colSpan={6} className="pb-2">
                      <Gstr4AnnualPanel clientId={clientId} gstin={r.gstin} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
          <div className="w-full max-w-md h-full bg-white shadow-xl flex flex-col">
            <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between">
              <p className="text-sm font-semibold text-ps-ink">Add a GST registration</p>
              <button onClick={() => setShowForm(false)} aria-label="Close"
                className="p-1 rounded hover:bg-ps-muted text-ps-label"><X size={16} /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">GSTIN *</span>
                <input value={form.gstin} maxLength={15}
                  onChange={(e) => setForm(f => ({ ...f, gstin: e.target.value.toUpperCase() }))}
                  placeholder="29AABCU9603R1ZJ"
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg font-mono" />
                <span className="block text-3xs text-ps-hint mt-1 leading-tight">
                  The state is the GSTIN&apos;s own first two characters and is not asked
                  for separately — a registration is state-wise.
                </span>
              </label>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Registration type</span>
                <select value={form.registration_type}
                  onChange={(e) => setForm(f => ({ ...f, registration_type: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg">
                  {(kinds?.registration_types ?? [{ value: form.registration_type, files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }])
                    .map((t) => (
                      <option key={t.value} value={t.value}>{pretty(t.value)}</option>
                    ))}
                </select>
                {(() => {
                  const chosen = kinds?.registration_types?.find(t => t.value === form.registration_type);
                  if (!chosen?.other_return_form) return null;
                  // The return this type owes IS prepared here, on this same
                  // row once added, for exactly the types this screen knows
                  // how to prepare (files_cmp08, files_gstr8, files_gstr4_annual)
                  // — every other one genuinely is not, so the two get
                  // different sentences.
                  const prepared = chosen.files_cmp08 || chosen.files_gstr8 || chosen.files_gstr4_annual;
                  return (
                    <span className="block text-3xs text-amber-800 mt-1 leading-tight">
                      {chosen.other_return_form}. No GSTR-1 or GSTR-3B will be
                      prepared for it{prepared
                        ? " — its own return is, once this registration is added"
                        : ", which this product does not yet build"}.
                    </span>
                  );
                })()}
              </label>

              {kinds?.registration_types?.find(t => t.value === form.registration_type)?.files_cmp08 && (
                <label className="text-xs block">
                  <span className="block text-ps-body font-medium mb-1">
                    Which s.10 rate applies
                  </span>
                  <select value={form.composition_category}
                    onChange={(e) => setForm(f => ({ ...f, composition_category: e.target.value }))}
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg">
                    <option value="">Not recorded yet</option>
                    {(kinds?.composition_categories ?? []).map((c) => (
                      <option key={c.value} value={c.value}>
                        {pretty(c.value)} ({(c.rate_bps / 100).toFixed(0)}%)
                      </option>
                    ))}
                  </select>
                  <span className="block text-3xs text-ps-hint mt-1 leading-tight">
                    A manufacturer or trader, a restaurant and another service
                    provider each pay a different rate on the same turnover
                    (CGST Act s.10). Leaving this unrecorded still lets its
                    return be prepared — it names the gap instead of a figure.
                    {kinds && !kinds.composition_rates_verified && (
                      <> Rates shown are not independently verified against
                      Rule 7 in this environment.</>
                    )}
                  </span>
                </label>
              )}

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Filing frequency</span>
                <select value={form.filing_frequency}
                  onChange={(e) => setForm(f => ({ ...f, filing_frequency: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg">
                  {(kinds?.filing_frequencies ?? [form.filing_frequency]).map((v) => (
                    <option key={v} value={v}>{pretty(v)}</option>
                  ))}
                </select>
              </label>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Trade name</span>
                <input value={form.trade_name}
                  onChange={(e) => setForm(f => ({ ...f, trade_name: e.target.value }))}
                  placeholder="Bengaluru depot"
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                <span className="block text-3xs text-ps-hint mt-1 leading-tight">
                  Two registrations in one state are told apart only by this.
                </span>
              </label>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Registered from</span>
                <input type="date" value={form.effective_from}
                  onChange={(e) => setForm(f => ({ ...f, effective_from: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
              </label>
            </div>

            <div className="px-5 py-3 border-t border-ps-border flex justify-end gap-2">
              <button onClick={() => setShowForm(false)}
                className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button onClick={handleSave} disabled={busy || !form.gstin.trim()}
                className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50">
                {saving ? "Adding…" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
