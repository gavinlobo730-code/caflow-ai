import { Landmark, BookOpen, Sparkles, Check, ArrowRight } from "../../icons";

/**
 * The client workspace's Bank → Entries queue, recreated.
 *
 * Every string here is verbatim from apps/web/app/clients/[id]/bank/page.tsx and
 * apps/web/components/banking/* — the tab names, the state chips, the column
 * headers, the status words, the working-state line, the footer caption. The
 * palette is the product's own literals (#0F172A, #64748B, #94A3B8, #E2E8F0,
 * #F8FAFC, and the green #059669 the one primary action uses).
 *
 * It is a recreation rather than a screenshot because §7 of the brief wants the
 * UI itself to be the focus: this is real text at the reader's own pixel ratio,
 * about 3 KB instead of 200, translatable, selectable, and it cannot silently
 * go stale into a claim about a screen that no longer looks like this — a
 * screenshot can.
 *
 * The rows are invented, and invented carefully: Indian bank narration formats
 * (NEFT/RTGS/UPI/ACH/CHRG), a real GSTIN shape, and the four states the queue
 * actually distinguishes. No real customer appears anywhere.
 */

type Row = {
  date: string;
  narration: string;
  entry: string;
  reason?: string;
  spent?: string;
  received?: string;
  status: "Ready" | "Passed · rule" | "Needs you" | "Proposed";
  action: string;
};

const ROWS: Row[] = [
  {
    date: "02 Sep",
    narration: "NEFT-HDFC0000240-SUNDARAM AUTO COMPONENTS PVT LTD-N240925",
    entry: "Receipt · Sundaram Auto Components",
    reason: "Matched an open invoice for the exact amount",
    received: "4,72,000.00",
    status: "Ready",
    action: "Pass",
  },
  {
    date: "03 Sep",
    narration: "UPI/DR/526104738201/RELIANCE JIO/YESB/jio@ybl",
    entry: "Payment · Telephone & Internet",
    reason: "Trusted rule — NEFT/UPI to RELIANCE JIO",
    spent: "2,360.00",
    status: "Passed · rule",
    action: "Undo",
  },
  {
    date: "04 Sep",
    narration: "RTGS-KKBKR52026090400234-VAIDEHI TEXTILES PVT LTD",
    entry: "Receipt · Vaidehi Textiles Private Limited",
    reason: "Matched two open invoices, ₹11,80,000 together",
    received: "11,80,000.00",
    status: "Ready",
    action: "Pass",
  },
  {
    date: "05 Sep",
    narration: "ACH-D-GST PMT-27AACCM9910C1ZN-0920",
    entry: "Payment · needs a ledger",
    reason: "A GST challan — which period is this for?",
    spent: "1,94,780.00",
    status: "Needs you",
    action: "Answer",
  },
  {
    date: "06 Sep",
    narration: "NEFT SHARMA ENTERPRISES-SBIN0001234-N652026090600891",
    entry: "Payment · Sharma Enterprises",
    reason: "Supplier matched by name; no open bill for this amount",
    spent: "88,500.00",
    status: "Proposed",
    action: "Answer",
  },
  {
    date: "08 Sep",
    narration: "BY CASH DEPOSIT-COSMOS BANK-BRANCH 004",
    entry: "Contra · Cash in hand",
    reason: "Between two of this client's own accounts",
    received: "50,000.00",
    status: "Ready",
    action: "Pass",
  },
];

const STATUS_STYLE: Record<Row["status"], string> = {
  Ready: "bg-[#ECFDF5] text-[#047857]",
  "Passed · rule": "bg-[#EEF2FF] text-[#4338CA]",
  "Needs you": "bg-[#FEF3C7] text-[#92400E]",
  Proposed: "bg-[#F1F5F9] text-[#475569]",
};

export function BankQueue() {
  return (
    <div className="min-w-[760px] bg-white text-[#0F172A]">
      {/* Client header strip */}
      <div className="flex h-12 items-center gap-3 border-b border-[#E2E8F0] px-4">
        <span className="grid h-[15px] w-[15px] place-items-center text-[#94A3B8]">
          <Landmark size={15} />
        </span>
        <span className="text-[13px] font-semibold text-[#182350]">
          Vaidehi Textiles Private Limited
        </span>
        <span className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] font-medium text-[#64748B]">
          Private Limited
        </span>
        <span className="hidden font-mono text-[10px] text-[#94A3B8] lg:inline">
          27AACCM9910C1ZN
        </span>
        <span className="ml-auto rounded-full bg-[#ECFDF5] px-2 py-0.5 text-[10px] font-semibold text-[#047857]">
          84 Healthy
        </span>
      </div>

      {/* Tab strip */}
      <div className="px-6 pb-0 pt-5">
        <div className="flex w-fit gap-0.5 rounded-lg bg-[#F8FAFC] p-1">
          {["Entries", "Reconcile", "Rules"].map((t) => (
            <span
              key={t}
              className={`rounded-md px-3 py-1.5 text-xs font-medium ${
                t === "Entries"
                  ? "bg-white text-[#0F172A] shadow-sm"
                  : "text-[#64748B]"
              }`}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-3 px-6 pb-6 pt-4">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-0.5 rounded-lg bg-[#F8FAFC] p-1">
            {[
              ["To do", "173", true],
              ["Passed", "128", false],
              ["Set aside", "4", false],
            ].map(([label, count, on]) => (
              <span
                key={label as string}
                className={`rounded-md px-2.5 py-1 text-xs ${
                  on ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B]"
                }`}
              >
                {label as string}{" "}
                <span className="tabular-nums opacity-70">{count as string}</span>
              </span>
            ))}
          </div>

          <span className="ml-auto hidden items-center gap-2 md:flex">
            <span className="inline-flex items-center gap-1.5 text-xs text-[#64748B]">
              <Landmark size={12} /> Accounts
            </span>
            <span className="inline-flex items-center gap-1.5 text-xs text-[#64748B]">
              <BookOpen size={12} /> Bank Book
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-xs text-[#475569]">
              Import statement
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-xs text-[#475569]">
              <Sparkles size={12} /> Propose
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-[#059669] px-3 py-1.5 text-xs font-medium text-white">
              <Check size={13} /> Pass 128 ready
            </span>
          </span>
        </div>

        {/* Working state */}
        <p className="text-xs text-[#334155]">
          <span className="font-bold text-[#0F172A]">173 to do</span>
          <span className="px-1.5 text-[#94A3B8]">—</span>
          <span className="underline decoration-dotted underline-offset-2">128 ready</span>
          <span className="px-1 text-[#94A3B8]">·</span>
          <span className="underline decoration-dotted underline-offset-2">12 proposed</span>
          <span className="px-1 text-[#94A3B8]">·</span>
          <span className="underline decoration-dotted underline-offset-2">33 need you</span>
        </p>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-[#E2E8F0]">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-[#F8FAFC] text-[10px] uppercase tracking-wide text-[#94A3B8]">
                <th className="px-4 py-2.5 font-semibold">Date</th>
                <th className="px-3 py-2.5 font-semibold">Bank narration</th>
                <th className="px-3 py-2.5 font-semibold">Entry</th>
                <th className="px-3 py-2.5 text-right font-semibold">Spent</th>
                <th className="px-3 py-2.5 text-right font-semibold">Received</th>
                <th className="px-3 py-2.5 font-semibold">Status</th>
                <th className="px-4 py-2.5 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F1F5F9]">
              {ROWS.map((r) => (
                <tr key={r.narration} className="align-top">
                  <td className="whitespace-nowrap px-4 py-3 text-[11.5px] text-[#64748B]">
                    {r.date}
                  </td>
                  <td className="max-w-[230px] px-3 py-3">
                    <span className="block truncate font-mono text-[11px] text-[#334155]">
                      {r.narration}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="block text-[12px] font-medium text-[#0F172A]">
                      {r.entry}
                    </span>
                    {r.reason ? (
                      <span className="mt-0.5 block text-[10.5px] leading-snug text-[#94A3B8]">
                        {r.reason}
                      </span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[11.5px] text-[#334155]">
                    {r.spent ? `₹${r.spent}` : <span className="text-[#94A3B8]">—</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[11.5px] font-semibold text-[#047857]">
                    {r.received ? `₹${r.received}` : <span className="font-normal text-[#94A3B8]">—</span>}
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLE[r.status]}`}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className="inline-flex items-center gap-1 rounded-md border border-[#E2E8F0] px-2 py-1 text-[10.5px] text-[#475569]">
                      {r.action}
                      {r.action === "Pass" ? <ArrowRight size={10} /> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-center text-[10px] text-[#94A3B8]">
          A line is a Receipt, a Payment or a Contra — the bank decides which. Click a line
          to answer it; Pass puts it in the books; Undo takes it back out.
        </p>
      </div>
    </div>
  );
}
