/**
 * CSV/XLSX bulk-import mapper for the Firm HSN/SAC Library (settings/firm-hsn-library).
 *
 * Firm-wide, not client-owned — unlike every other importer in lib/imports/mappers.ts
 * and lib/invoices/importMapping.ts, there's no clientId to scope rows to. Maps onto
 * the EXISTING POST /api/firm-hsn-library/bulk endpoint, which does its own
 * duplicate/reactivation handling — this mapper only does structural validation
 * (pure, unit-testable), matching the "Caflow never classifies HSN/SAC" rule the
 * whole library already follows.
 */

export interface ImportColumn { key: string; label: string; required: boolean; hint?: string; }

const CODE_RE = /^\d{2,8}$/;

function str(v: string | undefined): string { return (v ?? "").trim(); }
function num(v: string | undefined): number { return parseFloat(str(v)); }

export interface BuiltHsnCode {
  hsn_code: string;
  description: string;
  hsn_type: "goods" | "services";
  gst_rate_pct?: number;
  uqc?: string;
  notes?: string;
  source: "import";
}

export const FIRM_HSN_LIBRARY_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "hsn_code", label: "HSN/SAC Code", required: true, hint: "2-8 digits, e.g. 998221" },
  { key: "description", label: "Description", required: true, hint: "What this code covers" },
  { key: "hsn_type", label: "Type", required: true, hint: "goods / services" },
  { key: "gst_rate", label: "GST %", required: false, hint: "e.g. 18 — a pre-fill hint only, never used in tax math (optional)" },
  { key: "uqc", label: "UQC", required: false, hint: "Unit of measure, e.g. KGS, NOS (optional)" },
  { key: "notes", label: "Notes", required: false, hint: "Internal note (optional)" },
];

export function buildFirmHsnCodes(rows: Record<string, string>[]): { records: BuiltHsnCode[]; errors: string[] } {
  const records: BuiltHsnCode[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const hsnCode = str(r.hsn_code);
    if (!hsnCode) { errors.push(`Row ${rowNo}: HSN/SAC code is required`); return; }
    if (!CODE_RE.test(hsnCode)) { errors.push(`Row ${rowNo}: "${hsnCode}" must be 2-8 digits`); return; }
    if (seen.has(hsnCode)) { errors.push(`Row ${rowNo}: duplicate code "${hsnCode}" in this file`); return; }

    const description = str(r.description);
    if (!description) { errors.push(`Row ${rowNo}: description is required`); return; }

    const typeRaw = str(r.hsn_type).toLowerCase();
    if (typeRaw !== "goods" && typeRaw !== "services") {
      errors.push(`Row ${rowNo}: type must be "goods" or "services"`); return;
    }

    const gstRaw = str(r.gst_rate);
    const gstRatePct = gstRaw ? num(r.gst_rate) : undefined;
    if (gstRaw && (!Number.isFinite(gstRatePct) || (gstRatePct as number) < 0 || (gstRatePct as number) > 100)) {
      errors.push(`Row ${rowNo}: GST % must be between 0 and 100`); return;
    }

    seen.add(hsnCode);
    records.push({
      hsn_code: hsnCode,
      description,
      hsn_type: typeRaw as "goods" | "services",
      gst_rate_pct: gstRatePct,
      uqc: str(r.uqc) || undefined,
      notes: str(r.notes) || undefined,
      source: "import",
    });
  });

  return { records, errors };
}
