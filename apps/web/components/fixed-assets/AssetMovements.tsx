"use client";

/**
 * Where an asset has been and who has kept it, and a move recorded with its date (POST-A-112, migration 591).
 *
 * `fixed_assets.location` was one box a move overwrote, so where an asset was last March, and who held it before, was nowhere. The
 * server keeps a movement per move and moves the asset in the same step; this panel shows the history it serves and sends a move.
 * It decides nothing: whether a date may be used, whether anything moved and whether the asset can move at all are the server's, and
 * its refusal is shown in its own words. A typo in the place or the keeper is corrected from Correct, which records no movement.
 *
 * The movement carries the place and keeper the form opened on, and the server refuses it, recording nothing, when the asset has moved
 * since (somebody else recorded a movement in between), because the form would otherwise put the asset back where it was. After any
 * refusal the panel reads the history again, and where the register's place or keeper is no longer what the form opened on it closes
 * the form, keeps the server's sentence on screen and shows the row where the asset is now: a new form starts from there.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { formatDate, todayIstISO } from "@/lib/dates/format";

interface Movement {
  id: string;
  moved_on: string;
  from_location: string | null;
  to_location: string | null;
  from_custodian: string | null;
  to_custodian: string | null;
  note: string | null;
  recorded_by: string | null;
}
interface History { location: string | null; custodian: string | null; movements: Movement[] }
interface Envelope<T> { success: boolean; data: T | null; error?: string | null }

type Read = { state: "loading" } | { state: "ok"; history: History } | { state: "failed"; message: string };

const READ_FAILED = "The asset's movements could not be read.";

function readHistory(data: unknown): History | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  if (!Array.isArray(d.movements)) return null;
  const text = (v: unknown) => (typeof v === "string" && v ? v : null);
  return {
    location: text(d.location),
    custodian: text(d.custodian),
    movements: d.movements.filter((m): m is Movement => typeof m === "object" && m !== null && typeof (m as Movement).id === "string"),
  };
}

/** One side of a move in words: a place or a keeper that was not recorded is said so, never shown as a dash that reads as a value. */
const said = (v: string | null, none: string) => v ?? none;

export function AssetMovements({ assetId, onMoved }: {
  assetId: string;
  /** Where the asset is and who keeps it now, from the server (a movement it stored, or the register read again after a refusal), so
   *  the register's row can show it without reading the whole register again. */
  onMoved: (now: Pick<Movement, "to_location" | "to_custodian">) => void;
}) {
  const [read, setRead] = useState<Read>({ state: "loading" });
  const readRun = useRef(0);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ moved_on: "", to_location: "", to_custodian: "", note: "" });
  /** The place and keeper the form opened on, sent with the movement so the server can refuse one made from a stale form. */
  const [opened, setOpened] = useState<{ location: string | null; custodian: string | null }>({ location: null, custodian: null });
  /** A refusal that closed the form because the asset had moved since it was opened: the server's sentence, kept on screen. */
  const [notice, setNotice] = useState<string | null>(null);
  const dates = useDateProblems();
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  /** Reads the history; answers it, or null when it could not be read or a later read has superseded this one. */
  const load = useCallback(async (): Promise<History | null> => {
    const run = ++readRun.current;
    setRead({ state: "loading" });
    try {
      const j = await request<Envelope<unknown>>(`/api/fixed-assets/${encodeURIComponent(assetId)}/movements`);
      const history = j.success ? readHistory(j.data) : null;
      if (run !== readRun.current) return null;
      setRead(history ? { state: "ok", history } : { state: "failed", message: j.error || READ_FAILED });
      return history;
    } catch (e) {
      if (run === readRun.current) setRead({ state: "failed", message: e instanceof Error && e.message ? e.message : READ_FAILED });
      return null;
    }
  }, [assetId]);

  useEffect(() => { void load(); }, [load]);

  function openForm() {
    if (read.state !== "ok") return;
    // The form starts at where the asset is and who keeps it now, so a move changes what moved and leaves the rest as it is.
    setForm({ moved_on: "", to_location: read.history.location ?? "", to_custodian: read.history.custodian ?? "", note: "" });
    setOpened({ location: read.history.location, custodian: read.history.custodian });
    setError(null);
    setDone(null);
    setNotice(null);
    setOpen(true);
  }

  /** A refusal said in the form; then the history is read again, and where the asset has moved since the form opened the form is
   *  closed with the sentence kept beside the history, and the row shows where the asset is now. */
  async function refused(message: string) {
    setError(message);
    const now = await load();
    if (now && (now.location !== opened.location || now.custodian !== opened.custodian)) {
      setOpen(false);
      setError(null);
      setNotice(message);
      onMoved({ to_location: now.location, to_custodian: now.custodian });
    }
  }

  async function record() {
    if (savingRef.current) return;
    if (dates.first) { dates.refuseWith(setError); return; }
    if (!form.moved_on) { setError("Moved on: enter the date the asset moved."); return; }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      let j: Envelope<Movement>;
      try {
        j = await request<Envelope<Movement>>(`/api/fixed-assets/${encodeURIComponent(assetId)}/movements`, {
          method: "POST",
          body: JSON.stringify({
            moved_on: form.moved_on, from_location: opened.location, from_custodian: opened.custodian,
            to_location: form.to_location, to_custodian: form.to_custodian, note: form.note || null,
          }),
        });
      } catch (e) {
        await refused(e instanceof Error && e.message ? e.message : "The movement was not recorded.");
        return;
      }
      if (!j.success || !j.data) { await refused(j.error || "The movement was not recorded."); return; }
      const moved = j.data;
      setOpen(false);
      setDone("Recorded. The register shows the asset where it is now.");
      onMoved({ to_location: moved.to_location ?? null, to_custodian: moved.to_custodian ?? null });
      await load();
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 border-t border-ps-border pt-3 text-xs" data-testid={`asset-movements-${assetId}`}>
      <div className="flex items-center justify-between mb-2">
        <p className="font-medium text-ps-ink">Movements</p>
        {read.state === "ok" && !open && (
          <button type="button" onClick={openForm} className="text-2xs text-blue-600 hover:underline">Record a movement</button>
        )}
      </div>
      <p role="status" className="text-2xs text-state-ready">{done ?? ""}</p>
      {notice && <p role="alert" className="text-2xs text-state-problem">{notice}</p>}
      {read.state === "loading" && <p className="text-2xs text-ps-hint">Reading the asset&rsquo;s movements…</p>}
      {read.state === "failed" && (
        <p role="alert" className="text-2xs text-state-problem">
          {read.message}{" "}
          <button type="button" onClick={() => { void load(); }} className="underline">Try again</button>
        </p>
      )}
      {read.state === "ok" && read.history.movements.length === 0 && (
        <p className="text-2xs text-ps-label">This asset has not moved since it was entered in the register.</p>
      )}
      {read.state === "ok" && read.history.movements.length > 0 && (
        <ul className="space-y-1.5">
          {read.history.movements.map((m) => (
            <li key={m.id} className="text-2xs text-ps-body">
              <span className="font-medium">{formatDate(m.moved_on)}</span>
              {m.from_location !== m.to_location && (
                <> · {said(m.from_location, "no place recorded")} → {said(m.to_location, "no place recorded")}</>
              )}
              {m.from_custodian !== m.to_custodian && (
                <> · kept by {said(m.from_custodian, "nobody named")} → {said(m.to_custodian, "nobody named")}</>
              )}
              {m.note && <> · {m.note}</>}
              <span className="text-ps-hint"> · recorded by {m.recorded_by ?? "a member no longer with the firm"}</span>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="mt-2 grid grid-cols-2 gap-2 bg-white border border-ps-border rounded-lg p-3">
          <label className="flex flex-col gap-1">
            <span className="text-ps-label">Moved on</span>
            <DateInput id={`asset-moved-on-${assetId}`} value={form.moved_on} notAfter={todayIstISO()}
              onChange={(v) => setForm((f) => ({ ...f, moved_on: v }))}
              onStateChange={dates.watch("movedOn", "Moved on", { afterMax: true })} className="w-full" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ps-label">Now at</span>
            <input aria-label="Now at" maxLength={200} value={form.to_location} onChange={(e) => setForm((f) => ({ ...f, to_location: e.target.value }))}
              className="border border-ps-border rounded px-2 py-1" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ps-label">Now kept by</span>
            <input aria-label="Now kept by" maxLength={200} value={form.to_custodian} onChange={(e) => setForm((f) => ({ ...f, to_custodian: e.target.value }))}
              className="border border-ps-border rounded px-2 py-1" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ps-label">Note (optional)</span>
            <input aria-label="Note (optional)" maxLength={500} value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
              className="border border-ps-border rounded px-2 py-1" />
          </label>
          {error && <p role="alert" className="col-span-2 text-2xs text-state-problem">{error}</p>}
          <div className="col-span-2 flex gap-2">
            <Button variant="plain" size="none" onClick={() => record()} disabled={saving}
              className="px-3 py-1 bg-brand text-white rounded text-2xs disabled:opacity-50">{saving ? "Recording…" : "Record the movement"}</Button>
            <button type="button" onClick={() => setOpen(false)} disabled={saving} className="px-3 py-1 border rounded text-2xs disabled:opacity-50">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
