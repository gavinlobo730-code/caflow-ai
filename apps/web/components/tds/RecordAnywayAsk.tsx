"use client";

/**
 * "Record it anyway": the CA's own second confirmation for a statement the product holds back (POST-A-402).
 *
 * The server refuses to record a TDS statement as CA approved or filed when it holds no deductees or its quarter has not ended, and
 * its refusal says the CA may record it anyway. The refusal used to end with an instruction no screen could follow ("Resubmit with
 * acknowledge_incomplete=true"), so a CA who had filed a statement on the portal that this product held nothing for (a shell made with
 * "New Return", or a quarter whose books are kept elsewhere) could not record that it was filed.
 *
 * What this draws is the server's sentence, verbatim, and two buttons. Nothing is decided here: the sentence is the server's, the
 * marker that brought this on screen is the server's, and the flag goes out only when the CA presses "Record it anyway", never by
 * itself and never on a first press. "Leave it as it is" sends nothing.
 */
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";

export function RecordAnywayAsk({
  sentence, what, onConfirm, onLeave, busy = false,
}: {
  /** The server's sentence, as it said it. */
  sentence: string;
  /** What pressing the button records the statement as, in words: "CA approved" or "filed". */
  what: string;
  /** Sends the request again with the CA's confirmation. May return a promise: the shared Button ignores a second press while it is out. */
  onConfirm: () => void | Promise<void>;
  onLeave: () => void;
  /** True while something else on the screen is out; the confirmation waits for it. */
  busy?: boolean;
}) {
  // role="alert": this REPLACES the refusal a screen reader used to be told about (an error paragraph, a problem callout), and it asks for an answer; an
  // attention callout has no role of its own, so without the wrapper a person pressing CA Approve or Confirm Filed with a screen reader heard nothing and
  // their focus went back to the button they had pressed. Focus is deliberately NOT moved onto "Record it anyway": a held Enter would confirm.
  return (
    <div role="alert">
      <Callout tone="attention" title="The product holds this statement back">
        <p>{sentence}</p>
        <p className="mt-1">
          If you have checked it yourself and it should be on record all the same, you can record it as {what}. The audit log keeps that you
          did, and what was incomplete.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="plain" size="none" onClick={onConfirm} disabled={busy}
            className="rounded border border-state-attention-border bg-white px-3 py-1 text-xs font-medium text-state-attention hover:bg-state-attention-hover disabled:opacity-50">
            Record it anyway
          </Button>
          <button type="button" onClick={onLeave} disabled={busy}
            className="rounded border border-ps-border bg-white px-3 py-1 text-xs font-medium text-ps-body hover:bg-ps-bg disabled:opacity-50">
            Leave it as it is
          </button>
        </div>
      </Callout>
    </div>
  );
}
