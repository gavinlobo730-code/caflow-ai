import { CheckCircle, ChevronLeft, Info } from "../../icons";
import { GSTR3B } from "./productWords";

/**
 * The GSTR-3B Review workspace, redrawn.
 *
 * Copied on 16-11-2026 from apps/web/app/gst/gstr3b/page.tsx: the back link,
 * the title and statute line, the CA-review banner, the status row of a return
 * that has been computed and not yet approved (a Draft chip and CA Approve),
 * and Tables 3.1, 4 and 6 with every caption, column header, row label and
 * note the page renders for figures like these. A figure is printed the way the
 * page's own `r()` prints it, so a nil the page prints as ₹0.00 is ₹0.00 here
 * and a cell the page dashes is dashed. The wording comes from `GSTR3B` in
 * `productWords.ts`, which a test holds to that page. Left out, because the drawing is the
 * return and not the form that asks for it: the client, period and registration
 * pickers, Table 3.2 (shown only when there is something to declare), and the
 * Rule 37, 37A and 43 panels beneath Table 6.
 *
 * WHAT CHANGED SINCE THE DRAWING OF 16-09-2026: 3.1(d) carries no taxable value
 * on this working (the reverse-charge tax is carried as cash, not as turnover);
 * the zero-rated row's note appears only on an export made on payment of tax,
 * so an export under an undertaking has none; 4(C) is the plain green total;
 * and Table 6 is now the four heads after set-off, the reverse charge payable
 * in cash, the challan figure, and how much credit was available, used and
 * carried forward.
 *
 * THE FIGURES ARE INVENTED AND THEY FOOT. Anyone who reads a GSTR-3B for a
 * living will add these up, so the set-off is worked rather than decorated
 * (CGST Act s.49(5) with Rule 88A, IGST credit first; no opening balance in the
 * credit ledger):
 *
 *   output       IGST 2,84,400   CGST 1,72,566   SGST 1,72,566
 *   4(C) credit  IGST 1,99,400   CGST 1,27,740   SGST 1,27,740
 *
 *   IGST credit pays IGST: 1,99,400 → 85,000 IGST left, credit spent
 *   CGST credit pays CGST: 1,27,740 → 44,826 CGST left, credit spent
 *   SGST credit pays SGST: 1,27,740 → 44,826 SGST left, credit spent
 *   nothing is left to reach the residual IGST
 *
 *   after set-off                            1,74,652
 *   reverse charge — always cash, s.2(82)       37,800
 *   TOTAL PAYABLE IN CASH                     2,12,452
 *   credit available 4,54,880 · set off 4,54,880 · carried forward 0
 *
 * The reverse-charge row being kept out of the output-tax total and added back
 * as cash is the point of the screen: s.2(82) defines output tax as EXCLUDING
 * tax payable on reverse charge, so the credit ledger cannot pay it.
 */

const DASH = <span className="text-[#64748B]">—</span>;

function Rs({ v, className }: { v: string; className: string }) {
  return <span className={`font-mono ${className}`}>₹{v}</span>;
}

function SectionHead({ title, note }: { title: string; note: string }) {
  return (
    <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-5 py-3">
      <p className="text-sm font-semibold text-[#0D1635]">{title}</p>
      <p className="mt-0.5 max-w-[80ch] text-xs text-[#475569]">{note}</p>
    </div>
  );
}

export function Gstr3bReview() {
  return (
    <div className="min-w-[760px] space-y-5 bg-[#F8FAFC] p-6 text-[#0D1635]">
      <div>
        <span className="mb-1 inline-flex items-center gap-1 text-xs text-[#64748B]">
          <ChevronLeft size={13} /> {GSTR3B.back}
        </span>
        <p className="text-xl font-semibold text-[#0D1635]">{GSTR3B.title}</p>
        <p className="mt-0.5 max-w-3xl text-sm text-[#475569]">
          {GSTR3B.subtitle}
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-[#FDE68A] bg-[#FFFBEB] p-3">
        <Info size={16} className="mt-0.5 shrink-0 text-[#D97706]" />
        <p className="text-sm text-[#92400E]">
          <strong>{GSTR3B.reviewLead}</strong> {GSTR3B.review}
        </p>
      </div>

      {/* Status row */}
      <div className="flex items-center justify-between">
        <span className="rounded-full bg-[#F1F5F9] px-2.5 py-1 text-xs font-semibold text-[#334155]">
          {GSTR3B.draft}
        </span>
        <span className="flex items-center gap-2 rounded-lg bg-[#182350] px-4 py-2 text-sm font-medium text-white">
          <CheckCircle size={16} />
          {GSTR3B.approve}
        </span>
      </div>

      {/* Table 3.1 */}
      <section className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <SectionHead
          title={GSTR3B.t31}
          note={GSTR3B.t31Note}
        />
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E2E8F0] text-xs uppercase text-[#475569]">
              {GSTR3B.t31Columns.map((c, i) => (
                <th key={c} className={`px-5 py-2.5 font-medium ${i === 0 ? "text-left" : "text-right"}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E2E8F0]">
            <tr>
              <td className="px-5 py-3 text-[#334155]">
                {GSTR3B.rowA}
                <span className="mt-0.5 block max-w-[52ch] text-[10px] text-[#475569]">
                  Includes ₹2,36,000.00 {GSTR3B.advances}
                </span>
              </td>
              <td className="px-5 py-3 text-right"><Rs v="42,18,600.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="2,84,400.00" className="text-[#0D1635]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,72,566.00" className="text-[#0D1635]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,72,566.00" className="text-[#0D1635]" /></td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-[#334155]">{GSTR3B.rowB}</td>
              <td className="px-5 py-3 text-right"><Rs v="8,40,000.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-[#334155]">{GSTR3B.rowC}</td>
              <td className="px-5 py-3 text-right"><Rs v="1,26,000.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-[#334155]">{GSTR3B.rowD}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right"><Rs v="0.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="18,900.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="18,900.00" className="text-[#334155]" /></td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-[#334155]">{GSTR3B.rowE}</td>
              <td className="px-5 py-3 text-right"><Rs v="0.00" className="text-[#334155]" /></td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
            </tr>
            <tr className="bg-[#EFF6FF] font-semibold">
              <td className="px-5 py-3 text-[#1E40AF]">
                {GSTR3B.total}
                <span className="mt-0.5 block max-w-[52ch] text-[10px] font-normal text-[#1D4ED8]">
                  {GSTR3B.totalNote}
                </span>
              </td>
              <td className="px-5 py-3 text-right font-mono">{DASH}</td>
              <td className="px-5 py-3 text-right"><Rs v="2,84,400.00" className="text-[#1E3A8A]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,72,566.00" className="text-[#1E3A8A]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,72,566.00" className="text-[#1E3A8A]" /></td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* Table 4 */}
      <section className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <SectionHead
          title={GSTR3B.t4}
          note={GSTR3B.t4Note}
        />
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E2E8F0] text-xs uppercase text-[#475569]">
              <th className="px-5 py-2.5 text-left font-medium">{GSTR3B.t4Row}</th>
              {GSTR3B.t31Columns.slice(2).map((c) => (
                <th key={c} className="px-5 py-2.5 text-right font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E2E8F0]">
            <tr>
              <td className="px-5 py-3 text-[#334155]">
                {GSTR3B.a4}
                <span className="block text-xs text-[#64748B]">{GSTR3B.a4Note}</span>
              </td>
              <td className="px-5 py-3 text-right"><Rs v="2,11,800.00" className="text-[#0D1635]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,34,220.00" className="text-[#0D1635]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,34,220.00" className="text-[#0D1635]" /></td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-xs text-[#475569]">
                {GSTR3B.b41}
                <span className="block text-[#64748B]">{GSTR3B.b41Note}</span>
              </td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="0.00" className="text-[#475569]" /></td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="6,480.00" className="text-[#475569]" /></td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="6,480.00" className="text-[#475569]" /></td>
            </tr>
            <tr>
              <td className="px-5 py-3 text-xs text-[#475569]">
                {GSTR3B.b42}
                <span className="block text-[#64748B]">{GSTR3B.b42Note}</span>
              </td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="12,400.00" className="text-[#475569]" /></td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="0.00" className="text-[#475569]" /></td>
              <td className="px-5 py-3 text-right text-xs"><Rs v="0.00" className="text-[#475569]" /></td>
            </tr>
            <tr className="bg-[#F0FDF4] font-semibold">
              <td className="px-5 py-3 text-[#166534]">{GSTR3B.c4}</td>
              <td className="px-5 py-3 text-right"><Rs v="1,99,400.00" className="text-[#14532D]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,27,740.00" className="text-[#14532D]" /></td>
              <td className="px-5 py-3 text-right"><Rs v="1,27,740.00" className="text-[#14532D]" /></td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* Table 6 */}
      <section className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <SectionHead
          title={GSTR3B.t6}
          note={GSTR3B.t6Note}
        />
        <div className="grid grid-cols-4 divide-x divide-[#E2E8F0] text-center">
          {[
            [GSTR3B.t31Columns[2], "85,000.00", "text-[#1D4ED8]"],
            [GSTR3B.t31Columns[3], "44,826.00", "text-[#2563EB]"],
            [GSTR3B.t31Columns[4], "44,826.00", "text-[#7E22CE]"],
            [GSTR3B.afterSetOff, "1,74,652.00", "font-bold text-[#0D1635]"],
          ].map(([label, value, tone]) => (
            <div key={label} className="px-4 py-5">
              <p className="mb-1 text-xs font-medium text-[#475569]">{label}</p>
              <p className={`font-mono text-lg font-semibold ${tone}`}>₹{value}</p>
            </div>
          ))}
        </div>
        <div className="divide-y divide-[#E2E8F0] border-t border-[#E2E8F0]">
          <div className="flex items-baseline justify-between px-5 py-3">
            <div>
              <p className="text-sm text-[#334155]">{GSTR3B.rcm}</p>
              <p className="mt-0.5 text-[10px] text-[#475569]">{GSTR3B.rcmNote}</p>
            </div>
            <p className="font-mono text-lg font-semibold text-[#7E22CE]">₹37,800.00</p>
          </div>
          <div className="flex items-baseline justify-between bg-[#FEF2F2] px-5 py-4">
            <div>
              <p className="text-sm font-semibold text-[#0D1635]">{GSTR3B.cash}</p>
              <p className="mt-0.5 text-[10px] text-[#475569]">{GSTR3B.cashNote}</p>
            </div>
            <p className="font-mono text-xl font-bold text-[#B91C1C]">₹2,12,452.00</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 border-t border-[#E2E8F0] bg-[#F8FAFC] px-5 py-3 text-center">
          {[
            [GSTR3B.available, "4,54,880.00"],
            [GSTR3B.setOff, "4,54,880.00"],
            [GSTR3B.carried, "0.00"],
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-[11px] text-[#64748B]">{label}</p>
              <p className="font-mono text-sm font-semibold">₹{value}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
