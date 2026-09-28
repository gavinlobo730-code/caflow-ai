/**
 * `compute_recommendations` (apps/api/services/intelligence_service.py)
 * stamps every recommendation with an internal routing code — `open_compliance`,
 * `open_client`, `open_invoices`, `open_journal_suggestions` — meant for the
 * SERVER's own routing, never for a CA to read on the card. This is the one
 * place that turns such a code into a human label and a destination, so
 * `/insights` never prints the raw code (misc-tools-11) and its arrow goes to
 * the screen the recommendation is actually about rather than always the
 * client's generic Overview tab (misc-tools-10).
 *
 * An action this map does not know shows NO label — never the raw code — and
 * its link falls back to Overview, which is where every recommendation
 * already goes for want of a code the map understands.
 */

export interface RecommendationAction {
  label: string;
  href: (clientId: string) => string;
}

export const RECOMMENDATION_ACTIONS: Record<string, RecommendationAction> = {
  open_compliance: {
    label: "Open compliance",
    href: (clientId) => `/clients/${clientId}/compliance`,
  },
  open_client: {
    label: "Open client",
    href: (clientId) => `/clients/${clientId}/overview`,
  },
  open_invoices: {
    label: "Open invoices",
    href: (clientId) => `/clients/${clientId}/sales?tab=invoices`,
  },
  open_journal_suggestions: {
    label: "Open journal suggestions",
    href: (clientId) => `/clients/${clientId}/accounting?tab=journal`,
  },
};

/** Where the recommendation's arrow should go: the mapped screen, or the
 *  client's Overview tab when the action is absent or not one this map knows. */
export function recommendationHref(action: string | null | undefined, clientId: string): string {
  const mapped = action ? RECOMMENDATION_ACTIONS[action] : undefined;
  return mapped ? mapped.href(clientId) : `/clients/${clientId}/overview`;
}

/** The human label to show under the recommendation, or null when there is
 *  none — never the raw action code. */
export function recommendationLabel(action: string | null | undefined): string | null {
  if (!action) return null;
  return RECOMMENDATION_ACTIONS[action]?.label ?? null;
}
