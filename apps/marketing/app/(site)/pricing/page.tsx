import { Panel, SerifHeading, CineReveal, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { Check, Star, ArrowRight } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { appLinks } from "@/lib/site";

export const metadata = {
  title: "Pricing",
  description:
    "Simple, indicative pricing for Indian CA firms. Solo, Practice and Firm plans covering GST, ITR, TDS, accounting, payroll and AI. Free trial, no credit card.",
};

type Tier = {
  name: string;
  price: string;
  cadence: string | null;
  priceNote: string;
  description: string;
  featuresLead: string;
  features: string[];
  cta: { label: string; href: string; external: boolean };
  highlighted: boolean;
  badge: string | null;
};

const TIERS: Tier[] = [
  {
    name: "Solo",
    price: "₹1,499",
    cadence: "/month",
    priceNote: "Billed monthly · save ~2 months on annual",
    description: "For solo practitioners",
    featuresLead: "What's included",
    features: [
      "1 user",
      "Up to 25 clients",
      "GST, ITR & TDS compliance",
      "Accounting & ledgers",
      "Document storage",
      "Email support",
    ],
    cta: { label: "Start free trial", href: appLinks.signup, external: true },
    highlighted: false,
    badge: null,
  },
  {
    name: "Practice",
    price: "₹3,999",
    cadence: "/month",
    priceNote: "Billed monthly · save ~2 months on annual",
    description: "For growing practices",
    featuresLead: "Everything in Solo, plus",
    features: [
      "Up to 5 users",
      "Up to 150 clients",
      "Payroll",
      "AI assistant",
      "Client portal",
      "Practice analytics",
      "Priority support",
    ],
    cta: { label: "Start free trial", href: appLinks.signup, external: true },
    highlighted: true,
    badge: "Most popular",
  },
  {
    name: "Firm",
    price: "Custom",
    cadence: null,
    priceNote: "Tailored to your firm's size",
    description: "For established firms",
    featuresLead: "Everything in Practice, plus",
    features: [
      "Unlimited users & clients",
      "Dedicated onboarding & migration",
      "Single sign-on (SSO)",
      "Audit logs",
      "SLA & account manager",
    ],
    cta: { label: "Contact sales", href: "/support", external: false },
    highlighted: false,
    badge: null,
  },
];

const INCLUDED = [
  { title: "Data hosted in India", desc: "Your firm's and clients' data stays on infrastructure hosted in India." },
  { title: "Two-factor authentication", desc: "MFA and role-based access on every account, so only your team gets in." },
  { title: "Nothing auto-submitted", desc: "A CA confirms every filing — no return is sent to a government portal automatically." },
  { title: "Free trial, no card", desc: "Start on any plan with a free trial and no credit card required." },
];

const FAQS = [
  {
    q: "Is there a free trial?",
    a: "Yes. Every plan starts with a free trial and no credit card — set up your firm, add a few clients and run the full workflow before you decide.",
  },
  {
    q: "Can I migrate from Tally, ClearTax or Winman?",
    a: "Yes. The Firm plan includes dedicated onboarding and data migration, and our team can help import client masters and opening balances on any plan.",
  },
  {
    q: "Is my data secure and hosted in India?",
    a: "Your data is hosted in India, encrypted, and protected with two-factor authentication and role-based access, so only your team sees your clients' information.",
  },
  {
    q: "Do you file returns automatically?",
    a: "No. PracticeSync prepares everything and flags what needs attention, but nothing is auto-filed — a CA must click to submit every GST, ITR, TDS or MCA return.",
  },
  {
    q: "Can I change plans later?",
    a: "Yes. Move between Solo, Practice and Firm as your practice grows. Final pricing is always confirmed with you during onboarding.",
  },
];

export default function PricingPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Panel theme="dark" seam="none" numeral="01" numeralCorner="top-right">
        <SerifHeading
          eyebrow="Pricing"
          lines={[{ text: "Simple pricing for" }, { text: "firms of every size.", italic: true }]}
          subtitle="One AI-first platform for GST, ITR, TDS, accounting, payroll and clients — priced for solo practitioners through to established firms. Start free, no credit card."
        />
      </Panel>

      {/* ── Tiers ────────────────────────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right" numeral="02" numeralCorner="bottom-left">
        <div className="grid gap-6 md:grid-cols-3">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} variant="up" delay={i * 120} className="h-full">
              <div
                className={`relative flex h-full flex-col rounded-2xl border p-7 ${
                  tier.highlighted
                    ? "border-brand/30 bg-white shadow-[0_24px_60px_rgba(13,22,53,0.12)]"
                    : "border-slate-900/10 bg-white/70"
                }`}
              >
                {tier.badge ? (
                  <span className="absolute -top-3 left-7 inline-flex items-center gap-1.5 rounded-full bg-brand px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-white shadow-sm">
                    <Star size={12} /> {tier.badge}
                  </span>
                ) : null}

                <h3 className="font-display text-[26px] italic leading-none text-brand-dark">{tier.name}</h3>
                <p className="mt-2 text-[14px] text-slate-500">{tier.description}</p>

                <div className="mt-6 flex items-baseline gap-1.5">
                  <span className="font-display text-[clamp(40px,5vw,54px)] leading-none text-brand-dark">{tier.price}</span>
                  {tier.cadence ? <span className="text-[15px] font-medium text-slate-500">{tier.cadence}</span> : null}
                </div>
                <p className="mt-2 text-[12px] text-slate-500">{tier.priceNote}</p>

                <p className="mt-7 text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  {tier.featuresLead}
                </p>
                <ul className="mt-4 space-y-2.5">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2.5 text-[14px] leading-relaxed text-slate-600">
                      <Check size={16} className="mt-0.5 shrink-0 text-brand" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-auto pt-8">
                  <Button
                    href={tier.cta.href}
                    external={tier.cta.external}
                    variant={tier.highlighted ? "primary" : "secondary"}
                    className="w-full"
                  >
                    {tier.cta.label}
                    <ArrowRight size={16} />
                  </Button>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        <p className="mx-auto mt-8 max-w-2xl text-center text-[13px] leading-relaxed text-slate-500">
          All prices are indicative and shown in INR. Final pricing is confirmed with you during
          onboarding — and choosing annual billing saves you roughly two months.
        </p>
      </Panel>

      {/* ── Included in every plan ───────────────────────────────────────── */}
      <Panel theme="dark" seam="rising-left" numeral="03" numeralCorner="top-right">
        <CineReveal>
          <SerifHeading
            eyebrow="Every plan"
            lines={[{ text: "Included with", italic: false }, { text: "every plan.", italic: true }]}
            subtitle="Whatever size your firm is today, these come as standard on Solo, Practice and Firm."
          />
        </CineReveal>
        <div className="mt-12 grid gap-x-12 gap-y-8 sm:grid-cols-2">
          {INCLUDED.map((item, i) => (
            <Reveal key={item.title} variant="up" delay={i * 90}>
              <div className="border-t border-white/10 pt-5">
                <h3 className="font-display text-[22px] italic text-white">{item.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{item.desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right" numeral="04" numeralCorner="bottom-left">
        <CineReveal>
          <SerifHeading
            eyebrow="FAQ"
            theme="light"
            lines={[{ text: "Questions,", italic: false }, { text: "answered.", italic: true }]}
            subtitle="A few things CAs ask us before getting started."
          />
        </CineReveal>
        <div className="mt-12 grid gap-x-12 gap-y-8 md:grid-cols-2">
          {FAQS.map((item, i) => (
            <Reveal key={item.q} variant="up" delay={i * 80}>
              <div className="border-t border-slate-900/10 pt-5">
                <h3 className="font-display text-[21px] italic leading-snug text-brand-dark">{item.q}</h3>
                <p className="mt-2.5 text-[15px] leading-relaxed text-slate-600">{item.a}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CineCTA />
    </div>
  );
}
