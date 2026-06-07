"use client";

// Client-side gate: shows the login page when signed out, and the full app shell
// (sidebar + main) only when a Supabase session exists.
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <div className="main-inner">{children}</div>
      </main>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { session, loading, configured } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const onLogin = pathname === "/login";

  useEffect(() => {
    if (loading || !configured) return;
    if (!session && !onLogin) router.replace("/login");
    if (session && onLogin) router.replace("/");
  }, [session, loading, configured, onLogin, router]);

  // No Supabase configured -> single-user local mode: skip the gate entirely so
  // the app still works offline (pair with backend DOCFORGE_AUTH_REQUIRED=false).
  if (!configured) {
    if (onLogin) return <>{children}</>;
    return <Shell>{children}</Shell>;
  }

  if (loading) {
    return (
      <div className="auth-splash">
        <span className="mark">D</span>
        <p>Loading…</p>
      </div>
    );
  }

  // The login route renders standalone (no sidebar).
  if (onLogin) return <>{children}</>;

  // Signed out on a protected route: render nothing while the redirect runs.
  if (!session) return null;

  return <Shell>{children}</Shell>;
}
