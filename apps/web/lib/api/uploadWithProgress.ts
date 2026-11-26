// A multipart upload that can say how much of the file has left the browser (POST-A-158).
//
// `fetch` has no upload-progress callback, so a large bank statement or a scanned document on a slow
// connection showed a spinner and nothing else, and looked frozen. `XMLHttpRequest` reports it. This is the
// ONE place that uses it, and it hands back an ordinary `Response`, so every caller reads the answer, the
// refusal and the failure sentence exactly as it did with `fetch`.
//
// What it keeps from `fetch`'s path: NO retry (an upload that may have reached the server is never sent twice),
// no abort timer unless the caller passes `timeoutMs` (a screen's own upload passes the long bound; `lib/api`'s
// bulk imports pass none), and a browser failure becomes the same sentence `fetchPlain` gives. What it says and does not:
// progress is bytes SENT. When the last byte has left, the server still reads and checks the file, and the
// screen says so ("Processing…") and never "done".
import { plainFailure, type Doing } from "./failureSentence.ts";

export type UploadProgress = { loaded: number; total: number };

/** Whole percent sent, or null when the browser could not say how big the body is (never shown as 0). */
export function percentSent(p: UploadProgress): number | null {
  if (!Number.isFinite(p.total) || p.total <= 0) return null;
  return Math.max(0, Math.min(100, Math.floor((p.loaded / p.total) * 100)));
}

export function fetchUpload(
  url: string,
  init: { headers?: Record<string, string>; body: FormData; timeoutMs?: number },
  doing: Doing,
  onProgress?: (p: UploadProgress) => void,
): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    for (const [k, v] of Object.entries(init.headers ?? {})) xhr.setRequestHeader(k, v);
    xhr.responseType = "text";
    // A screen's own upload passes LONG_REQUEST_BOUND_MS, so an answer that never comes ends (POST-A-470); `lib/api`'s bulk imports pass none and stay unbounded.
    if (init.timeoutMs) xhr.timeout = init.timeoutMs;
    if (onProgress) {
      xhr.upload.onprogress = (e) => onProgress({ loaded: e.loaded, total: e.lengthComputable ? e.total : 0 });
    }
    xhr.onload = () => {
      const headers = new Headers();
      for (const line of xhr.getAllResponseHeaders().trim().split(/[\r\n]+/)) {
        const i = line.indexOf(":");
        if (i > 0) headers.append(line.slice(0, i).trim(), line.slice(i + 1).trim());
      }
      // A null-body status must not carry a body, or `new Response` throws.
      const noBody = xhr.status === 204 || xhr.status === 205 || xhr.status === 304;
      resolve(new Response(noBody ? null : xhr.responseText, { status: xhr.status, statusText: xhr.statusText, headers }));
    };
    // The same word `fetch` rejects with, so `plainFailure` reads it as the browser's own failure.
    xhr.onerror = () => reject(plainFailure(new TypeError("Failed to fetch"), doing));
    xhr.onabort = () => reject(plainFailure(new TypeError("Failed to fetch"), doing));
    // The same name `AbortSignal.timeout` rejects with, so the sentence is the timed-out one and a write says it is not known whether it went through.
    xhr.ontimeout = () => reject(plainFailure(new DOMException("The upload was given up on: the server did not answer in time.", "TimeoutError"), doing));
    xhr.send(init.body);
  });
}
