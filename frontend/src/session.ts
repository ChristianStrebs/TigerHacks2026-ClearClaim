import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { API_BASE_URL } from "./apiBase";
import type { HealthResponse } from "./types";

const UNREACHABLE =
  "Cannot reach the backend. Check that FastAPI is running and the API address is correct.";

// The backend owns the Supabase settings, so the web app can never disagree with it.
// Null when the backend runs without Supabase (single local member, no sign-in).
let client: Promise<SupabaseClient | null> | null = null;

function supabaseClient(): Promise<SupabaseClient | null> {
  client ??= (async () => {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) throw new Error(UNREACHABLE);
    const health = (await response.json()) as HealthResponse;
    const url = health.supabase_url;
    const key = health.supabase_publishable_key;
    return url && key ? createClient(url, key) : null;
  })().catch(() => {
    client = null;
    throw new Error(UNREACHABLE);
  });
  return client;
}

let signingIn: Promise<string> | null = null;

function signInAnonymously(supabase: SupabaseClient): Promise<string> {
  // Parallel first requests must share one anonymous user, not create several.
  signingIn ??= (async () => {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error || !data.session)
      throw new Error(
        "We couldn't start your private session. Refresh the page to try again.",
      );
    return data.session.access_token;
  })().finally(() => {
    signingIn = null;
  });
  return signingIn;
}

/** The visitor's access token, signing them in anonymously on first use. */
export async function accessToken(): Promise<string | null> {
  const supabase = await supabaseClient();
  if (!supabase) return null;
  // getSession refreshes an expired token when the saved refresh token allows.
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? signInAnonymously(supabase);
}

/**
 * Recover from a token the backend rejected. Renewing keeps the same anonymous
 * user and their saved data; only a session that can't be renewed is dropped.
 * Resolves true when sessions are in use, so the request is worth retrying.
 */
export async function resetSession(): Promise<boolean> {
  const supabase = await supabaseClient();
  if (!supabase) return false;
  const { error } = await supabase.auth.refreshSession();
  if (error) await supabase.auth.signOut({ scope: "local" });
  return true;
}
