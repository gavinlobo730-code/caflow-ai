"use client";

import { useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { formatDate, todayIstISO } from "@/lib/dates/format";

/**
 * WHOSE BOOKS THIS PAGE IS, ON PAPER (PRE-A-016).
 *
 * The client's name lives in `ClientTopBar`, and a printed page carries no top
 * bar (see the print paragraph on `ClientShell`), so a statement printed from a
 * client's workspace and carried to an auditor or a banker named nobody. This
 * is the one line that does, drawn ONLY when printing (`hidden print:block`),
 * so no screen changes.
 *
 * WHAT IT PRINTS is the client's name, its GSTIN when one is recorded, and the
 * day it was printed in INDIA (`todayIstISO`, not the browser's zone: a firm's
 * day is the Indian one). It prints nothing while the client is unresolved
 * (`client` is null until the lookup lands, so a statement never carries a
 * placeholder name or a blank "GSTIN" label) and never invents either field.
 *
 * THE DAY IS TAKEN WHEN THE PRINT STARTS, not when the page last rendered: a
 * tab left open overnight would otherwise print yesterday's date on a document
 * somebody dates by it. `beforeprint` fires before the browser lays the page
 * out, and `flushSync` makes the new text land inside that event rather than on
 * the next tick, which the layout would not wait for.
 *
 * `data-print-header` is what keeps it on the page when a screen prints ONE
 * region (`data-print-scope`, see globals.css): that rule hides everything
 * that is not the region or on the way to it, and this line is neither.
 */
export function PrintHeader() {
  const { client } = useClientNav();
  const [printedOn, setPrintedOn] = useState<string>(() => todayIstISO());

  useEffect(() => {
    function refresh() {
      flushSync(() => setPrintedOn(todayIstISO()));
    }
    window.addEventListener("beforeprint", refresh);
    return () => window.removeEventListener("beforeprint", refresh);
  }, []);

  if (!client) return null;
  return (
    <div data-print-header className="hidden print:block mx-6 mt-4 border-b border-ps-border pb-2 text-ps-ink">
      <p className="text-sm font-semibold">
        {client.client_name}
        {client.gstin ? <span className="font-normal"> · GSTIN {client.gstin}</span> : null}
      </p>
      <p className="text-xs text-ps-label">Printed {formatDate(printedOn)}</p>
    </div>
  );
}
