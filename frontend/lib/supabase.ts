// Supabase browser client (singleton). Used for email/password auth; the session
// JWT it issues is sent as a Bearer token to the DocForge backend (see api.ts).
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

// `configured` lets the UI show a helpful message instead of crashing when the
// env vars aren't set yet (e.g. a fresh checkout before Supabase is wired up).
export const supabaseConfigured = Boolean(url && anonKey);

export const supabase: SupabaseClient = createClient(
  url || "http://localhost:54321",
  anonKey || "public-anon-key-placeholder",
  { auth: { persistSession: true, autoRefreshToken: true } },
);

/** Current access token (JWT) for the signed-in user, or null. */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
