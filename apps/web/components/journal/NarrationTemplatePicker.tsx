"use client";
import * as React from "react";
import { Combobox } from "@/components/ui/combobox";
import { api, type NarrationTemplate } from "@/lib/api";
import { arrayOrEmpty } from "@/lib/api/shape";

/**
 * The client's saved narrations, beside a manual journal's narration box (POST-A-093).
 *
 * Picking one FILLS the box with its words; the CA may still change them, and the entry is saved with the words in the box, never with
 * the template, so removing a template later changes no entry. "Save this narration" keeps the words in the box for this client (the
 * server answers whether they were new or already kept, and refuses words it cannot keep, in its own sentence). A template picked from
 * the list can be taken out of it while the box still holds its words.
 *
 * The list is the server's: it is read when the picker appears (and again after a save or a removal) and searched in the browser only
 * for what was read. A read that fails is said as such with Try again and the picker stays shut, never an empty list, so "no saved
 * narrations" means there are none.
 */
/** What the last press said, and whether it was a refusal. */
type Said = { text: string; problem: boolean };

export function NarrationTemplatePicker({ clientId, narration, disabled, onPick }: {
  clientId: string;
  narration: string;
  disabled?: boolean;
  onPick: (words: string) => void;
}) {
  const [picked, setPicked] = React.useState<NarrationTemplate | null>(null);
  const [said, setSaid] = React.useState<Said | null>(null);
  const [busy, setBusy] = React.useState(false);
  // One write at a time, and a second click in the same tick is ignored (a ref, which a re-render cannot lag behind).
  const writing = React.useRef(false);

  // The client's list, read when the picker appears and again after a save or a removal. `null` is NOT READ (yet, or the read failed),
  // which is never shown as an empty list; a newer read supersedes an older one that answers late.
  const [templates, setTemplates] = React.useState<NarrationTemplate[] | null>(null);
  const [readProblem, setReadProblem] = React.useState<string | null>(null);
  const readRun = React.useRef(0);
  const read = React.useCallback(async () => {
    const mine = ++readRun.current;
    setReadProblem(null);
    try {
      const res = await api.narrationTemplates.list(clientId);
      if (mine !== readRun.current) return;
      if (!res.success) {
        setTemplates(null);
        setReadProblem(res.error || "The saved narrations could not be read.");
        return;
      }
      setTemplates(arrayOrEmpty<NarrationTemplate>(res.data));
    } catch (e: unknown) {
      if (mine !== readRun.current) return;
      setTemplates(null);
      setReadProblem(e instanceof Error && e.message ? e.message : "The saved narrations could not be read.");
    }
  }, [clientId]);
  // A new client is a new list: nothing of the last client's may be shown, picked or removed while the new one is read.
  React.useEffect(() => {
    setTemplates(null);
    setPicked(null);
    setSaid(null);
    void read();
  }, [read]);
  // What the last press said is about the words it was pressed on: a change to the box makes it stale.
  React.useEffect(() => { setSaid(null); }, [narration]);

  async function write(action: () => Promise<Said>) {
    if (writing.current) return;
    writing.current = true;
    setBusy(true);
    setSaid(null);
    try {
      setSaid(await action());
    } catch (e: unknown) {
      setSaid({ text: e instanceof Error && e.message ? e.message : "That could not be done. Please try again.", problem: true });
    } finally {
      writing.current = false;
      setBusy(false);
    }
  }

  const save = () => write(async () => {
    const res = await api.narrationTemplates.save(clientId, narration);
    if (!res.success || !res.data) return { text: res.error || "The narration could not be saved.", problem: true };
    if (res.data.created) void read();
    return { text: res.data.created ? "Saved for this client." : "Already saved for this client.", problem: false };
  });

  const remove = (template: NarrationTemplate) => write(async () => {
    const res = await api.narrationTemplates.archive(template.id, clientId);
    if (!res.success) return { text: res.error || "The saved narration could not be removed.", problem: true };
    setPicked(null);
    void read();
    return { text: "Removed from this client's saved narrations. Entries that used it keep their words.", problem: false };
  });

  const stillPicked = picked !== null && picked.narration === narration.trim();

  return (
    <div className="mt-1 space-y-1" data-testid="narration-templates">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-[14rem] flex-1">
          <Combobox<NarrationTemplate>
            value={stillPicked ? picked : null}
            onChange={(v) => {
              const t = Array.isArray(v) ? v[0] ?? null : v;
              setSaid(null);
              setPicked(t);
              if (t) onPick(t.narration);
            }}
            options={templates ?? []}
            getOptionId={(t) => t.id}
            getLabel={(t) => t.narration}
            placeholder={templates !== null ? "Pick a saved narration"
              : readProblem ? "Saved narrations could not be read" : "Reading saved narrations…"}
            searchPlaceholder="Search saved narrations"
            emptyText={templates && templates.length > 0
              ? "No saved narration matches what you typed." : "No saved narrations for this client yet."}
            ariaLabel="Saved narration"
            size="sm"
            disabled={disabled || templates === null}
          />
        </div>
        <button type="button" onClick={save} disabled={disabled || busy || !narration.trim()}
                className="rounded border border-ps-border px-2 py-1 text-xs text-ps-ink hover:bg-ps-muted disabled:opacity-50">
          Save this narration
        </button>
        {stillPicked && picked && (
          <button type="button" onClick={() => remove(picked)} disabled={disabled || busy}
                  className="text-xs text-ps-label underline hover:text-ps-ink disabled:opacity-50">
            Remove it from the saved narrations
          </button>
        )}
      </div>
      {readProblem && (
        <p className="text-xs text-state-problem" role="alert">
          {readProblem}{" "}
          <button type="button" onClick={() => void read()} className="underline hover:text-ps-ink">Try again</button>
        </p>
      )}
      {said?.problem && <p className="text-xs text-state-problem" role="alert">{said.text}</p>}
      {/* Mounted before it has anything to say, so a screen reader announces the words when they arrive. */}
      <p className="text-xs text-ps-label" role="status">{said && !said.problem ? said.text : ""}</p>
    </div>
  );
}
