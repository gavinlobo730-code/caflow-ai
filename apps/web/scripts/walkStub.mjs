/**
 * What the smoke walk's stub server knows about ONE client (POST-A-036), as pure functions a plain `node --test`
 * file can exercise.
 *
 * WHY IT EXISTS. Since the client workspace's `ClientResolutionGate` (D28) a screen under `/clients/<uuid>/…` renders
 * only once `clients?id=eq.<uuid>` answers a row; an absent row renders "no such client" and nothing else. The stub
 * answered every PostgREST read it did not know with `[]` (or null for one object), so under `--real-client` every
 * client screen the walk photographed was the refusal, and the axe scan of "a client's sales" was a scan of the
 * refusal. The stub is honest about that, and it is the reason the walk could not see the workspace.
 *
 * WHAT IS ANSWERED, AND WHAT STAYS EMPTY. Only a lookup KEYED ON THE CLIENT (`clients` with `id=eq.<CLIENT_UUID>`)
 * answers the row. Every list read stays empty, deliberately: the no-data state is the one the walk exists to look at
 * (see `serve` in smoke-walk.mjs), and a client list with one row would change what every firm-level screen renders.
 * So this is a row to get past the gate and to give the workspace chrome a name to show; it seeds nothing.
 *
 * THE ROW IS PROJECTED to the columns the caller selected, aliases included (`name:client_name`), because
 * PostgREST answers exactly the selected columns and a screen that selects `name:client_name` reads `.name`.
 */

/** The client every `--real-client` URL names, and the only one the stub knows. */
export const CLIENT_UUID = "00000000-0000-4000-8000-000000000001";

/** A firm id the signed-in user's row carries (smoke-walk.mjs FAKE_USERS_ROW.firm_id). */
export const FIRM_ID = "00000000-0000-4000-8000-0000000000f1";

/** Every column any screen's `clients` lookup by id selects today; a column a screen reads that is not here reads
 *  as absent, which is the empty state, never a crash. The GSTIN is a real check-digit-valid shape. */
export const CLIENT_ROW = {
  id: CLIENT_UUID,
  firm_id: FIRM_ID,
  client_name: "Smoke Client Pvt Ltd",
  entity_type: "Private Limited",
  gstin: "27AAPFU0939F1ZV",
  state_code: "27",
  status: "active",
  is_internal: false,
  gst_advance_tax_applicable: false,
};

/** Split a PostgREST `select=` list on its top-level commas (an embedded `clients(a,b)` is one item). */
export function selectItems(select) {
  const items = [];
  let depth = 0;
  let current = "";
  for (const ch of String(select ?? "")) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (ch === "," && depth === 0) { items.push(current.trim()); current = ""; continue; }
    current += ch;
  }
  if (current.trim()) items.push(current.trim());
  return items;
}

/** The row restricted to the selected columns, with aliases applied. `*` and an empty list answer the whole row;
 *  an embedded resource is left out (the stub has no related rows to put in it). */
export function project(row, select) {
  const items = selectItems(select);
  if (!items.length || items.includes("*")) return { ...row };
  const out = {};
  for (const item of items) {
    if (item.includes("(")) continue;
    const [aliasOrColumn, column] = item.includes(":") ? item.split(":") : [item, item];
    if (column in row) out[aliasOrColumn] = row[column];
  }
  return out;
}

/**
 * The answer to a PostgREST request the stub knows about, or `undefined` for one it does not (the caller then
 * answers its usual empty set). `wantsObject` is the `Accept: application/vnd.pgrst.object+json` of `.single()` /
 * `.maybeSingle()`.
 */
export function knownRead(pathname, query, wantsObject) {
  const table = pathname.replace(/^\/__supabase\/rest\/v1\//, "").split("/")[0];
  if (table !== "clients") return undefined;
  const params = new URLSearchParams(query ?? "");
  if (params.get("id") !== `eq.${CLIENT_UUID}`) return undefined;
  const row = project(CLIENT_ROW, params.get("select"));
  return wantsObject ? row : [row];
}
