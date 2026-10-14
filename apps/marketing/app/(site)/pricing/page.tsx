import { Panel, SerifHeading, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { Check, Star, ArrowRight } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";

export const metadata = {
  title: "Pricing",
  description:
    "Simple, indicative pricing for Indian CA firms. Solo, Practice and Firm plans covering GST, ITR, TDS, accounting, payroll and AI. Prices are indicative and confirmed during onboarding.",
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
    priceNote: "Indicative · confirmed during onboarding",
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
    cta: { label: "Book a demo", href: "/demo", external: false },
    highlighted: false,
    badge: null,
  },
  {
    name: "Practice",
    price: "₹3,999",
    cadence: "/month",
    priceNote: "Indicative · confirmed during onboarding",
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
    cta: { label: "Book a demo", href: "/demo", external: false },
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
    ],
    cta: { label: "Book a demo", href: "/demo", external: false },
    highlighted: false,
    badge: null,
  },
];

const INCLUDED = [
  { title: "Database in Mumbai", desc: "Records sit in a Mumbai database. The servers that run the application are in Singapore, and the AI features call providers outside India." },
  { title: "Two-factor authentication", desc: "TOTP two-factor for Partners and Managers on firm administration, billing, payroll and approvals, and role-based access on every account." },
  { title: "Nothing auto-submitted", desc: "PracticeSync prepares the return; a CA files it on the portal. The software never transmits anything to a government portal." },
  { title: "Indicative prices", desc: "The prices above are indicative. Final pricing is confirmed with you during onboarding, and there is no billing to set up before then." },
];

const FAQS = [
  {
    q: "Is there a free trial?",
    a: "Not yet. Book a demo and we will walk a real client's month end to end, so you can judge the workflow before you decide anything.",
  },
  {
    q: "Can I migrate from Tally, ClearTax or Winman?",
    a: "Yes. The Firm plan includes dedicated onboarding and data migration, and our team can help import client masters and opening balances on any plan.",
  },
  {
    q: "Is my data secure, and where is it hosted?",
    a: "The database is in the Mumbai region; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India. Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, and everyone works under role-based access, so only your team sees your clients' information.",
  },
  {
    q: "Does PracticeSync file returns for me?",
    a: "No — and it is worth being precise about this. PracticeSync computes the return from your books. For GSTR-1 and GSTR-3B it produces the JSON file you upload; for the income-tax return and the TDS statements it lays the figures out for you to key into the government's own utility. You upload and sign it on the government portal yourself, then record it back here, which is what locks the period. The software never transmits anything to a portal, for GST, ITR, TDS or MCA.",
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
      <Panel theme="dark" flush>
        <SerifHeading
          layout="split"
          eyebrow="Pricing"
          lines={[{ text: "Simple pricing for" }, { text: "firms of every size.", italic: true }]}
          subtitle="One AI-first platform for GST, ITR, TDS, accounting, payroll and clients — priced for solo practitioners through to established firms."
        />
      </Panel>

      {/* ── Tiers ────────────────────────────────────────────────────────── */}
      <Panel theme="light">
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
          onboarding.
        </p>
      </Panel>

      {/* ── Included in every plan ───────────────────────────────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          eyebrow="Every plan"
          lines={[{ text: "Included with", italic: false }, { text: "every plan.", italic: true }]}
          subtitle="Whatever size your firm is today, these come as standard on Solo, Practice and Firm."
        />
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
      <Panel theme="light">
        <SerifHeading
          layout="split"
          eyebrow="Common questions"
          theme="light"
          lines={[{ text: "Questions,", italic: false }, { text: "answered.", italic: true }]}
          subtitle="A few things CAs ask us before getting started."
        />
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
