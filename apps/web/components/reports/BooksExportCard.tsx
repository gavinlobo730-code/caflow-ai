"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth, usePermissions } from "@/lib/auth/AuthContext";
import { exportErrorMessage } from "@/lib/export/reportExport";

/**
 * "Take this client's books with you": one ZIP of CSV files with a manifest (POST-A-205, slice 1).
 *
 * A PARTNER'S, and the server decides it (`firm:admin` AND the Partner role, the client scope and the two-factor guard); this card only does not offer the
 * button to anyone the server would refuse. Everything it says about the file is the server's own account, written beside the button, because an export that looks complete
 * and is not is worse than none: what is in it, what is NOT in it, and that it is a copy read one request at a time rather than a snapshot. The file
 * is built page by page on the server and refused in words when the client is too large to read in one request; that sentence is shown as it comes.
 */
export default function BooksExportCard({ clientId }: { clientId: string }) {
  const { can } = usePermissions();
  const { userRole } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (userRole !== "Partner" || !can("firm", "admin")) return null;

  async function run() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setProblem(null);
    setDone(false);
    try {
      const headers = await api.dataExport.clientBooks(clientId);
      setDone(true);
      setProblem(headers.get("X-Export-Problems"));
    } catch (e) {
      setError(exportErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden" data-testid="books-export-card">
      <div className="px-5 py-4 border-b border-ps-border">
        <p className="text-xs font-semibold text-ps-body">Take this client&apos;s books with you</p>
        <p className="text-3xs text-ps-hint mt-0.5">A Partner&apos;s download, logged each time. One ZIP of CSV files and a manifest that names every file with its row count and checksum.</p>
      </div>
      <div className="px-5 py-4 space-y-3">
        <p className="text-2xs text-ps-label">
          <span className="font-medium">In it:</span> the chart of accounts, customers and vendors, every journal entry and line, sales invoices, purchase bills, credit and debit
          notes, receipts and vendor payments with their lines and allocations, and the TDS register. A trial balance made from the ledger files is included so the books can be
          checked without us.
        </p>
        <p className="text-2xs text-ps-label">
          <span className="font-medium">Not in it yet:</span> payroll, the bank, uploaded documents, the audit log, GST returns, income tax, fixed assets and stock, PDFs, and
          records beside the books such as advances, loans, orders and the service catalogue. The manifest lists the files that are here and says anything else is not. The files are read one request at a time, so they are a copy and not a snapshot; a client with a very large ledger is refused in words rather than
          cut short.
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={run}
            disabled={busy || !clientId}
            className="inline-flex items-center gap-1.5 text-2xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-label disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
            {busy ? "Preparing the files…" : "Download books (CSV)"}
          </button>
          {done && !error && <span className="text-3xs text-ps-label">Downloaded. Check manifest.json inside the file before relying on it.</span>}
        </div>
        {problem && (
          <p role="alert" className="text-3xs text-state-problem">
            The export found a problem in itself: {problem}. Open manifest.json in the file for what it is.
          </p>
        )}
        {error && (
          <p role="alert" className="text-3xs text-state-problem">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
