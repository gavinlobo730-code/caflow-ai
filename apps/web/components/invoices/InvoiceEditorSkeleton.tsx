/**
 * Shaped loading skeletons for the Invoice Editor (Batch 8 follow-up — density
 * audit fix). Mirror the REAL editor's carded, two-column layout so the
 * workspace never collapses to a bare, uncarded placeholder while data loads
 * (docs/audits/2026-07-06-sales-invoice-workspace-density-audit.md, F1/F2).
 *
 * `InvoiceEditorSkeleton` mirrors the left column (party block + line grid +
 * notes, each in the same white bordered card the loaded editor uses).
 * `SummaryPanelSkeleton` mirrors the sticky right rail so the two-column
 * silhouette — and the toolbar's disabled buttons — are visible immediately,
 * exactly as the Blueprint specifies ("skeleton for header + grid rows;
 * summary → shimmer").
 */
import { Skeleton } from "@/components/ui/skeleton";

const CARD = "bg-white rounded-xl border border-ps-border p-4";

function FieldSkeleton({ wide }: { wide?: boolean }) {
  return (
    <div className={`space-y-1.5 ${wide ? "col-span-2" : ""}`}>
      <Skeleton className="h-2.5 w-16" />
      <Skeleton className="h-8 w-full rounded-lg" />
    </div>
  );
}

function LineRowSkeleton() {
  return (
    <div className="flex items-center gap-2 py-1.5">
      <Skeleton className="h-7 flex-[2] rounded" />
      <Skeleton className="h-7 w-24 rounded" />
      <Skeleton className="h-7 w-12 rounded" />
      <Skeleton className="h-7 w-12 rounded" />
      <Skeleton className="h-7 w-16 rounded" />
      <Skeleton className="h-7 w-14 rounded" />
      <Skeleton className="h-7 w-16 rounded" />
    </div>
  );
}

export function InvoiceEditorSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading invoice editor">
      {/* Party + metadata card */}
      <section className={CARD}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <FieldSkeleton wide />
          <FieldSkeleton />
          <FieldSkeleton />
          <FieldSkeleton />
          <FieldSkeleton />
          <FieldSkeleton />
        </div>
      </section>

      {/* Line items card */}
      <section className={CARD}>
        <div className="flex items-center justify-between mb-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-40 rounded-lg" />
        </div>
        <div className="flex items-center gap-2 pb-2 border-b border-ps-border">
          <Skeleton className="h-2.5 flex-[2]" />
          <Skeleton className="h-2.5 w-24" />
          <Skeleton className="h-2.5 w-12" />
          <Skeleton className="h-2.5 w-12" />
          <Skeleton className="h-2.5 w-16" />
          <Skeleton className="h-2.5 w-14" />
          <Skeleton className="h-2.5 w-16" />
        </div>
        <div className="divide-y divide-ps-border">
          <LineRowSkeleton />
          <LineRowSkeleton />
          <LineRowSkeleton />
        </div>
        <Skeleton className="mt-3 h-3 w-20" />
      </section>

      {/* Notes card */}
      <section className={CARD}>
        <Skeleton className="h-2.5 w-14 mb-1.5" />
        <Skeleton className="h-14 w-full rounded-lg" />
      </section>
    </div>
  );
}

export function SummaryPanelSkeleton() {
  return (
    <div className={`${CARD} space-y-3`} role="status" aria-label="Loading summary">
      <Skeleton className="h-3 w-20" />
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex justify-between">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-2.5 w-16" />
          </div>
        ))}
      </div>
      <div className="border-t border-ps-border pt-2 flex justify-between">
        <Skeleton className="h-3.5 w-16" />
        <Skeleton className="h-3.5 w-20" />
      </div>
      <div className="border-t border-ps-border pt-2 space-y-2">
        <div className="flex justify-between">
          <Skeleton className="h-2.5 w-14" />
          <Skeleton className="h-2.5 w-16" />
        </div>
      </div>
      <Skeleton className="h-2.5 w-4/5" />
    </div>
  );
}

/** A non-interactive stand-in for the toolbar while the editor is loading —
 * keeps the sticky action-bar region present (visually) instead of blank. */
export function InvoiceToolbarSkeleton() {
  return (
    <>
      <Skeleton className="mr-auto h-7 w-14 rounded-lg" />
      <Skeleton className="h-7 w-24 rounded-lg" />
      <Skeleton className="h-7 w-28 rounded-lg" />
      <Skeleton className="h-7 w-28 rounded-lg" />
    </>
  );
}

/**
 * The Invoice Hub drawer's loading state (POST-A-150, the audit's F2 residue). It mirrors the LOADED drawer's silhouette, top to bottom:
 * customer and grand total, the status and compliance chips, the six detail rows in two columns, the action bar, the line-item table and the
 * accounting rows. The drawer used to show a generic form and table skeleton, which looked like neither.
 */
export function InvoiceHubSkeleton() {
  return (
    <div className="p-5 space-y-5" role="status" aria-label="Loading invoice">
      {/* Customer and grand total */}
      <section className="space-y-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1.5">
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="h-2.5 w-28" />
          </div>
          <div className="space-y-1.5 flex flex-col items-end">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-2.5 w-16" />
          </div>
        </div>
        {/* Status chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Skeleton className="h-4 w-14 rounded-full" />
          <Skeleton className="h-4 w-16 rounded-full" />
          <Skeleton className="h-4 w-12 rounded-full" />
          <Skeleton className="h-4 w-14 rounded-full" />
        </div>
        {/* Six detail rows, two columns */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-1">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex justify-between gap-2">
              <Skeleton className="h-2.5 w-16" />
              <Skeleton className="h-2.5 w-20" />
            </div>
          ))}
        </div>
      </section>

      {/* Action bar */}
      <div className="flex flex-wrap gap-2 pt-1">
        <Skeleton className="h-7 w-16 rounded-lg" />
        <Skeleton className="h-7 w-20 rounded-lg" />
        <Skeleton className="h-7 w-28 rounded-lg" />
        <Skeleton className="h-7 w-16 rounded-lg" />
      </div>

      {/* Line items */}
      <section>
        <Skeleton className="h-3 w-20 mb-2" />
        <div className="border border-ps-border rounded-lg p-2 space-y-1.5">
          <Skeleton className="h-2.5 w-full" />
          <div className="divide-y divide-ps-border">
            <LineRowSkeleton />
            <LineRowSkeleton />
            <LineRowSkeleton />
          </div>
        </div>
      </section>

      {/* Accounting rows */}
      <section className="space-y-2">
        <Skeleton className="h-3 w-24" />
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex justify-between gap-2">
            <Skeleton className="h-2.5 w-24" />
            <Skeleton className="h-2.5 w-28" />
          </div>
        ))}
      </section>
    </div>
  );
}
