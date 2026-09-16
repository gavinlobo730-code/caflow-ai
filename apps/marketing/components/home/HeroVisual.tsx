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
 * The hero's right-hand composition: the globe, the module cards orbiting it,
 * the lines connecting them, and the mark at the centre.
 *
 * Follows the brief's reference image (§2/§19) without reproducing it pixel for
 * pixel, which §18 explicitly rules out. Two things in that image are NOT
 * reproduced and the reasons are the same one: the chips reading "Trusted by
 * Growing Practices" and "Secure & Compliant" are a customer claim with no
 * customers behind it and a certification claim with no certification behind
 * it, and §16 forbids both.
 *
 * THE CARDS ARE DOM, NOT WEBGL, and that is a decision rather than a shortcut.
 * Rendered into the scene they would be unselectable, unsearchable,
 * untranslatable, invisible to a screen reader and blurry at any pixel ratio
 * the renderer is capped below — and the renderer IS capped below native, for
 * the frame-budget reasons in HeroGlobe.tsx. As DOM they are real text that
 * costs the compositor a transform.
 *
 * ANCHORS NEED MORE CLEARANCE THAN THEY LOOK LIKE THEY DO, because every card
 * BOBS. `.floaty` translates 12px vertically on a 6s loop and each card carries
 * its own `animationDelay`, so two cards in the same column drift up to 12px
 * relative to one another — a pair laid out 17px apart touches for part of
 * every cycle. Practice analytics and Banking did exactly that. Leave a gap
 * that survives the bob, not one that measures clear in a screenshot.
 *
 * DENSITY DROPS WITH WIDTH, per §14. Eight cards at ≥1280px, six between 1024
 * and 1280 ("Tablet: reduce orbit/card density"), none below that — where §14
 * asks for the headline first and a simplified globe beneath it, so the whole
 * composition is replaced rather than squeezed.
 *
 * THE CONNECTORS USE preserveAspectRatio="none" WITH non-scaling-stroke. The
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
  /** Dropped first when the stage narrows. */
  secondary?: boolean;
  /** Icon tint. FOUR colours, each used twice, and all of them inside the
   *  brand's own blue-to-gold range — the reference image tints its icons and a
   *  grid of identical grey chips is what made this composition read as a
   *  diagram. Eight different colours would read as a toy; four reads as a
   *  system. */
  tint: string;
};

/**
 * The stage's own width, and the card's, in pixels.
 *
 * The hero grid gives this composition `minmax(0, 640px)` (see Hero.tsx), and
 * every card below declares `minWidth: CARD_MIN_PX`. Those two numbers are what
 * decide whether a card fits, so they are named rather than repeated.
 */
const STAGE_MAX_PX = 640;
const CARD_MIN_PX = 196;

/**
 * The furthest right a `side: "right"` card may be anchored.
 *
 * Such a card is positioned by its LEFT edge at `x%` of the stage and grows
 * rightward, so its outer edge lands at `stageLeft + x% x stageWidth + 196`,
 * and that has to stay inside the viewport.
 *
 * MEASURED, BECAUSE IT WAS WRONG AND SHIPPED. With anchors at 89 and 91 the
 * Payroll and Documents cards ran past the right edge of the viewport — by
 * 71px at 1280, 56px at 1366 and 19px at 1440 — so on the three commonest
 * laptop widths the hero's own module cards were sliced in half. It survived
 * review because the hero section is `overflow-hidden`: the cards were clipped
 * rather than pushed out, so the page never gained a horizontal scrollbar and
 * a `scrollWidth` check saw nothing wrong. Only measuring the CARDS finds it.
 *
 * The binding case is the narrowest width that still shows cards — 1024px,
 * where `canRunGlobe()` and the `lg:` gate both still apply. There the content
 * column is 902px, the stage is the grid's 640px second column and starts at
 * page x 323, so the limit is (1009 - 196 - 323) / 640 = 76.6%.
 *
 * ⚠️ AND "FITS INSIDE THE STAGE" IS NOT THE RULE, though it is tempting
 * because it needs no page arithmetic. Tried: it gives 69.4%, which drags every
 * right-hand card onto the face of the globe, where they overlap each other and
 * the centre mark. The cards belong OUTSIDE the disc — the reference has them
 * grazing its limb, not sitting on it — so the stage is the wrong box to
 * measure against. 74 leaves a little room under the real limit.
 */
const MAX_RIGHT_ANCHOR = 74;

/**
 * The furthest LEFT a `side: "left"` card may be anchored, and it is a
 * different rule from the one above rather than its mirror.
 *
 * Such a card is positioned by its RIGHT edge at `x%` and grows leftward, so it
 * occupies `[x% - cardWidth, x%]`. Beyond the stage's left edge is not empty
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
 * The widest card is Banking at 232px (`minWidth` is a floor; the label sets
 * the real width), so the limit is 232 / 640 = 36.3%.
 */
const MAX_CARD_PX = 232;
const MIN_LEFT_ANCHOR = 37;

const TINT = {
  sky: "#8fb6ff",
  gold: "#d8b07a",
  indigo: "#a9a5f4",
  aqua: "#7fd4d0",
} as const;

const MODULES: Module[] = [
  { key: "compliance", title: "Compliance", line: "GST, TDS, ITR & ROC", icon: <FileText size={16} />, x: 38, y: 16, side: "left", tint: TINT.sky },
  { key: "accounting", title: "Accounting", line: "A ledger that foots", icon: <Calculator size={16} />, x: 72, y: 12, side: "right", tint: TINT.gold },
  { key: "clients", title: "Clients", line: "Every entity, one record", icon: <Building size={16} />, x: 37, y: 41, side: "left", tint: TINT.indigo },
  { key: "payroll", title: "Payroll", line: "Salary, PF, ESI & TDS", icon: <Users size={16} />, x: 74, y: 37, side: "right", tint: TINT.aqua },
  { key: "analytics", title: "Practice analytics", line: "The whole firm at a glance", icon: <BarChart size={16} />, x: 39, y: 63, side: "left", secondary: true, tint: TINT.gold },
  { key: "documents", title: "Documents", line: "Read by AI, checked by you", icon: <Layers size={16} />, x: 73, y: 62, side: "right", tint: TINT.sky },
  { key: "banking", title: "Banking", line: "Statements become vouchers", icon: <Landmark size={16} />, x: 48, y: 88, side: "left", secondary: true, tint: TINT.aqua },
  { key: "ai", title: "AI assistant", line: "It knows your practice", icon: <Sparkles size={16} />, x: 68, y: 89, side: "right", tint: TINT.indigo },
];

export function HeroVisual({ className = "" }: { className?: string }) {
  return (
    <div className={`relative ${className}`}>
      <HeroGlobe className="absolute inset-0 h-full w-full" />

      {/* Connectors — hidden wherever the cards are. */}
      <svg
        className="pointer-events-none absolute inset-0 hidden h-full w-full lg:block"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {/* Flat, thin and clearly VISIBLE. These went from a 5%-to-60%
            gradient (eight bright lines converging on one point, drawn across
            the planet's face) to a flat 0.22, which over-corrected: in the
            reference the web is one of the picture's strongest elements — fine
            bright lines running from every card into the mark at the centre.
            0.22 made them a smudge. Thin and bright rather than thick and dim
            is the same call the orbital sweeps take. */}
        {MODULES.map((m) => (
          <line
            key={m.key}
            x1={m.x}
            y1={m.y}
            x2={50}
            y2={50}
            stroke="#9dc4f5"
            strokeOpacity="0.42"
            strokeWidth="0.9"
            vectorEffect="non-scaling-stroke"
            className={m.secondary ? "hidden xl:block" : undefined}
          />
        ))}
      </svg>

      {/* Module cards */}
      <div className="pointer-events-none absolute inset-0 hidden lg:block" aria-hidden="true">
        {MODULES.map((m, i) => (
          /* TWO ELEMENTS, AND THAT IS THE WHOLE POINT. The placement transform
             and the bob CANNOT share one element: `.floaty`'s keyframes set
             `transform` outright, and an animation's value beats an inline
             one — so the `translate(-100%, -50%)` that is supposed to hang a
             left-hand card off its anchor was being thrown away on every
             frame.

             `side: "left"` therefore did NOTHING. Every card grew rightward
             from its anchor, left and right alike, and the vertical -50%
             centring was lost too. Measured: the Compliance card's LEFT edge
             sat exactly at its x%, where a left-hand card should have its
             RIGHT edge there.

             It reads as a styling detail and it is not — it is why the left
             column had to be crowded onto the globe to keep clear of the
             headline, and why two cards could be laid out 218px apart and
             measure 21px apart. The outer element positions; the inner one
             bobs. */
          <div
            key={m.key}
            className={`absolute ${m.secondary ? "hidden xl:block" : ""}`}
            style={{
              left: `${m.x}%`,
              top: `${m.y}%`,
              transform:
                m.side === "left" ? "translate(-100%, -50%)" : "translate(0, -50%)",
            }}
          >
            <div
              className={i % 2 === 0 ? "floaty" : "floaty-2"}
              style={{ animationDelay: `${i * 420}ms` }}
            >
            <div
              className="flex items-center gap-3 rounded-2xl border border-white/[0.16] bg-white/[0.07] px-3.5 py-3 shadow-[0_14px_40px_rgba(3,8,24,0.5)] backdrop-blur-md"
              style={{ minWidth: CARD_MIN_PX }}
            >
              <span
                className="grid h-9 w-9 shrink-0 place-items-center rounded-xl ring-1"
                style={{
                  color: m.tint,
                  backgroundColor: `${m.tint}1f`,
                  boxShadow: `inset 0 0 0 1px ${m.tint}33`,
                }}
              >
                {m.icon}
              </span>
              <span className="min-w-0">
                <span className="block whitespace-nowrap text-[13.5px] font-semibold leading-none text-white">
                  {m.title}
                </span>
                <span className="mt-1.5 block whitespace-nowrap text-[11px] leading-none text-white/60">
                  {m.line}
                </span>
              </span>
            </div>
            </div>
          </div>
        ))}
      </div>

      {/* The mark at the centre of the system.
          REMOVED ON 16-09-2026 AND RESTORED THE SAME DAY, which is worth
          recording because the removal fixed the symptom and not the cause. It
          sat at 50%/50% and the globe put INDIA at 50%/50%, so the badge
          covered the subcontinent — and the conclusion drawn was that the badge
          had to go. The reference image has BOTH: the mark dead centre and
          India clearly above it. The planet was in the wrong pose, not the mark
          in the wrong place, and HeroGlobe's INDIA_TILT_X is the actual fix. */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 lg:block"
        aria-hidden="true"
      >
        <span className="grid h-[52px] w-[52px] place-items-center rounded-full border border-white/25 bg-[#070f22]/85 shadow-[0_0_48px_rgba(116,180,245,0.55)] backdrop-blur-sm">
          <svg width="26" height="26" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="32" r="24" strokeWidth="3" stroke="rgba(255,255,255,0.22)" />
            <circle
              cx="32"
              cy="32"
              r="24"
              strokeWidth="5"
              strokeLinecap="round"
              className="logo-arc"
              stroke="#8dc0f8"
              strokeDasharray="29.3 121.5"
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
  );
}
