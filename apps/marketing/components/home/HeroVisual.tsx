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
};

const MODULES: Module[] = [
  { key: "compliance", title: "Compliance", line: "GST, TDS, ITR & ROC", icon: <FileText size={15} />, x: 17, y: 20, side: "left" },
  { key: "accounting", title: "Accounting", line: "A ledger that foots", icon: <Calculator size={15} />, x: 79, y: 15, side: "right" },
  { key: "clients", title: "Clients", line: "Every entity, one record", icon: <Building size={15} />, x: 8, y: 42, side: "left" },
  { key: "payroll", title: "Payroll", line: "Salary, PF, ESI & TDS", icon: <Users size={15} />, x: 89, y: 37, side: "right" },
  { key: "analytics", title: "Practice analytics", line: "The whole firm at a glance", icon: <BarChart size={15} />, x: 11, y: 64, side: "left", secondary: true },
  { key: "documents", title: "Documents", line: "Read by AI, checked by you", icon: <Layers size={15} />, x: 87, y: 60, side: "right" },
  { key: "banking", title: "Banking", line: "Statements become vouchers", icon: <Landmark size={15} />, x: 30, y: 82, side: "left", secondary: true },
  { key: "ai", title: "AI assistant", line: "It knows your practice", icon: <Sparkles size={15} />, x: 72, y: 80, side: "right" },
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
        <defs>
          <linearGradient id="ps-connector" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#7fa0ec" stopOpacity="0.05" />
            <stop offset="55%" stopColor="#7fa0ec" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#cfe0ff" stopOpacity="0.6" />
          </linearGradient>
        </defs>
        {MODULES.map((m) => (
          <line
            key={m.key}
            x1={m.x}
            y1={m.y}
            x2={50}
            y2={50}
            stroke="url(#ps-connector)"
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
              className="flex items-center gap-2.5 rounded-xl border border-white/[0.14] bg-white/[0.055] px-3 py-2.5 shadow-[0_10px_30px_rgba(3,8,24,0.45)] backdrop-blur-md"
              style={{ minWidth: 168 }}
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-light/[0.14] text-brand-light ring-1 ring-white/10">
                {m.icon}
              </span>
              <span className="min-w-0">
                <span className="block whitespace-nowrap text-[12.5px] font-semibold leading-none text-white">
                  {m.title}
                </span>
                <span className="mt-1 block whitespace-nowrap text-[10.5px] leading-none text-white/55">
                  {m.line}
                </span>
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* The mark at the centre of the system. */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 lg:block"
        aria-hidden="true"
      >
        <span className="grid h-[52px] w-[52px] place-items-center rounded-full border border-white/20 bg-[#0b1430]/85 shadow-[0_0_40px_rgba(88,122,217,0.55)] backdrop-blur-sm">
          <svg width="26" height="26" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="32" r="24" strokeWidth="3" stroke="rgba(255,255,255,0.22)" />
            <circle
              cx="32"
              cy="32"
              r="24"
              strokeWidth="5"
              strokeLinecap="round"
              className="logo-arc"
              stroke="#7fa0ec"
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
