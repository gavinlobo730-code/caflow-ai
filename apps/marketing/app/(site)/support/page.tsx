import Link from "next/link";
import { Panel, SerifHeading, GlassCard, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { Mail, Phone, Calendar, ArrowRight } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
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
const demoHref = `mailto:${CONTACT.email}?subject=${encodeURIComponent("Demo request")}`;

const CHANNELS = [
  {
    title: "Help centre & guides",
    desc: "Step-by-step guides for GST, ITR, TDS and MCA workflows, plus tips to get more out of every module — read them whenever it suits you.",
    meta: "Available anytime",
    label: "Browse resources",
    href: "/resources",
    anchor: false,
  },
  {
    title: "Email support",
    desc: "Questions about the product, your account or a specific filing? Email us and a real person on the team will help you sort it.",
    meta: "Reply within 1 business day",
    label: "Email our team",
    href: emailHref,
    anchor: true,
  },
  {
    title: "Onboarding & migration",
    desc: "Moving from Tally, ClearTax, Winman or spreadsheets? We help you bring your clients, ledgers and history across cleanly — no fresh start.",
    meta: "Guided, hands-on setup",
    label: "Talk to us",
    href: "#get-in-touch",
    anchor: true,
  },
  {
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

const linkCls =
  "mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-brand transition-colors hover:text-brand-hover";

export default function SupportPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Panel theme="dark" seam="none">
        <SerifHeading
          eyebrow="Support"
          lines={[{ text: "We're here to help" }, { text: "your firm succeed.", italic: true }]}
          subtitle="From your first client to peak filing season, our team knows Indian practice inside out — and we're ready to help by guide, email or phone."
        />
      </Panel>

      {/* ── Channels ─────────────────────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right">
        <SerifHeading
          eyebrow="How we help"
          theme="light"
          lines={[{ text: "Help, whichever" }, { text: "way suits you.", italic: true }]}
          subtitle="Self-serve when you're in a hurry, hands-on when you're switching over. Every PracticeSync plan includes real support from people who understand CA workflows."
        />
        <div className="mt-12 grid gap-x-12 gap-y-9 sm:grid-cols-2">
          {CHANNELS.map((c, i) => (
            <Reveal key={c.title} variant="up" delay={i * 90}>
              <div className="flex flex-col border-t border-slate-900/10 pt-6">
                <h3 className="font-display text-[22px] italic text-brand-dark">{c.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{c.desc}</p>
                <p className="mt-3 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-400">{c.meta}</p>
                {c.anchor ? (
                  <a href={c.href} className={linkCls}>
                    {c.label} <ArrowRight size={15} />
                  </a>
                ) : (
                  <Link href={c.href} className={linkCls}>
                    {c.label} <ArrowRight size={15} />
                  </Link>
                )}
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── Get in touch ─────────────────────────────────────────────────── */}
      <Panel id="get-in-touch" theme="dark" seam="rising-left">
        <SerifHeading
          eyebrow="Get in touch"
          lines={[{ text: "Talk to a" }, { text: "real person.", italic: true }]}
          subtitle="No bots, no ticket black holes. Reach us directly — we usually reply within one business day, Monday to Saturday."
        />
        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          <Reveal variant="up">
            <GlassCard className="flex h-full flex-col">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                <Mail size={20} />
              </span>
              <h3 className="mt-5 font-display text-[22px] italic text-white">Email us</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                The fastest way to reach us for anything — product, billing or your account.
              </p>
              <a href={emailHref} className="mt-4 self-start break-words text-[17px] font-semibold text-brand-light hover:text-white">
                {CONTACT.email}
              </a>
              <Button href={emailHref} external variant="light" className="mt-auto w-full">
                Send an email <ArrowRight size={16} />
              </Button>
            </GlassCard>
          </Reveal>

          <Reveal variant="up" delay={100}>
            <GlassCard className="flex h-full flex-col">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                <Phone size={20} />
              </span>
              <h3 className="mt-5 font-display text-[22px] italic text-white">Call us</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                Speak to our support team during working hours, Monday to Saturday, 9am–7pm IST.
              </p>
              <a href={telHref} className="mt-4 self-start break-words text-[17px] font-semibold text-brand-light hover:text-white">
                {CONTACT.phone}
              </a>
              <Button href={telHref} external variant="ghost-light" className="mt-auto w-full">
                Call now <ArrowRight size={16} />
              </Button>
            </GlassCard>
          </Reveal>

          <Reveal variant="up" delay={200}>
            <GlassCard className="flex h-full flex-col">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                <Calendar size={20} />
              </span>
              <h3 className="mt-5 font-display text-[22px] italic text-white">Book a demo</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                See PracticeSync mapped to your firm&apos;s workflow in a short, no-pressure walkthrough tailored to how you work.
              </p>
              <p className="mt-4 self-start text-[13px] font-medium text-slate-400">Typically around 30 minutes.</p>
              <Button href={demoHref} external variant="light" className="mt-auto w-full">
                Request a demo <ArrowRight size={16} />
              </Button>
            </GlassCard>
          </Reveal>
        </div>
      </Panel>

      {/* ── Common questions ─────────────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right">
        <SerifHeading
          eyebrow="Common questions"
          theme="light"
          lines={[{ text: "Answers before" }, { text: "you switch.", italic: true }]}
          subtitle="A few things CA firms ask us most often."
        />
        <div className="mt-12 grid gap-x-12 gap-y-8 md:grid-cols-2">
          {FAQ.map((f, i) => (
            <Reveal key={f.q} variant="up" delay={i * 80}>
              <div className="border-t border-slate-900/10 pt-5">
                <h3 className="font-display text-[21px] italic leading-snug text-brand-dark">{f.q}</h3>
                <p className="mt-2.5 text-[15px] leading-relaxed text-slate-600">{f.a}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CineCTA
        titleLines={[{ text: "Ready when", italic: true }, { text: "you are." }]}
        subtitle="Try PracticeSync free, or get in touch and we'll help your firm make the switch."
      />
    </div>
  );
}
