"use client";

import { useEffect, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { itemsKey, namesGoodsFrom } from "@/lib/inventory/namesGoods";

/**
 * Whether any of these catalogue items is a good (POST-A-378): the one question the "did the goods come back?" choice has to have answered before it is shown.
 *
 * A credit note raised from an invoice, or a debit note raised from a bill, copies the document's lines, and a line carries only the id of its catalogue item. The editors know each
 * line's item (`product.kind`); a modal that copies lines does not, so it asks the catalogue, under the client, once per set of ids. The server still decides what each answer does and
 * refuses to issue a note that names goods and has not said; this only decides whether to ASK.
 *
 * FALSE until the read returns, and FALSE when it fails or the items are not found: the choice is then not shown, the draft is saved without an answer exactly as before, and the editor
 * (or the issue) asks. Never true by guess.
 */
export function useNamesGoods(clientId: string, itemIds: readonly (string | null | undefined)[]): boolean {
  const key = itemsKey(itemIds);
  const [namesGoods, setNamesGoods] = useState(false);
  useEffect(() => {
    // A different set of items is a different question: the answer to the last one is not this one's, so it is false until this one is answered.
    setNamesGoods(false);
    if (!key) return;
    let cancelled = false;
    (async () => {
      try {
        const { data, error } = await getSupabaseClient()
          .from("service_catalogue")
          .select("id, kind")
          .eq("client_id", clientId)
          .in("id", key.split(","));
        // The client hands a failed read back as `error` and does not throw: a read that failed is not an answer, and is not "a good".
        if (!cancelled) setNamesGoods(namesGoodsFrom({ data, error }));
      } catch {
        // Best-effort, like the editors' own lookup of a line's item: the choice stays hidden and the note is asked about later.
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, key]);
  return namesGoods;
}
