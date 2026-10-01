"use client";

/**
 * Bring a migrated client's assets over WITH the depreciation each already
 * carries, from a spreadsheet (accounting-18).
 *
 * WHAT WAS MISSING
 *   An asset could be added one way: the Add Asset drawer, which starts the
 *   accumulated depreciation at nil and posts a fresh acquisition. A client
 *   arriving from Tally has tens or hundreds of part-depreciated assets, and the
 *   only route to their real position was to let the depreciation runner charge
 *   every month since the purchase on top of what the opening balances carry.
 *
 * THIS SCREEN DECIDES NOTHING. Which category Schedule II holds, what basis an
 * asset gets, whether a position is possible for its cost, which code is already
 * on the register and what a re-upload means are
 * `domain/fixed_assets/opening_register`'s answers. What is here is the choice
 * the CA has to make before anything is sent (the date the figures are stated
 * as at — chosen, never defaulted, because it decides which month the next
 * depreciation run starts at), the shared import dialog, and the result.
 *
 * AND THE RESULT SAYS WHAT WAS NOT DONE. The server posts nothing to the ledger —
 * the register is the asset-by-asset breakup of balances the opening balances
 * carry — and says so in a sentence it serves, which is shown beside the totals
 * to compare with the ledger. A quiet success would read as "the balance sheet
 * now carries these", which is exactly what it does not mean.
 */
import { useState } from "react";
import { Upload } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { Callout, GapList } from "@/components/ui/callout";
import CsvImportModal from "@/components/LazyCsvImportModal";
import type { ImportMeta, ImportResult, ImportRow } from "@/components/CsvImportModal";
import { request, type ApiResp } from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";
import {
  buildOpeningRegisterRows, openingRegisterColumns, openingRegisterHeadline,
  openingRegisterOutcome, openingRegisterWarnings, positionChoices,
  type OpeningRegisterResult, type PositionChoice,
} from "@/lib/fixedAssets/openingRegister";

export function OpeningRegisterImportButton({ clientId, onImported }: {
  clientId: string;
  /** The register changed — reload whatever lists it. */
  onImported: () => void;
}) {
  const [step, setStep] = useState<"closed" | "choose" | "import" | "summary">("closed");
  const [choices, setChoices] = useState<PositionChoice[]>([]);
  const [asAt, setAsAt] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [result, setResult] = useState<OpeningRegisterResult | null>(null);

  async function open() {
    setAsAt("");
    setResult(null);
    setChoices(positionChoices());
    setStep("choose");
    // The category list is the SERVER's; it only words a hint, so a failure to
    // ask for it costs a less specific hint and nothing else.
    try {
      const res = await request<ApiResp<unknown>>(
        `/api/fixed-assets/categories?client_id=${encodeURIComponent(clientId)}`);
      const names = res.success
        ? arrayOrEmpty<{ category?: unknown }>(res.data)
            .map((c) => c?.category)
            .filter((c): c is string => typeof c === "string")
        : [];
      setCategories(names);
    } catch {
      setCategories([]);
    }
  }

  async function handleImport(rows: ImportRow[], meta?: ImportMeta): Promise<ImportResult> {
    if (!asAt) throw new Error("Choose the date the accumulated depreciation is stated as at.");
    const res = await request<ApiResp<unknown>>("/api/fixed-assets/opening-register", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        as_at: asAt,
        rows: buildOpeningRegisterRows(rows, meta?.rowNumbers),
      }),
    });
    if (!res.success) throw new Error(res.error ?? "The import did not complete.");
    // `{}` passes a shape check and `.map` on it throws, so the lists are named.
    const data = objectWithLists<OpeningRegisterResult>(res.data, "rows", "by_category", "gaps");
    if (!data) throw new Error("The server's answer to the import could not be read.");
    setResult(data);
    onImported();
    return openingRegisterOutcome(data);
  }

  const warnings = result ? openingRegisterWarnings(result) : [];

  return (
    <>
      <button
        type="button"
        onClick={open}
        className="flex items-center gap-1.5 text-xs border border-ps-border text-ps-body px-3 py-1.5 rounded-lg hover:bg-ps-bg"
      >
        <Upload size={12} /> Import opening register
      </button>

      {step === "choose" && (
        <Modal title="Import an opening register" maxWidthClass="max-w-md"
               onClose={() => setStep("closed")}
               note="Assets brought over from the client's previous books, with the depreciation each already carries. Nothing is sent until you have chosen a file and seen the preview.">
          <div className="space-y-4 text-xs">
            <label className="block space-y-1.5">
              <span className="font-medium text-ps-body">
                The accumulated depreciation in your file is stated as at
              </span>
              <select
                className="w-full px-3 py-2 border border-ps-border rounded-lg text-xs bg-white"
                value={asAt}
                onChange={(e) => setAsAt(e.target.value)}
              >
                <option value="">Choose the date…</option>
                {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
              <span className="block text-3xs text-ps-hint">
                A financial-year end, because depreciation is charged one year at a time.
                The depreciation runner starts at the month after it.
              </span>
            </label>
            <p className="text-3xs text-ps-hint">
              This records each asset with its own accumulated depreciation and posts
              nothing to the ledger. Uploading the same file again adds nothing twice: an
              asset code already on the register is skipped.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStep("closed")}
                      className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button type="button" disabled={!asAt} onClick={() => setStep("import")}
                      className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40">
                Choose the file…
              </button>
            </div>
          </div>
        </Modal>
      )}

      {step === "import" && asAt && (
        <CsvImportModal
          title="Import an opening asset register"
          columns={openingRegisterColumns(categories)}
          templateFilename="opening-asset-register-template.csv"
          onImport={handleImport}
          onClose={() => setStep(result ? "summary" : "closed")}
          skippedHeading="Already on the register — skipped, so uploading the same file again adds nothing twice:"
        />
      )}

      {step === "summary" && result && (
        <Modal title="Opening register" maxWidthClass="max-w-2xl"
               onClose={() => setStep("closed")}>
          <div className="space-y-3 text-xs">
            <p className="text-ps-ink">{openingRegisterHeadline(result, formatPaise)}</p>

            {result.by_category.length > 0 && (
              <table className="w-full text-xs border border-ps-border rounded-lg overflow-hidden">
                <thead>
                  <tr className="bg-ps-bg text-ps-hint">
                    <th className="px-3 py-2 text-left font-semibold">Class</th>
                    <th className="px-3 py-2 text-right font-semibold">Assets</th>
                    <th className="px-3 py-2 text-right font-semibold">Cost</th>
                    <th className="px-3 py-2 text-right font-semibold">Accumulated</th>
                    <th className="px-3 py-2 text-right font-semibold">Net block</th>
                  </tr>
                </thead>
                <tbody>
                  {result.by_category.map((c) => (
                    <tr key={c.asset_category} className="border-t border-ps-border">
                      <td className="px-3 py-1.5">{c.asset_category}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{c.assets}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{formatPaise(c.cost_paise)}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{formatPaise(c.accumulated_paise)}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{formatPaise(c.net_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {result.created > 0 && result.ledger_note && (
              <Callout tone="attention" title="Compare these totals with the ledger">
                {result.ledger_note}
              </Callout>
            )}

            {result.created > 0 && result.next_depreciation_month && (
              <p className="text-ps-body">
                The next depreciation run starts at {result.next_depreciation_month}, from each
                asset&apos;s stated position.
              </p>
            )}

            <GapList gaps={result.gaps} tone="withheld" title="Not recorded" bulleted />
            <GapList gaps={warnings} tone="attention" title="Check these" bulleted />

            <div className="flex justify-end">
              <button type="button" onClick={() => setStep("closed")}
                      className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark">
                Done
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
