"use client";

import { HeroGlobe } from "./hero/HeroGlobe";
import { GlobeFallback } from "./hero/fallback";
import {
  Shield,
  Calculator,
  Users,
  Receipt,
  BarChart,
  FileText,
  Landmark,
  Sparkles,
} from "../icons";

/**
 * The hero composition: the scene, the capability cards and the interface
 * fragments floating around them.
 *
 * WHAT IS IN THE DOM AND WHAT IS IN WEBGL, AND WHY THE LINE IS THERE. The
 * planet, the network, the orbits and every space object are WebGL — they need
 * depth, perspective and shading, and a DOM version of any of them is a
 * forgery. The cards are DOM, because they carry real text that has to be
 * selectable, legible at every zoom level and readable by a screen reader, and
 * text rendered into a canvas is a picture of text. The interface fragments
 * are DOM for the same reason the cards are and because they are flat panels,
 * which is the one thing HTML does better than a 3D scene.
 *
 * THE CANVAS IS HUNG OUTSIDE ITS OWN GRID CELL, and that is the single trick
 * the whole layout rests on. §24 wants the Earth to "extend substantially into
 * the right side" and to overlap the conceptual centre, while §14 reserves the
 * left for the headline and Hero.tsx's grid gives this component a 640px
 * column. Growing the column would move the copy; growing the CANVAS inside an
 * absolutely-positioned overflow-visible layer moves nothing. So the scene is
 * 134% x 138% of the cell, offset by half the overhang in each axis so it
 * stays centred on it, and every card anchor below is still a percentage of
 * the untouched 640px stage.
 */

/**
 * The stage: the box card anchors are measured against.
 *
 * NOT the canvas, which is deliberately bigger. Anchors are percentages of
 * this, so the cards keep their relationship to the hero's grid while the
 * planet spills past it.
 */
const STAGE_MAX_PX = 640;

/** The widest a card is allowed to get. Drives MIN_LEFT_ANCHOR below. */
const MAX_CARD_PX = 232;
const CARD_MIN_PX = 196;

/**
 * How far right a card may be anchored, and the bug this number exists for.
 *
 * A right-hand card is placed by its LEFT edge at x% of the stage and grows
 * rightward, so its outer edge lands at stageLeft + x% * 640 + cardWidth. At
 * anchors of 89 and 91 two cards ran past the right edge of the VIEWPORT —
 * 71px over at 1280, 56px at 1366, 19px at 1440 — and were sliced in half on
 * the three commonest laptop widths. It shipped, because the hero is
 * overflow-hidden: the cards were CLIPPED rather than pushing the page wide,
 * so no horizontal scrollbar ever appeared and a scrollWidth check saw a clean
 * page at every width.
 *
 * 1024px is the narrowest that still renders cards, and canRunGlobe() agrees
 * on the same breakpoint: content 902px, stage 640px starting at x=323, card
 * 196px, so the limit is (1009 - 196 - 323) / 640 = 76.6%. Held at 74 for
 * margin. A backend guard re-derives this and fails if it is raised.
 */
const MAX_RIGHT_ANCHOR = 74;

/**
 * How far LEFT a card may be anchored, and it is not the mirror of the above.
 *
 * Past the stage's left edge is not background — it is the headline and the
 * buttons. So a left-hand card must stay inside the stage entirely, which
 * makes the floor the widest card as a percentage of the stage:
 * 232 / 640 = 36.3%.
 */
const MIN_LEFT_ANCHOR = 37;

type Module = {
  key: string;
  label: string;
  line: string;
  Icon: (p: { size?: number; className?: string }) => JSX.Element;
  x: number;
  y: number;
  side: "left" | "right";
  /** 0 is far and small, 1 is near and bright. */
  depth: number;
  /** How much of the card sits over the planet, so the glass has something to blur. */
  overLand: number;
};

/**
 * The eight capability cards.
 *
 * ARRANGEMENT IS ORGANIC, NOT A RING. §9 rules out "a perfect symmetrical
 * circle" and §27 lists "a symmetrical ring of cards" among the failures. So
 * the left column runs 9 / 33 / 60 / 86 and the right runs 19 / 31 / 67 / 91:
 * neither is evenly spaced, the two do not line up with each other, and the AI
 * assistant sits low and centre-right, off both columns entirely.
 *
 * DEPTH IS A PROPERTY OF EACH CARD, and it is what §9's "different depths,
 * subtle perspective, slight variation in scale" actually means in a DOM
 * layer: scale, fill, edge, shadow and glow all interpolate on it, so a far
 * card is smaller AND flatter AND dimmer rather than merely smaller.
 *
 * Every entry keeps `x`, `y` and `side` on ONE line because the backend guard
 * reads them with a regex and a wrapped entry is an anchor it silently stops
 * checking.
 */
const MODULES: Module[] = [
  { key: "compliance", label: "Compliance", line: "GST, TDS, ITR & ROC", Icon: Shield, x: 39, y: 9, side: "left", depth: 0.92, overLand: 0.78 },
  { key: "accounting", label: "Accounting", line: "A ledger that looks ahead", Icon: Calculator, x: 72, y: 19, side: "right", depth: 1, overLand: 0.62 },
  { key: "clients", label: "Clients", line: "Every entity, one record", Icon: Users, x: 37, y: 33, side: "left", depth: 0.62, overLand: 0.5 },
  { key: "payroll", label: "Payroll", line: "Salary, PF, ESI & TDS", Icon: Receipt, x: 74, y: 31, side: "right", depth: 0.86, overLand: 0.84 },
  { key: "analytics", label: "Practice analytics", line: "The whole firm at a glance", Icon: BarChart, x: 38, y: 60, side: "left", depth: 0.98, overLand: 0.74 },
  { key: "documents", label: "Documents", line: "Read by AI, checked by you", Icon: FileText, x: 70, y: 67, side: "right", depth: 0.56, overLand: 0.86 },
  { key: "banking", label: "Banking", line: "Statements become vouchers", Icon: Landmark, x: 43, y: 86, side: "left", depth: 0.7, overLand: 0.4 },
  { key: "ai", label: "AI assistant", line: "It knows your practice", Icon: Sparkles, x: 56, y: 91, side: "right", depth: 0.8, overLand: 0.8 },
];

/**
 * A capability card.
 *
 * ⚠️ DEPTH IS EXPRESSED IN THE CARD'S OWN COLOURS AND NEVER AS `opacity` ON AN
 * ANCESTOR, and the reason is silent. An element with opacity below 1 becomes
 * a BACKDROP ROOT: `backdrop-filter` inside it then samples that element's own
 * contents instead of the page behind it, so the glass simply stops working —
 * with no warning, no console message and no visual clue beyond the card
 * looking slightly flat. A whole pass of this design shipped with dead glass
 * on every card for exactly that reason. A backend guard walks the opacity
 * nesting here and fails if a backdrop-filtered card ends up inside one.
 *
 * So `depth` drives the fill alpha, the border alpha, the highlight, the
 * shadow and the standing glow individually. More code, working glass.
 */
function Card({ m }: { m: Module }) {
  const scale = 0.74 + m.depth * 0.26;
  const width = Math.round(CARD_MIN_PX + m.depth * (MAX_CARD_PX - CARD_MIN_PX));

  // Everything below is alpha on the card's own paint, never on a parent.
  const fill = (0.05 + m.depth * 0.055).toFixed(3);
  const edge = (0.11 + m.depth * 0.17).toFixed(3);
  const topLight = (0.09 + m.depth * 0.13).toFixed(3);
  const shadow = Math.round(12 + m.depth * 20);
  const glowPx = Math.round(26 + m.depth * 26);
  const glowA = (0.05 + m.depth * 0.08).toFixed(3);
  const textA = (0.82 + m.depth * 0.18).toFixed(2);
  const subA = (0.55 + m.depth * 0.2).toFixed(2);
  // A card over the planet has something bright to blur; one over open space
  // has almost nothing, and a heavy blur there reads as a grey smear.
  const blur = (7 + m.overLand * 9).toFixed(1);

  return (
    <div
      className="rounded-xl border"
      style={{
        width,
        transform: `scale(${scale})`,
        transformOrigin: m.side === "right" ? "left center" : "right center",
        backgroundColor: `rgba(14, 26, 48, ${fill})`,
        borderColor: `rgba(150, 190, 255, ${edge})`,
        backdropFilter: `blur(${blur}px) saturate(130%)`,
        WebkitBackdropFilter: `blur(${blur}px) saturate(130%)`,
        boxShadow: [
          `inset 0 1px 0 rgba(255,255,255,${topLight})`,
          `0 ${shadow}px ${shadow * 2}px rgba(2,6,16,0.5)`,
          `0 0 ${glowPx}px rgba(70,135,255,${glowA})`,
        ].join(", "),
      }}
    >
      <div className="flex items-center gap-3 px-3.5 py-3">
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg"
          style={{
            backgroundColor: `rgba(64, 126, 255, ${(0.14 + m.depth * 0.12).toFixed(3)})`,
            color: `rgba(140, 186, 255, ${textA})`,
          }}
        >
          <m.Icon size={16} />
        </span>
        <span className="min-w-0">
          <span
            className="block truncate text-[13px] font-semibold leading-tight"
            style={{ color: `rgba(238, 244, 255, ${textA})` }}
          >
            {m.label}
          </span>
          <span
            className="mt-0.5 block truncate text-[11px] leading-tight"
            style={{ color: `rgba(168, 194, 234, ${subA})` }}
          >
            {m.line}
          </span>
        </span>
      </div>
    </div>
  );
}

/**
 * The interface fragments.
 *
 * §13's "small number of floating document/interface fragments". They are what
 * says the network is carrying WORK rather than abstract data — a chart, a
 * table, a document — and the reference scatters them at a range of sizes
 * across the whole frame including over the planet's face.
 *
 * `left` / `top` rather than `x` / `y` deliberately: the backend guard that
 * checks card anchors matches on `x:` and `y:` and would otherwise read these
 * as cards and hold them to the card limits, which are a different rule for a
 * different reason.
 *
 * Perspective is a static rotateY, not an animation. §9 asks for "subtle
 * perspective" and §21 forbids movement, so these are tilted and still.
 */
type Fragment = {
  left: number;
  top: number;
  w: number;
  h: number;
  kind: "chart" | "doc" | "table";
  rot: number;
  o: number;
};

const FRAGMENTS: Fragment[] = [
  { left: 52, top: 4, w: 54, h: 66, kind: "doc", rot: -13, o: 0.4 },
  { left: 79, top: 7, w: 64, h: 46, kind: "chart", rot: 15, o: 0.34 },
  { left: 33, top: 22, w: 46, h: 56, kind: "doc", rot: -17, o: 0.3 },
  { left: 88, top: 41, w: 50, h: 60, kind: "doc", rot: 19, o: 0.32 },
  { left: 47, top: 47, w: 68, h: 44, kind: "table", rot: -9, o: 0.28 },
  { left: 62, top: 74, w: 72, h: 48, kind: "chart", rot: 11, o: 0.36 },
  { left: 30, top: 72, w: 44, h: 34, kind: "table", rot: -14, o: 0.26 },
];

function FragmentPanel({ f }: { f: Fragment }) {
  const rows = f.kind === "doc" ? 6 : f.kind === "table" ? 4 : 0;
  return (
    <div
      className="overflow-hidden rounded-md border"
      style={{
        width: f.w,
        height: f.h,
        opacity: f.o,
        transform: `perspective(700px) rotateY(${f.rot}deg)`,
        backgroundColor: "rgba(16, 32, 60, 0.5)",
        borderColor: "rgba(130, 175, 255, 0.28)",
        boxShadow: "0 8px 26px rgba(2,6,16,0.45), inset 0 1px 0 rgba(255,255,255,0.07)",
      }}
    >
      <div className="flex h-[7px] items-center gap-[2px] px-1" style={{ backgroundColor: "rgba(90,140,225,0.2)" }}>
        <i className="block h-[2px] w-[2px] rounded-full" style={{ backgroundColor: "rgba(190,215,255,0.65)" }} />
        <i className="block h-[2px] w-[2px] rounded-full" style={{ backgroundColor: "rgba(190,215,255,0.4)" }} />
      </div>

      {f.kind === "chart" ? (
        <div className="flex h-[calc(100%-7px)] items-end gap-[3px] px-1.5 pb-1.5">
          {[0.42, 0.7, 0.34, 0.86, 0.56, 0.95, 0.62].map((v, i) => (
            <span
              key={i}
              className="block flex-1 rounded-[1px]"
              style={{
                height: `${v * 100}%`,
                backgroundColor: i === 5 ? "rgba(255,206,150,0.8)" : "rgba(122,178,255,0.68)",
              }}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-[3px] px-1.5 py-1.5">
          {Array.from({ length: rows }).map((_, i) => (
            <span
              key={i}
              className="block h-[2px] rounded-full"
              style={{
                width: `${[92, 64, 80, 48, 74, 58][i % 6]}%`,
                backgroundColor: i === 0 ? "rgba(190,216,255,0.6)" : "rgba(140,176,230,0.34)",
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function HeroVisual({ className = "" }: { className?: string }) {
  return (
    <div className={`relative ${className}`}>
      {/*
        THE SCENE LAYER. Bigger than the cell in both axes and pulled back by
        half the overhang each way, so it stays centred on the stage while
        spilling past it. `overflow-visible` matters — the parent grid cell
        would otherwise clip the very overhang this exists to create. Behind
        everything, and `pointer-events-none` so a decorative canvas never
        eats a click meant for the copy beside it.

        The SVG fallback sits underneath and is never removed. When WebGL runs
        it is simply covered; when it does not — reduced motion, under 900px,
        a low-memory device, no context — there is nothing to detect and
        nothing to swap, because the thing that would have been swapped in was
        already there.
      */}
      <div className="pointer-events-none absolute inset-0 z-0 overflow-visible">
        <div className="absolute inset-0 lg:left-[-17%] lg:top-[-19%] lg:h-[138%] lg:w-[134%]">
          <GlobeFallback className="absolute inset-0 h-full w-full" />
          <HeroGlobe className="absolute inset-0 h-full w-full" />
        </div>
      </div>

      {/* The fragments sit between the scene and the cards. */}
      <div className="pointer-events-none absolute inset-0 z-[1] hidden lg:block">
        {FRAGMENTS.map((f, i) => (
          <div
            key={i}
            className="absolute"
            style={{ left: `${f.left}%`, top: `${f.top}%` }}
          >
            <FragmentPanel f={f} />
          </div>
        ))}
      </div>

      {/*
        The cards. Hidden below lg because the hero stacks there and §25 keeps
        the mobile composition to the Earth and a small number of elements.

        THE PLACEMENT TRANSFORM IS ON THE OUTER ELEMENT AND THE SCALE IS ON THE
        CARD. They are separate elements on purpose: two transforms on one
        element means one overwrites the other, and it also leaves room for a
        later idle animation — which sets `transform` outright in its keyframes
        — to be added to the middle element without eating the placement.
      */}
      <div className="pointer-events-none absolute inset-0 z-[2] hidden lg:block">
        {MODULES.map((m) => (
          <div
            key={m.key}
            className="absolute"
            style={{
              left: `${m.x}%`,
              top: `${m.y}%`,
              transform:
                m.side === "right" ? "translateY(-50%)" : "translate(-100%, -50%)",
            }}
          >
            <Card m={m} />
          </div>
        ))}
      </div>
    </div>
  );
}
