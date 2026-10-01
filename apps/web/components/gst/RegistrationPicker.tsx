"use client";

/**
 * Which of the client's GST registrations a return is being prepared for
 * (GST-17).
 *
 * See `lib/gst/registrationChoice.ts` for the three rules of choosing and for
 * why this exists. In one line: the API has taken `gstin` on every compute call
 * since GST-20 and no screen sent one, so only the primary could be built from
 * the UI and the "New" forms asked a CA to type fifteen characters.
 *
 * THIS SCREEN DECIDES NOTHING. The list, its order (primary first), which
 * registrations file the ordinary pair and the caveat for each are the server's;
 * a refusal is `registrationChoice.resolveChoice`'s. And it does NOT FILTER the
 * documents — no invoice, bill or note records which registration it belongs
 * to — so the server's caveat is shown beside the choice, in words, rather than
 * left for the compute result to mention afterwards.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { arrayOrEmpty } from "@/lib/api/shape";
import { api, type ClientGstRegistration } from "@/lib/api";
import {
  caveatFor, defaultGstin, needsPicker, optionLabel, resolveChoice,
  type Choice,
} from "@/lib/gst/registrationChoice";

export interface RegistrationChoiceState {
  list: ClientGstRegistration[];
  loading: boolean;
  /** Why the list could not be read, or null. A failed read is NOT an empty
   *  list: "none" would invite the CA to prepare the primary believing it is
   *  the only registration. */
  failed: string | null;
  selected: string | null;
  setSelected: (gstin: string) => void;
  choice: Choice;
}

/** Read the client's registrations and hold the current choice. */
export function useRegistrationChoice(
  clientId: string | null | undefined,
): RegistrationChoiceState {
  const [list, setList] = useState<ClientGstRegistration[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [selected, setSelectedState] = useState<string | null>(null);

  useEffect(() => {
    // A different client is a different set of registrations. Nothing is
    // carried across: a GSTIN chosen for the last client is NOT one this client
    // holds, and `resolveChoice` would refuse it — clearing it is kinder.
    setList([]);
    setSelectedState(null);
    setFailed(null);
    if (!clientId) { setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    api.clientGstRegistrations.list(clientId)
      .then((res) => {
        if (cancelled) return;
        if (!res.success) throw new Error(res.error ?? "Couldn't read the registrations.");
        // `arrayOrEmpty` at the setter: `{success: true}` with no data is a
        // payload and not a list.
        const rows = arrayOrEmpty<ClientGstRegistration>(res.data);
        setList(rows);
        setSelectedState(defaultGstin(rows));
      })
      .catch((e) => {
        if (cancelled) return;
        setFailed(e instanceof Error && e.message ? e.message : "Couldn't read the registrations.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [clientId]);

  const setSelected = useCallback((gstin: string) => setSelectedState(gstin), []);
  const choice = useMemo(() => resolveChoice(list, selected), [list, selected]);
  return { list, loading, failed, selected, setSelected, choice };
}

export function RegistrationPicker({
  state, onChange, disabled, id = "gst-registration",
}: {
  state: RegistrationChoiceState;
  /** Called AFTER the choice changes, so a screen can discard a result that was
   *  built for the registration it just left. */
  onChange?: (gstin: string) => void;
  disabled?: boolean;
  id?: string;
}) {
  const { list, loading, failed, selected, choice } = state;

  if (loading) {
    return <p className="text-xs text-ps-hint">Reading this client&apos;s registrations…</p>;
  }
  if (failed) {
    return (
      <p className="text-xs text-state-attention" role="alert">
        Couldn&apos;t read this client&apos;s registrations ({failed}). Nothing
        will be sent, so the PRIMARY registration is the one that would be used.
      </p>
    );
  }
  if (list.length === 0) {
    return (
      <p className="text-xs text-ps-label">
        No GSTIN is recorded for this client, so there is no registration to
        prepare a return for.
      </p>
    );
  }

  const caveat = caveatFor(list, choice.gstin ?? selected);
  const several = needsPicker(list);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs text-ps-label">
        Registration (GSTIN)
      </label>
      {several ? (
        <select
          id={id}
          value={selected ?? ""}
          disabled={disabled}
          onChange={(e) => { state.setSelected(e.target.value); onChange?.(e.target.value); }}
          className="w-full border rounded px-3 py-1.5 text-sm bg-white"
        >
          {list.map((r) => (
            <option key={r.gstin} value={r.gstin} disabled={!r.files_gstr1_and_3b}>
              {optionLabel(r)}
            </option>
          ))}
        </select>
      ) : (
        <p id={id} className="text-sm font-mono">
          {choice.gstin ?? list[0]?.gstin}
          {list[0]?.is_primary ? <span className="text-ps-label font-sans"> — primary</span> : null}
        </p>
      )}
      {list.filter((r) => !r.files_gstr1_and_3b && r.other_return_form).map((r) => (
        <p key={r.gstin} className="text-2xs text-ps-label">
          {r.gstin}: {r.other_return_form}
        </p>
      ))}
      {choice.refused && (
        <p className="text-xs text-state-problem" role="alert">{choice.refused}</p>
      )}
      {/* The server's sentence, because choosing a registration does NOT split
          the documents between them. */}
      {caveat && (
        <p className="text-2xs text-state-attention">{caveat}</p>
      )}
    </div>
  );
}
