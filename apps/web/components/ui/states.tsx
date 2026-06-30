import * as React from "react";
import { AlertCircle, Inbox, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/skeleton";
import { resolveAsyncState } from "@/components/ui/async-state";

export { resolveAsyncState } from "@/components/ui/async-state";
export type { AsyncState } from "@/components/ui/async-state";

/**
 * Shared EMPTY and ERROR states + a small AsyncBoundary that picks the right
 * one. Keeps "loading" visually distinct from "no data" and from "it failed",
 * so the user is never left guessing.
 */

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      <div className="mb-3 text-[#CBD5E1]">{icon ?? <Inbox size={32} />}</div>
      <p className="text-sm font-semibold text-[#334155]">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-[#94A3B8]">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 px-6 py-10 text-center",
        className,
      )}
    >
      <AlertCircle size={28} className="mb-3 text-red-500" />
      <p className="text-sm font-semibold text-red-800">{title}</p>
      {message && <p className="mt-1 max-w-md text-xs text-red-600">{message}</p>}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100"
        >
          <RefreshCw size={14} />
          Try again
        </button>
      )}
    </div>
  );
}

/**
 * Renders exactly one of: error → loading skeleton → empty → content.
 * Drop-in for the common `if (loading) … if (error) … if (empty) …` ladder so
 * every async region behaves identically.
 *
 *   <AsyncBoundary
 *     loading={loading} error={error} isEmpty={rows.length === 0}
 *     onRetry={reload}
 *     skeleton={<TableSkeleton rows={6} />}
 *     empty={<EmptyState title="No invoices yet" />}
 *   >
 *     {table}
 *   </AsyncBoundary>
 */
export function AsyncBoundary({
  loading,
  error,
  isEmpty = false,
  onRetry,
  skeleton,
  empty,
  children,
}: {
  loading: boolean;
  error?: string | null;
  isEmpty?: boolean;
  onRetry?: () => void;
  skeleton?: React.ReactNode;
  empty?: React.ReactNode;
  children: React.ReactNode;
}) {
  const state = resolveAsyncState({ loading, error, isEmpty });
  if (state === "error") return <ErrorState message={error ?? undefined} onRetry={onRetry} />;
  if (state === "loading") {
    return (
      <>
        {skeleton ?? (
          <div className="flex min-h-[30vh] items-center justify-center text-[#94A3B8]">
            <Spinner className="h-5 w-5" />
          </div>
        )}
      </>
    );
  }
  if (state === "empty" && empty) return <>{empty}</>;
  return <>{children}</>;
}
