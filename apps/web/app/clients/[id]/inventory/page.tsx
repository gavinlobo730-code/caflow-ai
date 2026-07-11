"use client";

/**
 * Inventory — stock register for kind='good' Product/Service catalogue items
 * (migration 188; costing engine in apps/api/domain/inventory_service.py).
 * Read-only: every stock movement is written as a side effect of issuing a
 * sales invoice, receiving a purchase bill, or seeding an opening balance on
 * the product form — there is no "add stock" action here.
 *
 * Clicking a row opens that item's movement ledger, mirroring the Accounting
 * tab's ledger drill-down: its own date range, defaulting to the client's FY.
 */
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { DataTable } from "@/components/ui/data-table";
import type { Column } from "@/lib/table/types";
import { formatServicePrice } from "@/lib/catalogue/service";

interface StockItem {
  id: string;
  name: string;
  description: string | null;
  hsn_sac: string | null;
  unit: string | null;
  is_active: boolean;
  stock_qty_units: number | null;
  avg_cost_paise: number | null;
  stock_value_paise: number | null;
}

interface StockLedgerLine {
  id: string;
  movement_date: string;
  movement_type: string;
  quantity_delta: string;
  unit_cost_paise: number;
  value_delta_paise: number;
  running_qty_units: string;
  running_avg_cost_paise: number;
  running_value_paise: number;
  reference_no: string | null;
  source_type: string | null;
}

function fyDateRange(fy: string): { start: string; end: string } {
  const [startYear] = fy.split("-");
  const y = parseInt(startYear, 10);
  return { start: `${y}-04-01`, end: `${y + 1}-03-31` };
}

const MOVEMENT_LABELS: Record<string, string> = {
  opening: "Opening Balance",
  purchase: "Purchase",
  sale: "Sale",
  sale_reversal: "Sale Reversal",
  purchase_reversal: "Purchase Reversal",
  adjustment: "Adjustment",
};

function fmtQty(v: number | string | null | undefined): string {
  if (v == null) return "0";
  const n = typeof v === "string" ? parseFloat(v) : v;
  return Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, "");
}

export default function InventoryPage() {
  const { clientId, financialYear } = useClientNav();
  const [items, setItems] = useState<StockItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [drillDown, setDrillDown] = useState<StockItem | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.inventory.items({ client_id: clientId })) as { success: boolean; data: StockItem[] | null };
      setItems(res.success && res.data ? res.data : []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (!clientId || clientId === "_placeholder") {
    return (
      <div className="px-6 py-4">
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}
        </div>
      </div>
    );
  }

  const columns: Column<StockItem>[] = [
    { key: "name", header: "Product", accessor: (i) => i.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (i) => <span className="font-medium text-[#1E293B]">{i.name}</span> },
    { key: "hsn_sac", header: "HSN", accessor: (i) => i.hsn_sac ?? "", searchable: true,
      render: (i) => <span className="font-mono text-[#64748B]">{i.hsn_sac ?? "—"}</span> },
    { key: "unit", header: "Unit", accessor: (i) => i.unit ?? "",
      render: (i) => <span className="text-[#64748B]">{i.unit ?? "—"}</span> },
    { key: "stock_qty_units", header: "On Hand", accessor: (i) => i.stock_qty_units ?? 0, sortable: true, align: "right",
      render: (i) => {
        const qty = i.stock_qty_units ?? 0;
        return <span className={`font-mono font-semibold ${qty < 0 ? "text-red-600" : "text-[#334155]"}`}>{fmtQty(qty)}</span>;
      } },
    { key: "avg_cost_paise", header: "Avg Cost", accessor: (i) => i.avg_cost_paise ?? 0, sortable: true, align: "right",
      exportValue: (i) => (i.avg_cost_paise ?? 0) / 100,
      render: (i) => <span className="font-mono text-[#64748B]">{formatServicePrice(i.avg_cost_paise) || "—"}</span> },
    { key: "stock_value_paise", header: "Stock Value", accessor: (i) => i.stock_value_paise ?? 0, sortable: true, align: "right",
      exportValue: (i) => (i.stock_value_paise ?? 0) / 100,
      render: (i) => <span className="font-mono font-semibold text-[#0F172A]">{formatServicePrice(i.stock_value_paise) || "₹0"}</span> },
    { key: "is_active", header: "Status", accessor: (i) => (i.is_active ? "active" : "archived"),
      render: (i) => (
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${i.is_active ? "bg-green-50 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
          {i.is_active ? "Active" : "Archived"}
        </span>
      ) },
  ];

  const totalValue = items.reduce((s, i) => s + (i.stock_value_paise ?? 0), 0);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-5 pb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-[#0F172A]">Inventory</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            {items.length} stock-tracked product{items.length !== 1 ? "s" : ""} · Total value {formatServicePrice(totalValue) || "₹0"}
          </p>
        </div>
        <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 min-h-0">
        <DataTable
          data={items}
          columns={columns}
          getRowId={(i) => i.id}
          loading={loading}
          onRefresh={load}
          searchPlaceholder="Search by product name or HSN…"
          initialSort={{ key: "name", dir: "asc" }}
          exportFilename="inventory-stock-register"
          persistKey="inventory.items"
          emptyTitle="No stock-tracked products yet"
          emptyDescription="Mark a Product/Service as a Product (not Service) and give it an opening quantity to start tracking stock."
          onRowClick={(item) => setDrillDown(item)}
        />
      </div>

      {drillDown && (
        <StockLedgerDrillDown clientId={clientId} financialYear={financialYear} item={drillDown} onClose={() => setDrillDown(null)} />
      )}
    </div>
  );
}

function StockLedgerDrillDown({
  clientId, financialYear, item, onClose,
}: {
  clientId: string;
  financialYear: string;
  item: StockItem;
  onClose: () => void;
}) {
  const fyRange = fyDateRange(financialYear);
  const [startDate, setStartDate] = useState(fyRange.start);
  const [endDate, setEndDate] = useState(fyRange.end);
  const [lines, setLines] = useState<StockLedgerLine[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = (await api.inventory.ledger(item.id, { client_id: clientId, start_date: startDate, end_date: endDate })) as {
        success: boolean; data: { item: unknown; lines: StockLedgerLine[] } | null;
      };
      setLines(res.success && res.data ? res.data.lines : []);
    } catch {
      setLines([]);
    } finally {
      setLoading(false);
    }
  }, [clientId, item.id, startDate, endDate]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-[100] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between shrink-0">
          <div>
            <p className="text-sm font-semibold text-[#0F172A]">{item.name}</p>
            <p className="text-[11px] text-[#94A3B8] mt-0.5">Stock movement ledger</p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-xl leading-none" aria-label="Back">×</button>
        </div>

        <div className="px-5 py-3 border-b border-[#F1F5F9] flex items-end gap-3 flex-wrap shrink-0">
          <div>
            <label className="block text-[10px] font-medium text-[#94A3B8] mb-1">From</label>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              className="px-2.5 py-[7px] text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-[10px] font-medium text-[#94A3B8] mb-1">To</label>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
              className="px-2.5 py-[7px] text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={() => { setStartDate(fyRange.start); setEndDate(fyRange.end); }} className="text-xs text-blue-600 hover:underline pb-1.5">
            Reset to FY {financialYear}
          </button>
          {loading && <RefreshCw size={13} className="animate-spin text-[#94A3B8] mb-1.5" />}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {!loading && lines.length === 0 ? (
            <div className="text-center py-10 text-[#94A3B8] text-sm">No stock movements for this item in the selected range.</div>
          ) : loading ? (
            <div className="h-40 rounded-lg bg-[#F8FAFC] animate-pulse" />
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-3 py-2 text-left font-semibold">Date</th>
                  <th className="px-3 py-2 text-left font-semibold">Type</th>
                  <th className="px-3 py-2 text-left font-semibold">Reference</th>
                  <th className="px-3 py-2 text-right font-semibold">Qty Δ</th>
                  <th className="px-3 py-2 text-right font-semibold">Unit Cost</th>
                  <th className="px-3 py-2 text-right font-semibold">Balance Qty</th>
                  <th className="px-3 py-2 text-right font-semibold">Balance Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((l) => {
                  const delta = parseFloat(l.quantity_delta);
                  return (
                    <tr key={l.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-3 py-2 text-[#64748B] whitespace-nowrap">{l.movement_date}</td>
                      <td className="px-3 py-2 text-[#334155]">{MOVEMENT_LABELS[l.movement_type] ?? l.movement_type}</td>
                      <td className="px-3 py-2 font-mono text-[#94A3B8]">{l.reference_no ?? "—"}</td>
                      <td className={`px-3 py-2 text-right font-mono ${delta >= 0 ? "text-green-700" : "text-red-700"}`}>
                        {delta >= 0 ? "+" : ""}{fmtQty(delta)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[#64748B]">{formatServicePrice(l.unit_cost_paise) || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-[#334155]">{fmtQty(l.running_qty_units)}</td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-[#0F172A]">{formatServicePrice(l.running_value_paise) || "₹0"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
