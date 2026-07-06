"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";
import {
  orderHsnResults, hsnTypeBadge, hsnSecondaryLine, type HsnRow,
} from "@/lib/lookups/hsn";

/** A row from GET /api/hsn/search (master + firm history). */
export type HsnResult = HsnRow;

/** Auto-fill payload handed to the caller on selection (all CA-overridable). */
export interface HsnPick {
  hsn_code: string;
  gst_rate_bps?: number | null;
  description?: string | null;
  uqc?: string | null;
}

/** Lower-case, whitespace-collapsed, trimmed — a stable key for comparing two
 * free-text descriptions regardless of incidental spacing/casing. */
const normalizeDesc = (s: string | null | undefined): string =>
  (s ?? "").trim().replace(/\s+/g, " ").toLowerCase();

/**
 * Smart HSN/SAC lookup — debounced server search over the canonical master
 * merged with the firm's own history (GET /api/hsn/search). Search by code OR
 * description; on select the caller may auto-fill GST rate / description / unit.
 *
 * The controlled `value` is the HSN code string itself (free-text is always
 * allowed via the "Use …" row) so an unlisted/edge code never blocks invoicing.
 * CGST Rule 46(g): the suggested rate is a hint only — never auto-applied to any
 * tax/journal computation without the existing CA-review path.
 */
export function HsnLookup(props: {
  value: string;
  onChange: (code: string) => void;
  onPick?: (pick: HsnPick) => void;
  clientId?: string;
  type?: "goods" | "services";
  disabled?: boolean;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  className?: string;
  placeholder?: string;
  /**
   * Optional: the sibling line-item description. When provided, edits to it
   * (debounced ~300ms) trigger an automatic lookup via the same
   * GET /api/hsn/search used by manual search, and silently fill the code
   * when a HIGH-CONFIDENCE match exists — defined as the firm's own
   * previously-used code (`source: "history"`) for the EXACT same
   * description (normalized for case/whitespace only). A generic canonical-
   * master hit never auto-fills, and neither does a history hit whose stored
   * description merely CONTAINS the typed text as a substring (the backend
   * matches that way) — e.g. pausing mid-sentence on a shared prefix like
   * "Annual maintenance contract" must not silently borrow the HSN/rate from
   * an unrelated past line that happened to start the same way. Restores the
   * old description-driven HsnAutocomplete's productivity behavior on top of
   * the newer merged master+history search, without a second endpoint.
   *
   * Never overwrites a code already present (typed, manually picked, or from
   * an earlier auto-fill) — checked both when the debounce fires and again
   * after the request resolves, so a pick made while the request was in
   * flight is never clobbered. The result is applied exactly like a manual
   * pick (same onChange/onPick), so it stays fully editable afterwards.
   */
  description?: string;
}) {
  const { value, onChange, onPick, clientId, type, disabled, description, ...rest } = props;

  const fetchOptions = React.useCallback(
    async (q: string): Promise<HsnResult[]> => {
      const res = (await api.hsn.search(q, { client_id: clientId, type })) as ApiResp<HsnResult[]>;
      // Group history → Services (SAC) → Goods (HSN) while keeping the server's
      // within-group relevance order (one unified lookup, distinguished visually).
      return orderHsnResults(res.data ?? []);
    },
    [clientId, type],
  );

  // Recently-used codes for this client, shown before the CA types anything
  // (reuses the same endpoint with an empty query → firm history). Best-effort:
  // an empty/failed fetch simply shows the normal "type to search" hint.
  const [recent, setRecent] = React.useState<HsnResult[]>([]);
  React.useEffect(() => {
    if (!clientId) { setRecent([]); return; }
    let alive = true;
    (async () => {
      try {
        const res = (await api.hsn.search("", { client_id: clientId, type, limit: 8 })) as ApiResp<HsnResult[]>;
        if (alive) setRecent(orderHsnResults(res.data ?? []));
      } catch { /* best-effort recent list */ }
    })();
    return () => { alive = false; };
  }, [clientId, type]);

  // The value is a bare code; show it in the trigger via a synthetic option.
  const selected: HsnResult | null = value ? { hsn_code: value } : null;

  // Latest-value refs for the auto-suggest effect below: only an actual
  // `description` change should reset its debounce timer, so `value` /
  // `onChange` / `onPick` (new identities on every parent re-render, e.g.
  // typing in an unrelated field on the same invoice line) are read via refs
  // rather than being effect dependencies.
  const valueRef = React.useRef(value);
  const onChangeRef = React.useRef(onChange);
  const onPickRef = React.useRef(onPick);
  React.useEffect(() => { valueRef.current = value; }, [value]);
  React.useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  React.useEffect(() => { onPickRef.current = onPick; }, [onPick]);

  const seqRef = React.useRef(0);

  React.useEffect(() => {
    // Claim a new sequence number on EVERY effect run, before any early
    // return — otherwise a re-run that bails out early (description cleared/
    // shortened, or disabled toggled on) never invalidates an already-in-
    // flight lookup from the PRIOR run, and that stale response can still
    // land (this was a confirmed race: clear/shorten mid-request and the
    // earlier request's result still applies once it resolves).
    const seq = ++seqRef.current;
    if (!description || disabled) return;
    const q = description.trim();
    if (q.length < 2) return;

    const timer = setTimeout(async () => {
      if (seq !== seqRef.current) return; // a newer description edit superseded this lookup
      if (valueRef.current) return; // CA (or an earlier auto-fill) already set a code

      try {
        const res = (await api.hsn.search(q, { client_id: clientId, type, limit: 1 })) as ApiResp<HsnResult[]>;
        if (seq !== seqRef.current) return; // stale by the time the request resolved
        if (valueRef.current) return; // re-check: the CA may have filled it in while we waited

        const top = (res.data ?? [])[0];
        // High confidence = an EXACT (normalized) repeat of a description the
        // firm has billed before, not just a substring match — the backend's
        // history search matches whenever the typed text is a substring of a
        // stored description, so a shared prefix ("Annual maintenance
        // contract") could otherwise silently borrow an unrelated line's HSN
        // and GST rate. A non-exact history hit or any master-catalog hit is
        // still fully available via manual search in this same field.
        if (top && top.source === "history" && normalizeDesc(top.description) === normalizeDesc(q)) {
          onChangeRef.current(top.hsn_code);
          onPickRef.current?.({
            hsn_code: top.hsn_code,
            gst_rate_bps: top.gst_rate_bps,
            description: top.description,
            uqc: top.uqc,
          });
        }
      } catch {
        // Best-effort suggestion only — the CA can always search/type manually.
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [description, disabled, clientId, type]);

  return (
    <Combobox<HsnResult>
      value={selected}
      onChange={(v) => {
        const o = (Array.isArray(v) ? v[0] : v) ?? null;
        if (!o) {
          onChange("");
          return;
        }
        onChange(o.hsn_code);
        onPick?.({ hsn_code: o.hsn_code, gst_rate_bps: o.gst_rate_bps, description: o.description, uqc: o.uqc });
      }}
      fetchOptions={fetchOptions}
      recent={recent}
      getOptionId={(h) => h.hsn_code}
      getLabel={(h) => h.hsn_code}
      getSecondary={(h) => hsnSecondaryLine(h) || undefined}
      renderOption={(h) => {
        const badge = hsnTypeBadge(h);
        return (
          <span className="flex min-w-0 items-center gap-2">
            {badge && (
              <span
                className={`flex-shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold ${
                  badge === "SAC" ? "bg-violet-50 text-violet-700" : "bg-sky-50 text-sky-700"
                }`}
              >
                {badge}
              </span>
            )}
            <span className="min-w-0">
              <span className="block truncate text-xs text-[#1E293B]">{h.hsn_code}</span>
              <span className="block truncate text-[10px] text-[#94A3B8]">
                {h.reason ? `${h.reason} · ` : ""}{hsnSecondaryLine(h)}
              </span>
            </span>
          </span>
        );
      }}
      onCreate={(label) => onChange(label)}
      createLabel={(q) => `Use “${q}”`}
      minChars={2}
      placeholder={props.placeholder ?? "HSN/SAC"}
      searchPlaceholder="Search code or description…"
      emptyText="Type a code or description"
      disabled={disabled}
      {...rest}
    />
  );
}
