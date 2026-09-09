"use client";

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { changedFields, formFor, type CorrectionForm } from "@/lib/fixedAssets/correction";
import { request } from "@/lib/api";
import { useEffect, useState, useCallback } from "react";
import { Plus, RefreshCw, ChevronDown, ChevronRight, Trash2, TrendingDown, AlertCircle } from "lucide-react";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import FinancialYearPicker from "@/components/FinancialYearPicker";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { TableSkeleton } from "@/components/ui/skeleton";

import { todayLocalISO } from "@/lib/dateMath";
// NO local API base and no bare fetch. Every call on this screen used to be
// `fetch(`${API}/api/fixed-assets/...`, { credentials: "include" })`, and
// `credentials` carries a COOKIE — which this API does not read. core/auth.py
// accepts an Authorization header and nothing else, and every route in
// routers/fixed_assets.py is Depends(rbac("accounting", …)), so all seven
// calls answered 401 in production and the whole screen was dead. `request`
// from lib/api is the one client that attaches the Bearer token (and refreshes
// it once on a 401, and reads a refusal out of `detail`).

type FATab = "register" | "depreciation" | "disposal" | "reports";

const TABS: { id: FATab; label: string }[] = [
  { id: "register",    label: "Asset Register" },
  { id: "depreciation",label: "Depreciation" },
  { id: "disposal",    label: "Disposal" },
  { id: "reports",     label: "Reports" },
];

interface Asset {
  id: string;
  asset_code?: string;
  asset_name: string;
  asset_category: string;
  location?: string;
  purchase_date: string;
  purchase_cost_paise: number;
  salvage_value_paise: number;
  depreciation_method: "WDV" | "SL";
  wdv_rate_percent?: number;
  useful_life_years?: number;
  accumulated_depreciation_paise: number;
  is_disposed: boolean;
  current_wdv_paise?: number;
  status: "active" | "disposed" | "fully_depreciated";
  notes?: string;
}

// fixed_assets has no status column (migration 025/054) — routers/
// fixed_assets.py never computes one either, only current_wdv_paise. Derive
// the display status the same way the backend's own "fully depreciated"
// check does (_compute_annual_depreciation: wdv_now <= salvage).
function computeAssetStatus(a: Pick<Asset, "is_disposed" | "purchase_cost_paise" | "accumulated_depreciation_paise" | "salvage_value_paise">): Asset["status"] {
  if (a.is_disposed) return "disposed";
  const wdv = a.purchase_cost_paise - a.accumulated_depreciation_paise;
  return wdv <= a.salvage_value_paise ? "fully_depreciated" : "active";
}

// Companies Act 2013, Schedule II Part C — the categories and the useful LIVES
// the statute prescribes, served by GET /api/fixed-assets/categories and never
// held here.
//
// This page used to carry its own CATEGORIES list and its own WDV_RATES table.
// The backend carried an identical pair, and both were wrong in the same way:
// they were mostly INCOME TAX ACT block rates under a "Companies Act 2013 Sch
// II" label, with the correct ten-year figure sitting against Vehicles, which
// Schedule II gives eight years. Two copies of a statutory table is how that
// survives — so there is one now, in apps/api, and this is its shape.
interface ScheduleIIClass {
  label: string;
  /** null where Schedule II prescribes no life (intangibles, "Other", land). */
  useful_life_years: number | null;
  /** Derived from the life: R = 1 − (residual/cost)^(1/n). null where there is none. */
  wdv_rate_percent: number | null;
}

interface AssetCategory {
  category: string;
  depreciable: boolean;
  residual_value_cap_percent: number;
  classes: ScheduleIIClass[];
}

/** A schedule row as routers/fixed_assets.py computes it — the charge, and the
 *  basis it was computed on. Nothing on this page recomputes any of it. */
interface ScheduleRow {
  asset_id: string;
  asset_code?: string | null;
  asset_name: string;
  asset_category: string;
  purchase_cost_paise: number;
  accumulated_paise: number;
  current_wdv_paise: number;
  annual_depreciation_paise: number;
  monthly_depreciation_paise: number;
  depreciation_method: "WDV" | "SL";
  salvage_value_paise: number;
  wdv_rate_percent?: number | null;
  useful_life_years?: number | null;
  depreciation_posted_through?: string | null;
  /** Set where the asset has no statutory basis for a charge — shown as a
   *  reason beside the zero, because a zero with no reason reads as "nothing
   *  to depreciate". */
  statutory_gap?: string | null;
}

/** What the create form says under the rate (or life) field. It repeats the
 *  class the backend served back to the CA — the life, the rate derived from
 *  it, and the residual cap it came from — and says plainly where Schedule II
 *  prescribes nothing. It computes no rate of its own. */
function scheduleIINote(cat: AssetCategory | undefined, cls: ScheduleIIClass | undefined, method: "WDV" | "SL"): string {
  if (!cat || !cls) return "Companies Act 2013, Schedule II Part C.";
  if (!cat.depreciable) {
    return `${cat.category} is not depreciated under Schedule II — there is no useful life to spread a cost over.`;
  }
  if (cls.useful_life_years == null) {
    return `Schedule II prescribes no useful life for ${cat.category}, so there is no rate to pre-fill — `
      + `record the ${method === "WDV" ? "rate" : "life"} the CA has determined. `
      + `Intangibles are amortised under AS 26 / Ind AS 38.`;
  }
  return `Schedule II Part C: ${cls.label} — ${cls.useful_life_years} years, which is `
    + `${cls.wdv_rate_percent}% on the written-down value at the `
    + `${cat.residual_value_cap_percent}% residual cap. Change it where the CA has `
    + `determined a different life.`;
}

/** The sentence out of a refusal. FastAPI answers with {"detail": "..."} and
 *  these details are written for the CA — "Depreciation for 2026-09 has not
 *  been posted". Swallowing them is what made a skipped month invisible. */
/** Every backend response is { success, data, error } — models/common.api_response.
 *  `detail` is FastAPI's own shape for a 4xx and rides along so refusalMessage
 *  can read either. */
interface ApiEnvelope<T = unknown> { success: boolean; data?: T; error?: string; detail?: unknown }

function refusalMessage(body: { detail?: unknown; error?: unknown }, fallback: string): string {
  const detail = body?.detail ?? body?.error;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  return fallback;
}

function fmt(paise: number) {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function fmtDate(d: string) {
  try { return new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return d; }
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function FixedAssetsPage() {
  const { clientId } = useClientNav();
  // Was a read-only "FY 2026-27" pill fed by the header selector. It is now
  // the control itself: the badge always said which year the depreciation
  // below belonged to, but changing it meant leaving the page to do it.
  const [financialYear, setFinancialYear] = useState(getCurrentFinancialYear());
  const [tab, setTab] = useState<FATab>("register");

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 py-4 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-base font-semibold text-[#1E293B]">Fixed Assets</h1>
          <p className="text-[11px] text-[#94A3B8] mt-0.5">
            Companies Act 2013, Schedule II — WDV &amp; SL depreciation
          </p>
        </div>
        <FinancialYearPicker value={financialYear} onChange={setFinancialYear} />
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 shrink-0">
        <nav className="flex gap-0">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-3 text-xs font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-[#64748B] hover:text-[#1E293B]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-6">
        {tab === "register"     && <RegisterTab    clientId={clientId} />}
        {tab === "depreciation" && <DepreciationTab clientId={clientId} />}
        {tab === "disposal"     && <DisposalTab     clientId={clientId} />}
        {tab === "reports"      && <ReportsTab      clientId={clientId} financialYear={financialYear} />}
      </div>
    </div>
  );
}

// ── Asset Register ─────────────────────────────────────────────────────────

function RegisterTab({ clientId }: { clientId: string }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  // True when the LAST load failed (thrown/PostgREST error) rather than the
  // client genuinely having no assets — without this a failed load renders
  // identically to an empty register: "No assets" + Gross/Net Block ₹0 (M17).
  const [loadFailed, setLoadFailed] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<Asset | null>(null);
  const [deleting, setDeleting] = useState<Asset | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // Direct Supabase, not api.fixed-assets.list() — that endpoint is a
      // plain client_id-scoped select (RLS enforces firm_id) filtered to
      // non-disposed assets, plus one derived field (current_wdv_paise =
      // purchase_cost_paise - accumulated_depreciation_paise, recomputed on
      // every read, never persisted — see routers/fixed_assets.py:list_assets).
      // No business logic here worth an extra backend hop for.
      const supabase = getSupabaseClient();
      const { data, error } = await selectAll(() => supabase
        .from("fixed_assets")
        .select("id, asset_code, asset_name, asset_category, location, purchase_date, purchase_cost_paise, salvage_value_paise, depreciation_method, wdv_rate_percent, useful_life_years, accumulated_depreciation_paise, is_disposed, notes")
        .eq("client_id", clientId)
        .eq("is_disposed", false)
        .order("purchase_date", { ascending: false })
        .order("id"));
      // A non-null PostgREST error is a real failure, not an empty register.
      if (error) throw error;
      const rows = ((data as Omit<Asset, "current_wdv_paise" | "status">[]) ?? []).map((a) => ({
        ...a,
        current_wdv_paise: a.purchase_cost_paise - a.accumulated_depreciation_paise,
        status: computeAssetStatus(a),
      }));
      setAssets(rows);
      setLoadFailed(false);
    } catch {
      setAssets([]); setLoadFailed(true);
    } finally {
      // In a finally rather than after the catch: a throw from inside the catch
      // (or a `return` added inside the try later) would skip a trailing call
      // and leave this tab as a permanent skeleton.
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const STATUS_BADGE: Record<string, string> = {
    active:             "bg-green-100 text-green-700",
    disposed:           "bg-red-100 text-red-700",
    fully_depreciated:  "bg-gray-100 text-gray-600",
  };

  // Summary stats
  const totalCost  = assets.reduce((s, a) => s + a.purchase_cost_paise, 0);
  const totalAccum = assets.reduce((s, a) => s + a.accumulated_depreciation_paise, 0);
  const totalWDV   = totalCost - totalAccum;

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Gross Block", value: loadFailed ? "—" : fmt(totalCost), accent: "blue" },
          { label: "Accumulated Depreciation", value: loadFailed ? "—" : fmt(totalAccum), accent: "amber" },
          { label: "Net Block (WDV)", value: loadFailed ? "—" : fmt(totalWDV), accent: "green" },
        ].map((c) => (
          <div key={c.label} className="bg-white rounded-xl border border-[#E2E8F0] px-5 py-4">
            <p className="text-[11px] text-[#94A3B8] font-medium">{c.label}</p>
            <p className="text-lg font-bold text-[#1E293B] mt-1 font-mono">{c.value}</p>
          </div>
        ))}
      </div>

      {/* Table header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{assets.length} asset{assets.length !== 1 ? "s" : ""}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> Add Asset
          </button>
        </div>
      </div>

      {loading ? (
        <TableSkeleton cols={11} rows={4} />
      ) : loadFailed ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <p className="text-sm text-red-600 font-medium">Couldn&apos;t load the asset register — the request failed or timed out.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : assets.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <TrendingDown size={32} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No assets added yet</p>
          <button onClick={() => setShowAdd(true)} className="text-xs text-blue-600 hover:underline">Add your first asset</button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                <th className="px-4 py-3 text-left font-semibold w-5"></th>
                <th className="px-2 py-3 text-left font-semibold">Code</th>
                <th className="px-3 py-3 text-left font-semibold">Asset Name</th>
                <th className="px-3 py-3 text-left font-semibold">Category</th>
                <th className="px-3 py-3 text-left font-semibold">Date</th>
                <th className="px-3 py-3 text-right font-semibold">Cost</th>
                <th className="px-3 py-3 text-right font-semibold">Accum Depn</th>
                <th className="px-3 py-3 text-right font-semibold">WDV</th>
                <th className="px-3 py-3 text-left font-semibold">Method</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-3 py-3 text-right font-semibold">Correct</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {assets.map((a) => (
                <>
                  <tr
                    key={a.id}
                    className="hover:bg-[#F8FAFC] cursor-pointer"
                    onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                  >
                    <td className="px-4 py-2.5 text-[#94A3B8]">
                      {expanded === a.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </td>
                    <td className="px-2 py-2.5 font-mono text-[10px] text-[#94A3B8]">{a.asset_code ?? "—"}</td>
                    <td className="px-3 py-2.5 font-medium text-[#1E293B]">{a.asset_name}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">{a.asset_category}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">{fmtDate(a.purchase_date)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(a.purchase_cost_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(a.accumulated_depreciation_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#1E293B]">
                      {fmt(a.purchase_cost_paise - a.accumulated_depreciation_paise)}
                    </td>
                    <td className="px-3 py-2.5 text-[#64748B]">
                      {a.depreciation_method === "WDV"
                        ? `WDV ${a.wdv_rate_percent}%`
                        : `SL ${a.useful_life_years}yr`}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${STATUS_BADGE[a.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                        {a.status.replace("_", " ")}
                      </span>
                    </td>
                    {/* FA-10. Until this the register was final the moment it
                        was saved: a mistyped cost or a wrong category could
                        only be escaped by disposing at nil proceeds (which
                        books a fabricated loss) or by a database console. What
                        may actually be changed, and what has to be reversed
                        first, is decided by the SERVER — the refusal is shown
                        verbatim because it names the way out. */}
                    <td className="px-3 py-2.5 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setCorrecting(a)}
                        className="text-[11px] text-blue-600 hover:underline"
                      >
                        Correct
                      </button>
                      <button
                        onClick={() => setDeleting(a)}
                        className="text-[11px] text-red-600 hover:underline ml-3"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                  {expanded === a.id && (
                    <tr key={`${a.id}-exp`} className="bg-[#F8FAFC]">
                      <td colSpan={11} className="px-8 py-3">
                        <div className="grid grid-cols-4 gap-4 text-xs">
                          <div><span className="text-[#94A3B8]">Location:</span> <span className="text-[#1E293B]">{a.location ?? "—"}</span></div>
                          <div><span className="text-[#94A3B8]">Salvage Value:</span> <span className="text-[#1E293B] font-mono">{fmt(a.salvage_value_paise)}</span></div>
                          <div><span className="text-[#94A3B8]">Notes:</span> <span className="text-[#1E293B]">{a.notes ?? "—"}</span></div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && <AddAssetDrawer clientId={clientId} onClose={() => setShowAdd(false)} onSaved={load} />}
      {correcting && (
        <CorrectAssetDrawer asset={correcting} onClose={() => setCorrecting(null)} onSaved={load} />
      )}
      {deleting && (
        <DeleteAssetDialog asset={deleting} onClose={() => setDeleting(null)} onSaved={load} />
      )}
    </div>
  );
}

// ── Correct an asset (FA-10) ────────────────────────────────────────────────
//
// The register was final the moment it was saved. A CA who typed ₹15,00,000 for
// ₹1,50,000, or picked the wrong category, had three ways out and all three
// were wrong: dispose at nil proceeds (a fabricated loss, and it first demands
// every unposted month be depreciated), reverse the journal through the generic
// accounting screen (the register then claims a cost the ledger no longer
// carries), or a database console.
//
// WHAT THIS SCREEN DOES NOT DECIDE
// Which fields may change, whether the acquisition journal has to be reversed
// and re-posted, whether the period is open, and whether a revised rate is
// prospective — every one of those is the server's. This form sends what was
// touched and shows the refusal verbatim, because the refusal names the way
// out ("reverse it a month at a time", "the year already carries…"). Nothing
// here recomputes a rate: the Schedule II table is served, never mirrored.

function CorrectAssetDrawer({ asset, onClose, onSaved }: { asset: Asset; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<CorrectionForm>(() => formFor(asset));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (k: keyof CorrectionForm, v: string) => setForm(f => ({ ...f, [k]: v }));

  async function save() {
    setError("");
    // Only what the CA actually CHANGED is sent, so the server can tell a
    // rename from a cost correction. Sending the whole form back would put
    // purchase_cost_paise in every request and reverse and re-post a real
    // acquisition journal for a typo in a name field. lib/fixedAssets/
    // correction.ts is that diff and the tests that hold it.
    const diff = changedFields(asset, form);
    if (!diff.ok) { setError(diff.error); return; }
    const body = diff.body;

    setSaving(true);
    try {
      const j = await request<ApiEnvelope>(`/api/fixed-assets/${asset.id}`, {
        method: "PATCH", body: JSON.stringify(body),
      });
      // The GST workspace answers refusals as HTTP 200 with success:false, and
      // so does this router — an unchecked call would show "saved" for a
      // request the server declined.
      if (!j.success) throw new Error(refusalMessage(j, "Could not correct the asset."));
      onSaved(); onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not correct the asset.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex justify-end" onClick={onClose}>
      <div className="bg-white w-full max-w-md h-full overflow-y-auto p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <div>
          <h3 className="text-sm font-semibold text-[#1E293B]">Correct {asset.asset_code ?? asset.asset_name}</h3>
          <p className="text-[11px] text-[#94A3B8] mt-1">
            A change to the cost reverses the acquisition journal and re-posts it. A
            revised rate or life applies from the next financial year, never to a
            month already posted.
          </p>
        </div>

        {[
          { k: "asset_name" as const,        label: "Asset name" },
          { k: "location" as const,          label: "Location" },
          { k: "purchase_cost_rs" as const,  label: "Purchase cost (₹)" },
          { k: "salvage_value_rs" as const,  label: "Salvage value (₹)" },
          { k: "wdv_rate_percent" as const,  label: "WDV rate (%)" },
          { k: "useful_life_years" as const, label: "Useful life (years)" },
          { k: "notes" as const,             label: "Notes" },
          { k: "reason" as const,            label: "Why (recorded on the audit trail)" },
        ].map(f => (
          <div key={f.k}>
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">{f.label}</label>
            <input
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs text-[#1E293B] focus:outline-none focus:ring-2 focus:ring-blue-200"
              value={form[f.k]}
              onChange={e => set(f.k, e.target.value)}
            />
          </div>
        ))}

        {error && (
          <div className="flex gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
            <AlertCircle size={13} className="text-red-600 shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <button onClick={onClose} className="flex-1 text-xs border border-[#E2E8F0] rounded-lg py-2 text-[#334155] hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 text-xs bg-blue-600 text-white rounded-lg py-2 hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Save correction"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Delete an asset created by mistake (FA-10) ──────────────────────────────

function DeleteAssetDialog({ asset, onClose, onSaved }: { asset: Asset; onClose: () => void; onSaved: () => void }) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function remove() {
    setError(""); setWorking(true);
    try {
      const j = await request<ApiEnvelope>(`/api/fixed-assets/${asset.id}`, { method: "DELETE" });
      if (!j.success) throw new Error(refusalMessage(j, "Could not delete the asset."));
      onSaved(); onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not delete the asset.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-xl max-w-sm w-full p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex gap-2">
          <Trash2 size={15} className="text-red-600 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-[#1E293B]">Delete {asset.asset_code ?? asset.asset_name}?</h3>
            <p className="text-[11px] text-[#64748B] mt-1">
              For an asset created by mistake. Its acquisition journal is reversed and the
              asset leaves the register — its code is kept so no later asset can take it.
              An asset with depreciation posted against it cannot be deleted; reverse the
              months first.
            </p>
          </div>
        </div>

        {error && (
          <div className="flex gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
            <AlertCircle size={13} className="text-red-600 shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 text-xs border border-[#E2E8F0] rounded-lg py-2 text-[#334155] hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={remove} disabled={working} className="flex-1 text-xs bg-red-600 text-white rounded-lg py-2 hover:bg-red-700 disabled:opacity-50">
            {working ? "Deleting…" : "Delete asset"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Add Asset Drawer ────────────────────────────────────────────────────────

function AddAssetDrawer({ clientId, onClose, onSaved }: { clientId: string; onClose: () => void; onSaved: () => void }) {
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [catsLoading, setCatsLoading] = useState(true);
  const [catsFailed, setCatsFailed] = useState(false);
  const [form, setForm] = useState({
    asset_name:            "",
    asset_category:        "",
    schedule_ii_class:     0,
    asset_code:            "",
    location:              "",
    purchase_date:         todayLocalISO(),
    purchase_cost_paise:   "",
    salvage_value_paise:   "0",
    depreciation_method:   "WDV" as "WDV" | "SL",
    wdv_rate_percent:      "",
    useful_life_years:     "",
    notes:                 "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Picking a category (or one of its Schedule II classes) pre-fills BOTH the
  // life and the rate from the same served row — they are one figure and its
  // derivation, so they can never be filled in from different places again.
  const applyClass = useCallback((cats: AssetCategory[], category: string, index: number) => {
    const cls = cats.find(c => c.category === category)?.classes[index];
    setForm(f => ({
      ...f,
      asset_category:    category,
      schedule_ii_class: index,
      // Left BLANK where Schedule II prescribes nothing (intangibles, "Other"):
      // the CA records what they determined, and the backend refuses the asset
      // rather than defaulting to a plausible number.
      wdv_rate_percent:  cls?.wdv_rate_percent != null ? String(cls.wdv_rate_percent) : "",
      useful_life_years: cls?.useful_life_years != null ? String(cls.useful_life_years) : "",
    }));
  }, []);

  const loadCategories = useCallback(async () => {
    setCatsLoading(true);
    try {
      const j = await request<ApiEnvelope<AssetCategory[]>>(`/api/fixed-assets/categories?client_id=${clientId}`);
      if (!j.success) throw new Error(refusalMessage(j, "Failed to load categories"));
      const cats: AssetCategory[] = j.data ?? [];
      setCategories(cats);
      setCatsFailed(cats.length === 0);
      if (cats.length) applyClass(cats, cats[0].category, 0);
    } catch {
      setCategories([]); setCatsFailed(true);
    } finally {
      setCatsLoading(false);
    }
  }, [clientId, applyClass]);

  useEffect(() => { loadCategories(); }, [loadCategories]);

  const selected = categories.find(c => c.category === form.asset_category);
  const selectedClass = selected?.classes[form.schedule_ii_class];

  async function save() {
    if (!form.asset_name || !form.purchase_cost_paise) { setError("Asset name and cost are required."); return; }
    if (!form.asset_category) { setError("Pick a category."); return; }
    // The field names still say _paise (they are the payload keys); what the CA
    // types into them is rupees, and this is what reads it exactly.
    const cost = paiseFromRupeeInput(form.purchase_cost_paise);
    const salvage = paiseFromRupeeInput(form.salvage_value_paise || "0");
    if (cost === null || salvage === null) {
      setError("Cost and salvage value must be amounts in rupees, e.g. 125000 or "
               + "125000.50 — without commas.");
      return;
    }
    setSaving(true); setError("");
    try {
      const body = {
        client_id:             clientId,
        asset_name:            form.asset_name,
        asset_category:        form.asset_category,
        asset_code:            form.asset_code || undefined,
        location:              form.location || undefined,
        purchase_date:         form.purchase_date,
        // The cost is the depreciable base for the life of the asset: read it
        // wrong once and every Schedule II charge after it is wrong too.
        purchase_cost_paise:   cost,
        salvage_value_paise:   salvage,
        depreciation_method:   form.depreciation_method,
        // BOTH are sent whichever method is chosen: the life is what Schedule
        // II prescribes and the rate is derived from it, so storing only one
        // of them is what let the two drift apart. A blank field is sent as
        // absent, not as NaN — the backend then either fills in the Schedule
        // II default or refuses with the reason, which is the single place
        // that decision is made.
        wdv_rate_percent:      form.wdv_rate_percent.trim()  === "" ? undefined : Number(form.wdv_rate_percent),
        useful_life_years:     form.useful_life_years.trim() === "" ? undefined : Number(form.useful_life_years),
        notes:                 form.notes || undefined,
      };
      if (body.wdv_rate_percent !== undefined && !Number.isFinite(body.wdv_rate_percent)) {
        setError("The WDV rate must be a percentage, e.g. 12.5."); return;  // the finally below lowers `saving`
      }
      if (body.useful_life_years !== undefined && !Number.isInteger(body.useful_life_years)) {
        setError("The useful life must be a whole number of years."); return;
      }
      const j = await request<ApiEnvelope>("/api/fixed-assets/", { method: "POST", body: JSON.stringify(body) });
      if (!j.success) throw new Error(refusalMessage(j, "Failed to add asset"));
      onSaved(); onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex justify-end" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bg-white w-[440px] h-full overflow-y-auto shadow-2xl flex flex-col">
        <div className="px-6 py-4 border-b border-[#E2E8F0] flex items-center justify-between shrink-0">
          <h2 className="text-sm font-semibold text-[#1E293B]">Add Fixed Asset</h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#1E293B]"><span className="text-lg">×</span></button>
        </div>

        <div className="flex-1 px-6 py-5 space-y-4 text-xs">
          {error && <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-700 flex gap-2 items-center"><AlertCircle size={13} />{error}</div>}

          <Field label="Asset Name *">
            <input className={INPUT} value={form.asset_name} onChange={e => setForm(f => ({ ...f, asset_name: e.target.value }))} placeholder="e.g. Dell Laptop SN12345" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Asset Code">
              <input className={INPUT} value={form.asset_code} onChange={e => setForm(f => ({ ...f, asset_code: e.target.value }))} placeholder="FA-001" />
            </Field>
            <Field label="Location">
              <input className={INPUT} value={form.location} onChange={e => setForm(f => ({ ...f, location: e.target.value }))} placeholder="Head Office" />
            </Field>
          </div>
          {catsFailed && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-amber-800 text-[11px] flex items-center justify-between gap-3">
              {/* No fallback list: a category picked from a stale copy of the
                  Schedule is the defect this change removed. The form waits. */}
              <span>Couldn&apos;t load the Schedule II categories — the request failed or timed out.</span>
              <button onClick={loadCategories} className="shrink-0 px-2 py-1 border border-amber-300 rounded hover:bg-amber-100">Retry</button>
            </div>
          )}
          <Field label="Category">
            <select
              className={INPUT}
              value={form.asset_category}
              disabled={catsLoading || categories.length === 0}
              onChange={e => applyClass(categories, e.target.value, 0)}
            >
              {catsLoading && <option value="">Loading Schedule II categories…</option>}
              {!catsLoading && categories.length === 0 && <option value="">Unavailable</option>}
              {categories.map(c => <option key={c.category}>{c.category}</option>)}
            </select>
          </Field>
          {/* Schedule II gives several classes under one heading — a server is
              six years and a laptop three, a lorry on hire six and a company
              car eight. The CA picks; only the ordinary case is the default. */}
          {selected && selected.classes.length > 1 && (
            <Field label="Schedule II class">
              <select
                className={INPUT}
                value={form.schedule_ii_class}
                onChange={e => applyClass(categories, form.asset_category, Number(e.target.value))}
              >
                {selected.classes.map((c, i) => (
                  <option key={c.label} value={i}>
                    {c.label}{c.useful_life_years ? ` — ${c.useful_life_years} years` : ""}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Purchase Date">
            <input type="date" className={INPUT} value={form.purchase_date} onChange={e => setForm(f => ({ ...f, purchase_date: e.target.value }))} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Purchase Cost (₹) *">
              <input type="number" className={INPUT} value={form.purchase_cost_paise} onChange={e => setForm(f => ({ ...f, purchase_cost_paise: e.target.value }))} placeholder="100000" />
            </Field>
            <Field label="Salvage Value (₹)">
              <input type="number" className={INPUT} value={form.salvage_value_paise} onChange={e => setForm(f => ({ ...f, salvage_value_paise: e.target.value }))} placeholder="0" />
            </Field>
          </div>

          <Field label="Depreciation Method">
            <div className="flex gap-3">
              {(["WDV", "SL"] as const).map(m => (
                <label key={m} className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="dep_method" value={m} checked={form.depreciation_method === m} onChange={() => setForm(f => ({ ...f, depreciation_method: m }))} />
                  <span className="text-[#1E293B] font-medium">{m === "WDV" ? "WDV (Written Down Value)" : "SL (Straight Line)"}</span>
                </label>
              ))}
            </div>
          </Field>

          {form.depreciation_method === "WDV" ? (
            <Field label="WDV Rate (% per year)">
              <input type="number" step="0.01" className={INPUT} value={form.wdv_rate_percent} onChange={e => setForm(f => ({ ...f, wdv_rate_percent: e.target.value }))} />
              <p className="text-[10px] text-[#94A3B8] mt-1">{scheduleIINote(selected, selectedClass, "WDV")}</p>
            </Field>
          ) : (
            <Field label="Useful Life (years)">
              <input type="number" className={INPUT} value={form.useful_life_years} onChange={e => setForm(f => ({ ...f, useful_life_years: e.target.value }))} />
              <p className="text-[10px] text-[#94A3B8] mt-1">{scheduleIINote(selected, selectedClass, "SL")}</p>
            </Field>
          )}

          <Field label="Notes">
            <textarea className={`${INPUT} h-16 resize-none`} value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Optional notes..." />
          </Field>
        </div>

        <div className="px-6 py-4 border-t border-[#E2E8F0] flex gap-3 shrink-0">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-[#E2E8F0] text-xs text-[#64748B] hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Add Asset"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Depreciation Tab ────────────────────────────────────────────────────────

function DepreciationTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<ScheduleRow[]>([]);
  const [loading, setLoading] = useState(true);
  // True when the LAST load failed (error/timeout / success:false) rather than
  // genuinely finding no assets — otherwise the charge tiles read ₹0 as if
  // there were simply nothing to depreciate (M17).
  const [loadFailed, setLoadFailed] = useState(false);
  const [posting, setPosting] = useState<string | null>(null);
  // Per-asset refusals, keyed by asset id. These used to be swallowed by an
  // empty catch, which is how a skipped month showed as nothing happening.
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [period, setPeriod] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // The SCHEDULE endpoint, not the plain asset list: the annual and
      // monthly charge are computed there, on the financial year's OPENING
      // written-down value (task #232). This tab used to recompute them in the
      // browser from the live, already-reduced accumulated depreciation — its
      // own copy of the rule, giving a different answer from the one the Post
      // button was about to write. Disposed assets are excluded server-side.
      const j = await request<ApiEnvelope<ScheduleRow[]>>(`/api/fixed-assets/depreciation-schedule?client_id=${clientId}`);
      if (!j.success) throw new Error(refusalMessage(j, "Failed to load"));
      setRows(j.data ?? []);
      setLoadFailed(false);
    } catch {
      setRows([]); setLoadFailed(true);
    } finally {
      // In a finally rather than after the catch: a throw from inside the catch
      // (or a `return` added inside the try later) would skip a trailing call
      // and leave this tab as a permanent skeleton.
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function postDepreciation(assetId: string) {
    setPosting(assetId);
    // Clear the previous refusal for this row before retrying, so a stale
    // sentence never sits under a request that has since succeeded.
    setErrors(e => Object.fromEntries(Object.entries(e).filter(([id]) => id !== assetId)));
    try {
      const j = await request<ApiEnvelope>(`/api/fixed-assets/${assetId}/depreciate`, {
        method: "POST",
        body: JSON.stringify({ period }),
      });
      if (!j.success) throw new Error(refusalMessage(j, "Failed to post depreciation."));
      await load();
    } catch (e: unknown) {
      // A refusal here NAMES what is wrong — a month skipped, a period locked,
      // an asset with no statutory rate. Showing it is the whole point.
      setErrors(prev => ({ ...prev, [assetId]: e instanceof Error ? e.message : "Failed to post depreciation." }));
    } finally {
      setPosting(null);
    }
  }

  async function reverseLastMonth(assetId: string, month: string) {
    // FA-10. The last month only, and the server enforces that — months come
    // off in the order they went on, because post_depreciation refuses any
    // month at or below the posted-through mark and a hole would be permanent.
    setPosting(assetId);
    setErrors(e => Object.fromEntries(Object.entries(e).filter(([id]) => id !== assetId)));
    try {
      const j = await request<ApiEnvelope>(
        `/api/fixed-assets/${assetId}/depreciation/${month}/reverse`, { method: "POST" });
      if (!j.success) throw new Error(refusalMessage(j, "Failed to reverse depreciation."));
      await load();
    } catch (e: unknown) {
      setErrors(prev => ({ ...prev, [assetId]: e instanceof Error ? e.message : "Failed to reverse depreciation." }));
    } finally {
      setPosting(null);
    }
  }

  async function postAllDepreciation() {
    // Skip assets whose annual charge is already zero, same condition the
    // per-row Post button below uses. One request at a time, deliberately:
    // each is a journal entry, and a refusal on one asset must not be lost in
    // a batch — it lands beside that row.
    for (const r of rows.filter(r => r.annual_depreciation_paise > 0)) {
      await postDepreciation(r.asset_id);
    }
  }

  const totalAnnual = rows.reduce((s, r) => s + r.annual_depreciation_paise, 0);
  // The sum of the server's monthly figures, not the total annual divided by
  // twelve: each asset's monthly charge is floored to whole paise on its own,
  // so floor(Σannual/12) is not what will actually be posted.
  const totalMonthly = rows.reduce((s, r) => s + r.monthly_depreciation_paise, 0);

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      {/* Period + Post All */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] px-5 py-4 flex items-center justify-between">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[#1E293B]">Post Depreciation</p>
          <p className="text-[11px] text-[#94A3B8]">Posts journal entry: Dr Depreciation Expense / Cr Accumulated Depreciation. Idempotent per period.</p>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="month"
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-xs text-[#1E293B] focus:outline-none focus:ring-2 focus:ring-blue-200"
            value={period}
            onChange={e => setPeriod(e.target.value)}
          />
          <button
            onClick={postAllDepreciation}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <TrendingDown size={12} /> Post All for Period
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border border-[#E2E8F0] px-5 py-4">
          <p className="text-[11px] text-[#94A3B8]">Total Annual Depreciation</p>
          <p className="text-lg font-bold text-[#1E293B] font-mono mt-1">{loadFailed ? "—" : fmt(totalAnnual)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#E2E8F0] px-5 py-4">
          <p className="text-[11px] text-[#94A3B8]">Monthly Charge</p>
          <p className="text-lg font-bold text-[#1E293B] font-mono mt-1">{loadFailed ? "—" : fmt(totalMonthly)}</p>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <TableSkeleton cols={6} rows={3} />
      ) : loadFailed ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <p className="text-sm text-red-600 font-medium">Couldn&apos;t load assets — the request failed or timed out.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                <th className="px-4 py-3 text-left font-semibold">Asset</th>
                <th className="px-3 py-3 text-left font-semibold">Method</th>
                <th className="px-3 py-3 text-right font-semibold">Opening WDV</th>
                <th className="px-3 py-3 text-right font-semibold">Annual Depn</th>
                <th className="px-3 py-3 text-right font-semibold">Monthly Depn</th>
                <th className="px-3 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {rows.map((r) => (
                <tr key={r.asset_id} className="hover:bg-[#F8FAFC] align-top">
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">
                    {r.asset_name}
                    {r.depreciation_posted_through && (
                      <span className="block text-[10px] text-[#94A3B8] font-normal">
                        posted through {r.depreciation_posted_through}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-[#64748B]">
                    {r.depreciation_method === "WDV" ? `WDV ${r.wdv_rate_percent ?? "—"}%` : `SL ${r.useful_life_years ?? "—"}yr`}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(r.current_wdv_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(r.annual_depreciation_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#64748B]">{fmt(r.monthly_depreciation_paise)}</td>
                  <td className="px-3 py-2.5">
                    {r.statutory_gap ? (
                      // A zero with a reason beside it is not the same number
                      // as a zero: this asset has no statutory basis for a
                      // charge, so nothing is posted until a CA records one.
                      <span className="text-[10px] text-amber-700">{r.statutory_gap}</span>
                    ) : r.annual_depreciation_paise > 0 ? (
                      <>
                        <button
                          onClick={() => postDepreciation(r.asset_id)}
                          disabled={posting === r.asset_id}
                          className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                        >
                          {posting === r.asset_id ? "Posting…" : `Post ${period}`}
                        </button>
                        {errors[r.asset_id] && (
                          <span className="block text-[10px] text-red-600 mt-1 max-w-xs">{errors[r.asset_id]}</span>
                        )}
                      </>
                    ) : (
                      <span className="text-[10px] text-[#94A3B8]">Fully depreciated</span>
                    )}
                    {r.depreciation_posted_through && (
                      // FA-10: a month posted on a wrong cost or a wrong rate
                      // had no way back. The refusal that names it — "reverse
                      // it a month at a time" — is only actionable because of
                      // this control.
                      <button
                        onClick={() => reverseLastMonth(r.asset_id, r.depreciation_posted_through!)}
                        disabled={posting === r.asset_id}
                        className="block text-[10px] text-red-600 hover:underline disabled:opacity-50 mt-1"
                      >
                        Reverse {r.depreciation_posted_through}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-amber-800">CA Review Required</p>
        <p className="text-[11px] text-amber-700 mt-1">
          Depreciation journals are posted to the ledger after CA review. Rates follow <strong>Companies Act 2013, Schedule II</strong>.
          WDV rates are applied to the Written Down Value; SL rates to the original cost less salvage.
        </p>
      </div>
    </div>
  );
}

// ── Disposal Tab ────────────────────────────────────────────────────────────

function DisposalTab({ clientId }: { clientId: string }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  // True when the LAST load failed rather than genuinely finding no disposable
  // assets — otherwise a failed load reads as "No active assets" (M17).
  const [loadFailed, setLoadFailed] = useState(false);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [proceeds, setProceeds] = useState("");
  // One parse, shared by the gain/loss shown on screen and the payload sent —
  // so the figure the CA reads before confirming is the one that is posted.
  const proceedsPaise = paiseFromRupeeInput(proceeds || "0");
  const [disposalDate, setDisposalDate] = useState(todayLocalISO());
  const [disposing, setDisposing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // include_disposed defaults to false server-side — already-disposed
      // assets are excluded without needing a (nonexistent) status filter.
      const j = await request<ApiEnvelope<Asset[]>>(`/api/fixed-assets/?client_id=${clientId}`);
      if (!j.success) throw new Error(j.error ?? "Failed to load");
      setAssets(j.data ?? []);
      setLoadFailed(false);
    } catch {
      setAssets([]); setLoadFailed(true);
    } finally {
      // In a finally rather than after the catch: a throw from inside the catch
      // (or a `return` added inside the try later) would skip a trailing call
      // and leave this tab as a permanent skeleton.
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function dispose() {
    if (!selected) return;
    if (proceedsPaise === null) {
      setError("Sale proceeds must be an amount in rupees, e.g. 125000 or "
               + "125000.50 — without commas.");
      return;
    }
    setDisposing(true); setError("");
    try {
      // A refusal is a SENTENCE, and FastAPI puts it in `detail` — a 422 body
      // has no `error` key, so `j.error ?? "Failed"` showed the CA the word
      // "Failed" where the server had named the months of depreciation still
      // to post. `request` throws with errorMessage(res), which reads either
      // shape, so the non-2xx case is handled before this line.
      const j = await request<ApiEnvelope>(`/api/fixed-assets/${selected.id}/dispose`, {
        method: "PATCH",
        body: JSON.stringify({
          disposal_date:         disposalDate,
          sale_proceeds_paise:   proceedsPaise as number,
        }),
      });
      if (!j.success) throw new Error(j.error ?? "Failed");
      setSelected(null); setProceeds(""); await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to dispose asset");
    }
    setDisposing(false);
  }

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 flex gap-2">
        <AlertCircle size={14} className="text-red-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-red-800">Asset Disposal — CA Review Required</p>
          <p className="text-[11px] text-red-700 mt-0.5">
            Disposal creates a journal entry: Dr Accumulated Depreciation + Dr/Cr Bank / Cr Fixed Asset ± Profit/Loss on Disposal.
            This action cannot be undone. CA must review before confirming.
          </p>
        </div>
      </div>

      {loading ? (
        <TableSkeleton cols={5} rows={3} />
      ) : loadFailed ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12 space-y-3">
          <p className="text-sm text-red-600 font-medium">Couldn&apos;t load assets — the request failed or timed out.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : assets.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
          <p className="text-sm text-[#64748B]">No active assets available for disposal.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                <th className="px-4 py-3 text-left font-semibold">Asset</th>
                <th className="px-3 py-3 text-right font-semibold">Cost</th>
                <th className="px-3 py-3 text-right font-semibold">Accum Depn</th>
                <th className="px-3 py-3 text-right font-semibold">WDV</th>
                <th className="px-3 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {assets.map((a) => (
                <tr key={a.id} className={`hover:bg-[#F8FAFC] ${selected?.id === a.id ? "bg-red-50" : ""}`}>
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">{a.asset_name}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(a.purchase_cost_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(a.accumulated_depreciation_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#1E293B]">
                    {fmt(a.purchase_cost_paise - a.accumulated_depreciation_paise)}
                  </td>
                  <td className="px-3 py-2.5">
                    <button
                      onClick={() => setSelected(selected?.id === a.id ? null : a)}
                      className="text-xs text-red-600 hover:underline flex items-center gap-1"
                    >
                      <Trash2 size={11} /> Dispose
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="bg-white rounded-xl border border-red-200 px-5 py-5 space-y-4">
          <p className="text-xs font-semibold text-[#1E293B]">Dispose: {selected.asset_name}</p>
          {error && <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-700 text-xs">{error}</div>}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Disposal Date">
              <input type="date" className={INPUT} value={disposalDate} onChange={e => setDisposalDate(e.target.value)} />
            </Field>
            <Field label="Sale Proceeds (₹)">
              <input type="number" className={INPUT} value={proceeds} onChange={e => setProceeds(e.target.value)} placeholder="0" />
            </Field>
          </div>
          <div className="bg-[#F8FAFC] rounded-lg px-4 py-3 text-xs space-y-1">
            <div className="flex justify-between"><span className="text-[#94A3B8]">WDV at disposal:</span><span className="font-mono text-[#1E293B]">{fmt(selected.purchase_cost_paise - selected.accumulated_depreciation_paise)}</span></div>
            <div className="flex justify-between"><span className="text-[#94A3B8]">Sale proceeds:</span><span className="font-mono text-[#1E293B]">{proceedsPaise === null ? "—" : fmt(proceedsPaise)}</span></div>
            <div className="flex justify-between border-t border-[#E2E8F0] pt-1 mt-1">
              <span className="font-medium text-[#1E293B]">P&L on disposal:</span>
              <span className={`font-mono font-semibold ${
                (proceedsPaise ?? 0) >= (selected.purchase_cost_paise - selected.accumulated_depreciation_paise)
                  ? "text-green-700" : "text-red-700"
              }`}>
                {proceedsPaise === null
                  ? "—"
                  : fmt(proceedsPaise - (selected.purchase_cost_paise - selected.accumulated_depreciation_paise))}
              </span>
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={() => { setSelected(null); setProceeds(""); }} className="flex-1 py-2 rounded-lg border border-[#E2E8F0] text-xs text-[#64748B]">Cancel</button>
            <button onClick={dispose} disabled={disposing} className="flex-1 py-2 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 disabled:opacity-50">
              {disposing ? "Processing…" : "Confirm Disposal"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Reports Tab ─────────────────────────────────────────────────────────────

function ReportsTab({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  // True when the LAST load failed rather than genuinely finding no assets —
  // without it every figure here (Gross/Net Block, counts) reads ₹0 / 0 on a
  // failed load, indistinguishable from a client that holds no assets (M17).
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // include_disposed=true — this report needs the disposed/fully-
      // depreciated breakdown too, unlike the other tabs which only work
      // with currently-held assets.
      const j = await request<ApiEnvelope<Omit<Asset, "status">[]>>(`/api/fixed-assets/?client_id=${clientId}&include_disposed=true`);
      if (!j.success) throw new Error(j.error ?? "Failed to load");
      const rows = ((j.data ?? []) as Omit<Asset, "status">[]).map((a) => ({ ...a, status: computeAssetStatus(a) }));
      setAssets(rows);
      setLoadFailed(false);
    } catch {
      setAssets([]); setLoadFailed(true);
    } finally {
      // In a finally rather than after the catch: a throw from inside the catch
      // (or a `return` added inside the try later) would skip a trailing call
      // and leave this tab as a permanent skeleton.
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const active    = assets.filter(a => a.status === "active");
  const disposed  = assets.filter(a => a.status === "disposed");
  const fullyDep  = assets.filter(a => a.status === "fully_depreciated");
  const grossBlock = active.reduce((s, a) => s + a.purchase_cost_paise, 0);
  const accumDep   = active.reduce((s, a) => s + a.accumulated_depreciation_paise, 0);

  const byCategory = active.reduce<Record<string, { cost: number; accum: number }>>((acc, a) => {
    const k = a.asset_category;
    if (!acc[k]) acc[k] = { cost: 0, accum: 0 };
    acc[k].cost  += a.purchase_cost_paise;
    acc[k].accum += a.accumulated_depreciation_paise;
    return acc;
  }, {});

  // Failed load: one banner in place of every zeroed tile/table below, so the
  // report is never mistaken for a client that genuinely holds no assets (M17).
  if (loadFailed) {
    return (
      <div className="space-y-5 max-w-4xl mx-auto">
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <p className="text-sm text-red-600 font-medium">Couldn&apos;t load the fixed-asset report — the request failed or timed out.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      {/* Summary */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Active Assets",   value: active.length,  sub: "", accent: "blue" },
          { label: "Gross Block",     value: fmt(grossBlock), sub: "", accent: "gray" },
          { label: "Accumulated Depn",value: fmt(accumDep),  sub: "", accent: "amber" },
          { label: "Net Block",       value: fmt(grossBlock - accumDep), sub: `FY ${financialYear}`, accent: "green" },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border border-[#E2E8F0] px-4 py-4">
            <p className="text-[11px] text-[#94A3B8]">{c.label}</p>
            <p className="text-base font-bold text-[#1E293B] mt-1 font-mono">{c.value}</p>
            {c.sub && <p className="text-[10px] text-[#94A3B8] mt-0.5">{c.sub}</p>}
          </div>
        ))}
      </div>

      {/* By Category */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50">
          <p className="text-xs font-semibold text-[#334155]">Assets by Category — FY {financialYear}</p>
        </div>
        {loading ? (
          <TableSkeleton cols={5} rows={4} bare />
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="px-5 py-2.5 text-left font-semibold">Category</th>
              <th className="px-3 py-2.5 text-right font-semibold">Count</th>
              <th className="px-3 py-2.5 text-right font-semibold">Gross Block</th>
              <th className="px-3 py-2.5 text-right font-semibold">Accum Depn</th>
              <th className="px-5 py-2.5 text-right font-semibold">Net Block</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {Object.entries(byCategory).map(([cat, vals]) => (
                <tr key={cat} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-2.5 font-medium text-[#1E293B]">{cat}</td>
                  <td className="px-3 py-2.5 text-right text-[#64748B]">{active.filter(a => a.asset_category === cat).length}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(vals.cost)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(vals.accum)}</td>
                  <td className="px-5 py-2.5 text-right font-mono font-semibold text-[#1E293B]">{fmt(vals.cost - vals.accum)}</td>
                </tr>
              ))}
              <tr className="bg-[#F8FAFC] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total</td>
                <td className="px-3 py-2.5 text-right text-[#1E293B]">{active.length}</td>
                <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(grossBlock)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(accumDep)}</td>
                <td className="px-5 py-2.5 text-right font-mono text-[#1E293B]">{fmt(grossBlock - accumDep)}</td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      {/* Disposed + Fully Depreciated summary */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-4">
          <p className="text-xs font-semibold text-[#334155] mb-2">Disposed Assets ({disposed.length})</p>
          {disposed.length === 0 ? <p className="text-xs text-[#94A3B8]">No disposals this year.</p> : (
            <ul className="space-y-1">{disposed.slice(0, 5).map(a => <li key={a.id} className="text-xs text-[#64748B]">{a.asset_name}</li>)}</ul>
          )}
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-4">
          <p className="text-xs font-semibold text-[#334155] mb-2">Fully Depreciated ({fullyDep.length})</p>
          {fullyDep.length === 0 ? <p className="text-xs text-[#94A3B8]">None fully depreciated.</p> : (
            <ul className="space-y-1">{fullyDep.slice(0, 5).map(a => <li key={a.id} className="text-xs text-[#64748B]">{a.asset_name}</li>)}</ul>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const INPUT = "w-full border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-xs text-[#1E293B] focus:outline-none focus:ring-2 focus:ring-blue-200 bg-white";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-[11px] font-medium text-[#64748B]">{label}</label>
      {children}
    </div>
  );
}
