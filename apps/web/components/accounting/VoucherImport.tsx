"use client";

/**
 * Import journals, payments, receipts and contras from a spreadsheet (ACC-17).
 *
 * WHAT WAS MISSING
 *   Bulk import existed for invoices, receipts, bills and notes and not for the
 *   vouchers a bookkeeper most often has in a spreadsheet. Many small clients
 *   send the CA an Excel of payments and journals, and every line was typed
 *   again.
 *
 * THIS SCREEN DECIDES NOTHING. Whether a voucher balances, which ledger a cell
 * means, whether a date is open and whether a number is already on the books are
 * `domain/accounting/voucher_import`'s answers; every posting goes through the
 * one posting kernel on the server. What is here is the choice the CA has to make
 * before anything is sent, the shared import dialog, and the loop that sends the
 * vouchers a few at a time (see lib/accounting/voucherImport for why).
 *
 * THE CA MUST SAY WHERE THE VOUCHERS GO. "Post to the ledger now" and "Save as
 * drafts" are both on the screen and neither is pre-selected: the server refuses
 * a request that does not say, and a screen that picked for the CA would be the
 * same omission one layer up. Drafts are off-books, so they are the safe choice;
 * posting is what most files are for.
 */
import { useState } from "react";
import { Upload } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import CsvImportModal from "@/components/LazyCsvImportModal";
import type { ImportMeta, ImportResult, ImportRow } from "@/components/CsvImportModal";
import { api, type VoucherImportResult } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";
import {
  buildVoucherLegs, chunkVouchers, mergeVoucherResults, voucherColumns,
  voucherOutcomeFrom, voucherSummarySentence,
  type VoucherLayout, type VoucherStatus,
} from "@/lib/accounting/voucherImport";

export function VoucherImportButton({ clientId, onImported, onSummary }: {
  clientId: string;
  /** The ledger changed (or drafts were added) — reload whatever lists them. */
  onImported: () => void;
  /** What happened, in a sentence, for the screen to show once the dialog closes. */
  onSummary?: (sentence: string) => void;
}) {
  const [step, setStep] = useState<"closed" | "choose" | "import">("closed");
  const [layout, setLayout] = useState<VoucherLayout>("lines");
  const [status, setStatus] = useState<VoucherStatus | null>(null);

  async function handleImport(rows: ImportRow[], meta?: ImportMeta): Promise<ImportResult> {
    if (!status) throw new Error("Say whether the vouchers are posted or saved as drafts.");
    const batches = chunkVouchers(buildVoucherLegs(rows, layout, meta?.rowNumbers));
    const parts: VoucherImportResult[] = [];
    const stopped: string[] = [];
    for (let i = 0; i < batches.length; i++) {
      try {
        const res = await api.accounting.importVouchers({
          client_id: clientId, status, legs: batches[i],
        });
        if (!res.success) throw new Error(res.error ?? "The import did not complete.");
        const part = objectWithLists<VoucherImportResult>(res.data, "results");
        if (!part) throw new Error("The server's answer to the import could not be read.");
        parts.push(part);
      } catch (e) {
        // Stop at the first batch that does not answer: carrying on would post
        // more vouchers on top of a state the CA cannot see. Everything already
        // posted is real and is reported, and uploading the file again skips it.
        const done = parts.reduce((n, p) => n + p.vouchers, 0);
        stopped.push(
          `The import stopped after ${done} voucher${done === 1 ? "" : "s"} (batch ${i + 1} of `
          + `${batches.length}): ${e instanceof Error ? e.message : "no answer from the server"}. `
          + "Upload the same file again — vouchers already on the books are skipped.");
        break;
      }
    }
    const merged = mergeVoucherResults(parts);
    onImported();
    onSummary?.(voucherSummarySentence(merged, status, formatPaise));
    const outcome = voucherOutcomeFrom(merged);
    return { ...outcome, errors: [...stopped, ...outcome.errors] };
  }

  const radio = "mt-0.5";
  return (
    <>
      <button
        type="button"
        onClick={() => { setStatus(null); setStep("choose"); }}
        className="text-xs px-3 py-1.5 border border-ps-border text-ps-body rounded-lg hover:bg-ps-bg flex items-center gap-1"
      >
        <Upload size={12} /> Import vouchers
      </button>

      {step === "choose" && (
        <Modal title="Import vouchers from a spreadsheet" maxWidthClass="max-w-md"
               onClose={() => setStep("closed")}
               note="Journals, payments, receipts and contras. Nothing is sent until you have chosen a file and seen the preview.">
          <div className="space-y-4 text-xs">
            <fieldset className="space-y-1.5">
              <legend className="font-medium text-ps-body mb-1">How is the sheet laid out?</legend>
              <label className="flex items-start gap-2 text-ps-body">
                <input type="radio" name="voucher-layout" className={radio}
                       checked={layout === "lines"} onChange={() => setLayout("lines")} />
                <span>One line per ledger entry
                  <span className="block text-3xs text-ps-hint">Journals — a voucher of several lines shares its voucher number.</span></span>
              </label>
              <label className="flex items-start gap-2 text-ps-body">
                <input type="radio" name="voucher-layout" className={radio}
                       checked={layout === "simple"} onChange={() => setLayout("simple")} />
                <span>One line per voucher
                  <span className="block text-3xs text-ps-hint">Payments, receipts and contras — a debit ledger, a credit ledger and an amount.</span></span>
              </label>
            </fieldset>

            <fieldset className="space-y-1.5">
              <legend className="font-medium text-ps-body mb-1">Where do the vouchers go?</legend>
              <label className="flex items-start gap-2 text-ps-body">
                <input type="radio" name="voucher-status" className={radio}
                       checked={status === "posted"} onChange={() => setStatus("posted")} />
                <span>Post to the ledger now
                  <span className="block text-3xs text-ps-hint">A closed period or a filed return refuses a voucher by name; the rest post.</span></span>
              </label>
              <label className="flex items-start gap-2 text-ps-body">
                <input type="radio" name="voucher-status" className={radio}
                       checked={status === "draft"} onChange={() => setStatus("draft")} />
                <span>Save as drafts for review
                  <span className="block text-3xs text-ps-hint">Off the books until each is posted.</span></span>
              </label>
            </fieldset>

            <p className="text-3xs text-ps-hint">
              Uploading the same file twice posts nothing twice: a voucher number already
              on the books is skipped.
            </p>

            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStep("closed")}
                      className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button type="button" disabled={status === null} onClick={() => setStep("import")}
                      className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40">
                Choose the file…
              </button>
            </div>
          </div>
        </Modal>
      )}

      {step === "import" && status && (
        <CsvImportModal
          title={layout === "lines" ? "Import journal lines" : "Import payments, receipts and contras"}
          columns={voucherColumns(layout)}
          templateFilename={layout === "lines" ? "voucher-lines-template.csv" : "vouchers-template.csv"}
          onImport={handleImport}
          onClose={() => setStep("closed")}
          skippedHeading="Already on the books — skipped, so uploading the same file again posts nothing twice:"
        />
      )}
    </>
  );
}
