import Link from "next/link";
import { Panel, SerifHeading, GlassCard, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { Mail, Calendar, ArrowRight } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { CONTACT, DEMO_BOOKINGS_OPEN } from "@/lib/site";

export const metadata = {
  title: "Support",
  description:
    "Get help with PracticeSync — guides you can read any time, plus hands-on onboarding and data migration for Indian CA firms moving from Tally, ClearTax or Winman.",
};

// THIS PAGE OFFERS ONLY THE HELP THAT EXISTS (PRE-A-026, the owner's decision of
// 16-11-2026). It used to offer email and phone support, Monday to Saturday
// 9am-7pm IST, a reply within one business day and a support line, at an
// address and a number that did not exist. Until a business mailbox exists
// there is no public contact, and the page says so; when `CONTACT.email` is set
// the address is printed, with no hours and no reply time, because a promise
// about a service is the owner's to make once somebody staffs it (POST-B-346).

type Channel = {
  title: string;
  desc: string;
  meta: string;
  link: { label: string; href: string } | null;
};

const CHANNELS: Channel[] = [
  {
    title: "Help centre & guides",
    desc: "Step-by-step guides for GST, ITR, TDS and MCA workflows, plus tips to get more out of every module — read them whenever it suits you.",
    meta: "Available anytime",
    link: { label: "Browse resources", href: "/resources" },
  },
  {
    title: "Onboarding & migration",
    desc: "Moving from Tally, ClearTax, Winman or spreadsheets? We help you bring your clients, ledgers and history across cleanly — no fresh start.",
    meta: "Guided, hands-on setup",
    link: null,
  },
];

const FAQ = [
  {
    q: "How do I get started?",
    a: DEMO_BOOKINGS_OPEN
      ? "Book a demo. We walk a real client's month end to end, and then set up your firm with you and bring your first clients across from Tally or a spreadsheet."
      : "Demo bookings are not open yet. When they open, you book one on the Demo page: we walk a real client's month end to end, and then set up your firm with you and bring your first clients across from Tally or a spreadsheet.",
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
    q: "How is my data protected?",
    a: "Your records sit in a database in Mumbai; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India. Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, access is by role and by client assignment, and the audit log records who created, changed or deleted a client, invoice, bill, receipt or ledger entry — it records changes, not views. PracticeSync also never transmits anything to a government portal — it prepares the return and a CA files it themselves.",
  },
];

const linkCls =
  "mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-brand transition-colors hover:text-brand-dark";

export default function SupportPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Panel theme="dark" flush>
        <SerifHeading
          layout="split"
          eyebrow="Support"
          lines={[{ text: "We're here to help" }, { text: "your firm succeed.", italic: true }]}
          subtitle="From your first client to peak filing season: guides you can read whenever it suits you, and hands-on help moving your firm across."
        />
      </Panel>

      {/* ── Channels ─────────────────────────────────────────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
          eyebrow="How we help"
          theme="light"
          lines={[{ text: "Help, whichever" }, { text: "way suits you.", italic: true }]}
          subtitle="Self-serve when you're in a hurry, hands-on when you're switching over."
        />
        <div className="mt-12 grid gap-x-12 gap-y-9 sm:grid-cols-2">
          {CHANNELS.map((c, i) => (
            <Reveal key={c.title} variant="up" delay={i * 90}>
              <div className="flex flex-col border-t border-slate-900/10 pt-6">
                <h3 className="font-display text-[22px] italic text-brand-dark">{c.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{c.desc}</p>
                <p className="mt-3 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-500">{c.meta}</p>
                {c.link ? (
                  <Link href={c.link.href} className={linkCls}>
                    {c.link.label} <ArrowRight size={15} />
                  </Link>
                ) : null}
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── Get in touch ─────────────────────────────────────────────────── */}
      <Panel id="get-in-touch" theme="dark">
        <SerifHeading
          layout="split"
          eyebrow="Get in touch"
          lines={[{ text: "How to" }, { text: "reach us.", italic: true }]}
          subtitle={
            CONTACT.email
              ? `Write to us at ${CONTACT.email}.`
              : "There is no public email address or phone line yet. When there is one, it is listed here."
          }
        />
        <div className={`mt-12 grid gap-6 ${CONTACT.email ? "lg:grid-cols-2" : "max-w-xl"}`}>
          {CONTACT.email ? (
            <Reveal variant="up">
              <GlassCard className="flex h-full flex-col">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                  <Mail size={20} />
                </span>
                <h3 className="mt-5 font-display text-[22px] italic text-white">Email us</h3>
                <a
                  href={`mailto:${CONTACT.email}`}
                  className="mt-4 self-start break-words text-[17px] font-semibold text-brand-light hover:text-white"
                >
                  {CONTACT.email}
                </a>
              </GlassCard>
            </Reveal>
          ) : null}

          <Reveal variant="up" delay={100}>
            <GlassCard className="flex h-full flex-col">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                <Calendar size={20} />
              </span>
              <h3 className="mt-5 font-display text-[22px] italic text-white">Book a demo</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                {DEMO_BOOKINGS_OPEN
                  ? "See PracticeSync mapped to your firm's workflow in a short, no-pressure walkthrough tailored to how you work."
                  : "Demo bookings are not open yet. The Demo page shows what one covers, and takes bookings once they open."}
              </p>
              <Button href="/demo" variant="light" className="mt-6 w-full">
                {DEMO_BOOKINGS_OPEN ? "Book a demo" : "See what a demo covers"} <ArrowRight size={16} />
              </Button>
            </GlassCard>
          </Reveal>
        </div>
      </Panel>

      {/* ── Common questions ─────────────────────────────────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
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
      {/* The subtitle used to offer a free trial (the Pricing page says there is
          none yet) and to "get in touch" (there is no contact yet, PRE-A-026), so
          it takes the shared default, which follows whether bookings are open. */}
      <CineCTA titleLines={[{ text: "Ready when", italic: true }, { text: "you are." }]} />
    </div>
  );
}
