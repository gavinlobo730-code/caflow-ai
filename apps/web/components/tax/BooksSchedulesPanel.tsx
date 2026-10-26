"use client";

/**
 * POST-A-070 — Part A of ITR-3, ITR-5 and ITR-6, laid out from the books: the balance sheet, the profit and loss account and the
 * depreciation schedules, with the tie-out that says nothing was dropped.
 *
 * WHAT IT IS AND IS NOT. It is a READ of `GET /api/itr/filings/{id}/books-schedules`: it computes nothing, saves nothing and produces no
 * file. Every figure, every box, every "not recorded" and every sentence is the server's (`domain/income_tax/books_schedules.py`). What
 * this screen adds is the order a CA works down the form in, and the three things it will not let a reader mistake:
 *
 *   * A TOTAL WHOSE PARTS THE BOOKS DO NOT HOLD is shown as a total, with the sentence saying why and the box the parts are keyed under.
 *     It is never shown as a figure to key into that box, because the form splits it and the books do not.
 *   * A FIGURE THE FORM'S NAMES DO NOT PLACE (ITR-5 and ITR-6 rename two columns of the depreciation schedule and swap their order) is
 *     shown beside the boxes it could be, with the number, and in none of them.
 *   * THE PLACEMENT TABLE IS NOT CONFIRMED against the form's instructions, and the sheet says so at the top, on the printed page too.
 *
 * IT PRINTS, like the keying sheet beside it: `data-print-scope` makes Print carry this and the client's name, not the filing screen
 * around it.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */

import { Fragment } from "react";
import type { ReactNode } from "react";
import { Callout, GapList } from "@/components/ui/callout";
import { formatPaiseBare, NO_FIGURE } from "@/lib/money/format";

export interface BooksBox {
  label: string;
  json_path: string;
  amount_paise: number | null;
  amount_rupees: number | null;
}

interface BooksPart extends BooksBox {
  state: "placed" | "not_recorded";
  source: string;
}

interface BooksLine { line: string; label: string; amount_paise: number }

interface BooksSlot extends BooksBox {
  key: string;
  /** "box": key this figure into `json_path`. "group_total": the form's total; its parts are keyed under `parts_under`. */
  role: "box" | "group_total";
  parts_under: string | null;
  lines: BooksLine[];
  parts: BooksPart[];
  not_split_paise: number;
  question: string;
  note: string;
  deduct: boolean;
  negative_notes?: string[];
}

interface BooksUnplaced { line: string; label: string; amount_paise: number; side: string; question: string }

interface BooksCheckBox extends BooksBox { kind: string }

interface BooksDepBox extends BooksBox { box: string; state: "placed" | "not_recorded" }

interface BooksDepRow {
  row_key: string;
  schedule: string;
  caption: string;
  block_key: string;
  allowance_paise: number;
  boxes: BooksDepBox[];
  to_key_by_hand: { boxes: string[]; label: string; reason: string; amount_paise: number | null; amount_rupees: number | null }[];
  /** Figures of the working that this row of the return has no box for: in no box of the return, so the CA is told. */
  figures_without_a_box: { label: string; amount_paise: number; amount_rupees: number; reason: string }[];
  notes: string[];
  not_recorded: string[];
}

interface BooksDepUnplaced {
  block_key: string;
  rate_percent: number | null;
  reason: string;
  allowance_paise: number;
  opening_wdv_paise: number;
  closing_wdv_paise: number;
}

export interface BooksSchedules {
  form: string;
  assessment_year: string;
  financial_year: string;
  mapping_confirmed: boolean;
  framework: string;
  status?: string | null;
  balance_sheet: {
    title: string;
    liability_side_label: string;
    asset_side_label: string;
    liability_slots: BooksSlot[];
    asset_slots: BooksSlot[];
    unplaced: BooksUnplaced[];
    checks: BooksCheckBox[];
    reconciliation: Record<string, number>;
  };
  profit_loss: {
    title: string;
    slots: BooksSlot[];
    unplaced: BooksUnplaced[];
    checks: BooksCheckBox[];
    reconciliation: Record<string, number>;
  };
  depreciation: null | {
    title: string;
    rows: BooksDepRow[];
    summary: BooksBox[];
    checks: BooksCheckBox[];
    unplaced: BooksDepUnplaced[];
    not_recorded: { box: string; reason: string }[];
    reconciliation: Record<string, number>;
    gaps: string[];
  };
  tie_out: {
    ok: boolean;
    difference_paise: number;
    lines_misplaced: number;
    /** `unit` says what the three numbers are: paise, or a COUNT of lines for the placed-once checks. */
    checks: {
      name: string; label: string; expected_paise: number; actual_paise: number; difference_paise: number;
      informational: boolean; unit: "paise" | "count";
    }[];
  };
  gaps: string[];
}

/** The form's own root segment dropped, so a path reads the way the utility's tree does. Display only. */
function shortPath(p: string): string {
  return p.replace(/^ITR\.ITR\d\./, "");
}

const TH = "px-3 py-2 text-3xs font-semibold text-ps-label uppercase";

type TieOutCheck = BooksSchedules["tie_out"]["checks"][number];

/** A check's number in its own unit: a count of lines is not paise, and one misplaced line must not read as a paisa. */
function inUnit(c: TieOutCheck, n: number): string {
  return c.unit === "count" ? `${n} ${n === 1 || n === -1 ? "line" : "lines"}` : formatPaiseBare(n);
}

function Rupees({ value }: { value: number | null | undefined }) {
  return <>{value === null || value === undefined ? NO_FIGURE : value.toLocaleString("en-IN")}</>;
}

function SlotRows({ slots }: { slots: BooksSlot[] }) {
  return (
    <>
      {slots.map(s => (
        <tr key={s.key} className="border-b border-ps-border align-top">
          <td className="px-3 py-2">
            <p className="text-ps-ink">{s.deduct ? `Less: ${s.label}` : s.label}</p>
            <p className="text-3xs text-ps-hint">
              {s.lines.map(l => `${l.label} ${formatPaiseBare(l.amount_paise)}`).join(" + ")}
            </p>
            {s.note && <p className="text-3xs text-ps-hint">{s.note}</p>}
            {s.negative_notes?.map(n => (
              <p key={n} className="text-3xs text-state-attention mt-0.5">{n}</p>
            ))}
          </td>
          <td className="px-3 py-2 text-right tabular-nums text-ps-ink whitespace-nowrap">{formatPaiseBare(s.amount_paise)}</td>
          <td className="px-3 py-2 text-right tabular-nums text-ps-ink whitespace-nowrap">
            <Rupees value={s.amount_rupees} />
          </td>
          <td className="px-3 py-2">
            {s.role === "box" ? (
              <p className="text-3xs text-ps-body">Key into <span className="font-mono">{shortPath(s.json_path)}</span></p>
            ) : (
              <>
                <p className="text-3xs text-ps-body">
                  The form&apos;s total <span className="font-mono">{shortPath(s.json_path)}</span>. Key its parts under{" "}
                  <span className="font-mono">{s.parts_under ? shortPath(s.parts_under) : NO_FIGURE}</span>.
                </p>
                {s.not_split_paise !== 0 && (
                  <p className="text-3xs text-state-attention mt-0.5">
                    {formatPaiseBare(s.not_split_paise)} is not split in the books. {s.question}
                  </p>
                )}
              </>
            )}
            {s.parts.map(p => (
              <p key={p.json_path} className="text-3xs text-ps-body mt-0.5">
                {p.label}:{" "}
                {p.state === "placed" ? (
                  <>
                    <span className="tabular-nums"><Rupees value={p.amount_rupees} /></span>{" "}
                    <span className="text-ps-hint">({p.source})</span>
                  </>
                ) : (
                  <span className="text-state-attention">not recorded — key by hand</span>
                )}
              </p>
            ))}
          </td>
        </tr>
      ))}
    </>
  );
}

function SlotTable({ title, slots }: { title: string; slots: BooksSlot[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-ps-border bg-ps-bg">
            <th className="px-3 py-2 text-left text-3xs font-semibold text-ps-label uppercase">{title}</th>
            <th className={`${TH} text-right`}>Books, ₹</th>
            <th className={`${TH} text-right`}>Whole ₹</th>
            <th className={`${TH} text-left`}>What to key</th>
          </tr>
        </thead>
        <tbody>
          <SlotRows slots={slots} />
        </tbody>
      </table>
    </div>
  );
}

function UnplacedTable({ lines, heading }: { lines: BooksUnplaced[]; heading: string }) {
  if (lines.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-ps-border bg-ps-bg">
            <th className="px-3 py-2 text-left text-3xs font-semibold text-ps-label uppercase">{heading}</th>
            <th className={`${TH} text-right`}>Books, ₹</th>
            <th className={`${TH} text-left`}>Why it is not placed</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(u => (
            <tr key={u.line} className="border-b border-ps-border align-top">
              <td className="px-3 py-2 text-ps-ink">{u.label}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ps-ink whitespace-nowrap">{formatPaiseBare(u.amount_paise)}</td>
              <td className="px-3 py-2 text-3xs text-ps-body">{u.question}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChecksList({ checks, lead }: { checks: BooksCheckBox[]; lead: string }) {
  if (checks.length === 0) return null;
  return (
    <p className="px-4 py-2 text-3xs text-ps-label">
      {lead}{" "}
      {checks.map((c, i) => (
        <Fragment key={c.json_path}>
          {i > 0 && "; "}
          {c.label} <span className="tabular-nums">{formatPaiseBare(c.amount_paise)}</span>
        </Fragment>
      ))}
      .
    </p>
  );
}

function SectionHead({ children }: { children: ReactNode }) {
  return <h3 className="px-4 py-2 text-xs font-semibold text-ps-ink bg-ps-bg border-y border-ps-border">{children}</h3>;
}

export function BooksSchedulesPanel({ sheet }: { sheet: BooksSchedules }) {
  const bs = sheet.balance_sheet;
  const pl = sheet.profit_loss;
  const dep = sheet.depreciation;
  const failing = sheet.tie_out.checks.filter(c => !c.informational && c.difference_paise !== 0);

  return (
    <div data-print-scope className="border border-ps-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-ps-border flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-ps-ink">
            Part A from the books — {sheet.form}, AY {sheet.assessment_year}
          </p>
          <p className="text-3xs text-ps-label mt-0.5">
            FY {sheet.financial_year} · the year-end statements, laid out as the return asks for them. Statements: {sheet.framework}.
          </p>
        </div>
        <button
          onClick={() => window.print()}
          className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-hover print:hidden flex-shrink-0"
        >
          Print
        </button>
      </div>

      <p className="px-4 py-2 text-3xs text-state-attention bg-state-attention-surface border-b border-state-attention-border">
        A keying aid, not a return. This software prepares; it does not file, and nothing here has been submitted.
        {!sheet.mapping_confirmed
          && " Which box each line of the books answers has NOT been read against the form's instructions — check each placement before relying on it."}
      </p>

      <div className="px-4 py-3 space-y-3">
        {failing.length > 0 ? (
          <Callout tone="problem" title="The books do not tie out to this layout.">
            <ul className="list-disc pl-4 space-y-1">
              {failing.map(c => (
                <li key={c.name}>{c.label}: expected {inUnit(c, c.expected_paise)}, found {inUnit(c, c.actual_paise)}.</li>
              ))}
            </ul>
          </Callout>
        ) : (
          <p className="text-3xs text-ps-label">
            Every line of the year-end statements is accounted for below, once. What is assembled adds to the statements&apos; totals, the
            balance sheet balances, the profit and loss account reaches the statements&apos; profit before tax
            {dep ? ", and the depreciation adds to the section 32 allowance" : ""} — to the paisa.
          </p>
        )}
        <GapList gaps={sheet.gaps} tone="attention" bulleted title="What this layout cannot settle" />
      </div>

      <SectionHead>{bs.title}</SectionHead>
      <SlotTable title={bs.liability_side_label} slots={bs.liability_slots} />
      <SlotTable title={bs.asset_side_label} slots={bs.asset_slots} />
      <UnplacedTable lines={bs.unplaced} heading="Lines the form has no box for" />
      <ChecksList checks={bs.checks} lead="The form computes these from the parts you key, each a whole-rupee box, so they agree with the books to within that rounding:" />

      <SectionHead>{pl.title}</SectionHead>
      <SlotTable title="Placed" slots={pl.slots} />
      <UnplacedTable lines={pl.unplaced} heading="Lines the form takes in detail the books do not hold" />
      <ChecksList checks={pl.checks} lead="The form computes these from the parts you key, each a whole-rupee box, so they agree with the books to within that rounding:" />

      {dep && (
        <>
          <SectionHead>{dep.title}</SectionHead>
          {dep.rows.length === 0 && (
            <p className="px-4 py-3 text-3xs text-ps-label">
              Nothing is placed on a row of the return yet. Record the row of each block on the Depreciation under §32 screen.
            </p>
          )}
          {dep.rows.map(r => (
            <div key={r.row_key} className="border-b border-ps-border">
              <p className="px-4 pt-3 text-xs font-medium text-ps-ink">
                {r.caption} <span className="text-3xs font-normal text-ps-hint">· block &ldquo;{r.block_key}&rdquo; · {r.schedule}</span>
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-2xs">
                  <tbody>
                    {r.boxes.map(b => (
                      <tr key={b.box} className="align-top">
                        <td className="px-4 py-1 text-ps-body">{b.label}</td>
                        <td className="px-3 py-1 text-right tabular-nums text-ps-ink whitespace-nowrap">
                          {b.state === "placed" ? <Rupees value={b.amount_rupees} /> : "not recorded"}
                        </td>
                        <td className="px-3 py-1 text-3xs font-mono text-ps-hint">{b.box}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {r.figures_without_a_box.map(f => (
                <p key={f.label} className="px-4 pb-2 text-3xs text-state-attention">
                  {f.label}: <span className="tabular-nums"><Rupees value={f.amount_rupees} /></span> — {f.reason}
                </p>
              ))}
              {r.notes.map(n => (
                <p key={n} className="px-4 pb-2 text-3xs text-state-attention">{n}</p>
              ))}
              {r.to_key_by_hand.map(h => (
                <p key={h.boxes.join("|")} className="px-4 pb-2 text-3xs text-state-attention">
                  {h.label}: <span className="tabular-nums"><Rupees value={h.amount_rupees} /></span> — not written into a box.{" "}
                  Could be {h.boxes.join(" or ")}. {h.reason}
                </p>
              ))}
            </div>
          ))}
          {dep.unplaced.length > 0 && (
            <div className="px-4 py-3 space-y-2 border-b border-ps-border">
              <p className="text-xs font-medium text-ps-ink">Blocks not on a row of the return</p>
              {dep.unplaced.map(u => (
                <p key={u.block_key} className="text-3xs text-state-attention">
                  <span className="font-medium">{u.block_key}</span>
                  {u.rate_percent !== null ? ` (${u.rate_percent}%)` : ""} — depreciation {formatPaiseBare(u.allowance_paise)}, closing value{" "}
                  {formatPaiseBare(u.closing_wdv_paise)}. {u.reason}
                </p>
              ))}
            </div>
          )}
          {dep.summary.length > 0 && (
            <ChecksList checks={dep.summary.map(s => ({ ...s, kind: "box" }))} lead="Schedule DEP, one box per row:" />
          )}
          <ChecksList checks={dep.checks} lead="The form computes these from the rows, each a whole-rupee box, so they agree with the allowance to within that rounding:" />
          <GapList gaps={dep.not_recorded.map(n => `${n.box}: ${n.reason}`)} tone="note" bulleted className="mx-4 mb-3"
                   title="Not recorded in the books, so left blank on every row" />
          {/* dep.gaps are part of sheet.gaps, listed once at the top; the row-level sentences sit beside the row they are about. */}
        </>
      )}

      <SectionHead>Tie-out</SectionHead>
      <div className="overflow-x-auto">
        <table className="w-full text-2xs">
          <tbody>
            {sheet.tie_out.checks.map(c => (
              <tr key={c.name} className="border-b border-ps-border">
                <td className="px-4 py-1.5 text-ps-body">{c.label}{c.informational ? " (reported, not a failure)" : ""}</td>
                <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                  {c.difference_paise === 0 ? "agrees" : `differs by ${inUnit(c, c.difference_paise)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
