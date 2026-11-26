// The platform administration site (POST-B-351). One page, no framework and no library: it signs in against the
// sign-in service's own HTTP interface and calls the API's platform routes, and nothing else.
//
// WHAT IT KEEPS: the session token in this page's memory and nowhere else (no cookie, no browser storage), so closing or
// reloading the tab signs out, and every visit needs the password AND the authenticator code (lock 4). Fifteen minutes
// without a click or a key also signs out. Text from the server is put on the page as text, never as markup.
//
// THE LOCKS ARE THE SERVER'S: this page cannot grant anything. The platform list, the second factor, the fresh code before
// a destructive action, the "belongs to no firm" rule and the mail on every sign-in and action are all asked by the API
// (core/platform_auth.py, services/platform_notice.py). What this page adds is asking for a code before each destructive
// action, so that the server's five-minute rule is always met.

const CFG = window.PLATFORM_CONFIG || {};
const IDLE_MS = 15 * 60 * 1000;
const IST = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
const ACTION_WORDS = {
  platform_sign_in: "Signed in to these pages",
  platform_suspend: "Suspended a firm",
  platform_unsuspend: "Reopened a firm",
  platform_delete: "Deleted a firm (records kept)",
  platform_purge: "Permanently deleted a firm",
  platform_firmless_rule_on: "An account that belongs to no firm was listed: accounts that belong to a firm are refused from now on",
};

let session = null; // { token, factorId, email }
let idleTimer = null;

const $ = (id) => document.getElementById(id);

function show(step) {
  for (const id of ["step-password", "step-code", "console"]) $(id).hidden = id !== step;
  $("sign-out").hidden = step !== "console";
}

function say(text) { $("notice").textContent = text || ""; }
function fail(text) { $("error").textContent = text || ""; }

function when(stamp) {
  if (!stamp) return "—";
  const d = new Date(stamp);
  return Number.isNaN(d.getTime()) ? "—" : IST.format(d);
}

function cell(row, text) {
  const td = document.createElement("td");
  td.textContent = text === null || text === undefined || text === "" ? "—" : String(text);
  row.appendChild(td);
  return td;
}

// ── the sign-in service ─────────────────────────────────────────────────────────────────────────────────────────────
async function auth(path, { method = "GET", body, token } = {}) {
  const res = await fetch(`${CFG.supabaseUrl}/auth/v1${path}`, {
    method,
    headers: {
      apikey: CFG.supabaseAnonKey,
      Authorization: `Bearer ${token || CFG.supabaseAnonKey}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "omit",
  });
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) {
    const words = data.msg || data.error_description || data.message || "";
    throw new Error(words ? `The sign-in service refused: ${words}` : `The sign-in service refused (HTTP ${res.status}).`);
  }
  return data;
}

async function verifyCode(code) {
  if (!/^[0-9]{6}$/.test(code || "")) throw new Error("The authenticator code is six digits.");
  const challenge = await auth(`/factors/${session.factorId}/challenge`, { method: "POST", token: session.token, body: {} });
  const verified = await auth(`/factors/${session.factorId}/verify`, {
    method: "POST", token: session.token, body: { challenge_id: challenge.id, code },
  });
  if (!verified.access_token) throw new Error("The sign-in service did not return a session after the code.");
  session.token = verified.access_token;
}

// ── the API ─────────────────────────────────────────────────────────────────────────────────────────────────────────
async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`${CFG.apiUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${session.token}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "omit",
  });
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (res.status === 401 || res.status === 404 && path === "/api/platform/stats") {
    signOut("This session is not accepted for the platform pages. Sign in again.");
    throw new Error("signed out");
  }
  if (!res.ok || data.success === false) {
    throw new Error(data.detail || data.error || `The server refused (HTTP ${res.status}).`);
  }
  return data.data;
}

// ── the console ─────────────────────────────────────────────────────────────────────────────────────────────────────
async function load() {
  const [stats, firms, activity] = await Promise.all([api("/api/platform/stats"), api("/api/platform/firms"), api("/api/platform/activity")]);
  const dl = $("stats");
  dl.replaceChildren();
  for (const [label, key] of [["Firms", "total_firms"], ["Active", "active_firms"], ["Suspended", "suspended_firms"],
    ["People", "total_users"], ["Clients", "total_clients"]]) {
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = stats && stats[key] !== undefined ? String(stats[key]) : "—";
    dl.append(dt, dd);
  }
  const body = $("firms");
  body.replaceChildren();
  for (const f of firms || []) {
    const row = document.createElement("tr");
    cell(row, f.name); cell(row, when(f.created_at)); cell(row, f.users); cell(row, f.clients); cell(row, f.status);
    const actions = cell(row, "");
    actions.textContent = "";
    const button = (label, fn) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.addEventListener("click", () => run(b, () => fn(f)));
      actions.appendChild(b);
    };
    button("People", showPeople);
    if (f.status === "active") button("Suspend", suspend);
    if (f.status === "suspended") button("Reopen", reopen);
    if (f.status !== "deleted") button("Delete", softDelete);
    button("Delete permanently", purge);
    body.appendChild(row);
  }
  const log = $("activity");
  log.replaceChildren();
  for (const a of activity || []) {
    const row = document.createElement("tr");
    cell(row, when(a.at)); cell(row, ACTION_WORDS[a.action] || a.action); cell(row, a.firm_name); cell(row, a.by);
    cell(row, a.address);
    log.appendChild(row);
  }
}

async function run(button, fn) {
  if (button.disabled) return;
  button.disabled = true;
  fail(""); say("");
  try { await fn(); } catch (e) { if (e.message !== "signed out" && e.message !== "cancelled") fail(e.message); }
  finally { button.disabled = false; }
}

async function showPeople(f) {
  const people = await api(`/api/platform/firms/${encodeURIComponent(f.id)}/users`);
  $("people-title").textContent = `People in ${f.name}`;
  const rows = $("people-rows");
  rows.replaceChildren();
  for (const p of people || []) {
    const row = document.createElement("tr");
    cell(row, p.name); cell(row, p.email); cell(row, p.role); cell(row, p.status);
    rows.appendChild(row);
  }
  $("people").hidden = false;
}

function confirmAction({ title, text, go, reason = false, typedName = null }) {
  return new Promise((resolve) => {
    const dialog = $("confirm");
    $("confirm-title").textContent = title;
    $("confirm-text").textContent = text;
    $("confirm-go").textContent = go;
    $("confirm-reason-label").hidden = !reason;
    $("confirm-name-label").hidden = typedName === null;
    for (const id of ["confirm-reason", "confirm-name", "confirm-code"]) $(id).value = "";
    $("confirm-error").textContent = "";
    const done = (value) => { if (dialog.open) dialog.close(); resolve(value); };
    $("confirm-cancel").onclick = () => done(null);
    // Escape closes a modal dialog without a click: it is a cancel, or the action's button would stay disabled.
    dialog.oncancel = () => resolve(null);
    $("confirm-form").onsubmit = (event) => {
      event.preventDefault();
      const answer = { reason: $("confirm-reason").value.trim(), code: $("confirm-code").value.trim() };
      // Said inside the dialog: the page's own message line sits behind it.
      if (reason && !answer.reason) { $("confirm-error").textContent = "A reason is required."; return; }
      if (typedName !== null && $("confirm-name").value !== typedName) {
        $("confirm-error").textContent = "The name typed is not the firm's name exactly.";
        return;
      }
      done(answer);
    };
    dialog.showModal();
  });
}

async function withCode(answer, fn) {
  if (!answer) throw new Error("cancelled");
  await verifyCode(answer.code);
  return fn();
}

async function suspend(f) {
  const answer = await confirmAction({ title: `Suspend ${f.name}?`, go: "Suspend", reason: true,
    text: "Everyone in the firm is signed out and cannot sign in until it is reopened." });
  const r = await withCode(answer, () => api(`/api/platform/firms/${encodeURIComponent(f.id)}/suspend`, { method: "POST", body: { reason: answer.reason } }));
  say(`${f.name} was suspended; ${r.sessions_ended} people were signed out.`);
  await load();
}

async function reopen(f) {
  await api(`/api/platform/firms/${encodeURIComponent(f.id)}/unsuspend`, { method: "POST" });
  say(`${f.name} was reopened. Its people sign in again.`);
  await load();
}

async function softDelete(f) {
  const answer = await confirmAction({ title: `Delete ${f.name}?`, go: "Delete",
    text: "The firm is closed and its people are signed out. Its records are kept." });
  const r = await withCode(answer, () => api(`/api/platform/firms/${encodeURIComponent(f.id)}`, { method: "DELETE" }));
  say(`${f.name} was deleted; ${r.sessions_ended} people were signed out. Its records are kept.`);
  await load();
}

async function purge(f) {
  const answer = await confirmAction({ title: `Permanently delete ${f.name}?`, go: "Delete permanently", typedName: f.name,
    text: "This removes the firm and all of its data and cannot be undone. The database has no daily backup." });
  await withCode(answer, () => api(`/api/platform/firms/${encodeURIComponent(f.id)}/permanent`, { method: "DELETE" }));
  say(`${f.name} was permanently deleted.`);
  $("people").hidden = true;
  await load();
}

// ── a first authenticator, for the dedicated account that belongs to no firm and so never sees the product's settings ──
// Offered only to an account the server says is on the platform list (GET /api/platform/me answers that without the
// second factor and is not a platform visit). The secret is shown as text to type into an authenticator app: a picture
// of it would need the page to accept data: images, which its Content-Security-Policy does not.
async function enrol() {
  const res = await fetch(`${CFG.apiUrl}/api/platform/me`, { headers: { Authorization: `Bearer ${session.token}` }, credentials: "omit" });
  let me = {};
  try { me = (await res.json()).data || {}; } catch { me = {}; }
  if (!res.ok || !me.is_platform_admin) {
    signOut("This account is not on the platform list.");
    return;
  }
  const created = await auth("/factors", { method: "POST", token: session.token,
    body: { factor_type: "totp", friendly_name: `platform ${new Date().toISOString()}` } });
  session.factorId = created.id;
  $("enrol-secret").textContent = ((created.totp && created.totp.secret) || "").replace(/(.{4})/g, "$1 ").trim();
  $("enrol-hint").hidden = false;
  show("step-code");
  $("code").focus();
}

// ── signing in and out ──────────────────────────────────────────────────────────────────────────────────────────────
function signOut(reason) {
  const token = session && session.token;
  session = null;
  clearTimeout(idleTimer);
  for (const id of ["firms", "people-rows", "activity", "stats"]) $(id).replaceChildren();
  $("people").hidden = true;
  // scope=local: only this session ends, so an account that is also used elsewhere is not signed out there.
  if (token) auth("/logout?scope=local", { method: "POST", token }).catch(() => {});
  show("step-password");
  say(reason || "Signed out.");
}

function touch() {
  if (!session) return;
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => signOut("Signed out after fifteen minutes without activity."), IDLE_MS);
}

function start() {
  if (!CFG.apiUrl || !CFG.supabaseUrl || !CFG.supabaseAnonKey) {
    fail("This site was built without its settings, so it cannot sign anybody in.");
    return;
  }
  show("step-password");
  for (const kind of ["click", "keydown"]) document.addEventListener(kind, touch);
  $("sign-out").addEventListener("click", () => signOut());

  $("password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    fail(""); say("");
    const button = event.submitter;
    if (button) button.disabled = true;
    try {
      const email = $("email").value.trim();
      const signedIn = await auth("/token?grant_type=password", { method: "POST", body: { email, password: $("password").value } });
      $("password").value = "";
      const user = await auth("/user", { token: signedIn.access_token });
      const factor = (user.factors || []).find((x) => x.factor_type === "totp" && x.status === "verified");
      session = { token: signedIn.access_token, factorId: factor ? factor.id : null, email };
      if (!factor) {
        await enrol();
        return;
      }
      show("step-code");
      $("code").focus();
    } catch (e) {
      fail(e.message);
    } finally {
      if (button) button.disabled = false;
    }
  });

  $("code-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    fail("");
    const button = event.submitter;
    if (button) button.disabled = true;
    try {
      await verifyCode($("code").value.trim());
      $("code").value = "";
      $("enrol-hint").hidden = true;
      $("enrol-secret").textContent = "";
      show("console");
      touch();
      await load();
    } catch (e) {
      if (e.message !== "signed out") fail(e.message);
    } finally {
      if (button) button.disabled = false;
    }
  });
}

start();
