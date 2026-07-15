import Link from "next/link";
import {
  PageHero,
  Section,
  SectionHeading,
  Card,
  IconBadge,
  Button,
  CTASection,
} from "@/components/ui";
import { Reveal } from "@/components/motion";
import {
  BookOpen,
  Mail,
  LifeBuoy,
  Phone,
  Clock,
  Calendar,
  ArrowRight,
} from "@/components/icons";
import { CONTACT } from "@/lib/site";

export const metadata = {
  title: "Support",
  description:
    "Get help with PracticeSync — guides, email and phone support, plus hands-on onboarding and data migration for Indian CA firms moving from Tally, ClearTax or Winman.",
};

// The marketing site is a static export with no backend, so contact actions are
// plain mailto:/tel: anchors (never a submitted form). tel is derived from the
// single source of truth, CONTACT.phone — digits only, keeping the leading +.
const emailHref = `mailto:${CONTACT.email}`;
const telHref = `tel:${CONTACT.phone.replace(/[^\d+]/g, "")}`;
const demoHref = `mailto:${CONTACT.email}?subject=${encodeURIComponent(
  "Demo request",
)}`;

// Shared inline styles so the anchor-based footer links and meta chips read
// exactly like the rest of the design system.
const metaCls =
  "mt-4 inline-flex items-center gap-1.5 self-start rounded-full bg-ps-muted px-3 py-1 text-[12px] font-medium text-slate-500";
const footerLinkCls =
  "mt-auto inline-flex items-center gap-1.5 self-start pt-5 text-[13px] font-semibold text-brand transition-colors hover:text-brand-hover";

const CHANNELS = [
  {
    icon: <BookOpen size={20} />,
    title: "Help centre & guides",
    desc: "Step-by-step guides for GST, ITR, TDS and MCA workflows, plus tips to get more out of every module — read them whenever it suits you.",
    meta: "Available anytime",
    label: "Browse resources",
    href: "/resources",
    anchor: false,
  },
  {
    icon: <Mail size={20} />,
    title: "Email support",
    desc: "Questions about the product, your account or a specific filing? Email us and a real person on the team will help you sort it.",
    meta: "Reply within 1 business day",
    label: "Email our team",
    href: emailHref,
    anchor: true,
  },
  {
    icon: <LifeBuoy size={20} />,
    title: "Onboarding & migration",
    desc: "Moving from Tally, ClearTax, Winman or spreadsheets? We help you bring your clients, ledgers and history across cleanly — no fresh start.",
    meta: "Guided, hands-on setup",
    label: "Talk to us",
    href: "#get-in-touch",
    anchor: true,
  },
  {
    icon: <Phone size={20} />,
    title: "Phone support",
    desc: "Prefer to talk it through? Reach our support line during working hours for a quick hand with anything that needs a conversation.",
    meta: "Priority on Practice & Firm plans",
    label: "Call us",
    href: telHref,
    anchor: true,
  },
];

const FAQ = [
  {
    q: "How do I get started?",
    a: "Start a free trial, add your firm and import your first clients — most firms are up and running within a day. No credit card is needed to try PracticeSync.",
  },
  {
    q: "Can you help migrate my existing data?",
    a: "Yes. Our team helps you bring across clients, ledgers and history from Tally, ClearTax, Winman and spreadsheets, so you carry your practice forward instead of rebuilding it.",
  },
  {
    q: "Is onboarding included?",
    a: "Every plan includes guided onboarding. Practice and Firm plans also get a dedicated onboarding specialist to set up your team, templates and compliance calendar.",
  },
  {
    q: "What are your support hours?",
    a: "Our support team is available Monday to Saturday, 9am–7pm IST. Email us any time and we'll respond within one business day.",
  },
  {
    q: "How is my data protected?",
    a: "Your data is hosted in India, secured with two-factor authentication and role-based access, and every action is captured in a full audit log. Nothing is ever filed to a government portal without an explicit click from a CA.",
  },
];

export default function SupportPage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <PageHero
        eyebrow="Support"
        title="We're here to help your firm succeed"
        subtitle="From your first client to peak filing season, our team knows Indian practice inside out — and we're ready to help by guide, email or phone."
      />

      {/* ── Support channels ─────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="How we help"
            title="Help, whichever way suits you"
            subtitle="Self-serve when you're in a hurry, hands-on when you're switching over. Every PracticeSync plan includes real support from people who understand CA workflows."
          />
        </Reveal>
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {CHANNELS.map((c, i) => (
            <Reveal key={c.title} delay={i * 100}>
              <Card className="h-full">
                <div className="flex h-full flex-col">
                  <IconBadge>{c.icon}</IconBadge>
                  <h3 className="mt-5 text-[17px] font-bold text-brand-dark">
                    {c.title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-slate-600">
                    {c.desc}
                  </p>
                  <span className={metaCls}>
                    <Clock size={13} /> {c.meta}
                  </span>
                  {c.anchor ? (
                    <a href={c.href} className={footerLinkCls}>
                      {c.label} <ArrowRight size={15} />
                    </a>
                  ) : (
                    <Link href={c.href} className={footerLinkCls}>
                      {c.label} <ArrowRight size={15} />
                    </Link>
                  )}
                </div>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Get in touch ─────────────────────────────────────────────────── */}
      <Section id="get-in-touch" className="bg-white">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="Get in touch"
            title="Talk to a real person"
            subtitle="No bots, no ticket black holes. Reach us directly — we usually reply within one business day, Monday to Saturday."
          />
        </Reveal>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {/* Email us */}
          <Reveal>
            <Card className="h-full">
              <div className="flex h-full flex-col">
                <IconBadge>
                  <Mail size={20} />
                </IconBadge>
                <h3 className="mt-5 text-[17px] font-bold text-brand-dark">
                  Email us
                </h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">
                  The fastest way to reach us for anything — product, billing or
                  your account.
                </p>
                <a
                  href={emailHref}
                  className="mt-4 self-start break-words text-[18px] font-bold text-brand transition-colors hover:text-brand-hover"
                >
                  {CONTACT.email}
                </a>
                <Button
                  href={emailHref}
                  external
                  variant="primary"
                  className="mt-auto w-full"
                >
                  Send an email
                  <ArrowRight size={16} />
                </Button>
              </div>
            </Card>
          </Reveal>

          {/* Call us */}
          <Reveal delay={100}>
            <Card className="h-full">
              <div className="flex h-full flex-col">
                <IconBadge>
                  <Phone size={20} />
                </IconBadge>
                <h3 className="mt-5 text-[17px] font-bold text-brand-dark">
                  Call us
                </h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">
                  Speak to our support team during working hours, Monday to
                  Saturday, 9am–7pm IST.
                </p>
                <a
                  href={telHref}
                  className="mt-4 self-start break-words text-[18px] font-bold text-brand transition-colors hover:text-brand-hover"
                >
                  {CONTACT.phone}
                </a>
                <Button
                  href={telHref}
                  external
                  variant="secondary"
                  className="mt-auto w-full"
                >
                  Call now
                  <ArrowRight size={16} />
                </Button>
              </div>
            </Card>
          </Reveal>

          {/* Book a demo */}
          <Reveal delay={200}>
            <Card className="h-full">
              <div className="flex h-full flex-col">
                <IconBadge>
                  <Calendar size={20} />
                </IconBadge>
                <h3 className="mt-5 text-[17px] font-bold text-brand-dark">
                  Book a demo
                </h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">
                  See PracticeSync mapped to your firm&apos;s workflow in a
                  short, no-pressure walkthrough tailored to how you work.
                </p>
                <p className="mt-4 self-start text-[13px] font-medium text-slate-500">
                  Typically around 30 minutes.
                </p>
                <Button
                  href={demoHref}
                  external
                  variant="primary"
                  className="mt-auto w-full"
                >
                  Request a demo
                  <ArrowRight size={16} />
                </Button>
              </div>
            </Card>
          </Reveal>
        </div>
      </Section>

      {/* ── Common questions ─────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="Common questions"
            title="Answers before you switch"
            subtitle="A few things CA firms ask us most often."
          />
        </Reveal>
        <div className="mx-auto mt-12 grid max-w-3xl gap-4">
          {FAQ.map((f, i) => (
            <Reveal key={f.q} delay={i * 100}>
              <Card>
                <h3 className="text-[16px] font-bold text-brand-dark">{f.q}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">
                  {f.a}
                </p>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CTASection
        title="Ready when you are"
        subtitle="Try PracticeSync free, or get in touch and we'll help your firm make the switch."
      />
    </>
  );
}
