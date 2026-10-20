/**
 * Challan 281's minor head, in words: who initiated the payment (POST-A-277). `create_challan` records 200 (tax the deductor pays over
 * of their own motion) or 400 (a deposit against a demand raised on regular assessment), and the challan lists show it so a payment
 * made against a demand is told apart from the rest. It replaced a Status column that printed the one value the server writes for every
 * challan.
 *
 * Whether a payment against a demand can ever settle tax that was deducted is a reading of the Act that this repository has not
 * confirmed (POST-C-210), so nothing here says what a 400 does to a figure; it only names the head.
 */
export const MINOR_HEAD_LABEL: Record<"200" | "400", string> = {
  "200": "200 — TDS payable by the deductor",
  "400": "400 — TDS regular assessment (against a demand)",
};

/** The words for a stored minor head. A value that is neither 200 nor 400 is shown as it is stored and an absent one as a dash: it is
 *  not turned into 200, because an unknown head read as the ordinary one is a deposit nobody has looked at. */
export function minorHeadLabel(minorHead: unknown): string {
  if (minorHead === "200" || minorHead === "400") return MINOR_HEAD_LABEL[minorHead];
  const stored = String(minorHead ?? "").trim();
  return stored || "—";
}
