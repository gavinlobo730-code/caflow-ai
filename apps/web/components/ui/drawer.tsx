"use client";

/**
 * Drawer — a reusable right-side slide-over sheet (Batch 2).
 *
 * Extracted from the bespoke overlay the Sales invoice detail view used inline, so
 * every workspace surface shares one accessible, responsive sheet. Behaviour mirrors
 * the original: a dimmed click-away overlay, a right-anchored white panel that scrolls
 * its own body, and a sticky header with a close button. On small screens the panel
 * goes full-width (a mobile sheet).
 *
 * Accessibility: role="dialog" + aria-modal, labelled by its title; Escape closes;
 * focus moves into the panel on open and is restored to the previously focused element
 * on close; a click on the overlay (but not the panel) closes.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  /** Header content (e.g. the invoice number). Omit to render a header-less sheet. */
  title?: ReactNode;
  /** Max-width utility for the panel on ≥sm screens. Full-width below sm. */
  widthClass?: string;
  /** Accessible name when `title` is not a plain string. */
  ariaLabel?: string;
  children: ReactNode;
}

export function Drawer({
  open,
  onClose,
  title,
  widthClass = "sm:max-w-md",
  ariaLabel,
  children,
}: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  // Escape-to-close + focus management. Only active while open.
  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = (document.activeElement as HTMLElement) ?? null;
    panelRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Restore focus to whatever opened the drawer (row action / link).
      restoreFocusRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : ariaLabel}
        tabIndex={-1}
        className={`relative w-full ${widthClass} bg-white h-full shadow-xl overflow-y-auto outline-none`}
      >
        {title !== undefined && (
          <div className="sticky top-0 bg-white border-b border-[#F1F5F9] px-5 py-3 flex items-center justify-between z-10">
            <h3 className="text-sm font-semibold text-[#0F172A] font-mono">{title}</h3>
            <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]" aria-label="Close">
              <X size={16} />
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
