"use client";

/**
 * Price lists, and a default list per customer (accounting-20).
 *
 * A PRICE LIST IS A PRE-FILL SOURCE AND NOTHING ELSE, AND THIS SCREEN SAYS SO. A
 * trading client who quotes a dealer, a retailer and a wholesaler three rates used
 * to remember each one. A list holds a rate per catalogue item and a customer can
 * be put on one; when a catalogue item is picked on a new invoice line for that
 * customer, the line's rate box is pre-filled from the list (see InvoiceEditor).
 * It changes no tax and posts nothing, and an invoice keeps whatever rate it was
 * given.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which rate a line gets, and why, is
 * `domain/sales/price_list.py` through `resolve`; this keeps the lists and the
 * assignments. A typed rate becomes integer paise through `lib/money/rupeeInput`,
 * and every refusal (a zero rate, a duplicate name, an archived list) is the
 * server's own sentence.
 *
 * A LIST IS ARCHIVED, NOT DELETED: a customer pointing at an archived list falls
 * back to the catalogue rate, and the screen says which customers are in that
 * position.
 */
import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Plus, Trash2 } from "lucide-react";
import {
  api,
  type PriceList,
  type PriceListCustomerRow,
  type PriceListItemRow,
} from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";
import { EmptyState } from "@/components/ui/states";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";

type Msg = { type: "ok" | "err"; text: string } | null;

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Something went wrong. Please try again.";
}

export default function PriceListsPanel({
  clientId,
  onAddCustomer,
}: {
  clientId: string;
  /** Opens the Add Customer form. Supplied by the Customers tab, which owns that form: a customer is
   *  made there and this panel only chooses each one's default list, so with no customers the next
   *  step is the tab's own button, not a second form here. */
  onAddCustomer: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [lists, setLists] = useState<PriceList[]>([]);
  const [customers, setCustomers] = useState<PriceListCustomerRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<PriceListItemRow[]>([]);
  const [rowRates, setRowRates] = useState<Record<string, string>>({});

  const [newName, setNewName] = useState("");
  const [renameTo, setRenameTo] = useState("");
  const [pick, setPick] = useState<ServiceCatalogueItem | null>(null);
  const [pickRate, setPickRate] = useState("");

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [l, c] = await Promise.all([
        api.priceLists.list(clientId, true),
        api.priceLists.customers(clientId),
      ]);
      if (l.success && l.data) {
        const loadedLists = objectWithLists<{ price_lists: PriceList[] }>(l.data, "price_lists");
        setLists(loadedLists ? loadedLists.price_lists : []);
      }
      if (c.success && c.data) {
        const loadedCust = objectWithLists<{ customers: PriceListCustomerRow[] }>(c.data, "customers");
        setCustomers(loadedCust ? loadedCust.customers : []);
      }
      setLoaded(true);
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  const loadItems = useCallback(async (listId: string) => {
    try {
      const r = await api.priceLists.items(listId, clientId);
      if (r.success && r.data) {
        const got = objectWithLists<{ price_list: PriceList; items: PriceListItemRow[] }>(r.data, "items");
        const rows = got ? got.items : [];
        setItems(rows);
        const rates: Record<string, string> = {};
        for (const row of rows) rates[row.service_catalogue_id] = rupeeInputFromPaise(row.rate_paise);
        setRowRates(rates);
      }
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    }
  }, [clientId]);

  useEffect(() => {
    if (open && !loaded) void loadAll();
  }, [open, loaded, loadAll]);

  useEffect(() => {
    if (selectedId) void loadItems(selectedId);
    else setItems([]);
  }, [selectedId, loadItems]);

  const selected = lists.find((l) => l.id === selectedId) ?? null;
  const activeLists = lists.filter((l) => l.is_active);

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label);
    setMsg(null);
    try {
      await work();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const createList = () => run("create", async () => {
    const r = await api.priceLists.create(clientId, newName);
    if (!r.success || !r.data) throw new Error(r.error || "The list was not created.");
    setNewName("");
    await loadAll();
    setSelectedId(r.data.id);
    setMsg({ type: "ok", text: "Price list created. Add the items it prices." });
  });

  const rename = () => run("rename", async () => {
    if (!selected) return;
    const r = await api.priceLists.update(selected.id, clientId, { name: renameTo });
    if (!r.success) throw new Error(r.error || "The list was not renamed.");
    setRenameTo("");
    await loadAll();
  });

  const toggleArchive = () => run("archive", async () => {
    if (!selected) return;
    const r = await api.priceLists.update(selected.id, clientId, { is_active: !selected.is_active });
    if (!r.success) throw new Error(r.error || "The list was not changed.");
    await loadAll();
    setMsg({
      type: "ok",
      text: selected.is_active
        ? "List archived. Customers on it are pre-filled from the catalogue rate until you move them."
        : "List restored.",
    });
  });

  const addItem = () => run("add", async () => {
    if (!selected || !pick) return;
    const paise = paiseFromRupeeInput(pickRate);
    if (paise === null || paise <= 0) throw new Error("Enter the price as a rupee amount above zero.");
    const r = await api.priceLists.setItem(selected.id, pick.id, clientId, paise);
    if (!r.success) throw new Error(r.error || "The price was not saved.");
    setPick(null);
    setPickRate("");
    await loadItems(selected.id);
  });

  const saveRow = (row: PriceListItemRow) => run(`row:${row.service_catalogue_id}`, async () => {
    if (!selected) return;
    const paise = paiseFromRupeeInput(rowRates[row.service_catalogue_id] ?? "");
    if (paise === null || paise <= 0) throw new Error("Enter the price as a rupee amount above zero.");
    const r = await api.priceLists.setItem(selected.id, row.service_catalogue_id, clientId, paise);
    if (!r.success) throw new Error(r.error || "The price was not saved.");
    await loadItems(selected.id);
  });

  const removeRow = (row: PriceListItemRow) => run(`rm:${row.service_catalogue_id}`, async () => {
    if (!selected) return;
    const r = await api.priceLists.removeItem(selected.id, row.service_catalogue_id, clientId);
    if (!r.success) throw new Error(r.error || "The item was not removed.");
    await loadItems(selected.id);
  });

  const assign = (customerId: string, listId: string) => run(`assign:${customerId}`, async () => {
    const r = await api.priceLists.assign(clientId, customerId, listId || null);
    if (!r.success) throw new Error(r.error || "The customer's list was not changed.");
    await loadAll();
  });

  const onArchivedList = customers.filter((c) => c.price_list_archived);

  return (
    <div className="rounded-lg border border-ps-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-semibold text-ps-body hover:bg-ps-bg"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Price lists
        <span className="font-normal text-ps-hint">
          — a rate per item for a customer, pre-filled on a new invoice line
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-ps-border p-3">
          <p className="max-w-3xl text-xs text-ps-label">
            A price list only pre-fills the rate when you pick an item on a new invoice line. You
            can change the rate on the line, and the invoice keeps whatever rate it is given: a
            list changes no tax and posts nothing, and no invoice already raised is touched.
          </p>

          {msg && <Callout tone={msg.type === "ok" ? "note" : "problem"}>{msg.text}</Callout>}
          {loading && !loaded && <p className="text-xs text-ps-hint">Reading the price lists…</p>}

          <div className="flex flex-wrap items-end gap-2">
            <label className="text-2xs text-ps-label">
              New price list
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Dealer, Retail, Wholesale…"
                className="mt-0.5 block w-56 rounded-lg border border-ps-border px-2 py-1.5 text-xs"
              />
            </label>
            <button
              type="button"
              onClick={() => void createList()}
              disabled={busy !== null || !newName.trim()}
              className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {busy === "create" ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
              Create
            </button>
            <label className="text-2xs text-ps-label">
              Edit prices on
              <select
                value={selectedId ?? ""}
                onChange={(e) => setSelectedId(e.target.value || null)}
                className="mt-0.5 block rounded-lg border border-ps-border px-2 py-1.5 text-xs"
              >
                <option value="">Choose a list…</option>
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>{l.name}{l.is_active ? "" : " (archived)"}</option>
                ))}
              </select>
            </label>
          </div>

          {selected && (
            <div className="space-y-3 rounded-lg border border-ps-border p-3">
              <div className="flex flex-wrap items-end gap-2">
                <h3 className="text-xs font-semibold text-ps-ink">
                  {selected.name}{selected.is_active ? "" : " — archived"}
                </h3>
                <label className="ml-auto text-2xs text-ps-label">
                  Rename
                  <input
                    value={renameTo}
                    onChange={(e) => setRenameTo(e.target.value)}
                    placeholder={selected.name}
                    className="mt-0.5 block w-44 rounded-lg border border-ps-border px-2 py-1 text-xs"
                  />
                </label>
                <button type="button" onClick={() => void rename()} disabled={busy !== null || !renameTo.trim()}
                  className="rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50">
                  Rename
                </button>
                <button type="button" onClick={() => void toggleArchive()} disabled={busy !== null}
                  className="rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50">
                  {selected.is_active ? "Archive" : "Restore"}
                </button>
              </div>

              <div className="flex flex-wrap items-end gap-2">
                <div className="w-72">
                  <span className="text-2xs text-ps-label">Add an item to this list</span>
                  <ServiceCataloguePicker
                    clientId={clientId}
                    value={pick}
                    onPick={(item) => {
                      setPick(item);
                      setPickRate(item.default_rate_paise ? rupeeInputFromPaise(item.default_rate_paise) : "");
                    }}
                    ariaLabel="Product or service to price"
                    placeholder="Pick a product or service…"
                  />
                </div>
                <label className="text-2xs text-ps-label">
                  Price on this list (₹)
                  <input
                    inputMode="decimal"
                    value={pickRate}
                    onChange={(e) => setPickRate(e.target.value)}
                    className="mt-0.5 block w-32 rounded-lg border border-ps-border px-2 py-1.5 text-right text-xs tabular-nums"
                  />
                </label>
                <button type="button" onClick={() => void addItem()} disabled={busy !== null || !pick}
                  className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50">
                  {busy === "add" && <Loader2 size={12} className="animate-spin" />}
                  Set price
                </button>
              </div>

              {items.length === 0 ? (
                <p className="text-xs text-ps-hint">
                  No item is priced on this list yet. An item with no price here uses the
                  catalogue rate.
                </p>
              ) : (
                <div className="overflow-x-auto rounded border border-ps-border">
                  <table className="w-full text-sm">
                    <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
                      <tr>
                        <th className="px-3 py-2">Item</th>
                        <th className="px-3 py-2">HSN/SAC</th>
                        <th className="px-3 py-2 text-right">Catalogue rate</th>
                        <th className="px-3 py-2 text-right">This list (₹)</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((row) => (
                        <tr key={row.id} className="border-t border-ps-border">
                          <td className="px-3 py-2">{row.name ?? "—"}{row.is_active === false ? " (archived item)" : ""}</td>
                          <td className="px-3 py-2 font-mono text-xs">{row.hsn_sac ?? "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {row.catalogue_rate_paise === null ? "—" : formatPaise(row.catalogue_rate_paise)}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <input
                              inputMode="decimal"
                              value={rowRates[row.service_catalogue_id] ?? ""}
                              onChange={(e) => setRowRates({ ...rowRates, [row.service_catalogue_id]: e.target.value })}
                              aria-label={`Price of ${row.name ?? "item"} on this list`}
                              className="w-28 rounded border border-ps-border px-2 py-1 text-right text-xs tabular-nums"
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className="inline-flex gap-1">
                              <button type="button" onClick={() => void saveRow(row)} disabled={busy !== null}
                                className="rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50">
                                Save
                              </button>
                              <button type="button" onClick={() => void removeRow(row)} disabled={busy !== null}
                                aria-label={`Take ${row.name ?? "item"} off this list`}
                                title="Take it off this list: the catalogue rate applies again"
                                className="rounded-lg border border-ps-border px-2 py-1 text-state-problem hover:bg-ps-bg disabled:opacity-50">
                                <Trash2 size={12} />
                              </button>
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div>
            <h3 className="text-xs font-semibold text-ps-ink">Each customer&apos;s default list</h3>
            {onArchivedList.length > 0 && (
              <Callout tone="attention" className="mt-2">
                {onArchivedList.length === 1
                  ? `${onArchivedList[0].customer_name ?? "A customer"} is on an archived list`
                  : `${onArchivedList.length} customers are on an archived list`}
                {" "}and is pre-filled from the catalogue rate until moved to an active one.
              </Callout>
            )}
            {customers.length === 0 ? (
              <EmptyState
                className="py-6"
                title="No customers yet"
                description="A default price list belongs to a customer. Add this client's customers, then choose each one's list here."
                action={
                  <EmptyStateActions>
                    <EmptyStateAction requires={["client", "write"]} icon={<Plus size={14} />} label="Add Customer"
                      onClick={onAddCustomer} />
                  </EmptyStateActions>
                }
              />
            ) : (
              <div className="mt-2 overflow-x-auto rounded border border-ps-border">
                <table className="w-full text-sm">
                  <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
                    <tr>
                      <th className="px-3 py-2">Customer</th>
                      <th className="px-3 py-2">Default price list</th>
                    </tr>
                  </thead>
                  <tbody>
                    {arrayOrEmpty<PriceListCustomerRow>(customers).map((c) => (
                      <tr key={c.customer_id} className="border-t border-ps-border">
                        <td className="px-3 py-2">
                          {c.customer_name ?? "—"}{c.is_active ? "" : " (inactive)"}
                        </td>
                        <td className="px-3 py-2">
                          <select
                            value={c.price_list_id ?? ""}
                            onChange={(e) => void assign(c.customer_id, e.target.value)}
                            disabled={busy !== null}
                            aria-label={`Default price list for ${c.customer_name ?? "customer"}`}
                            className="rounded-lg border border-ps-border px-2 py-1 text-xs"
                          >
                            <option value="">None — catalogue rate</option>
                            {c.price_list_archived && c.price_list_id && (
                              <option value={c.price_list_id} disabled>
                                {c.price_list_name ?? "Archived list"} (archived)
                              </option>
                            )}
                            {activeLists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
