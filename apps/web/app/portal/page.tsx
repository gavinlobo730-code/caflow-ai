"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  FileText, Calendar, FolderOpen, LogOut, AlertCircle, Upload,
  CheckCircle, AlertTriangle, Download, BarChart3,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

interface PortalClient {
  id: string;
  client_name: string;
  gst_filing_frequency: string | null;
  firm_id: string;
}

interface FirmInfo {
  id: string;
  firm_name: string;
}

interface DocumentRequest {
  id: string;
  title: string;
  description: string | null;
  is_urgent: boolean;
  status: string;
  fulfilled_at: string | null;
  storage_path: string | null;
  file_name: string | null;
  created_at: string;
}

interface SharedDocument {
  id: string;
  file_name: string;
  label: string;
  storage_path: string;
  file_size_bytes: number | null;
  created_at: string;
}

interface SharedReport {
  id: string;
  report_label: string;
  report_type: string;
  financial_year: string;
  storage_path: string;
  file_name: string;
  file_size_bytes: number | null;
  created_at: string;
}

interface GSTDueDate {
  label: string;
  dueDate: string;
  description: string;
}

type PortalTab = "requests" | "shared" | "reports" | "filings" | "dues";


function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Compute upcoming GST due dates based on filing frequency
// CGST Act §37 (GSTR-1), §39 (GSTR-3B)
function getUpcomingGSTDates(frequency: string | null): GSTDueDate[] {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth(); // 0-indexed

  const dates: GSTDueDate[] = [];

  if (!frequency || frequency === "monthly") {
    for (let offset = 0; offset <= 2; offset++) {
      const targetMonth = (month + offset) % 12;
      const targetYear = year + Math.floor((month + offset) / 12);
      const monthName = new Date(targetYear, targetMonth, 1).toLocaleString("en-IN", { month: "long", year: "numeric" });
      const gstr1Date = new Date(targetYear, targetMonth + 1, 11).toISOString().split("T")[0];
      const gstr3bDate = new Date(targetYear, targetMonth + 1, 20).toISOString().split("T")[0];
      if (gstr1Date >= today.toISOString().split("T")[0]) {
        dates.push({ label: `GSTR-1 (${monthName})`, dueDate: gstr1Date, description: "Monthly outward supplies return" });
      }
      if (gstr3bDate >= today.toISOString().split("T")[0]) {
        dates.push({ label: `GSTR-3B (${monthName})`, dueDate: gstr3bDate, description: "Monthly summary return" });
      }
      if (dates.length >= 4) break;
    }
  } else if (frequency === "quarterly") {
    const quarters = [
      { label: "Apr–Jun", endMonth: 5 },
      { label: "Jul–Sep", endMonth: 8 },
      { label: "Oct–Dec", endMonth: 11 },
      { label: "Jan–Mar", endMonth: 2 },
    ];
    for (const q of quarters) {
      const qEndYear = q.endMonth < month ? year + 1 : year;
      const gstr1Date = new Date(qEndYear, q.endMonth + 1, 13).toISOString().split("T")[0];
      const gstr3bDate = new Date(qEndYear, q.endMonth + 1, 22).toISOString().split("T")[0];
      if (gstr1Date >= today.toISOString().split("T")[0]) {
        dates.push({ label: `GSTR-1 (${q.label})`, dueDate: gstr1Date, description: "Quarterly outward supplies return" });
        dates.push({ label: `GSTR-3B (${q.label})`, dueDate: gstr3bDate, description: "Quarterly summary return" });
        break;
      }
    }
  }

  return dates.slice(0, 4);
}

function LoadingScreen() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center space-y-3">
        <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center mx-auto">
          <span className="text-white font-bold text-sm">CA</span>
        </div>
        <p className="text-sm text-gray-500">Loading your portal…</p>
      </div>
    </div>
  );
}

export default function PortalPage() {
  const [client, setClient] = useState<PortalClient | null>(null);
  const [firm, setFirm] = useState<FirmInfo | null>(null);
  const [documents, setDocuments] = useState<SharedDocument[]>([]);
  const [docRequests, setDocRequests] = useState<DocumentRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<PortalTab>("requests");

  // Upload state per request
  const [sharedReports, setSharedReports] = useState<SharedReport[]>([]);
  const [uploadingRequestId, setUploadingRequestId] = useState<string | null>(null);
  const uploadRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Read ?client= param from magic link redirect URL
  const clientIdFromUrl =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("client")
      : null;

  const loadPortalData = useCallback(async (authUserId: string, supabase: ReturnType<typeof getSupabaseClient>) => {
    // Try auto-link from magic link redirect if client ID is in URL
    if (clientIdFromUrl) {
      const { data: linkedRow } = await supabase
        .from("clients")
        .select("portal_user_id")
        .eq("id", clientIdFromUrl)
        .eq("portal_enabled", true)
        .maybeSingle();
      if (linkedRow && !linkedRow.portal_user_id) {
        // Auto-link on first login — no manual SQL needed
        await supabase
          .from("clients")
          .update({ portal_user_id: authUserId })
          .eq("id", clientIdFromUrl)
          .eq("portal_enabled", true);
      }
    }

    const { data: clientRow, error: clientErr } = await supabase
      .from("clients")
      .select("id, client_name, gst_filing_frequency, firm_id")
      .eq("portal_user_id", authUserId)
      .eq("portal_enabled", true)
      .maybeSingle();

    return { clientRow, clientErr };
  }, [clientIdFromUrl]);

  useEffect(() => {
    async function load() {
      const supabase = getSupabaseClient();
      try {
        const { data: sessionData } = await supabase.auth.getSession();
        const session = sessionData?.session;
        if (!session) {
          setError("You are not signed in. Please sign in to access the portal.");
          setLoading(false);
          return;
        }

        const authUserId = session.user.id;

        const { clientRow, clientErr } = await loadPortalData(authUserId, supabase);

        if (clientErr) throw new Error(clientErr.message);
        if (!clientRow) {
          setError("No client portal found for this account. Please contact your CA.");
          setLoading(false);
          return;
        }

        setClient(clientRow);

        // Load firm info
        const { data: firmRow } = await supabase
          .from("firms")
          .select("id, firm_name")
          .eq("id", clientRow.firm_id)
          .maybeSingle();
        setFirm(firmRow ?? null);

        // Load shared documents (CA → client)
        const { data: docRows } = await supabase
          .from("client_documents")
          .select("id, file_name, label, storage_path, file_size_bytes, created_at")
          .eq("client_id", clientRow.id)
          .order("created_at", { ascending: false });
        setDocuments(docRows ?? []);

        // Load document requests from CA
        const { data: requestRows } = await supabase
          .from("document_requests")
          .select("id, title, description, is_urgent, status, fulfilled_at, storage_path, file_name, created_at")
          .eq("client_id", clientRow.id)
          .order("created_at", { ascending: false });
        setDocRequests(requestRows ?? []);

        // Load shared reports from CA
        const { data: reportRows } = await supabase
          .from("shared_reports")
          .select("id, report_label, report_type, financial_year, storage_path, file_name, file_size_bytes, created_at")
          .eq("client_id", clientRow.id)
          .order("created_at", { ascending: false });
        setSharedReports(reportRows ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load portal");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [loadPortalData]);

  async function handleUploadForRequest(requestId: string, file: File) {
    if (!client) return;
    setUploadingRequestId(requestId);
    try {
      const supabase = getSupabaseClient();
      const uuid = crypto.randomUUID();
      const storagePath = `document_requests/${client.id}/${uuid}-${file.name}`;

      const { error: uploadErr } = await supabase.storage
        .from("Documents")
        .upload(storagePath, file, { contentType: file.type || "application/octet-stream" });
      if (uploadErr) throw new Error(uploadErr.message);

      // Update the request row: status='fulfilled', storage_path, file_name
      const { error: updateErr } = await supabase
        .from("document_requests")
        .update({
          status: "fulfilled",
          fulfilled_at: new Date().toISOString(),
          storage_path: storagePath,
          file_name: file.name,
        })
        .eq("id", requestId);
      if (updateErr) throw new Error(updateErr.message);

      // Refresh requests
      const { data: requestRows } = await supabase
        .from("document_requests")
        .select("id, title, description, is_urgent, status, fulfilled_at, storage_path, file_name, created_at")
        .eq("client_id", client.id)
        .order("created_at", { ascending: false });
      setDocRequests(requestRows ?? []);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploadingRequestId(null);
    }
  }

  async function handleDownloadDoc(doc: SharedDocument) {
    const supabase = getSupabaseClient();
    const { data, error: err } = await supabase.storage
      .from("Documents")
      .createSignedUrl(doc.storage_path, 3600);
    if (err || !data) {
      alert("Could not generate download link. Please try again.");
      return;
    }
    window.open(data.signedUrl, "_blank");
  }

  async function handleSignOut() {
    const supabase = getSupabaseClient();
    await supabase.auth.signOut();
    window.location.href = "/";
  }

  if (loading) return <LoadingScreen />;

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 max-w-sm w-full text-center space-y-4">
          <div className="flex items-center justify-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <span className="text-white font-bold text-xs">CA</span>
            </div>
            <span className="text-base font-bold text-gray-900">CAflow AI</span>
          </div>
          <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700 text-left">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
          <button
            onClick={handleSignOut}
            className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1 mx-auto"
          >
            <LogOut className="w-3 h-3" /> Sign out
          </button>
        </div>
      </div>
    );
  }

  if (!client) return null;

  const gstDates = getUpcomingGSTDates(client.gst_filing_frequency);
  const today = new Date().toISOString().split("T")[0];
  const pendingRequests = docRequests.filter((r) => r.status === "pending");
  const fulfilledRequests = docRequests.filter((r) => r.status === "fulfilled");

  const TABS: { id: PortalTab; label: string; icon: React.ElementType; count?: number }[] = [
    { id: "requests", label: "Documents Requested", icon: FileText, count: pendingRequests.length || undefined },
    { id: "shared", label: "Shared by CA", icon: FolderOpen },
    { id: "reports", label: "Reports", icon: BarChart3 },
    { id: "filings", label: "Recent Filings", icon: Calendar },
    { id: "dues", label: "Outstanding Dues", icon: AlertCircle },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <span className="text-white font-bold text-xs">CA</span>
          </div>
          <span className="text-sm font-bold text-gray-900">CAflow AI</span>
          <span className="text-gray-300 text-sm">·</span>
          <span className="text-sm text-gray-500">Client Portal</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right hidden sm:block">
            <p className="text-xs font-medium text-gray-900">{client.client_name}</p>
            {firm && <p className="text-xs text-gray-400">{firm.firm_name}</p>}
          </div>
          <button
            onClick={handleSignOut}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600"
          >
            <LogOut className="w-3.5 h-3.5" />
            Sign out
          </button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Welcome */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <h1 className="text-xl font-semibold text-gray-900">Welcome, {client.client_name}</h1>
          {firm && <p className="text-sm text-gray-500 mt-0.5">Managed by {firm.firm_name}</p>}
          {pendingRequests.length > 0 && (
            <div className="mt-3 flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
              <span className="text-sm text-amber-800 font-medium">
                {pendingRequests.length} document{pendingRequests.length > 1 ? "s" : ""} requested by your CA
              </span>
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-gray-200 bg-white rounded-t-xl px-2 pt-2 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap rounded-t-lg ${
                activeTab === tab.id
                  ? "border-blue-600 text-blue-700 bg-blue-50/50"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50"
              }`}
            >
              <tab.icon size={14} />
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className="ml-1 bg-amber-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center font-semibold">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Documents Requested tab */}
        {activeTab === "requests" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-900">Documents Requested by Your CA</h2>
            </div>
            {docRequests.length === 0 ? (
              <div className="px-5 py-12 text-center space-y-2">
                <FileText className="w-8 h-8 text-gray-200 mx-auto" />
                <p className="text-sm text-gray-400">No documents have been requested yet</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {/* Pending first */}
                {pendingRequests.map((req) => (
                  <div key={req.id} className="px-5 py-4 flex items-start gap-3">
                    <div className="w-9 h-9 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                      <FileText size={16} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-900">{req.title}</p>
                        {req.is_urgent && (
                          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full font-medium">
                            <AlertTriangle size={10} /> Urgent
                          </span>
                        )}
                      </div>
                      {req.description && (
                        <p className="text-xs text-gray-500 mt-0.5">{req.description}</p>
                      )}
                      <p className="text-xs text-gray-400 mt-1">Requested {formatDate(req.created_at)}</p>
                    </div>
                    <div className="shrink-0">
                      <input
                        type="file"
                        className="hidden"
                        ref={(el) => { uploadRefs.current[req.id] = el; }}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) handleUploadForRequest(req.id, f);
                          e.target.value = "";
                        }}
                      />
                      <button
                        onClick={() => uploadRefs.current[req.id]?.click()}
                        disabled={uploadingRequestId === req.id}
                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-60"
                      >
                        <Upload size={11} />
                        {uploadingRequestId === req.id ? "Uploading…" : "Upload"}
                      </button>
                    </div>
                  </div>
                ))}
                {/* Fulfilled */}
                {fulfilledRequests.map((req) => (
                  <div key={req.id} className="px-5 py-4 flex items-start gap-3 bg-green-50/30">
                    <div className="w-9 h-9 rounded-full bg-green-100 text-green-600 flex items-center justify-center shrink-0 mt-0.5">
                      <CheckCircle size={16} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-700 line-through decoration-gray-400">{req.title}</p>
                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full font-medium">
                          <CheckCircle size={10} /> Submitted ✓
                        </span>
                      </div>
                      {req.file_name && (
                        <p className="text-xs text-gray-400 mt-0.5">Uploaded: {req.file_name}</p>
                      )}
                      {req.fulfilled_at && (
                        <p className="text-xs text-gray-400 mt-0.5">{formatDate(req.fulfilled_at)}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Shared by CA tab */}
        {activeTab === "shared" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <FolderOpen className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-900">Documents Shared by Your CA</h2>
            </div>
            {documents.length === 0 ? (
              <div className="px-5 py-12 text-center space-y-2">
                <FolderOpen className="w-8 h-8 text-gray-200 mx-auto" />
                <p className="text-sm text-gray-400">
                  No documents shared yet — your CA will upload returns, notices, and reports here
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {documents.map((doc) => (
                  <div key={doc.id} className="px-5 py-3 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{doc.label}</p>
                      <p className="text-xs text-gray-400 mt-0.5 truncate">
                        {doc.file_name}
                        {doc.file_size_bytes ? ` · ${formatFileSize(doc.file_size_bytes)}` : ""}
                        {" · "}{formatDate(doc.created_at)}
                      </p>
                    </div>
                    <button
                      onClick={() => handleDownloadDoc(doc)}
                      className="shrink-0 flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                    >
                      <Download className="w-3 h-3" />
                      Download
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Reports tab — shared by CA */}
        {activeTab === "reports" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-900">Reports Shared by Your CA</h2>
            </div>
            {sharedReports.length === 0 ? (
              <div className="px-5 py-12 text-center space-y-2">
                <BarChart3 className="w-8 h-8 text-gray-200 mx-auto" />
                <p className="text-sm text-gray-400">No reports shared yet</p>
                <p className="text-xs text-gray-300">Your CA will share P&L, Balance Sheet, and other reports here</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {sharedReports.map((r) => (
                  <div key={r.id} className="px-5 py-3 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{r.report_label}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        FY {r.financial_year}
                        {r.file_size_bytes ? ` · ${formatFileSize(r.file_size_bytes)}` : ""}
                        {" · "}{formatDate(r.created_at)}
                      </p>
                    </div>
                    <button
                      onClick={async () => {
                        const supabase = getSupabaseClient();
                        const { data, error: err } = await supabase.storage
                          .from("Documents")
                          .createSignedUrl(r.storage_path, 3600);
                        if (err || !data) { alert("Could not generate download link."); return; }
                        const a = document.createElement("a");
                        a.href = data.signedUrl;
                        a.download = r.file_name;
                        a.click();
                      }}
                      className="shrink-0 flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                    >
                      <Download className="w-3 h-3" />
                      Download
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Recent Filings tab — GST due dates */}
        {activeTab === "filings" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <Calendar className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-900">Upcoming GST Due Dates</h2>
            </div>
            {gstDates.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-gray-400">No upcoming GST deadlines</div>
            ) : (
              <div className="divide-y divide-gray-50">
                {gstDates.map((d, i) => {
                  const isOverdue = d.dueDate < today;
                  const daysLeft = Math.ceil((new Date(d.dueDate).getTime() - Date.now()) / 86400000);
                  return (
                    <div key={i} className="px-5 py-3 flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-900">{d.label}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{d.description}</p>
                      </div>
                      <div className="text-right">
                        <p className={`text-sm font-medium ${isOverdue ? "text-red-600" : daysLeft <= 7 ? "text-amber-600" : "text-gray-700"}`}>
                          {formatDate(d.dueDate)}
                        </p>
                        <p className={`text-xs mt-0.5 ${isOverdue ? "text-red-500" : daysLeft <= 7 ? "text-amber-500" : "text-gray-400"}`}>
                          {isOverdue ? "Overdue" : daysLeft === 0 ? "Due today" : `${daysLeft} days`}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Outstanding Dues tab — placeholder */}
        {activeTab === "dues" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-900">Outstanding Dues</h2>
            </div>
            <div className="px-5 py-12 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-gray-200 mx-auto" />
              <p className="text-sm text-gray-400">Outstanding dues will be shown here</p>
              <p className="text-xs text-gray-300">Contact your CA for details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
