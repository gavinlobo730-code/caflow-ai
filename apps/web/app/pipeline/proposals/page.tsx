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
  Draft:    "bg-gray-100 text-gray-600",
  Sent:     "bg-blue-100 text-blue-700",
  Accepted: "bg-green-100 text-green-700",
  Rejected: "bg-red-100 text-red-700",
  Expired:  "bg-orange-100 text-orange-700",
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
      <div className="p-6 space-y-4 animate-pulse bg-[#F8FAFC] min-h-full">
        <div className="h-6 bg-gray-200 rounded w-48" />
        <div className="h-10 bg-gray-100 rounded" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-gray-100 rounded-xl" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-[#F8FAFC] min-h-full">
        <div className="bg-red-50 text-red-600 rounded-lg px-5 py-4 text-sm border border-red-200">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#182350]">Proposals</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {proposals.length} total · {proposals.filter((p) => p.status === "Accepted").length} accepted
          </p>
        </div>
        <button
          onClick={() => {
            setForm({ title: "", lead_name: "", fee_rupees: "" });
            setSaveError(null);
            setModalOpen(true);
          }}
          className="flex items-center gap-1.5 text-sm bg-[#182350] text-white px-3 py-1.5 rounded-md hover:bg-[#0D1635]"
        >
          <Plus size={14} /> New Proposal
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search proposals…"
            className="w-full pl-8 pr-4 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
          />
        </div>
        <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-md p-1">
          <Filter size={12} className="text-gray-400 ml-1" />
          {(["All", ...ALL_STATUSES] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s as ProposalStatus | "All")}
              className={`text-xs px-3 py-1 rounded transition-colors ${
                statusFilter === s
                  ? "bg-[#182350] text-white"
                  : "text-gray-500 hover:text-[#182350]"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card className="bg-white border-gray-200 shadow-sm">
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-sm text-gray-500">No proposals found</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-gray-200">
                  <th className="px-5 py-3 text-left font-medium">Proposal No</th>
                  <th className="px-3 py-3 text-left font-medium">Title</th>
                  <th className="px-3 py-3 text-left font-medium">Lead / Client</th>
                  <th className="px-3 py-3 text-left font-medium">Fee</th>
                  <th className="px-3 py-3 text-left font-medium">Status</th>
                  <th className="px-3 py-3 text-left font-medium">Sent Date</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((proposal) => (
                  <tr key={proposal.id} className="hover:bg-[#AFD2FA]/10 group">
                    <td className="px-5 py-3 font-mono text-xs text-gray-500">
                      {proposal.proposal_no}
                    </td>
                    <td className="px-3 py-3 text-gray-800 font-medium">
                      {proposal.title}
                    </td>
                    <td className="px-3 py-3 text-gray-700">
                      {proposal.lead_name || proposal.client_name || "—"}
                    </td>
                    <td className="px-3 py-3 text-emerald-700 font-medium">
                      {formatRupees(proposal.fee_paise)}
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-[11px] ${STATUS_BADGE[proposal.status]}`}>
                        {proposal.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-gray-500 text-xs">
                      {formatDate(proposal.sent_date)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button className="text-xs text-gray-500 hover:text-[#182350] opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 rounded hover:bg-gray-100">
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
        <div className="fixed inset-0 bg-[#182350]/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">New Proposal</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-700">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600 font-medium">Proposal Title *</label>
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                  placeholder="e.g. GST Compliance Package — FY 2025-26"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Lead / Client Name</label>
                <input
                  value={form.lead_name}
                  onChange={(e) => setForm({ ...form, lead_name: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                  placeholder="Company or contact name"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Fee (₹)</label>
                <input
                  type="number"
                  min="0"
                  step="500"
                  value={form.fee_rupees}
                  onChange={(e) => setForm({ ...form, fee_rupees: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                  placeholder="e.g. 25000"
                />
              </div>
            </div>
            {saveError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md border border-red-200">
                {saveError}
              </p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModalOpen(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-300 py-2 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProposal}
                disabled={saving || !form.title.trim()}
                className="flex-1 text-sm bg-[#182350] text-white py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
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
