"use client";

/**
 * confirmDialog() and promptDialog() — Promise-based replacements for
 * window.confirm() and window.prompt() that render as a styled in-app dialog
 * instead of the browser's native chrome. Mirrors the module-level pub-sub
 * pattern used by useToast(): a single ConfirmDialogHost, mounted once in the
 * root layout, renders whichever question is currently pending.
 *
 * Usage (mirrors window.confirm's call shape so existing call sites need
 * only add `await`):
 *   if (!(await confirmDialog("Delete this record?"))) return;
 *   if (!(await confirmDialog({ message: "...", danger: true }))) return;
 *
 * A prompt answers with the TEXT, or `null` when it is cancelled — the same
 * two outcomes window.prompt had, so `if (reason === null) return;` still means
 * "the CA changed their mind":
 *   const reason = await promptDialog({ message: "Reason (required):", required: true });
 *   if (reason === null) return;
 *
 * WHY THE NATIVE ONES ARE GONE (frontend_ux-21). A native pop-up cannot be
 * styled, cannot say what a statutory action will do, blocks the page and any
 * automation in front of it, and looks like the browser asking rather than the
 * product. `no-alert` is an error in .eslintrc.json and
 * scripts/no-screen-uses-a-native-popup.test.ts holds it from the source side.
 *
 * ONE QUESTION AT A TIME, AND A SUPERSEDED ONE IS ANSWERED "NO". Asking while a
 * question is already open used to replace it and leave the first caller's
 * promise unresolved for ever. That was a stalled handler; behind a button with
 * a repeat-click guard (components/ui/button.tsx) it is a button that stays
 * disabled until the page is reloaded. The older question is now settled as
 * cancelled, which is the safe answer for a destructive one.
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

export type PromptOptions = ConfirmOptions & {
  /** The box's own label; the message above is the question. */
  label?: string;
  placeholder?: string;
  defaultValue?: string;
  /** The confirm button stays disabled until something other than blanks is typed. */
  required?: boolean;
  /** A textarea instead of a one-line input — for a reason that may be a sentence or two. */
  multiline?: boolean;
};

type PendingConfirm = ConfirmOptions & {
  kind: "confirm";
  id: number;
  resolve: (ok: boolean) => void;
};
type PendingPrompt = PromptOptions & {
  kind: "prompt";
  id: number;
  resolve: (value: string | null) => void;
};
type Pending = PendingConfirm | PendingPrompt;

let listeners: Array<(state: Pending | null) => void> = [];
let current: Pending | null = null;
let counter = 0;

function notify() {
  listeners.forEach((l) => l(current));
}

/** Answer whatever is open as "cancelled" — false for a confirm, null for a prompt. */
function cancelCurrent() {
  if (!current) return;
  const open = current;
  current = null;
  if (open.kind === "confirm") open.resolve(false);
  else open.resolve(null);
}

export function confirmDialog(options: ConfirmOptions | string): Promise<boolean> {
  const opts: ConfirmOptions = typeof options === "string" ? { message: options } : options;
  return new Promise((resolve) => {
    cancelCurrent();
    current = { ...opts, kind: "confirm", id: ++counter, resolve };
    notify();
  });
}

export function promptDialog(options: PromptOptions | string): Promise<string | null> {
  const opts: PromptOptions = typeof options === "string" ? { message: options } : options;
  return new Promise((resolve) => {
    cancelCurrent();
    current = { ...opts, kind: "prompt", id: ++counter, resolve };
    notify();
  });
}

function settleConfirm(ok: boolean) {
  if (!current || current.kind !== "confirm") return;
  const open = current;
  current = null;
  open.resolve(ok);
  notify();
}

function settlePrompt(value: string | null) {
  if (!current || current.kind !== "prompt") return;
  const open = current;
  current = null;
  open.resolve(value);
  notify();
}

function dismiss() {
  cancelCurrent();
  notify();
}

/** The text box, with its own state so typing does not re-render the host. */
function PromptField({ state }: { state: PendingPrompt }) {
  const [text, setText] = React.useState(state.defaultValue ?? "");
  const blank = text.trim() === "";
  const canSubmit = !state.required || !blank;
  const common = {
    id: "confirm-dialog-input",
    value: text,
    autoFocus: true,
    placeholder: state.placeholder,
    "aria-labelledby": state.label ? undefined : "confirm-dialog-message",
    "aria-label": state.label,
    className:
      "w-full rounded-lg border border-ps-border px-3 py-2 text-sm text-ps-ink " +
      "placeholder:text-ps-hint focus:outline-none focus:ring-2 focus:ring-brand",
  };
  const submit = () => { if (canSubmit) settlePrompt(text); };

  return (
    <>
      <div className="px-6 pb-5">
        {state.multiline ? (
          <textarea
            {...common}
            rows={3}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}
          />
        ) : (
          <input
            {...common}
            type="text"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
          />
        )}
      </div>
      <div className="px-6 py-4 border-t border-ps-border flex justify-end gap-2">
        <button
          onClick={() => settlePrompt(null)}
          className="px-4 py-2 text-sm text-ps-label rounded-lg border border-ps-border hover:bg-ps-bg"
        >
          {state.cancelLabel ?? "Cancel"}
        </button>
        <button
          onClick={submit}
          disabled={!canSubmit}
          className={`px-4 py-2 text-sm font-medium text-white rounded-lg disabled:opacity-40 ${
            state.danger ? "bg-red-600 hover:bg-red-700" : "bg-brand hover:bg-brand-dark"
          }`}
        >
          {state.confirmLabel ?? "OK"}
        </button>
      </div>
    </>
  );
}

/** Mount once (in app/layout.tsx, alongside <Toaster />). */
export function ConfirmDialogHost() {
  const [state, setState] = React.useState<Pending | null>(current);

  React.useEffect(() => {
    listeners.push(setState);
    return () => { listeners = listeners.filter((l) => l !== setState); };
  }, []);

  React.useEffect(() => {
    if (!state) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") dismiss();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state]);

  if (!state) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand-dark/60 p-4 print:hidden">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="bg-white rounded-2xl shadow-xl w-full max-w-md"
      >
        <div className="px-6 py-5 border-b border-ps-border flex items-center gap-2">
          {state.danger && <AlertTriangle size={18} className="text-amber-500 shrink-0" />}
          <h2 id="confirm-dialog-title" className="text-base font-semibold text-ps-ink">
            {state.title ?? (state.danger ? "Are you sure?" : state.kind === "prompt" ? "Please answer" : "Confirm")}
          </h2>
        </div>
        <div className={state.kind === "prompt" ? "px-6 pt-5 pb-3" : "px-6 py-5"}>
          <p id="confirm-dialog-message" className="text-sm text-ps-label whitespace-pre-line">
            {state.message}
          </p>
        </div>
        {state.kind === "prompt" ? (
          // Keyed on the question so a second prompt starts with an empty box.
          <PromptField key={state.id} state={state} />
        ) : (
          <div className="px-6 py-4 border-t border-ps-border flex justify-end gap-2">
            <button
              onClick={() => settleConfirm(false)}
              autoFocus={!state.danger}
              className="px-4 py-2 text-sm text-ps-label rounded-lg border border-ps-border hover:bg-ps-bg"
            >
              {state.cancelLabel ?? "Cancel"}
            </button>
            <button
              onClick={() => settleConfirm(true)}
              autoFocus={state.danger}
              className={`px-4 py-2 text-sm font-medium text-white rounded-lg ${
                state.danger ? "bg-red-600 hover:bg-red-700" : "bg-brand hover:bg-brand-dark"
              }`}
            >
              {state.confirmLabel ?? (state.danger ? "Delete" : "OK")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
