/**
 * The inline callout, and the statutory-gap list built on it.
 *
 * ── WHY ─────────────────────────────────────────────────────────────────────
 * The backend emits, from 96 files, a list of sentences saying what it could
 * NOT derive and why: `payload_gaps`, `statutory_gaps`, `movement_gaps`,
 * `cess_gaps`, `table_4a_gaps`, `rate_gap`, `cap_gap`, `withheld_gaps` — 32
 * differently-named fields carrying one idea. 63 sites in 36 files render one,
 * each with its own amber div, its own icon size and its own heading, and
 * `components/gst/Gstr1Findings.tsx` had to grow a `scripts/panelSource.ts`
 * helper precisely because three guards had a rendering's PATH written into
 * them.
 *
 * ── THE FOUR TONES ARE NOT INTERCHANGEABLE, AND THAT IS THE WHOLE DESIGN ────
 * This product says four different things and a CA acts differently on each.
 * Collapsing any two is what makes a panel unreadable:
 *
 *   `problem`    it failed, or it will. Act.
 *   `attention`  a person has to answer something before this is right.
 *   `withheld`   the product deliberately declared NOTHING here because it
 *                cannot derive it — a nil meaning "we cannot see it", which is
 *                not a nil meaning "there was none". CLAUDE.md records this
 *                distinction on GSTR-3B's four underivable rows, on Table
 *                4(A)'s ISD row, and on Table 13's cancelled count.
 *   `note`       settled; recorded so the reader is not surprised.
 *
 * `withheld` and `attention` look similar and mean opposite things — one says
 * a figure is ABSENT from what will be filed, the other says a figure is
 * PRESENT and unchecked. `Gstr1Findings` already splits its list on exactly
 * that (`stamp_withheld`, GST-29), and this is that split made reusable.
 *
 * ── NOTHING IS DECIDED HERE ─────────────────────────────────────────────────
 * The component renders; the server decides. It holds no list of gap kinds, no
 * mapping from a kind to a tone, and no sentences — the browser keeping a
 * vocabulary the backend owns is the Schedule III caption mistake, twice
 * recorded in CLAUDE.md. A caller passes the tone it was served.
 */
import * as React from "react";
import { AlertTriangle, Info, EyeOff, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalloutTone = "problem" | "attention" | "withheld" | "note";

const TONE: Record<CalloutTone, { box: string; ink: string; Icon: typeof Info }> = {
  problem:   { box: "bg-state-problem-surface border-state-problem-border",     ink: "text-state-problem",   Icon: XCircle },
  attention: { box: "bg-state-attention-surface border-state-attention-border", ink: "text-state-attention", Icon: AlertTriangle },
  // Slate rather than a fifth hue: "we could not see this" is a statement
  // about the product, not about the client's tax position, and giving it a
  // colour of its own would put a third warning shade on a screen that already
  // has two meanings to tell apart.
  withheld:  { box: "bg-state-done-surface border-state-done-border",           ink: "text-state-done",      Icon: EyeOff },
  note:      { box: "bg-ps-muted border-ps-border",                             ink: "text-ps-body",         Icon: Info },
};

export interface CalloutProps {
  tone?: CalloutTone;
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

export function Callout({ tone = "note", title, children, className }: CalloutProps) {
  const { box, ink, Icon } = TONE[tone];
  return (
    <div
      // `problem` is the only tone that interrupts a screen reader. The others
      // are read in document order, which is where they belong — a CA reading
      // a return should not have a note about Table 12 announced over them.
      role={tone === "problem" ? "alert" : undefined}
      className={cn("rounded-lg border px-3 py-2.5", box, className)}
    >
      {title && (
        <h4 className={cn("flex items-center gap-1.5 text-xs font-semibold", ink)}>
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {title}
        </h4>
      )}
      {children && (
        <div className={cn("text-xs", ink, title && "mt-1.5")}>{children}</div>
      )}
    </div>
  );
}

/** One gap as the backend emits it. Every field but `reason` is optional
 *  because the 32 shapes do not agree on the others, and a renderer that
 *  required one would simply not be used by two thirds of them. */
export interface Gap {
  reason: string;
  kind?: string;
  reference_no?: string | null;
  /** GST-29's stamp. `undefined` reads as withheld, so a frontend running
   *  ahead of its backend renders exactly as it did before the field existed. */
  withheld?: boolean;
}

export interface GapListProps {
  gaps: Gap[];
  tone?: CalloutTone;
  title?: React.ReactNode;
  className?: string;
}

/** The list inside a callout. Renders nothing at all for an empty list — an
 *  empty panel headed "Gaps" reads as a clean bill of health, which is the one
 *  thing a gap list must never say by accident. */
export function GapList({ gaps, tone = "withheld", title, className }: GapListProps) {
  if (!gaps.length) return null;
  return (
    <Callout tone={tone} title={title} className={className}>
      <ul className="space-y-1.5">
        {gaps.map((g, i) => (
          <li key={`${g.kind ?? ""}-${g.reference_no ?? ""}-${i}`}>
            {g.reference_no && <span className="mr-1 font-mono">[{g.reference_no}]</span>}
            {g.kind && <span className="mr-1 font-medium">{g.kind}</span>}
            {g.reason}
          </li>
        ))}
      </ul>
    </Callout>
  );
}
