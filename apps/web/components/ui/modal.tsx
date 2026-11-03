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
 *     on close; Tab is trapped within the dialog;
 *   • dialogs STACK (a dialog opened from inside another, a confirmation shown
 *     over one): only the top one acts on Escape, kept in lib/ui/overlayStack
 *     (POST-A-128). `footer` is a bar pinned to the bottom of the panel, for a
 *     dialog whose buttons must stay in view while its body scrolls.
 */
import { useEffect, useRef, useId, type ReactNode } from "react";
import { X } from "lucide-react";
import { trapTabKey } from "@/lib/ui/focusTrap";
import { lockBodyScroll } from "@/lib/ui/scrollLock";
import { closeAfterTheFocusedDateCommits } from "@/lib/dates/closeAfterDateCommit";
import { openOverlay } from "@/lib/ui/overlayStack";

export function Modal({
  title,
  note,
  onClose,
  children,
  footer,
  maxWidthClass = "max-w-sm",
}: {
  title: string;
  note?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Buttons that stay in view at the bottom of the panel while the body scrolls. */
  footer?: ReactNode;
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
    const overlay = openOverlay();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Only the TOP dialog acts: a dialog opened over this one hears the same press and closes itself, and this one stays (POST-A-128).
        if (!overlay.isTop()) return;
        // Capture phase + stopPropagation so Escape closes THIS dialog only and
        // does not also bubble to a parent Drawer's document listener (a Modal
        // may be rendered inside the Invoice Hub drawer).
        e.stopPropagation();
        // A date box commits on blur: with the cursor in one, it is left first and the close (which may ask about unsaved typing) runs on
        // the next tick, by the closure that has seen the date (POST-A-126).
        closeAfterTheFocusedDateCommits(() => onCloseRef.current());
        return;
      }
      trapTabKey(e, panelRef.current);
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.close();
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
        {footer && (
          <div className="sticky bottom-0 -mx-4 -mb-4 flex items-center justify-end gap-2 rounded-b-xl border-t border-ps-border bg-white px-4 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
