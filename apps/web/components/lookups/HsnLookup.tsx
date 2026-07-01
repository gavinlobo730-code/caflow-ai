"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";
import { api, type ApiResp } from "@/lib/api";

/** A row from GET /api/hsn/search (master + firm history). */
export interface HsnResult {
  hsn_code: string;
  description?: string | null;
  gst_rate_bps?: number | null;
  uqc?: string | null;
  hsn_type?: string | null;
  source?: "history" | "master" | null;
  reason?: string | null;
}

/** Auto-fill payload handed to the caller on selection (all CA-overridable). */
export interface HsnPick {
  hsn_code: string;
  gst_rate_bps?: number | null;
  description?: string | null;
  uqc?: string | null;
}

const bpsToPct = (bps?: number | null) =>
  bps == null ? "" : `${(bps / 100).toFixed(bps % 100 === 0 ? 0 : 2)}% GST`;

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
}) {
  const { value, onChange, onPick, clientId, type, ...rest } = props;

  const fetchOptions = React.useCallback(
    async (q: string): Promise<HsnResult[]> => {
      const res = (await api.hsn.search(q, { client_id: clientId, type })) as ApiResp<HsnResult[]>;
      return res.data ?? [];
    },
    [clientId, type],
  );

  // The value is a bare code; show it in the trigger via a synthetic option.
  const selected: HsnResult | null = value ? { hsn_code: value } : null;

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
      getOptionId={(h) => h.hsn_code}
      getLabel={(h) => h.hsn_code}
      getSecondary={(h) =>
        [h.description, bpsToPct(h.gst_rate_bps), h.uqc].filter(Boolean).join(" · ") || undefined
      }
      onCreate={(label) => onChange(label)}
      createLabel={(q) => `Use “${q}”`}
      minChars={2}
      placeholder={props.placeholder ?? "HSN/SAC"}
      searchPlaceholder="Search code or description…"
      emptyText="Type a code or description"
      {...rest}
    />
  );
}
