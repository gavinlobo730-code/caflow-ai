"use client";

/**
 * "PRICE INCLUDING GST": TYPE THE PRICE YOU HAVE, AND THE SERVER WORKS OUT THE RATE BEFORE TAX (POST-A-490).
 *
 * A person raising a sales invoice often knows only the price including GST. This box takes that figure for one line and
 * asks the server which unit rate before tax it stands for. `lib/invoices/inclusivePrice.ts` builds the question from what
 * was typed and reads the answer; this draws them.
 *
 * NO ARITHMETIC HAPPENS HERE. Every figure shown is the server's, formatted, and the sentence explaining them is the
 * server's own. Where no rate reaches the typed figure exactly (a unit rate is a whole number of paise and the GST on a line
 * is rounded down), the server says by how much and the box shows that in the attention colour: the difference is never
 * hidden and never rounded away here.
 *
 * NOTHING CHANGES UNTIL THE PERSON ACCEPTS. "Use this rate" writes the server's rate into the line's rate box, and the line
 * is then an ordinary line: the invoice stores quantity and rate, as it always did.
 */
import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { api } from "@/lib/api";
import { formatPaise } from "@/lib/money/format";
import {
  inclusiveAnswer, inclusiveQuestion, rateBoxText, type InclusiveAnswer, type InclusiveBasis, type LineFacts,
} from "@/lib/invoices/inclusivePrice";

export function InclusivePriceDialog({
  clientId, lineNumber, line, onUse, onClose,
}: {
  clientId: string;
  /** The line's position as the person counts it, from 1. */
  lineNumber: number;
  line: LineFacts;
  /** Called with the text for the line's rate box when the person accepts the answer. */
  onUse: (rate: string) => void;
  onClose: () => void;
}) {
  const [price, setPrice] = useState("");
  const [basis, setBasis] = useState<InclusiveBasis>("line");
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [answer, setAnswer] = useState<InclusiveAnswer | null>(null);
  const priceId = useId();
  const figures = answer;

  async function work() {
    if (asking) return;
    setProblem(null);
    setAnswer(null);
    const built = inclusiveQuestion(clientId, price, basis, line);
    if ("problem" in built) { setProblem(built.problem); return; }
    setAsking(true);
    try {
      const got = inclusiveAnswer(await api.salesInvoices.inclusiveRate(built.question));
      if (!got) throw new Error("The server's answer could not be read. Nothing was changed; try again.");
      setAnswer(got);
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : "The rate could not be worked out. Nothing was changed; try again.");
    } finally {
      setAsking(false);
    }
  }

  return (
    <Modal
      title={`Line ${lineNumber}: price including GST`}
      onClose={onClose}
      maxWidthClass="max-w-md"
      footer={figures ? (
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={() => { onUse(rateBoxText(figures)); onClose(); }} data-inclusive-use="">
            Use {formatPaise(figures.rate_paise)} as the rate
          </Button>
        </div>
      ) : undefined}
    >
      <form onSubmit={(e) => { e.preventDefault(); void work(); }} className="space-y-3" data-inclusive-price="">
        <p className="text-xs text-ps-label">
          Type the price including GST. The rate before tax is worked out from this line&apos;s quantity, GST rate and discount as
          they stand now, and nothing changes until you accept it.
        </p>
        <div>
          <label htmlFor={priceId} className="block text-xs font-medium text-ps-ink">Price including GST (₹)</label>
          <input
            id={priceId}
            inputMode="decimal"
            autoComplete="off"
            value={price}
            onChange={(e) => { setPrice(e.target.value); setAnswer(null); }}
            placeholder="11800.00"
            aria-invalid={problem ? true : undefined}
            className="mt-1 w-full rounded-lg border border-ps-border px-3 py-2 text-right text-sm text-ps-ink placeholder:text-ps-hint focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          />
        </div>
        <fieldset>
          <legend className="text-xs font-medium text-ps-ink">This price is for</legend>
          <div className="mt-1 flex gap-4 text-sm text-ps-body">
            <label className="flex items-center gap-1.5">
              <input type="radio" name="inclusive-basis" checked={basis === "line"} onChange={() => { setBasis("line"); setAnswer(null); }} />
              the whole line
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" name="inclusive-basis" checked={basis === "unit"} onChange={() => { setBasis("unit"); setAnswer(null); }} />
              one unit
            </label>
          </div>
        </fieldset>
        <Button type="submit" variant="outline" disabled={asking}>{asking ? "Working it out…" : "Work out the rate"}</Button>
      </form>

      <div aria-live="polite" className="mt-3" data-inclusive-answer={figures ? (figures.exact ? "exact" : "nearest") : problem ? "problem" : "none"}>
        {problem && <Callout tone="problem">{problem}</Callout>}
        {figures && (
          <Callout tone={figures.exact ? "note" : "attention"} title={figures.exact ? "Exact" : "Nearest rate, not exact"}>
            <p>{figures.sentence}</p>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-ps-label">Rate before GST, a unit</dt><dd className="text-right font-medium">{formatPaise(figures.rate_paise)}</dd>
              <dt className="text-ps-label">Line value before GST</dt><dd className="text-right">{formatPaise(figures.taxable_paise)}</dd>
              <dt className="text-ps-label">GST</dt><dd className="text-right">{formatPaise(figures.tax_paise)}</dd>
              <dt className="text-ps-label">Line total</dt><dd className="text-right font-medium">{formatPaise(figures.total_paise)}</dd>
            </dl>
            <p className="mt-2 text-xs text-ps-label">A discount on the whole invoice, if there is one, is taken off after this.</p>
          </Callout>
        )}
      </div>
    </Modal>
  );
}
