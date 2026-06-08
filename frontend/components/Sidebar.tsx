"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Health } from "@/lib/types";
import {
  FileText,
  FolderKanban,
  LayoutGrid,
  PenLine,
  Pin,
  Plus,
  Settings,
  ShieldCheck,
} from "@/components/icons";

const NAV = [
  { href: "/", label: "Dashboard", Icon: LayoutGrid, exact: true },
  { href: "/new", label: "New Template", Icon: Plus },
  { href: "/projects", label: "Projects", Icon: FolderKanban },
  { href: "/generate", label: "Generate Document", Icon: PenLine },
  { href: "/compliance", label: "Compliance Check", Icon: ShieldCheck },
  { href: "/settings", label: "Settings", Icon: Settings },
];

const PIN_KEY = "docforge-sidebar-pinned";

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, signOut } = useAuth();
  const [health, setHealth] = useState<Health | null>(null);
  const [pinned, setPinned] = useState(false);

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    try {
      setPinned(localStorage.getItem(PIN_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);

  function togglePin() {
    setPinned((p) => {
      const next = !p;
      try {
        localStorage.setItem(PIN_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");

  return (
    <aside className={`sidebar ${pinned ? "pinned" : ""}`}>
      <div className="brand">
        <span className="mark">
          <FileText size={16} strokeWidth={2} />
        </span>
        <span className="brand-text">
          Doc<b>Forge</b>
        </span>
        <button
          className={`pin-btn ${pinned ? "on" : ""}`}
          onClick={togglePin}
          title={pinned ? "Unpin — collapse to icons" : "Pin sidebar open"}
          aria-pressed={pinned}
        >
          <Pin size={15} strokeWidth={1.9} fill={pinned ? "currentColor" : "none"} />
        </button>
      </div>

      {NAV.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          className={`nav-link ${isActive(n.href, n.exact) ? "active" : ""}`}
          title={n.label}
        >
          <span className="ic">
            <n.Icon size={20} strokeWidth={1.75} />
          </span>
          <span className="label">{n.label}</span>
        </Link>
      ))}

      <div className="sidebar-foot">
        {health ? (
          <>
            <Link href="/settings" style={{ color: "inherit", textDecoration: "none" }}>
              <span className={`dot ${health.ai_active ? "" : "off"}`} />
              {health.ai_active ? `AI: ${health.ai_model}` : "AI off · connect →"}
            </Link>
            <br />
            <span style={{ opacity: 0.7 }}>v{health.version}</span>
          </>
        ) : (
          "connecting…"
        )}

        {user && (
          <div className="user-menu">
            <span className="user-email label" title={user.email ?? undefined}>
              {user.email}
            </span>
            <button className="signout label" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
