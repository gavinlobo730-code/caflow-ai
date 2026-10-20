/**
 * The line under the executive dashboard's Firm Health ring: which scores the figure is the mean of, and how old the oldest is.
 *
 * The ring is the mean of the stored scores that EXIST (`domain/practice/executive_dashboard.score_basis` computes the three facts),
 * so with one client of eight scored it is that one client's score, and a score is a fact about the day it was calculated. A figure
 * that said neither would show a reading as more than it is. Wording only: every number and the day come from the server.
 */
import { formatDate } from "../dates/format.ts";

export interface ScoreBasis {
  scored: number;
  clients: number;
  /** The Indian calendar day the oldest counted score was calculated on, `YYYY-MM-DD`; null when any counted score has no recorded time. */
  oldest_calculated_on: string | null;
  /** True when the stored scores could not be read at all: "none has been scored" would then be a false sentence. */
  unreadable?: boolean;
}

function clientsText(n: number): string {
  return `${n} client${n === 1 ? "" : "s"}`;
}

/** The sentence, or null where the payload gave no basis (a server one deploy behind), which says nothing rather than something false. */
export function scoreBasisLine(basis: ScoreBasis | null | undefined): string | null {
  if (!basis || !Number.isInteger(basis.scored) || !Number.isInteger(basis.clients)) return null;
  if (basis.unreadable === true) return "The stored scores could not be read just now.";
  if (basis.scored === 0) {
    return basis.clients === 0 ? "No clients yet." : `None of ${clientsText(basis.clients)} has been scored yet.`;
  }
  const mean = basis.scored === 1 ? "The score of 1 client" : `Mean of ${basis.scored} clients' stored scores`;
  const of = basis.scored === basis.clients ? "" : ` (${basis.scored} of ${clientsText(basis.clients)} scored)`;
  const age = basis.oldest_calculated_on ? `, the oldest calculated on ${formatDate(basis.oldest_calculated_on)}` : "";
  return `${mean}${of}${age}.`;
}
