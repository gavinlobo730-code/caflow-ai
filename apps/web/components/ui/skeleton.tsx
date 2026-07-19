import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { LogoIcon } from "@/components/LogoIcon";

/**
 * Shared loading primitives for PracticeSync. One source of truth so every
 * loading experience looks the same and never leaves the user staring at a
 * blank screen. Palette matches the app (slate: #F1F5F9 blocks, #E2E8F0
 * borders, #F8FAFC surfaces).
 *
 * Use a *skeleton* (content-shaped placeholder) whenever you know the shape of
 * what is loading (tables, cards, lists, forms). Use a *spinner / PageLoader*
 * only for short, shape-unknown waits. Skeletons should mirror the real layout
 * so there is no jump when data arrives.
 */

/** Base shimmer block. Compose these for any bespoke skeleton. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded bg-[#F1F5F9]", className)}
      {...props}
    />
  );
}

/** A few lines of text placeholder; the last line is shorter, like real text. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn("h-3", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** Inline spinner (lucide Loader2). Accessible label for screen readers. */
export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return <Loader2 className={cn("animate-spin", className)} role="status" aria-label={label} />;
}

/**
 * Centered loading state for a whole page/route or a large region that has no
 * obvious content shape. Fills its container so the page never appears blank.
 */
export function PageLoader({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("flex min-h-[40vh] w-full flex-col items-center justify-center gap-3 text-[#94A3B8]", className)}
    >
      <LogoIcon size="lg" spin />
      <p className="text-sm font-medium">{label}</p>
    </div>
  );
}

/**
 * Skeleton rows for any data table while loading. By default it renders its own
 * bordered card (standalone use). Pass `bare` to render just the header+rows
 * (no outer card) when embedding inside an existing card/table container.
 */
export function TableSkeleton({
  rows = 5,
  cols = 4,
  bare = false,
  className,
}: {
  rows?: number;
  cols?: number;
  bare?: boolean;
  className?: string;
}) {
  const header = (
    <div className="flex gap-4 border-b border-[#F1F5F9] bg-[#F8FAFC] px-4 py-3">
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton key={i} className="h-3 flex-1" />
      ))}
    </div>
  );
  const body = (
    <div className="divide-y divide-[#F1F5F9]">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-4 py-4">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className={cn("h-3 flex-1", c === 0 && "max-w-[40%]")} />
          ))}
        </div>
      ))}
    </div>
  );
  if (bare) {
    return (
      <div role="status" aria-label="Loading table" className={className}>
        {header}
        {body}
      </div>
    );
  }
  return (
    <div
      role="status"
      aria-label="Loading table"
      className={cn("overflow-hidden rounded-xl border border-[#E2E8F0] bg-white", className)}
    >
      {header}
      {body}
    </div>
  );
}

/** A single metric/KPI card placeholder. */
export function MetricCardSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-lg border border-[#E2E8F0] bg-white px-4 py-3", className)}>
      <Skeleton className="h-2.5 w-24" />
      <Skeleton className="mt-2 h-6 w-16" />
    </div>
  );
}

/** Row of metric cards — the typical dashboard summary bar. */
export function DashboardSkeleton({ cards = 4, className }: { cards?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading dashboard"
      className={cn("grid grid-cols-2 gap-3 sm:grid-cols-4", className)}
    >
      {Array.from({ length: cards }).map((_, i) => (
        <MetricCardSkeleton key={i} />
      ))}
    </div>
  );
}

/** Vertical list of rows (avatar + two lines) — directory/feed style lists. */
export function ListSkeleton({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading list" className={cn("space-y-3", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-lg border border-[#E2E8F0] bg-white px-4 py-3">
          <Skeleton className="h-10 w-10 shrink-0 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-2.5 w-32" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Grid of cards (e.g. templates, clients-as-cards). */
export function CardGridSkeleton({ count = 6, className }: { count?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-3 rounded-xl border border-[#E2E8F0] bg-white p-4">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
          <SkeletonText lines={2} />
        </div>
      ))}
    </div>
  );
}

/** Form field placeholders — for modals/drawers that hydrate from the server. */
export function FormSkeleton({ fields = 4, className }: { fields?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading form" className={cn("space-y-4", className)}>
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className="space-y-1.5">
          <Skeleton className="h-2.5 w-24" />
          <Skeleton className="h-9 w-full rounded-lg" />
        </div>
      ))}
    </div>
  );
}

/** Client-workspace header placeholder (avatar + name + meta chips). */
export function ClientHeaderSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-4 border-b border-[#E2E8F0] bg-white px-6 py-4", className)}>
      <Skeleton className="h-12 w-12 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-56" />
        <div className="flex gap-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
    </div>
  );
}

/** Vertical timeline placeholder (dot + line + text). */
export function TimelineSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading timeline" className={cn("space-y-4", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="mt-0.5 h-3 w-3 shrink-0 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-2.5 w-24" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Financial-statement placeholder — a captioned card with grouped, indented
 * line-item rows (label + amount) and a bold total per section. Mirrors the
 * P&L / Balance Sheet / Cash Flow / reconciliation layouts instead of a
 * single blank block.
 */
export function StatementSkeleton({
  sections = 2,
  rowsPerSection = 3,
  className,
}: {
  sections?: number;
  rowsPerSection?: number;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-label="Loading statement"
      className={cn("overflow-hidden rounded-xl border border-[#E2E8F0] bg-white", className)}
    >
      <div className="border-b border-[#F1F5F9] bg-[#F8FAFC] px-5 py-4">
        <Skeleton className="h-3 w-48" />
      </div>
      <div className="divide-y divide-[#F1F5F9] px-5 py-4">
        {Array.from({ length: sections }).map((_, s) => (
          <div key={s} className="space-y-2.5 py-3 first:pt-0 last:pb-0">
            <Skeleton className="h-2.5 w-32" />
            {Array.from({ length: rowsPerSection }).map((_, r) => (
              <div key={r} className="flex items-center justify-between pl-4">
                <Skeleton className="h-2.5 w-40" />
                <Skeleton className="h-2.5 w-16" />
              </div>
            ))}
            <div className="flex items-center justify-between pt-1">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-20" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Transaction/queue row placeholder — title+subtitle left, amount right, in a
 * single divided card. For bank-queue/approval-style lists that aren't a
 * plain data table.
 */
export function TransactionListSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading transactions"
      className={cn("overflow-hidden rounded-xl border border-[#E2E8F0] bg-white divide-y divide-[#F1F5F9]", className)}
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-start justify-between gap-4 px-4 py-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-2.5 w-1/3" />
          </div>
          <Skeleton className="h-3 w-16 shrink-0" />
        </div>
      ))}
    </div>
  );
}

/** Chart/report placeholder — a captioned box with faux bars. */
export function ChartSkeleton({ height = 240, className }: { height?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading chart"
      className={cn("rounded-xl border border-[#E2E8F0] bg-white p-4", className)}
    >
      <Skeleton className="mb-4 h-3 w-40" />
      <div className="flex items-end gap-2" style={{ height }}>
        {[60, 85, 45, 70, 95, 55, 80, 40, 65].map((h, i) => (
          <Skeleton key={i} className="flex-1 rounded-t" style={{ height: `${h}%` }} />
        ))}
      </div>
    </div>
  );
}
