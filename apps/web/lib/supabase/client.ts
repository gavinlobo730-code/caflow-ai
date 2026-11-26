import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { plainRestFetch } from "./plainRestFetch.ts";
import { rememberRecoveryLink } from "../auth/recoveryLink.ts";

let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;

  // The address is read HERE, before the library is made, because the library reads a recovery link when it starts, stores its session
  // and clears the hash, and the reset page renders after that (lib/auth/recoveryLink.ts says why that matters, POST-A-510).
  if (typeof window !== "undefined") rememberRecoveryLink(window.location, Date.now());

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

  // Provide a no-op client at build time so static generation doesn't crash.
  // Real auth calls only happen in the browser where env vars are populated.
  //
  // The client is given `plainRestFetch`, so a table read or write whose connection drops comes back with the product's sentence as `error.message` and not
  // `TypeError: Failed to fetch` (POST-A-413). It is the ONLY place the browser makes a Supabase client: a second one would not have it.
  _client = createClient(url || "https://placeholder.supabase.co", key || "placeholder", { global: { fetch: plainRestFetch } });
  return _client;
}

/**
 * A client that holds NOTHING, for proving a password and being thrown away (POST-A-512).
 *
 * Settings > Security used to prove the current password with `signInWithPassword` on the browser's own client, which REPLACES the
 * browser's session: the sign-in service announced a new token, the guard rebuilt the page, a person with an authenticator was
 * dropped to the first assurance level and asked for the code again, and the answer to the change arrived at a page that had gone.
 * This client keeps no session in storage, refreshes nothing, reads no address, and has its own storage key so the library does not
 * mistake it for a second copy of the browser's client; what it signs in is signed out again, and the browser's session is the one
 * thing it never touches. It is made HERE because this module is the only place the browser makes a Supabase client (it is given
 * `plainRestFetch` too).
 */
export function makeEphemeralAuthClient(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  return createClient(url || "https://placeholder.supabase.co", key || "placeholder", {
    global: { fetch: plainRestFetch },
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false, storageKey: "ps-password-check" },
  });
}

// Convenience singleton — used by AuthContext and api client
export const supabase = {
  auth: {
    getSession: () => getSupabaseClient().auth.getSession(),
    refreshSession: () => getSupabaseClient().auth.refreshSession(),
    onAuthStateChange: (...args: Parameters<SupabaseClient["auth"]["onAuthStateChange"]>) =>
      getSupabaseClient().auth.onAuthStateChange(...args),
    signInWithPassword: (creds: { email: string; password: string }) =>
      getSupabaseClient().auth.signInWithPassword(creds),
    // `scope: "local"` ends only this device (POST-A-486: the session that asked to sign the others out must survive); left out it is the
    // library's default, every session of the person.
    signOut: (...args: Parameters<SupabaseClient["auth"]["signOut"]>) => getSupabaseClient().auth.signOut(...args),
  },
};
