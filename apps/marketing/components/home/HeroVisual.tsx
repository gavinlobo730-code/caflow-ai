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

const TINT = {
  sky: "#8fb6ff",
  gold: "#d8b07a",
  indigo: "#a9a5f4",
  aqua: "#7fd4d0",
} as const;

const MODULES: Module[] = [
  { key: "compliance", title: "Compliance", line: "GST, TDS, ITR & ROC", icon: <FileText size={16} />, x: 15, y: 19, side: "left", tint: TINT.sky },
  { key: "accounting", title: "Accounting", line: "A ledger that foots", icon: <Calculator size={16} />, x: 81, y: 14, side: "right", tint: TINT.gold },
  { key: "clients", title: "Clients", line: "Every entity, one record", icon: <Building size={16} />, x: 6, y: 42, side: "left", tint: TINT.indigo },
  { key: "payroll", title: "Payroll", line: "Salary, PF, ESI & TDS", icon: <Users size={16} />, x: 91, y: 37, side: "right", tint: TINT.aqua },
  { key: "analytics", title: "Practice analytics", line: "The whole firm at a glance", icon: <BarChart size={16} />, x: 9, y: 66, side: "left", secondary: true, tint: TINT.gold },
  { key: "documents", title: "Documents", line: "Read by AI, checked by you", icon: <Layers size={16} />, x: 89, y: 61, side: "right", tint: TINT.sky },
  { key: "banking", title: "Banking", line: "Statements become vouchers", icon: <Landmark size={16} />, x: 29, y: 84, side: "left", secondary: true, tint: TINT.aqua },
  { key: "ai", title: "AI assistant", line: "It knows your practice", icon: <Sparkles size={16} />, x: 74, y: 82, side: "right", tint: TINT.indigo },
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
        {/* Flat and faint. These used to run from 5% to 60% opacity along a
            gradient, brightest where they met in the middle — eight bright
            lines converging on one point, drawn straight across the face of the
            planet. With the centre badge gone they now converge on the lit
            subcontinent itself, which is the picture: a network running into
            India. That only reads if the lines stay quieter than the globe. */}
        {MODULES.map((m) => (
          <line
            key={m.key}
            x1={m.x}
            y1={m.y}
            x2={50}
            y2={50}
            stroke="#7fa0ec"
            strokeOpacity="0.22"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            className={m.secondary ? "hidden xl:block" : undefined}
          />
        ))}
      </svg>

      {/* Module cards */}
      <div className="pointer-events-none absolute inset-0 hidden lg:block" aria-hidden="true">
        {MODULES.map((m, i) => (
          <div
            key={m.key}
            className={`absolute ${m.secondary ? "hidden xl:block" : ""} ${
              i % 2 === 0 ? "floaty" : "floaty-2"
            }`}
            style={{
              left: `${m.x}%`,
              top: `${m.y}%`,
              transform:
                m.side === "left" ? "translate(-100%, -50%)" : "translate(0, -50%)",
              animationDelay: `${i * 420}ms`,
            }}
          >
            <div
              className="flex items-center gap-3 rounded-2xl border border-white/[0.16] bg-white/[0.07] px-3.5 py-3 shadow-[0_14px_40px_rgba(3,8,24,0.5)] backdrop-blur-md"
              style={{ minWidth: 196 }}
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
        ))}
      </div>

      {/* THE CENTRE MARK IS GONE (16-09-2026). A 52px badge sat at exactly
          50%/50% — which is exactly where the globe now puts INDIA, so the one
          feature the brief asks to be "visibly central" was underneath it. The
          badge made sense when the globe was an abstract sphere with nothing in
          particular at its centre; once the sphere became an Earth, it was
          covering the subject. The connectors converge on the lit subcontinent
          instead, which says the same thing the badge did and says it with the
          picture rather than on top of it. */}
    </div>
  );
}
