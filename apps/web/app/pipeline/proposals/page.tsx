"use client";

import { useState, useEffect } from "react";
import { Plus, X, Search, Filter } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ─── Types ───────────────────────────────────────────────────────────────────

type ProposalStatus = "Draft" | "Sent" | "Accepted" | "Rejected" | "Expired";

interface Proposal {
  id: string;
  proposal_no: string;
  title: string;
  lead_name: string;
  client_name: string;
  fee_paise: number;
  status: ProposalStatus;
  sent_date: string | null;
  created_at: string;
  updated_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const ALL_STATUSES: ProposalStatus[] = ["Draft", "Sent", "Accepted", "Rejected", "Expired"];

const STATUS_BADGE: Record<ProposalStatus, string> = {
  Draft:    "bg-gray-700 text-gray-300",
  Sent:     "bg-blue-800 text-blue-300",
  Accepted: "bg-green-800 text-green-300",
  Rejected: "bg-red-800 text-red-300",
  Expired:  "bg-orange-800 text-orange-300",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatRupees(paise: number): string {
  const rupees = Math.floor(paise / 100);
  return `₹${rupees.toLocaleString("en-IN")}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProposalStatus | "All">("All");
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    lead_name: "",
    fee_rupees: "",
  });

  useEffect(() => {
    loadProposals();
  }, []);

  async function loadProposals() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/pipeline/proposals");
      const json: ApiResponse<Proposal[]> = await res.json();
      if (!json.success) throw new Error(json.error ?? "Failed to load proposals");
      setProposals(json.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateProposal() {
    if (!form.title.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const feePaise = Math.round(parseFloat(form.fee_rupees || "0") * 100);
      const res = await fetch("/api/pipeline/proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.title.trim(),
          lead_name: form.lead_name.trim(),
          fee_paise: feePaise,
          status: "Draft",
        }),
      });
      const json: ApiResponse<Proposal> = await res.json();
      if (!json.success) throw new Error(json.error ?? "Failed to create proposal");
      setProposals((prev) => [json.data, ...prev]);
      setModalOpen(false);
      setForm({ title: "", lead_name: "", fee_rupees: "" });
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const filtered = proposals.filter((p) => {
    const matchStatus = statusFilter === "All" || p.status === statusFilter;
    const matchSearch =
      !search ||
      p.title.toLowerCase().includes(search.toLowerCase()) ||
      p.proposal_no.toLowerCase().includes(search.toLowerCase()) ||
      (p.lead_name || p.client_name || "").toLowerCase().includes(search.toLowerCase());
    return matchStatus && matchSearch;
  });

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-6 bg-white/[0.08] rounded w-48" />
        <div className="h-10 bg-white/[0.05] rounded" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-white/[0.05] rounded-xl" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-900/30 text-red-400 rounded-lg px-5 py-4 text-sm border border-red-800">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Proposals</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            {proposals.length} total · {proposals.filter((p) => p.status === "Accepted").length} accepted
          </p>
        </div>
        <button
          onClick={() => {
            setForm({ title: "", lead_name: "", fee_rupees: "" });
            setSaveError(null);
            setModalOpen(true);
          }}
          className="flex items-center gap-1.5 text-sm bg-violet-600 text-white px-3 py-1.5 rounded-md hover:bg-violet-700"
        >
          <Plus size={14} /> New Proposal
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search proposals…"
            className="w-full pl-8 pr-4 py-2 text-sm bg-gray-800 border border-gray-700 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
        </div>
        <div className="flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-md p-1">
          <Filter size={12} className="text-slate-500 ml-1" />
          {(["All", ...ALL_STATUSES] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s as ProposalStatus | "All")}
              className={`text-xs px-3 py-1 rounded transition-colors ${
                statusFilter === s
                  ? "bg-violet-600 text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card className="bg-gray-800 border-gray-700">
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-sm text-slate-500">No proposals found</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-gray-700">
                  <th className="px-5 py-3 text-left font-medium">Proposal No</th>
                  <th className="px-3 py-3 text-left font-medium">Title</th>
                  <th className="px-3 py-3 text-left font-medium">Lead / Client</th>
                  <th className="px-3 py-3 text-left font-medium">Fee</th>
                  <th className="px-3 py-3 text-left font-medium">Status</th>
                  <th className="px-3 py-3 text-left font-medium">Sent Date</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {filtered.map((proposal) => (
                  <tr key={proposal.id} className="hover:bg-gray-700/30 group">
                    <td className="px-5 py-3 font-mono text-xs text-slate-400">
                      {proposal.proposal_no}
                    </td>
                    <td className="px-3 py-3 text-white font-medium">
                      {proposal.title}
                    </td>
                    <td className="px-3 py-3 text-slate-300">
                      {proposal.lead_name || proposal.client_name || "—"}
                    </td>
                    <td className="px-3 py-3 text-emerald-400 font-medium">
                      {formatRupees(proposal.fee_paise)}
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-[11px] ${STATUS_BADGE[proposal.status]}`}>
                        {proposal.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-slate-400 text-xs">
                      {formatDate(proposal.sent_date)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button className="text-xs text-slate-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 rounded hover:bg-gray-700">
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* New Proposal Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-white">New Proposal</h2>
              <button onClick={() => setModalOpen(false)} className="text-slate-500 hover:text-white">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400 font-medium">Proposal Title *</label>
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  placeholder="e.g. GST Compliance Package — FY 2025-26"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 font-medium">Lead / Client Name</label>
                <input
                  value={form.lead_name}
                  onChange={(e) => setForm({ ...form, lead_name: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  placeholder="Company or contact name"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 font-medium">Fee (₹)</label>
                <input
                  type="number"
                  min="0"
                  step="500"
                  value={form.fee_rupees}
                  onChange={(e) => setForm({ ...form, fee_rupees: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  placeholder="e.g. 25000"
                />
              </div>
            </div>
            {saveError && (
              <p className="mt-3 text-xs text-red-400 bg-red-900/30 px-3 py-2 rounded-md border border-red-800">
                {saveError}
              </p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModalOpen(false)}
                className="flex-1 text-sm text-slate-400 border border-gray-700 py-2 rounded-md hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProposal}
                disabled={saving || !form.title.trim()}
                className="flex-1 text-sm bg-violet-600 text-white py-2 rounded-md hover:bg-violet-700 disabled:opacity-50"
              >
                {saving ? "Creating…" : "Create Proposal"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
