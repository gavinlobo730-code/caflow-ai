"use client";

import { useState } from "react";
import { Reveal } from "../motion";
import { BankQueue } from "./screens/BankQueue";
import { Gstr3bReview } from "./screens/Gstr3bReview";
import { CopilotChat } from "./screens/CopilotChat";
import { ClientOverview } from "./screens/ClientOverview";

/**
 * Four hand-drawn recreations of the product's screens (brief §7 — "one of the
 * most important additions after the hero… Visitors should not only see a
 * beautiful concept; they should see the actual software").
 *
 * WHY THESE ARE BUILT AND NOT PHOTOGRAPHED. An owner decision of 16-09-2026,
 * taken over supplying screenshots: crisp at any pixel ratio rather than one;
 * roughly 3 KB rather than 200; animatable between states, which §7 asks for
 * and an image cannot do; selectable, translatable and readable by a screen
 * reader.
 *
 * ⚠️ THE ARGUMENT THAT THEY ARE "HONEST BECAUSE A RECREATION IS CODE IN THE
 * SAME REPOSITORY" WAS WRONG, AND THE PAGE SAID MORE THAN IT KNEW (POST-A-121,
 * 30-10-2026). A recreation goes stale exactly as silently as a screenshot:
 * nothing ties it to the product, and the client Overview here still draws the
 * 17-item sidebar the product replaced on 25-09-2026 with its module grid. The
 * page used to say the screens were made out of the product's own parts and
 * spoke its own words, under a heading that denied they were any kind of
 * impression. They are an impression, and the page now says so; a rule in
 * `apps/api/tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`
 * refuses the old sentences. Re-copying the four screens from the product, with
 * a check that ties the module list here to the product's, is still open
 * (POST-A-121).
 *
 * Each screen's own file records which product file its strings were first
 * copied from. The FIGURES are invented, and the figures that are meant to add up do add up — the
 * §49(5) set-off in the GSTR-3B screen is worked properly, because the people
 * this page is for will check it.
 *
 * The frame is deliberately thin. §7: "Use device/browser frames sparingly; the
 * UI itself should be the focus."
 */

const TABS = [
  {
    key: "bank",
    label: "Banking",
    caption: "A statement line arrives as a voucher you review, not a row you type.",
    path: "practicesync.app / clients / vaidehi-textiles / bank",
    screen: <BankQueue />,
  },
  {
    key: "gst",
    label: "GSTR-3B",
    caption:
      "Computed from the books, with the §49(5) set-off worked in order — and reverse charge kept out of it, because credit cannot pay it.",
    path: "practicesync.app / gst / gstr3b",
    screen: <Gstr3bReview />,
  },
  {
    key: "copilot",
    label: "AI Copilot",
    caption: "Ask about the whole book of clients. Every answer says where it came from.",
    path: "practicesync.app / copilot",
    screen: <CopilotChat />,
  },
  {
    key: "client",
    label: "Client workspace",
    caption: "One client, everything about them, and what needs doing next.",
    path: "practicesync.app / clients / vaidehi-textiles",
    screen: <ClientOverview />,
  },
];

export function ProductShowcase() {
  const [active, setActive] = useState(0);
  const tab = TABS[active];

  return (
    <div>
      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Product screens"
        className="flex flex-wrap gap-2"
      >
        {TABS.map((t, i) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={i === active}
            onClick={() => setActive(i)}
            className={`rounded-full border px-4 py-2 text-[13px] font-medium transition-colors ${
              i === active
                ? "border-brand-light/50 bg-brand-light/15 text-white"
                : "border-white/10 text-white/55 hover:border-white/25 hover:text-white/85"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <p className="mt-5 max-w-[68ch] text-[15px] leading-relaxed text-slate-300">
        {tab.caption}
      </p>

      {/* Frame */}
      <Reveal variant="up" delay={80} className="mt-7">
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-white shadow-[0_30px_80px_rgba(3,8,24,0.55)]">
          <div className="flex items-center gap-2 border-b border-[#E2E8F0] bg-[#F1F5F9] px-4 py-2.5">
            <span className="flex gap-1.5" aria-hidden="true">
              <span className="h-2.5 w-2.5 rounded-full bg-[#CBD5E1]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#CBD5E1]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#CBD5E1]" />
            </span>
            <span className="ml-3 truncate font-mono text-[10.5px] text-[#94A3B8]">
              {tab.path}
            </span>
          </div>
          {/* The screens are laid out at their real widths; a narrow viewport
              scrolls rather than reflowing them into something the product
              does not actually look like. */}
          <div className="overflow-x-auto">{tab.screen}</div>
        </div>
      </Reveal>

      <p className="mt-6 text-[12.5px] leading-relaxed text-white/40">
        Redrawn by hand, not screenshots, so a label on one may differ from the live
        software. The client names and figures are illustrative — no real client
        appears on this page.
      </p>
    </div>
  );
}
