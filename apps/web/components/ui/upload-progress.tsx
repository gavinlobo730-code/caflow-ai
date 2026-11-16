"use client";

import * as React from "react";
import { percentSent, type UploadProgress as Sent } from "@/lib/api/uploadWithProgress";

/**
 * What an upload has done so far, in words (POST-A-158).
 *
 * `null` renders nothing. While bytes leave the browser it shows the share sent; when the browser could not
 * say how big the body is it says "Uploading…" and no number (an unknown is never drawn as 0%); once the last
 * byte has gone it says "Processing…", because the server still reads and checks the file and the screen must
 * not claim a finish the server has not given. The caller clears it when the answer comes.
 */
export function UploadProgress({ progress, what = "the file" }: { progress: Sent | null; what?: string }) {
  if (!progress) return null;
  const pct = percentSent(progress);
  const sentAll = pct !== null && pct >= 100;
  const text = sentAll
    ? `Sent ${what}. The server is reading it…`
    : pct === null ? `Uploading ${what}…` : `Uploading ${what}: ${pct}% sent`;
  return (
    <div role="status" aria-live="polite" className="space-y-1">
      <p className="text-xs text-ps-label">{text}</p>
      {pct !== null && !sentAll && (
        <div role="progressbar" aria-label={`Upload of ${what}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
          className="h-1.5 w-full overflow-hidden rounded bg-ps-muted">
          <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}
