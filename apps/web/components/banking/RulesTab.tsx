"use client";
/**
 * Rules — what the machine proposes, and what it may pass on its own.
 *
 * A rule watches for lines that match its conditions and PROPOSES how to
 * book them; the proposal appears on the line in Entries with the rule's
 * name as the reason. A Manager or Partner can mark a rule TRUSTED, and then
 * its lines pass with no click — after an import and in the daily sweep — as
 * journals created by the person who trusted it (migration 322,
 * docs/architecture/09-bank-entries.md). Un-trusting stops it at once.
 *
 * Precedence is the PRIORITY column, lower first, with creation order as the
 * tiebreak (BANK-11, migration 380). The first rule that fires wins, so a
 * narrow rule needs a smaller number than the broad one it sits under — until
 * this existed the only way past a broad rule written early was to delete and
 * re-create it, which loses its trusted flag. The list below is served in
 * evaluation order, so what a CA reads top to bottom is what the queue does.
 */
import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, ShieldCheck, X } from "lucide-react";
import { api } from "@/lib/api";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Can } from "@/components/Can";
import { useToast } from "@/components/ui/use-toast";
import { type Account, fmt, rsToP, BANK_CATEGORIES, GST_RATE_OPTIONS } from "@/components/banking/shared";

interface BankRule {
  id: string;
  rule_name: string;
  description_pattern: string | null;
  amount_min_paise: number | null;
  amount_max_paise: number | null;
  txn_type: "debit" | "credit" | "any";
  // BANK-11 / migration 380. Every default reproduces the old behaviour, so a
  // rule saved before this reads and behaves exactly as it did.
  priority: number | null;
  match_field: "description" | "reference_no" | "payee_name" | "any" | null;
  match_operator: "contains" | "starts_with" | "equals" | null;
  description_patterns: string[] | null;
  suggested_category: string | null;
  suggested_account_id: string | null;
  suggested_narration: string | null;
  suggested_gst_rate_bps: number | null;
  suggested_is_interstate: boolean | null;
  is_active: boolean;
  is_trusted: boolean;
  trusted_by: string | null;
  trusted_at: string | null;
}

const BLANK_RULE = {
  rule_name: "", description_pattern: "", amount_min: "", amount_max: "",
  txn_type: "any" as "debit" | "credit" | "any",
  // Lower runs first. 100 is the column default, so a new rule sits with the
  // existing ones and a CA who wants it to win types a smaller number.
  priority: "100",
  match_field: "description" as "description" | "reference_no" | "payee_name" | "any",
  match_operator: "contains" as "contains" | "starts_with" | "equals",
  // One per line in the textarea. Blank lines are dropped by the server, which
  // matters: an empty pattern would match every transaction.
  description_patterns: "",
  suggested_category: "", suggested_account_id: "", suggested_narration: "",
  // "" = the rule says nothing about GST. "0" = it says the charge carries none.
  suggested_gst_rate_bps: "", suggested_is_interstate: false,
};

export function RulesTab({ clientId, accounts }: { clientId: string; accounts: Account[] }) {
  const { toast } = useToast();
  const [rules, setRules] = useState<BankRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState({ ...BLANK_RULE });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.rules.list(clientId)) as { success: boolean; data: BankRule[] };
      if (!res.success) throw new Error("Couldn't load the rules.");
      setRules(res.data ?? []);
      setLoadError(null);
    } catch (e) {
      setRules([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the rules.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const accountName = (id: string | null) => {
    if (!id) return null;
    const a = accounts.find((x) => x.id === id);
    return a ? `${a.account_code} · ${a.account_name}` : "Unknown ledger";
  };

  function startNew() { setForm({ ...BLANK_RULE }); setFormError(null); setEditing("new"); }
  function startEdit(r: BankRule) {
    setForm({
      rule_name: r.rule_name,
      description_pattern: r.description_pattern ?? "",
      amount_min: r.amount_min_paise != null ? (r.amount_min_paise / 100).toFixed(2) : "",
      amount_max: r.amount_max_paise != null ? (r.amount_max_paise / 100).toFixed(2) : "",
      txn_type: r.txn_type ?? "any",
      priority: String(r.priority ?? 100),
      match_field: r.match_field ?? "description",
      match_operator: r.match_operator ?? "contains",
      description_patterns: (r.description_patterns ?? []).join("\n"),
      suggested_category: r.suggested_category ?? "",
      suggested_account_id: r.suggested_account_id ?? "",
      suggested_narration: r.suggested_narration ?? "",
      suggested_gst_rate_bps: r.suggested_gst_rate_bps == null ? "" : String(r.suggested_gst_rate_bps),
      suggested_is_interstate: !!r.suggested_is_interstate,
    });
    setFormError(null);
    setEditing(r.id);
  }

  // Empty string means "no bound", which is not the same as zero. rsToP now
  // returns null for text that is not an amount too, so both cases arrive here
  // as null — and save() refuses a bound that was typed but unreadable, rather
  // than storing "no bound" and letting the rule match lines it should not.
  const boundToPaise = (v: string) => (v.trim() === "" ? null : rsToP(v));

  async function save() {
    const payload = {
      rule_name: form.rule_name.trim(),
      description_pattern: form.description_pattern.trim() || null,
      amount_min_paise: boundToPaise(form.amount_min),
      amount_max_paise: boundToPaise(form.amount_max),
      txn_type: form.txn_type,
      // A whole number, and NOT rsToP: this is an ordering key, not money.
      priority: Number.isFinite(Number(form.priority)) && form.priority.trim() !== ""
        ? Math.trunc(Number(form.priority)) : 100,
      match_field: form.match_field,
      match_operator: form.match_operator,
      description_patterns: form.description_patterns
        .split("\n").map((t) => t.trim()).filter(Boolean),
      suggested_category: form.suggested_category || null,
      suggested_account_id: form.suggested_account_id || null,
      suggested_narration: form.suggested_narration.trim() || null,
      // Explicit null so clearing a wrongly-stamped rate actually sticks.
      suggested_gst_rate_bps: form.suggested_gst_rate_bps === "" ? null : Number(form.suggested_gst_rate_bps),
      suggested_is_interstate: form.suggested_is_interstate,
    };
    if (!payload.rule_name) { setFormError("Give the rule a name."); return; }
    if (form.amount_min.trim() !== "" && payload.amount_min_paise === null) {
      setFormError("The minimum amount isn't a number. Type it in rupees, like 25000 or 25000.50."); return;
    }
    if (form.amount_max.trim() !== "" && payload.amount_max_paise === null) {
      setFormError("The maximum amount isn't a number. Type it in rupees, like 25000 or 25000.50."); return;
    }
    if (form.priority.trim() !== "" && !Number.isFinite(Number(form.priority))) {
      setFormError("Priority must be a whole number. Lower runs first."); return;
    }
    const hasCondition = payload.description_pattern || payload.description_patterns.length > 0
      || payload.amount_min_paise != null
      || payload.amount_max_paise != null || payload.txn_type !== "any";
    if (!hasCondition) {
      setFormError("Add at least one condition — a narration phrase, an amount range, or money-in/money-out. A rule with no conditions would match every line.");
      return;
    }
    if (!payload.suggested_category && !payload.suggested_account_id && !payload.suggested_narration) {
      setFormError("Say what the rule proposes — a ledger, a category, or a narration.");
      return;
    }
    if (payload.suggested_gst_rate_bps !== null && !payload.suggested_account_id) {
      setFormError("A GST rate needs a ledger — the split books the ex-GST amount there.");
      return;
    }
    if (payload.suggested_gst_rate_bps !== null && payload.txn_type === "credit") {
      setFormError("A GST rate applies to bank charges — money out. Set this rule to money out, or either.");
      return;
    }
    setSaving(true); setFormError(null);
    try {
      if (editing === "new") await api.banking.rules.create({ client_id: clientId, ...payload });
      else if (editing) await api.banking.rules.update(editing, payload);
      setEditing(null);
      await load();
      toast({ title: "Rule saved", description: "Open lines will be proposed for again the next time Entries loads." });
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't save the rule.");
    } finally {
      setSaving(false);
    }
  }

  async function patch(r: BankRule, data: Record<string, unknown>, failed: string) {
    setBusy((b) => ({ ...b, [r.id]: true }));
    try { await api.banking.rules.update(r.id, data); await load(); return true; }
    catch (e) { toast({ title: failed, description: e instanceof Error ? e.message : String(e), variant: "destructive" }); return false; }
    finally { setBusy((b) => ({ ...b, [r.id]: false })); }
  }

  async function trust(r: BankRule, on: boolean) {
    if (on && !confirm(
      `Trust “${r.rule_name}”?\n\nEvery line it matches will be passed into the books with no click — after each import and in the daily sweep — as a journal created by you. You can undo any of them, and un-trusting the rule stops it at once.`)) return;
    const ok = await patch(r, { is_trusted: on }, on ? "Couldn't trust the rule" : "Couldn't un-trust the rule");
    if (ok) toast({ title: on ? "Trusted" : "No longer trusted",
                    description: on ? "Its ready lines will pass the next time Entries loads." : "It proposes only, from now." });
  }

  async function remove(r: BankRule) {
    if (!confirm(`Delete the rule “${r.rule_name}”? Lines it has already passed are unaffected.`)) return;
    setBusy((b) => ({ ...b, [r.id]: true }));
    try { await api.banking.rules.remove(r.id); await load(); }
    catch (e) { toast({ title: "Couldn't delete", description: e instanceof Error ? e.message : String(e), variant: "destructive" }); }
    finally { setBusy((b) => ({ ...b, [r.id]: false })); }
  }

  function gstSummary(r: BankRule) {
    if (r.suggested_gst_rate_bps == null) return null;
    if (r.suggested_gst_rate_bps === 0) return "no GST";
    return `${r.suggested_gst_rate_bps / 100}% ${r.suggested_is_interstate ? "IGST" : "CGST+SGST"}`;
  }
  const FIELD_LABEL: Record<string, string> = {
    description: "narration", reference_no: "reference", payee_name: "payee",
    any: "narration, reference or payee",
  };
  const OP_LABEL: Record<string, string> = {
    contains: "contains", starts_with: "starts with", equals: "is",
  };
  function conditionSummary(r: BankRule) {
    const bits: string[] = [];
    // The summary must say WHICH field and WHICH comparison, or two rules that
    // read identically here behave differently in the queue — and the queue is
    // where a trusted rule posts.
    const field = FIELD_LABEL[r.match_field ?? "description"] ?? "narration";
    const op = OP_LABEL[r.match_operator ?? "contains"] ?? "contains";
    const alts = r.description_patterns ?? [];
    const all = [r.description_pattern, ...alts].filter(Boolean) as string[];
    if (all.length === 1) bits.push(`${field} ${op} “${all[0]}”`);
    else if (all.length > 1) bits.push(`${field} ${op} any of ${all.length}: “${all.slice(0, 2).join("”, “")}”…`);
    if (r.amount_min_paise != null && r.amount_max_paise != null) bits.push(`${fmt(r.amount_min_paise)}–${fmt(r.amount_max_paise)}`);
    else if (r.amount_min_paise != null) bits.push(`≥ ${fmt(r.amount_min_paise)}`);
    else if (r.amount_max_paise != null) bits.push(`≤ ${fmt(r.amount_max_paise)}`);
    if (r.txn_type === "debit") bits.push("money out");
    if (r.txn_type === "credit") bits.push("money in");
    return bits.join(" · ") || "every line";
  }

  const trustedCount = rules.filter((r) => r.is_trusted && r.is_active).length;

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="bg-ps-hover border border-brand-light rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-brand-dark">How rules work</p>
        <p className="text-[11px] text-brand mt-1">
          A rule watches for lines that match its conditions and <strong>proposes</strong> how to book
          them — the proposal shows on the line in Entries, ready to pass. A rule marked{" "}
          <strong>trusted</strong> goes one step further: its lines are passed with no click, after each
          import and in the daily sweep, as journals created by whoever trusted it. Only a Manager or
          Partner can trust a rule, and any of its entries can be undone. When two rules match, the{" "}
          <strong>older one wins</strong>, so write the specific rules before the broad ones.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-ps-label">
          {loading ? "Loading…" : `${rules.length} rule${rules.length === 1 ? "" : "s"}${trustedCount ? ` · ${trustedCount} trusted` : ""}`}
        </p>
        <button onClick={startNew} className="text-xs px-3 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark flex items-center gap-1.5">
          <Plus size={12} /> New rule
        </button>
      </div>

      {editing && (
        <div className="bg-white rounded-xl border border-ps-border p-4 space-y-3">
          <p className="text-xs font-semibold text-ps-body">{editing === "new" ? "New rule" : "Edit rule"}</p>
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Rule name *</label>
            <input value={form.rule_name} onChange={(e) => setForm((f) => ({ ...f, rule_name: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. HDFC bank charges" />
          </div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ps-hint pt-1">When</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Look at</label>
              <select value={form.match_field}
                onChange={(e) => setForm((f) => ({ ...f, match_field: e.target.value as typeof f.match_field }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="description">The narration</option>
                <option value="reference_no">The reference / UTR</option>
                <option value="payee_name">The payee name</option>
                <option value="any">Any of the three</option>
              </select>
              <p className="text-[10px] text-ps-hint mt-1">
                The reference is often the only part a bank does not rewrite each month.
              </p>
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Which</label>
              <select value={form.match_operator}
                onChange={(e) => setForm((f) => ({ ...f, match_operator: e.target.value as typeof f.match_operator }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="contains">contains</option>
                <option value="starts_with">starts with</option>
                <option value="equals">is exactly</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Text to match</label>
            <input value={form.description_pattern} onChange={(e) => setForm((f) => ({ ...f, description_pattern: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. BANK CHARGES" />
            <p className="text-[10px] text-ps-hint mt-1">Plain text, not case-sensitive. No wildcards.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Or any of these (one per line)</label>
            <textarea value={form.description_patterns} rows={3}
              onChange={(e) => setForm((f) => ({ ...f, description_patterns: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
              placeholder={"ACME TRADERS\nACME EXPORTS\nACME PVT LTD"} />
            <p className="text-[10px] text-ps-hint mt-1">
              Matched the same way, against the same field. Three customers, one rule.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Min amount (₹)</label>
              <input type="number" min="0" step="0.01" value={form.amount_min} onChange={(e) => setForm((f) => ({ ...f, amount_min: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="any" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Max amount (₹)</label>
              <input type="number" min="0" step="0.01" value={form.amount_max} onChange={(e) => setForm((f) => ({ ...f, amount_max: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="any" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Direction</label>
              <select value={form.txn_type} onChange={(e) => setForm((f) => ({ ...f, txn_type: e.target.value as "debit" | "credit" | "any" }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="any">Either</option>
                <option value="credit">Money in (Receipt)</option>
                <option value="debit">Money out (Payment)</option>
              </select>
            </div>
          </div>
          <div className="w-40">
            <label className="block text-xs font-medium text-ps-label mb-1">Priority</label>
            <input type="number" step="1" value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="100" />
            <p className="text-[10px] text-ps-hint mt-1">
              Lower runs first. The first rule that fires wins, so give a narrow
              rule a smaller number than the broad one it sits under.
            </p>
          </div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ps-hint pt-1">Propose</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Book under</label>
              <AccountLookup accounts={accounts} value={form.suggested_account_id}
                onChange={(v) => setForm((f) => ({ ...f, suggested_account_id: v }))}
                ariaLabel="Ledger the rule proposes" placeholder="— None —" />
              <p className="text-[10px] text-ps-hint mt-1">A trusted rule must name a ledger.</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Category</label>
              <select value={form.suggested_category} onChange={(e) => setForm((f) => ({ ...f, suggested_category: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="">— Derive from the ledger —</option>
                {BANK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Narration</label>
            <input value={form.suggested_narration} onChange={(e) => setForm((f) => ({ ...f, suggested_narration: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. Bank charges" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">GST inside the amount</label>
              <select value={form.suggested_gst_rate_bps} onChange={(e) => setForm((f) => ({ ...f, suggested_gst_rate_bps: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="">— Don&apos;t split —</option>
                {GST_RATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <p className="text-[10px] text-ps-hint mt-1">
                Statement amounts are GST-inclusive. On money out the split claims the input credit
                (CGST Act s.16); on money in it books the output tax owed (s.9). 18% is usual on bank charges.
              </p>
            </div>
            {form.suggested_gst_rate_bps !== "" && form.suggested_gst_rate_bps !== "0" && (
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">Place of supply</label>
                <label className="flex items-start gap-2 pt-1.5">
                  <input type="checkbox" checked={form.suggested_is_interstate}
                    onChange={(e) => setForm((f) => ({ ...f, suggested_is_interstate: e.target.checked }))}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-ps-disabled" />
                  <span className="text-xs text-ps-label">Inter-state (IGST)</span>
                </label>
                <p className="text-[10px] text-ps-hint mt-1">Tick when this bank is registered outside the client&apos;s state (IGST Act s.12(12)).</p>
              </div>
            )}
          </div>
          {formError && <p className="text-xs text-state-problem bg-state-problem-surface rounded px-3 py-2">{formError}</p>}
          <div className="flex gap-2 justify-end pt-1">
            <button onClick={() => setEditing(null)} className="text-xs px-4 py-2 border border-ps-border rounded-lg hover:bg-ps-bg">Cancel</button>
            <button onClick={save} disabled={saving} className="text-xs px-4 py-2 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40">
              {saving ? "Saving…" : editing === "new" ? "Create rule" : "Save changes"}
            </button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={3} rows={3} /> : loadError ? (
        <div className="bg-white rounded-xl border border-state-problem-border p-10 text-center">
          <p className="text-sm text-state-problem font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">Retry</button>
        </div>
      ) : rules.length === 0 ? (
        <div className="bg-white rounded-xl border border-ps-muted p-10 text-center">
          <p className="text-sm text-ps-hint">No rules yet.</p>
          <p className="text-[11px] text-ps-hint mt-1">Rules save re-booking the same line every month — bank charges, salary, a recurring vendor. Book a few lines under a ledger in Entries and it will offer to make one.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden divide-y divide-ps-bg">
          {rules.map((r, i) => (
            <div key={r.id} className={`px-4 py-3 flex items-start gap-3 ${r.is_active ? "" : "bg-ps-surface"}`}>
              <span className="text-[10px] text-ps-disabled font-mono mt-0.5 w-4 shrink-0">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className={`text-xs font-medium truncate ${r.is_active ? "text-ps-ink" : "text-ps-hint"}`}>{r.rule_name}</p>
                  {!r.is_active && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ps-muted text-ps-hint">Off</span>}
                  {/* Only when it is NOT the default. The number on the left is
                      already the evaluation position — this says which rules
                      were deliberately moved, which is the question a CA asks
                      when one rule beats another. */}
                  {r.priority != null && r.priority !== 100 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ps-muted text-ps-label font-mono"
                      title="Lower runs first. The first rule that fires wins.">
                      priority {r.priority}
                    </span>
                  )}
                  {r.is_trusted && (
                    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-state-ready-surface text-state-ready border border-state-ready-border"
                      title={r.trusted_at ? `Trusted on ${r.trusted_at.slice(0, 10)}` : "Trusted"}>
                      <ShieldCheck size={10} /> Trusted — passes without a click
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-ps-hint mt-0.5">When {conditionSummary(r)}</p>
                <p className="text-[10px] text-ps-label mt-0.5">
                  {r.is_trusted ? "Pass as" : "Propose"}{" "}
                  {[accountName(r.suggested_account_id), r.suggested_category, r.suggested_narration, gstSummary(r)].filter(Boolean).join(" · ")}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Can resource="banking" action="approve"
                  fallback={r.is_trusted ? <span className="text-[10px] text-ps-hint" title="Only a Manager or Partner can change this">trusted</span> : null}>
                  {r.is_active && (
                    <button onClick={() => trust(r, !r.is_trusted)} disabled={busy[r.id] || (!r.is_trusted && !r.suggested_account_id)}
                      title={!r.is_trusted && !r.suggested_account_id ? "Give the rule a ledger first" : r.is_trusted ? "Stop it passing on its own" : "Let it pass its lines without a click"}
                      className={`text-[10px] px-2 py-1 border rounded ${r.is_trusted ? "border-ps-border text-ps-label hover:bg-ps-bg" : "border-state-ready-border bg-state-ready-surface text-state-ready hover:bg-emerald-100"} disabled:opacity-40`}>
                      {r.is_trusted ? "Un-trust" : "Trust"}
                    </button>
                  )}
                </Can>
                <button onClick={() => patch(r, { is_active: !r.is_active }, "Couldn't change the rule")} disabled={busy[r.id]}
                  className="text-[10px] px-2 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-label">
                  {r.is_active ? "Turn off" : "Turn on"}
                </button>
                <button onClick={() => startEdit(r)} disabled={busy[r.id]} className="text-ps-hint hover:text-ps-label" aria-label={`Edit ${r.rule_name}`}><Pencil size={13} /></button>
                <button onClick={() => remove(r)} disabled={busy[r.id]} className="text-ps-hint hover:text-state-problem" aria-label={`Delete ${r.rule_name}`}><X size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
