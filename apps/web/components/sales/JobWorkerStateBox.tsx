"use client";

/**
 * The State of a job worker who has no GSTIN recorded (POST-A-423).
 *
 * The FORM GST ITC-04 statement identifies the job worker by their GSTIN or, failing that, their State. A job-work challan to a job worker with no GSTIN, for a movement within the client's own State,
 * carried neither: the new-challan form shows the place of supply only for an inter-State movement (the one case CGST Rule 55(1)(viii) asks for it), the issue door asks for neither, and no screen
 * changed that challan's place of supply afterwards (the draft's correction form does, for an inter-State draft), so the statement named the challan as a gap on every statement it appeared in and
 * nothing on screen could close it.
 *
 * ONE COLUMN, ONE FACT. The challan's place of supply is the State its goods go to; for goods sent to a job worker that IS the job worker's State, which is what the statement reads when no GSTIN is held
 * (`itc_04._job_worker`). So this records the same column the inter-State box does, labelled for what the statement reads it as, and no second column was added. It records the State and nothing else:
 * whether the movement is inter-State is the challan's own tick, which this does not change.
 *
 * IT IS OFFERED WHILE NO GSTIN IS HELD, EMPTY OR HOLDING THE STATE ALREADY RECORDED (`jobWorkerHasNoGstin`, defined in `lib/sales/challanOffers.ts` and pinned to the statement's own test by
 * `shared/challan-offer-vectors.json`), so a wrong pick can be changed and not only a missing one filled in. It lists the current States and Union Territories (`INDIAN_STATES`) and not the
 * place-of-supply list, which adds "Other Country" and "Other Territory". A place of supply already recorded that is NOT on this list (the inter-State form offers the longer one) is SHOWN, in words,
 * and never as an empty picker; whether the form accepts such a value for a job worker is a statutory question that is on the owner's list and is not decided here.
 *
 * THIS SCREEN DECIDES NOTHING: the server judges the code and says a refusal in a sentence, which is shown here. The words follow the challan's status, because a draft is not on the statement yet.
 */
import { useEffect, useState } from "react";
import { api, type DeliveryChallan } from "@/lib/api";
import { INDIAN_STATES } from "@/lib/constants/indianStates";
import { Button } from "@/components/ui/button";
import { StateLookup } from "@/components/lookups/StateLookup";

export function JobWorkerStateBox({ challan, clientId, onSaved }: {
  challan: DeliveryChallan;
  clientId: string;
  /** Called once the server has taken the State, so the tab reads its lists and the open detail again. */
  onSaved: (challanId: string) => void | Promise<void>;
}) {
  const recorded = (challan.place_of_supply ?? "").trim();
  const listed = INDIAN_STATES.some((s) => s.code === recorded);
  // The picker holds a recorded State it can show; a recorded value it cannot show leaves it empty and is said in words instead.
  const shown = listed ? recorded : "";
  const [state, setState] = useState(shown);
  const [problem, setProblem] = useState<string | null>(null);
  // The box stays mounted across a save (focus stays on the button), so what it holds follows what the server now records.
  useEffect(() => { setState(shown); }, [shown]);

  async function save() {
    setProblem(null);
    if (!state) { setProblem("Pick the State first."); return; }
    if (state === recorded) { setProblem("That is the State already recorded."); return; }
    try {
      const res = await api.salesCycle.updateChallan(challan.id, clientId, { place_of_supply: state });
      if (!res.success) { setProblem(res.error || "That was refused."); return; }
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That was refused.");
      return;
    }
    await onSaved(challan.id);
  }

  const missing = !recorded;
  const draft = challan.status === "draft";
  const who = "identifies the job worker by their GSTIN or, where they have none, their State";
  const sameBox = "It is the same box as the place of supply of an inter-State movement.";
  const heading = missing
    ? "No GSTIN or State is recorded for the job worker"
    : listed
      ? "The job worker has no GSTIN recorded, so their State is the one below"
      : `The recorded place of supply (${recorded}) is not on the list of States`;
  const body = missing
    ? `${draft ? `Once this challan is issued, the FORM GST ITC-04 statement ${who}, and neither is recorded.` : `The FORM GST ITC-04 statement ${who}, and neither is recorded, so the statement names this challan until one is.`} Record the State the goods go to. ${sameBox} It records the State only: whether the movement is inter-State is the challan's own tick, which this does not change. The Rule 55 table below shows a place of supply only for an inter-State movement.`
    : listed
      ? `The FORM GST ITC-04 statement ${draft ? "will read" : "reads"} this State for the job worker because no GSTIN is held. Change it here if it is wrong. ${sameBox}`
      : `The FORM GST ITC-04 statement ${draft ? "will read" : "reads"} this value for the job worker because no GSTIN is held, and the list below offers States only. Pick the job worker's State to replace it. ${sameBox}`;
  return (
    <div
      className={`mb-3 rounded border p-3 text-sm ${missing ? "border-state-attention-border bg-state-attention-surface text-state-attention" : "border-ps-border bg-ps-muted text-ps-body"}`}
      data-testid="job-worker-state-box"
    >
      <div className="font-medium">{heading}</div>
      <p className="mt-1 text-xs">{body}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <StateLookup value={state} onChange={(code) => setState(code)} placeholder="— Select —" ariaLabel="State of the job worker" />
        <Button variant="plain" size="none" onClick={save} className="rounded bg-brand px-3 py-1 text-xs text-white disabled:opacity-50">Record the State</Button>
      </div>
      {problem && <p role="alert" className="mt-2 text-xs text-state-problem">{problem}</p>}
    </div>
  );
}
