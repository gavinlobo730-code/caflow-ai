import {
  BookOpen,
  CheckCircle,
  ChevronsUpDown,
  Landmark,
  Search,
  Sparkles,
  Upload,
} from "../../icons";
import { ClientBar } from "./ClientBar";
import {
  BANK_TABS,
  CLIENT_MODULES,
  DATA_TABLE,
  DRAFT_REASONS,
  ENTRIES,
  HISTORY_REASONS,
  fill,
} from "./productWords";

/**
 * A client's Bank → Entries queue, redrawn.
 *
 * Copied on 16-11-2026 from apps/web/app/clients/[id]/bank/page.tsx (the four
 * tabs) and apps/web/components/banking/EntriesTab.tsx (the three filters with
 * their counts, the account picker, the toolbar, the working line under To do,
 * the columns, the state chips, the one action per row and the sentence under
 * the table), inside the client top bar (`ClientBar`). The table's own chrome
 * (the search box, Columns, the selection boxes, the sort marks, Actions) is
 * components/ui/data-table.tsx's. The wording comes from `productWords.ts`,
 * which a test holds to those files.
 *
 * THE ROWS ARE WHAT THE PRODUCT WOULD SHOW FOR THESE LINES. The narration column
 * is what domain/banking/narration.py makes of a statement line (the
 * counterparty, and a chip for the channel), and each invented line was put
 * through that parser to get it, including the one it reads oddly (a GST
 * payment's counterparty is the GSTIN printed on it). The Entry column is
 * EntriesTab's `entryText`, and the line under it is the reason
 * domain/banking/entry.py writes for each kind of proposal: one document that
 * fits exactly, two that do, a rule, the payee's history, a transfer between
 * two of the client's own accounts, and nothing at all, which asks instead.
 * Pass is green on a Ready line and navy on a proposal it may accept; a
 * proposal against a document is answered, never passed in one click. The
 * green is drawn one step darker than the product's (its `state.ready` ink,
 * #047857, where the product's buttons use #059669): white on #059669 is below
 * WCAG's 4.5:1, which a trial axe scan of the home page reported.
 *
 * THE DRAWING BEFORE THIS ONE (16-09-2026) had three tabs where the product now
 * has four, put a passed line in the To do list (which never holds one) and
 * showed raw narrations the product no longer shows. The lines, the ledgers,
 * the amounts and the names are invented; the GSTIN is well-formed. No real
 * client appears.
 */

type State = "ready" | "proposed" | "needs_you";

type Row = {
  date: string;
  party: string;
  channel?: string;
  entry: string;
  reason?: string;
  spent?: string;
  received?: string;
  state: State;
  /** Pass on a line that can be passed; Answer opens it when it cannot. */
  action: "pass-ready" | "pass-proposed" | "answer";
};

const [READY, PROPOSED, NEEDS_YOU] = ENTRIES.states;

const ROWS: Row[] = [
  {
    date: "02 Sep 2026",
    party: "SUNDARAM AUTO COMPONENTS PVT LTD",
    channel: "NEFT",
    entry: `${ENTRIES.receipt} · INV/2026-27/0184 · Sundaram Auto Components Pvt Ltd`,
    reason: DRAFT_REASONS.onlyDocument,
    received: "4,72,000.00",
    state: "ready",
    action: "pass-ready",
  },
  {
    date: "03 Sep 2026",
    party: "RELIANCE JIO",
    channel: "UPI",
    entry: `${ENTRIES.payment} · Telephone & Internet`,
    reason: fill(DRAFT_REASONS.rule, "Jio broadband"),
    spent: "2,360.00",
    state: "ready",
    action: "pass-ready",
  },
  {
    date: "04 Sep 2026",
    party: "MEGHDOOT INTERIORS PVT LTD",
    channel: "RTGS",
    entry: `${ENTRIES.receipt} · INV/2026-27/0171 · Meghdoot Interiors Pvt Ltd`,
    reason: fill(DRAFT_REASONS.severalDocuments, 2),
    received: "11,80,000.00",
    state: "proposed",
    action: "answer",
  },
  {
    date: "05 Sep 2026",
    party: "27AACCV4721K1Z6",
    channel: "NACH",
    entry: ENTRIES.askPayment,
    spent: "1,94,780.00",
    state: "needs_you",
    action: "answer",
  },
  {
    date: "06 Sep 2026",
    party: "SHARMA ENTERPRISES",
    channel: "NEFT",
    entry: `${ENTRIES.payment} · Purchases — Raw Material`,
    reason: fill(HISTORY_REASONS.most, 7, 9),
    spent: "88,500.00",
    state: "proposed",
    action: "pass-proposed",
  },
  {
    date: "08 Sep 2026",
    party: "COSMOS BANK 004",
    entry: `${ENTRIES.receipt} · from Cosmos Bank 004`,
    reason: DRAFT_REASONS.ownAccount,
    received: "50,000.00",
    state: "ready",
    action: "pass-ready",
  },
  {
    date: "09 Sep 2026",
    party: "SMS ALERT CHARGES",
    channel: "CHARGES",
    entry: `${ENTRIES.payment} · Bank Charges`,
    reason: fill(HISTORY_REASONS.every, 14),
    spent: "17.70",
    state: "ready",
    action: "pass-ready",
  },
];

const STATE_LABEL: Record<State, string> = {
  ready: READY,
  proposed: PROPOSED,
  needs_you: NEEDS_YOU,
};

const STATE_STYLE: Record<State, string> = {
  ready: "border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]",
  proposed: "border-[#BFDBFE] bg-[#DBEAFE] text-[#1D4ED8]",
  needs_you: "border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]",
};

/** EntriesTab's tones: a ready proposal is body ink; a question, or a proposal still to confirm, is amber. */
const ENTRY_TONE: Record<State, string> = {
  ready: "text-[#334155]",
  proposed: "text-[#B45309]",
  needs_you: "text-[#B45309]",
};

const BANK = CLIENT_MODULES.find((m) => m.id === "bank")?.label ?? "Bank";

function Action({ kind }: { kind: Row["action"] }) {
  if (kind === "answer") {
    return (
      <span className="rounded-md border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-1 text-[11px] font-medium text-[#B45309]">
        {ENTRIES.answer}
      </span>
    );
  }
  return (
    <span
      className={`rounded-md px-2.5 py-1 text-[11px] font-medium text-white ${
        kind === "pass-ready" ? "bg-[#047857]" : "bg-[#182350]"
      }`}
    >
      {ENTRIES.pass}
    </span>
  );
}

function Header({ label, sortable, right }: { label: string; sortable?: boolean; right?: boolean }) {
  return (
    <th className={`px-3 py-3 font-semibold ${right ? "text-right" : "text-left"}`}>
      <span className={`inline-flex items-center gap-1 ${right ? "flex-row-reverse" : ""}`}>
        {label}
        {sortable ? <ChevronsUpDown size={11} className="text-[#CBD5E1]" /> : null}
      </span>
    </th>
  );
}

const Box = () => <span className="block h-3 w-3 rounded-sm border border-[#94A3B8] bg-white" />;

export function BankQueue() {
  const [date, narration, entry, spent, received, status] = ENTRIES.headers;
  const counts = { toDo: "173", passed: "386", setAside: "4" };
  return (
    <div className="min-w-[760px] bg-white text-[#0D1635]">
      <ClientBar module={BANK} />

      {/* The four tabs */}
      <div className="px-6 pb-0 pt-5">
        <div className="flex w-fit gap-0.5 rounded-lg bg-[#F8FAFC] p-1">
          {BANK_TABS.tabs.map((t, i) => (
            <span
              key={t}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium ${
                i === 0 ? "bg-white text-[#0D1635] shadow-sm" : "text-[#475569]"
              }`}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-3 px-6 pb-6 pt-4">
        {/* The three filters, the account picker, setup on the right, and the one primary action */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-lg bg-[#F8FAFC] p-1">
            {ENTRIES.filters.map((label, i) => (
              <span
                key={label}
                className={`whitespace-nowrap rounded-md px-2.5 py-1 text-xs ${
                  i === 0 ? "bg-white font-medium text-[#0D1635] shadow-sm" : "text-[#475569]"
                }`}
              >
                {label}
                <span className={`ml-1 tabular-nums ${i === 0 ? "text-[#334155]" : "text-[#64748B]"}`}>
                  {[counts.toDo, counts.passed, counts.setAside][i]}
                </span>
              </span>
            ))}
          </div>
          <span className="rounded-lg border border-[#E2E8F0] bg-white px-2 py-1.5 text-xs text-[#334155]">
            {ENTRIES.allAccounts} ▾
          </span>

          <span className="ml-auto flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs text-[#475569]">
              <Landmark size={12} /> {ENTRIES.accounts}
            </span>
            <span className="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs text-[#475569]">
              <BookOpen size={12} /> {ENTRIES.bankBook}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-xs text-[#475569]">
              <Upload size={12} /> {ENTRIES.importStatement}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-xs text-[#475569]">
              <Sparkles size={12} /> {ENTRIES.propose}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-[#047857] px-3 py-1.5 text-xs font-medium text-white">
              <CheckCircle size={13} /> {fill(ENTRIES.passReady, 128)}
            </span>
          </span>
        </div>

        {/* The working states under To do, as one line */}
        <p className="text-xs text-[#475569]">
          <span className="font-medium tabular-nums text-[#0D1635]">{fill(ENTRIES.toDo, counts.toDo)}</span>
          <span className="text-[#64748B]"> — </span>
          <span className="tabular-nums underline decoration-dotted underline-offset-2">
            {fill(ENTRIES.ready, 128)}
          </span>
          <span className="text-[#64748B]"> · </span>
          <span className="tabular-nums underline decoration-dotted underline-offset-2">
            {fill(ENTRIES.proposed, 12)}
          </span>
          <span className="text-[#64748B]"> · </span>
          <span className="tabular-nums underline decoration-dotted underline-offset-2">33 need you</span>
        </p>

        {/* The table's own toolbar */}
        <div className="flex items-center gap-2">
          <span className="relative flex min-w-[14rem] flex-1 items-center rounded-lg border border-[#E2E8F0] bg-white py-1.5 pl-8 pr-7 text-xs text-[#64748B]">
            <Search size={13} className="absolute left-2.5 text-[#64748B]" />
            {ENTRIES.search}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-xs text-[#475569]">
            {DATA_TABLE.columns}
          </span>
        </div>

        <div className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
          <table className="w-full text-xs">
            <thead className="bg-[#F8FAFC]">
              <tr className="border-b border-[#E2E8F0] text-[#64748B]">
                <th className="w-8 px-3 py-3">
                  <Box />
                </th>
                <Header label={date} sortable />
                <Header label={narration} sortable />
                <Header label={entry} />
                <Header label={spent} sortable right />
                <Header label={received} sortable right />
                <Header label={status} sortable />
                <th className="px-3 py-3 text-right font-semibold">{DATA_TABLE.actions}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {ROWS.map((r) => (
                <tr key={r.party + r.date} className={r.state === "ready" ? "bg-[#ECFDF5]" : undefined}>
                  <td className="px-3 py-2">
                    <Box />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-[#475569]">{r.date}</td>
                  <td className="max-w-[150px] px-3 py-2">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-[#0D1635]">{r.party}</span>
                      {r.channel ? (
                        <span className="shrink-0 rounded bg-[#F1F5F9] px-1 py-0.5 text-[10px] text-[#475569]">
                          {r.channel}
                        </span>
                      ) : null}
                    </span>
                  </td>
                  <td className="max-w-[190px] px-3 py-2">
                    <span className={`block truncate text-xs ${ENTRY_TONE[r.state]}`}>{r.entry}</span>
                    {r.reason ? (
                      <span className="block truncate text-[10px] text-[#64748B]">{r.reason}</span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-[#9F1239]">
                    {r.spent ? `₹${r.spent}` : ""}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-[#15803D]">
                    {r.received ? `₹${r.received}` : ""}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] ${STATE_STYLE[r.state]}`}
                    >
                      {STATE_LABEL[r.state]}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <Action kind={r.action} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-center text-[10px] text-[#64748B]">{ENTRIES.footer}</p>
      </div>
    </div>
  );
}
