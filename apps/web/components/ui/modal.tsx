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
import { trapTabKey } from "@/lib/ui/focusTrap";
import { lockBodyScroll } from "@/lib/ui/scrollLock";

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
  // The latest onClose, read at the moment Escape is pressed. The effect below used to depend on `onClose`, so a parent that passes an
  // inline arrow (nearly all of them) re-ran it on EVERY parent render: the cleanup gave focus back to the opener and the setup then moved
  // it to the first field, so a parent that re-rendered while the person was in a later field (a date box commits on blur, a typed
  // field re-renders per keystroke) pulled the cursor away. It runs once, when the dialog opens and closes.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    restoreRef.current = (document.activeElement as HTMLElement) ?? null;
    // Focus the first form field (not the Close button) once mounted.
    const firstField = panelRef.current?.querySelector<HTMLElement>("input, select, textarea");
    (firstField ?? panelRef.current)?.focus();
    const unlockScroll = lockBodyScroll();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Capture phase + stopPropagation so Escape closes THIS dialog only and
        // does not also bubble to a parent Drawer's document listener (a Modal
        // may be rendered inside the Invoice Hub drawer).
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      trapTabKey(e, panelRef.current);
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      unlockScroll();
      restoreRef.current?.focus?.();
    };
  }, []);

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
          <h3 id={titleId} className="text-sm font-semibold text-ps-ink">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="text-ps-hint hover:text-ps-label rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X size={16} />
          </button>
        </div>
        {note && <p className="text-2xs text-ps-label">{note}</p>}
        {children}
      </div>
    </div>
  );
}
