import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { plainRestFetch } from "./plainRestFetch.ts";

let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;

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

// Convenience singleton — used by AuthContext and api client
export const supabase = {
  auth: {
    getSession: () => getSupabaseClient().auth.getSession(),
    refreshSession: () => getSupabaseClient().auth.refreshSession(),
    onAuthStateChange: (...args: Parameters<SupabaseClient["auth"]["onAuthStateChange"]>) =>
      getSupabaseClient().auth.onAuthStateChange(...args),
    signInWithPassword: (creds: { email: string; password: string }) =>
      getSupabaseClient().auth.signInWithPassword(creds),
    signOut: () => getSupabaseClient().auth.signOut(),
  },
};
