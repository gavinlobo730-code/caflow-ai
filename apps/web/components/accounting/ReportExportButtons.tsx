"use client";

import { useState } from "react";
import { FileSpreadsheet, FileText, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import {
  exportErrorMessage,
  type ExportFormat,
  type ExportParams,
  type ExportReport,
} from "@/lib/export/reportExport";

/**
 * "PDF" and "Excel" for a live report (accounting-16).
 *
 * THE FILE IS BUILT BY THE SERVER, from the same report function the screen
 * beside this button calls, so what is downloaded is what is on screen — this
 * component holds no figure, no format rule and no letterhead. It asks, waits,
 * and says in words when the server refused (a ledger too long to print, a
 * report that does not foot), rather than leaving a button that appears to do
 * nothing.
 *
 * The parent says WHICH formats it offers; the server refuses the rest, so the
 * two cannot disagree about it.
 */
export default function ReportExportButtons({
  report,
  clientId,
  params,
  formats = ["pdf"],
  disabled = false,
}: {
  report: ExportReport;
  clientId: string;
  params?: ExportParams;
  formats?: ExportFormat[];
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(format: ExportFormat) {
    setBusy(format);
    setError(null);
    try {
      await api.reportExports.download(report, format, clientId, params ?? {});
    } catch (e) {
      setError(exportErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <span className="inline-flex items-center gap-1.5">
        {formats.map((format) => (
          <button
            key={format}
            type="button"
            onClick={() => run(format)}
            disabled={disabled || busy !== null || !clientId}
            title={format === "pdf" ? "Download a PDF of this report" : "Download this report as an Excel file"}
            className="inline-flex items-center gap-1 text-2xs px-2 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-label disabled:opacity-50"
          >
            {busy === format ? (
              <Loader2 size={12} className="animate-spin" />
            ) : format === "pdf" ? (
              <FileText size={12} />
            ) : (
              <FileSpreadsheet size={12} />
            )}
            {format === "pdf" ? "PDF" : "Excel"}
          </button>
        ))}
      </span>
      {error && (
        <span role="alert" className="max-w-xs text-right text-3xs text-state-problem">
          {error}
        </span>
      )}
    </span>
  );
}
