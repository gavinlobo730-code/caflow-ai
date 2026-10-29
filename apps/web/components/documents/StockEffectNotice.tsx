"use client";

/**
 * Says, on the screen that just issued or received a document, that its stock effect was not all recorded (POST-A-092).
 *
 * The sentence is the server's (`domain/inventory/stock_effect`), read by `lib/documents/stockEffect`; this component words
 * nothing. It is the amber panel kind the purchases screen already uses for what the TDS register could not establish, and for
 * the same reason: the document IS in the books, so a red failure would be false, and a green confirmation would hide that the
 * stock report and the Inventory account do not include it. It stays until dismissed, because a notice a CA never saw is no notice,
 * and a second document adds its sentence beside the first instead of replacing it (each sentence names its document).
 */
import { AlertTriangle } from "lucide-react";

export function StockEffectNotice({ texts, onDismiss }: { texts: readonly string[]; onDismiss: () => void }) {
  if (texts.length === 0) return null;
  return (
    <div role="status" data-testid="stock-effect-notice"
      className="rounded-lg border border-state-attention-border bg-state-attention-surface px-4 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} className="text-state-attention mt-0.5 flex-shrink-0" aria-hidden />
        <div className="flex-1">
          <p className="text-sm font-semibold text-ps-body">Stock was not fully recorded</p>
          <ul className="mt-1 space-y-1">
            {texts.map((text) => <li key={text} className="text-xs text-ps-body">{text}</li>)}
          </ul>
        </div>
        <button type="button" onClick={onDismiss} aria-label="Dismiss"
          className="text-xs text-state-attention hover:underline flex-shrink-0">Dismiss</button>
      </div>
    </div>
  );
}
