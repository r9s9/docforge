"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";

const NAV = [
  { href: "/", label: "Dashboard", icon: "◧", exact: true },
  { href: "/new", label: "New Template", icon: "＋" },
  { href: "/generate", label: "Generate Document", icon: "✎" },
  { href: "/compliance", label: "Compliance Check", icon: "✓" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/") || pathname === href;

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="mark">D</span>
        <span>
          Doc<b>Forge</b>
        </span>
      </div>

      {NAV.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          className={`nav-link ${isActive(n.href, n.exact) ? "active" : ""}`}
        >
          <span className="ic">{n.icon}</span>
          {n.label}
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
            <span style={{ opacity: 0.7 }}>v{health.version} · local-first</span>
          </>
        ) : (
          "connecting…"
        )}
      </div>
    </aside>
  );
}
