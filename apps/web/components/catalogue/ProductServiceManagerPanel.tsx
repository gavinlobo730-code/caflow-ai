"use client";

/**
 * Products & Services management — the ONE reusable UI (list, search, sort,
 * filter, bulk-select, create/edit/archive/delete). There is no standalone
 * page for it; it only ever slides in as a half-screen overlay (backdrop +
 * close affordance) from ServiceCataloguePicker's "+ Add Product/Service"
 * row on a Sales Invoice line, so a CA who wants to browse/create/edit/
 * archive/delete products never has to leave the invoice they're drafting.
 *
 * `onPick`, when provided, adds a click-to-select affordance on top of the
 * normal management actions (row click selects; the Edit/Archive/Delete
 * buttons still work independently — DataTable's actions column already
 * stops click propagation). Omit it for pure management.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Plus, Pencil, Archive, RotateCcw, Trash2, BookMarked, Upload, X } from "lucide-react";
import { api, type ApiResp } from "@/lib/api/index";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import {
  formatServiceRate, formatServicePrice, formatServiceKind, type ServiceCatalogueItem,
} from "@/lib/catalogue/service";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { Modal } from "@/components/ui/modal";
import { buildServices, SERVICE_IMPORT_COLUMNS } from "@/lib/imports/mappers";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";

export function ProductServiceManagerPanel({
  clientId,
  onClose,
  onPick,
}: {
  clientId: string;
  /** The panel's own close button + backdrop click. */
  onClose: () => void;
  /** When set, picking a row (click, or its own affordance) hands the item
   * back to the caller — used by ServiceCataloguePicker so the invoice line
   * gets auto-filled exactly like a normal search result. */
  onPick?: (item: ServiceCatalogueItem) => void;
}) {
  const [items, setItems] = useState<ServiceCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState<ServiceCatalogueItem | "new" | null>(null);
  // Import is a two-step flow: first capture ONE opening-balance "as of"
  // date for the whole file (an opening-stock import is a single conversion
  // event, not N independent ones — see handleImport), then the normal
  // upload/preview/import CsvImportModal.
  const [importStep, setImportStep] = useState<"closed" | "date" | "csv">("closed");
  const [openingBalanceDate, setOpeningBalanceDate] = useState("");
  const [toast, setToast] = useState<{ msg: string; kind: "success" | "error" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string, kind: "success" | "error") {
    setToast({ msg, kind });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  // Whole catalogue, once per client — DataTable owns search/sort/filter/
  // pagination over it client-side (SMB scale; matches every other roster).
  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setError(false);
    try {
      const res = (await api.serviceCatalogue.list(clientId, {
        include_archived: true,
        limit: 500,
      })) as ApiResp<ServiceCatalogueItem[]>;
      if (!res.success) { setError(true); return; }
      setItems(res.data ?? []);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

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

  // Permanent delete — the backend only allows this when the item has never
  // been linked to a real, non-draft/cancelled invoice/bill/note line, and
  // has no inventory stock movement history; otherwise it rejects with
  // success:false and a message pointing at Archive instead, which we
  // surface via the same error toast rather than a generic failure.
  async function deleteItem(item: ServiceCatalogueItem) {
    const ok = await confirmDialog({
      message: `Permanently delete "${item.name}"? This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    try {
      const res = (await api.serviceCatalogue.delete(item.id)) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Delete failed");
      showToast(`${item.name} deleted`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  // Bulk actions mirror the Customers tab's pattern (sales/page.tsx): no
  // pre-check GET — the backend re-validates on every call, so a blocked row
  // is just reported as a failure rather than fetched twice. Skips rows
  // already in the target state (e.g. archiving an already-archived row)
  // rather than erroring on them.
  async function bulkArchive(selected: ServiceCatalogueItem[]): Promise<boolean> {
    const targets = selected.filter((s) => s.is_active);
    let archived = 0;
    const failures: string[] = [];
    await Promise.all(targets.map(async (s) => {
      try {
        const res = (await api.serviceCatalogue.update(s.id, { is_active: false })) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        archived++;
      } catch (e) {
        failures.push(`${s.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const skipped = selected.length - targets.length;
    const parts: string[] = [];
    if (archived) parts.push(`${archived} archived`);
    if (skipped) parts.push(`${skipped} already archived`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    showToast(parts.join(", ") || "Nothing to do", failures.length ? "error" : "success");
    if (archived) load();
    return failures.length === 0;
  }

  async function bulkRestore(selected: ServiceCatalogueItem[]): Promise<boolean> {
    const targets = selected.filter((s) => !s.is_active);
    let restored = 0;
    const failures: string[] = [];
    await Promise.all(targets.map(async (s) => {
      try {
        const res = (await api.serviceCatalogue.update(s.id, { is_active: true })) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        restored++;
      } catch (e) {
        failures.push(`${s.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const skipped = selected.length - targets.length;
    const parts: string[] = [];
    if (restored) parts.push(`${restored} restored`);
    if (skipped) parts.push(`${skipped} already active`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    showToast(parts.join(", ") || "Nothing to do", failures.length ? "error" : "success");
    if (restored) load();
    return failures.length === 0;
  }

  async function bulkDelete(selected: ServiceCatalogueItem[]): Promise<boolean> {
    let deleted = 0;
    const failures: string[] = [];
    await Promise.all(selected.map(async (s) => {
      try {
        const res = (await api.serviceCatalogue.delete(s.id)) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        deleted++;
      } catch (e) {
        failures.push(`${s.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const summary = failures.length
      ? `${deleted} deleted, ${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`
      : `${deleted} item${deleted !== 1 ? "s" : ""} deleted`;
    showToast(summary, failures.length ? "error" : "success");
    if (deleted) load();
    return failures.length === 0;
  }

  /** Bulk-import products/services through /api/service-catalogue/bulk — one
   *  request for the whole file instead of one POST per row. Only Name is
   *  mandatory; everything else (kind, category, HSN/SAC, GST rate, prices,
   *  notes) is optional, matching the single-create form. */
  async function handleImport(
    rows: ImportRow[]
  ): Promise<{ imported: number; errors: string[]; skipped: number; skippedDetail: string[] }> {
    const { records, errors } = buildServices(rows, clientId);
    if (records.length === 0) return { imported: 0, errors, skipped: 0, skippedDetail: [] };

    let imported = 0;
    let skipped = 0;
    const skippedDetail: string[] = [];
    const res = (await api.serviceCatalogue.bulkCreate(records, openingBalanceDate)) as ApiResp<{
      created: unknown[];
      duplicates: { name?: string }[];
      errors: { name?: string; error: string }[];
    }>;
    if (res.success && res.data) {
      imported = res.data.created.length;
      for (const d of res.data.duplicates) {
        skipped++;
        skippedDetail.push(`"${d.name ?? "?"}" already exists — skipped`);
      }
      for (const e of res.data.errors) {
        errors.push(`"${e.name ?? "?"}": ${e.error}`);
      }
    } else {
      errors.push(res.error ?? "Bulk import failed");
    }

    if (imported > 0) load();
    return { imported, errors, skipped, skippedDetail };
  }

  function handlePick(item: ServiceCatalogueItem) {
    if (!onPick) return;
    onPick(item);
    // Fire-and-forget usage bump, same as ServiceCataloguePicker's direct
    // search-result pick — keeps recent/frequent ranking accurate regardless
    // of whether the CA picked via the fast dropdown or this panel.
    api.serviceCatalogue.recordUsed(item.id).catch(() => {});
    onClose();
  }

  // ── DataTable columns / filters ───────────────────────────────────────────
  const columns: Column<ServiceCatalogueItem>[] = useMemo(() => [
    { key: "name", header: "Name", accessor: (s) => s.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (s) => (
        <div>
          <p className="font-medium text-[#1E293B]">
            {s.name}
            <span className="ml-2 text-[9px] uppercase tracking-wide text-[#94A3B8]">{formatServiceKind(s.kind)}</span>
            {!s.is_active && <span className="ml-2 text-[10px] uppercase tracking-wide text-[#94A3B8]">archived</span>}
          </p>
          {s.description && <p className="text-[11px] text-[#94A3B8] truncate max-w-[280px]">{s.description}</p>}
        </div>
      ) },
    { key: "hsn_sac", header: "SAC/HSN", accessor: (s) => s.hsn_sac ?? "", searchable: true,
      render: (s) => <span className="font-mono text-[#64748B]">{s.hsn_sac || "—"}</span> },
    // Stock on hand — kind='good' only (migration 188). A service row shows
    // "—", never 0, since a service was never stock-tracked to begin with.
    { key: "stock_qty_units", header: "Stock", accessor: (s) => (s.kind === "good" ? s.stock_qty_units ?? 0 : 0), sortable: true, align: "right",
      render: (s) => {
        if (s.kind !== "good") return <span className="text-[#CBD5E1]">—</span>;
        const qty = s.stock_qty_units ?? 0;
        const label = Number.isInteger(qty) ? String(qty) : qty.toFixed(3).replace(/\.?0+$/, "");
        return <span className={`font-mono ${qty < 0 ? "text-red-600" : "text-[#334155]"}`}>{label}</span>;
      } },
    { key: "gst_rate_bps", header: "GST", accessor: (s) => s.gst_rate_bps ?? 0, sortable: true, align: "right",
      render: (s) => <span className="text-[#334155]">{formatServiceRate(s.gst_rate_bps) || "—"}</span> },
    { key: "default_rate_paise", header: "Selling price", accessor: (s) => s.default_rate_paise ?? 0, sortable: true, align: "right",
      render: (s) => <span className="font-mono text-[#334155]">{formatServicePrice(s.default_rate_paise) || "—"}</span> },
  ], []);

  const filters: FilterDef<ServiceCatalogueItem>[] = useMemo(() => [
    { key: "is_active", label: "Status", type: "select", accessor: (s) => (s.is_active ? "active" : "inactive"), options: [
      { value: "active", label: "Active" },
      { value: "inactive", label: "Archived" },
    ] },
  ], []);

  const body = (
    <div className="space-y-5">
      {toast && (
        <div className={`fixed top-4 right-4 z-[70] px-4 py-2 rounded-lg text-sm shadow-lg ${toast.kind === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2"><BookMarked size={18} className="text-emerald-600" /> Products &amp; Services</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            {onPick
              ? "Search, pick, or manage this client's billing presets without leaving the invoice."
              : "Reusable billing presets for this client. Products (kind='good') also track stock and moving-average cost — see the Inventory tab for full ledger detail."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setOpeningBalanceDate(""); setImportStep("date"); }}
            className="flex items-center gap-1.5 text-sm border border-[#E2E8F0] text-[#475569] px-3.5 py-2 rounded-lg hover:bg-[#F8FAFC] whitespace-nowrap"
          >
            <Upload size={15} /> Import
          </button>
          <button
            onClick={() => setEditing("new")}
            className="flex items-center gap-1.5 text-sm bg-emerald-600 text-white px-3.5 py-2 rounded-lg hover:bg-emerald-700 whitespace-nowrap"
          >
            <Plus size={15} /> New Product/Service
          </button>
        </div>
      </div>

      {/* Table — shared DataTable (search, sort, filters, pagination, export, bulk-select) */}
      <DataTable
        data={items}
        columns={columns}
        filters={filters}
        getRowId={(s) => s.id}
        loading={loading}
        error={error ? "Couldn't load Products & Services" : null}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search by name, SAC/HSN or description…"
        initialSort={{ key: "name", dir: "asc" }}
        initialFilters={{ is_active: "active" }}
        exportFilename="products-services"
        persistKey="products-services"
        emptyTitle="No products or services yet"
        emptyAction={
          <button onClick={() => setEditing("new")} className="mt-3 text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
            Create the first one
          </button>
        }
        onRowClick={onPick ? handlePick : undefined}
        bulkActions={[
          {
            id: "archive",
            label: "Archive",
            icon: <Archive size={13} />,
            confirm: "Archive the selected products/services? They will no longer appear in the invoice picker. Existing invoices are unaffected and this can be undone.",
            run: bulkArchive,
          },
          {
            id: "restore",
            label: "Restore",
            icon: <RotateCcw size={13} />,
            run: bulkRestore,
          },
          {
            id: "delete-permanent",
            label: "Delete permanently",
            icon: <Trash2 size={13} />,
            variant: "danger",
            confirm: "Permanently delete the selected products/services? Any item still in use (an invoice, bill, note, or with stock history) will be skipped. This cannot be undone.",
            run: bulkDelete,
          },
          exportSelectedAction("products-services-selected.csv", columns),
        ]}
        rowActions={(s) => (
          <div className="flex items-center justify-end gap-1">
            {onPick && (
              <button onClick={(e) => { e.stopPropagation(); handlePick(s); }} className="px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-50 rounded" aria-label={`Select ${s.name}`}>
                Select
              </button>
            )}
            <button onClick={() => setEditing(s)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Edit"><Pencil size={14} /></button>
            {s.is_active ? (
              <button onClick={() => setActive(s, false)} className="p-1.5 text-[#64748B] hover:text-amber-600 hover:bg-amber-50 rounded" aria-label="Archive"><Archive size={14} /></button>
            ) : (
              <button onClick={() => setActive(s, true)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Restore"><RotateCcw size={14} /></button>
            )}
            <button onClick={() => deleteItem(s)} className="p-1.5 text-[#64748B] hover:text-red-600 hover:bg-red-50 rounded" aria-label="Delete"><Trash2 size={14} /></button>
          </div>
        )}
      />

      {editing && (
        <ProductServiceFormModal
          clientId={clientId}
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(item) => {
            setEditing(null);
            showToast(`${item.name} ${editing === "new" ? "created" : "updated"}`, "success");
            load();
            // A fresh create in picker mode is almost always meant for THIS
            // line — hand it straight back, same as the old create-only flow.
            if (onPick && editing === "new") handlePick(item);
          }}
          onError={(msg) => showToast(msg, "error")}
        />
      )}

      {importStep === "date" && (
        <Modal title="Opening stock date" onClose={() => setImportStep("closed")} maxWidthClass="max-w-md">
          <p className="text-sm text-[#64748B]">
            If your file sets opening stock (quantity/value) for any products, what date is that stock <strong>as of</strong>?
            This is when the stock existed — not today, or whenever you happen to be importing. Leave blank to default to your client&apos;s financial-year start.
          </p>
          <label className="block space-y-1">
            <span className="block text-xs font-medium text-[#475569]">Opening balance as of (optional)</span>
            <input
              type="date"
              autoFocus
              value={openingBalanceDate}
              onChange={(e) => setOpeningBalanceDate(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </label>
          <p className="text-xs text-[#94A3B8]">No opening stock in this file? Leave this blank and continue — it's ignored for rows with no opening quantity/value.</p>
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={() => setImportStep("closed")} className="text-sm px-3.5 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={() => setImportStep("csv")} className="text-sm px-4 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">Continue</button>
          </div>
        </Modal>
      )}

      {importStep === "csv" && (
        <CsvImportModal
          title="Import Products & Services"
          columns={SERVICE_IMPORT_COLUMNS}
          templateFilename="products-services-template.csv"
          onImport={handleImport}
          onClose={() => setImportStep("closed")}
        />
      )}
    </div>
  );

  // Half-screen slide-over from the right, backdrop closes it — same
  // layering convention (fixed inset-0 backdrop + z-index) as every other
  // modal in the app (ProductServiceFormModal, CsvImportModal, …).
  return (
    <div className="fixed inset-0 z-[80] flex justify-end bg-[#0F172A]/50" onClick={onClose}>
      <div
        className="relative h-full w-full max-w-3xl overflow-y-auto bg-[#F8FAFC] p-6 pt-14 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 rounded-lg p-1.5 text-[#94A3B8] hover:bg-white hover:text-[#334155]"
        >
          <X size={18} />
        </button>
        {body}
      </div>
    </div>
  );
}
