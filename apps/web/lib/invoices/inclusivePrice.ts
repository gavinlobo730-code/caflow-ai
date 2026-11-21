/**
 * A PRICE INCLUDING GST, WORKED BACK BY THE SERVER (POST-A-490): what the browser's part is, and it is not arithmetic.
 *
 * A person raising a sales invoice often knows only the price INCLUDING GST. The server works the unit rate before tax out
 * of it (`POST /api/sales-invoices/inclusive-rate`, whose answer is the invoice's own arithmetic and says so when no rate
 * reaches the typed figure exactly). This module does the two things the browser must: it turns what was TYPED (the price,
 * and the line's quantity, GST rate and discount as they stand in the editor) into the question, refusing in words what is
 * not a figure, and it reads the answer's shape before a screen trusts it.
 *
 * NOTHING HERE MULTIPLIES, DIVIDES OR ROUNDS AN AMOUNT. The price is read by the one parser (`paiseFromRupeeInput`), the
 * quantity by `parseQuantity`, and the percentage boxes by `bpsFromPercentInput`; the rate that goes into the line's rate box
 * is the server's paise written out by `rupeeInputFromPaise`, which is formatting. Pure, so it is tested as plain code.
 */
import { bpsFromPercentInput, paiseFromRupeeInput, parseQuantity, rupeeInputFromPaise } from "../money/rupeeInput.ts";
import { gstRateBpsFromPercent } from "../money/gstLine.ts";

export type InclusiveBasis = "unit" | "line";

/** The line's own facts, as the editor holds them: strings as typed, the GST rate as the percentage chosen. */
export interface LineFacts {
  qty: string;
  gstRatePercent: number;
  discountPercent?: string | null;
  cessPercent?: string | null;
  cessPerUnit?: string | null;
}

export interface InclusiveQuestion {
  client_id: string;
  inclusive_paise: number;
  basis: InclusiveBasis;
  quantity: number;
  gst_rate_bps: number;
  discount_percent_bps: number | null;
  has_cess: boolean;
}

/** The server's answer, in paise, with its own sentence. */
export interface InclusiveAnswer {
  rate_paise: number;
  typed_total_paise: number;
  list_value_paise: number;
  list_tax_paise: number;
  list_total_paise: number;
  difference_paise: number;
  exact: boolean;
  discount_paise: number;
  taxable_paise: number;
  tax_paise: number;
  total_paise: number;
  sentence: string;
}

const filled = (raw: string | null | undefined): boolean => (raw ?? "").trim() !== "";

/**
 * The question to send, or the sentence saying why it cannot be asked yet. A box that is not a figure is refused here, in
 * the screen's words, so the server is not asked a question with a guess in it.
 */
export function inclusiveQuestion(
  clientId: string, typedPrice: string, basis: InclusiveBasis, line: LineFacts,
): { question: InclusiveQuestion } | { problem: string } {
  const price = filled(typedPrice) ? paiseFromRupeeInput(typedPrice) : null;
  if (price === null || price <= 0) return { problem: "Type the price including GST as an amount, with no commas, for example 11800 or 11800.50." };
  const quantity = parseQuantity(line.qty);
  if (quantity === null || quantity <= 0) return { problem: "Enter this line's quantity first." };
  let discount: number | null = null;
  if (filled(line.discountPercent)) {
    discount = bpsFromPercentInput(line.discountPercent ?? "");
    if (discount === null) return { problem: "This line's discount is not a percentage. Correct it first." };
  }
  // A cess box with anything in it other than nought means the line carries cess, which the server refuses in its own words.
  const cess = (raw: string | null | undefined) => filled(raw) && paiseFromRupeeInput(raw ?? "") !== 0;
  return {
    question: {
      client_id: clientId, inclusive_paise: price, basis, quantity,
      gst_rate_bps: gstRateBpsFromPercent(line.gstRatePercent),
      discount_percent_bps: discount,
      has_cess: cess(line.cessPercent) || cess(line.cessPerUnit),
    },
  };
}

const NUMBERS = ["rate_paise", "typed_total_paise", "list_value_paise", "list_tax_paise", "list_total_paise",
  "difference_paise", "discount_paise", "taxable_paise", "tax_paise", "total_paise"] as const;

/** The answer out of the server's envelope, or null when it is not the shape the route sends: every figure a whole number. */
export function inclusiveAnswer(res: unknown): InclusiveAnswer | null {
  const body = res && typeof res === "object" ? (res as { success?: unknown; data?: unknown }) : null;
  const data = body?.success === true && body.data && typeof body.data === "object" ? (body.data as Record<string, unknown>) : null;
  if (!data) return null;
  for (const key of NUMBERS) if (!Number.isSafeInteger(data[key])) return null;
  if (typeof data.exact !== "boolean" || typeof data.sentence !== "string" || data.sentence.trim() === "") return null;
  if ((data.rate_paise as number) <= 0) return null;
  return data as unknown as InclusiveAnswer;
}

/** What goes in the line's rate box for an accepted answer: the server's paise, written as rupees. */
export function rateBoxText(answer: InclusiveAnswer): string {
  return rupeeInputFromPaise(answer.rate_paise);
}
