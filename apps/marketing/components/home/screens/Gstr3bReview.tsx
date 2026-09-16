import { Shield } from "../../icons";

/**
 * The GSTR-3B Review workspace, recreated.
 *
 * Verbatim from apps/web/app/gst/gstr3b/page.tsx: the title, the statute line,
 * the CA-review banner, every table caption and column header, and the
 * §2(82)/§49(4) footnote under Table 3.1's total — which is the sentence that
 * makes this screen worth showing at all, because it is the thing competitors
 * get wrong.
 *
 * THE FIGURES ARE INVENTED AND THEY FOOT. Anyone who reads a GSTR-3B for a
 * living will add these up, so the §49(5) set-off below is worked properly
 * rather than decorated:
 *
 *   output       IGST 2,84,400   CGST 1,72,566   SGST 1,72,566
 *   4(C) credit  IGST 1,99,400   CGST 1,27,740   SGST 1,27,740
 *
 *   §49(5)(a)  IGST credit pays IGST: 1,99,400 → 85,000 IGST left, credit spent
 *   §49(5)(b)  CGST credit pays CGST: 1,27,740 → 44,826 CGST left, credit spent
 *   §49(5)(c)  SGST credit pays SGST: 1,27,740 → 44,826 SGST left, credit spent
 *              nothing is left to reach the residual IGST under Rule 88A
 *
 *   cash on output tax                       1,74,652
 *   reverse charge — always cash, §2(82)        37,800
 *   TOTAL PAYABLE IN CASH                     2,12,452
 *
 * The reverse-charge row being excluded from the output-tax total and added
 * back as cash is the whole point: §2(82) defines output tax as EXCLUDING tax
 * payable on reverse charge, so the credit ledger cannot pay it.
 */

const T31 = [
  {
    label: "(a) Taxable supplies (B2B + B2C + B2CL)",
    note: "Includes ₹2,36,000.00 of advances — GSTR-1 Table 11A less 11B, taxable on receipt under CGST s.13(2).",
    taxable: "42,18,600.00",
    igst: "2,84,400.00",
    cgst: "1,72,566.00",
    sgst: "1,72,566.00",
  },
  {
    label: "(b) Zero-rated supplies (Exports / SEZ)",
    note: "Under LUT — CGST s.16(3)(a). No tax charged.",
    taxable: "8,40,000.00",
    igst: null,
    cgst: null,
    sgst: null,
  },
  { label: "(c) Nil-rated / Exempt", taxable: "1,26,000.00", igst: null, cgst: null, sgst: null },
  {
    label: "(d) Inward supplies liable to reverse charge",
    taxable: "2,10,000.00",
    igst: null,
    cgst: "18,900.00",
    sgst: "18,900.00",
  },
  { label: "(e) Non-GST outward supplies", taxable: null, igst: null, cgst: null, sgst: null },
];

const T4 = [
  {
    label: "4(A) ITC available",
    sub: "All credit availed, including credit reversed below",
    igst: "2,11,800.00",
    cgst: "1,34,220.00",
    sgst: "1,34,220.00",
    strong: true,
  },
  {
    label: "4(B)(1) Reversed — permanent",
    sub: "Rules 38, 42 and 43, and Section 17(5) blocked credit",
    igst: null,
    cgst: "6,480.00",
    sgst: "6,480.00",
  },
  {
    label: "4(B)(2) Reversed — reclaimable later",
    sub: "Rule 37 / 37A and Section 16(2)(b), (c). Comes back through 4(A)(5)",
    igst: "12,400.00",
    cgst: null,
    sgst: null,
  },
  {
    label: "4(C) Net ITC available",
    sub: "4(A) less 4(B). This is what Table 6 may set off — never 4(A)",
    igst: "1,99,400.00",
    cgst: "1,27,740.00",
    sgst: "1,27,740.00",
    strong: true,
    total: true,
  },
];

function Money({ value, bold }: { value: string | null; bold?: boolean }) {
  if (!value) return <span className="text-[#94A3B8]">—</span>;
  return (
    <span className={`font-mono ${bold ? "font-semibold text-[#0F172A]" : "text-[#334155]"}`}>
      ₹{value}
    </span>
  );
}

export function Gstr3bReview() {
  return (
    <div className="min-w-[760px] space-y-5 bg-[#F8FAFC] p-6 text-[#0F172A]">
      <div>
        <h3 className="text-[19px] font-bold leading-tight text-[#0F172A]">GSTR-3B Review</h3>
        <p className="mt-0.5 text-[12.5px] text-[#64748B]">
          CGST Act Section 39 — Monthly summary return. Due 20th of following month.
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-[#FDE68A] bg-[#FFFBEB] p-3">
        <Shield size={15} className="mt-0.5 shrink-0 text-[#D97706]" />
        <p className="text-[12.5px] leading-relaxed text-[#92400E]">
          <span className="font-semibold">CA Review Required.</span> Verify all figures
          before downloading JSON for portal upload. Do not upload to gst.gov.in without CA
          approval.
        </p>
      </div>

      {/* Table 3.1 */}
      <div className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-5 py-3">
          <p className="text-[13px] font-semibold text-[#1E293B]">
            Table 3.1 — Outward Taxable Supplies
          </p>
          <p className="mt-0.5 text-[11px] text-[#64748B]">
            Net of credit notes. CGST Act Section 37.
          </p>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[10px] uppercase tracking-wide text-[#64748B]">
              <th className="px-5 py-2.5 font-semibold">Supply Type</th>
              <th className="px-3 py-2.5 text-right font-semibold">Taxable value</th>
              <th className="px-3 py-2.5 text-right font-semibold">IGST</th>
              <th className="px-3 py-2.5 text-right font-semibold">CGST</th>
              <th className="px-5 py-2.5 text-right font-semibold">SGST</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC] text-[12px]">
            {T31.map((r) => (
              <tr key={r.label}>
                <td className="px-5 py-2.5 text-[#334155]">
                  {r.label}
                  {r.note ? (
                    <span className="mt-0.5 block max-w-[46ch] text-[10px] leading-snug text-[#64748B]">
                      {r.note}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 text-right"><Money value={r.taxable} /></td>
                <td className="px-3 py-2.5 text-right"><Money value={r.igst} /></td>
                <td className="px-3 py-2.5 text-right"><Money value={r.cgst} /></td>
                <td className="px-5 py-2.5 text-right"><Money value={r.sgst} /></td>
              </tr>
            ))}
            <tr className="bg-[#EFF6FF] font-semibold">
              <td className="px-5 py-3 text-[#1E293B]">
                Total output tax — rows (a) and (b)
                <span className="mt-1 block max-w-[52ch] text-[10px] font-normal leading-snug text-[#64748B]">
                  Reverse charge (d) is excluded — s.2(82) puts it outside output tax, and
                  s.49(4) makes it cash. It is on the challan below.
                </span>
              </td>
              <td className="px-3 py-3 text-right"><span className="text-[#94A3B8]">—</span></td>
              <td className="px-3 py-3 text-right"><Money value="2,84,400.00" bold /></td>
              <td className="px-3 py-3 text-right"><Money value="1,72,566.00" bold /></td>
              <td className="px-5 py-3 text-right"><Money value="1,72,566.00" bold /></td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Table 4 */}
      <div className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-5 py-3">
          <p className="text-[13px] font-semibold text-[#1E293B]">Table 4 — Input Tax Credit</p>
          <p className="mt-0.5 max-w-[78ch] text-[11px] leading-snug text-[#64748B]">
            Notification 14/2022 with Circular 170/02/2022-GST. 4(A) is gross — the portal
            populates it from GSTR-2B — and the reversals are declared separately in 4(B).
          </p>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[10px] uppercase tracking-wide text-[#64748B]">
              <th className="px-5 py-2.5 font-semibold">Row</th>
              <th className="px-3 py-2.5 text-right font-semibold">IGST</th>
              <th className="px-3 py-2.5 text-right font-semibold">CGST</th>
              <th className="px-5 py-2.5 text-right font-semibold">SGST</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC] text-[12px]">
            {T4.map((r) => (
              <tr key={r.label} className={r.total ? "bg-[#EFF6FF]" : undefined}>
                <td className="px-5 py-2.5">
                  <span className={r.strong ? "font-semibold text-[#1E293B]" : "text-[#475569]"}>
                    {r.label}
                  </span>
                  <span className="mt-0.5 block max-w-[54ch] text-[10px] leading-snug text-[#64748B]">
                    {r.sub}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right"><Money value={r.igst} bold={r.strong} /></td>
                <td className="px-3 py-2.5 text-right"><Money value={r.cgst} bold={r.strong} /></td>
                <td className="px-5 py-2.5 text-right"><Money value={r.sgst} bold={r.strong} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Table 6 */}
      <div className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
        <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-5 py-3">
          <p className="text-[13px] font-semibold text-[#1E293B]">Table 6 — Net Tax Payable</p>
          <p className="mt-0.5 max-w-[80ch] text-[11px] leading-snug text-[#64748B]">
            Section 49(5) with Rule 88A, in order: IGST credit, then CGST, then SGST. Credit
            pays output tax only — reverse charge is always cash.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-px bg-[#F1F5F9] md:grid-cols-4">
          {[
            ["Output tax", "6,29,532.00", false],
            ["Credit set off — 4(C)", "4,54,880.00", false],
            ["After set-off", "1,74,652.00", false],
            ["Reverse charge — cash", "37,800.00", false],
          ].map(([label, value]) => (
            <div key={label as string} className="bg-white px-5 py-4">
              <p className="text-[10.5px] font-medium uppercase tracking-wide text-[#64748B]">
                {label as string}
              </p>
              <p className="mt-1.5 font-mono text-[15px] font-semibold text-[#0F172A]">
                ₹{value as string}
              </p>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between border-t border-[#E2E8F0] bg-[#0F172A] px-5 py-4">
          <span className="text-[12.5px] font-semibold text-white">Total payable in cash</span>
          <span className="font-mono text-[18px] font-bold text-white">₹2,12,452.00</span>
        </div>
      </div>
    </div>
  );
}
