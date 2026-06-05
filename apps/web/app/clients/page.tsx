"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { ChevronRight, Plus, Search, RefreshCw, Pencil, KanbanSquare, Upload } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClientFormModal } from "@/components/ClientFormModal";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

const CLIENT_IMPORT_COLUMNS = [
  { key: "client_name",  label: "Client Name",    required: true,  hint: "e.g. ABC Pvt Ltd" },
  { key: "entity_type",  label: "Entity Type",    required: true,  hint: "Proprietorship | Partnership | LLP | Private Limited | Public Limited | Trust | Society | Individual" },
  { key: "pan",          label: "PAN",            required: true,  hint: "e.g. AABCU9603R — 10 chars" },
  { key: "gstin",        label: "GSTIN",          required: false, hint: "e.g. 27AABCU9603R1ZX — 15 chars" },
  { key: "mobile",       label: "Mobile",         required: false, hint: "e.g. 9876543210" },
  { key: "email",        label: "Email",          required: false, hint: "e.g. client@example.com" },
  { key: "city",         label: "City",           required: false, hint: "e.g. Mumbai" },
  { key: "state",        label: "State",          required: false, hint: "e.g. Maharashtra" },
  { key: "pincode",      label: "Pincode",        required: false, hint: "6-digit" },
  { key: "gst_filing_frequency", label: "GST Frequency", required: false, hint: "monthly | quarterly" },
];

const VALID_ENTITY_TYPES = ["Proprietorship","Partnership","LLP","Private Limited","Public Limited","Trust","Society","Individual"];
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

const ENTITY_LABELS: Record<string, string> = {
  Proprietorship: "Prop.", Partnership: "Partner.", LLP: "LLP",
  "Private Limited": "Pvt Ltd", "Public Limited": "Pub Ltd",
  Trust: "Trust", Society: "Society", Individual: "Individual",
};

export default function ClientsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [filtered, setFiltered] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editClient, setEditClient] = useState<Client | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getClients();
      setClients(data);
      setFiltered(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load clients");
    } finally {
      setLoading(false);
    }
  }, []);

  // Wait for Supabase session to be restored before fetching.
  // Without this, the query fires before auth.uid() is available,
  // get_my_firm_id() returns NULL, and RLS filters out all rows.
  useEffect(() => {
    const sb = getSupabaseClient();
    // getSession() resolves once the session is restored from storage.
    sb.auth.getSession().then(({ data }) => {
      if (data.session) {
        load();
      } else {
        // No session — clear loading state
        setLoading(false);
      }
    });

    // Also reload whenever the user signs in mid-session
    const { data: { subscription } } = sb.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_IN") load();
    });
    return () => subscription.unsubscribe();
  }, [load]);

  useEffect(() => {
    const q = search.toLowerCase();
    setFiltered(
      clients.filter(c =>
        c.client_name.toLowerCase().includes(q) ||
        c.pan.toLowerCase().includes(q) ||
        (c.gstin?.toLowerCase().includes(q) ?? false) ||
        (c.city?.toLowerCase().includes(q) ?? false)
      )
    );
  }, [search, clients]);

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

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Clients</h1>
          <p className="text-gray-500 text-sm mt-1">
            {loading ? "Loading…" : `${filtered.length} client${filtered.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500"
            title="Refresh"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <Link
            href="/pipeline"
            className="flex items-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <KanbanSquare size={15} />
            Pipeline
          </Link>
          <button
            onClick={() => setImportOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <Upload size={15} />
            Import CSV
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <Plus size={15} />
            Add Client
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by name, PAN, GSTIN, city…"
          className="w-full rounded-lg border border-gray-200 pl-9 pr-4 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error} —{" "}
          <button onClick={load} className="underline">retry</button>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <Card>
          <CardContent className="p-0 divide-y divide-gray-100">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-6 py-4">
                <div className="w-10 h-10 rounded-full bg-gray-100 animate-pulse shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 bg-gray-100 rounded animate-pulse w-48" />
                  <div className="h-2.5 bg-gray-100 rounded animate-pulse w-32" />
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
            <Plus size={24} className="text-blue-500" />
          </div>
          <h3 className="text-base font-semibold text-gray-900 mb-1">No clients yet</h3>
          <p className="text-sm text-gray-500 mb-4">Add your first client to get started</p>
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={15} /> Add Client
          </button>
        </div>
      )}

      {/* No search results */}
      {!loading && !error && clients.length > 0 && filtered.length === 0 && (
        <div className="text-center py-10 text-sm text-gray-500">
          No clients match &ldquo;{search}&rdquo;
        </div>
      )}

      {/* Client list */}
      {!loading && filtered.length > 0 && (
        <Card>
          <CardContent className="p-0 divide-y divide-gray-100">
            {filtered.map((c) => (
              <Link
                key={c.id}
                href={`/clients/${c.id}`}
                className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors group"
              >
                <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-sm shrink-0">
                  {c.client_name[0]}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900">{c.client_name}</p>
                  <p className="text-xs text-gray-500 font-mono mt-0.5">
                    {c.gstin ?? c.pan}
                  </p>
                </div>
                <div className="text-right mr-2">
                  <p className="text-xs text-gray-500">{ENTITY_LABELS[c.entity_type] ?? c.entity_type}</p>
                  <p className="text-xs font-mono text-gray-600">{c.pan}</p>
                </div>
                <Badge variant="secondary" className="bg-green-100 text-green-700 text-xs">
                  {c.status}
                </Badge>
                <button
                  onClick={e => openEdit(e, c)}
                  className="p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-gray-200 text-gray-500 transition-all"
                  title="Edit client"
                >
                  <Pencil size={13} />
                </button>
                <ChevronRight size={16} className="text-gray-400 group-hover:text-gray-600 shrink-0" />
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Modal */}
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
            if (!PAN_RE.test(row.pan?.toUpperCase() ?? "")) errs.push("Invalid PAN format (AABCU9603R)");
            if (row.gstin && !GSTIN_RE.test(row.gstin.toUpperCase())) errs.push("Invalid GSTIN format");
            if (row.entity_type && !VALID_ENTITY_TYPES.includes(row.entity_type)) errs.push(`Invalid entity type`);
            return errs;
          }}
        />
      )}
    </div>
  );
}
