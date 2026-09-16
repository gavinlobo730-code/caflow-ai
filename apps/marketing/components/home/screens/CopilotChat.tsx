import { Sparkles, Shield, Users, Zap, BarChart } from "../../icons";

/**
 * /copilot, recreated.
 *
 * Verbatim from apps/web/app/copilot/page.tsx: the title and subtitle, the
 * context options, the Chat/Insights segmented control with its red count
 * badge, "New Conversation", "Ask anything about your clients, compliance, GST,
 * TDS...", and the footer line — which is the one that matters:
 *
 *   "AI responses are advisory — always verify with source documents. Never
 *    auto-submit to government portals."
 *
 * The answer shown is the shape this product's copilot actually returns: a
 * heading, the statutory position, then the clients with their GSTINs and what
 * each owes — and a closing line that says the figures were prepared from the
 * books and that the CA files them. That last sentence is why this screen is in
 * the showcase at all.
 */

const CONVERSATIONS = [
  { icon: <Shield size={13} />, title: "GST filing status for Q1 FY27", when: "4h ago", on: true },
  { icon: <Users size={13} />, title: "TDS deposit position for Rajhans Polymers", when: "22m ago" },
  { icon: <Sparkles size={13} />, title: "Risk clients this month", when: "2d ago" },
  { icon: <Zap size={13} />, title: "Which workflows have failed recently?", when: "18 Aug" },
  { icon: <BarChart size={13} />, title: "Q2 FY 2026-27 realisation by partner", when: "just now" },
];

const CLIENTS = [
  ["Rajhans Polymers Pvt Ltd", "27AAECR2938K1Z1", "₹4,86,200 payable"],
  ["Suvarna Agro Exports LLP", "29AABCS5647L1ZT", "₹1,12,450 payable"],
  ["Meghdoot Interiors Pvt Ltd", "07AAGCM8821P1ZU", "nil return"],
  ["Vaidya Consulting Services", "24AACCV4419N1Z3", "₹68,900 payable"],
];

export function CopilotChat() {
  return (
    <div className="flex min-w-[760px] flex-col bg-[#F8FAFC] text-[#0F172A]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#E2E8F0] bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#182350] text-white">
            <Sparkles size={16} />
          </span>
          <span>
            <span className="block text-[17px] font-semibold leading-tight text-[#182350]">
              AI Copilot
            </span>
            <span className="block text-[11.5px] text-[#64748B]">
              Intelligent assistant for your CA practice
            </span>
          </span>
        </div>
        <div className="hidden items-center gap-2 sm:flex">
          <span className="rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-[11.5px] text-[#475569]">
            Compliance
          </span>
          <span className="flex gap-1 rounded-lg border border-[#E2E8F0] bg-white p-0.5">
            <span className="rounded-md bg-[#182350] px-3 py-1.5 text-[11.5px] font-medium text-white">
              Chat
            </span>
            <span className="relative rounded-md px-3 py-1.5 text-[11.5px] font-medium text-[#64748B]">
              Insights
              <span className="absolute -right-1 -top-1 grid h-4 w-4 place-items-center rounded-full bg-red-500 text-[9px] font-bold text-white">
                6
              </span>
            </span>
          </span>
        </div>
      </div>

      <div className="flex">
        {/* Sidebar */}
        <div className="hidden w-60 shrink-0 flex-col border-r border-[#E2E8F0] bg-white lg:flex">
          <div className="border-b border-[#F1F5F9] p-3">
            <span className="flex items-center justify-center gap-2 rounded-lg bg-[#182350] px-3 py-2 text-[12.5px] font-medium text-white">
              + New Conversation
            </span>
          </div>
          <div className="space-y-1 p-2">
            {CONVERSATIONS.map((c) => (
              <div
                key={c.title}
                className={`flex items-start gap-2 rounded-lg px-2.5 py-2 ${
                  c.on ? "bg-[#F1F5F9]" : ""
                }`}
              >
                <span className={`mt-0.5 shrink-0 ${c.on ? "text-[#182350]" : "text-[#94A3B8]"}`}>
                  {c.icon}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[11.5px] font-medium text-[#334155]">
                    {c.title}
                  </span>
                  <span className="block text-[10px] text-[#94A3B8]">{c.when}</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Conversation */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="space-y-4 p-5">
            {/* User */}
            <div className="flex justify-end">
              <p className="max-w-[80%] rounded-2xl rounded-br-md bg-[#182350] px-4 py-2.5 text-[12.5px] leading-relaxed text-white">
                Which clients have GSTR-3B pending for August 2026?
              </p>
            </div>

            {/* Assistant */}
            <div className="flex gap-3">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[#182350] text-white">
                <Sparkles size={13} />
              </span>
              <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-[#E2E8F0] bg-white px-4 py-3.5">
                <p className="text-[13px] font-bold text-[#0F172A]">
                  4 clients have GSTR-3B pending for 08/2026
                </p>
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-[#475569]">
                  Due 20 September 2026. Interest under CGST §50(1) runs at 18% p.a. on the
                  cash-ledger portion only.
                </p>
                <ul className="mt-3 space-y-1.5">
                  {CLIENTS.map(([name, gstin, amount]) => (
                    <li key={gstin} className="flex flex-wrap items-baseline gap-x-2 text-[11.5px]">
                      <span className="font-medium text-[#334155]">{name}</span>
                      <span className="font-mono text-[10.5px] text-[#94A3B8]">{gstin}</span>
                      <span
                        className={`ml-auto font-mono ${
                          amount === "nil return" ? "text-[#94A3B8]" : "font-semibold text-[#0F172A]"
                        }`}
                      >
                        {amount}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3.5 border-t border-[#F1F5F9] pt-2.5 text-[11px] text-[#64748B]">
                  Prepared from the books. File on gst.gov.in and record the ARN here.
                </p>
                <p className="mt-2 text-[10px] text-[#94A3B8]">12m ago · 1,284 tokens</p>
              </div>
            </div>
          </div>

          {/* Composer */}
          <div className="border-t border-[#E2E8F0] bg-white px-5 py-3.5">
            <div className="flex items-center gap-2 rounded-lg border border-[#E2E8F0] px-3.5 py-2.5">
              <span className="flex-1 text-[12px] text-[#94A3B8]">
                Ask anything about your clients, compliance, GST, TDS...
              </span>
              <span className="grid h-6 w-6 place-items-center rounded-md bg-[#182350] text-white">
                <Sparkles size={12} />
              </span>
            </div>
            <p className="mt-2.5 flex items-start gap-1.5 text-[10.5px] leading-snug text-[#94A3B8]">
              <Shield size={11} className="mt-px shrink-0" />
              AI responses are advisory — always verify with source documents. Never
              auto-submit to government portals.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
