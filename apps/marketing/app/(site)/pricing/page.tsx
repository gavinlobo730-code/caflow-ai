import {
  Section,
  SectionHeading,
  Button,
  Card,
  FeatureCard,
  PageHero,
  CTASection,
} from "@/components/ui";
import { Check, Star, ArrowRight, Globe, Lock, Shield, Zap } from "@/components/icons";
import { Reveal } from "@/components/motion";
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
    featuresLead: "What's included:",
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
    featuresLead: "Everything in Solo, plus:",
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
    featuresLead: "Everything in Practice, plus:",
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
  {
    icon: <Globe size={20} />,
    title: "Data hosted in India",
    desc: "Your firm's and clients' data stays on infrastructure hosted in India.",
  },
  {
    icon: <Lock size={20} />,
    title: "Two-factor authentication",
    desc: "MFA and role-based access on every account, so only your team gets in.",
  },
  {
    icon: <Shield size={20} />,
    title: "Nothing auto-submitted",
    desc: "A CA confirms every filing — no return is sent to a government portal automatically.",
  },
  {
    icon: <Zap size={20} />,
    title: "Free trial, no card",
    desc: "Start on any plan with a free trial and no credit card required.",
  },
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
    <>
      <PageHero
        eyebrow="Pricing"
        title="Simple pricing for firms of every size"
        subtitle="One AI-first platform for GST, ITR, TDS, accounting, payroll and clients — priced for solo practitioners through to established firms. Start free, no credit card."
      />

      {/* ── Pricing tiers ────────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <div className="grid gap-6 md:grid-cols-3">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} variant="up" delay={i * 130} className="h-full">
              <Card
                className={`relative flex h-full flex-col ${
                  tier.highlighted ? "ring-2 ring-brand" : ""
                }`}
              >
                {tier.badge ? (
                  <span className="absolute -top-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-brand px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-white shadow-sm">
                    <Star size={12} /> {tier.badge}
                  </span>
                ) : null}

                <h3 className="text-[18px] font-bold text-brand-dark">{tier.name}</h3>
                <p className="mt-1 text-[14px] text-slate-600">{tier.description}</p>

                <div className="mt-5 flex items-baseline gap-1">
                  <span className="text-[34px] font-bold tracking-tight text-brand-dark">
                    {tier.price}
                  </span>
                  {tier.cadence ? (
                    <span className="text-[15px] font-medium text-slate-500">
                      {tier.cadence}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1.5 text-[12px] text-slate-500">{tier.priceNote}</p>

                <p className="mt-6 text-[13px] font-semibold text-brand-dark">
                  {tier.featuresLead}
                </p>
                <ul className="mt-3 space-y-2.5">
                  {tier.features.map((f) => (
                    <li
                      key={f}
                      className="flex items-start gap-2.5 text-[14px] leading-relaxed text-slate-600"
                    >
                      <Check size={17} className="mt-0.5 shrink-0 text-emerald-500" />
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
              </Card>
            </Reveal>
          ))}
        </div>

        <p className="mx-auto mt-8 max-w-2xl text-center text-[13px] leading-relaxed text-slate-500">
          All prices are indicative and shown in INR. Final pricing is confirmed
          with you during onboarding — and choosing annual billing saves you
          roughly two months.
        </p>
      </Section>

      {/* ── Included in every plan ───────────────────────────────────────── */}
      <Section className="bg-white">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="Every plan"
            title="Included with every plan"
            subtitle="Whatever size your firm is today, these come as standard on Solo, Practice and Firm."
          />
        </Reveal>
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {INCLUDED.map((item, i) => (
            <Reveal key={item.title} delay={i * 90} className="h-full">
              <FeatureCard icon={item.icon} title={item.title} desc={item.desc} />
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="FAQ"
            title="Questions, answered"
            subtitle="A few things CAs ask us before getting started."
          />
        </Reveal>
        <div className="mx-auto mt-14 grid max-w-4xl gap-6 md:grid-cols-2">
          {FAQS.map((item, i) => (
            <Reveal key={item.q} delay={i * 90} className="h-full">
              <Card className="h-full">
                <h3 className="text-[16px] font-bold text-brand-dark">{item.q}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{item.a}</p>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      <CTASection />
    </>
  );
}
