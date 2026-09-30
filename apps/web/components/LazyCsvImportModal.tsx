"use client";

import dynamic from "next/dynamic";

/**
 * The import modal, loaded when somebody opens it and not before.
 *
 * Ten screens import this — the client list, client Sales, Purchases and
 * Payroll, onboarding, /tds, payroll people and attendance, the firm HSN
 * library and the catalogue panel — and each of them renders the modal only
 * after a click on "Import". Importing `CsvImportModal` directly put its whole
 * source (and, until the spreadsheet library was made a lazy import inside it,
 * SheetJS with it) into the first load of every one of those screens. This is
 * the ONE door the screens take instead, so a screen cannot opt back in by
 * accident and there is no second way to write `dynamic(...)` for it.
 *
 * `ssr: false` is accurate rather than a workaround: the modal reads `window`
 * for its Escape handler and `FileReader` for the chosen file, and `apps/web`
 * is a static export, so there is no server render to skip.
 *
 * TYPES STAY WHERE THEY ARE. `ImportRow`, `ImportResult`, `CsvColumn` and
 * `ReferenceResolver` are still imported from `@/components/CsvImportModal`,
 * with `import type` — that import is erased at build time and pulls nothing
 * in. Only the COMPONENT comes from here.
 *
 * `loading` is a real overlay, not `null`: the click that opens the modal must
 * visibly do something in the tens of milliseconds before its chunk arrives, or
 * a CA on a slow line clicks Import twice.
 */
const LazyCsvImportModal = dynamic(() => import("@/components/CsvImportModal"), {
  ssr: false,
  loading: () => (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ps-bg/60 p-4"
    >
      <div className="rounded-2xl bg-white px-6 py-4 text-sm text-ps-label shadow-xl">
        Opening the importer…
      </div>
    </div>
  ),
});

export default LazyCsvImportModal;
