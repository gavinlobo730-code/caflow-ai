"use client";

/**
 * Firm HSN/SAC Library management (HSN/SAC architecture redesign, Phase 2).
 *
 * The CA-owned, CA-curated source of HSN/SAC codes. Add manually, edit,
 * retire (never hard-deleted), search. Caflow does not ship or suggest a
 * classification here — only structural validation (digits, non-blank
 * description). Every Product/Service and invoice line selects its code
 * from THIS list; see FirmHsnLibraryQuickAddModal for the same add flow
 * reachable inline from an invoice/product form.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, Pencil, Archive, RotateCcw, Search, Hash, Upload, Download, Trash2, X } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";
import {
  FirmHsnLibraryQuickAddModal, type FirmHsnLibraryRow,
} from "@/components/lookups/FirmHsnLibraryQuickAddModal";
import CsvImportModal from "@/components/LazyCsvImportModal";
import type { ImportRow } from "@/components/CsvImportModal";
import { FIRM_HSN_LIBRARY_IMPORT_COLUMNS, buildFirmHsnCodes } from "@/lib/imports/firmHsnLibrary";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import type { Column } from "@/lib/table/types";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { TableSkeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { readWindow } from "@/lib/lists/readWindow";
import { windowDescription } from "@/lib/lists/window";

type Filter = "active" | "archived";
type TypeFilter = "all" | "goods" | "services";

// The window the screen asks for. The server caps a single list response (routers/firm_hsn_library.py) and answers
// `has_more` and its own ceiling, so the count badge shows "200+" only when the server says more exist, and the screen
// never compares a row count to this number (POST-A-262).
const HSN_LIBRARY_FETCH_LIMIT = 200;

const EXPORT_COLUMNS: Column<FirmHsnLibraryRow>[] = [
  { key: "hsn_code", header: "Code", accessor: (r) => r.hsn_code },
  { key: "description", header: "Description", accessor: (r) => r.description },
  { key: "hsn_type", header: "Type", accessor: (r) => r.hsn_type },
  { key: "gst_rate_pct", header: "GST Rate", accessor: (r) => r.gst_rate_pct ?? "" },
  { key: "is_active", header: "Status", accessor: (r) => (r.is_active ? "Active" : "Archived") },
];

export default function FirmHsnLibraryPage() {
  const [items, setItems] = useState<FirmHsnLibraryRow[]>([]);
  // The server's window over the list on screen. The Archived tab asks the server for retired codes only
  // (`archived_only`), so it is a window over those and not a filter over a window of everything.
  const [win, setWin] = useState<{ hasMore: boolean; limit: number; maxLimit: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editing, setEditing] = useState<FirmHsnLibraryRow | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: "success" | "error" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = bulkBusy || rowBusy;

  function showToast(msg: string, kind: "success" | "error") {
    setToast({ msg, kind });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = (await api.firmHsnLibrary.list({
        q: q.trim() || undefined,
        hsn_type: typeFilter === "all" ? undefined : typeFilter,
        archived_only: filter === "archived",
        limit: HSN_LIBRARY_FETCH_LIMIT,
      })) as ApiResp<unknown>;
      const w = res.success ? readWindow<FirmHsnLibraryRow>(res.data, "codes", HSN_LIBRARY_FETCH_LIMIT) : null;
      if (!w) { setError(true); return; }
      setWin({ hasMore: w.hasMore, limit: w.limit, maxLimit: w.maxLimit });
      setItems(w.rows);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [q, filter, typeFilter]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  // Selection only ever refers to rows on screen — drop it whenever the
  // visible set changes (search/filter/tab switch or a reload).
  useEffect(() => { setSelected(new Set()); }, [items]);

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function toggleSelectAll() {
    setSelected((prev) => (prev.size === items.length ? new Set() : new Set(items.map((r) => r.id))));
  }

  async function retire(row: FirmHsnLibraryRow) {
    setRowBusy(true);
    try {
    try {
      const res = (await api.firmHsnLibrary.retire(row.id)) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Could not retire this code.");
      showToast(`${row.hsn_code} retired`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Could not retire this code.", "error");
    }
  } finally { setRowBusy(false); }
  }

  async function restore(row: FirmHsnLibraryRow) {
    setRowBusy(true);
    try {
    try {
      const res = (await api.firmHsnLibrary.update(row.id, { is_active: true })) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Could not restore this code.");
      showToast(`${row.hsn_code} restored`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Could not restore this code.", "error");
    }
  } finally { setRowBusy(false); }
  }

  /** Permanent delete — blocked server-side (with a specific reason) if the
   *  code is still used anywhere. Distinct from retire(), which is always
   *  allowed and just hides the code from the active picker. */
  async function purgeSingle(row: FirmHsnLibraryRow) {
    setRowBusy(true);
    try {
    const ok = await confirmDialog({
      message: `Permanently delete ${row.hsn_code} — ${row.description}? This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    try {
      const res = (await api.firmHsnLibrary.purge(row.id)) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Could not delete this code.");
      showToast(`${row.hsn_code} permanently deleted`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Could not delete this code.", "error");
    }
  } finally { setRowBusy(false); }
  }

  async function bulkDelete() {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    const ok = await confirmDialog({
      message: `Permanently delete ${ids.length} code${ids.length === 1 ? "" : "s"}? Any code still in use will be skipped. This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    setBulkBusy(true);
    try {
      const res = (await api.firmHsnLibrary.bulkPurge(ids)) as ApiResp<{
        deleted: string[];
        blocked: { id: string; hsn_code: string; used_in: string[] }[];
      }>;
      if (!res.success || !res.data) throw new Error(res.error ?? "Bulk delete failed.");
      const { deleted, blocked } = res.data;
      if (blocked.length === 0) {
        showToast(`${deleted.length} code${deleted.length === 1 ? "" : "s"} permanently deleted`, "success");
      } else {
        const blockedCodes = blocked.map((b) => b.hsn_code).join(", ");
        showToast(
          `${deleted.length} deleted. ${blocked.length} skipped (still in use): ${blockedCodes}`,
          deleted.length > 0 ? "success" : "error",
        );
      }
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Bulk delete failed.", "error");
    } finally {
      setBulkBusy(false);
    }
  }

  /** Bulk-import HSN/SAC codes through /api/firm-hsn-library/bulk — one
   *  request for the whole file instead of one POST per row. A retired code
   *  that reappears in the file is reactivated (counts as imported, not
   *  skipped); an already-active duplicate is reported as skipped. */
  async function handleImport(
    rows: ImportRow[]
  ): Promise<{ imported: number; errors: string[]; skipped: number; skippedDetail: string[] }> {
    const { records, errors } = buildFirmHsnCodes(rows);
    if (records.length === 0) return { imported: 0, errors, skipped: 0, skippedDetail: [] };

    let imported = 0;
    let skipped = 0;
    const skippedDetail: string[] = [];
    const res = (await api.firmHsnLibrary.bulkAdd(records)) as ApiResp<{
      created: FirmHsnLibraryRow[];
      reactivated: FirmHsnLibraryRow[];
      duplicates: { hsn_code?: string }[];
      errors: { hsn_code?: string; error: string }[];
    }>;
    if (res.success && res.data) {
      imported = res.data.created.length + res.data.reactivated.length;
      for (const d of res.data.duplicates) {
        skipped++;
        skippedDetail.push(`"${d.hsn_code ?? "?"}" already in your library — skipped`);
      }
      for (const e of res.data.errors) {
        errors.push(`"${e.hsn_code ?? "?"}": ${e.error}`);
      }
    } else {
      errors.push(res.error ?? "Bulk import failed");
    }

    if (imported > 0) load();
    return { imported, errors, skipped, skippedDetail };
  }

  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <div className="p-6 max-w-ps-data mx-auto space-y-5">
        {toast && (
          <div className={`fixed top-4 right-4 z-[70] px-4 py-2 rounded-lg text-sm shadow-lg ${toast.kind === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
            {toast.msg}
          </div>
        )}

        <PageHeader
          back={{ href: "/settings", label: "Settings" }}
          icon={<Hash size={18} className="text-violet-600" />}
          title="Firm HSN/SAC Library"
          meta={
            !loading && !error ? (
              <span className="text-xs font-normal text-ps-hint">
                {items.length}{win?.hasMore ? "+" : ""} code{items.length === 1 ? "" : "s"}
              </span>
            ) : undefined
          }
          subtitle={
            <>
              The HSN/SAC codes your firm bills against. You add and curate every code here — Caflow does not ship a shared list or suggest a classification; every Product/Service and invoice line picks from this library.
            </>
          }
          actions={
            <>
              <button
                onClick={() => setImporting(true)}
                className="flex items-center gap-1.5 text-sm border border-ps-border text-ps-label px-3.5 py-2 rounded-lg hover:bg-ps-bg whitespace-nowrap"
              >
                <Upload size={15} /> Import
              </button>
              <button
                onClick={() => downloadCsv("firm-hsn-sac-library.csv", toCsv(items, EXPORT_COLUMNS))}
                disabled={items.length === 0}
                className="flex items-center gap-1.5 text-sm border border-ps-border text-ps-label px-3.5 py-2 rounded-lg hover:bg-ps-bg whitespace-nowrap disabled:opacity-50"
              >
                <Download size={15} /> Export
              </button>
              <button
                onClick={() => setAdding(true)}
                className="flex items-center gap-1.5 text-sm bg-brand text-white px-3.5 py-2 rounded-lg hover:bg-brand-dark whitespace-nowrap"
              >
                <Plus size={15} /> Add Code
              </button>
            </>
          }
        />

        {/* Search + filters */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ps-hint" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by code or description…"
              className="w-full pl-8 pr-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
            />
          </div>
          <select
            aria-label="Filter by goods or services"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            className="px-3 py-2 text-xs border border-ps-border rounded-lg"
          >
            <option value="all">All types</option>
            <option value="services">Services (SAC)</option>
            <option value="goods">Goods (HSN)</option>
          </select>
          <div className="flex rounded-lg border border-ps-border overflow-hidden text-xs">
            {(["active", "archived"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-2 capitalize ${filter === f ? "bg-brand text-white" : "bg-white text-ps-label hover:bg-ps-bg"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Bulk action bar */}
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-light bg-brand-surface px-3 py-2 text-xs">
            <span className="font-semibold text-brand-dark">{selected.size} selected</span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Button variant="plain" size="none"
                onClick={bulkDelete}
                disabled={actionInFlight}
                className="inline-flex items-center gap-1.5 rounded-lg border border-state-problem-border bg-white px-2.5 py-1.5 font-medium text-state-problem hover:bg-state-problem-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 size={13} /> {bulkBusy ? "Deleting…" : "Delete"}
              </Button>
              <button onClick={() => setSelected(new Set())} disabled={bulkBusy} className="text-brand hover:text-brand-dark disabled:opacity-50" aria-label="Clear selection">
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {win && !loading && !error && (
          <ListWindowNotice
            hasMore={win.hasMore}
            what={windowDescription(items.length, "codes", "first", "in code order")}
            limit={win.limit}
            maxLimit={win.maxLimit}
            elsewhere="Search, or filter by type, to narrow the list."
          />
        )}

        {/* List */}
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          {loading ? (
            <TableSkeleton cols={6} rows={4} bare />
          ) : error ? (
            <div className="p-8 text-center text-sm">
              <p className="text-ps-body font-medium">Couldn&apos;t load your library</p>
              <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">Retry</button>
            </div>
          ) : items.length === 0 ? (
            <div className="p-10 text-center">
              <Hash size={26} className="mx-auto mb-2 text-ps-disabled" />
              <p className="text-sm font-medium text-ps-body">
                {q ? "No codes match your search" : filter === "archived" ? "No retired codes" : "Your library is empty"}
              </p>
              {!q && filter === "active" && (
                <button onClick={() => setAdding(true)} className="mt-3 text-xs px-3 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark">
                  Add your first code
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-2xs text-ps-hint border-b border-ps-border">
                    <th className="w-8 px-4 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all visible codes"
                        checked={items.length > 0 && selected.size === items.length}
                        ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < items.length; }}
                        onChange={toggleSelectAll}
                        className="cursor-pointer accent-violet-600"
                      />
                    </th>
                    <th className="px-4 py-2 text-left font-semibold">Code</th>
                    <th className="px-4 py-2 text-left font-semibold">Description</th>
                    <th className="px-4 py-2 text-left font-semibold">Type</th>
                    <th className="px-4 py-2 text-right font-semibold">GST rate</th>
                    <th className="px-4 py-2 text-right font-semibold w-28"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {items.map((r) => {
                    const active = filter === "active";
                    return (
                      <tr key={r.id} className={active ? "" : "bg-ps-bg text-ps-hint"}>
                        <td className="px-4 py-2.5">
                          <input
                            type="checkbox"
                            aria-label={`Select ${r.hsn_code}`}
                            checked={selected.has(r.id)}
                            onChange={() => toggleRow(r.id)}
                            className="cursor-pointer accent-violet-600"
                          />
                        </td>
                        <td className="px-4 py-2.5 font-mono text-ps-ink">{r.hsn_code}</td>
                        <td className="px-4 py-2.5">
                          <p className="text-ps-ink truncate max-w-[280px]">{r.description}</p>
                        </td>
                        <td className="px-4 py-2.5 text-ps-label capitalize">{r.hsn_type}</td>
                        <td className="px-4 py-2.5 text-right text-ps-body">
                          {r.gst_rate_pct != null ? `${r.gst_rate_pct}%` : "—"}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center justify-end gap-1">
                            <button onClick={() => setEditing(r)} className="p-1.5 text-ps-label hover:text-violet-600 hover:bg-violet-50 rounded" aria-label="Edit"><Pencil size={14} /></button>
                            {active ? (
                              <Button variant="plain" size="none" disabled={actionInFlight} onClick={() => retire(r)} className="p-1.5 text-ps-label hover:text-amber-600 hover:bg-state-attention-hover rounded" aria-label="Retire"><Archive size={14} /></Button>
                            ) : (
                              <Button variant="plain" size="none" disabled={actionInFlight} onClick={() => restore(r)} className="p-1.5 text-ps-label hover:text-violet-600 hover:bg-violet-50 rounded" aria-label="Restore"><RotateCcw size={14} /></Button>
                            )}
                            <Button variant="plain" size="none" disabled={actionInFlight} onClick={() => purgeSingle(r)} className="p-1.5 text-ps-label hover:text-red-600 hover:bg-state-problem-hover rounded" aria-label="Delete permanently"><Trash2 size={14} /></Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {adding && (
        <FirmHsnLibraryQuickAddModal
          onClose={() => setAdding(false)}
          onAdded={() => { setAdding(false); showToast("Code added to your library", "success"); load(); }}
        />
      )}

      {importing && (
        <CsvImportModal
          title="Import HSN/SAC Codes"
          columns={FIRM_HSN_LIBRARY_IMPORT_COLUMNS}
          templateFilename="hsn-sac-library-template.csv"
          onImport={handleImport}
          onClose={() => setImporting(false)}
        />
      )}

      {editing && (
        <EditCodeModal
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); showToast(`${editing.hsn_code} updated`, "success"); load(); }}
          onError={(msg) => showToast(msg, "error")}
        />
      )}
    </RoleGuard>
  );
}

function EditCodeModal({ row, onClose, onSaved, onError }: {
  row: FirmHsnLibraryRow;
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const [description, setDescription] = useState(row.description);
  const [gstRate, setGstRate] = useState<number | "">(row.gst_rate_pct ?? "");
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!description.trim()) { onError("Description cannot be blank."); return; }
    setSaving(true);
    try {
      const res = (await api.firmHsnLibrary.update(row.id, {
        description: description.trim(),
        gst_rate_pct: gstRate === "" ? null : gstRate,
      })) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Save failed");
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-md bg-white rounded-xl shadow-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-ps-ink">Edit {row.hsn_code}</h3>
        <label className="block space-y-1">
          <span className="block text-xs font-medium text-ps-label">Description</span>
          <input
            autoFocus
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
          />
        </label>
        <label className="block space-y-1">
          <span className="block text-xs font-medium text-ps-label">GST rate (optional)</span>
          <input
            type="number" min="0" max="100" step="0.01"
            value={gstRate}
            onChange={(e) => setGstRate(e.target.value === "" ? "" : parseFloat(e.target.value))}
            placeholder="Varies / not set"
            className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
          />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={saving} className="text-sm px-3.5 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-50">Cancel</button>
          <Button variant="plain" size="none" onClick={submit} disabled={saving} className="text-sm px-4 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50">
            Save changes
          </Button>
        </div>
      </div>
    </div>
  );
}
