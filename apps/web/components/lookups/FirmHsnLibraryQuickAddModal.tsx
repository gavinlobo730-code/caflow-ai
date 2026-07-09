"use client";

/**
 * Firm HSN/SAC Library — quick-add modal (HSN/SAC architecture redesign,
 * Decision C).
 *
 * "Master data must never be created directly within the transaction." When
 * a CA can't find the code they need while filling in an invoice line (or a
 * Product/Service), this is what opens instead of letting them free-type an
 * arbitrary code onto the transaction: it adds the code to the FIRM'S OWN
 * library (POST /api/firm-hsn-library/), then hands the new code back to the
 * caller exactly like a normal pick — the transaction still only ever
 * consumes codes that exist in the library, it just never has to leave the
 * page to do it.
 *
 * Caflow does not validate or suggest the classification here — only the
 * shape (digits, non-blank description). The CA is asserting this code into
 * their own library; Caflow neither owns nor confirms that judgement.
 */
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { api, type ApiResp } from "@/lib/api";
import { GST_RATES } from "@/lib/invoices/shared";

export interface FirmHsnLibraryRow {
  id: string;
  hsn_code: string;
  description: string;
  hsn_type: "goods" | "services";
  gst_rate_pct: number | null;
  uqc: string | null;
  is_active?: boolean;
  duplicate?: boolean;
}

const inputCls =
  "w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

export function FirmHsnLibraryQuickAddModal({
  seedCode,
  seedDescription,
  defaultType,
  onClose,
  onAdded,
}: {
  /** Prefilled if the CA's typed search looked like a code (digits only). */
  seedCode?: string;
  /** Prefilled if the CA's typed search looked like free text. */
  seedDescription?: string;
  defaultType?: "goods" | "services";
  onClose: () => void;
  onAdded: (row: FirmHsnLibraryRow) => void;
}) {
  const [hsnCode, setHsnCode] = useState(seedCode ?? "");
  const [description, setDescription] = useState(seedDescription ?? "");
  const [hsnType, setHsnType] = useState<"goods" | "services">(defaultType ?? "services");
  const [gstRate, setGstRate] = useState<number | "">(18);
  const [uqc, setUqc] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const codeValid = /^\d{2,8}$/.test(hsnCode.trim());
  const descValid = description.trim().length > 0;
  const canSave = codeValid && descValid && !saving;

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const res = (await api.firmHsnLibrary.add({
        hsn_code: hsnCode.trim(),
        description: description.trim(),
        hsn_type: hsnType,
        gst_rate_pct: gstRate === "" ? null : gstRate,
        uqc: uqc.trim() || undefined,
        source: "manual",
      })) as ApiResp<FirmHsnLibraryRow>;
      if (!res.success || !res.data) {
        setError(res.error ?? "Could not add this code.");
        return;
      }
      onAdded(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add this code.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Add to your Firm HSN/SAC Library"
      note="This adds the code to your firm's own library so it — and every future line that reuses it — comes from one place you control. Caflow does not check or suggest whether this is the correct classification."
      onClose={onClose}
      maxWidthClass="max-w-md"
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="block text-xs font-medium text-[#475569]">HSN/SAC code</span>
          <input
            autoFocus
            value={hsnCode}
            onChange={(e) => setHsnCode(e.target.value.replace(/[^\d]/g, ""))}
            placeholder="e.g. 998221"
            className={inputCls}
            inputMode="numeric"
          />
          {!codeValid && hsnCode.length > 0 && (
            <span className="block text-[11px] text-red-600">2–8 digits.</span>
          )}
        </label>

        <label className="block space-y-1">
          <span className="block text-xs font-medium text-[#475569]">Description</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Financial auditing services"
            className={inputCls}
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="block text-xs font-medium text-[#475569]">Type</span>
            <select value={hsnType} onChange={(e) => setHsnType(e.target.value as "goods" | "services")} className={inputCls}>
              <option value="services">Services (SAC)</option>
              <option value="goods">Goods (HSN)</option>
            </select>
          </label>
          <label className="block space-y-1">
            <span className="block text-xs font-medium text-[#475569]">GST rate (optional)</span>
            <select
              value={gstRate}
              onChange={(e) => setGstRate(e.target.value === "" ? "" : parseFloat(e.target.value))}
              className={inputCls}
            >
              <option value="">Varies / not set</option>
              {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
            </select>
          </label>
        </div>

        <label className="block space-y-1">
          <span className="block text-xs font-medium text-[#475569]">Unit (optional)</span>
          <input value={uqc} onChange={(e) => setUqc(e.target.value)} placeholder="e.g. NOS, OTH" className={inputCls} />
        </label>

        {error && <p className="text-[11px] text-red-600">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={saving} className="text-sm px-3.5 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSave}
            className="text-sm px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {saving && <Loader2 size={14} className="animate-spin" />} Add to library
          </button>
        </div>
      </div>
    </Modal>
  );
}
