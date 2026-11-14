"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { readFilingChoices, type FilingChoices } from "./filingChoices";

/** What a new-filing form knows about the client's companies and open years (POST-A-291). */
export type ChoicesState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "read"; choices: FilingChoices }
  | { kind: "unreadable"; sentence: string };

/** The first half of the sentence when the choices could not be read; each form says what it then does, because they do different
 *  things (the client tab's save is checked by the server, the firm-level form's insert is not). */
export const CHOICES_UNREADABLE = "The client's companies and the years the calendar holds open could not be read.";

type Fetcher = (clientId: string, formType: string) => Promise<{ success?: boolean; data?: unknown; error?: string | null } | null | undefined>;

/**
 * Asks the server which companies and years a new filing for `clientId` and `formType` may name, again whenever either changes or `retry`
 * is pressed, and keeps only the newest answer: a client or a form changed while a request is in flight cannot have the earlier answer
 * shown against it. Nothing is asked until both are known. `whatNow` finishes the sentence said when the answer cannot be read.
 */
export function useFilingChoices(clientId: string, formType: string, fetcher: Fetcher, whatNow: string): { state: ChoicesState; retry: () => void } {
  const [state, setState] = useState<ChoicesState>({ kind: "idle" });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const whatNowRef = useRef(whatNow);
  whatNowRef.current = whatNow;
  useEffect(() => {
    const run = ++latest.current;
    if (!clientId || !formType) { setState({ kind: "idle" }); return; }
    setState({ kind: "loading" });
    const unreadable = (said?: string | null) => ({ kind: "unreadable" as const, sentence: `${said || CHOICES_UNREADABLE} ${whatNowRef.current}` });
    fetchRef.current(clientId, formType)
      .then((res) => {
        if (run !== latest.current) return;
        const choices = res?.success ? readFilingChoices(res.data) : null;
        setState(choices ? { kind: "read", choices } : unreadable(res?.success ? null : res?.error));
      })
      .catch(() => { if (run === latest.current) setState(unreadable()); });
  }, [clientId, formType, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
