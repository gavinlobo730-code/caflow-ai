"use client";

/**
 * THE SWITCH FOR GUIDED TIPS, ON THE "YOUR PROFILE" TAB OF SETTINGS (POST-A-531).
 *
 * It is the person's own setting, kept by the server on their own row, so it is the same on every device and a colleague's
 * is untouched. The card says what the switch IS (the server's answer) and never what was last clicked: a press is shown as
 * done only when the server has kept it, and a refusal or a failed call says so in a sentence and leaves the switch where it
 * was. A setting that could not be read is said to be unread, because a switch drawn "off" would be a statement.
 */
import { useState } from "react";
import { Lightbulb } from "lucide-react";
import { useGuidedTips } from "@/lib/tips/GuidedTipsContext";
import { LoadingRegion, SkeletonText } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export function GuidedTipsCard() {
  const { state, settled, setOn, showAgain } = useGuidedTips();
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ tone: "done" | "problem"; text: string } | null>(null);

  const act = async (call: () => Promise<string | null>, done: string) => {
    setBusy(true);
    setSaid(null);
    try {
      const failed = await call();
      setSaid(failed ? { tone: "problem", text: failed } : { tone: "done", text: done });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden" data-guided-tips-card>
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
        <Lightbulb size={15} className="text-ps-label" />
        <h2 className="text-sm font-semibold text-ps-ink">Guided tips</h2>
      </div>
      <div className="px-5 py-4 space-y-3">
        {!settled && <LoadingRegion label="Loading your tips setting"><SkeletonText lines={2} /></LoadingRegion>}
        {settled && !state && (
          <p role="alert" className="text-sm text-state-problem">
            Your tips setting could not be read just now, so it is not shown. Reload the page to try again.
          </p>
        )}
        {state && (
          <>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm text-ps-body">Show tips that explain a screen</p>
                <p className="text-xs text-ps-hint">
                  A short pop-up beside a button says what it is for, once, until you close it. This is your own setting,
                  on every device you sign in on; your colleagues choose their own.
                </p>
              </div>
              <Button
                variant="plain" size="none" spinner={false}
                role="switch"
                aria-checked={state.on}
                aria-label="Show guided tips"
                disabled={busy}
                onClick={() => act(() => setOn(!state.on), state.on ? "Tips are off." : "Tips are on.")}
                className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${state.on ? "bg-brand" : "bg-ps-border-strong"}`}
              >
                <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${state.on ? "translate-x-5" : "translate-x-0.5"}`} />
              </Button>
            </div>
            <div className="flex items-center justify-between gap-4 border-t border-ps-border pt-3">
              <p className="text-xs text-ps-hint">
                {state.seen.length === 0
                  ? "You have not closed any tip yet."
                  : `You have closed ${state.seen.length} tip${state.seen.length === 1 ? "" : "s"}. They are not shown again unless you ask.`}
              </p>
              <Button
                variant="plain" size="none"
                disabled={busy || state.seen.length === 0}
                onClick={() => act(showAgain, "Every tip will be shown again.")}
                className="shrink-0 rounded-lg border border-ps-border px-3 py-1.5 text-xs font-medium text-ps-body hover:bg-ps-bg disabled:opacity-50"
              >
                Show every tip again
              </Button>
            </div>
          </>
        )}
        {/* On the page before anything is put in it, so the result of a press is announced. */}
        <p role="status" className={`text-xs ${said?.tone === "problem" ? "text-state-problem" : "text-state-ready"} empty:hidden`}>{said?.text ?? ""}</p>
      </div>
    </div>
  );
}
