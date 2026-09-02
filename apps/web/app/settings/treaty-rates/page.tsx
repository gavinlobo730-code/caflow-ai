"use client";

/**
 * The firm's own reading of the DTAA rates it withholds under.
 *
 * WHY A TABLE AND NOT A FIELD ON A VENDOR
 *   A treaty rate is a fact about a COUNTRY and an ARTICLE, not about a
 *   supplier: royalty to Switzerland is the same rate whichever Swiss company
 *   is paid, and the same agreement commonly gives royalty, fees for technical
 *   services, interest and dividends four different rates.
 *
 * THIS SHIPS EMPTY AND IS NEVER SEEDED
 *   India has agreements with over ninety countries, their articles differ, MFN
 *   clauses need their own §90(1) notification (AO v. Nestlé SA, 2023), and a
 *   wrong rate too low disallows the whole expenditure under IT Act §40(a)(i)
 *   while too high takes money off a supplier who can only recover it by filing
 *   an Indian return. A CA reads the agreement and records what they read.
 *
 * Zero business logic here (CLAUDE.md): the backend validates every field and
 * owns §90(2), which gives the assessee whichever of this and the Act rate is
 * lower.
 */
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Trash2, Globe2, X } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type TreatyRateRow } from "@/lib/api/index";
import { bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { TableSkeleton } from "@/components/ui/skeleton";

const NATURE_LABELS: Record<string, string> = {
  royalty: "Royalty",
  fees_for_technical_services: "Fees for technical services",
  interest: "Interest",
  interest_194lc: "Interest — §194LC concessional",
  dividend: "Dividend",
  ltcg_112: "Long-term capital gains — §112",
  ltcg_112a: "Long-term capital gains — §112A",
  stcg_111a: "Short-term capital gains — §111A",
  business_profits_no_pe: "Business profits — no PE",
  other_sums: "Other sums chargeable",
};

export default function TreatyRatesPage() {
  const [rows, setRows] = useState<TreatyRateRow[]>([]);
  const [natures, setNatures] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [country, setCountry] = useState("");
  const [nature, setNature] = useState("");
  const [rate, setRate] = useState("");
  const [noArticle, setNoArticle] = useState(false);
  const [articleRef, setArticleRef] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.treatyRates.list();
      if (res.success && res.data) {
        setRows(res.data.rates ?? []);
        setNatures(res.data.natures ?? []);
      } else {
        setMsg({ type: "err", text: res.error ?? "Could not load treaty rates." });
      }
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not load treaty rates." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function reset() {
    setCountry(""); setNature(""); setRate(""); setNoArticle(false);
    setArticleRef(""); setNotes("");
  }

  async function save() {
    setMsg(null);
    // Read the rate through the exact percentage parser, like every other rate
    // in this app — "10" is 1000 bps and a blank field is genuinely unset.
    let bps: number | null = null;
    if (!noArticle) {
      bps = bpsFromPercentInput(rate);
      if (bps === null) {
        setMsg({ type: "err", text: "Rate must be a percentage, e.g. 10 or 7.5 — or tick 'no article' if the agreement has none for this nature." });
        return;
      }
    }
    setSaving(true);
    try {
      const res = await api.treatyRates.upsert({
        country_code: country.trim().toUpperCase(),
        nature,
        rate_bps: noArticle ? null : bps,
        no_article: noArticle,
        article_ref: articleRef.trim() || null,
        notes: notes.trim() || null,
      });
      if (!res.success) throw new Error(res.error ?? "Could not save.");
      setMsg({ type: "ok", text: "Saved." });
      setShowForm(false);
      reset();
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not save." });
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: TreatyRateRow) {
    const ok = await confirmDialog({
      title: "Remove this reading?",
      message: `${row.country_code} · ${NATURE_LABELS[row.nature] ?? row.nature}. Bills already booked keep what they withheld — a deduction records what was true at the time, not what this table says today.`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.treatyRates.remove(row.id);
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not remove." });
    }
  }

  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <div className="p-6 max-w-5xl mx-auto space-y-5">
        <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#64748B] hover:text-[#0F172A]">
          <ChevronLeft size={14} /> Settings
        </Link>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-[#0F172A] flex items-center gap-2">
              <Globe2 size={18} className="text-sky-500" /> DTAA Treaty Rates
            </h1>
            <p className="text-xs text-[#64748B] mt-1 max-w-2xl">
              Your firm&apos;s reading of the agreements it withholds under, one row per country
              and nature of income. Nothing is shipped or suggested here: India has agreements
              with over ninety countries, MFN clauses need their own §90(1) notification, and a
              wrong rate too low disallows the whole expenditure under §40(a)(i). §90(2) then
              applies whichever of your rate and the Act rate is lower.
            </p>
          </div>
          <button
            onClick={() => { reset(); setShowForm(true); }}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700"
          >
            <Plus size={14} /> Add reading
          </button>
        </div>

        {msg && (
          <div className={`text-xs px-3 py-2 rounded-lg ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {msg.text}
          </div>
        )}

        {showForm && (
          <div className="border border-[#E2E8F0] rounded-xl p-4 space-y-3 bg-white">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-[#0F172A]">Record a reading</p>
              <button onClick={() => setShowForm(false)} className="text-[#94A3B8] hover:text-[#0F172A]"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label htmlFor="tr-country" className="block text-xs font-medium text-[#475569] mb-1">Country (ISO code)</label>
                <input id="tr-country" value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} maxLength={2} placeholder="AE"
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-sky-500" />
              </div>
              <div>
                <label htmlFor="tr-nature" className="block text-xs font-medium text-[#475569] mb-1">Nature of income</label>
                <select id="tr-nature" value={nature} onChange={(e) => setNature(e.target.value)}
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500">
                  <option value="">Select…</option>
                  {natures.map((n) => <option key={n} value={n}>{NATURE_LABELS[n] ?? n}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="tr-rate" className="block text-xs font-medium text-[#475569] mb-1">Rate (%)</label>
                <input id="tr-rate" value={rate} onChange={(e) => setRate(e.target.value)} disabled={noArticle} placeholder="10"
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              </div>
            </div>
            <label className="flex items-start gap-2 text-xs text-[#475569]">
              <input type="checkbox" checked={noArticle} onChange={(e) => setNoArticle(e.target.checked)} className="rounded mt-0.5" />
              <span>
                The agreement has <strong>no article</strong> for this nature. Several — the UAE and
                Singapore among them — have no fees-for-technical-services article, which makes the
                income Article 7 business profits and not taxable in India without a permanent
                establishment. That is an answer, not a missing rate.
              </span>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="tr-article" className="block text-xs font-medium text-[#475569] mb-1">Article relied on</label>
                <input id="tr-article" value={articleRef} onChange={(e) => setArticleRef(e.target.value)} placeholder="Article 12(2)"
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500" />
              </div>
              <div>
                <label htmlFor="tr-notes" className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
                <input id="tr-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="MFN position, protocol date, conditions…"
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500" />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
              <button onClick={save} disabled={saving || !country || !nature} className="text-xs px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 disabled:opacity-40">
                {saving ? "Saving…" : "Save reading"}
              </button>
            </div>
          </div>
        )}

        {loading ? <TableSkeleton /> : rows.length === 0 ? (
          <div className="border border-dashed border-[#E2E8F0] rounded-xl p-8 text-center">
            <p className="text-sm text-[#475569]">No treaty readings recorded.</p>
            <p className="text-xs text-[#94A3B8] mt-1 max-w-md mx-auto">
              Until a country and nature are recorded here, a bill for a non-resident vendor
              holding a Tax Residency Certificate is refused rather than withheld at the Act
              rate — which would over-deduct on a payment a treaty already covers.
            </p>
          </div>
        ) : (
          <div className="border border-[#E2E8F0] rounded-xl overflow-hidden bg-white">
            <table className="w-full text-sm">
              <thead className="bg-[#F8FAFC] text-xs text-[#64748B]">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Country</th>
                  <th className="text-left px-4 py-2 font-medium">Nature of income</th>
                  <th className="text-right px-4 py-2 font-medium">Rate</th>
                  <th className="text-left px-4 py-2 font-medium">Article</th>
                  <th className="text-left px-4 py-2 font-medium">Recorded</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-[#F1F5F9]">
                    <td className="px-4 py-2 font-mono text-[#0F172A]">{r.country_code}</td>
                    <td className="px-4 py-2 text-[#475569]">{NATURE_LABELS[r.nature] ?? r.nature}</td>
                    <td className="px-4 py-2 text-right">
                      {r.no_article
                        ? <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">No article</span>
                        : <span className="font-medium text-[#0F172A]">{((r.rate_bps ?? 0) / 100).toFixed(2)}%</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-[#64748B]">{r.article_ref ?? "—"}</td>
                    <td className="px-4 py-2 text-xs text-[#94A3B8]">{r.verified_on ?? "—"}</td>
                    <td className="px-4 py-2 text-right">
                      <button onClick={() => remove(r)} aria-label={`Remove ${r.country_code} ${r.nature}`}
                        className="text-[#94A3B8] hover:text-red-600"><Trash2 size={14} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </RoleGuard>
  );
}
