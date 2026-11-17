/**
 * A phone photograph that is over the extraction upload's limit is reduced to fit it, and ONLY then (POST-A-131).
 *
 * `POST /api/document-intelligence-v1/extract-invoice` refuses a file over 10 MB, and a modern phone's photograph of a bill can be 8 to 15 MB. The file
 * is also RETAINED as the evidence of the supplier's tax invoice (CGST Rule 36(1)), so an image that already fits is sent exactly as it was taken: nothing is
 * resized, recompressed or re-encoded unless the alternative is a refusal. When one is reduced, the screen says so, with both sizes, because the reduced copy
 * is what is kept.
 *
 * The limit is the SERVER's number repeated here so the reduction is attempted before the upload and not after a refusal; the server remains the authority
 * and still refuses what is too big.
 */
export const EXTRACT_UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024;
/**
 * The size a REDUCTION aims for, a little under the limit so a reduced copy is not left at its edge. It is not the test of whether to reduce: the
 * server caps the FILE's own bytes at the limit (`read_limited` in the extraction route) and the request as a whole has its own, larger cap, so a
 * photograph at or under the limit is accepted and must be sent as taken.
 */
const TARGET_BYTES = EXTRACT_UPLOAD_LIMIT_BYTES - 256 * 1024;
const STEPS: ReadonlyArray<{ edge: number; quality: number }> = [
  { edge: 3200, quality: 0.9 }, { edge: 2800, quality: 0.85 }, { edge: 2400, quality: 0.8 }, { edge: 2000, quality: 0.75 }, { edge: 1600, quality: 0.7 },
];

/** Does this file need reducing? Only a JPEG or PNG photograph over the limit does. */
export function needsReducing(file: { type: string; size: number }): boolean {
  return /^image\/(jpeg|png)$/i.test(file.type) && file.size > EXTRACT_UPLOAD_LIMIT_BYTES;
}

/** The size an image of `width` x `height` is drawn at so its longer edge is `edge` (never enlarged). */
export function scaledSize(width: number, height: number, edge: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (!(longest > 0) || longest <= edge) return { width, height };
  const k = edge / longest;
  return { width: Math.max(1, Math.round(width * k)), height: Math.max(1, Math.round(height * k)) };
}

export type FitResult =
  | { file: File; reduced: false }
  | { file: File; reduced: true; fromBytes: number; toBytes: number }
  | { file: File; reduced: false; couldNotReduce: true };

/** The photograph, reduced if it is over the limit. Any failure hands back the ORIGINAL file (the server then refuses it in words). Browser only. */
export async function fitForExtraction(file: File): Promise<FitResult> {
  if (!needsReducing(file)) return { file, reduced: false };
  try {
    const bitmap = await createImageBitmap(file);
    for (const step of STEPS) {
      const { width, height } = scaledSize(bitmap.width, bitmap.height, step.edge);
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) break;
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, width, height); // a PNG's transparency would otherwise go black as a JPEG
      ctx.drawImage(bitmap, 0, 0, width, height);
      const blob: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", step.quality));
      if (blob && blob.size <= TARGET_BYTES) {
        const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
        return { file: new File([blob], name, { type: "image/jpeg" }), reduced: true, fromBytes: file.size, toBytes: blob.size };
      }
    }
  } catch { /* an image the browser cannot decode is sent as it is */ }
  return { file, reduced: false, couldNotReduce: true };
}

/** The sentence the screen shows after a reduction. */
export function reducedSentence(fromBytes: number, toBytes: number): string {
  const mb = (n: number) => `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `The photograph was ${mb(fromBytes)}, over the 10 MB limit, so it was reduced to ${mb(toBytes)} before it was sent. The reduced copy is the one kept with the bill.`;
}
