"use client";

// Depreciation rates per IT Act 1961 Schedule II and Income Tax Rules 1962 Appendix I
// SL method: Section 32(1)(i), WDV method: Section 32(1)(ii)

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, X, AlertCircle, Trash2 } from "lucide-react";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = {
  id: string;
  client_name: string;
};

type FixedAsset = {
  id: string;
  firm_id: string;
  client_id: string;
  asset_name: string;
  asset_category: string;
  purchase_date: string;
  purchase_cost_paise: number;
  salvage_value_paise: number;
  useful_life_years: number | null;
  depreciation_method: "SL" | "WDV";
  wdv_rate_percent: number | null;
  accumulated_depreciation_paise: number;
  is_disposed: boolean;
  disposal_date: string | null;
  disposal_value_paise: number | null;
  notes: string | null;
};

// ── Helpers ────────────────────────────────────────────────────────────────

/** Format paise as ₹ with Indian number formatting */
function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

/** Parse rupees string to integer paise — always integer arithmetic */
function rsToPaise(rs: string): number {
  if (!rs || rs.trim() === "") return 0;
  // Use integer math: parse as paise by multiplying
  const parts = rs.trim().split(".");
  const rupeesPart = parseInt(parts[0] || "0", 10);
  const paisePart = parts[1] ? parseInt((parts[1] + "00").slice(0, 2), 10) : 0;
  return rupeesPart * 100 + paisePart;
}

// Default WDV rates per IT Act Schedule II
const DEFAULT_WDV_RATES: Record<string, number> = {
  "Building": 10,
  "Plant & Machinery": 15,
  "Furniture & Fixtures": 10,
  "Vehicle": 15,
  "Computer & Peripherals": 40,
  "Intangible Assets": 25,
  "Other": 15,
};

const CATEGORIES = [
  "Building",
  "Plant & Machinery",
  "Furniture & Fixtures",
  "Vehicle",
  "Computer & Peripherals",
  "Intangible Assets",
  "Other",
];

// ── Depreciation calculation helpers ──────────────────────────────────────

/**
 * Calculate annual depreciation in paise.
 * SL method: (Cost - Salvage) / Useful Life  [Section 32(1)(i)]
 * WDV method: Opening WDV × Rate%            [Section 32(1)(ii)]
 * All arithmetic is integer paise — never float.
 */
function calcAnnualDepreciation(asset: FixedAsset): number {
  if (asset.is_disposed) return 0;
  const openingWdvPaise = asset.purchase_cost_paise - asset.accumulated_depreciation_paise;
  if (openingWdvPaise <= 0) return 0;

  if (asset.depreciation_method === "SL") {
    const depreciableBase = asset.purchase_cost_paise - asset.salvage_value_paise;
    if (!asset.useful_life_years || asset.useful_life_years <= 0) return 0;
    // Integer division in paise
    const annualDep = Math.floor(depreciableBase / asset.useful_life_years);
    // Do not exceed remaining WDV minus salvage value
    const maxDep = openingWdvPaise - asset.salvage_value_paise;
    return Math.max(0, Math.min(annualDep, maxDep));
  } else {
    // WDV method
    const rate = asset.wdv_rate_percent ?? 15;
    // Integer paise: floor(WDV * rate / 100)
    const annualDep = Math.floor((openingWdvPaise * rate) / 100);
    return Math.max(0, annualDep);
  }
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function FixedAssetsPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [assets, setAssets] = useState<FixedAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add Asset modal
  const [showAddModal, setShowAddModal] = useState(false);
  const [addForm, setAddForm] = useState({
    asset_name: "",
    asset_category: "Plant & Machinery",
    purchase_date: "",
    purchase_cost_rs: "",
    salvage_value_rs: "",
    depreciation_method: "WDV" as "SL" | "WDV",
    useful_life_years: "",
    wdv_rate_percent: "15",
    notes: "",
  });
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Run Depreciation modal
  const [showDepModal, setShowDepModal] = useState(false);
  const [depYear, setDepYear] = useState(new Date().getFullYear().toString());
  const [depPreview, setDepPreview] = useState<Array<{ asset: FixedAsset; annualDep: number }>>([]);
  const [depConfirmed, setDepConfirmed] = useState(false);
  const [depLoading, setDepLoading] = useState(false);
  const [depError, setDepError] = useState<string | null>(null);

  // Dispose modal
  const [disposeAsset, setDisposeAsset] = useState<FixedAsset | null>(null);
  const [disposeForm, setDisposeForm] = useState({ disposal_date: "", disposal_value_rs: "" });
  const [disposeLoading, setDisposeLoading] = useState(false);
  const [disposeError, setDisposeError] = useState<string | null>(null);

  // ── Load firm + clients ──────────────────────────────────────────────────

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        setFirmId(fid);
        const { data } = await sb.from("clients").select("id, client_name").eq("firm_id", fid).order("client_name");
        setClients((data ?? []) as Client[]);
        if (data && data.length > 0) setSelectedClientId((data[0] as Client).id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // ── Load assets for selected client ─────────────────────────────────────

  const loadAssets = useCallback(async () => {
    if (!firmId || !selectedClientId) return;
    const sb = getSupabaseClient();
    const { data, error: err } = await sb
      .from("fixed_assets")
      .select("*")
      .eq("firm_id", firmId)
      .eq("client_id", selectedClientId)
      .order("purchase_date", { ascending: true });
    if (err) { setError(err.message); return; }
    setAssets((data ?? []) as FixedAsset[]);
  }, [firmId, selectedClientId]);

  useEffect(() => { loadAssets(); }, [loadAssets]);

  // ── Summary stats ────────────────────────────────────────────────────────

  const totalCost = assets.reduce((s, a) => s + a.purchase_cost_paise, 0);
  const totalAccumDep = assets.reduce((s, a) => s + a.accumulated_depreciation_paise, 0);
  const totalWdv = totalCost - totalAccumDep;
  const activeCount = assets.filter((a) => !a.is_disposed).length;

  // ── Add Asset ────────────────────────────────────────────────────────────

  function handleCategoryChange(cat: string) {
    const defaultRate = DEFAULT_WDV_RATES[cat] ?? 15;
    setAddForm((f) => ({ ...f, asset_category: cat, wdv_rate_percent: String(defaultRate) }));
  }

  async function handleAddAsset(e: React.FormEvent) {
    e.preventDefault();
    if (!firmId || !selectedClientId) return;
    setAddLoading(true);
    setAddError(null);
    try {
      const costPaise = rsToPaise(addForm.purchase_cost_rs);
      const salvagePaise = rsToPaise(addForm.salvage_value_rs);
      if (costPaise <= 0) throw new Error("Purchase cost must be greater than zero");

      const sb = getSupabaseClient();
      const { error: err } = await sb.from("fixed_assets").insert({
        firm_id: firmId,
        client_id: selectedClientId,
        asset_name: addForm.asset_name.trim(),
        asset_category: addForm.asset_category,
        purchase_date: addForm.purchase_date,
        purchase_cost_paise: costPaise,
        salvage_value_paise: salvagePaise,
        depreciation_method: addForm.depreciation_method,
        useful_life_years: addForm.depreciation_method === "SL" ? parseInt(addForm.useful_life_years, 10) : null,
        wdv_rate_percent: addForm.depreciation_method === "WDV" ? parseFloat(addForm.wdv_rate_percent) : null,
        accumulated_depreciation_paise: 0,
        is_disposed: false,
        notes: addForm.notes.trim() || null,
      });
      if (err) throw new Error(err.message);
      setShowAddModal(false);
      setAddForm({
        asset_name: "", asset_category: "Plant & Machinery", purchase_date: "",
        purchase_cost_rs: "", salvage_value_rs: "", depreciation_method: "WDV",
        useful_life_years: "", wdv_rate_percent: "15", notes: "",
      });
      await loadAssets();
    } catch (e) {
      setAddError((e as Error).message);
    } finally {
      setAddLoading(false);
    }
  }

  // ── Run Depreciation ─────────────────────────────────────────────────────

  function openDepModal() {
    const preview = assets
      .filter((a) => !a.is_disposed)
      .map((a) => ({ asset: a, annualDep: calcAnnualDepreciation(a) }))
      .filter((p) => p.annualDep > 0);
    setDepPreview(preview);
    setDepConfirmed(false);
    setDepError(null);
    setShowDepModal(true);
  }

  async function handleRunDepreciation() {
    if (!depPreview.length) return;
    setDepLoading(true);
    setDepError(null);
    try {
      const sb = getSupabaseClient();
      for (const { asset, annualDep } of depPreview) {
        const newAccum = asset.accumulated_depreciation_paise + annualDep;
        const { error: err } = await sb
          .from("fixed_assets")
          .update({ accumulated_depreciation_paise: newAccum })
          .eq("id", asset.id);
        if (err) throw new Error(err.message);
      }
      setShowDepModal(false);
      await loadAssets();
    } catch (e) {
      setDepError((e as Error).message);
    } finally {
      setDepLoading(false);
    }
  }

  // ── Dispose Asset ────────────────────────────────────────────────────────

  async function handleDispose(e: React.FormEvent) {
    e.preventDefault();
    if (!disposeAsset) return;
    setDisposeLoading(true);
    setDisposeError(null);
    try {
      const disposalValuePaise = rsToPaise(disposeForm.disposal_value_rs);
      const sb = getSupabaseClient();
      const { error: err } = await sb
        .from("fixed_assets")
        .update({
          is_disposed: true,
          disposal_date: disposeForm.disposal_date,
          disposal_value_paise: disposalValuePaise,
        })
        .eq("id", disposeAsset.id);
      if (err) throw new Error(err.message);
      setDisposeAsset(null);
      setDisposeForm({ disposal_date: "", disposal_value_rs: "" });
      await loadAssets();
    } catch (e) {
      setDisposeError((e as Error).message);
    } finally {
      setDisposeLoading(false);
    }
  }

  // ── Disposal gain/loss ───────────────────────────────────────────────────

  function calcGainLoss(asset: FixedAsset): number | null {
    if (!asset.is_disposed || asset.disposal_value_paise == null) return null;
    const wdvAtDisposal = asset.purchase_cost_paise - asset.accumulated_depreciation_paise;
    return asset.disposal_value_paise - wdvAtDisposal;
  }

  // ── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <TableSkeleton rows={6} cols={6} />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
            <ArrowLeft size={18} />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-[#0F172A]">Fixed Assets</h1>
            <p className="text-xs text-[#64748B] mt-0.5">
              Depreciation per IT Act 1961 Schedule II — Section 32(1)(i)/(ii)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="text-sm border rounded-md px-3 py-1.5 bg-white"
            value={selectedClientId}
            onChange={(e) => setSelectedClientId(e.target.value)}
          >
            {clients.length === 0 && <option value="">No clients</option>}
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.client_name}</option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={openDepModal} disabled={!selectedClientId}>
            Run Depreciation
          </Button>
          <Button size="sm" onClick={() => setShowAddModal(true)} disabled={!selectedClientId}>
            <Plus size={14} className="mr-1" /> Add Asset
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded-md p-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total Assets", value: String(activeCount) },
          { label: "Total Cost", value: fmtRs(totalCost) },
          { label: "Accumulated Depreciation", value: fmtRs(totalAccumDep) },
          { label: "Total WDV", value: fmtRs(totalWdv) },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className="text-lg font-bold text-[#0F172A]">{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Asset Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Fixed Asset Register</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F8FAFC] border-y border-[#F1F5F9]">
              <tr>
                {["Asset Name", "Category", "Purchase Date", "Cost", "Method", "Rate / Life", "Accum. Dep.", "WDV", "Status", "Actions"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-[#64748B] font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {assets.map((asset) => {
                const wdv = asset.purchase_cost_paise - asset.accumulated_depreciation_paise;
                const gainLoss = calcGainLoss(asset);
                return (
                  <tr key={asset.id} className={asset.is_disposed ? "bg-[#F8FAFC] opacity-60" : "hover:bg-[#F8FAFC]"}>
                    <td className="px-3 py-2.5 font-medium text-[#0F172A]">{asset.asset_name}</td>
                    <td className="px-3 py-2.5 text-[#475569]">{asset.asset_category}</td>
                    <td className="px-3 py-2.5 text-[#475569] whitespace-nowrap">{asset.purchase_date}</td>
                    <td className="px-3 py-2.5 text-[#0F172A] whitespace-nowrap">{fmtRs(asset.purchase_cost_paise)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${asset.depreciation_method === "WDV" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>
                        {asset.depreciation_method}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-[#475569] whitespace-nowrap">
                      {asset.depreciation_method === "WDV"
                        ? `${asset.wdv_rate_percent}%`
                        : `${asset.useful_life_years} yrs`}
                    </td>
                    <td className="px-3 py-2.5 text-[#0F172A] whitespace-nowrap">{fmtRs(asset.accumulated_depreciation_paise)}</td>
                    <td className="px-3 py-2.5 font-semibold text-[#0F172A] whitespace-nowrap">{fmtRs(wdv)}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {asset.is_disposed ? (
                        <div>
                          <span className="px-1.5 py-0.5 rounded text-xs bg-gray-100 text-[#475569]">Disposed</span>
                          {gainLoss !== null && (
                            <span className={`ml-1 px-1.5 py-0.5 rounded text-xs ${gainLoss >= 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                              {gainLoss >= 0 ? "Gain" : "Loss"} {fmtRs(Math.abs(gainLoss))}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700">Active</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {!asset.is_disposed && (
                        <button
                          className="text-xs text-red-500 hover:text-red-700 flex items-center gap-1"
                          onClick={() => {
                            setDisposeAsset(asset);
                            setDisposeError(null);
                            setDisposeForm({ disposal_date: "", disposal_value_rs: "" });
                          }}
                        >
                          <Trash2 size={12} /> Dispose
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {assets.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-[#94A3B8]">
                    No assets found. Add your first fixed asset.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Add Asset Modal ── */}
      {showAddModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="text-base font-semibold">Add Fixed Asset</h2>
              <button onClick={() => setShowAddModal(false)} className="text-[#94A3B8] hover:text-[#475569]"><X size={18} /></button>
            </div>
            <form onSubmit={handleAddAsset} className="px-5 py-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Asset Name *</label>
                <input
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={addForm.asset_name}
                  onChange={(e) => setAddForm((f) => ({ ...f, asset_name: e.target.value }))}
                  required
                  placeholder="e.g. Dell Laptop"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Category *</label>
                <select
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={addForm.asset_category}
                  onChange={(e) => handleCategoryChange(e.target.value)}
                >
                  {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Purchase Date *</label>
                <input
                  type="date"
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={addForm.purchase_date}
                  onChange={(e) => setAddForm((f) => ({ ...f, purchase_date: e.target.value }))}
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Purchase Cost (₹) *</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="w-full border rounded-md px-3 py-2 text-sm"
                    value={addForm.purchase_cost_rs}
                    onChange={(e) => setAddForm((f) => ({ ...f, purchase_cost_rs: e.target.value }))}
                    required
                    placeholder="0.00"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Salvage Value (₹)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="w-full border rounded-md px-3 py-2 text-sm"
                    value={addForm.salvage_value_rs}
                    onChange={(e) => setAddForm((f) => ({ ...f, salvage_value_rs: e.target.value }))}
                    placeholder="0.00"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Depreciation Method *</label>
                <select
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={addForm.depreciation_method}
                  onChange={(e) => setAddForm((f) => ({ ...f, depreciation_method: e.target.value as "SL" | "WDV" }))}
                >
                  <option value="WDV">WDV — Written Down Value [Section 32(1)(ii)]</option>
                  <option value="SL">SL — Straight Line [Section 32(1)(i)]</option>
                </select>
              </div>

              {addForm.depreciation_method === "SL" && (
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Useful Life (years) *</label>
                  <input
                    type="number"
                    min="1"
                    className="w-full border rounded-md px-3 py-2 text-sm"
                    value={addForm.useful_life_years}
                    onChange={(e) => setAddForm((f) => ({ ...f, useful_life_years: e.target.value }))}
                    required
                    placeholder="e.g. 10"
                  />
                </div>
              )}

              {addForm.depreciation_method === "WDV" && (
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">
                    WDV Rate % *
                    <span className="ml-1 text-[#94A3B8] font-normal">(IT Act default: {DEFAULT_WDV_RATES[addForm.asset_category]}%)</span>
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    step="0.01"
                    className="w-full border rounded-md px-3 py-2 text-sm"
                    value={addForm.wdv_rate_percent}
                    onChange={(e) => setAddForm((f) => ({ ...f, wdv_rate_percent: e.target.value }))}
                    required
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Notes</label>
                <textarea
                  className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                  rows={2}
                  value={addForm.notes}
                  onChange={(e) => setAddForm((f) => ({ ...f, notes: e.target.value }))}
                  placeholder="Optional notes"
                />
              </div>

              {addError && (
                <div className="flex items-center gap-2 text-red-600 text-xs bg-red-50 border border-red-200 rounded p-2">
                  <AlertCircle size={12} /> {addError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setShowAddModal(false)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={addLoading}>
                  {addLoading ? "Saving…" : "Add Asset"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Run Depreciation Modal ── */}
      {showDepModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="text-base font-semibold">Run Depreciation</h2>
              <button onClick={() => setShowDepModal(false)} className="text-[#94A3B8] hover:text-[#475569]"><X size={18} /></button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <div className="flex items-center gap-3">
                <label className="text-xs font-medium text-[#334155]">Financial Year Ending</label>
                <input
                  type="number"
                  min="2000"
                  max="2100"
                  className="border rounded-md px-3 py-1.5 text-sm w-28"
                  value={depYear}
                  onChange={(e) => setDepYear(e.target.value)}
                />
                <span className="text-xs text-[#64748B]">(FY {parseInt(depYear) - 1}-{depYear.slice(2)})</span>
              </div>

              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-3">
                <strong>Preview</strong> — review before confirming. Each asset will be updated once.
                All calculations use integer paise arithmetic per IT Act 1961 Schedule II.
              </div>

              <table className="w-full text-xs">
                <thead className="bg-[#F8FAFC] border-y border-[#F1F5F9]">
                  <tr>
                    {["Asset", "Method", "Opening WDV", "Depreciation", "Closing WDV"].map((h) => (
                      <th key={h} className="px-3 py-2 text-left text-[#64748B] font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {depPreview.map(({ asset, annualDep }) => {
                    const openWdv = asset.purchase_cost_paise - asset.accumulated_depreciation_paise;
                    const closeWdv = openWdv - annualDep;
                    return (
                      <tr key={asset.id}>
                        <td className="px-3 py-2 font-medium">{asset.asset_name}</td>
                        <td className="px-3 py-2 text-[#64748B]">{asset.depreciation_method}</td>
                        <td className="px-3 py-2">{fmtRs(openWdv)}</td>
                        <td className="px-3 py-2 text-red-600">{fmtRs(annualDep)}</td>
                        <td className="px-3 py-2 font-semibold">{fmtRs(closeWdv)}</td>
                      </tr>
                    );
                  })}
                  {depPreview.length === 0 && (
                    <tr><td colSpan={5} className="px-3 py-6 text-center text-[#94A3B8]">No active assets to depreciate</td></tr>
                  )}
                </tbody>
              </table>

              <div className="flex items-center gap-2 text-xs text-[#475569] border-t pt-3">
                <input
                  type="checkbox"
                  id="dep-confirm"
                  checked={depConfirmed}
                  onChange={(e) => setDepConfirmed(e.target.checked)}
                />
                <label htmlFor="dep-confirm">
                  I have reviewed the depreciation preview and confirm running it for FY {parseInt(depYear) - 1}-{depYear.slice(2)}
                </label>
              </div>

              {depError && (
                <div className="flex items-center gap-2 text-red-600 text-xs bg-red-50 border border-red-200 rounded p-2">
                  <AlertCircle size={12} /> {depError}
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => setShowDepModal(false)}>Cancel</Button>
                <Button
                  size="sm"
                  disabled={!depConfirmed || depLoading || depPreview.length === 0}
                  onClick={handleRunDepreciation}
                >
                  {depLoading ? "Running…" : "Confirm & Run Depreciation"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Dispose Asset Modal ── */}
      {disposeAsset && (
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="text-base font-semibold">Dispose Asset</h2>
              <button onClick={() => setDisposeAsset(null)} className="text-[#94A3B8] hover:text-[#475569]"><X size={18} /></button>
            </div>
            <form onSubmit={handleDispose} className="px-5 py-4 space-y-4">
              <div className="bg-[#F8FAFC] rounded-md p-3 text-xs space-y-1">
                <p className="font-semibold text-[#0F172A]">{disposeAsset.asset_name}</p>
                <p className="text-[#64748B]">WDV at disposal: {fmtRs(disposeAsset.purchase_cost_paise - disposeAsset.accumulated_depreciation_paise)}</p>
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Disposal Date *</label>
                <input
                  type="date"
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={disposeForm.disposal_date}
                  onChange={(e) => setDisposeForm((f) => ({ ...f, disposal_date: e.target.value }))}
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Disposal Value (₹) *</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  className="w-full border rounded-md px-3 py-2 text-sm"
                  value={disposeForm.disposal_value_rs}
                  onChange={(e) => setDisposeForm((f) => ({ ...f, disposal_value_rs: e.target.value }))}
                  required
                  placeholder="0.00"
                />
              </div>

              {disposeForm.disposal_value_rs && (
                <div className="text-xs rounded-md p-3 bg-blue-50 text-blue-800">
                  {(() => {
                    const disposalPaise = rsToPaise(disposeForm.disposal_value_rs);
                    const wdv = disposeAsset.purchase_cost_paise - disposeAsset.accumulated_depreciation_paise;
                    const gl = disposalPaise - wdv;
                    return gl >= 0
                      ? `Capital Gain: ${fmtRs(gl)}`
                      : `Capital Loss: ${fmtRs(Math.abs(gl))}`;
                  })()}
                </div>
              )}

              {disposeError && (
                <div className="flex items-center gap-2 text-red-600 text-xs bg-red-50 border border-red-200 rounded p-2">
                  <AlertCircle size={12} /> {disposeError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setDisposeAsset(null)}>Cancel</Button>
                <Button type="submit" size="sm" variant="destructive" disabled={disposeLoading}>
                  {disposeLoading ? "Disposing…" : "Mark as Disposed"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
