"use client";

import { useEffect, useState, useCallback } from "react";
import { CheckCircle, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getComplianceCalendar, markFiled as markObligationFiled, seedComplianceCalendar } from "@/lib/data/compliance";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { getFirmId } from "@/lib/data/getFirmId";
import { getSupabaseClient } from "@/lib/supabase/client";
import { todayLocalISO } from "@/lib/dateMath";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

type ComplianceSubTab = "all" | "gst" | "tds" | "income_tax" | "mca";

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-[#F1F5F9] text-[#64748B]",
};

interface MarkFiledForm {
  id: string;
  arn: string;
}

// ── Notices Section ────────────────────────────────────────────────────────

function NoticesSection({ clientId }: { clientId: string }) {
  const [notices, setNotices] = useState<Record<string, unknown>[]>([]);
  const [showExtract, setShowExtract] = useState(false);
  const [noticeText, setNoticeText] = useState("");
  const [extracting, setExtracting] = useState(false);

  const loadNotices = useCallback(() => {
    apiFetch(`/api/document-intelligence-v2/notices?client_id=${clientId}`)
      .then((r) => setNotices(r.success ? r.data : []));
  }, [clientId]);

  useEffect(() => { loadNotices(); }, [loadNotices]);

  async function extract() {
    setExtracting(true);
    await apiFetch("/api/document-intelligence-v2/notices/extract", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, document_text: noticeText }),
    });
    setShowExtract(false);
    setNoticeText("");
    setExtracting(false);
    loadNotices();
  }

  async function approveNotice(id: string) {
    await apiFetch(`/api/document-intelligence-v2/notices/${id}/approve`, { method: "POST" });
    loadNotices();
  }

  const STATUS_COLORS: Record<string, string> = {
    open: "bg-red-100 text-red-700",
    in_progress: "bg-blue-100 text-blue-700",
    responded: "bg-green-100 text-green-700",
    closed: "bg-[#F1F5F9] text-[#64748B]",
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex justify-between items-center">
          <CardTitle className="text-sm">Government Notices ({notices.length})</CardTitle>
          <button onClick={() => setShowExtract(!showExtract)}
            className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + Extract Notice
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {showExtract && (
          <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
            <p className="text-xs font-medium text-amber-700">⚠ CA Review Required — AI extraction only. CA must approve before action.</p>
            <textarea placeholder="Paste government notice text here…"
              value={noticeText} onChange={(e) => setNoticeText(e.target.value)}
              rows={6} className="w-full border rounded px-3 py-2 text-sm" />
            <div className="flex gap-2">
              <button onClick={extract} disabled={extracting || !noticeText}
                className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
                {extracting ? "Extracting…" : "Extract"}
              </button>
              <button onClick={() => setShowExtract(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
            </div>
          </div>
        )}
        {notices.length === 0 ? (
          <p className="text-sm text-[#94A3B8] text-center py-4">No government notices extracted yet.</p>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-[#F8FAFC] text-left text-xs">
                <th className="px-3 py-2 border-b">Authority</th>
                <th className="px-3 py-2 border-b">Type</th>
                <th className="px-3 py-2 border-b">Reference</th>
                <th className="px-3 py-2 border-b">Response Due</th>
                <th className="px-3 py-2 border-b">Status</th>
                <th className="px-3 py-2 border-b">CA Approved</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.id as string} className="border-b hover:bg-[#F8FAFC]">
                  <td className="px-3 py-2 font-medium text-xs">{n.authority as string}</td>
                  <td className="px-3 py-2 text-xs">{(n.notice_type as string)?.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-xs font-mono">{n.reference_no as string ?? "—"}</td>
                  <td className="px-3 py-2 text-xs">{n.response_due_date as string ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[n.status as string] ?? ""}`}>
                      {n.status as string}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {n.ca_approved ? (
                      <span className="text-xs text-green-700">✓ Approved</span>
                    ) : (
                      <button onClick={() => approveNotice(n.id as string)}
                        className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">
                        CA Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

export default function CompliancePage() {
  const router = useRouter();
  const { clientId, financialYear } = useClientNav();
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [subTab, setSubTab] = useState<ComplianceSubTab>("all");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const today = todayLocalISO();

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      setLoading(true);
      try {
        let comp = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        if (comp.length === 0) {
          await seedComplianceCalendar(clientId).catch(() => undefined);
          comp = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        }
        setCompliance(comp);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [clientId]);

  useEffect(() => { setSelected(new Set()); }, [subTab]);

  async function reloadCompliance() {
    if (!clientId || clientId === "_placeholder") return;
    const comp = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
    setCompliance(comp);
  }

  async function handleMarkFiled() {
    if (!markFiled) return;
    setFilingLoading(true);
    try {
      const entry = compliance.find((c) => c.id === markFiled.id);
      await markObligationFiled(markFiled.id, markFiled.arn || undefined);
      setCompliance((prev) =>
        prev.map((c) =>
          c.id === markFiled.id ? { ...c, filing_status: "filed", arn_number: markFiled.arn || undefined } : c
        )
      );
      setMarkFiled(null);

      // Emit timeline event
      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({
          client_id: clientId,
          firm_id: firmId,
          financial_year: financialYear,
          category: "compliance",
          event_type: "filing_marked_filed",
          severity: "success",
          title: `${entry?.compliance_type ?? "Filing"} marked as filed`,
          description: markFiled.arn ? `ARN: ${markFiled.arn}` : undefined,
          entity_type: "compliance_record",
          entity_id: markFiled.id,
          actor_type: "user",
        });
      } catch { /* timeline is non-blocking */ }
    } finally {
      setFilingLoading(false);
    }
  }

  const filtered = compliance.filter((c) => {
    if (subTab === "all") return true;
    if (subTab === "gst") return /GSTR/i.test(c.compliance_type);
    if (subTab === "tds") return /TDS|24Q|26Q/i.test(c.compliance_type);
    if (subTab === "income_tax") return /ITR|ADVANCE_TAX/i.test(c.compliance_type);
    if (subTab === "mca") return /MCA|ROC|DIR/i.test(c.compliance_type);
    return true;
  });

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
  }
  async function bulkMarkFiled() {
    if (selected.size === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    const ids = Array.from(selected);
    const results = await Promise.all(
      ids.map(async (id) => {
        const entry = compliance.find((c) => c.id === id);
        if (entry?.filing_status === "filed") return "skipped" as const;
        try {
          await markObligationFiled(id);
          return "success" as const;
        } catch (e) {
          return e instanceof Error ? e.message : "Failed";
        }
      })
    );
    const successCount = results.filter((r) => r === "success").length;
    const skipCount = results.filter((r) => r === "skipped").length;
    const failCount = results.length - successCount - skipCount;

    if (successCount > 0) {
      await reloadCompliance();
    }
    setBulkBusy(false);

    if (failCount > 0) {
      setBulkError(
        `Failed to mark ${failCount} of ${ids.length} filing${ids.length === 1 ? "" : "s"} as filed.` +
          (skipCount > 0 ? ` ${skipCount} already filed (skipped).` : "")
      );
    } else {
      clearSelection();
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      {/* Workspace Navigation Cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "GST Workspace", desc: "GSTR-1, GSTR-3B, 2B Reconciliation", path: "gst", color: "bg-green-50 border-green-200 hover:bg-green-100" },
          { label: "TDS Workspace", desc: "Challans, Returns, 26AS Reconciliation", path: "tds", color: "bg-blue-50 border-blue-200 hover:bg-blue-100" },
          { label: "MCA Workspace", desc: "Company Master, Directors, Filings", path: "mca", color: "bg-purple-50 border-purple-200 hover:bg-purple-100" },
        ].map(({ label, desc, path, color }) => (
          <button key={path}
            onClick={() => router.push(`/clients/${clientId}/compliance/${path}`)}
            className={`border rounded-lg p-4 text-left transition-colors ${color}`}>
            <p className="font-semibold text-sm">{label}</p>
            <p className="text-xs text-[#64748B] mt-1">{desc}</p>
          </button>
        ))}
      </div>

      {/* Government Notices */}
      {clientId && clientId !== "_placeholder" && <NoticesSection clientId={clientId} />}

      {/* Sub-tab filter */}
      <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
        {(["all", "gst", "tds", "income_tax", "mca"] as ComplianceSubTab[]).map((id) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              subTab === id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {id === "income_tax" ? "Income Tax" : id.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Mark as Filed inline form */}
      {markFiled && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="pt-4 pb-4">
            <p className="text-sm font-medium text-blue-900 mb-3">Mark as Filed</p>
            <div className="flex gap-3 items-center">
              <input
                value={markFiled.arn}
                onChange={(e) => setMarkFiled({ ...markFiled, arn: e.target.value })}
                placeholder="ARN Number (optional)"
                className="flex-1 px-3 py-1.5 text-sm border border-blue-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
              <button
                onClick={handleMarkFiled}
                disabled={filingLoading}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {filingLoading ? "Saving…" : "Confirm Filed"}
              </button>
              <button
                onClick={() => setMarkFiled(null)}
                className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-md hover:bg-[#F1F5F9]"
              >
                Cancel
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            Compliance Calendar ({loading ? "…" : `${filtered.length} deadlines`})
          </CardTitle>
        </CardHeader>
        {loading ? (
          <CardContent><div className="h-32 animate-pulse bg-[#F8FAFC] rounded" /></CardContent>
        ) : (
          <>
            {selected.size > 0 && (
              <div className="mx-5 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-[#C7D2FE] bg-[#EEF2FF] px-3 py-2 text-xs">
                <span className="font-semibold text-[#3730A3]">{selected.size} selected</span>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <button
                    onClick={bulkMarkFiled}
                    disabled={bulkBusy}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2FE] bg-white px-2.5 py-1.5 font-medium text-[#4338CA] hover:bg-[#E0E7FF] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {bulkBusy ? "Marking…" : "Mark Filed"}
                  </button>
                  <button onClick={clearSelection} disabled={bulkBusy} className="text-[#6366F1] hover:text-[#4338CA] disabled:opacity-50" aria-label="Clear selection">
                    <X size={14} />
                  </button>
                </div>
              </div>
            )}
            {bulkError && <p className="mx-5 mt-2 text-[11px] text-red-600">{bulkError}</p>}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                  <th className="px-5 py-3 text-left font-semibold w-8">
                    <input
                      type="checkbox"
                      aria-label="Select all visible compliance obligations"
                      checked={filtered.length > 0 && selected.size === filtered.length}
                      ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < filtered.length; }}
                      onChange={toggleSelectAll}
                      className="h-3.5 w-3.5 rounded border-[#CBD5E1]"
                    />
                  </th>
                  <th className="px-3 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-left font-semibold">Period</th>
                  <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-3 py-3 text-left font-semibold">ARN</th>
                  <th className="px-5 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {filtered.map((c) => (
                  <tr key={c.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-5 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${c.compliance_type} filing`}
                        checked={selected.has(c.id)}
                        onChange={() => toggleRow(c.id)}
                        className="h-3.5 w-3.5 rounded border-[#CBD5E1]"
                      />
                    </td>
                    <td className="px-3 py-3 text-sm font-medium text-[#0F172A]">{c.compliance_type}</td>
                    <td className="px-3 py-3 text-xs text-[#64748B]">
                      {formatDate(c.period_start)} – {formatDate(c.period_end)}
                    </td>
                    <td
                      className={`px-3 py-3 text-xs whitespace-nowrap ${
                        c.due_date < today && c.filing_status !== "filed"
                          ? "text-red-600 font-medium"
                          : "text-[#475569]"
                      }`}
                    >
                      {formatDate(c.due_date)}
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                        {c.filing_status}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-xs text-[#64748B] font-mono">{c.arn_number ?? "—"}</td>
                    <td className="px-5 py-3">
                      {c.filing_status !== "filed" && (
                        <button
                          onClick={() => setMarkFiled({ id: c.id, arn: c.arn_number ?? "" })}
                          className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                        >
                          <CheckCircle size={12} /> Mark Filed
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="text-center py-12 text-[#94A3B8] text-sm">No compliance entries</div>
            )}
          </div>
          </>
        )}
      </Card>
    </div>
  );
}
