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

/** One gap as the backend emits it — and it emits THREE shapes, not one.
 *
 *  A bare `string` is by far the commonest (`statutory_gaps`, `caveats`,
 *  `movement_gaps`, `rate_gaps`, `payload_gaps` on most builders); `{reason,
 *  kind}` is the GSTR-1 payload's; `{code, message}` is the ageing note's, the
 *  ratios note's and the Worth-A-Look list's. `GapList` used to accept only
 *  the second, which is why 54 sites across 31 files hand-rolled the panel
 *  instead of using it — a renderer that speaks one of three dialects is a
 *  renderer two thirds of its callers cannot call.
 *
 *  Nothing here UNIFIES the backend's vocabulary: 32 differently-named fields
 *  in three shapes is the server's business, and a browser-side normaliser
 *  would be a second authority on what a gap is. This only reads whichever
 *  shape arrived. */
export interface Gap {
  /** The sentence. `message` is the other spelling; one of the two is present. */
  reason?: string;
  message?: string;
  kind?: string;
  code?: string;
  reference_no?: string | null;
  /** GST-29's stamp. `undefined` reads as withheld, so a frontend running
   *  ahead of its backend renders exactly as it did before the field existed. */
  withheld?: boolean;
}

/** What a caller may pass. `string` first because it is what most of them hold. */
export type GapLike = string | Gap;

function sentenceOf(g: GapLike): string {
  return typeof g === "string" ? g : (g.reason ?? g.message ?? "");
}

export interface GapListProps {
  gaps: GapLike[];
  tone?: CalloutTone;
  title?: React.ReactNode;
  className?: string;
  /** Renders each sentence with a leading marker, as several screens do by
   *  hand today. Off by default: a single-item list reads better without one. */
  bulleted?: boolean;
}

/** The list inside a callout. Renders nothing at all for an empty list — an
 *  empty panel headed "Gaps" reads as a clean bill of health, which is the one
 *  thing a gap list must never say by accident. */
export function GapList({ gaps, tone = "withheld", title, className, bulleted }: GapListProps) {
  if (!gaps.length) return null;
  return (
    <Callout tone={tone} title={title} className={className}>
      <ul className={cn("space-y-1.5", bulleted && "list-disc pl-4")}>
        {gaps.map((g, i) => {
          const o = typeof g === "string" ? null : g;
          return (
            <li key={`${o?.kind ?? o?.code ?? ""}-${o?.reference_no ?? ""}-${i}`}>
              {o?.reference_no && <span className="mr-1 font-mono">[{o.reference_no}]</span>}
              {o?.kind && <span className="mr-1 font-medium">{o.kind}</span>}
              {sentenceOf(g)}
            </li>
          );
        })}
      </ul>
    </Callout>
  );
}

/** THE TWO LISTS A STATUTORY PANEL CARRIES, AND WHY THEY ARE ONE COMPONENT.
 *
 *  `app/income-tax/advance-tax/page.tsx` already states the rule in a comment:
 *  *"GAPS ARE ACTIONABLE AND CAVEATS ARE NOT, and they are rendered
 *  differently for that reason — a mis-headed challan or an unpaid §140A
 *  balance needs doing something about; the statement that the interest came
 *  from the panel above needs reading once."* `components/fixed-assets/
 *  CwipTab.tsx` states it again, and `domain/gst/late_filing.py`,
 *  `domain/gst/rule_43.py` and `domain/income_tax/self_assessment.py` all emit
 *  the pair on the same payload.
 *
 *  It was rendered FIVE ways. Measured over the 54 sites: a gap wore 11
 *  distinct inks and a caveat 6, and **five inks were used for both** — so on
 *  the GSTR-3B screen `rule37a.caveats` came out slate (right) while
 *  `rule37.interest_caveats` and `r43.caveats` came out amber, the same colour
 *  as the gap list two panels above. A CA reading that screen cannot tell
 *  "read this once" from "go and record this".
 *
 *  So the pair is one component and the tones are not the caller's to pick.
 *  An empty half renders nothing, and BOTH empty renders nothing at all. */
export interface StatutoryNotesProps {
  gaps?: GapLike[] | null;
  caveats?: GapLike[] | null;
  /** Heading on the gaps half only. Caveats are read, not acted on, and a
   *  heading over them invites a CA to treat them as a list of jobs. */
  title?: React.ReactNode;
  className?: string;
  bulleted?: boolean;
}

export function StatutoryNotes(
  { gaps, caveats, title, className, bulleted }: StatutoryNotesProps,
) {
  const g = gaps ?? [];
  const c = caveats ?? [];
  if (!g.length && !c.length) return null;
  return (
    <div className={cn("space-y-2", className)}>
      <GapList gaps={g} tone="attention" title={title} bulleted={bulleted} />
      <GapList gaps={c} tone="note" bulleted={bulleted} />
    </div>
  );
}
