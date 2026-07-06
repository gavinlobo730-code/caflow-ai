"use client";

/**
 * Modal — a reusable, accessible centered dialog (Batch 8 polish).
 *
 * Consolidates the three near-identical ad-hoc modal shells the Sales-Invoice
 * module grew (Compliance panel, Invoice Hub payment/credit-note, Service
 * Catalogue form) into one primitive, mirroring the Drawer's accessibility:
 *   • role="dialog" + aria-modal, labelled by its title;
 *   • Escape closes; a click on the backdrop (not the panel) closes;
 *   • focus moves to the first field on open and is restored to the opener
 *     on close; Tab is trapped within the dialog.
 */
import { useEffect, useRef, useId, type ReactNode } from "react";
import { X } from "lucide-react";

function focusables(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
    ),
  ).filter((n) => n.offsetParent !== null || n === document.activeElement);
}

export function Modal({
  title,
  note,
  onClose,
  children,
  maxWidthClass = "max-w-sm",
}: {
  title: string;
  note?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  maxWidthClass?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    restoreRef.current = (document.activeElement as HTMLElement) ?? null;
    // Focus the first form field (not the Close button) once mounted.
    const firstField = panelRef.current?.querySelector<HTMLElement>("input, select, textarea");
    (firstField ?? panelRef.current)?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Capture phase + stopPropagation so Escape closes THIS dialog only and
        // does not also bubble to a parent Drawer's document listener (a Modal
        // may be rendered inside the Invoice Hub drawer).
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab") {
        const items = focusables(panelRef.current);
        if (items.length === 0) return;
        const firstEl = items[0];
        const lastEl = items[items.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && active === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      restoreRef.current?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`relative w-full ${maxWidthClass} bg-white rounded-xl shadow-xl p-4 space-y-3 max-h-[90vh] overflow-y-auto outline-none`}
      >
        <div className="flex items-center justify-between gap-3">
          <h3 id={titleId} className="text-sm font-semibold text-[#0F172A]">{title}</h3>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-[#94A3B8] hover:text-[#475569] rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <X size={16} />
          </button>
        </div>
        {note && <p className="text-[11px] text-[#64748B]">{note}</p>}
        {children}
      </div>
    </div>
  );
}
