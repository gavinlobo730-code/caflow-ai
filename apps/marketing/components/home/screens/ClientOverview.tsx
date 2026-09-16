import { Building, FileText, Landmark, Sparkles, Check, Calendar } from "../../icons";

/**
 * The client workspace Overview, recreated.
 *
 * Verbatim from apps/web/app/clients/[id]/overview/page.tsx and the client
 * workspace shell: the sidebar's 21 tab names in their real order, the three
 * stat labels ("Open Tasks", "Overdue Filings", "Filed This FY"), the header
 * chrome, the health badge, and the activity-feed row shapes.
 *
 * The three stats are plain integers on purpose — the real screen renders no
 * rupee figure anywhere, and inventing one here would misrepresent the screen
 * as well as the product.
 */

const NAV = [
  "Overview",
  "Accounting",
  "Sales",
  "Purchases",
  "Bank",
  "Inventory",
  "Compliance",
  "Payroll",
  "Fixed Assets",
  "Year End",
  "Tax",
  "Reports",
  "Documents",
  "Tasks",
  "Portal",
  "AI Insights",
  "Health",
];

type Tone = "success" | "info" | "warning";

const EVENTS: { tone: Tone; title: string; desc: string; when: string }[] = [
  {
    tone: "success",
    title: "Sales Invoice Created",
    desc: "INV/2026-27/0184 — Sundaram Auto Components Pvt Ltd",
    when: "2h ago",
  },
  {
    tone: "info",
    title: "Bank Statement Imported",
    desc: "146 transactions imported from HDFC Bank (3 duplicate(s) skipped)",
    when: "5h ago",
  },
  {
    tone: "warning",
    title: "Purchase Bill Created",
    desc: "Vendor Anantha Agro Foods LLP has no MSMED classification recorded",
    when: "1d ago",
  },
  {
    tone: "success",
    title: "Journal Posted",
    desc: "Draft JV/2026-27/0091 approved and posted to the ledger",
    when: "2d ago",
  },
  {
    tone: "info",
    title: "GSTR-9 Draft Saved",
    desc: "FY 2025-26 annual return draft saved for review",
    when: "3d ago",
  },
];

const TONE: Record<Tone, { dot: string; icon: React.ReactNode }> = {
  success: { dot: "bg-[#059669]", icon: <Check size={11} /> },
  info: { dot: "bg-[#3B82F6]", icon: <FileText size={11} /> },
  warning: { dot: "bg-[#D97706]", icon: <Landmark size={11} /> },
};

export function ClientOverview() {
  return (
    <div className="flex min-w-[760px] bg-[#F8FAFC] text-[#0F172A]">
      {/* Client nav */}
      <div className="hidden w-[200px] shrink-0 flex-col bg-[#182350] lg:flex">
        <div className="flex h-12 items-center border-b border-white/10 px-3">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            Client Workspace
          </span>
        </div>
        <div className="space-y-0.5 px-1.5 py-2">
          {NAV.map((n) => (
            <div
              key={n}
              className={`relative flex items-center gap-2.5 rounded-lg px-2 py-[7px] text-[12px] font-medium ${
                n === "Overview" ? "bg-blue-600 text-white" : "text-slate-400"
              }`}
            >
              {n === "Overview" ? (
                <span className="absolute -left-1.5 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-r bg-blue-400" />
              ) : null}
              <span className="h-[13px] w-[13px] shrink-0 rounded-sm bg-current opacity-30" />
              {n}
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0 flex-1">
        {/* Client header */}
        <div className="flex h-12 items-center gap-3 border-b border-[#E2E8F0] bg-white px-4">
          <Building size={15} className="text-[#94A3B8]" />
          <span className="truncate text-[13px] font-semibold text-[#182350]">
            Vaidehi Textiles Private Limited
          </span>
          <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] font-medium text-[#64748B]">
            Private Limited
          </span>
          <span className="hidden font-mono text-[10px] text-[#94A3B8] xl:inline">
            27AACCM9910C1ZN
          </span>
          <span className="ml-auto rounded-full bg-[#ECFDF5] px-2.5 py-1 text-[10px] font-semibold text-[#047857]">
            84 Healthy ↑
          </span>
        </div>

        <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_240px]">
          <div>
            {/* Stats */}
            <div className="grid grid-cols-3 gap-3">
              {[
                ["Open Tasks", "7", "bg-[#EFF6FF] text-[#1D4ED8]"],
                ["Overdue Filings", "2", "bg-[#FFFBEB] text-[#B45309]"],
                ["Filed This FY", "14", "bg-[#F8FAFC] text-[#334155]"],
              ].map(([label, value, tone]) => (
                <div
                  key={label}
                  className={`rounded-xl border border-[#E2E8F0] px-4 py-3 ${tone}`}
                >
                  <p className="text-[10.5px] font-medium uppercase tracking-wide opacity-70">
                    {label}
                  </p>
                  <p className="mt-1 text-[22px] font-bold leading-none">{value}</p>
                </div>
              ))}
            </div>

            {/* Pinned instruction */}
            <div className="mt-4 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3">
              <p className="text-[11.5px] font-semibold text-[#92400E]">
                Always reconcile HDFC 004 before month-end close
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-[#B45309]">
                Client emails the statement by the 3rd. Do not post the GST challan until the
                Cosmos Bank line clears.
              </p>
            </div>

            {/* Activity */}
            <div className="mt-4 overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
              <div className="flex items-center justify-between border-b border-[#F1F5F9] px-4 py-2.5">
                <span className="text-[12px] font-semibold text-[#1E293B]">Activity</span>
                <span className="text-[10.5px] text-[#94A3B8]">FY 2026-27</span>
              </div>
              <div className="divide-y divide-[#F8FAFC]">
                {EVENTS.map((e) => (
                  <div key={e.title + e.when} className="flex items-start gap-3 px-4 py-3">
                    <span
                      className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-white ${TONE[e.tone].dot}`}
                    >
                      {TONE[e.tone].icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12px] font-medium text-[#0F172A]">
                        {e.title}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-[#64748B]">
                        {e.desc}
                      </span>
                    </span>
                    <span className="shrink-0 text-[10.5px] text-[#94A3B8]">{e.when}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right rail */}
          <div className="hidden space-y-3 xl:block">
            <div className="rounded-xl border border-[#E2E8F0] bg-white p-4">
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-[#94A3B8]">
                Health Score
              </p>
              <p className="mt-1.5 text-[30px] font-bold leading-none text-[#047857]">84</p>
              <p className="mt-1 text-[11px] text-[#64748B]">Healthy, improving</p>
              <div className="mt-3 space-y-1.5">
                {[
                  ["Compliance", 92],
                  ["Accounting", 88],
                  ["Work Progress", 74],
                  ["Documents", 81],
                ].map(([k, v]) => (
                  <div key={k as string}>
                    <div className="flex justify-between text-[10px] text-[#64748B]">
                      <span>{k as string}</span>
                      <span className="tabular-nums">{v as number}</span>
                    </div>
                    <div className="mt-0.5 h-1 rounded-full bg-[#F1F5F9]">
                      <div
                        className="h-1 rounded-full bg-[#059669]"
                        style={{ width: `${v as number}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[#E2E8F0] bg-white p-4">
              <p className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-[#94A3B8]">
                <Calendar size={11} /> Upcoming
              </p>
              <div className="mt-2.5 space-y-2">
                {[
                  ["GSTR-1", "11 Oct"],
                  ["GSTR-3B", "20 Oct"],
                  ["TDS 26Q — Q2", "31 Oct"],
                  ["Advance tax", "15 Dec"],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between text-[11px]">
                    <span className="text-[#334155]">{k}</span>
                    <span className="text-[#94A3B8]">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[#E2E8F0] bg-white p-4">
              <p className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-[#94A3B8]">
                <Sparkles size={11} /> AI Risk Signals
              </p>
              <p className="mt-2 text-[11px] leading-relaxed text-[#64748B]">
                Bank reconciliation not done for 2 months on Cosmos Bank 004.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
