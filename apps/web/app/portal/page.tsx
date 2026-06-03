"use client";

import { useState, useEffect } from "react";
import { FileText, Calendar, FolderOpen, LogOut, AlertCircle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

interface PortalClient {
  id: string;
  client_name: string;
  gst_filing_frequency: string | null;
}

interface PortalDocument {
  id: string;
  file_name: string;
  label: string;
  storage_path: string;
  file_size_bytes: number | null;
  created_at: string;
}

interface PortalInvoice {
  id: string;
  invoice_number: string | null;
  invoice_date: string;
  total_paise: number;
  status: string;
}

interface GSTDueDate {
  label: string;
  dueDate: string;
  description: string;
}

function formatPaise(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const paiseRemainder = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${String(paiseRemainder).padStart(2, "0")}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// Compute upcoming GST due dates based on filing frequency
// CGST Act §37 (GSTR-1), §39 (GSTR-3B)
function getUpcomingGSTDates(frequency: string | null): GSTDueDate[] {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth(); // 0-indexed

  const dates: GSTDueDate[] = [];

  if (!frequency || frequency === "monthly") {
    // GSTR-1: 11th of following month
    // GSTR-3B: 20th of following month
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
    // QRMP scheme — GSTR-1 quarterly: 13th of month after quarter end
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
  const [invoices, setInvoices] = useState<PortalInvoice[]>([]);
  const [documents, setDocuments] = useState<PortalDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

        const { data: clientRow, error: clientErr } = await supabase
          .from("clients")
          .select("id, client_name, gst_filing_frequency")
          .eq("portal_user_id", authUserId)
          .eq("portal_enabled", true)
          .maybeSingle();

        if (clientErr) throw new Error(clientErr.message);
        if (!clientRow) {
          setError("No client portal found for this account. Please contact your CA.");
          setLoading(false);
          return;
        }

        setClient(clientRow);

        const { data: invoiceRows } = await supabase
          .from("sales_invoices")
          .select("id, invoice_number, invoice_date, total_paise, status")
          .eq("client_id", clientRow.id)
          .order("invoice_date", { ascending: false })
          .limit(10);

        setInvoices(invoiceRows ?? []);

        const { data: docRows } = await supabase
          .from("client_documents")
          .select("id, file_name, label, storage_path, file_size_bytes, created_at")
          .eq("client_id", clientRow.id)
          .order("created_at", { ascending: false });

        setDocuments(docRows ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load portal");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleDownloadDoc(doc: PortalDocument) {
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

  function formatFileSize(bytes: number | null): string {
    if (bytes === null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
          <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center mx-auto">
            <span className="text-white font-bold text-sm">CA</span>
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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <span className="text-white font-bold text-xs">CA</span>
          </div>
          <span className="text-sm font-semibold text-gray-900">CAflow</span>
          <span className="text-gray-300 text-sm">·</span>
          <span className="text-sm text-gray-500">Client Portal</span>
        </div>
        <button
          onClick={handleSignOut}
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </button>
      </div>

      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Welcome */}
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Welcome, {client.client_name}</h1>
          <p className="text-sm text-gray-500 mt-0.5">Your practice portal — invoices, compliance, and documents in one place</p>
        </div>

        {/* Invoices */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
            <FileText className="w-4 h-4 text-blue-600" />
            <h2 className="text-sm font-semibold text-gray-900">Recent Invoices</h2>
          </div>
          {invoices.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No invoices found</div>
          ) : (
            <div className="divide-y divide-gray-50">
              {invoices.map(inv => (
                <div key={inv.id} className="px-5 py-3 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {inv.invoice_number ?? "Invoice"}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">{formatDate(inv.invoice_date)}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-gray-900 tabular-nums">
                      {formatPaise(inv.total_paise)}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      inv.status === "paid"
                        ? "bg-green-100 text-green-700"
                        : inv.status === "overdue"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                    }`}>
                      {inv.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* GST Due Dates */}
        <div className="bg-white rounded-xl border border-gray-100">
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

        {/* Documents */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
            <FolderOpen className="w-4 h-4 text-blue-600" />
            <h2 className="text-sm font-semibold text-gray-900">Documents</h2>
          </div>
          {documents.length === 0 ? (
            <div className="px-5 py-10 text-center space-y-1">
              <FolderOpen className="w-8 h-8 text-gray-200 mx-auto" />
              <p className="text-sm text-gray-400">No documents shared yet — your CA will upload returns, notices, and reports here</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-50">
              {documents.map(doc => (
                <div key={doc.id} className="px-5 py-3 flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{doc.label}</p>
                    <p className="text-xs text-gray-400 mt-0.5 truncate">
                      {doc.file_name}{doc.file_size_bytes ? ` · ${formatFileSize(doc.file_size_bytes)}` : ""} · {formatDate(doc.created_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => handleDownloadDoc(doc)}
                    className="shrink-0 flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
