"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  CheckCircle2, XCircle, Clock, AlertTriangle, ChevronLeft,
  Building2, RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";

interface Approval {
  id: string;
  instance_id: string;
  firm_id: string;
  step_name?: string;
  approver_role: string;
  status: string;
  title: string;
  description?: string;
  context_data: Record<string, unknown>;
  due_at?: string;
  escalation_at?: string;
  escalated_to?: string;
  responded_at?: string;
  response_notes?: string;
  created_at: string;
  template_name?: string;
  client_name?: string;
  client_id?: string;
}

function fmtDate(s?: string) {
  if (!s) return "—";
  return new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function isOverdue(due?: string) {
  if (!due) return false;
  return new Date(due) < new Date();
}

// Backend hard-caps this endpoint at 200 (routers/workflow_builder.py list_approvals,
// `le=200`) — request the max allowed and detect if we still hit it.
const APPROVALS_FETCH_LIMIT = 200;

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalsCapped, setApprovalsCapped] = useState(false);
  const [status, setStatus] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [responding, setResponding] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: String(APPROVALS_FETCH_LIMIT) };
      if (status !== "all") params.status = status;
      const res = (await api.workflowEngine.listApprovals(params)) as { data: { approvals: Approval[] } };
      const rows = res.data?.approvals || [];
      setApprovals(rows);
      setApprovalsCapped(rows.length === APPROVALS_FETCH_LIMIT);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const respond = async (id: string, decision: "approved" | "rejected") => {
    setResponding(id);
    try {
      await api.workflowEngine.respondApproval(id, { decision, response_notes: notes[id] || undefined });
      await load();
    } finally {
      setResponding(null);
    }
  };

  const pendingCount = approvals.filter((a: Approval) => a.status === "pending").length;
  const overdueCount = approvals.filter((a: Approval) => a.status === "pending" && isOverdue(a.due_at)).length;

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 py-4">
        <div className="flex items-center gap-3">
          <Link href="/workflows" className="text-[#64748B] hover:text-[#182350] transition-colors">
            <ChevronLeft size={18} />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-[#182350]">Workflow Approvals</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Review and respond to pending workflow approval requests</p>
          </div>
          {pendingCount > 0 && (
            <span className="ml-2 bg-orange-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
              {pendingCount}
            </span>
          )}
        </div>
      </div>

      <div className="px-6 py-6 max-w-4xl mx-auto space-y-6">

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-4">
            <p className="text-xs text-[#64748B] uppercase tracking-wide font-medium">Pending</p>
            <p className="text-2xl font-bold text-orange-600 mt-1">{pendingCount}</p>
          </div>
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-4">
            <p className="text-xs text-[#64748B] uppercase tracking-wide font-medium">Overdue</p>
            <p className="text-2xl font-bold text-red-600 mt-1">{overdueCount}</p>
          </div>
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-4">
            <p className="text-xs text-[#64748B] uppercase tracking-wide font-medium">All Today</p>
            <p className="text-2xl font-bold text-[#182350] mt-1">{approvals.length}{approvalsCapped ? "+" : ""}</p>
          </div>
        </div>

        {/* Filter */}
        <div className="flex items-center gap-3">
          <select
            value={status}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value)}
            className="px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white"
          >
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="escalated">Escalated</option>
            <option value="all">All</option>
          </select>
          <button onClick={load} className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#182350]">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>

        {/* Approvals list */}
        {loading ? (
          <div className="text-center py-16 text-[#94A3B8]">Loading approvals...</div>
        ) : approvals.length === 0 ? (
          <div className="text-center py-16">
            <CheckCircle2 size={40} className="mx-auto text-green-300 mb-3" />
            <p className="text-[#64748B]">No {status === "all" ? "" : status} approvals</p>
          </div>
        ) : (
          <div className="space-y-4">
            {approvals.map((approval: Approval) => {
              const overdue = approval.status === "pending" && isOverdue(approval.due_at);
              return (
                <div
                  key={approval.id}
                  className={`bg-white border rounded-xl p-5 ${
                    overdue ? "border-red-200 bg-red-50/30" : "border-[#E2E8F0]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        {overdue && (
                          <span className="flex items-center gap-1 text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                            <AlertTriangle size={10} /> Overdue
                          </span>
                        )}
                        <span className="text-xs bg-[#EFF6FF] text-[#182350] px-2 py-0.5 rounded-full font-medium">
                          {approval.approver_role}
                        </span>
                        {approval.template_name && (
                          <span className="text-xs text-[#94A3B8]">via {approval.template_name}</span>
                        )}
                      </div>

                      <h3 className="font-semibold text-[#182350] text-sm">{approval.title}</h3>
                      {approval.description && (
                        <p className="text-xs text-[#64748B] mt-1">{approval.description}</p>
                      )}

                      {typeof approval.context_data?.client_name === "string" && (
                        <div className="flex items-center gap-1 mt-2 text-xs text-[#475569]">
                          <Building2 size={11} />
                          <span>{approval.context_data.client_name}</span>
                        </div>
                      )}

                      <div className="flex items-center gap-4 mt-2 text-xs text-[#94A3B8]">
                        <span className="flex items-center gap-1">
                          <Clock size={10} />
                          Due: <strong className={overdue ? "text-red-600" : "text-[#475569]"}>{fmtDate(approval.due_at)}</strong>
                        </span>
                        <span>Created: {fmtDate(approval.created_at)}</span>
                      </div>
                    </div>

                    {/* Status badge */}
                    <div className="flex-shrink-0">
                      {approval.status === "approved" && (
                        <span className="flex items-center gap-1 text-xs bg-green-100 text-green-700 px-3 py-1.5 rounded-lg font-medium">
                          <CheckCircle2 size={12} /> Approved
                        </span>
                      )}
                      {approval.status === "rejected" && (
                        <span className="flex items-center gap-1 text-xs bg-red-100 text-red-700 px-3 py-1.5 rounded-lg font-medium">
                          <XCircle size={12} /> Rejected
                        </span>
                      )}
                      {approval.status === "escalated" && (
                        <span className="flex items-center gap-1 text-xs bg-orange-100 text-orange-700 px-3 py-1.5 rounded-lg font-medium">
                          <AlertTriangle size={12} /> Escalated
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Response section for pending */}
                  {approval.status === "pending" && (
                    <div className="mt-4 pt-4 border-t border-[#F1F5F9]">
                      <textarea
                        placeholder="Optional notes..."
                        value={notes[approval.id] || ""}
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setNotes((prev: Record<string, string>) => ({ ...prev, [approval.id]: e.target.value }))}
                        rows={2}
                        className="w-full px-3 py-2 text-xs border border-[#E2E8F0] rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[#182350]/20 mb-3"
                      />
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => respond(approval.id, "approved")}
                          disabled={responding === approval.id}
                          className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          <CheckCircle2 size={12} />
                          {responding === approval.id ? "Processing..." : "Approve"}
                        </button>
                        <button
                          onClick={() => respond(approval.id, "rejected")}
                          disabled={responding === approval.id}
                          className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-50"
                        >
                          <XCircle size={12} />
                          Reject
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Show response for completed */}
                  {approval.status !== "pending" && approval.response_notes && (
                    <div className="mt-3 pt-3 border-t border-[#F1F5F9] text-xs text-[#64748B]">
                      <strong>Notes:</strong> {approval.response_notes}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
