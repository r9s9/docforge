"use client";

// Client-side gate: shows the login page when signed out, and the full app shell
// (sidebar + main) only when a Supabase session exists.
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";
import TutorialModal from "@/components/TutorialModal";

// Per-account so every new sign-up gets the tour once; ":local" covers the
// no-Supabase single-user mode.
const TUTORIAL_SEEN_PREFIX = "docforge-tutorial-seen";

function Shell({ children, userId }: { children: React.ReactNode; userId: string }) {
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const seenKey = `${TUTORIAL_SEEN_PREFIX}:${userId}`;

  // First sign-in on this browser: open the tour automatically, exactly once.
  useEffect(() => {
    try {
      if (!localStorage.getItem(seenKey)) setTutorialOpen(true);
    } catch {
      /* ignore */
    }
  }, [seenKey]);

  function closeTutorial() {
    setTutorialOpen(false);
    try {
      localStorage.setItem(seenKey, "1");
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="app">
      <div className="aurora" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <Sidebar onOpenTutorial={() => setTutorialOpen(true)} />
      <main className="main">
        <div className="main-inner">{children}</div>
      </main>
      <TutorialModal open={tutorialOpen} onClose={closeTutorial} />
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
    return <Shell userId="local">{children}</Shell>;
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

  return <Shell userId={session.user.id}>{children}</Shell>;
}
