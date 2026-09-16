import type { Metadata } from "next";
import { Panel, SerifHeading, CineReveal, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Shield } from "@/components/icons";

/**
 * Our Story.
 *
 * THIS PAGE EXISTS BECAUSE THE NAV ITEM DID NOT LEAD ANYWHERE. "Our Story" in
 * the header pointed at `/#story` — an anchor onto a homepage panel headed
 * "Every CA firm runs like this", which is a positioning statement about the
 * READER's practice and not a story about this one. The owner put it plainly:
 * "our story is a big page if you see i guess we have to split it."
 *
 * The homepage keeps a short version of the problem statement (it still has to
 * say what this is, above the fold of the second screen) and links here. The
 * anchor keeps working, because it is in the wild.
 *
 * WHAT IS ON IT. A CA evaluating a new platform is not asking for a founding
 * anecdote; they are asking whether the people who built it understand what
 * they are signing. So this page is the decisions — what was chosen, and more
 * usefully what was REFUSED. Every claim below is a property of the system
 * that can be pointed at in this repository, which is the same bar the
 * homepage's trust section is held to. There is no origin myth, no team
 * photograph and no customer to be trusted by, because none of those is real
 * yet and §16 of the brief forbids inventing them.
 */

export const metadata: Metadata = {
  title: "Our story",
  description:
    "Why PracticeSync exists, what we decided to build, and what we deliberately refuse to do — written for the Chartered Accountant who has to sign the return at the end of it.",
};

/** The decisions. Each is enforced somewhere in the product, not a slogan. */
const DECISIONS = [
  {
    title: "One ledger, not five that reconcile",
    body: "Every accounting event — a sales invoice, a bank line, a payroll run, a depreciation charge — is written by one posting function that asserts the entry balances before it inserts. There is deliberately no second path. That is what makes a GST return computed from the books rather than assembled beside them, and it is why the return and the trial balance cannot disagree.",
  },
  {
    title: "Money is counted in paise, never in decimals",
    body: "Every rupee figure in the system is a whole number of paise. Not a preference: a floating-point rupee loses a paisa on some values and not others, and a return that has to foot will eventually fail to. The conversion to rupees happens once, at the boundary where a statutory file is written — two decimals for GSTR-1, whole rupees for GSTR-3B, as the CGST Act requires.",
  },
  {
    title: "A posted entry is never quietly rewritten",
    body: "Corrections are append-only reversals, enforced by the database rather than by convention. Where the law does allow an entry to be edited or deleted — a manual journal in an open period — the whole entry, its lines and their account names are written to the audit log in the same transaction. The log is what is immutable, not the entry, which is exactly what Rule 3(1) of the Companies (Accounts) Rules presumes.",
  },
  {
    title: "A rate nobody has read is not a rate",
    body: "Every tax rate, threshold and due date is versioned by financial year and carries the year a person last checked it against the Finance Act. Where a figure could not be confirmed, the software says so and refuses rather than falling back on last year's number — because a missing year that silently answers with last year's rate is not an error, it is a confident wrong answer.",
  },
];

/** The refusals. This is the distinctive half and it is all enforced in code. */
const REFUSALS = [
  {
    title: "We do not file anything",
    body: "PracticeSync prepares. It computes GSTR-1, GSTR-3B, GSTR-9, the ITR JSON, 24Q and 26Q from your books and produces the file; you upload and sign on the government portal, then record the ARN here and the period locks. No batch, no scheduler, no retry that resubmits. When filing through software is built it will still wait for an explicit confirmation from a Chartered Accountant, per return, every time.",
  },
  {
    title: "We do not guess a fact we do not hold",
    body: "A vendor with no MSMED classification is named, not assumed to be a large enterprise. An asset with no recorded use is refused, not defaulted. Where two rules disagree about what a reversal costs, both readings are shown and neither is chosen. A nil on a return says which kind of nil it is — nothing happened, or nothing could be derived.",
  },
  {
    title: "We never touch a bank login",
    body: "No credential capture, no stored net-banking passwords, no third party that screen-scrapes. Bank data arrives as a statement you upload; when a live feed is built it will go through India's Account Aggregator framework and the consent will be your client's, time-bound and revocable. This is not a trade-off we intend to revisit.",
  },
  {
    title: "AI proposes, a person decides",
    body: "Extraction and insight produce drafts that a human confirms. No model key ever reaches the browser — every call is made server-side — and nothing an AI produces reaches the ledger or a return without somebody accepting it.",
  },
];

export default function StoryPage() {
  return (
    <>
      {/* ── Why ──────────────────────────────────────────────────────────── */}
      <Panel theme="dark" flush>
        <SerifHeading
          layout="split"
          index="01"
          eyebrow="Our story"
          lines={[
            { text: "We built the software" },
            { text: "we wanted to hand a CA.", italic: true },
          ]}
          subtitle="PracticeSync is an Indian practice-management platform written for the person who has to sign at the end of it. That constraint decided almost everything about how it works."
        />
      </Panel>

      {/* ── The problem ──────────────────────────────────────────────────── */}
      <Panel theme="light">
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
          subtitle="Tally holds the books. ClearTax or the portal holds GST. Winman holds the returns. A spreadsheet holds the deadlines. WhatsApp holds everything the client actually said. None of them can see the others."
        />

        <CineReveal delay={100}>
          <div className="mt-14 grid gap-10 border-t border-slate-900/10 pt-10 md:grid-cols-2 md:gap-14">
            <div>
              <h3 className="font-display text-[22px] italic text-brand-dark">
                The cost is not the licence fees
              </h3>
              <p className="mt-3 max-w-[48ch] text-[15.5px] leading-relaxed text-slate-600">
                It is that a figure has to be carried between them by hand. A purchase
                bill is entered in the books, typed again into the GST working, checked
                a third time against the 2B. Each crossing is a chance to be wrong, and
                the wrongness only shows up on the portal — or a year later, in an
                assessment.
              </p>
            </div>
            <div>
              <h3 className="font-display text-[22px] italic text-brand-dark">
                And nobody can answer a simple question
              </h3>
              <p className="mt-3 max-w-[48ch] text-[15.5px] leading-relaxed text-slate-600">
                &ldquo;Which of my clients has an unfiled return this month, and what
                does it come to?&rdquo; is a question no single tool in that list can
                answer, because the answer needs the books, the returns and the calendar
                at once. So it gets answered by a person, on a Sunday, from memory.
              </p>
            </div>
          </div>
        </CineReveal>
      </Panel>

      {/* ── What we decided ──────────────────────────────────────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          index="03"
          eyebrow="What we decided"
          lines={[{ text: "Four decisions" }, { text: "everything else follows from.", italic: true }]}
          subtitle="None of these is a feature. They are constraints the whole system is held to, and each one is enforced somewhere rather than promised here."
        />

        <div className="mt-14 grid gap-x-12 gap-y-10 md:grid-cols-2">
          {DECISIONS.map((d, i) => (
            <Reveal key={d.title} variant="up" delay={i * 90}>
              <div className="border-t border-white/10 pt-6">
                <span className="font-display text-[13px] leading-none tabular-nums text-gold">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-4 font-display text-[21px] italic text-white">{d.title}</h3>
                <p className="mt-3 max-w-[48ch] text-[14.5px] leading-relaxed text-slate-300">
                  {d.body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </Panel>

      {/* ── What we refuse ───────────────────────────────────────────────── */}
      <Panel theme="light">
        <SerifHeading
          layout="split"
          theme="light"
          index="04"
          eyebrow="What we refuse to do"
          lines={[{ text: "The more useful half" }, { text: "of any product story.", italic: true }]}
          subtitle="Plenty of software will tell you what it can do. These are the four things PracticeSync will not do, in every case because doing them would put your signature behind something you did not see."
        />

        <div className="mt-14 grid gap-x-12 gap-y-10 md:grid-cols-2">
          {REFUSALS.map((r, i) => (
            <Reveal key={r.title} variant="up" delay={i * 90}>
              <div className="border-t border-slate-900/10 pt-6">
                <h3 className="font-display text-[21px] italic text-brand-dark">{r.title}</h3>
                <p className="mt-3 max-w-[48ch] text-[14.5px] leading-relaxed text-slate-600">
                  {r.body}
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
              CA who files it on the portal.
            </p>
          </div>
        </CineReveal>
      </Panel>

      {/* ── Where it is now ──────────────────────────────────────────────── */}
      <Panel theme="dark">
        <SerifHeading
          layout="split"
          index="05"
          eyebrow="Where the product is today"
          lines={[{ text: "Honestly:" }, { text: "further than it looks.", italic: true }]}
          subtitle="Eleven modules are built and connected — accounting and the general ledger, GST, TDS, income tax, payroll with the employee portal, banking, fixed assets, inventory, year-end and Schedule III, clients and documents, and an AI assistant across all of it. What the software still cannot do is transmit a return to a government portal, and that is a set of registrations rather than a set of features."
        />

        <CineReveal delay={120}>
          <p className="mt-10 max-w-[62ch] text-[15px] leading-relaxed text-white/60">
            We would rather say that plainly than describe a roadmap as a product. If
            you want to see where the line falls, book a demo and ask us to walk a real
            client&apos;s month — a GST return, a bank reconciliation, a payroll run —
            right up to the point where the software stops and you take over.
          </p>
        </CineReveal>
      </Panel>

      <CineCTA
        titleLines={[{ text: "See it on your own" }, { text: "client's books.", italic: true }]}
        subtitle="Book a demo and we'll walk a real month end to end — and answer the awkward questions about moving across from Tally, ClearTax or Winman."
      />
    </>
  );
}
