"use client";

/**
 * InvoiceWorkspaceLayout — the Sales-Invoice workspace SHELL (Batch 2).
 *
 * Layout only: breadcrumbs, a page header (title + status pill + unsaved hint), a
 * sticky action toolbar, and a responsive two-column body (main editor + an optional
 * sticky summary rail on ≥lg). Below lg it collapses to a single column; the toolbar
 * stays sticky so the primary actions are always reachable (mobile shell).
 *
 * It is presentational — the editor content, the Save & Issue/Send actions, and the
 * summary panel are supplied by the caller and evolve in later batches.
 */
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

export interface Crumb {
  label: string;
  href?: string;
}

export interface InvoiceWorkspaceLayoutProps {
  breadcrumbs: Crumb[];
  title: ReactNode;
  /** Small status pill (e.g. "Draft") shown beside the title. */
  statusPill?: ReactNode;
  /** Right-aligned hint under the header, e.g. "Unsaved changes". */
  dirtyHint?: ReactNode;
  /** Sticky toolbar content (actions). Optional in the shell. */
  toolbar?: ReactNode;
  /** Optional sticky right rail (summary panel) — rendered on ≥lg when provided. */
  summary?: ReactNode;
  children: ReactNode;
}

export function InvoiceWorkspaceLayout({
  breadcrumbs,
  title,
  statusPill,
  dirtyHint,
  toolbar,
  summary,
  children,
}: InvoiceWorkspaceLayoutProps) {
  return (
    <div className="max-w-screen-2xl mx-auto px-6 pt-4 pb-24 lg:pt-5 lg:pb-6">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-[#94A3B8] mb-2 flex-wrap">
        {breadcrumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight size={12} className="text-[#CBD5E1]" />}
            {c.href ? (
              <Link href={c.href} className="hover:text-[#334155]">{c.label}</Link>
            ) : (
              <span className="text-[#475569]">{c.label}</span>
            )}
          </span>
        ))}
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-lg font-semibold text-[#0F172A] truncate">{title}</h1>
          {statusPill}
        </div>
        {dirtyHint && <div className="text-xs text-[#94A3B8] flex-shrink-0">{dirtyHint}</div>}
      </div>

      {/* Sticky toolbar (actions). On mobile it pins to the bottom of the viewport. */}
      {toolbar && (
        <div className="sticky top-0 z-20 hidden lg:flex items-center justify-end gap-2 bg-[#F8FAFC]/90 backdrop-blur border-b border-[#F1F5F9] py-2 mb-4">
          {toolbar}
        </div>
      )}

      {/* Body — two columns on ≥lg (editor + sticky summary rail), single below. */}
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="flex-1 min-w-0">{children}</div>
        {summary && (
          <aside className="lg:w-[320px] lg:flex-shrink-0">
            <div className="lg:sticky lg:top-16">{summary}</div>
          </aside>
        )}
      </div>

      {/* Mobile sticky action bar */}
      {toolbar && (
        <div className="fixed bottom-0 inset-x-0 z-30 flex lg:hidden items-center justify-end gap-2 bg-white border-t border-[#E2E8F0] px-4 py-2.5 shadow-[0_-2px_8px_rgba(0,0,0,0.04)]">
          {toolbar}
        </div>
      )}
    </div>
  );
}
