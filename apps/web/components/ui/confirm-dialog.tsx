"use client";

/**
 * confirmDialog() — a drop-in, Promise-based replacement for window.confirm()
 * that renders as a styled in-app dialog instead of the browser's native
 * chrome. Mirrors the module-level pub-sub pattern used by useToast(): a
 * single ConfirmDialogHost, mounted once in the root layout, renders
 * whichever confirmation is currently pending.
 *
 * Usage (mirrors window.confirm's call shape so existing call sites need
 * only add `await`):
 *   if (!(await confirmDialog("Delete this record?"))) return;
 *   if (!(await confirmDialog({ message: "...", danger: true }))) return;
 */
import * as React from "react";
import { AlertTriangle } from "lucide-react";

export type ConfirmOptions = {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the icon/confirm button as destructive (red) instead of primary (blue). */
  danger?: boolean;
};

type PendingConfirm = ConfirmOptions & {
  id: number;
  resolve: (ok: boolean) => void;
};

let listeners: Array<(state: PendingConfirm | null) => void> = [];
let current: PendingConfirm | null = null;
let counter = 0;

function notify() {
  listeners.forEach((l) => l(current));
}

export function confirmDialog(options: ConfirmOptions | string): Promise<boolean> {
  const opts: ConfirmOptions = typeof options === "string" ? { message: options } : options;
  return new Promise((resolve) => {
    current = { ...opts, id: ++counter, resolve };
    notify();
  });
}

function settle(ok: boolean) {
  if (!current) return;
  current.resolve(ok);
  current = null;
  notify();
}

/** Mount once (in app/layout.tsx, alongside <Toaster />). */
export function ConfirmDialogHost() {
  const [state, setState] = React.useState<PendingConfirm | null>(current);

  React.useEffect(() => {
    listeners.push(setState);
    return () => { listeners = listeners.filter((l) => l !== setState); };
  }, []);

  React.useEffect(() => {
    if (!state) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") settle(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state]);

  if (!state) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand-dark/60 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="bg-white rounded-2xl shadow-xl w-full max-w-md"
      >
        <div className="px-6 py-5 border-b border-ps-muted flex items-center gap-2">
          {state.danger && <AlertTriangle size={18} className="text-amber-500 shrink-0" />}
          <h2 id="confirm-dialog-title" className="text-base font-semibold text-ps-ink">
            {state.title ?? (state.danger ? "Are you sure?" : "Confirm")}
          </h2>
        </div>
        <div className="px-6 py-5">
          <p id="confirm-dialog-message" className="text-sm text-ps-label whitespace-pre-line">
            {state.message}
          </p>
        </div>
        <div className="px-6 py-4 border-t border-ps-muted flex justify-end gap-2">
          <button
            onClick={() => settle(false)}
            autoFocus={!state.danger}
            className="px-4 py-2 text-sm text-ps-label rounded-lg border border-ps-border hover:bg-ps-bg"
          >
            {state.cancelLabel ?? "Cancel"}
          </button>
          <button
            onClick={() => settle(true)}
            autoFocus={state.danger}
            className={`px-4 py-2 text-sm font-medium text-white rounded-lg ${
              state.danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {state.confirmLabel ?? (state.danger ? "Delete" : "OK")}
          </button>
        </div>
      </div>
    </div>
  );
}
