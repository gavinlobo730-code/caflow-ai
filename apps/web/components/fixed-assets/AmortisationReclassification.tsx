"use client";

/**
 * Move an intangible asset's accumulated amortisation out of the shared Accumulated Depreciation ledger into the ledger of its own
 * (POST-A-345, stage 3).
 *
 * WHY THE SCREEN EXISTS. Schedule III presents tangible and intangible assets on separate lines, each net of its own accumulated
 * depreciation or amortisation, and the product credited every asset's depreciation to one ledger on the tangible line. New
 * intangible assets are born pointing at their own ledger. For those already on the register this is the Partner's posting that
 * moves what is in the shared ledger, so that both balance-sheet lines are right.
 *
 * THIS SCREEN DECIDES NOTHING. Which assets move, what each move is made of, which dates the entries carry, which balance sheets it
 * changes and every reason it must not be posted are the server's (`services/amortisation_reclass_service`), and the screen shows the
 * server's own sentences and figures. What is here is the choice the Partner has to make before anything is sent: the date it is AS AT
 * (never defaulted, and a month end), and where the part of the depreciation an asset brought over with it sits (never defaulted
 * either: the server offers the ledgers that could hold it and the Partner picks, the shared ledger included, on purpose).
 *
 * WHAT IS POSTED IS WHAT WAS PREPARED. The date and ledger the preview was made for are kept with it and are what the post sends, and
 * changing either field throws the preview away, so a Partner can never post a preview of one date under another. The post asks again
 * and is refused if the total has moved since the Partner looked.
 *
 * WHO. Reading needs the accounting read permission. Posting and undoing need `accounting`/`approve`, which is a Partner's: posted
 * history is the CA's entry. The buttons are hidden for anyone else, and the server refuses them regardless.
 *
 * IT HIDES ITSELF when there is nothing for it to do, by asking the server's summary once, which reads the register, the chart and the
 * reclassification entries and no balance sheet figure. When the chart cannot take the change it says why in the server's words rather than vanishing.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { request } from "@/lib/api";
import { formatDate } from "@/lib/dates/format";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { usePermissions } from "@/lib/auth/AuthContext";
import { formatPaise } from "@/lib/money/format";
import {
  readPostResult, readPreview, readSummary,
  type ReclassPostResult, type ReclassPreview, type ReclassSummary,
} from "@/lib/fixedAssets/amortisationReclass";

interface Envelope<T = unknown> { success: boolean; data?: T; error?: string | null; detail?: unknown }

/** The sentence out of an answer. FastAPI's own refusals arrive as `detail`, the product's as `error`. */
function sentence(body: { detail?: unknown; error?: unknown } | null | undefined, fallback: string): string {
  const text = body?.detail ?? body?.error;
  return typeof text === "string" && text.trim() ? text.trim() : fallback;
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

const INPUT = "w-full px-3 py-2 border border-ps-border rounded-lg text-xs bg-white";

export function AmortisationReclassification({ clientId, onChanged }: {
  clientId: string;
  /** The register or the ledger changed — reload whatever lists it. */
  onChanged: () => void;
}) {
  const { can } = usePermissions();
  const canPost = can("accounting", "approve");
  const dates = useDateProblems();
  const ids = useId();

  // What the register and the chart say, asked once and again after a change: is there anything here at all?
  const [look, setLook] = useState<ReclassSummary | null | "failed" | "loading">("loading");
  const [asAt, setAsAt] = useState("");
  const [carriedId, setCarriedId] = useState("");
  const [preview, setPreview] = useState<ReclassPreview | null>(null);
  // The ledger the preview was made for. The post sends this and the preview's own date, never whatever the fields hold now.
  const [preparedCarried, setPreparedCarried] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReclassPostResult | null>(null);
  const [preparing, setPreparing] = useState(false);
  const writing = useRef(false);
  // The newest request of each kind. An answer that is not the newest is dropped, so a slow answer for an earlier date, ledger or
  // client never lands on what the Partner is now looking at.
  const prepareSeq = useRef(0);
  const lookSeq = useRef(0);

  const quietLook = useCallback(async () => {
    const mine = ++lookSeq.current;
    if (!clientId || clientId === "_placeholder") { setLook(null); return; }
    try {
      const body = await request<Envelope>(
        `/api/fixed-assets/amortisation-reclassification/summary?client_id=${encodeURIComponent(clientId)}`);
      const read = body.success ? readSummary(body.data) : null;
      if (mine === lookSeq.current) setLook(read ?? "failed");
    } catch {
      if (mine === lookSeq.current) setLook("failed");
    }
  }, [clientId]);

  useEffect(() => { quietLook(); }, [quietLook]);

  /** Anything the preview was made from has changed: it is no longer what would be posted. */
  function discardPreview() {
    prepareSeq.current += 1;          // an answer still on its way was asked for the old date
    setPreparing(false);
    setPreview(null);
    setError(null);
  }

  /** Ask the server what the move would be. Choosing the ledger asks again WITHOUT removing the preview, so the box the choice was made
   *  in stays where it is (focus and the screen reader's place are kept) and Post is held off until the answer arrives. */
  async function prepare(carried: string = carriedId, keepPreview = false) {
    const mine = ++prepareSeq.current;
    setError(null);
    setResult(null);
    if (!keepPreview) setPreview(null);
    if (dates.first) { setPreview(null); setError(dates.first); return; }
    if (!asAt) { setPreview(null); setError("Say the date the reclassification is as at: a month end."); return; }
    const qs = new URLSearchParams({ client_id: clientId, as_at: asAt });
    if (carried) qs.set("carried_over_from_account_id", carried);
    setPreparing(true);
    try {
      const body = await request<Envelope>(`/api/fixed-assets/amortisation-reclassification?${qs.toString()}`);
      if (mine !== prepareSeq.current) return;
      if (!body.success) { setPreview(null); setError(sentence(body, "Could not prepare the reclassification.")); return; }
      const read = readPreview(body.data);
      if (!read) { setPreview(null); setError("The server's answer could not be read."); return; }
      setPreview(read);
      setPreparedCarried(carried);
    } catch (e) {
      if (mine !== prepareSeq.current) return;
      setPreview(null);
      setError(e instanceof Error ? e.message : "Could not prepare the reclassification.");
    } finally {
      if (mine === prepareSeq.current) setPreparing(false);
    }
  }

  /** What the Partner is agreeing to, in the server's figures and dates: nothing in it is worked out here. */
  function confirmation(p: ReclassPreview): string {
    const source = p.shared_ledger?.name ?? "the shared Accumulated Depreciation ledger";
    const parts: string[] = [];
    if (p.moves_count > 0) {
      parts.push(
        `${p.journals_to_post} journal ${plural(p.journals_to_post, "entry", "entries")} will be posted for ` +
        `${p.moves_count} ${plural(p.moves_count, "asset", "assets")}, dated ${p.entry_dates.map((d) => formatDate(d)).join(", ")}, moving ` +
        `${formatPaise(p.total_to_move_paise)} out of ${source} into ${p.own_ledger?.name ?? "the Accumulated Amortisation ledger"}.`);
      if (p.carried_over_total_paise > 0) {
        parts.push(
          `${formatPaise(p.carried_over_total_paise)} of that is depreciation the assets brought over with them, taken from ` +
          `${p.carried_over_ledger?.name ?? source}.`);
      }
    }
    if (p.pointed_only_count > 0) {
      parts.push(
        `${p.pointed_only_count} ${plural(p.pointed_only_count, "asset", "assets")} with nothing depreciated yet ` +
        `${plural(p.pointed_only_count, "is", "are")} only pointed at the new ledger; no entry is posted for ` +
        `${plural(p.pointed_only_count, "it", "them")}, and there is nothing to undo.`);
    }
    if (p.moves_count > 0) parts.push("An asset that is moved can be undone while no depreciation or disposal has been posted on it since.");
    return parts.join(" ");
  }

  async function post() {
    if (!preview || !preview.ready || preparing || writing.current) return;
    const ok = await confirmDialog({ title: "Post the reclassification?", message: confirmation(preview), confirmLabel: "Post it" });
    if (!ok || writing.current) return;
    writing.current = true;
    setError(null);
    try {
      const body = await request<Envelope>("/api/fixed-assets/amortisation-reclassification", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, as_at: preview.as_at, asset_ids: preview.assets.map((a) => a.asset_id),
          expected_total_paise: preview.total_to_move_paise,
          carried_over_from_account_id: preparedCarried || null,
        }),
      });
      if (!body.success) { setError(sentence(body, "The reclassification was not posted.")); return; }
      const read = readPostResult(body.data);
      if (!read) { setError("The server's answer could not be read."); return; }
      setResult(read);
      setPreview(null);
      onChanged();
      await quietLook();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The reclassification was not posted.");
    } finally {
      writing.current = false;
    }
  }

  async function undo(assetId: string, code: string | null) {
    if (writing.current) return;
    const ok = await confirmDialog({
      title: "Undo the reclassification?",
      message: `${code ?? "This asset"} goes back to the shared Accumulated Depreciation ledger, and the journal entries that moved it are reversed. ` +
               "This is allowed only while no depreciation or disposal has been posted on the asset since.",
      confirmLabel: "Undo it", danger: true,
    });
    if (!ok || writing.current) return;
    writing.current = true;
    setError(null);
    try {
      const body = await request<Envelope>(`/api/fixed-assets/${encodeURIComponent(assetId)}/amortisation-reclassification/reverse`, { method: "POST" });
      if (!body.success) { setError(sentence(body, "The reclassification was not undone.")); }
      else { setResult(null); setPreview(null); onChanged(); }
      await quietLook();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The reclassification was not undone.");
      await quietLook();
    } finally {
      writing.current = false;
    }
  }

  if (look === "loading") return null;
  if (look === "failed" && !result && !error) {
    return <p className="text-3xs text-ps-hint">Could not check whether intangible assets&apos; amortisation sits in its own ledger.</p>;
  }
  if (look === null) return null;
  // `look` is the summary, or "failed" while there is still a result or an error to show (the refresh after a post can fail).
  const summary: ReclassSummary | null = look === "failed" ? null : look;
  if (summary?.refusal) {
    return <p className="text-3xs text-ps-hint" data-testid="amortisation-reclassification-refusal">{summary.refusal}</p>;
  }
  // Nothing to move and none moved: the screen has nothing to offer, so it says nothing.
  if (summary && summary.unmoved === 0 && summary.moved_assets.length === 0 && summary.excluded === 0 && !result && !error) return null;
  const movedAssets = summary?.moved_assets ?? [];

  const dateHint = `${ids}-date`;
  // Shown while any asset brought depreciation over AND once a ledger has been chosen, so a refusal of that choice (which lists no
  // assets) does not take the box away and leave the Partner unable to choose again.
  const needsCarriedChoice = !!preview && (preview.assets.some((a) => a.carried_over_paise > 0) || carriedId !== "");

  return (
    <div className="bg-white rounded-xl border border-ps-border px-5 py-4 space-y-3" data-testid="amortisation-reclassification">
      <div className="space-y-1">
        <p className="text-xs font-semibold text-ps-ink">Intangible assets — accumulated amortisation</p>
        <p className="text-2xs text-ps-hint">
          Schedule III shows intangible assets on their own line, net of their own amortisation. An intangible asset whose amortisation is
          still in the shared Accumulated Depreciation ledger makes the tangible line too low and the intangible line too high by the
          same amount. New intangible assets are kept in the Accumulated Amortisation ledger from the start.
          {summary && summary.unmoved > 0 && ` ${summary.unmoved} ${plural(summary.unmoved, "asset is", "assets are")} still in the shared ledger.`}
          {summary && summary.moved > 0 && ` ${summary.moved} ${plural(summary.moved, "has", "have")} been moved by a reclassification.`}
        </p>
      </div>

      {canPost ? (
        <div className="space-y-3">
          <label className="block space-y-1 max-w-sm">
            <span className="text-2xs font-medium text-ps-body">Reclassify as at</span>
            <DateInput className={INPUT} value={asAt} onChange={(v) => { setAsAt(v); discardPreview(); }}
                       onStateChange={dates.watch("asAt", "As-at date")} aria-label="Reclassify as at"
                       aria-describedby={dateHint} />
            <span id={dateHint} className="block text-3xs text-ps-hint">
              A month end, such as 31 March or 30 September, and not in the future. The balance sheet at each financial year end from this
              date shows the corrected split; a date between year ends is only partly corrected, and the preview says which. An earlier
              balance sheet keeps the split it had.
            </span>
          </label>
          <Button variant="plain" size="none" onClick={() => prepare()}
                  className="text-xs border border-ps-border text-ps-body px-3 py-1.5 rounded-lg hover:bg-ps-bg">
            Prepare the reclassification
          </Button>
        </div>
      ) : (
        <p className="text-2xs text-ps-hint">Only a Partner can post or undo this.</p>
      )}

      {error && <Callout tone="problem">{error}</Callout>}

      {preview && (
        <div className="space-y-3">
          {preview.refusals.length > 0 && (
            <Callout tone="problem" title="Not ready to post">
              <ul className="list-disc pl-4 space-y-1">{preview.refusals.map((r) => <li key={r}>{r}</li>)}</ul>
            </Callout>
          )}
          {needsCarriedChoice && canPost && (
            <div className="space-y-1 max-w-xl">
              <label htmlFor={`${ids}-carried-select`} className="block text-2xs font-medium text-ps-body">
                Depreciation the assets brought over with them sits in
              </label>
              <select id={`${ids}-carried-select`} className={INPUT} value={carriedId} aria-describedby={`${ids}-carried`}
                      onChange={(e) => { setCarriedId(e.target.value); void prepare(e.target.value, true); }}>
                <option value="">Choose the ledger…</option>
                {preview.shared_ledger && (
                  <option value={preview.shared_ledger.id}>{preview.shared_ledger.name} (the shared ledger)</option>
                )}
                {preview.carried_over_candidates.map((l) => (
                  <option key={l.id} value={l.id}>{`${l.code ?? ""} ${l.name ?? ""}`.trim()} — credit {formatPaise(l.credit_paise)}</option>
                ))}
              </select>
              <span id={`${ids}-carried`} className="block text-3xs text-ps-hint">
                Some assets came over from other books with depreciation already on them, and this product cannot tell which ledger holds
                it. The ledgers offered are those that hold a credit for this client and look like an accumulated depreciation ledger;
                an imported trial balance often puts it in one of its own. Nothing is moved until you choose.
              </span>
            </div>
          )}
          {preview.assets.length === 0 && preview.refusals.length === 0 && (
            <p className="text-2xs text-ps-hint">
              Nothing is left in the shared ledger to move as at {formatDate(preview.as_at)}.
            </p>
          )}
          {preview.assets.length > 0 && (
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-left text-ps-hint border-b border-ps-border">
                  <th className="py-1 pr-2 font-medium">Asset</th>
                  <th className="py-1 px-2 font-medium text-right">Register</th>
                  <th className="py-1 px-2 font-medium text-right">From its depreciation entries</th>
                  <th className="py-1 px-2 font-medium text-right">Brought over</th>
                  <th className="py-1 px-2 font-medium text-right">Moves as at {formatDate(preview.as_at)}</th>
                  <th className="py-1 pl-2 font-medium text-right">Moves later</th>
                </tr>
              </thead>
              <tbody>
                {preview.assets.map((a) => (
                  <tr key={a.asset_id} className="border-b border-ps-border/60">
                    <td className="py-1 pr-2 text-ps-ink">{a.asset_code} {a.asset_name}{a.outcome === "pointed_only" ? " (nothing depreciated yet)" : ""}</td>
                    <td className="py-1 px-2 text-right">{formatPaise(a.register_paise)}</td>
                    <td className="py-1 px-2 text-right">{formatPaise(a.posted_by_depreciation_paise)}</td>
                    <td className="py-1 px-2 text-right">{formatPaise(a.carried_over_paise)}</td>
                    <td className="py-1 px-2 text-right">{formatPaise(a.moves_as_at_paise)}</td>
                    <td className="py-1 pl-2 text-right">{formatPaise(a.moves_later_paise)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="pt-1.5 font-semibold text-ps-ink" colSpan={5}>
                    Total moved into {preview.own_ledger?.name ?? "the new ledger"}, as at {formatDate(preview.as_at)} and later
                  </td>
                  <td className="pt-1.5 text-right font-semibold text-ps-ink">{formatPaise(preview.total_to_move_paise)}</td>
                </tr>
              </tfoot>
            </table>
          )}
          {preview.excluded.length > 0 && (
            <Callout tone="attention" title="Left where they are">
              <ul className="list-disc pl-4 space-y-1">{preview.excluded.map((x) => <li key={x.asset_id}>{x.asset_code}: {x.reason}</li>)}</ul>
            </Callout>
          )}
          {preview.financial_years.length > 0 && (
            <ul className="text-3xs text-ps-hint space-y-0.5">
              {preview.financial_years.map((y) => <li key={y.label}>{y.note}</li>)}
            </ul>
          )}
          {canPost && preview.ready && (
            <Button variant="plain" size="none" onClick={() => post()} disabled={preparing}
                    className="text-xs bg-brand text-white px-3 py-1.5 rounded-lg hover:bg-brand-dark disabled:opacity-60">
              Post the reclassification
            </Button>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-2">
          {result.moved.length > 0 && (
            <Callout tone="note" title="Posted">
              {result.moved.length} {plural(result.moved.length, "asset", "assets")} moved, {formatPaise(result.total_moved_paise)} in all, as at {formatDate(result.as_at)}.
            </Callout>
          )}
          {result.skipped.length > 0 && (
            <Callout tone="attention" title="Skipped">
              <ul className="list-disc pl-4 space-y-1">{result.skipped.map((s) => <li key={s.asset_id}>{s.asset_code}: {s.reason}</li>)}</ul>
            </Callout>
          )}
          {result.failed.length > 0 && (
            <Callout tone="problem" title="Not posted">
              <ul className="list-disc pl-4 space-y-1">
                {result.failed.map((s) => (
                  <li key={s.asset_id}>{s.asset_code}: {s.reason}{s.partly_moved ? " It is listed below with an Undo." : ""}</li>
                ))}
              </ul>
            </Callout>
          )}
        </div>
      )}

      {movedAssets.length > 0 && (
        <div className="space-y-1">
          <p className="text-2xs font-medium text-ps-body">Moved by a reclassification</p>
          <ul className="text-2xs text-ps-ink space-y-1">
            {movedAssets.map((a) => (
              <li key={a.asset_id} className="flex items-center justify-between gap-3">
                <span>
                  {a.asset_code} {a.asset_name}
                  {a.unfinished ? " — its move did not finish: part of its amortisation is in each ledger" : ""}
                </span>
                {canPost && (
                  <Button variant="plain" size="none" onClick={() => undo(a.asset_id, a.asset_code)}
                          aria-label={`${a.unfinished ? "Finish undoing" : "Undo"} the reclassification of ${a.asset_code ?? a.asset_name ?? "this asset"}`}
                          className="text-3xs border border-ps-border text-ps-body px-2 py-1 rounded-lg hover:bg-ps-bg">
                    {a.unfinished ? "Finish undo" : "Undo"}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <p className="text-3xs text-ps-hint">
            Undo is refused once depreciation or a disposal has been posted on the asset since, and says why.
          </p>
        </div>
      )}
    </div>
  );
}
