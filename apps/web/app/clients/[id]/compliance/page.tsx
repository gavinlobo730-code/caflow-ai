"use client";

import { useEffect, useState } from "react";
import { CheckCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getComplianceCalendar, updateFilingStatus, seedComplianceCalendar } from "@/lib/data/compliance";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

type ComplianceSubTab = "all" | "gst" | "tds" | "income_tax" | "mca";

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-gray-100 text-gray-500",
};

interface MarkFiledForm {
  id: string;
  arn: string;
}

export default function CompliancePage() {
  const { clientId } = useClientNav();
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [subTab, setSubTab] = useState<ComplianceSubTab>("all");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);

  const today = new Date().toISOString().split("T")[0];

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

  async function handleMarkFiled() {
    if (!markFiled) return;
    setFilingLoading(true);
    try {
      await updateFilingStatus(markFiled.id, "filed", markFiled.arn || undefined);
      setCompliance((prev) =>
        prev.map((c) =>
          c.id === markFiled.id ? { ...c, filing_status: "filed", arn_number: markFiled.arn || null } : c
        )
      );
      setMarkFiled(null);
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

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      {/* Sub-tab filter */}
      <div className="flex gap-0.5 bg-gray-50 rounded-lg p-1 w-fit">
        {(["all", "gst", "tds", "income_tax", "mca"] as ComplianceSubTab[]).map((id) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              subTab === id ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
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
                className="text-xs px-3 py-1.5 border border-gray-200 rounded-md hover:bg-gray-100"
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
          <CardContent><div className="h-32 animate-pulse bg-gray-50 rounded" /></CardContent>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400">
                  <th className="px-5 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-left font-semibold">Period</th>
                  <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-3 py-3 text-left font-semibold">ARN</th>
                  <th className="px-5 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3 text-sm font-medium text-gray-900">{c.compliance_type}</td>
                    <td className="px-3 py-3 text-xs text-gray-500">
                      {formatDate(c.period_start)} – {formatDate(c.period_end)}
                    </td>
                    <td
                      className={`px-3 py-3 text-xs whitespace-nowrap ${
                        c.due_date < today && c.filing_status !== "filed"
                          ? "text-red-600 font-medium"
                          : "text-gray-600"
                      }`}
                    >
                      {formatDate(c.due_date)}
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-gray-100 text-gray-600"}`}>
                        {c.filing_status}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500 font-mono">{c.arn_number ?? "—"}</td>
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
              <div className="text-center py-12 text-gray-400 text-sm">No compliance entries</div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
