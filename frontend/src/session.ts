import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL?.trim();
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

// Null when the backend runs without Supabase (single local member, no sign-in).
const supabase = url && key ? createClient(url, key) : null;

let signingIn: Promise<string> | null = null;

function signInAnonymously(): Promise<string> {
  // Parallel first requests must share one anonymous user, not create several.
  signingIn ??= (async () => {
    const { data, error } = await supabase!.auth.signInAnonymously();
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
  if (!supabase) return null;
  // getSession refreshes an expired token when the saved refresh token allows.
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? signInAnonymously();
}

/**
 * Recover from a token the backend rejected. Renewing keeps the same anonymous
 * user and their saved data; only a session that can't be renewed is dropped.
 */
export async function resetSession(): Promise<void> {
  if (!supabase) return;
  const { error } = await supabase.auth.refreshSession();
  if (error) await supabase.auth.signOut({ scope: "local" });
}

export const sessionsEnabled = supabase !== null;
