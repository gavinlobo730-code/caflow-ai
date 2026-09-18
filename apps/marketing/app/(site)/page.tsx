import type { Metadata } from "next";
import { Panel, SerifHeading, CineReveal } from "@/components/cinematic";
import { Button } from "@/components/ui";
import { Reveal } from "@/components/motion";
import Link from "next/link";
import { ArrowRight, Shield, Lock, Users, FileText, Landmark, Sparkles } from "@/components/icons";
import { Hero } from "@/components/home/Hero";
import { Ecosystem } from "@/components/home/Ecosystem";
import { BeforeAfter } from "@/components/home/BeforeAfter";
import { AiInAction } from "@/components/home/AiInAction";
import { ProductShowcase } from "@/components/home/ProductShowcase";
import { Grain, ScrollMarquee, CountUp } from "@/components/home/primitives";
import { appLinks } from "@/lib/site";

/**
 * The homepage.
 *
 * UNTIL 16 SEPTEMBER 2026 THIS WAS NOT A REACT PAGE AT ALL. It was
 * public/practicesync-homepage.html — 717 lines of inline-styled HTML with its
 * own hand-rolled JS engine — served at `/` by a Cloudflare `_redirects`
 * rewrite, while every other page on the site was React sharing SiteHeader,
 * SiteFooter, cinematic.tsx and ui.tsx.
 *
 * Every homepage-versus-inner-page defect found in the week before this port
 * was a symptom of that split: the logo rendered at a different size, the CTA
 * was a different blue, the header used a different typeface, the nav gaps
 * differed, the content column was 100px wider, light panels were not inset,
 * the header sat a pixel high, and the homepage scrolled with a JS scroll-jack
 * while everything else scrolled natively. Each was found separately and fixed
 * twice, by hand, in two places.
 *
 * The brief asks for the opposite of that (§21: "The dynamic hero word, premium
 * globe/network visual, typography and motion must feel like one designed
 * system"), which is unreachable while half the site cannot use the other
 * half's components. So the engine became components — see components/home/ —
 * and the reveals, the word-by-word headline entrance, Tilt and Parallax are
 * now the SAME implementations the inner pages use rather than a second copy.
 *
 * Section order follows the brief's own §10, with the panels alternating
 * dark/light because §18 rules out making every section dark.
 */

export const metadata: Metadata = {
  title: "PracticeSync — the AI-first platform for Indian CA firms",
  description:
    "Run your entire practice on one intelligent platform. Compliance, accounting, banking, payroll, clients and an AI assistant — built for Indian Chartered Accountants, with every return computed from your own books.",
};

const TICKER = [
  "GSTR-1",
  "GSTR-3B",
  "GSTR-9",
  "GSTR-2B RECONCILIATION",
  "ITR PREPARATION",
  "TDS 24Q",
  "TDS 26Q",
  "MCA & ROC FORMS",
  "ADVANCE TAX",
  "SALES & PURCHASES",
  "BANKING & RECONCILIATION",
  "INVENTORY",
  "PAYROLL, PF & ESI",
  "EMPLOYEE PORTAL",
  "SCHEDULE III",
  "FIXED ASSETS",
  "AI DOCUMENT EXTRACTION",
  "CLIENT PORTAL",
  "WORKFLOW AUTOMATION",
  "TALLY MIGRATION",
];

/**
 * Trust signals (brief §9).
 *
 * Every one is a property of the system that can be pointed at in this
 * repository. There is deliberately no certification, no compliance badge and
 * no customer logo — §9 permits those only if they are real and approved, and
 * none of them is either.
 */
const TRUST = [
  {
    icon: <Lock size={18} />,
    title: "Two-factor on every firm sign-in",
    body: "TOTP, not an SMS code. The client portal and the employee portal are separate principals with their own, narrower access.",
  },
  {
    icon: <Users size={18} />,
    title: "Access by role, and by assignment",
    body: "Partner, Manager, Executive, Reviewer, Client. A Manager or Executive sees the clients they are assigned to — a firm-wide report means their clients, not the firm's.",
  },
  {
    icon: <FileText size={18} />,
    title: "A ledger that cannot be quietly rewritten",
    body: "A posted entry is never deleted or edited in place. A correction is an append-only reversal, and every deletion writes the whole entry and its lines to the audit log in the same transaction.",
  },
  {
    icon: <Landmark size={18} />,
    title: "Data hosted in India",
    body: "Your firm's and your clients' data sits on infrastructure in the Mumbai region. Bank statements are handled as their own retention category under the DPDP Act.",
  },
  {
    icon: <Shield size={18} />,
    title: "Tenant isolation at two layers",
    body: "Every row carries the firm it belongs to, filtered in the application and enforced again by row-level security in the database.",
  },
  {
    icon: <Sparkles size={18} />,
    title: "AI that proposes, never files",
    body: "Extraction and insight are drafts a person confirms. No AI key ever reaches the browser — every model call is made server-side.",
  },
];

export default function HomePage() {
  return (
    <>
      <Grain />

      {/* 01 ───────────────────────────────────────────────────────────── */}
      <Hero />

      {/* The statutory ticker, between the hero and the first panel. */}
      <div className="relative overflow-hidden border-y border-white/[0.12] bg-[#0a1026] py-5">
        <ScrollMarquee>
          {TICKER.map((t) => (
            <span key={t} className="flex items-center whitespace-nowrap pr-[26px]">
              <span className="text-[13px] font-semibold leading-none tracking-[0.1em] text-white/60">
                {t}
              </span>
              <span className="pl-[26px] text-[#5876c7]">&bull;</span>
            </span>
          ))}
        </ScrollMarquee>
      </div>

      {/* 02 — the positioning statement, and the problem ─────────────────

          THIS PANEL IS "OUR STORY". `id="story"` is what the nav item and the
          footer link point at, and it is load-bearing rather than a leftover
          from an old anchor — see NAV in lib/site.ts. Between 16 and 18
          September the long version lived at `/story`, a page made by copying
          this panel; the copy was never re-written, both pages ended up with
          the same heading and the same callout, and the owner's instruction was
          to keep one of them: *"our story must contain the homepage only not
          the existing our story page delete that page."*

          So the "Read why we built it" link that used to sit under this panel
          is gone with the page it pointed at, and this panel is the whole of
          it. The deleted page's four decisions and four refusals are in git at
          e55227e0 if any of that copy is ever wanted here. */}
      <Panel id="story" theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          index="02"
          eyebrow="Where it starts"
          lines={[
            { text: "Every CA firm runs like this." },
            { text: "Five tools. Five logins.", italic: true },
            { text: "One deadline through the cracks." },
          ]}
          subtitle="PracticeSync replaces Tally, ClearTax, Winman and WhatsApp with a single workspace for compliance, accounting, banking, payroll, clients and documents — where every return is computed from the books rather than assembled beside them."
        />
      </Panel>

      {/* 03 — the platform ecosystem ───────────────────────────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          index="03"
          eyebrow="One connected workspace"
          lines={[{ text: "One workspace." }, { text: "Every part of the practice.", italic: true }]}
          subtitle="Not a suite of products that integrate. One system, one ledger, one source of truth — and each part reads what the others wrote."
        />
        <div className="mt-16">
          <Ecosystem />
        </div>
      </Panel>

      {/* 04 — the old way against the PracticeSync way ─────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          index="04"
          eyebrow="Before and after"
          lines={[{ text: "The difference is not features." }, { text: "It is the shape.", italic: true }]}
          subtitle="What changes when a practice moves onto one platform is the number of places a thing can be."
        />
        <div className="mt-14">
          <BeforeAfter />
        </div>
      </Panel>

      {/* 05 — the actual software ──────────────────────────────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          index="05"
          eyebrow="The product"
          lines={[{ text: "This is the software," }, { text: "not an impression of it.", italic: true }]}
          subtitle="Four screens a CA would use in an ordinary week, built from the product's own components and carrying its own words."
        />
        <div className="mt-14">
          <ProductShowcase />
        </div>
      </Panel>

      {/* 06 — AI in action ─────────────────────────────────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          index="06"
          eyebrow="Intelligence, across the practice"
          lines={[{ text: "Not a chatbot in the corner." }, { text: "A bill, end to end.", italic: true }]}
          subtitle="One real chain, from the moment a client photographs a purchase bill to the moment the deadline lands on your calendar — and the point at which the software deliberately stops."
        />
        <AiInAction />
      </Panel>

      {/* 07 — control, and what the numbers actually are ───────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          index="07"
          eyebrow="How filing works"
          lines={[{ text: "We compute it." }, { text: "You file it.", italic: true }]}
          subtitle="PracticeSync reads your books and produces the return — GSTR-1, GSTR-3B, GSTR-9, the ITR JSON, 24Q and 26Q — computed, reconciled and ready to file. You upload and sign on the government portal, then record the ARN here and the period locks. No software files in your name."
        />

        <div className="mt-16 grid grid-cols-2 gap-x-10 gap-y-12 sm:grid-cols-4">
          {[
            { n: 11, suffix: "+", label: "Modules, one connected workspace" },
            { n: 4, suffix: "", label: "Separate tools replaced by one login" },
            { n: 100, suffix: "%", label: "Filings reviewed by a CA before submit" },
            { n: 4, suffix: "", label: "Compliance domains — GST, ITR, TDS, MCA" },
          ].map((s, i) => (
            <Reveal key={s.label} variant="up" delay={i * 90}>
              <div className={i % 2 === 1 ? "sm:mt-8" : ""}>
                <div className="font-display leading-none text-[clamp(44px,5.5vw,76px)]">
                  <CountUp to={s.n} suffix={s.suffix} />
                </div>
                <p className="mt-3 text-[13px] font-medium leading-[1.5] text-white/55">{s.label}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* 08 — security ─────────────────────────────────────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          index="08"
          eyebrow="Security & trust"
          lines={[{ text: "Your clients' data —" }, { text: "and your sign-off.", italic: true }]}
          subtitle="Six things that are true about how this is built. There are no certification badges on this page, because there are no certifications to show."
        />

        <div className="mt-14 grid gap-x-12 gap-y-9 sm:grid-cols-2">
          {TRUST.map((t, i) => (
            <Reveal key={t.title} variant="up" delay={i * 80}>
              <div className="border-t border-slate-900/10 pt-6">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand/[0.06] text-brand ring-1 ring-brand/15">
                  {t.icon}
                </span>
                <h3 className="mt-4 font-display text-[21px] italic text-brand-dark">{t.title}</h3>
                <p className="mt-2.5 max-w-[46ch] text-[14.5px] leading-relaxed text-slate-600">
                  {t.body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>

        <CineReveal delay={120}>
          <div className="mt-14 flex flex-col items-start gap-5 rounded-2xl border border-gold/30 bg-gold/[0.06] p-6 sm:flex-row sm:items-center md:p-8">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-gold/15 text-gold ring-1 ring-gold/25">
              <Shield size={22} />
            </span>
            <p className="text-[15px] leading-relaxed text-brand-dark md:text-[16px]">
              <span className="font-semibold">Nothing leaves your hands on its own.</span>{" "}
              Every GST return, income-tax return, TDS statement and MCA form waits for an
              explicit confirmation from a Chartered Accountant — and even then, it is that
              CA who files it on the portal. Not a batch, not a scheduler, not a retry.
            </p>
          </div>
        </CineReveal>
      </Panel>

      {/* 09 — where to go next ─────────────────────────────────────────── */}
      <Panel theme="dark" innerClassName="text-center">
        <SerifHeading
          align="center"
          lines={[{ text: "Bring your whole practice" }, { text: "into one place.", italic: true }]}
          subtitle="Book a demo and we will walk a real client's month end to end — a GST return, a bank reconciliation, a payroll run — and answer the awkward questions about moving across."
        />
        <CineReveal delay={120}>
          <div className="mt-10 flex flex-wrap justify-center gap-5">
            <Button href="/demo" variant="accent" className="px-7 py-[15px]">
              Book a demo
              <ArrowRight size={16} />
            </Button>
            <Button href="/products" variant="ghost-light" className="px-7 py-[15px]">
              Explore products
            </Button>
          </div>
        </CineReveal>
        <p className="mt-9 text-[13px] text-white/50">
          Already using PracticeSync?{" "}
          <a href="/access" className="underline underline-offset-4 hover:text-white">
            Sign in here
          </a>
          {" · "}
          <a href={appLinks.signup} className="underline underline-offset-4 hover:text-white">
            Start free trial
          </a>
        </p>
      </Panel>
    </>
  );
}
