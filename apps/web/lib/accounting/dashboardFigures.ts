/**
 * The accounting dashboard's headline tiles, each in the state it can truthfully be in (POST-A-515 (d)).
 *
 * Revenue, expenses and net profit come from the profit and loss report; Cash & Bank comes from the cash-flow report. They are two
 * requests, and either can fail on its own (a reporting engine that is briefly unavailable, a refusal, a timeout). A request that
 * did not answer used to leave its figures at 0, and the tile printed ₹0: a statement about the books, made about a client whose
 * books were never read. The page already said so for a failure of the whole load ("a zero on an accounting dashboard is a claim
 * about the books, and this one would be false"); the two report calls had a `.catch` of their own that took the failure back out.
 *
 * `reportReading` is the one question asked of an answer: did the report say what the figure is? Anything else (no answer, an
 * answer that says it failed, an answer with no figure in it) is UNKNOWN, and an unknown is drawn as a dash with a sentence and is
 * never added up. A genuine zero (a client with nothing posted) is a reading and prints as ₹0.
 */
export type FigureReading = { kind: "known"; paise: number } | { kind: "unknown" };

export const UNKNOWN_FIGURE = "—";

/** The reading an answer gives for one figure. `pick` takes the figure out of the answer's data; it may return nothing. */
export function reportReading<T>(
  answer: { success?: boolean; data?: T } | null | undefined,
  pick: (data: T) => number | null | undefined,
): FigureReading {
  if (!answer || answer.success !== true || answer.data === undefined || answer.data === null) return { kind: "unknown" };
  let figure: number | null | undefined;
  try {
    figure = pick(answer.data);
  } catch {
    return { kind: "unknown" };
  }
  return typeof figure === "number" && Number.isFinite(figure) ? { kind: "known", paise: figure } : { kind: "unknown" };
}

/** Revenue less expenses, or unknown when either is: a profit worked out from half the books is not a profit. */
export function netReading(revenue: FigureReading, expenses: FigureReading): FigureReading {
  if (revenue.kind !== "known" || expenses.kind !== "known") return { kind: "unknown" };
  return { kind: "known", paise: revenue.paise - expenses.paise };
}

/** What a tile prints for a reading: the formatted figure, or a dash. */
export function figureText(reading: FigureReading, format: (paise: number) => string): string {
  return reading.kind === "known" ? format(reading.paise) : UNKNOWN_FIGURE;
}

/** The sentence to show above the tiles when a report did not answer, or null when both did. Names the report, not a code. */
export function unreadReportsSentence(profitAndLoss: FigureReading, cashFlow: FigureReading): string | null {
  const pl = profitAndLoss.kind !== "known";
  const cf = cashFlow.kind !== "known";
  if (pl && cf) {
    return "The profit and loss report and the cash-flow report did not answer, so revenue, expenses, profit and cash are not shown. They are not nil; reopen this tab to read them again.";
  }
  if (pl) {
    return "The profit and loss report did not answer, so revenue, expenses and profit are not shown. They are not nil; reopen this tab to read them again.";
  }
  if (cf) {
    return "The cash-flow report did not answer, so Cash & Bank is not shown. It is not nil; reopen this tab to read it again.";
  }
  return null;
}
