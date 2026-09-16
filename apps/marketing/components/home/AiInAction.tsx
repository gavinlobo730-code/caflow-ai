"use client";

import { useEffect, useRef, useState } from "react";
import { useInView, usePrefersReducedMotion } from "../motion";
import { Sparkles } from "../icons";

/**
 * AI in action (brief §8).
 *
 * "Avoid making AI feel like a separate chatbot feature. Present AI as
 * intelligence working across the practice… Show the AI doing useful practice
 * work rather than simply answering questions. Any AI capability claims must
 * match the actual product."
 *
 * So this is ONE REAL CHAIN rather than a list of adjectives, and every link in
 * it is a shipped surface:
 *
 *   1. the client portal, where a client uploads what you asked them for;
 *   2. document intelligence — Gemini for a photographed bill, Groq for a typed
 *      PDF (two providers because Groq's vision models 404 on this account);
 *   3. domain/tds/section_rates.py, which resolves the section as the bill is
 *      entered and knows §194J aggregates over the year;
 *   4. the posting kernel, which is the only path to the general ledger;
 *   5. domain/gst/itc_matching.py, which is what §16(2)(aa) actually turns on;
 *   6. the deadline tracker and the notification sweep.
 *
 * THE LAST STEP IS THE ONE THAT MATTERS AND IT IS A REFUSAL. Nothing in the
 * chain files anything. The AI prepares, flags and reminds; a Chartered
 * Accountant confirms and files on the portal themselves. Putting that at the
 * END of an AI section, where a reader expects the triumphant claim, is
 * deliberate.
 *
 * The chain plays through as it scrolls into view — sequentially, not all at
 * once, because the sequence IS the content. Under reduced motion every step is
 * present immediately.
 */

const STEPS = [
  {
    surface: "Client portal",
    title: "Your client sends a photo of a purchase bill",
    body: "They upload it to the portal you invited them to, against the document you asked for. No email thread, no WhatsApp forward to chase.",
  },
  {
    surface: "Document intelligence",
    title: "It is read — supplier, GSTIN, lines, rate, tax",
    body: "A photographed bill goes to a vision model; a typed PDF goes to the text one. What comes back is a draft you check, not a figure you type.",
  },
  {
    surface: "TDS engine",
    title: "The section resolves as the bill is entered",
    body: "A professional fee is §194J — and because §194J charges on the year's aggregate, the bill that crosses the limit carries the tax for everything before it too.",
  },
  {
    surface: "Posting kernel",
    title: "It posts once, through the one path to the ledger",
    body: "Expense, input tax, TDS withheld and the payable, in integer paise, asserted to balance before the entry is written.",
  },
  {
    surface: "GSTR-2B reconciliation",
    title: "Then the portal file says the supplier has not filed it",
    body: "So the credit is held back rather than claimed — §16(2)(aa) — and the bill is on the list of suppliers to chase, not the list of documents to find.",
  },
  {
    surface: "Deadlines & notifications",
    title: "The team is told, and the date is on the calendar",
    body: "GSTR-1 on the 11th, GSTR-3B on the 20th, per client, per GSTIN — watched for you rather than remembered by you.",
  },
];

export function AiInAction() {
  const { ref, inView } = useInView<HTMLDivElement>();
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState(0);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setShown(STEPS.length);
      return;
    }
    // One timer per step rather than an interval, so unmounting mid-sequence
    // cannot leave a tick running against a dead component.
    timers.current = STEPS.map((_, i) =>
      window.setTimeout(() => setShown(i + 1), 220 + i * 520)
    );
    const ids = timers.current;
    return () => ids.forEach((id) => window.clearTimeout(id));
  }, [inView, reduced]);

  const progress = STEPS.length > 1 ? (Math.max(0, shown - 1) / (STEPS.length - 1)) * 100 : 0;

  return (
    <div ref={ref} className="relative mt-14">
      <ol className="relative">
        {/* The rail, and the line that fills along it as the chain plays. */}
        <span
          aria-hidden="true"
          className="absolute left-[15px] top-3 h-[calc(100%-28px)] w-px bg-slate-900/10 md:left-[19px]"
        />
        <span
          aria-hidden="true"
          className="absolute left-[15px] top-3 w-px bg-gradient-to-b from-brand via-brand to-brand-light md:left-[19px]"
          style={{
            height: `calc((100% - 28px) * ${progress / 100})`,
            transition: reduced ? "none" : "height 520ms cubic-bezier(0.16,1,0.3,1)",
          }}
        />

        {STEPS.map((s, i) => {
          const on = i < shown;
          return (
            <li
              key={s.title}
              className="relative flex gap-5 pb-9 last:pb-0 md:gap-7"
              style={{
                opacity: on ? 1 : 0.28,
                transform: on ? "none" : "translateY(10px)",
                transition: reduced
                  ? "none"
                  : "opacity 600ms cubic-bezier(0.16,1,0.3,1), transform 600ms cubic-bezier(0.16,1,0.3,1)",
              }}
            >
              <span
                className={`relative z-[1] grid h-[31px] w-[31px] shrink-0 place-items-center rounded-full border text-[12px] font-semibold transition-colors duration-500 md:h-[39px] md:w-[39px] md:text-[13px] ${
                  on
                    ? "border-brand/30 bg-brand text-white"
                    : "border-slate-900/10 bg-white text-slate-400"
                }`}
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="min-w-0 pt-1">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/15 bg-brand/[0.05] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-brand">
                  {i === 1 ? <Sparkles size={11} /> : null}
                  {s.surface}
                </span>
                <span className="mt-3 block text-[17px] font-semibold leading-snug text-brand-dark md:text-[19px]">
                  {s.title}
                </span>
                <span className="mt-2 block max-w-[62ch] text-[15px] leading-[1.7] text-slate-600">
                  {s.body}
                </span>
              </span>
            </li>
          );
        })}
      </ol>

      <div className="mt-12 rounded-2xl border border-gold/30 bg-gold/[0.06] p-6 md:p-8">
        <p className="text-[15px] leading-relaxed text-brand-dark md:text-[16px]">
          <span className="font-semibold">And then it stops.</span> Nothing in that chain
          files anything. PracticeSync computes the return, reconciles it and hands you a
          file that is ready to submit — a Chartered Accountant uploads and signs it on the
          government portal, and records it back here. The software never transmits a
          return, for any tax, ever.
        </p>
      </div>
    </div>
  );
}
