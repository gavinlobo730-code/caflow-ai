"use client";
/**
 * Recording an exchange rate — the table nothing could write.
 *
 * `public.fx_rates` (migration 146) is what every foreign invoice, bill,
 * receipt and payment resolves its booking rate through, and no endpoint,
 * field, screen or seed ever put a row in it. ACC-19 made the multi-currency
 * gates switchable, which turned that from dormant into live: a Partner can
 * now turn the feature on and find the one thing it needs cannot be recorded.
 *
 * THE RATE IS SHARED ACROSS THE PLATFORM AND THIS SCREEN SAYS SO
 *   USD→INR on a date is a fact about the world — the RBI publishes one — so
 *   the table is global and the tenancy answer is on the WRITE side:
 *   Partner-only, with `created_by` stamped. A firm-scoped copy would have
 *   every firm re-typing the same number, and the rate a document was booked
 *   at would depend on who typed it. The owner's decision, and the sentence
 *   rendered below is the half of it a person has to see.
 *
 * THE RATE IS TEXT ALL THE WAY DOWN
 *   The column is NUMERIC(18,8) precisely so a rate is exact, and `RateQuote`
 *   reads it back through `Decimal(str(...))`. So it is typed as text, sent as
 *   text and rendered as text — a `parseFloat` anywhere on this path would put
 *   a float round trip in front of a column chosen to avoid one. It is
 *   deliberately NOT `paiseFromRupeeInput`: that is for money, and a rate is
 *   not an amount of anything.
 *
 * The four rate types and their meanings are SERVED, not spelled here.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type FxRate } from "@/lib/api/index";
import { TableSkeleton } from "@/components/ui/skeleton";

/** A plain decimal, and nothing else. Not a parser — it never converts, so
 *  what is sent is exactly what was typed. */
function looksLikeARate(text: string): boolean {
  return /^\d{1,9}(\.\d{1,8})?$/.test(text.trim()) && Number(text.trim()) > 0;
}

export function FxRatesPanel() {
  const [types, setTypes] = useState<{ code: string; meaning: string }[]>([]);
  const [base, setBase] = useState("USD");
  const [quote] = useState("INR");          // Capability A is INR-functional books.
  const [rateType, setRateType] = useState("booking");
  const [rows, setRows] = useState<FxRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [when, setWhen] = useState("");
  const [rate, setRate] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [t, r] = await Promise.all([
        api.currencies.rateTypes(),
        api.currencies.rates({ base, quote, rate_type: rateType }),
      ]);
      if (t.success && t.data) setTypes(t.data.rate_types);
      if (!r.success || !r.data) throw new Error(r.error ?? "failed");
      setRows(r.data.rates);
    } catch {
      setRows([]);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [base, quote, rateType]);

  useEffect(() => { load(); }, [load]);

  async function save() {
    if (!looksLikeARate(rate)) {
      setMsg({ ok: false, text: "The rate must be a plain decimal, e.g. 83.4200 — no commas." });
      return;
    }
    if (!when) {
      setMsg({ ok: false, text: "Which date is this the rate for?" });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.currencies.recordRate({
        base, quote, rate_date: when, rate: rate.trim(), rate_type: rateType });
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't save the rate.");
      setMsg({ ok: true, text: res.data.replaced
        ? `Replaced the ${rateType} rate already recorded for ${when}.`
        : `Recorded ${base}/${quote} at ${res.data.rate} for ${when}.` });
      setRate("");
      await load();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Couldn't save the rate." });
    } finally {
      setSaving(false);
    }
  }

  const meaning = types.find((t) => t.code === rateType)?.meaning;

  return (
    <section className="mt-8">
      <h2 className="text-sm font-semibold text-ps-ink">Exchange rates</h2>
      <p className="mt-1 text-xs text-ps-label">
        A rate is a fact about the world, so these are shared across the whole
        platform — every firm sees the same {base}/{quote} rate for a date, and
        only a Partner can record one. Nothing is fetched automatically.
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="fx-base" className="block text-2xs font-medium text-ps-label mb-1">Currency</label>
          <input id="fx-base" value={base} maxLength={3}
            onChange={(e) => setBase(e.target.value.toUpperCase())}
            className="w-20 text-xs px-2 py-1.5 border border-ps-border rounded-lg font-mono" />
        </div>
        <span className="pb-2 text-xs text-ps-hint">&rarr; {quote}</span>
        <div>
          <label htmlFor="fx-type" className="block text-2xs font-medium text-ps-label mb-1">Rate type</label>
          <select id="fx-type" value={rateType} onChange={(e) => setRateType(e.target.value)}
            className="text-xs px-2 py-1.5 border border-ps-border rounded-lg">
            {types.map((t) => <option key={t.code} value={t.code}>{t.code}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="fx-date" className="block text-2xs font-medium text-ps-label mb-1">For the date</label>
          <input id="fx-date" type="date" value={when} onChange={(e) => setWhen(e.target.value)}
            className="text-xs px-2 py-1.5 border border-ps-border rounded-lg" />
        </div>
        <div>
          <label htmlFor="fx-rate" className="block text-2xs font-medium text-ps-label mb-1">Rate</label>
          <input id="fx-rate" value={rate} inputMode="decimal" placeholder="83.4200"
            onChange={(e) => setRate(e.target.value)}
            className="w-32 text-xs px-2 py-1.5 border border-ps-border rounded-lg font-mono text-right" />
        </div>
        <button onClick={save} disabled={saving}
          className="text-xs px-4 py-2 bg-brand text-white rounded-lg disabled:opacity-50">
          {saving ? "Saving…" : "Record rate"}
        </button>
      </div>

      {/* What this rate type IS. The server's sentence, because the four are not
          interchangeable — recording a market rate as gst_notified declares a
          different taxable value from the one CGST Rule 34 fixes. */}
      {meaning && <p className="mt-2 text-2xs text-ps-hint max-w-2xl">{meaning}</p>}

      {msg && (
        <p className={`mt-2 text-xs ${msg.ok ? "text-state-ready" : "text-state-problem"}`}>
          {msg.text}
        </p>
      )}

      <div className="mt-4">
        {loading ? <TableSkeleton rows={3} /> : failed ? (
          <p className="text-xs text-state-problem">
            The recorded rates could not be loaded, so this is not &ldquo;none
            recorded&rdquo;.
          </p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-ps-hint">
            No {rateType} rate has been recorded for {base}/{quote}. A foreign
            document dated before the first one has no rate to book at.
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-ps-label border-b border-ps-border">
                <th className="py-1.5 font-medium">Date</th>
                <th className="py-1.5 font-medium text-right">Rate</th>
                <th className="py-1.5 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id ?? `${r.rate_date}-${r.rate_type}`} className="border-b border-ps-border/60">
                  <td className="py-1.5 text-ps-body">{r.rate_date}</td>
                  {/* Rendered as the stored TEXT. Formatting it through a
                      number would drop trailing precision the column keeps. */}
                  <td className="py-1.5 text-right font-mono text-ps-ink">{r.rate}</td>
                  <td className="py-1.5 text-ps-hint">{r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
