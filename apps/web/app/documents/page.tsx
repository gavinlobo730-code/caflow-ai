"use client";

import { useState, useEffect, useCallback } from "react";
import { FileText, AlertTriangle, Clock, CheckCircle, XCircle, Zap, Search } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DocumentWithIntelligence, DocumentStats, InsightSeverity } from "@/lib/types";
import { formatRelativeTime } from "@/lib/services/formatting";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const severityBadge: Record<InsightSeverity, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-green-100 text-green-700",
  info: "bg-gray-100 text-gray-600",
};

const reviewBadge: Record<string, string> = {
  pending_review: "bg-amber-100 text-amber-700",
  approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-24 bg-gray-100 rounded-xl" />
        ))}
      </div>
      <div className="h-8 bg-gray-100 rounded w-full" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-12 bg-gray-50 rounded" />
      ))}
    </div>
  );
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentWithIntelligence[]>([]);
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState<Record<string, boolean>>({});

  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [filterRisk, setFilterRisk] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docsRes, statsRes] = await Promise.all([
        fetch(`${BASE_URL}/api/document-intelligence/documents`).then((r) => r.json()),
        fetch(`${BASE_URL}/api/document-intelligence/stats`).then((r) => r.json()),
      ]);
      if (docsRes.success) setDocs(docsRes.data ?? []);
      if (statsRes.success) setStats(statsRes.data);
    } catch {
      setError("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function triggerExtraction(docId: string) {
    setExtracting((prev) => ({ ...prev, [docId]: true }));
    try {
      await fetch(`${BASE_URL}/api/document-intelligence/${docId}/extract`, { method: "POST" });
      await loadData();
    } finally {
      setExtracting((prev) => ({ ...prev, [docId]: false }));
    }
  }

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-5 py-4 flex items-center justify-between">
          <span className="text-sm">{error}</span>
          <button onClick={loadData} className="text-xs underline hover:no-underline">Retry</button>
        </div>
      </div>
    );
  }

  const filtered = docs.filter((d) => {
    const q = search.toLowerCase();
    if (q && !d.file_name.toLowerCase().includes(q) && !(d.client_name ?? "").toLowerCase().includes(q)) return false;
    if (filterType !== "all" && d.document_type !== filterType) return false;
    if (filterRisk !== "all" && (d.risk_level ?? "none") !== filterRisk) return false;
    if (filterStatus !== "all" && d.review_status !== filterStatus) return false;
    return true;
  });

  const s = stats ?? { total: 0, pending_review: 0, processing: 0, high_risk: 0, extraction_failures: 0 };

  const STAT_CARDS = [
    { label: "Total Documents", value: s.total, icon: FileText, color: "text-blue-600", bg: "bg-blue-50" },
    { label: "Pending Review", value: s.pending_review, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Processing", value: s.processing, icon: Zap, color: "text-purple-600", bg: "bg-purple-50", pulse: true },
    { label: "High Risk", value: s.high_risk, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "Failed Extractions", value: s.extraction_failures, icon: XCircle, color: "text-gray-600", bg: "bg-gray-100" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Document Intelligence</h1>
          <p className="text-sm text-gray-500 mt-1">AI-powered extraction and risk analysis</p>
        </div>
        <Badge variant="outline" className="text-blue-700 border-blue-200 bg-blue-50 px-3 py-1">
          {docs.length} documents
        </Badge>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {STAT_CARDS.map((card) => (
          <Card key={card.label}>
            <CardContent className="pt-5 pb-4">
              <div className={`w-9 h-9 rounded-lg ${card.bg} flex items-center justify-center mb-3`}>
                <card.icon className={`${card.color}${card.pulse ? " animate-pulse" : ""}`} size={18} />
              </div>
              <p className="text-2xl font-bold text-gray-900">{card.value}</p>
              <p className="text-xs text-gray-500 mt-0.5 leading-tight">{card.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search documents or clients…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Types</option>
          <option value="FORM16">FORM16</option>
          <option value="GST_INVOICE">GST Invoice</option>
          <option value="BANK_STATEMENT">Bank Statement</option>
          <option value="AIS">AIS</option>
          <option value="FORM26AS">FORM26AS</option>
          <option value="TDS_CERTIFICATE">TDS Certificate</option>
          <option value="OTHER">Other</option>
        </select>

        <select
          value={filterRisk}
          onChange={(e) => setFilterRisk(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Risk Levels</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="none">None</option>
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Statuses</option>
          <option value="pending_review">Pending Review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {/* Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText size={15} />
            Documents ({filtered.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Document</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Client</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Type</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Uploaded</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Status</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Confidence</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Risk</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center text-gray-400 py-10 text-sm">
                      No documents found
                    </td>
                  </tr>
                ) : (
                  filtered.map((doc) => (
                    <tr key={doc.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <p className="font-medium text-gray-900 truncate max-w-[200px]" title={doc.file_name}>
                          {doc.file_name}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-sm">{doc.client_name ?? "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className="text-xs">{doc.document_type}</Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{formatRelativeTime(doc.upload_date)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${reviewBadge[doc.review_status] ?? "bg-gray-100 text-gray-600"}`}>
                          {doc.review_status === "pending_review" ? "Pending" : doc.review_status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {doc.confidence_score != null ? `${Math.round(doc.confidence_score * 100)}%` : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {doc.risk_level ? (
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${severityBadge[doc.risk_level]}`}>
                            {doc.risk_level}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">None</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => triggerExtraction(doc.id)}
                          disabled={extracting[doc.id]}
                          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                        >
                          <Zap size={11} className={extracting[doc.id] ? "animate-pulse" : ""} />
                          {extracting[doc.id] ? "Extracting…" : "Extract"}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="flex items-center gap-1 text-xs text-gray-400">
        <CheckCircle size={12} className="text-green-500" />
        <span>Approved</span>
        <span className="mx-2">·</span>
        <Clock size={12} className="text-amber-500" />
        <span>Pending Review</span>
        <span className="mx-2">·</span>
        <XCircle size={12} className="text-red-500" />
        <span>Rejected</span>
      </div>
    </div>
  );
}
