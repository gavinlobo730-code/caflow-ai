import {
  Clock,
  Plus,
  Send,
  Shield,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Zap,
} from "../../icons";
import { COPILOT, COPILOT_DISCLOSURE, COPILOT_QUESTIONS } from "./productWords";

/**
 * /copilot, redrawn.
 *
 * Copied on 16-11-2026 from apps/web/app/copilot/page.tsx: the title and
 * subtitle, the context picker, New Conversation, the conversation list (an
 * icon for the context each was opened in, and how long ago), the two bubbles,
 * the time, tokens and the two ratings under an answer, the disclosure the page
 * shows before anything is sent (`AI_DISCLOSURES.copilot` in
 * apps/web/lib/ai/disclosure.ts, letter for letter), the box and its
 * placeholder, and the advisory line at the foot. The wording comes from
 * `productWords.ts`, which a test holds to those files. The suggested-question
 * chips the page shows under a conversation are left out.
 *
 * THE DRAWING BEFORE THIS ONE (16-09-2026) SHOWED A CAPABILITY THE COPILOT DOES
 * NOT HAVE. Its answer listed four clients by name with their GSTINs and what
 * each owed. The copilot is given COUNTS from the practice's records and never
 * a client's name (domain/ai_copilot_service.py `_build_context`), and anything
 * shaped like a PAN or a GSTIN is replaced before a message leaves
 * (domain/ai/redaction.py), so it could not have written that answer. It also
 * drew a Chat and Insights switch the product removed (the Insights tab listed
 * recommendations nothing generated). The answer below is the shape the copilot
 * can give: counts, the statutory date its own brief carries, and a plain
 * statement that it holds no names.
 *
 * The questions in the sidebar are ones the product suggests
 * (models/ai_copilot.py); the counts, the times and the token figure are
 * invented. The greys the product uses for the times, the token count and the
 * foot line are drawn one or two steps darker here, so they pass WCAG's 4.5:1 on
 * a public page (a trial axe scan of each screen is what found the last of them).
 */

const CONVERSATIONS = [
  { icon: <Shield size={14} />, title: COPILOT_QUESTIONS.status, when: "4m ago", on: true },
  { icon: <Zap size={14} />, title: COPILOT_QUESTIONS.workflows, when: "2h ago" },
  { icon: <Sparkles size={14} />, title: COPILOT_QUESTIONS.risk, when: "13 Nov 2026" },
  { icon: <Sparkles size={14} />, title: COPILOT_QUESTIONS.tds, when: "10 Nov 2026" },
];

/** The answer, one line per paragraph, as the page renders a reply: `## ` is a heading, `- ` an item. */
const ANSWER = [
  "## Compliance status, from your practice's records",
  "- 3 compliance filings are overdue.",
  "- 9 more fall due in the next 7 days.",
  "- 5 tasks are past their due date.",
  "GSTR-3B is due on the 20th of the following month (Rule 61 CGST Rules).",
  "I am given counts, not client names: the compliance calendar shows which clients these are. Prepare each return here and file it on the portal yourself — never auto-submit.",
];

export function CopilotChat() {
  return (
    <div className="flex min-w-[760px] flex-col bg-[#F8FAFC] text-[#0D1635]">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 border-b border-[#E2E8F0] bg-white px-6 py-4">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#182350] text-white">
            <Sparkles size={16} />
          </span>
          <span>
            <span className="block text-xl font-semibold text-[#0D1635]">{COPILOT.title}</span>
            <span className="mt-0.5 block text-sm text-[#475569]">{COPILOT.subtitle}</span>
          </span>
        </div>
        <span className="rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs text-[#475569]">
          {COPILOT.context} ▾
        </span>
      </div>

      <div className="flex">
        {/* Conversation history */}
        <div className="flex w-64 shrink-0 flex-col border-r border-[#E2E8F0] bg-white">
          <div className="border-b border-[#E2E8F0] p-3">
            <span className="flex w-full items-center gap-2 rounded-lg bg-[#182350] px-3 py-2 text-sm font-medium text-white">
              <Plus size={14} />
              {COPILOT.newConversation}
            </span>
          </div>
          <div className="space-y-1 p-2">
            {CONVERSATIONS.map((c) => (
              <div
                key={c.title}
                className={`rounded-lg px-3 py-2.5 ${c.on ? "bg-[#EFF6FF] text-[#182350]" : "text-[#334155]"}`}
              >
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 text-[#64748B]">{c.icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">{c.title}</p>
                    <div className="mt-0.5 flex items-center gap-1 text-[10px] text-[#475569]">
                      <Clock size={9} />
                      {c.when}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* The conversation */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="px-6 py-4">
            <div className="mx-auto max-w-3xl">
              {/* The CA */}
              <div className="mb-4 flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-[#182350] px-4 py-3 text-sm leading-relaxed text-white">
                  {COPILOT_QUESTIONS.status}
                </div>
              </div>

              {/* The copilot */}
              <div className="mb-4 flex justify-start">
                <span className="mr-2 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#182350] text-white">
                  <Sparkles size={13} />
                </span>
                <div className="max-w-[85%]">
                  <div className="rounded-2xl rounded-tl-sm border border-[#E2E8F0] bg-white px-4 py-3 text-sm leading-relaxed text-[#0D1635] shadow-sm">
                    {ANSWER.map((line) => (
                      <p
                        key={line}
                        className={
                          line.startsWith("##") ? "mt-2 font-semibold" : line.startsWith("- ") ? "pl-3" : ""
                        }
                      >
                        {line.startsWith("## ") ? line.slice(3) : line}
                      </p>
                    ))}
                  </div>
                  <div className="mt-1.5 flex items-center gap-2 px-1 text-[10px] text-[#64748B]">
                    <span>4m ago</span>
                    <span>1284 tokens</span>
                    <span className="ml-auto flex gap-1">
                      <ThumbsUp size={11} />
                      <ThumbsDown size={11} />
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* The box */}
          <div className="border-t border-[#E2E8F0] bg-white px-6 py-4">
            <span className="mx-auto mb-2 block max-w-3xl text-[10px] leading-snug text-[#475569]">
              {COPILOT_DISCLOSURE.sentence}
            </span>
            <div className="mx-auto flex max-w-3xl items-end gap-3">
              <span className="flex min-h-[48px] flex-1 items-center rounded-xl border border-[#E2E8F0] px-4 py-3 text-sm text-[#64748B]">
                {COPILOT.placeholder}
              </span>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#E2E8F0] text-[#64748B]">
                <Send size={15} />
              </span>
            </div>
            <p className="mt-2 text-center text-[10px] text-[#64748B]">{COPILOT.footer}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
