import Link from "next/link";
import { Panel, SerifHeading } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { instrumentSerif, manrope } from "@/lib/fonts";

// PRE-B-015(a), an owner decision of 9 October 2026: the footer's Privacy link opens a plain, factual
// summary of where the data is and where it goes, marked as a summary, with the full notice to follow.
//
// EVERY SENTENCE HERE IS HELD, AND THE WAY IT IS HELD DEPENDS ON WHAT KIND OF SENTENCE IT IS.
//   * A sentence about where data is kept, what leaves for an AI provider, or what is recorded or measured is in
//     the marketing claims ledger (apps/api/tests/_marketing_claims.py) with the test that proves it.
//   * Every other sentence (a heading, a disclaimer, the demo form, and the figures paragraph of the AI card) is in the page-facts table of
//     apps/api/tests/test_the_data_handling_summary_states_only_what_the_code_holds.py, which asserts the page
//     says nothing that is in neither place. The figures paragraph is held by tests that drive the real prompt
//     builders and read every message handed to the model: that rupee amounts leave, which features they leave
//     from, and that no client name is attached to any of them. It once said "only counts", which a reader takes
//     to mean no money figure leaves, and the statement analysis and the assistant's client brief send rupee amounts.
// So rewording a sentence here fails a required check until its proof has been read again.
//
// WHAT THE PAGE DELIBERATELY LEAVES OUT, and the test beside it refuses the vocabulary: anything about what an
// AI provider does with content once it has it (their terms for the plans in use are not confirmed, PRE-B-013),
// encryption, security, certification, retention, and any claim about cookies or third parties as a whole. It
// names no mailbox, no telephone number and no exact hosting region: those are the owner's to confirm
// (PRE-C-006), and the Support page is where a person is sent. It has no `alternates` export: the layout's
// canonical resolves to this page's own address.

export const metadata = {
  title: "How we handle your data",
  description:
    "A plain summary of where PracticeSync keeps your firm's records, where the application runs and which AI providers receive content. It is a summary, not the full privacy notice.",
};

const WHERE: { title: string; body: string; figures?: string }[] = [
  {
    title: "Records stored in Mumbai",
    body: "Supabase hosts the database that holds your firm's and your clients' records, in its Mumbai region.",
  },
  {
    title: "Run from Singapore",
    body: "The PracticeSync API, which does the computing and the checking, runs on Render in Singapore.",
  },
  {
    title: "Sent to AI providers outside India",
    body: "AI features send content to Groq, for text and for PDFs with a text layer, or to Google Gemini, for photographs and scanned pages; both are outside India.",
    figures:
      "Some features also send figures the product has already worked out from your records, such as counts, totals and ratios. Some of those figures are rupee amounts, such as the revenue, expenses and profit the statement analysis sends for two financial years. When you ask the assistant about one client, it is also given figures from that client's records, including rupee amounts. The product attaches no client name to these figures.",
  },
  {
    title: "What is replaced on the way",
    body: "In the assistant and the copilot, anything shaped like a PAN or a GSTIN is replaced before it is sent. Names and amounts you type there are sent as written. A bill, a notice or a statement sent to be read is sent as it is, with every GSTIN and name on it.",
  },
];

const YOUR_VISIT = [
  {
    title: "No screen recording",
    body: "No session-replay or screen-recording tool is built into the product or this website.",
  },
  {
    title: "No tracking scripts",
    body: "This website loads no analytics, advertising or tracking scripts.",
  },
  {
    title: "If you book a demo",
    body: "The form sends what you type to our team by email. It does not write to the product's database.",
  },
];

const NOT_CLAIMED = [
  "This page is a summary. It is not a privacy notice or terms of service.",
  "It does not describe what the AI providers do with content once they receive it.",
  "It does not cover how long records are kept or how they are protected in storage.",
  "It does not name every service the product uses; email delivery and error reporting are two it leaves out.",
];

export default function PrivacyPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      <Panel theme="dark" flush>
        <SerifHeading
          layout="split"
          eyebrow="Privacy"
          lines={[{ text: "How we handle" }, { text: "your data.", italic: true }]}
          subtitle="This is a short, factual summary of where your records are kept and where they go. It is a summary and not our full privacy notice, which is still to come."
        />
      </Panel>

      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          eyebrow="Where it goes"
          lines={[{ text: "Where your records" }, { text: "are, and where they go.", italic: true }]}
          subtitle="The places your firm's information is stored, worked on and sent to."
        />
        <div className="mt-12 grid gap-x-12 gap-y-9 sm:grid-cols-2">
          {WHERE.map((c, i) => (
            <Reveal key={c.title} variant="up" delay={i * 90}>
              <div className="border-t border-slate-900/10 pt-6">
                <h3 className="font-display text-[22px] italic text-brand-dark">{c.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{c.body}</p>
                {c.figures ? <p className="mt-3 text-[15px] leading-relaxed text-slate-600">{c.figures}</p> : null}
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      <Panel theme="dark">
        <SerifHeading
          layout="split"
          eyebrow="Your visit"
          lines={[{ text: "Recording, tracking" }, { text: "and the demo form.", italic: true }]}
          subtitle="What the product and this website do not do, and what the demo form does."
        />
        <div className="mt-12 grid gap-x-12 gap-y-9 sm:grid-cols-3">
          {YOUR_VISIT.map((c, i) => (
            <Reveal key={c.title} variant="up" delay={i * 90}>
              <div className="border-t border-white/10 pt-6">
                <h3 className="font-display text-[22px] italic text-white">{c.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-white/70">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          eyebrow="Not claimed"
          lines={[{ text: "What this summary" }, { text: "does not claim.", italic: true }]}
          subtitle="A short list of what is deliberately left out, so nothing here reads as more than it is."
        />
        <ul className="mt-12 space-y-4">
          {NOT_CLAIMED.map((s) => (
            <li key={s} className="max-w-[60ch] text-[15px] leading-relaxed text-slate-600">
              {s}
            </li>
          ))}
        </ul>
        <p className="mt-10 max-w-[60ch] text-[15px] leading-relaxed">
          <Link href="/support" className="font-semibold text-brand underline underline-offset-2 hover:text-brand-dark">
            For a question about your data, see how to reach us on the Support page.
          </Link>
        </p>
      </Panel>
    </div>
  );
}
