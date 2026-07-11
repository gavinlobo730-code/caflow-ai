"use client";

/**
 * Inventory — stock register for kind='good' Product/Service catalogue items
 * (migration 188; costing engine in apps/api/domain/inventory_service.py).
 * Most stock movements are written as a side effect of issuing a sales
 * invoice, receiving a purchase bill, issuing a credit/debit note, or
 * seeding an opening balance on the product form. The one exception is the
 * ledger drill-down's "Adjust Stock" action — a manual physical-count
 * correction, damage, theft, destruction or free-sample giveaway, with an
 * optional ITC reversal (CGST Act §17(5)(h)).
 *
 * Clicking a row opens that item's movement ledger, mirroring the Accounting
 * tab's ledger drill-down: its own date range, defaulting to the client's FY.
 */
import { useCallback, useEffect, useState } from "react";
import { RefreshCw, AlertTriangle, ClipboardEdit, Loader2, TrendingDown } from "lucide-react";
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
  sale_return: "Sales Return (Credit Note)",
  purchase_return: "Purchase Return (Debit Note)",
  adjustment: "Adjustment",
  nrv_writedown: "NRV Write-down",
};

// Reason taxonomy for a manual stock adjustment (models/inventory.py:
// ADJUSTMENT_REASONS). CGST Act §17(5)(h): ITC must be reversed for goods
// lost, stolen, destroyed, written off, or given away as free samples — the
// suggested default below is a starting point, never auto-applied; the CA
// always confirms (or overrides) the checkbox before this posts.
const ADJUSTMENT_REASONS: { value: string; label: string; direction: "increase" | "decrease" | "both"; suggestReverseItc: boolean }[] = [
  { value: "physical_count_shortage", label: "Physical count — shortage found", direction: "decrease", suggestReverseItc: true },
  { value: "physical_count_surplus", label: "Physical count — surplus found", direction: "increase", suggestReverseItc: false },
  { value: "damage", label: "Damaged (written off)", direction: "decrease", suggestReverseItc: true },
  { value: "theft_loss", label: "Theft / loss", direction: "decrease", suggestReverseItc: true },
  { value: "destroyed", label: "Destroyed (fire, expiry, etc.)", direction: "decrease", suggestReverseItc: true },
  { value: "free_sample", label: "Given away as a free sample", direction: "decrease", suggestReverseItc: true },
  { value: "other", label: "Other", direction: "both", suggestReverseItc: false },
];

/** True once an item has gone negative on hand with no cost ever recorded
 * against it (no opening balance, no purchase) — record_stock_out still
 * tracks the movement (domain/inventory_service.py) rather than skip it
 * silently, but the Rs 0 cost is a real "unknown," not a computed zero. */
function isUntrackedOversold(i: { stock_qty_units: number | null; avg_cost_paise: number | null }): boolean {
  return (i.stock_qty_units ?? 0) < 0 && !(i.avg_cost_paise ?? 0);
}

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
        return (
          <span className={`inline-flex items-center gap-1 font-mono font-semibold ${qty < 0 ? "text-red-600" : "text-[#334155]"}`}>
            {isUntrackedOversold(i) && (
              <AlertTriangle size={12} className="text-amber-500 shrink-0"
                aria-label="Cost not established — sold before a purchase or opening balance was recorded" />
            )}
            {fmtQty(qty)}
          </span>
        );
      } },
    { key: "avg_cost_paise", header: "Avg Cost", accessor: (i) => i.avg_cost_paise ?? 0, sortable: true, align: "right",
      exportValue: (i) => (i.avg_cost_paise ?? 0) / 100,
      render: (i) => <span className="font-mono text-[#64748B]">{formatServicePrice(i.avg_cost_paise) || "—"}</span> },
    { key: "stock_value_paise", header: "Stock Value", accessor: (i) => i.stock_value_paise ?? 0, sortable: true, align: "right",
      exportValue: (i) => (i.stock_value_paise ?? 0) / 100,
      render: (i) => isUntrackedOversold(i) ? (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-amber-50 text-amber-700"
          title="Cost not established — this item sold before it ever had a purchase or opening balance recorded. Enter one to start valuing its stock.">
          Cost unknown
        </span>
      ) : (
        <span className="font-mono font-semibold text-[#0F172A]">{formatServicePrice(i.stock_value_paise) || "₹0"}</span>
      ) },
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
        <StockLedgerDrillDown clientId={clientId} financialYear={financialYear} item={drillDown} onClose={() => setDrillDown(null)} onAdjusted={load} />
      )}
    </div>
  );
}

function StockLedgerDrillDown({
  clientId, financialYear, item, onClose, onAdjusted,
}: {
  clientId: string;
  financialYear: string;
  item: StockItem;
  onClose: () => void;
  onAdjusted: () => void;
}) {
  const fyRange = fyDateRange(financialYear);
  const [startDate, setStartDate] = useState(fyRange.start);
  const [endDate, setEndDate] = useState(fyRange.end);
  const [lines, setLines] = useState<StockLedgerLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [writedownOpen, setWritedownOpen] = useState(false);

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
          <div className="flex items-center gap-3">
            <button onClick={() => setAdjustOpen(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
              <ClipboardEdit size={13} /> Adjust Stock
            </button>
            <button onClick={() => setWritedownOpen(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
              <TrendingDown size={13} /> Write Down to NRV
            </button>
            <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-xl leading-none" aria-label="Back">×</button>
          </div>
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

      {adjustOpen && (
        <AdjustStockModal
          clientId={clientId}
          item={item}
          onClose={() => setAdjustOpen(false)}
          onSaved={() => { setAdjustOpen(false); load(); onAdjusted(); }}
        />
      )}

      {writedownOpen && (
        <NrvWritedownModal
          clientId={clientId}
          item={item}
          onClose={() => setWritedownOpen(false)}
          onSaved={() => { setWritedownOpen(false); load(); onAdjusted(); }}
        />
      )}
    </div>
  );
}

function AdjustStockModal({
  clientId, item, onClose, onSaved,
}: {
  clientId: string;
  item: StockItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [direction, setDirection] = useState<"increase" | "decrease">("decrease");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("physical_count_shortage");
  const [reverseItc, setReverseItc] = useState(true);
  const [adjustmentDate, setAdjustmentDate] = useState(today);
  const [referenceNo, setReferenceNo] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reasonOptions = ADJUSTMENT_REASONS.filter((r) => r.direction === "both" || r.direction === direction);

  function onDirectionChange(next: "increase" | "decrease") {
    setDirection(next);
    const stillValid = ADJUSTMENT_REASONS.find((r) => r.value === reason && (r.direction === "both" || r.direction === next));
    const fallback = ADJUSTMENT_REASONS.find((r) => r.direction === "both" || r.direction === next);
    const resolved = stillValid ?? fallback;
    if (resolved) {
      setReason(resolved.value);
      setReverseItc(next === "decrease" && resolved.suggestReverseItc);
    }
  }

  function onReasonChange(value: string) {
    setReason(value);
    const opt = ADJUSTMENT_REASONS.find((r) => r.value === value);
    setReverseItc(direction === "decrease" && (opt?.suggestReverseItc ?? false));
  }

  async function submit() {
    const qty = parseFloat(quantity);
    if (!(qty > 0)) { setError("Enter a quantity greater than 0."); return; }
    setSaving(true);
    setError(null);
    try {
      const result = (await api.inventory.adjust(item.id, {
        client_id: clientId,
        adjustment_date: adjustmentDate,
        quantity: qty,
        direction,
        reason,
        reverse_itc: direction === "decrease" ? reverseItc : false,
        reference_no: referenceNo.trim() || undefined,
        notes: notes.trim() || undefined,
      })) as { success: boolean; error: string | null };
      if (!result.success) throw new Error(result.error ?? "Failed to record the adjustment");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record the adjustment");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-[110] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between">
          <p className="text-sm font-semibold text-[#0F172A]">Adjust Stock — {item.name}</p>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-xl leading-none" aria-label="Close">×</button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-[11px] text-[#94A3B8]">
            Currently {fmtQty(item.stock_qty_units)} on hand. This posts a journal entry immediately — review the details before saving.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Direction</label>
              <select value={direction} onChange={(e) => onDirectionChange(e.target.value as "increase" | "decrease")}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="decrease">Decrease (loss / write-off)</option>
                <option value="increase">Increase (surplus found)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Quantity *</label>
              <input type="number" min="0.001" step="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)}
                placeholder="0" className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Reason</label>
            <select value={reason} onChange={(e) => onReasonChange(e.target.value)}
              className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {reasonOptions.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>

          {direction === "decrease" && (
            <label className="flex items-start gap-2 text-xs text-[#475569] bg-amber-50 border border-amber-200 rounded-lg p-2.5 cursor-pointer">
              <input type="checkbox" checked={reverseItc} onChange={(e) => setReverseItc(e.target.checked)} className="mt-0.5 rounded" />
              <span>
                Reverse input tax credit (CGST Act §17(5)(h)). Approximated using this item&apos;s own GST rate — verify against the
                original purchase invoice for a high-value write-off.
              </span>
            </label>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
              <input type="date" value={adjustmentDate} onChange={(e) => setAdjustmentDate(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Reference</label>
              <input value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} placeholder="e.g. count sheet #"
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              placeholder="Details for the audit trail" className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} disabled={saving} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
            <button onClick={submit} disabled={saving}
              className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
              {saving && <Loader2 size={12} className="animate-spin" />} Save Adjustment
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function NrvWritedownModal({
  clientId, item, onClose, onSaved,
}: {
  clientId: string;
  item: StockItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const currentAvgCost = (item.avg_cost_paise ?? 0) / 100;
  const [nrvPerUnit, setNrvPerUnit] = useState("");
  const [writedownDate, setWritedownDate] = useState(today);
  const [referenceNo, setReferenceNo] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nrvNum = parseFloat(nrvPerUnit);
  const qty = item.stock_qty_units ?? 0;
  const previewWritedown = nrvNum >= 0 && nrvNum < currentAvgCost ? (currentAvgCost - nrvNum) * qty : 0;

  async function submit() {
    if (!(nrvNum >= 0)) { setError("Enter a valid net realisable value per unit."); return; }
    setSaving(true);
    setError(null);
    try {
      const result = (await api.inventory.writedown(item.id, {
        client_id: clientId,
        writedown_date: writedownDate,
        nrv_per_unit_paise: Math.round(nrvNum * 100),
        reference_no: referenceNo.trim() || undefined,
        notes: notes.trim() || undefined,
      })) as { success: boolean; data: unknown; error: string | null };
      if (!result.success) throw new Error(result.error ?? "Failed to record the write-down");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record the write-down");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-[110] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between">
          <p className="text-sm font-semibold text-[#0F172A]">Write Down to NRV — {item.name}</p>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-xl leading-none" aria-label="Close">×</button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-[11px] text-[#94A3B8]">
            AS-2 / Ind AS 2 / ICDS-II: inventory must be carried at the lower of cost or net realisable value. Quantity
            never changes — only the recorded value. Current average cost is {formatServicePrice(item.avg_cost_paise) || "₹0"}/unit
            on {fmtQty(qty)} units on hand.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Net realisable value / unit (₹) *</label>
              <input type="number" min="0" step="0.01" value={nrvPerUnit} onChange={(e) => setNrvPerUnit(e.target.value)}
                placeholder="0.00" className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
              <input type="date" value={writedownDate} onChange={(e) => setWritedownDate(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {previewWritedown > 0 ? (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
              This writes down inventory value by ₹{previewWritedown.toLocaleString("en-IN", { maximumFractionDigits: 2 })}.
            </p>
          ) : nrvPerUnit !== "" && nrvNum >= currentAvgCost ? (
            <p className="text-xs text-[#64748B] bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-2.5">
              NRV is at or above the current average cost — no write-down needed; nothing will be posted.
            </p>
          ) : null}

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Reference</label>
            <input value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} placeholder="e.g. valuation note #"
              className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              placeholder="Basis for the NRV estimate" className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} disabled={saving} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
            <button onClick={submit} disabled={saving}
              className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
              {saving && <Loader2 size={12} className="animate-spin" />} Save Write-down
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
