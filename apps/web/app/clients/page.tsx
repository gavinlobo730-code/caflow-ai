"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { pruneSelection } from "@/lib/table/pruneSelection";
import Link from "next/link";
import {
  ChevronRight, Plus, Search, RefreshCw, Pencil, KanbanSquare, Upload, Download,
  MoreVertical, Archive, RotateCcw, Trash2, X,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClientFormModal } from "@/components/ClientFormModal";
import {
  getClients, archiveClient, restoreClient, permanentDeleteClient,
  type ClientFilter, DeleteBlockedError,
} from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { filterClients } from "@/lib/clients/search";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getLatestHealthScores } from "@/lib/services/health-score-compute";
import { HealthBadgeLight } from "@/components/HealthBadge";
import { usePermissions } from "@/lib/auth/AuthContext";
import { api } from "@/lib/api";
import { gstinProblem } from "@/lib/gst/gstin";
import { panProblem } from "@/lib/identifiers/pan";

const CLIENT_IMPORT_COLUMNS = [
  { key: "client_name",  label: "Client Name",    required: true,  hint: "e.g. ABC Pvt Ltd" },
  { key: "entity_type",  label: "Entity Type",    required: true,  hint: "Proprietorship | Partnership | LLP | Private Limited | Public Limited | Trust | Society | Individual" },
  { key: "pan",          label: "PAN",            required: true,  hint: "e.g. AABCU9603R — 10 chars" },
  { key: "gstin",        label: "GSTIN",          required: false, hint: "e.g. 27AABCU9603R1ZN — 15 chars" },
  { key: "mobile",       label: "Mobile",         required: false, hint: "e.g. 9876543210" },
  { key: "email",        label: "Email",          required: false, hint: "e.g. client@example.com" },
  { key: "city",         label: "City",           required: false, hint: "e.g. Mumbai" },
  { key: "state",        label: "State",          required: false, hint: "e.g. Maharashtra" },
  { key: "pincode",      label: "Pincode",        required: false, hint: "6-digit" },
  { key: "gst_filing_frequency", label: "GST Frequency", required: false, hint: "monthly | quarterly" },
];

// Raw entity_type (not the friendly ENTITY_LABELS) so an exported CSV can be
// re-imported via CLIENT_IMPORT_COLUMNS above without a manual translation step.
/** One client's standing on this payroll month, as the firm-grain endpoint
 *  returns it (GET /api/payroll/client-states). `run_status` is null when no
 *  run exists for the month, which for an ENABLED client means "not started"
 *  and for a disabled one means nothing at all — the two are rendered
 *  differently rather than collapsed into one word. */
type PayrollState = {
  client_id: string;
  payroll_enabled: boolean;
  run_status: string | null;
  headcount: number | null;
};

/** The badge for a client's payroll month, or null where there is nothing
 *  honest to say. Colour follows the module's own vocabulary: a released run
 *  (finalized/paid) is settled, a draft is in hand, and an enabled client with
 *  no run is the one that needs somebody. */
function payrollBadge(p: PayrollState | undefined):
    { label: string; className: string; title: string } | null {
  if (!p) return null;
  if (!p.payroll_enabled) {
    return {
      label: "Payroll off",
      className: "bg-ps-muted text-ps-label",
      title: "This firm does not run payroll for this client. Existing payroll "
           + "records stay readable; nothing new can be created.",
    };
  }
  const status = p.run_status;
  if (status === "paid" || status === "finalized") {
    return {
      label: status === "paid" ? "Payroll paid" : "Payroll finalised",
      className: "bg-green-100 text-green-700",
      title: `This month's payroll is ${status}.`,
    };
  }
  if (status) {
    return {
      label: "Payroll draft",
      className: "bg-blue-100 text-blue-700",
      title: "This month's payroll run exists and has not been released.",
    };
  }
  return {
    label: "Payroll due",
    className: "bg-state-attention-surface text-state-attention",
    title: "Payroll is switched on for this client and this month's run has "
         + "not been started.",
  };
}


const CLIENT_EXPORT_COLUMNS: { key: string; header: string; accessor: (row: Client) => unknown }[] = [
  { key: "client_name", header: "Client Name", accessor: (c) => c.client_name },
  { key: "entity_type", header: "Entity Type", accessor: (c) => c.entity_type },
  { key: "pan",         header: "PAN",         accessor: (c) => c.pan },
  { key: "gstin",       header: "GSTIN",       accessor: (c) => c.gstin },
  { key: "mobile",      header: "Mobile",      accessor: (c) => c.mobile },
  { key: "email",       header: "Email",       accessor: (c) => c.email },
  { key: "city",        header: "City",        accessor: (c) => c.city },
  { key: "state",       header: "State",       accessor: (c) => c.state },
  { key: "pincode",     header: "Pincode",     accessor: (c) => c.pincode },
  { key: "status",      header: "Status",      accessor: (c) => c.status },
];

const VALID_ENTITY_TYPES = ["Proprietorship","Partnership","LLP","Private Limited","Public Limited","Trust","Society","Individual"];
// PAN — IT Act §139A, through `lib/identifiers/pan.panProblem`, which
// normalises the way `core/validators.validate_pan` does. This tested the
// raw cell, so a spreadsheet column left in lower case failed every row.
// The GSTIN rule is `lib/gst/gstin.gstinProblem` and there is one of it — a
// shape regex here accepted every transposition inside the PAN, on the door
// that writes a whole spreadsheet of clients at once.

const ENTITY_LABELS: Record<string, string> = {
  Proprietorship: "Prop.", Partnership: "Partner.", LLP: "LLP",
  "Private Limited": "Pvt Ltd", "Public Limited": "Pub Ltd",
  Trust: "Trust", Society: "Society", Individual: "Individual",
};

const FILTER_TABS: { id: ClientFilter; label: string }[] = [
  { id: "active",   label: "Active"   },
  { id: "archived", label: "Archived" },
  { id: "all",      label: "All"      },
];

export default function ClientsPage() {
  const [filter, setFilter]       = useState<ClientFilter>("active");
  const [clients, setClients]     = useState<Client[]>([]);
  const [filtered, setFiltered]   = useState<Client[]>([]);
  const [healthScores, setHealthScores] = useState<Record<string, number>>({});
  /** client_id -> this month's payroll state (migration 332, payroll v1 item 11).
   *  Only clients the firm has a payroll setting or run for appear, so a client
   *  the firm does not run payroll for shows no badge at all rather than an
   *  "off" one — most clients have no payroll and a badge on all forty would
   *  be noise. */
  const [payrollStates, setPayrollStates] = useState<Record<string, PayrollState>>({});
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [search, setSearch]       = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editClient, setEditClient] = useState<Client | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  // Action dropdown
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Lifecycle modals
  const [archiveTarget, setArchiveTarget]         = useState<Client | null>(null);
  const [restoreTarget, setRestoreTarget]         = useState<Client | null>(null);
  const [deleteTarget, setDeleteTarget]           = useState<Client | null>(null);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [deleteBlockers, setDeleteBlockers]       = useState<string[] | null>(null);
  const [actionBusy, setActionBusy]               = useState(false);
  const [actionError, setActionError]             = useState<string | null>(null);

  // Bulk select (Archive) — mirrors the BankMatchQueue selection pattern
  // (app/clients/[id]/accounting/page.tsx): Set<id>, toggle/select-all/clear,
  // bulk action bar shown only when something is selected.
  const [selected, setSelected]   = useState<Set<string>>(new Set());

  // A selection may only name rows still on screen (see lib/table/pruneSelection).
  useEffect(() => { setSelected((s) => pruneSelection(s, clients.map((c) => c.id))); }, [clients]);
  const [bulkBusy, setBulkBusy]   = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = actionBusy || bulkBusy;
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  // Read from the backend's permission map rather than a role list copied here:
  // archive/delete are rbac("client","write") and rbac("client","delete"), and a
  // second copy of who holds those is a copy that can drift out of step.
  const { can } = usePermissions();
  const canArchive = can("client", "write");
  const canDelete  = can("client", "delete");
  const hasActions = canArchive || canDelete;

  // ── Data loading ────────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getClients(filter);
      setClients(data);
      setFiltered(data);
      getLatestHealthScores(data.map((c) => c.id)).then(setHealthScores).catch(() => {});
      // One firm-wide request, not one per client. Failure is silent and the
      // badges simply do not appear: a payroll state is useful context on this
      // screen, never the reason it exists, and a client list that refuses to
      // render because payroll could not be read would be a worse screen.
      api.payroll.payrollClientStates()
        .then((res) => {
          const rows = (res as { data?: { clients?: PayrollState[] } })?.data?.clients ?? [];
          setPayrollStates(Object.fromEntries(rows.map((r) => [r.client_id, r])));
        })
        .catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load clients");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  // Wait for Supabase session before fetching (RLS requires auth.uid()).
  useEffect(() => {
    const sb = getSupabaseClient();
    sb.auth.getSession().then(({ data }) => {
      if (data.session) load();
      else setLoading(false);
    });
    const { data: { subscription } } = sb.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_IN") load();
    });
    return () => subscription.unsubscribe();
  }, [load]);

  // Client-side search filter. Null-safe across every searchable field (see
  // lib/clients/search): pan/gstin/email/etc. are nullable, so the search must
  // never call a string method on a missing value (BUG 001 — NULL pan crash).
  useEffect(() => {
    setFiltered(filterClients(clients, search));
  }, [search, clients]);

  // Close action dropdown on outside click
  useEffect(() => {
    if (!menuOpenId) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpenId]);

  // Selection is over the visible list — a new filter tab shows a different
  // set of clients, so stale selected ids no longer make sense.
  useEffect(() => {
    setSelected(new Set());
    setBulkError(null);
    setBulkMessage(null);
  }, [filter]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  function handleSaved(client: Client) {
    setClients(prev => {
      const idx = prev.findIndex(c => c.id === client.id);
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = client;
        return updated;
      }
      return [client, ...prev];
    });
  }

  function openEdit(e: React.MouseEvent, client: Client) {
    e.preventDefault();
    e.stopPropagation();
    setEditClient(client);
    setModalOpen(true);
  }

  function openCreate() {
    setEditClient(null);
    setModalOpen(true);
  }

  async function handleArchive() {
    if (!archiveTarget) return;
    setActionBusy(true);
    setActionError(null);
    try {
      await archiveClient(archiveTarget.id);
      setArchiveTarget(null);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Archive failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRestore() {
    if (!restoreTarget) return;
    setActionBusy(true);
    setActionError(null);
    try {
      await restoreClient(restoreTarget.id);
      setRestoreTarget(null);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Restore failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget || deleteConfirmName !== deleteTarget.client_name) return;
    setActionBusy(true);
    setActionError(null);
    setDeleteBlockers(null);
    try {
      await permanentDeleteClient(deleteTarget.id);
      setDeleteTarget(null);
      setDeleteConfirmName("");
      load();
    } catch (e) {
      if (e instanceof DeleteBlockedError) {
        setDeleteBlockers(e.blockers);
        setActionError(null);
      } else {
        setActionError(e instanceof Error ? e.message : "Delete failed");
      }
    } finally {
      setActionBusy(false);
    }
  }

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === filtered.length ? new Set() : new Set(filtered.map((c) => c.id))));
  }

  function clearSelection() {
    setSelected(new Set());
    setBulkError(null);
    setBulkMessage(null);
  }

  // Bulk archive: skips already-archived clients client-side, runs the rest
  // in parallel, and reports partial failures without silently clearing the
  // selection — a prior bug in this codebase's shared DataTable component
  // cleared selection on partial failure and hid which rows still needed
  // attention, so this deliberately keeps selection whenever anything failed.
  async function bulkArchive() {
    if (selected.size === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    setBulkMessage(null);

    const ids = Array.from(selected);
    const targets = ids.filter((id) => clients.find((c) => c.id === id)?.status !== "archived");
    const skipped = ids.length - targets.length;

    const results = await Promise.all(
      targets.map((id) =>
        archiveClient(id).then(
          () => ({ id, error: null as string | null }),
          (e) => ({ id, error: e instanceof Error ? e.message : "Archive failed" }),
        ),
      ),
    );
    const failed = results.filter((r) => r.error !== null);
    const succeeded = targets.length - failed.length;

    try {
      if (succeeded > 0) await load();
    } catch (e) {
      // The archives went through; only the refresh failed, so the roster on
      // screen still lists rows that are no longer active. Say which it is
      // rather than leaving the bulk bar disabled.
      setBulkError(e instanceof Error ? e.message : "Archived, but the client list could not be refreshed.");
      return;
    } finally {
      setBulkBusy(false);
    }

    if (failed.length > 0) {
      // The action completed with partial failures — report them, but still
      // clear the selection. The successfully-archived clients have left this
      // active-only roster, so keeping them selected just leaves a stale
      // "N selected" count. Mirrors the shared DataTable's bulk-action behavior.
      setBulkError(
        `Archived ${succeeded} of ${targets.length} client${targets.length === 1 ? "" : "s"}` +
        (skipped > 0 ? `, skipped ${skipped} already archived` : "") +
        `. Failed: ${failed.length} — ${failed[0].error}${failed.length > 1 ? ` (+${failed.length - 1} more)` : ""}.`
      );
      setSelected(new Set());
      return;
    }

    // Full success (skips are not failures) — clear selection.
    if (targets.length === 0) {
      setBulkMessage(`All ${skipped} selected client${skipped === 1 ? " is" : "s are"} already archived.`);
    } else {
      setBulkMessage(
        `Archived ${succeeded} client${succeeded === 1 ? "" : "s"}` +
        (skipped > 0 ? `. Skipped ${skipped} already archived.` : ".")
      );
    }
    setSelected(new Set());
  }

  async function handleClientImport(rows: ImportRow[]) {
    const sb = getSupabaseClient();
    const firmId = await getFirmId();
    let imported = 0;
    const errors: string[] = [];
    for (const row of rows) {
      const { error } = await sb.from("clients").insert({
        firm_id: firmId,
        client_name: row.client_name,
        entity_type: row.entity_type,
        pan: row.pan.toUpperCase(),
        gstin: row.gstin?.toUpperCase() || null,
        mobile: row.mobile || null,
        email: row.email || null,
        city: row.city || null,
        state: row.state || null,
        pincode: row.pincode || null,
        gst_filing_frequency: row.gst_filing_frequency || "monthly",
        status: "active",
      });
      if (error) errors.push(`${row.client_name}: ${error.message}`);
      else imported++;
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ps-ink">Clients</h1>
          <p className="text-ps-label text-sm mt-1">
            {loading ? "Loading…" : `${filtered.length} client${filtered.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="p-2 rounded-lg border border-ps-border hover:bg-ps-bg text-ps-label"
            title="Refresh"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <Link
            href="/pipeline"
            className="flex items-center gap-2 rounded-lg border border-ps-border px-4 py-2 text-sm font-medium text-ps-label hover:bg-ps-bg transition-colors"
          >
            <KanbanSquare size={15} />
            Pipeline
          </Link>
          <button
            onClick={() => setImportOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-ps-border px-4 py-2 text-sm font-medium text-ps-label hover:bg-ps-bg transition-colors"
          >
            <Upload size={15} />
            Import CSV
          </button>
          <button
            onClick={() => downloadCsv("clients.csv", toCsv(filtered, CLIENT_EXPORT_COLUMNS))}
            disabled={filtered.length === 0}
            className="flex items-center gap-2 rounded-lg border border-ps-border px-4 py-2 text-sm font-medium text-ps-label hover:bg-ps-bg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Download size={15} />
            Export
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
          >
            <Plus size={15} />
            Add Client
          </button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b border-ps-border">
        {FILTER_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => { setFilter(tab.id); setSearch(""); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              filter === tab.id
                ? "border-brand text-blue-600"
                : "border-transparent text-ps-label hover:text-ps-ink"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ps-hint" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by name, PAN, GSTIN, email, city…"
          className="w-full rounded-lg border border-ps-border pl-9 pr-4 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand-light"
        />
      </div>

      {/* Error */}
      {error && (
        <div role="alert" className="rounded-lg bg-state-problem-surface border border-state-problem-border px-4 py-3 text-sm text-state-problem">
          {error} —{" "}
          <button onClick={load} className="underline">retry</button>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <Card>
          <CardContent className="p-0 divide-y divide-ps-muted">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-6 py-4">
                <div className="w-10 h-10 rounded-full bg-ps-muted animate-pulse shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 bg-ps-muted rounded animate-pulse w-48" />
                  <div className="h-2.5 bg-ps-muted rounded animate-pulse w-32" />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!loading && !error && clients.length === 0 && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center mx-auto mb-4">
            {filter === "archived" ? <Archive size={24} className="text-gray-400" /> : <Plus size={24} className="text-blue-500" />}
          </div>
          <h3 className="text-base font-semibold text-ps-ink mb-1">
            {filter === "archived" ? "No archived clients" : "No clients yet"}
          </h3>
          <p className="text-sm text-ps-label mb-4">
            {filter === "archived" ? "Archived clients will appear here" : "Add your first client to get started"}
          </p>
          {filter === "active" && (
            <button
              onClick={openCreate}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark"
            >
              <Plus size={15} /> Add Client
            </button>
          )}
        </div>
      )}

      {/* No search results */}
      {!loading && !error && clients.length > 0 && filtered.length === 0 && (
        <div className="text-center py-10 text-sm text-ps-label">
          No clients match &ldquo;{search}&rdquo;
        </div>
      )}

      {/* Bulk select — Archive only (Manager+). Selection is over `filtered`. */}
      {!loading && filtered.length > 0 && canArchive && (
        <div className="flex items-center gap-2 px-1">
          <input
            type="checkbox"
            aria-label="Select all visible clients"
            checked={filtered.length > 0 && selected.size === filtered.length}
            ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < filtered.length; }}
            onChange={toggleSelectAll}
            className="h-3.5 w-3.5 rounded border-ps-border-strong"
          />
          <span className="text-3xs text-ps-hint">Select all visible</span>
        </div>
      )}

      {!loading && canArchive && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-light bg-brand-surface px-3 py-2 text-xs">
          <span className="font-semibold text-brand-dark">{selected.size} selected</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button
              onClick={bulkArchive}
              disabled={actionInFlight}
              className="inline-flex items-center gap-1.5 rounded-lg border border-brand-light bg-white px-2.5 py-1.5 font-medium text-brand hover:bg-ps-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Archive size={12} />
              {bulkBusy ? "Archiving…" : "Archive"}
            </button>
            <button onClick={clearSelection} disabled={bulkBusy} className="text-ps-label hover:text-brand disabled:opacity-50" aria-label="Clear selection">
              <X size={14} />
            </button>
          </div>
        </div>
      )}
      {!loading && canArchive && bulkError && <p className="text-xs text-red-600 px-1">{bulkError}</p>}
      {!loading && canArchive && bulkMessage && <p className="text-xs text-ps-label px-1">{bulkMessage}</p>}

      {/* Client list */}
      {!loading && filtered.length > 0 && (
        <Card>
          <CardContent className="p-0 divide-y divide-ps-muted">
            {filtered.map((c) => {
              const isArchived = c.status === "archived";
              return (
                <div
                  key={c.id}
                  className="relative flex items-center gap-4 px-6 py-4 hover:bg-ps-bg transition-colors group"
                >
                  {/* Full-row clickable link, behind buttons */}
                  <Link
                    href={`/clients/${c.id}`}
                    className="absolute inset-0"
                    aria-label={`Open ${c.client_name}`}
                  />

                  {/* Bulk-select checkbox — z-10 to sit above the full-row Link */}
                  {canArchive && (
                    <input
                      type="checkbox"
                      aria-label={`Select ${c.client_name}`}
                      checked={selected.has(c.id)}
                      onChange={() => toggleRow(c.id)}
                      className="relative z-10 h-3.5 w-3.5 rounded border-ps-border-strong shrink-0"
                    />
                  )}

                  {/* Avatar */}
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm shrink-0 ${
                    isArchived ? "bg-gray-100 text-gray-400" : "bg-blue-100 text-blue-700"
                  }`}>
                    {c.client_name[0]}
                  </div>

                  {/* Name + identifier */}
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-semibold ${isArchived ? "text-ps-hint" : "text-ps-ink"}`}>
                      {c.client_name}
                    </p>
                    <p className="text-xs text-ps-label font-mono mt-0.5">{c.gstin ?? c.pan}</p>
                  </div>

                  {/* Entity + PAN */}
                  <div className="text-right mr-2">
                    <p className="text-xs text-ps-label">{ENTITY_LABELS[c.entity_type] ?? c.entity_type}</p>
                    <p className="text-xs font-mono text-ps-label">{c.pan}</p>
                  </div>

                  {healthScores[c.id] !== undefined && (
                    <HealthBadgeLight score={healthScores[c.id]} />
                  )}

                  {(() => {
                    const p = payrollBadge(payrollStates[c.id]);
                    return p ? (
                      <Badge variant="secondary" className={`text-xs ${p.className}`} title={p.title}>
                        {p.label}
                      </Badge>
                    ) : null;
                  })()}

                  <Badge
                    variant="secondary"
                    className={`text-xs ${isArchived ? "bg-gray-100 text-gray-500" : "bg-green-100 text-green-700"}`}
                  >
                    {c.status}
                  </Badge>

                  {/* Edit button */}
                  <button
                    onClick={e => openEdit(e, c)}
                    className="relative z-10 p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-ps-muted text-ps-label transition-all"
                    title="Edit client"
                  >
                    <Pencil size={13} />
                  </button>

                  {/* Action dropdown */}
                  {hasActions && (
                    <div
                      className="relative z-10"
                      ref={menuOpenId === c.id ? menuRef : undefined}
                    >
                      <button
                        onClick={e => {
                          e.preventDefault();
                          e.stopPropagation();
                          setMenuOpenId(menuOpenId === c.id ? null : c.id);
                        }}
                        className="p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-ps-muted text-ps-label transition-all"
                        title="More actions"
                      >
                        <MoreVertical size={13} />
                      </button>

                      {menuOpenId === c.id && (
                        <div className="absolute right-0 top-8 bg-white rounded-lg shadow-lg border border-ps-border py-1 min-w-40">
                          {canArchive && !isArchived && (
                            <button
                              onClick={() => {
                                setMenuOpenId(null);
                                setArchiveTarget(c);
                                setActionError(null);
                              }}
                              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-ps-label hover:bg-ps-bg"
                            >
                              <Archive size={13} /> Archive
                            </button>
                          )}
                          {canArchive && isArchived && (
                            <button
                              onClick={() => {
                                setMenuOpenId(null);
                                setRestoreTarget(c);
                                setActionError(null);
                              }}
                              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-ps-label hover:bg-ps-bg"
                            >
                              <RotateCcw size={13} /> Restore
                            </button>
                          )}
                          {canDelete && (
                            <>
                              {canArchive && <div className="my-1 border-t border-ps-muted" />}
                              <button
                                onClick={() => {
                                  setMenuOpenId(null);
                                  setDeleteTarget(c);
                                  setDeleteConfirmName("");
                                  setDeleteBlockers(null);
                                  setActionError(null);
                                }}
                                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-state-problem-hover"
                              >
                                <Trash2 size={13} /> Permanent Delete
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <ChevronRight size={16} className="relative z-10 text-ps-hint group-hover:text-ps-label shrink-0" />
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* ── Archive modal ─────────────────────────────────────────────────── */}
      {archiveTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                <Archive size={16} className="text-amber-600" />
              </div>
              <h2 className="text-base font-semibold text-ps-ink">Archive Client</h2>
            </div>
            <p className="text-sm text-ps-label mb-1">
              Archive <span className="font-semibold">{archiveTarget.client_name}</span>?
            </p>
            <p className="text-sm text-ps-label mb-4">
              This client will be hidden from the active list. All data and history are preserved and can be restored at any time.
            </p>
            {actionError && <p className="text-sm text-red-600 mb-3">{actionError}</p>}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setArchiveTarget(null); setActionError(null); }}
                disabled={actionBusy}
                className="px-4 py-2 text-sm rounded-lg border border-ps-border text-ps-label hover:bg-ps-bg disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleArchive}
                disabled={actionInFlight}
                className="px-4 py-2 text-sm rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
              >
                {actionBusy ? "Archiving…" : "Archive"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Restore modal ─────────────────────────────────────────────────── */}
      {restoreTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-green-100 flex items-center justify-center shrink-0">
                <RotateCcw size={16} className="text-green-600" />
              </div>
              <h2 className="text-base font-semibold text-ps-ink">Restore Client</h2>
            </div>
            <p className="text-sm text-ps-label mb-4">
              Restore <span className="font-semibold">{restoreTarget.client_name}</span> to the active client list?
            </p>
            {actionError && <p className="text-sm text-red-600 mb-3">{actionError}</p>}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setRestoreTarget(null); setActionError(null); }}
                disabled={actionBusy}
                className="px-4 py-2 text-sm rounded-lg border border-ps-border text-ps-label hover:bg-ps-bg disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleRestore}
                disabled={actionInFlight}
                className="px-4 py-2 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
              >
                {actionBusy ? "Restoring…" : "Restore"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete modal ──────────────────────────────────────────────────── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 size={16} className="text-red-600" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-ps-ink">Permanently Delete</h2>
                <p className="text-xs font-medium text-red-600">This cannot be undone</p>
              </div>
            </div>

            {!deleteBlockers && (
              <>
                <p className="text-sm text-ps-label mb-3">
                  Permanently delete <span className="font-semibold">{deleteTarget.client_name}</span>? Consider archiving to preserve history instead.
                </p>
                <label className="block text-xs font-medium text-ps-label mb-1">
                  Type <span className="font-mono font-bold">{deleteTarget.client_name}</span> to confirm
                </label>
                <input
                  value={deleteConfirmName}
                  onChange={e => setDeleteConfirmName(e.target.value)}
                  placeholder={deleteTarget.client_name}
                  className="w-full rounded-lg border border-ps-border px-3 py-2 text-sm outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100 mb-4"
                />
                {actionError && <p className="text-sm text-red-600 mb-3">{actionError}</p>}
              </>
            )}

            {deleteBlockers && (
              <div className="mb-4 bg-state-attention-surface border border-state-attention-border rounded-lg p-3">
                <p className="text-xs font-semibold text-amber-800 mb-1">Cannot delete — linked records exist:</p>
                <ul className="text-xs text-state-attention list-disc list-inside space-y-0.5">
                  {deleteBlockers.map((b, i) => <li key={i}>{b}</li>)}
                </ul>
                <p className="text-xs font-medium text-amber-800 mt-2">Archive this client instead to preserve all history.</p>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setDeleteTarget(null);
                  setDeleteConfirmName("");
                  setDeleteBlockers(null);
                  setActionError(null);
                }}
                disabled={actionBusy}
                className="px-4 py-2 text-sm rounded-lg border border-ps-border text-ps-label hover:bg-ps-bg disabled:opacity-50"
              >
                {deleteBlockers ? "Close" : "Cancel"}
              </button>

              {deleteBlockers && canArchive && (
                <button
                  onClick={() => {
                    const target = deleteTarget;
                    setDeleteTarget(null);
                    setDeleteBlockers(null);
                    setDeleteConfirmName("");
                    setActionError(null);
                    setArchiveTarget(target);
                  }}
                  className="px-4 py-2 text-sm rounded-lg bg-amber-600 text-white hover:bg-amber-700"
                >
                  Archive Instead
                </button>
              )}

              {!deleteBlockers && (
                <button
                  onClick={handleDelete}
                  disabled={actionInFlight || deleteConfirmName !== deleteTarget.client_name}
                  className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-40"
                >
                  {actionBusy ? "Deleting…" : "Delete Permanently"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Form modal ────────────────────────────────────────────────────── */}
      <ClientFormModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); setEditClient(null); }}
        onSaved={handleSaved}
        editClient={editClient}
      />

      {importOpen && (
        <CsvImportModal
          title="Import Clients from CSV"
          columns={CLIENT_IMPORT_COLUMNS}
          templateFilename="practicesync-clients-template.xlsx"
          onClose={() => setImportOpen(false)}
          onImport={handleClientImport}
          validateRow={(row) => {
            const errs: string[] = [];
            const panIssue = row.pan?.trim() ? panProblem(row.pan) : "PAN is required. IT Act §139A — e.g. AABCU9603R.";
            if (panIssue) errs.push(panIssue);
            const gstinIssue = gstinProblem(row.gstin);
            if (gstinIssue) errs.push(gstinIssue);
            if (row.entity_type && !VALID_ENTITY_TYPES.includes(row.entity_type)) errs.push(`Invalid entity type`);
            return errs;
          }}
        />
      )}
    </div>
  );
}
