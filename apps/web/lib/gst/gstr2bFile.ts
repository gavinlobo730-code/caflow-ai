/**
 * Reading the GSTR-2B file a CA chose (gst-09).
 *
 * The screen used to ask for the period to be typed and the file to be pasted
 * into a textarea. The file says which month it is for and whose it is
 * (`data.rtnprd`, `data.gstin`), and what the server makes of those two facts is
 * the server's: `POST /api/gst-workspace/gstr2b/inspect` answers them and
 * `gstr2b/upload` acts on the same answer. So this module reads NEITHER field.
 *
 * It does the one job a browser has to do before it can send anything — turn
 * the file's text into an object — and refuses exactly what cannot be sent:
 * empty text, text that is not JSON, and JSON that is not an object (the API's
 * `raw_data` is one). It does not decide whether the object is a GSTR-2B; the
 * parser does, and says why in words the screen shows.
 *
 * A byte-order mark is stripped because a file saved by some Windows tools
 * carries one and `JSON.parse` rejects it with a message that says nothing
 * about a BOM — the CA sees "not valid JSON" over a file that is valid.
 *
 * Nothing here knows the portal's Excel download. Its layout could not be read
 * while this was written, and a parser written from memory of it would file
 * figures from a guessed column order.
 */

export type Gstr2bFileRead =
  | { ok: true; raw: Record<string, unknown> }
  | { ok: false; error: string };

export function readGstr2bText(text: string): Gstr2bFileRead {
  // 0xFEFF is the byte-order mark. Written as a code unit rather than typed, for
  // the reason scripts/one-csv-writer-and-it-escapes.test.ts gives: a literal
  // U+FEFF in source is invisible in every editor.
  const raw = String(text ?? "");
  const body = (raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw).trim();
  if (!body) return { ok: false, error: "That file is empty." };

  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return {
      ok: false,
      error:
        "That is not valid JSON. Choose the .json file the portal gives you for " +
        "GSTR-2B, not a screenshot, a PDF or an Excel copy of it.",
    };
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      ok: false,
      error:
        "That file is JSON but not a GSTR-2B download: its top level is not an " +
        "object.",
    };
  }
  return { ok: true, raw: parsed as Record<string, unknown> };
}
