"use client";

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useEffect, useState, useCallback } from "react";
import { Plus, RefreshCw, ChevronDown, ChevronRight, Trash2, TrendingDown, AlertCircle } from "lucide-react";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import FinancialYearPicker from "@/components/FinancialYearPicker";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

const CATEGORIES = [
  "Computer & IT Equipment",
  "Furniture & Fixtures",
  "Office Equipment",
  "Plant & Machinery",
  "Vehicles",
  "Building",
  "Land",
  "Intangibles",
  "Other",
];

const WDV_RATES: Record<string, number> = {
  "Computer & IT Equipment": 31.67,
  "Furniture & Fixtures":    10.0,
  "Office Equipment":        13.91,
  "Plant & Machinery":       15.33,
  "Vehicles":                25.89,
  "Building":                 5.0,
  "Land":                     0.0,
  "Intangibles":             25.0,
  "Other":                   15.33,
};

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
        <TableSkeleton cols={10} rows={4} />
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
                  </tr>
                  {expanded === a.id && (
                    <tr key={`${a.id}-exp`} className="bg-[#F8FAFC]">
                      <td colSpan={10} className="px-8 py-3">
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
    </div>
  );
}

// ── Add Asset Drawer ────────────────────────────────────────────────────────

function AddAssetDrawer({ clientId, onClose, onSaved }: { clientId: string; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    asset_name:            "",
    asset_category:        "Computer & IT Equipment",
    asset_code:            "",
    location:              "",
    purchase_date:         new Date().toISOString().slice(0, 10),
    purchase_cost_paise:   "",
    salvage_value_paise:   "0",
    depreciation_method:   "WDV" as "WDV" | "SL",
    wdv_rate_percent:      "31.67",
    useful_life_years:     "5",
    notes:                 "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function handleCategoryChange(cat: string) {
    setForm(f => ({ ...f, asset_category: cat, wdv_rate_percent: String(WDV_RATES[cat] ?? 15.33) }));
  }

  async function save() {
    if (!form.asset_name || !form.purchase_cost_paise) { setError("Asset name and cost are required."); return; }
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
        wdv_rate_percent:      form.depreciation_method === "WDV" ? parseFloat(form.wdv_rate_percent) : undefined,
        useful_life_years:     form.depreciation_method === "SL"  ? parseInt(form.useful_life_years) : undefined,
        notes:                 form.notes || undefined,
      };
      const res = await fetch(`${API}/api/fixed-assets/`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await res.json();
      if (!j.success) throw new Error(j.error ?? "Failed to add asset");
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
          <Field label="Category">
            <select className={INPUT} value={form.asset_category} onChange={e => handleCategoryChange(e.target.value)}>
              {CATEGORIES.map(c => <option key={c}>{c}</option>)}
            </select>
          </Field>
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
              <p className="text-[10px] text-[#94A3B8] mt-1">Companies Act 2013 Sch II rate pre-filled for selected category.</p>
            </Field>
          ) : (
            <Field label="Useful Life (years)">
              <input type="number" className={INPUT} value={form.useful_life_years} onChange={e => setForm(f => ({ ...f, useful_life_years: e.target.value }))} />
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
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  // True when the LAST load failed (error/timeout / success:false) rather than
  // genuinely finding no assets — otherwise the charge tiles read ₹0 as if
  // there were simply nothing to depreciate (M17).
  const [loadFailed, setLoadFailed] = useState(false);
  const [posting, setPosting] = useState<string | null>(null);
  const [period, setPeriod] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // include_disposed defaults to false server-side — no "status" query
      // param exists on this endpoint (it was silently ignored, not filtering
      // anything); disposed assets are already excluded by the default.
      const res = await fetch(`${API}/api/fixed-assets/?client_id=${clientId}`, { credentials: "include" });
      const j = await res.json();
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

  async function postDepreciation(assetId: string) {
    setPosting(assetId);
    try {
      const res = await fetch(`${API}/api/fixed-assets/${assetId}/depreciate`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period }),
      });
      const j = await res.json();
      if (!j.success) throw new Error(j.error ?? "Failed");
      await load();
    } catch { /* ignore */ }
    setPosting(null);
  }

  async function postAllDepreciation() {
    // No "active" status field to filter on (see computeAssetStatus) — skip
    // assets whose annual depreciation already rounds to zero, same
    // condition the per-row Post button below uses.
    for (const a of assets.filter(a => annualDepn(a) > 0)) {
      await postDepreciation(a.id);
    }
  }

  // Compute annual depreciation client-side for display
  function annualDepn(a: Asset): number {
    const wdv = a.purchase_cost_paise - a.accumulated_depreciation_paise;
    if (wdv <= a.salvage_value_paise) return 0;
    if (a.depreciation_method === "WDV") {
      return Math.floor(wdv * (a.wdv_rate_percent ?? 0) / 100);
    } else {
      const life = a.useful_life_years ?? 5;
      const annual = Math.floor((a.purchase_cost_paise - a.salvage_value_paise) / life);
      const remaining = wdv - a.salvage_value_paise;
      return Math.min(annual, remaining);
    }
  }

  const totalAnnual = assets.reduce((s, a) => s + annualDepn(a), 0);

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
          <p className="text-lg font-bold text-[#1E293B] font-mono mt-1">{loadFailed ? "—" : fmt(Math.floor(totalAnnual / 12))}</p>
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
              {assets.map((a) => {
                const annual  = annualDepn(a);
                const monthly = Math.floor(annual / 12);
                const wdv     = a.purchase_cost_paise - a.accumulated_depreciation_paise;
                return (
                  <tr key={a.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 font-medium text-[#1E293B]">{a.asset_name}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">
                      {a.depreciation_method === "WDV" ? `WDV ${a.wdv_rate_percent}%` : `SL ${a.useful_life_years}yr`}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#1E293B]">{fmt(wdv)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-amber-700">{fmt(annual)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#64748B]">{fmt(monthly)}</td>
                    <td className="px-3 py-2.5">
                      {annual > 0 ? (
                        <button
                          onClick={() => postDepreciation(a.id)}
                          disabled={posting === a.id}
                          className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                        >
                          {posting === a.id ? "Posting…" : `Post ${period}`}
                        </button>
                      ) : (
                        <span className="text-[10px] text-[#94A3B8]">Fully depreciated</span>
                      )}
                    </td>
                  </tr>
                );
              })}
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
  const [disposalDate, setDisposalDate] = useState(new Date().toISOString().slice(0, 10));
  const [disposing, setDisposing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    try {
      // include_disposed defaults to false server-side — already-disposed
      // assets are excluded without needing a (nonexistent) status filter.
      const res = await fetch(`${API}/api/fixed-assets/?client_id=${clientId}`, { credentials: "include" });
      const j = await res.json();
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
      const res = await fetch(`${API}/api/fixed-assets/${selected.id}/dispose`, {
        method: "PATCH", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disposal_date:         disposalDate,
          sale_proceeds_paise:   proceedsPaise as number,
        }),
      });
      const j = await res.json();
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
      const res = await fetch(`${API}/api/fixed-assets/?client_id=${clientId}&include_disposed=true`, { credentials: "include" });
      const j = await res.json();
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
