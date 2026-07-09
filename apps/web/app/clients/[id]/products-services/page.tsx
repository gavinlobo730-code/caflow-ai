"use client";

/**
 * Products & Services management (HSN/SAC workflow alignment, migration
 * 182) — create/edit/archive/restore/search a CLIENT's reusable goods and
 * services billing presets. Client-owned: "Client B must never inherit
 * Client A's products." Not an inventory master: the form captures billing
 * defaults only (kind, HSN/SAC, GST, price, unit, category) — no stock, no
 * valuation, no quantity. HSN/SAC is picked from the firm's shared
 * firm_hsn_library (the library stays firm-wide even though this table is
 * client-owned).
 *
 * The create/edit form itself lives in ProductServiceFormModal (shared with
 * the Sales Invoice's inline "+ Create Product/Service" flow — Final
 * Invoice Workflow Alignment: ONE creation workflow, not one per caller).
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, Pencil, Archive, RotateCcw, Search, BookMarked } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import {
  formatServiceRate, formatServicePrice, type ServiceCatalogueItem,
} from "@/lib/catalogue/service";

type Filter = "active" | "archived";

export default function ProductsServicesPage() {
  const { clientId } = useClientNav();
  const [items, setItems] = useState<ServiceCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [editing, setEditing] = useState<ServiceCatalogueItem | "new" | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: "success" | "error" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string, kind: "success" | "error") {
    setToast({ msg, kind });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setError(false);
    try {
      const res = (await api.serviceCatalogue.list(clientId, {
        q: q.trim() || undefined,
        include_archived: filter === "archived",
        limit: 100,
      })) as ApiResp<ServiceCatalogueItem[]>;
      if (!res.success) { setError(true); return; }
      const rows = res.data ?? [];
      // include_archived returns both; the "archived" tab shows only archived.
      setItems(filter === "archived" ? rows.filter((r) => !r.is_active) : rows);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, q, filter]);

  useEffect(() => {
    const t = setTimeout(load, 200); // debounce search
    return () => clearTimeout(t);
  }, [load]);

  async function setActive(item: ServiceCatalogueItem, is_active: boolean) {
    try {
      const res = (await api.serviceCatalogue.update(item.id, { is_active })) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Update failed");
      showToast(`${item.name} ${is_active ? "restored" : "archived"}`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Update failed", "error");
    }
  }

  if (!clientId || clientId === "_placeholder") {
    return <div className="p-6 max-w-4xl mx-auto text-sm text-[#94A3B8]">Loading…</div>;
  }

  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <div className="p-6 max-w-4xl mx-auto space-y-5">
        {toast && (
          <div className={`fixed top-4 right-4 z-[70] px-4 py-2 rounded-lg text-sm shadow-lg ${toast.kind === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
            {toast.msg}
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2"><BookMarked size={18} className="text-emerald-600" /> Products &amp; Services</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Reusable billing presets for this client. No stock or inventory — billing defaults only.</p>
          </div>
          <button
            onClick={() => setEditing("new")}
            className="flex items-center gap-1.5 text-sm bg-emerald-600 text-white px-3.5 py-2 rounded-lg hover:bg-emerald-700 whitespace-nowrap"
          >
            <Plus size={15} /> New Product/Service
          </button>
        </div>

        {/* Search + filter */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by name, SAC/HSN or description…"
              className="w-full pl-8 pr-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div className="flex rounded-lg border border-[#E2E8F0] overflow-hidden text-xs">
            {(["active", "archived"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-2 capitalize ${filter === f ? "bg-emerald-600 text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          {loading ? (
            <div className="p-4 space-y-2">
              {[...Array(4)].map((_, i) => <div key={i} className="h-11 rounded bg-[#F8FAFC] animate-pulse" />)}
            </div>
          ) : error ? (
            <div className="p-8 text-center text-sm">
              <p className="text-[#334155] font-medium">Couldn&apos;t load Products &amp; Services</p>
              <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Retry</button>
            </div>
          ) : items.length === 0 ? (
            <div className="p-10 text-center">
              <BookMarked size={26} className="mx-auto mb-2 text-[#CBD5E1]" />
              <p className="text-sm font-medium text-[#334155]">
                {q ? "No products or services match your search" : filter === "archived" ? "No archived items" : "No products or services yet"}
              </p>
              {!q && filter === "active" && (
                <button onClick={() => setEditing("new")} className="mt-3 text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
                  Create the first one
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-[11px] text-[#94A3B8] border-b border-[#F1F5F9]">
                    <th className="px-4 py-2 text-left font-semibold">Name</th>
                    <th className="px-4 py-2 text-left font-semibold">SAC/HSN</th>
                    <th className="px-4 py-2 text-right font-semibold">GST</th>
                    <th className="px-4 py-2 text-right font-semibold">Selling price</th>
                    <th className="px-4 py-2 text-right font-semibold w-24"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {items.map((s) => (
                    <tr key={s.id} className={s.is_active ? "" : "bg-[#FAFAFA] text-[#94A3B8]"}>
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-[#1E293B]">
                          {s.name}
                          <span className="ml-2 text-[9px] uppercase tracking-wide text-[#94A3B8]">{s.kind ?? "service"}</span>
                          {!s.is_active && <span className="ml-2 text-[10px] uppercase tracking-wide text-[#94A3B8]">archived</span>}
                        </p>
                        {s.description && <p className="text-[11px] text-[#94A3B8] truncate max-w-[280px]">{s.description}</p>}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[#64748B]">{s.hsn_sac || "—"}</td>
                      <td className="px-4 py-2.5 text-right text-[#334155]">{formatServiceRate(s.gst_rate_bps) || "—"}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-[#334155]">{formatServicePrice(s.default_rate_paise) || "—"}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => setEditing(s)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Edit"><Pencil size={14} /></button>
                          {s.is_active ? (
                            <button onClick={() => setActive(s, false)} className="p-1.5 text-[#64748B] hover:text-amber-600 hover:bg-amber-50 rounded" aria-label="Archive"><Archive size={14} /></button>
                          ) : (
                            <button onClick={() => setActive(s, true)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Restore"><RotateCcw size={14} /></button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {editing && (
        <ProductServiceFormModal
          clientId={clientId}
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(item) => { setEditing(null); showToast(`${item.name} ${editing === "new" ? "created" : "updated"}`, "success"); load(); }}
          onError={(msg) => showToast(msg, "error")}
        />
      )}
    </RoleGuard>
  );
}
