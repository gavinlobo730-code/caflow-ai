"use client";

import { useId } from "react";
import type { GoodsReturned } from "@/lib/inventory/goodsReturned";

/**
 * Did the goods on this credit or debit note physically come back? (POST-A-371)
 *
 * A section 34 note is also how a PRICE, a RATE or a DISCOUNT is corrected, and until now every goods line on a note moved stock and cost
 * whatever the note was for. The answer is stored on the note (`goods_returned`) and the server obeys it: "yes" moves stock as before, "no"
 * moves nothing and says so, and a note that names goods and has not said is REFUSED at issue in the server's own sentence. This control
 * only asks the question. It holds no rule: whether the note names goods is the caller's (a line whose item is a good), and what each answer
 * does is the server's.
 */
export function GoodsReturnedChoice({
  value,
  onChange,
  disabled,
  kind,
}: {
  value: GoodsReturned;
  onChange: (next: GoodsReturned) => void;
  disabled?: boolean;
  kind: "credit_note" | "debit_note";
}) {
  const group = useId();
  const yes = kind === "credit_note" ? "Goods returned: add them back to stock" : "Goods returned to the supplier: take them out of stock";
  const no = "No goods returned: a price, rate or discount correction (stock and cost do not move)";
  return (
    <fieldset className="text-xs text-ps-label" disabled={disabled}>
      <legend className="block text-xs font-medium text-ps-label mb-1">
        Did the goods come back?
        {value === null && <span className="ml-2 font-normal text-ps-hint">Required before you issue this note. The tax is adjusted either way.</span>}
      </legend>
      <div className="flex flex-col gap-1">
        <label className={`flex items-center gap-2 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
          <input type="radio" name={group} checked={value === true} onChange={() => onChange(true)} />
          <span>{yes}</span>
        </label>
        <label className={`flex items-center gap-2 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
          <input type="radio" name={group} checked={value === false} onChange={() => onChange(false)} />
          <span>{no}</span>
        </label>
      </div>
    </fieldset>
  );
}
