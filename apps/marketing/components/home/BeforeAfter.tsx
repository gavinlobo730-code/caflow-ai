"use client";

import { Reveal } from "../motion";

/**
 * The old way against the PracticeSync way (brief §6).
 *
 * §6 ends with a rule that shapes the whole section: "Do not overclaim
 * measurable results unless PracticeSync has verified customer data." There is
 * none, so there is not a number anywhere below — no hours saved, no percentage
 * faster, no error rate. The contrast is STRUCTURAL and it is drawn rather than
 * asserted: on the left, seven tools with no line between any of them; on the
 * right, one spine everything hangs off.
 *
 * That is also the honest claim. What changes when a practice moves onto one
 * platform is the number of places a thing can be, which is a fact about the
 * shape of the system and not a result somebody has to have measured.
 */

const OLD_TOOLS = [
  "Tally",
  "ClearTax",
  "Winman",
  "WhatsApp",
  "Excel",
  "Email",
  "Gov. portals",
  "Sticky notes",
];

const NEW_SPINE = [
  { label: "Clients", detail: "every entity, one record" },
  { label: "Documents", detail: "collected in the portal, read by AI" },
  { label: "Books", detail: "one ledger, one posting path" },
  { label: "Compliance", detail: "returns computed from those books" },
  { label: "Review & file", detail: "a CA signs off; you file on the portal" },
];

const WHAT_CHANGES = [
  {
    title: "Fewer handoffs",
    body: "A bill is entered once. The ledger, the GST return, the TDS working and the ageing schedule all read the same row.",
  },
  {
    title: "Nothing lives in two places",
    body: "No re-keying between the books and the return, so there is no gap between them to reconcile at the end of the month.",
  },
  {
    title: "You can see the whole practice",
    body: "Every client's deadlines, books and documents on one screen, for whoever on the team is allowed to see them.",
  },
];

export function BeforeAfter() {
  return (
    <>
      <div className="grid gap-8 lg:grid-cols-2 lg:gap-10">
        {/* ── Before ──────────────────────────────────────────────────── */}
        <Reveal variant="left">
          <div className="h-full rounded-2xl border border-slate-900/10 bg-white/60 p-7 md:p-8">
            <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              The old way
            </p>
            <h3 className="mt-3 font-display text-[26px] leading-tight text-brand-dark">
              Seven tools that have never met.
            </h3>

            <div className="relative mt-8 h-[220px]">
              {/* Scattered, unconnected, slightly askew — the picture is the
                  point and it is drawn rather than described. */}
              {OLD_TOOLS.map((t, i) => {
                const positions = [
                  { l: 4, t: 8, r: -6 },
                  { l: 44, t: 0, r: 4 },
                  { l: 74, t: 16, r: -3 },
                  { l: 14, t: 38, r: 5 },
                  { l: 52, t: 44, r: -4 },
                  { l: 2, t: 70, r: 3 },
                  { l: 38, t: 76, r: -5 },
                  { l: 72, t: 62, r: 6 },
                ][i];
                return (
                  <span
                    key={t}
                    className="absolute whitespace-nowrap rounded-lg border border-slate-900/10 bg-white px-3 py-2 text-[13px] font-medium text-slate-500 shadow-[0_2px_8px_rgba(24,35,80,0.06)]"
                    style={{
                      left: `${positions.l}%`,
                      top: `${positions.t}%`,
                      transform: `rotate(${positions.r}deg)`,
                    }}
                  >
                    {t}
                  </span>
                );
              })}
            </div>

            <p className="mt-6 max-w-[44ch] text-[15px] leading-relaxed text-slate-600">
              Compliance in one app, client chats in another, ledgers in a third — and
              nothing talks to anything else. Every figure is typed at least twice.
            </p>
          </div>
        </Reveal>

        {/* ── After ───────────────────────────────────────────────────── */}
        <Reveal variant="right" delay={120}>
          <div className="h-full rounded-2xl border border-brand/15 bg-white p-7 shadow-[0_18px_44px_rgba(24,35,80,0.08)] md:p-8">
            <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-brand">
              With PracticeSync
            </p>
            <h3 className="mt-3 font-display text-[26px] leading-tight text-brand-dark">
              One spine. Everything hangs off it.
            </h3>

            <ol className="relative mt-8 h-[220px]">
              <span
                aria-hidden="true"
                className="absolute left-[9px] top-2 h-[calc(100%-22px)] w-px bg-gradient-to-b from-brand/40 via-brand/25 to-transparent"
              />
              {NEW_SPINE.map((s, i) => (
                <li key={s.label} className="relative flex items-start gap-4 pb-[14px]">
                  <span className="relative z-[1] mt-1 grid h-[19px] w-[19px] shrink-0 place-items-center rounded-full border border-brand/30 bg-white">
                    <span className="h-[7px] w-[7px] rounded-full bg-brand" />
                  </span>
                  <span className="pt-px">
                    <span className="block text-[14.5px] font-semibold leading-none text-brand-dark">
                      {s.label}
                    </span>
                    <span className="mt-1.5 block text-[13px] leading-none text-slate-500">
                      {s.detail}
                    </span>
                  </span>
                  <span className="sr-only">{i < NEW_SPINE.length - 1 ? "then" : ""}</span>
                </li>
              ))}
            </ol>

            <p className="mt-6 max-w-[44ch] text-[15px] leading-relaxed text-slate-600">
              Each step reads what the one before it wrote. The return is computed from
              the books rather than assembled beside them.
            </p>
          </div>
        </Reveal>
      </div>

      <div className="mt-14 grid gap-x-10 gap-y-8 sm:grid-cols-3">
        {WHAT_CHANGES.map((c, i) => (
          <Reveal key={c.title} variant="up" delay={i * 110}>
            <div className="border-t border-slate-900/10 pt-5">
              <h4 className="font-display text-[21px] italic text-brand-dark">{c.title}</h4>
              <p className="mt-2.5 text-[14.5px] leading-relaxed text-slate-600">{c.body}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </>
  );
}
