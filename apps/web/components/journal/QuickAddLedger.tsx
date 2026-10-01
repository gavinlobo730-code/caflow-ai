"use client";

/**
 * Create a ledger without leaving the voucher (accounting-08).
 *
 * WHAT WAS MISSING
 *   The journal editor's account box had no way to say "this ledger does not
 *   exist yet", so a CA a third of the way through a voucher who found the
 *   ledger missing abandoned it, went to the chart of accounts, added the
 *   account, and keyed the voucher again. `HsnLookup` already shows the shape
 *   that fixes it — a "Create" row in the picker that opens a small dialog and
 *   comes back with the new row selected — and this is that, for accounts.
 *
 * IT WRITES THROUGH THE ACCOUNT ENDPOINT AND DECIDES NOTHING. The same
 * `POST /api/accounting/accounts` the Chart of Accounts screen uses, so the code
 * is still required (UNIQUE per firm, client and code is the server's rule and
 * the server's sentence comes back verbatim) and the account is created for THIS
 * CLIENT: a ledger typed from inside one client's voucher is that client's own,
 * and a firm-wide one would appear on every other client's chart too. A firm-
 * level account is offered on the Chart of Accounts screen, where that choice is
 * the point of the form.
 *
 * Subtype, group and the Schedule III mapping are left to the chart screen on
 * purpose: they decide where the account sits on the balance sheet, which is a
 * considered act and not a side effect of finishing a voucher. The account is
 * created with a type alone, which is all a journal line needs.
 */
import { useRef, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Field, Input, Select } from "@/components/ui/field";
import { Callout } from "@/components/ui/callout";
import { api } from "@/lib/api";
import type { EditorAccount } from "@/components/journal/JournalEditor";

//: The five types chart_of_accounts.account_type allows. The Chart of Accounts
//: screen holds the same list; both take it from the table's own CHECK.
const ACCOUNT_TYPES = ["Asset", "Liability", "Equity", "Revenue", "Expense"] as const;
type AccountType = typeof ACCOUNT_TYPES[number];

interface CreatedRow {
  id?: string;
  account_code?: string;
  account_name?: string;
  account_type?: string;
  is_active?: boolean;
}

export function QuickAddLedger({ clientId, seedName, onCreated, onClose }: {
  clientId: string;
  seedName: string;
  /** Called with the new account once the server has written it. */
  onCreated: (account: EditorAccount) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(seedName);
  const [code, setCode] = useState("");
  const [type, setType] = useState<AccountType>("Expense");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // `disabled={saving}` alone lags a genuinely back-to-back double dispatch by
  // one render, and here the second dispatch is a duplicate account.
  const submitting = useRef(false);

  async function save() {
    if (submitting.current) return;
    if (!name.trim()) { setError("The ledger needs a name."); return; }
    if (!code.trim()) {
      setError("An account code is required — it is what the chart is ordered and matched by.");
      return;
    }
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const res = await api.accounting.createAccount(
        { name: name.trim(), code: code.trim(), account_type: type }, clientId,
      ) as { success: boolean; data?: CreatedRow | null; error?: string | null };
      if (!res.success || !res.data?.id) {
        throw new Error(res.error ?? "The ledger was not created.");
      }
      onCreated({
        id: res.data.id,
        account_code: res.data.account_code ?? code.trim(),
        account_name: res.data.account_name ?? name.trim(),
        account_type: res.data.account_type ?? type,
        is_active: res.data.is_active ?? true,
      });
    } catch (e) {
      // The server's sentence is written for the CA (a duplicate code, a
      // read-only role) and is shown as it came.
      setError(e instanceof Error ? e.message : "The ledger was not created.");
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  return (
    <Modal title="Create a ledger" onClose={onClose} maxWidthClass="max-w-md"
           note="It is added to this client's chart and selected on the line you were editing.">
      <div className="space-y-3 text-xs"
           onKeyDown={(e) => { if (e.key === "Enter" && !saving) { e.preventDefault(); void save(); } }}>
        {error && <Callout tone="problem">{error}</Callout>}
        <Field label="Ledger name" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Code" required hint="Unique within this client's chart.">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="5100" />
          </Field>
          <Field label="Type" required>
            <Select value={type} onChange={(e) => setType(e.target.value as AccountType)}>
              {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          </Field>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={saving}
                  className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-40">
            Cancel
          </button>
          <button type="button" onClick={() => void save()} disabled={saving}
                  className="px-3 py-1.5 text-xs bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50">
            {saving ? "Creating…" : "Create ledger"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
