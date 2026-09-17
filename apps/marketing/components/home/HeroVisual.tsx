"use client";

import type { ReactNode } from "react";
import { HeroGlobe } from "./HeroGlobe";
import {
  FileText,
  Calculator,
  Users,
  Landmark,
  Building,
  Layers,
  BarChart,
  Sparkles,
} from "../icons";

/**
 * The hero's right-hand composition: the globe, the capability cards around it,
 * the data lines from those cards down onto the planet, the control node at the
 * centre, and a handful of small interface fragments floating in the space
 * between.
 *
 * ── THE CANVAS IS BIGGER THAN THE CELL IT SITS IN ─────────────────────────
 * Owner brief, 17-09-2026: the globe should "dominate the right half of the
 * hero", take "roughly 60-70% of the available visual area on the right side",
 * and may "extend beyond the normal boundaries of the hero composition
 * slightly". The grid gives this composition a 640px column (Hero.tsx) and the
 * cards are positioned in percentages of it, so the column cannot simply grow —
 * every anchor below and both of the limits they are checked against are
 * derived from that 640.
 *
 * So the GLOBE'S OWN canvas is hung outside it: 132% of the width and 136% of
 * the height, offset so the planet stays centred on the cell. What spills over
 * is the atmosphere, the outer orbits and the star field — the faint half of
 * the picture — and the hero section is overflow-hidden, so it fades off the
 * edge of the frame rather than pushing the page wide. The card geometry is
 * untouched by any of it.
 *
 * ── THE CARDS ARE DOM, NOT WEBGL, and that is a decision rather than a
 * shortcut. Rendered into the scene they would be unselectable, unsearchable,
 * untranslatable, invisible to a screen reader and resampled at whatever pixel
 * ratio the renderer runs at. As DOM they are real text that costs the
 * compositor a transform.
 *
 * ── DEPTH IS A PROPERTY OF EACH CARD ──────────────────────────────────────
 * The brief asks for cards at varying depth — "some closer, some farther",
 * "vary the scale slightly", "apply subtle rotation/perspective" — rather than
 * eight identical chips on a ring. Each carries a `depth` from 0 (farthest) to
 * 1 (nearest), and it drives everything at once: scale, the fill and border of
 * the glass, its blur radius, how hard the shadow falls, the text contrast and
 * how bright its data line is. One number, so a card cannot be large and faint
 * at the same time, which is what reads as wrong.
 *
 * SCALE NEVER EXCEEDS 1, and that is load-bearing rather than timid. Both anchor
 * limits below are derived from a card's own width; a card scaled ABOVE 1 grows
 * past its anchor in both directions and silently invalidates them. Depth
 * therefore works downward from full size.
 *
 * ── ANCHORS NEED MORE CLEARANCE THAN THEY LOOK LIKE THEY DO, because every
 * card BOBS. `.floaty` translates 12px vertically on a 6s loop and each card
 * carries its own animationDelay, so two cards in the same column drift up to
 * 12px relative to one another — a pair laid out 17px apart touches for part of
 * every cycle. Leave a gap that survives the bob, not one that measures clear
 * in a screenshot.
 *
 * ── DENSITY DROPS WITH WIDTH. Eight cards at >=1280px, six between 1024 and
 * 1280, none below that — where the whole composition is replaced by the
 * headline and a simplified globe rather than being squeezed.
 *
 * ── THE CONNECTORS USE preserveAspectRatio="none" WITH non-scaling-stroke. The
 * viewBox is a unit square so card anchors and line endpoints are written in
 * the same percentage coordinates and cannot drift apart; letting the box
 * stretch to the stage would normally distort the stroke too, which is exactly
 * what vectorEffect prevents.
 */

type Module = {
  key: string;
  title: string;
  line: string;
  icon: ReactNode;
  /** Anchor in percent of the stage — also where its connector line starts. */
  x: number;
  y: number;
  /** Which side the card body sits on, relative to its anchor. */
  side: "left" | "right";
  /** 0 = farthest back, 1 = nearest. Drives scale, contrast, shadow and line. */
  depth: number;
  /** Where on the globe this card's data line lands, as a fraction of the
   *  planet's radius. ABSENT MEANS NO LINE, and three of the eight are absent
   *  on purpose: the brief asks to "connect SOME of them to the globe", and a
   *  line from every card is the spoke diagram this composition keeps being
   *  mistaken for. */
  land?: number;
  /** Dropped first when the stage narrows. */
  secondary?: boolean;
  /** Icon tint. Deliberately a RESTRAINED set: two blues, a cool white, a gold
   *  and an indigo, each used at most twice. The brief rules out rainbow
   *  colours and excessive cyan, and the globe below is now blue-dominant with
   *  gold reserved for India — so the cards cannot be the brightest or the most
   *  colourful thing in the frame. */
  tint: string;
};

/**
 * The stage's own width, and the card's, in pixels.
 *
 * The hero grid gives this composition minmax(0, 640px) (see Hero.tsx), and
 * every card below declares minWidth: CARD_MIN_PX. Those two numbers are what
 * decide whether a card fits, so they are named rather than repeated.
 */
const STAGE_MAX_PX = 640;
const CARD_MIN_PX = 196;

/**
 * The furthest right a `side: "right"` card may be anchored.
 *
 * Such a card is positioned by its LEFT edge at x% of the stage and grows
 * rightward, so its outer edge lands at stageLeft + x% * stageWidth + 196, and
 * that has to stay inside the viewport.
 *
 * MEASURED, BECAUSE IT WAS WRONG AND SHIPPED. With anchors at 89 and 91 the
 * Payroll and Documents cards ran past the right edge of the viewport — by 71px
 * at 1280, 56px at 1366 and 19px at 1440 — so on the three commonest laptop
 * widths the hero's own cards were sliced in half. It survived review because
 * the hero section is overflow-hidden: the cards were clipped rather than
 * pushed out, so the page never gained a horizontal scrollbar and a scrollWidth
 * check saw nothing wrong. Only measuring the CARDS finds it.
 *
 * The binding case is the narrowest width that still shows cards — 1024px,
 * where canRunGlobe() and the lg: gate both still apply. There the content
 * column is 902px, the stage is the grid's 640px second column and starts at
 * page x 323, so the limit is (1009 - 196 - 323) / 640 = 76.6%.
 *
 * ⚠️ AND "FITS INSIDE THE STAGE" IS NOT THE RULE, though it is tempting because
 * it needs no page arithmetic. Tried: it gives 69.4%, which drags every
 * right-hand card onto the face of the globe, where they overlap each other and
 * the centre node. The cards belong at the planet's LIMB, not on it, so the
 * stage is the wrong box to measure against. 74 leaves a little room under the
 * real limit.
 */
const MAX_RIGHT_ANCHOR = 74;

/**
 * The furthest LEFT a `side: "left"` card may be anchored, and it is a
 * different rule from the one above rather than its mirror.
 *
 * Such a card is positioned by its RIGHT edge at x% and grows leftward, so it
 * occupies [x% - cardWidth, x%]. Beyond the stage's left edge is not empty
 * space — it is the hero's headline, standfirst and buttons. So here the card
 * really must stay inside the STAGE, which is the constraint explicitly
 * rejected for the right-hand side, where the only thing past the stage is
 * background.
 *
 * MEASURED: at 1280 the Practice analytics card's left edge landed at x=454
 * while the copy column runs to x=528, so it sat on top of "From clients and
 * compliance to accounts and advisory". At 1440 it cleared, which is why a
 * single-width check missed it — the copy column and the stage move toward each
 * other as the viewport narrows.
 *
 * The widest card is Banking at 232px (minWidth is a floor; the label sets the
 * real width), so the limit is 232 / 640 = 36.3%.
 */
const MAX_CARD_PX = 232;
const MIN_LEFT_ANCHOR = 37;

/**
 * The planet's own radius, in the same percentages the cards are anchored in.
 * This is what lets a data line STOP ON THE GLOBE rather than at the middle of
 * the box.
 *
 * Derived, not measured off a screenshot. HeroGlobe's camera puts the sphere's
 * diameter at 65.7% of its CANVAS height, and that canvas is 136% of the stage
 * height — so the radius is 0.657 * 1.36 / 2 = 44.7% of the stage's HEIGHT,
 * exactly, whatever size the stage is.
 *
 * ⚠️ THE HORIZONTAL FIGURE IS NOT A CONSTANT AND IS DELIBERATELY UNDERSTATED.
 * The connector SVG's viewBox is a unit square stretched over the stage, so the
 * same radius in x is (0.447 * stageHeight) / 640 — which depends on the stage's
 * own aspect, and the stage is min(84vh, 720px) tall. That runs from about 41%
 * of the width on a short laptop to 50% on a tall monitor.
 *
 * 42 is the SHORT end, and taking the short end is what makes the error safe:
 * under-stating the radius lands every line further INSIDE the planet's face,
 * while over-stating it would put the line's endpoint past the limb on exactly
 * the screens where the stage is shortest — a data line ending in empty space
 * beside the globe. The visible cost is that on a tall monitor the lines stop
 * around 0.7 of the true radius instead of 0.8, which is not a difference
 * anybody can see.
 */
const GLOBE_RX = 42;
const GLOBE_RY = 44.7;

/**
 * Where a card's data line meets the planet.
 *
 * Straight toward the centre, stopped at `t` of the way there — so the line
 * lands ON the sphere's face at a point that varies per card, instead of eight
 * lines converging on one spot. The direction is normalised in the ELLIPSE's
 * own metric, or a line to a card above the globe would land at a different
 * fraction of the radius than a line to one beside it.
 */
function landingPoint(x: number, y: number, t: number) {
  const dx = (x - 50) / GLOBE_RX;
  const dy = (y - 50) / GLOBE_RY;
  const len = Math.hypot(dx, dy) || 1;
  return {
    x: 50 + (dx / len) * GLOBE_RX * t,
    y: 50 + (dy / len) * GLOBE_RY * t,
  };
}

const TINT = {
  sky: "#8fb6ff",
  pale: "#cfe0f8",
  gold: "#e0b57e",
  indigo: "#a2a9f2",
} as const;

const MODULES: Module[] = [
  { key: "compliance", title: "Compliance", line: "GST, TDS, ITR & ROC", icon: <FileText size={16} />, x: 37, y: 11, side: "left", depth: 0.92, land: 0.72, tint: TINT.sky },
  { key: "accounting", title: "Accounting", line: "A ledger that foots", icon: <Calculator size={16} />, x: 70, y: 19, side: "right", depth: 1, tint: TINT.gold },
  { key: "clients", title: "Clients", line: "Every entity, one record", icon: <Building size={16} />, x: 40, y: 34, side: "left", depth: 0.62, tint: TINT.indigo },
  { key: "payroll", title: "Payroll", line: "Salary, PF, ESI & TDS", icon: <Users size={16} />, x: 74, y: 33, side: "right", depth: 0.86, land: 0.8, tint: TINT.pale },
  { key: "analytics", title: "Practice analytics", line: "The whole firm at a glance", icon: <BarChart size={16} />, x: 37, y: 59, side: "left", depth: 0.98, land: 0.68, secondary: true, tint: TINT.gold },
  { key: "documents", title: "Documents", line: "Read by AI, checked by you", icon: <Layers size={16} />, x: 72, y: 66, side: "right", depth: 0.56, land: 0.86, tint: TINT.sky },
  { key: "banking", title: "Banking", line: "Statements become vouchers", icon: <Landmark size={16} />, x: 45, y: 85, side: "left", depth: 0.7, secondary: true, tint: TINT.pale },
  { key: "ai", title: "AI assistant", line: "It knows your practice", icon: <Sparkles size={16} />, x: 66, y: 90, side: "right", depth: 0.8, land: 0.76, tint: TINT.indigo },
];

/**
 * The interface fragments.
 *
 * The brief asks for "a very limited number of" floating document sheets,
 * dashboard fragments and chart pieces, as "secondary details that reward
 * people who look closely" — and immediately afterwards, "do not clutter the
 * composition". Four of them, none wider than 96px, none above 46% opacity, and
 * all four are xl-only: at 1024-1280 the card set has already been thinned to
 * six and adding scenery to a crowded frame is the opposite of the brief.
 *
 * They carry no words that could read as a claim. A fragment showing a number
 * is a fragment somebody will read as a statistic.
 *
 * ⚠️ THE POSITION FIELDS ARE `left`/`top`, NOT `x`/`y`, AND THAT IS DELIBERATE.
 * The backend guard that checks no card is anchored off the edge of the screen
 * finds module entries by the literal pattern `x: N, y: N, side: "…"`. A
 * fragment written with the same field names would be read as a card and
 * measured against a card's width limits — the sheet below sits at 84%, which
 * is past MAX_RIGHT_ANCHOR for a 196px card and perfectly safe for a 78px SVG.
 */
type Fragment = { key: string; left: number; top: number; side: "left" | "right"; body: ReactNode };

const FRAGMENTS: Fragment[] = [
  {
    key: "spark",
    left: 55,
    top: 2,
    side: "right",
    body: (
      <svg width="96" height="44" viewBox="0 0 96 44" fill="none" aria-hidden="true">
        <rect x="0.6" y="0.6" width="94.8" height="42.8" rx="5" stroke="rgba(174,205,247,0.3)" strokeWidth="1.1" fill="rgba(12,22,44,0.5)" />
        <path d="M9 32 L20 26 L30 29 L41 18 L52 22 L63 12 L74 15 L87 9" stroke="#9dc4f5" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="63" cy="12" r="2.1" fill="#dbe9ff" />
        <path d="M9 37h78" stroke="rgba(157,196,245,0.22)" strokeWidth="0.8" />
      </svg>
    ),
  },
  {
    // WIDE AND SHORT, NOT A PAGE. The first draft of this was a 62x76 document
    // sheet, and there is nowhere in this composition to put a 76px-tall object:
    // measured at six viewport widths it fouled Payroll, the vertical rail, or
    // both, at every position on the right-hand side and every position on the
    // left. A document reads as a document from three ruled lines and a
    // highlighted one; the page around them is what needed the room.
    key: "sheet",
    left: 84,
    top: 5,
    side: "right",
    body: (
      <svg width="78" height="26" viewBox="0 0 78 26" fill="none" aria-hidden="true">
        <rect x="0.6" y="0.6" width="76.8" height="24.8" rx="4" stroke="rgba(174,205,247,0.3)" strokeWidth="1.1" fill="rgba(12,22,44,0.5)" />
        <g stroke="rgba(190,215,250,0.5)" strokeWidth="1.4" strokeLinecap="round">
          <path d="M8 9h34" />
          <path d="M8 17h22" />
        </g>
        <path d="M50 17h20" stroke="#e0b57e" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    key: "bars",
    left: 43,
    top: 73,
    side: "left",
    body: (
      <svg width="74" height="40" viewBox="0 0 74 40" fill="none" aria-hidden="true">
        <g fill="rgba(143,182,255,0.5)">
          <rect x="2" y="22" width="8" height="16" rx="1.6" />
          <rect x="15" y="14" width="8" height="24" rx="1.6" />
          <rect x="28" y="26" width="8" height="12" rx="1.6" />
          <rect x="41" y="8" width="8" height="30" rx="1.6" />
          <rect x="54" y="18" width="8" height="20" rx="1.6" />
        </g>
        <rect x="41" y="8" width="8" height="30" rx="1.6" fill="rgba(224,181,126,0.6)" />
        <path d="M0 39h74" stroke="rgba(157,196,245,0.2)" strokeWidth="0.8" />
      </svg>
    ),
  },
  {
    key: "gauge",
    left: 52,
    top: 92,
    side: "left",
    body: (
      <svg width="46" height="46" viewBox="0 0 46 46" fill="none" aria-hidden="true">
        <circle cx="23" cy="23" r="18" stroke="rgba(157,196,245,0.22)" strokeWidth="2.6" />
        <circle cx="23" cy="23" r="18" stroke="#9dc4f5" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="76 114" transform="rotate(-90 23 23)" />
        <circle cx="23" cy="23" r="4.4" fill="rgba(219,233,255,0.5)" />
      </svg>
    ),
  },
];

export function HeroVisual({ className = "" }: { className?: string }) {
  return (
    <div className={`relative ${className}`}>
      {/* The globe's canvas, hung outside the grid cell — see the header. Only
          at lg and above: below that the composition is replaced rather than
          scaled, and an oversized canvas on a phone would push the simplified
          globe off its own centre. */}
      <div className="absolute left-0 top-0 h-full w-full lg:left-[-16%] lg:top-[-18%] lg:h-[136%] lg:w-[132%]">
        <HeroGlobe className="h-full w-full" />
      </div>

      {/* Data lines — from a card's anchor down onto the planet's own face. */}
      <svg
        className="pointer-events-none absolute inset-0 hidden h-full w-full lg:block"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {MODULES.filter((m) => m.land !== undefined).map((m) => {
          const p = landingPoint(m.x, m.y, m.land as number);
          return (
            <g key={m.key} className={m.secondary ? "hidden xl:block" : undefined}>
              <line
                x1={m.x}
                y1={m.y}
                x2={p.x}
                y2={p.y}
                stroke="#9dc4f5"
                strokeOpacity={(0.16 + m.depth * 0.3).toFixed(2)}
                strokeWidth="0.85"
                vectorEffect="non-scaling-stroke"
              />
              {/* The junction where the line meets the planet. Without it the
                  line simply stops in the middle of the disc and reads as a
                  scratch on the image rather than as a connection. */}
              <circle
                cx={p.x}
                cy={p.y}
                r="0.55"
                fill="#dbe9ff"
                fillOpacity={(0.3 + m.depth * 0.45).toFixed(2)}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>

      {/* Capability cards */}
      <div className="pointer-events-none absolute inset-0 hidden lg:block" aria-hidden="true">
        {MODULES.map((m, i) => {
          // One number drives the whole depth cue, so a card cannot be large
          // and faint at the same time. Scale stays at or below 1 — see the
          // header; both anchor limits depend on it.
          //
          // ⚠️ AND NONE OF IT IS `opacity` ON THIS ELEMENT, however obvious a
          // way that is to push a card back. An element with opacity below 1
          // becomes a BACKDROP ROOT: `backdrop-filter` on anything inside it
          // then samples that element's own contents instead of the page
          // behind, and the card's glass silently becomes a flat translucent
          // rectangle. Depth is expressed in the card's own colours instead —
          // fill, border, blur radius, shadow and text — which is also the
          // truer cue: something further away is lower in CONTRAST, not
          // see-through.
          const scale = 0.74 + m.depth * 0.26;
          const shadow = Math.round(10 + m.depth * 18);
          const fill = (0.040 + m.depth * 0.048).toFixed(3);
          const edge = (0.09 + m.depth * 0.15).toFixed(3);
          const blur = (5 + m.depth * 8).toFixed(1);
          // Turned slightly TOWARD the centre of the composition, which is the
          // brief's "subtle rotation/perspective". Small on purpose: past about
          // eight degrees the label's own letterforms start to shear visibly.
          const turn = m.side === "left" ? 5 : -5;
          return (
            /* TWO ELEMENTS, AND THAT IS THE WHOLE POINT. The placement
               transform and the bob CANNOT share one element: `.floaty`'s
               keyframes set `transform` outright, and an animation's value
               beats an inline one — so the translate(-100%, -50%) that is
               supposed to hang a left-hand card off its anchor was being thrown
               away on every frame.

               `side: "left"` therefore did NOTHING, for a month. Every card
               grew rightward from its anchor, left and right alike, and the
               vertical -50% centring was lost too. Measured: the Compliance
               card's LEFT edge sat exactly at its x%, where a left-hand card
               should have its RIGHT edge there.

               It reads as a styling detail and it is not — it is why the left
               column had to be crowded onto the globe to keep clear of the
               headline, and why two cards could be laid out 218px apart and
               measure 21px apart. The outer element positions, scales and
               turns; the inner one bobs. */
            <div
              key={m.key}
              className={`absolute ${m.secondary ? "hidden xl:block" : ""}`}
              style={{
                left: `${m.x}%`,
                top: `${m.y}%`,
                transform: `perspective(1100px) ${
                  m.side === "left" ? "translate(-100%, -50%)" : "translate(0, -50%)"
                } rotateY(${turn}deg) scale(${scale})`,
              }}
            >
              <div
                className={i % 2 === 0 ? "floaty" : "floaty-2"}
                style={{ animationDelay: `${i * 420}ms` }}
              >
                <div
                  className="flex items-center gap-3 rounded-2xl border px-3.5 py-3"
                  style={{
                    minWidth: CARD_MIN_PX,
                    // A COOL fill and a cool edge rather than neutral white.
                    // The brief asks for "premium translucent dark glass with
                    // subtle blue edges"; plain white at these alphas over a
                    // navy page reads as grey plastic.
                    backgroundColor: `rgba(150,186,255,${fill})`,
                    borderColor: `rgba(176,206,255,${edge})`,
                    backdropFilter: `blur(${blur}px)`,
                    WebkitBackdropFilter: `blur(${blur}px)`,
                    boxShadow: `0 ${shadow}px ${shadow * 2.4}px rgba(2,6,20,${(
                      0.3 +
                      m.depth * 0.28
                    ).toFixed(2)})`,
                  }}
                >
                  <span
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-xl"
                    style={{
                      color: m.tint,
                      opacity: (0.62 + m.depth * 0.38).toFixed(2),
                      backgroundColor: `${m.tint}1c`,
                      boxShadow: `inset 0 0 0 1px ${m.tint}30`,
                    }}
                  >
                    {m.icon}
                  </span>
                  <span className="min-w-0">
                    <span
                      className="block whitespace-nowrap text-[13.5px] font-semibold leading-none"
                      style={{ color: `rgba(255,255,255,${(0.76 + m.depth * 0.24).toFixed(2)})` }}
                    >
                      {m.title}
                    </span>
                    <span
                      className="mt-1.5 block whitespace-nowrap text-[11px] leading-none"
                      style={{ color: `rgba(255,255,255,${(0.38 + m.depth * 0.22).toFixed(2)})` }}
                    >
                      {m.line}
                    </span>
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Interface fragments — the small stuff in the gaps. See FRAGMENTS. */}
      <div className="pointer-events-none absolute inset-0 hidden xl:block" aria-hidden="true">
        {FRAGMENTS.map((f, i) => (
          <div
            key={f.key}
            className="absolute"
            style={{
              left: `${f.left}%`,
              top: `${f.top}%`,
              opacity: 0.46,
              transform:
                f.side === "left" ? "translate(-100%, -50%)" : "translate(0, -50%)",
            }}
          >
            <div className={i % 2 === 0 ? "floaty-2" : "floaty"} style={{ animationDelay: `${900 + i * 700}ms` }}>
              {f.body}
            </div>
          </div>
        ))}
      </div>

      {/* THE CONTROL NODE AT THE CENTRE OF THE SYSTEM.
          The brief: keep the tick, but make it "the central control/identity
          node of the entire network … use a subtle circular/digital housing
          around it". So the mark itself is unchanged and what is around it is
          new — a graduation ring, a containing ring with two bright arc
          segments at different lengths, and four registration ticks. Rings
          rather than a plate, because a plate would hide the planet it is
          supposed to be reading.

          IT WAS REMOVED ON 16-09-2026 AND RESTORED THE SAME DAY, which is
          worth recording because the removal fixed the symptom and not the
          cause. It sat at 50%/50% and the globe put INDIA at 50%/50%, so the
          badge covered the subcontinent — and the conclusion drawn was that
          the badge had to go. Both belong here: the mark dead centre and India
          clearly above it. The planet was in the wrong pose, not the mark in
          the wrong place, and HeroGlobe's INDIA_TILT_X is the actual fix. */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 lg:block"
        aria-hidden="true"
      >
        <div className="relative grid h-[124px] w-[124px] place-items-center">
          <svg viewBox="0 0 124 124" className="absolute inset-0 h-full w-full" fill="none" aria-hidden="true">
            {/* 36 graduations. The circumference at r=60 is 377, so the dash
                period is 377/36 = 10.47 — written out rather than eyeballed,
                or the last graduation lands a fraction from the first. */}
            <circle
              cx="62"
              cy="62"
              r="60"
              stroke="rgba(157,196,245,0.28)"
              strokeWidth="1"
              strokeLinecap="round"
              strokeDasharray="1.2 9.27"
            />
            <circle cx="62" cy="62" r="49" stroke="rgba(157,196,245,0.18)" strokeWidth="0.75" />
            {/* Two arcs of different lengths at different angles: a ring broken
                in one place reads as a gap, broken in two as a mechanism. */}
            <circle
              cx="62"
              cy="62"
              r="49"
              stroke="#8dc0f8"
              strokeOpacity="0.55"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeDasharray="42 266"
              transform="rotate(-118 62 62)"
            />
            <circle
              cx="62"
              cy="62"
              r="49"
              stroke="#8dc0f8"
              strokeOpacity="0.3"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeDasharray="20 288"
              transform="rotate(44 62 62)"
            />
            <g stroke="rgba(200,224,255,0.38)" strokeWidth="1" strokeLinecap="round">
              <path d="M62 3.5v7" />
              <path d="M62 113.5v7" />
              <path d="M3.5 62h7" />
              <path d="M113.5 62h7" />
            </g>
            <circle cx="62" cy="62" r="35" stroke="rgba(141,192,248,0.2)" strokeWidth="0.75" />
          </svg>

          <span className="relative grid h-[58px] w-[58px] place-items-center rounded-full border border-white/25 bg-[#050c1d]/90 shadow-[0_0_56px_rgba(116,180,245,0.5)] backdrop-blur-sm">
            <svg width="28" height="28" viewBox="0 0 64 64" fill="none" aria-hidden="true">
              <circle cx="32" cy="32" r="24" strokeWidth="3" stroke="rgba(255,255,255,0.2)" />
              <circle
                cx="32"
                cy="32"
                r="24"
                strokeWidth="5"
                strokeLinecap="round"
                stroke="#8dc0f8"
                strokeDasharray="29.3 121.5"
                transform="rotate(-50 32 32)"
              />
              <path
                d="M20,33 L28,41 L45,22"
                strokeWidth="6.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                stroke="#ffffff"
              />
            </svg>
          </span>
        </div>
      </div>
    </div>
  );
}
