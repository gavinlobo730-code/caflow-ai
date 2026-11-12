"use client";

/**
 * Correct a DRAFT delivery challan from the screen (POST-A-417).
 *
 * WHAT THE SCREEN COULD NOT DO. A challan is made as a draft whose Rule 55(1) particulars are optional (the HSN code of a line, the consignee when no customer was picked, what a job-work challan
 * sends), and the server will not issue it without them. The amendment door took the consignee, the kind of goods and the place of supply but DROPPED a line, so an HSN code could never be added,
 * and no screen called it for a draft at all: a challan that lacked a particular was made again with a new number while the draft kept its own.
 *
 * THIS SCREEN JUDGES NO VALUE. It shows the draft as the server read it and sends what the person changed; the server judges every value (a GSTIN's check digit, a state code, an HSN that is not
 * digits, a line that is not this challan's, anything of a line but its words and its HSN code) and says a refusal in a sentence, which is shown here. What the screen does decide is which boxes it
 * offers (the kind of goods for job work, the place of supply for an inter-State movement, as the new-challan form does) and the emptied-box case below. Only a draft is offered this form: once the
 * goods have left, the lines are the issued document's.
 *
 * THREE BOXES CANNOT BE EMPTIED HERE, the consignee's GSTIN, the place of supply and the kind of goods: the amendment door reads a blank for those as "unchanged" (POST-A-399's shape: an
 * emptied box that is sent as nothing while the screen says it saved). So a box that held a value and is now empty is said on the box before anything is sent, and not saved as if it had worked.
 * An HSN box can be emptied (the server clears it).
 */
import { useState } from "react";
import { api, type ChallanParticulars, type DeliveryChallan, type SalesCycleVocabulary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { StateLookup } from "@/components/lookups/StateLookup";

interface LineBox { id: string; description: string; hsn: string; wasDescription: string; wasHsn: string }

const text = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

export function DraftChallanEditor({ detail, clientId, goodsKinds, onSaved, onClose }: {
  detail: ChallanParticulars;
  clientId: string;
  goodsKinds: SalesCycleVocabulary["goods_kinds"];
  /** Called once the server has taken the correction, so the tab reads its lists and the open detail again. */
  onSaved: (challanId: string) => void | Promise<void>;
  onClose: () => void;
}) {
  const challan = detail.challan as DeliveryChallan;
  const jobWork = challan.reason === "job_work";
  const wasName = text(challan.consignee_name);
  const wasGstin = text(challan.consignee_gstin);
  const wasAddress = text(challan.consignee_address);
  const wasKind = text(challan.goods_kind);
  const wasPlace = text(challan.place_of_supply);

  const [name, setName] = useState(wasName);
  const [gstin, setGstin] = useState(wasGstin);
  const [address, setAddress] = useState(wasAddress);
  const [kind, setKind] = useState(wasKind);
  const [place, setPlace] = useState(wasPlace);
  const [lines, setLines] = useState<LineBox[]>(() => detail.lines.map((l) => ({
    id: text(l.id), description: text(l.description), hsn: text(l.hsn_sac), wasDescription: text(l.description), wasHsn: text(l.hsn_sac),
  })));
  const [problem, setProblem] = useState<string | null>(null);
  // True from the press of Save to the server's answer: Close, Escape and a click on the backdrop do nothing then, so a refusal is not lost to a dialog that went away while the request was out.
  const [saving, setSaving] = useState(false);

  /** The boxes that held a value and are empty now, by name: the amendment door cannot remove these (it reads a blank as unchanged), so they are said and nothing is sent. */
  function removedBoxes(): string[] {
    const out: string[] = [];
    if (wasGstin && !gstin.trim()) out.push("the consignee's GSTIN");
    if (challan.is_inter_state && wasPlace && !place.trim()) out.push("the place of supply");
    if (jobWork && wasKind && !kind.trim()) out.push("what is being sent");
    return out;
  }

  const lineChanged = (l: LineBox) => l.description !== l.wasDescription || l.hsn !== l.wasHsn;
  const anyChange = name !== wasName || gstin !== wasGstin || address !== wasAddress || (jobWork && kind !== wasKind) || (!!challan.is_inter_state && place !== wasPlace) || lines.some(lineChanged);

  async function save() {
    setProblem(null);
    const removed = removedBoxes();
    if (removed.length) {
      setProblem(`${removed.join(" and ")} held a value and is empty now. ${removed.length === 1 ? "That box cannot" : "Those boxes cannot"} be emptied here: type the new value, or leave ${removed.length === 1 ? "it" : "them"} as it was.`);
      return;
    }
    if (!anyChange) { setProblem("Nothing was changed."); return; }
    const changedLines = lines.filter(lineChanged);
    setSaving(true);
    try {
      const res = await api.salesCycle.updateChallan(challan.id, clientId, {
        consignee_name: name !== wasName ? name : undefined,
        consignee_gstin: gstin !== wasGstin ? gstin.trim() : undefined,
        consignee_address: address !== wasAddress ? address : undefined,
        goods_kind: jobWork && kind !== wasKind ? kind : undefined,
        place_of_supply: challan.is_inter_state && place !== wasPlace ? place : undefined,
        lines: changedLines.length
          ? changedLines.map((l) => ({
            id: l.id,
            description: l.description !== l.wasDescription ? l.description : undefined,
            hsn_sac: l.hsn !== l.wasHsn ? l.hsn : undefined,
          }))
          : undefined,
      });
      if (!res.success) { setProblem(res.error || "That was refused."); return; }
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That was refused.");
      return;
    } finally {
      setSaving(false);
    }
    await onSaved(challan.id);
  }

  /** Closing is held while a save is out: the answer to it is said in this dialog. */
  const close = () => { if (!saving) onClose(); };

  const box = "w-full rounded border border-ps-border px-2 py-1.5 text-sm";
  return (
    <Modal
      title={`Correct draft challan ${challan.document_no}`}
      note="A draft is corrected here until it is issued. What Rule 55(1) asks for is checked when you issue it, and the server says what is still missing."
      onClose={close}
      maxWidthClass="max-w-2xl"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="plain" size="none" onClick={close} className="rounded border border-ps-border px-3 py-1 text-xs">Close</Button>
          <Button variant="plain" size="none" onClick={save} className="rounded bg-brand px-3 py-1 text-xs text-white disabled:opacity-50">Save the correction</Button>
        </div>
      }
    >
      <div className="space-y-3">
        <label className="block text-sm">
          <span className="mb-1 block text-ps-label">Consignee name</span>
          <input aria-label="Consignee name" value={name} onChange={(e) => setName(e.target.value)} className={box} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-ps-label">Consignee GSTIN</span>
          <input aria-label="Consignee GSTIN" value={gstin} onChange={(e) => setGstin(e.target.value)} className={box} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-ps-label">Consignee address</span>
          <input aria-label="Consignee address" value={address} onChange={(e) => setAddress(e.target.value)} className={box} />
        </label>
        {jobWork && (
          <label className="block text-sm">
            <span className="mb-1 block text-ps-label">What is being sent (CGST s.143)</span>
            <select aria-label="What is being sent" value={kind} onChange={(e) => setKind(e.target.value)} className={box}>
              <option value="">Not recorded</option>
              {goodsKinds.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
          </label>
        )}
        {challan.is_inter_state && (
          <div className="text-sm">
            <span className="mb-1 block text-ps-label">Place of supply (CGST Rule 55(1)(viii))</span>
            <StateLookup placeOfSupply value={place} onChange={(code) => setPlace(code)} placeholder="— Select —" ariaLabel="Place of supply" clearable />
          </div>
        )}
        <div>
          <div className="mb-1 text-sm font-medium text-ps-body">Lines — description and HSN code</div>
          <p className="mb-2 text-xs text-ps-label">The quantity, unit, rate and tax of a line are what the challan&apos;s totals are made from, so they are not changed on a draft: a challan with different ones is made again.</p>
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={l.id} className="grid gap-2 sm:grid-cols-3">
                <input aria-label={`Line ${i + 1} description`} value={l.description} placeholder="Description"
                  onChange={(e) => setLines(lines.map((x) => (x.id === l.id ? { ...x, description: e.target.value } : x)))}
                  className={`${box} sm:col-span-2`} />
                <input aria-label={`Line ${i + 1} HSN code`} value={l.hsn} placeholder="HSN code" inputMode="numeric"
                  onChange={(e) => setLines(lines.map((x) => (x.id === l.id ? { ...x, hsn: e.target.value } : x)))}
                  className={box} />
              </div>
            ))}
          </div>
        </div>
        {problem && <p role="alert" className="text-xs text-state-problem">{problem}</p>}
      </div>
    </Modal>
  );
}
