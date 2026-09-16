import { Panel, SerifHeading, CineReveal } from "@/components/cinematic";
import { DemoForm } from "@/components/DemoForm";
import { Reveal } from "@/components/motion";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { CONTACT } from "@/lib/site";

export const metadata = {
  title: "Book a demo",
  description:
    "See PracticeSync run against a real Indian CA practice — compliance, accounting, banking, payroll and the AI assistant, walked through by someone who knows the domain.",
};

/**
 * The page behind the site's primary call to action.
 *
 * Everything on it is checkable. The three "what happens" steps describe what
 * we will actually do, and the four bullets under them name shipped
 * subsystems — there is no metric, no customer count and no testimonial here,
 * because §16 of the redesign brief forbids inventing any of them and this
 * product has data for none of them.
 */

const WHAT_HAPPENS = [
  {
    step: "01",
    title: "Tell us how you work today",
    body: "Which tools you are on, roughly how many clients, and what you file. Two minutes on the form below is usually enough.",
  },
  {
    step: "02",
    title: "We walk your workflow, not a slide deck",
    body: "A live run through the parts that matter to your practice — a GST month, a bank reconciliation, a payroll run, a year-end close.",
  },
  {
    step: "03",
    title: "You decide, with the awkward questions answered",
    body: "What it does, what it does not, and what moving across from Tally or ClearTax would actually involve. No obligation either way.",
  },
];

const BRING = [
  "A client's GST month — GSTR-1, GSTR-3B and the 2B reconciliation against the purchase register",
  "A bank statement, so you can watch it become vouchers you review rather than type",
  "A payroll run with PF, ESI and §192 TDS, and the employee portal your client's staff would use",
  "A trial balance, and the Schedule III statements that come out the other end",
];

export default function DemoPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      <Panel theme="dark" seam="none" numeral="01" numeralCorner="top-right">
        <div className="grid gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)] lg:gap-16">
          <div>
            <SerifHeading
              eyebrow="Book a demo"
              lines={[
                { text: "See it run against" },
                { text: "a practice like yours.", italic: true },
              ]}
              subtitle="Thirty minutes, on your schedule, with someone who knows Indian practice — not a sales script. Bring a real client's month and we will walk it end to end."
            />

            <div className="mt-14 space-y-8">
              {WHAT_HAPPENS.map((s, i) => (
                <Reveal key={s.step} variant="left" delay={i * 110}>
                  <div className="flex gap-5 border-t border-white/10 pt-6">
                    <span className="font-display text-[26px] italic leading-none text-white/25">
                      {s.step}
                    </span>
                    <span>
                      <span className="block text-[16px] font-semibold text-white">{s.title}</span>
                      <span className="mt-2 block max-w-[48ch] text-[15px] leading-relaxed text-slate-300">
                        {s.body}
                      </span>
                    </span>
                  </div>
                </Reveal>
              ))}
            </div>

            <CineReveal delay={140}>
              <div className="mt-12 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
                <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-white/50">
                  What we can show you
                </p>
                <ul className="mt-4 space-y-3">
                  {BRING.map((b) => (
                    <li key={b} className="flex gap-3 text-[14.5px] leading-relaxed text-slate-300">
                      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand-light" />
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
            </CineReveal>

            <p className="mt-8 text-[14px] text-slate-400">
              Would rather just write?{" "}
              <a
                href={`mailto:${CONTACT.email}?subject=${encodeURIComponent("Demo request")}`}
                className="font-semibold text-brand-light underline-offset-4 hover:underline"
              >
                {CONTACT.email}
              </a>
              {" · "}
              <a href={`tel:${CONTACT.phone.replace(/\s/g, "")}`} className="text-slate-300 hover:text-white">
                {CONTACT.phone}
              </a>
            </p>
          </div>

          <div className="lg:pt-2">
            <DemoForm />
          </div>
        </div>
      </Panel>
    </div>
  );
}
