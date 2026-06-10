"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AISettings, AIUsage, Health } from "@/lib/types";
import {
  Check,
  FileText,
  FolderKanban,
  GripVertical,
  LayoutGrid,
  type LucideIcon,
  PenLine,
  Pencil,
  Pin,
  Plug,
  Plus,
  Settings,
  ShieldCheck,
} from "@/components/icons";

type NavId =
  | "dashboard"
  | "new"
  | "projects"
  | "generate"
  | "compliance"
  | "connections"
  | "settings";

interface NavDef {
  id: NavId;
  href: string;
  label: string;
  Icon: LucideIcon;
  exact?: boolean;
}

// Static registry: icons + routes never change (only order + labels are editable).
const NAV_REGISTRY: Record<NavId, NavDef> = {
  dashboard: { id: "dashboard", href: "/", label: "Dashboard", Icon: LayoutGrid, exact: true },
  new: { id: "new", href: "/new", label: "New Template", Icon: Plus },
  projects: { id: "projects", href: "/projects", label: "Projects", Icon: FolderKanban },
  generate: { id: "generate", href: "/generate", label: "Generate Document", Icon: PenLine },
  compliance: { id: "compliance", href: "/compliance", label: "Compliance Check", Icon: ShieldCheck },
  connections: { id: "connections", href: "/connections", label: "Connections", Icon: Plug },
  settings: { id: "settings", href: "/settings", label: "Settings", Icon: Settings },
};

const DEFAULT_ORDER: NavId[] = [
  "dashboard",
  "new",
  "projects",
  "generate",
  "compliance",
  "connections",
  "settings",
];

const PIN_KEY = "docforge-sidebar-pinned";
const ORDER_KEY = "docforge-nav-order";
const LABELS_KEY = "docforge-nav-labels";

/** Per-user AI status line: own key > free allowance > global > off. */
function AiStatus({
  ai,
  usage,
  health,
}: {
  ai: AISettings | null;
  usage: AIUsage | null;
  health: Health;
}) {
  if (ai?.active) {
    return (
      <>
        <span className="dot" />
        AI: {ai.model}
      </>
    );
  }
  if (usage?.free_enabled && !usage.has_own_key) {
    const out = usage.free_remaining <= 0;
    return (
      <>
        <span className={`dot ${out ? "off" : ""}`} />
        {out ? "Free AI used up · add key →" : `${usage.free_remaining} free AI actions`}
      </>
    );
  }
  // Fall back to the platform-wide status (legacy shared key / local dev).
  return (
    <>
      <span className={`dot ${health.ai_active ? "" : "off"}`} />
      {health.ai_active ? `AI: ${health.ai_model}` : "AI off · connect →"}
    </>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, signOut } = useAuth();
  const [health, setHealth] = useState<Health | null>(null);
  const [ai, setAi] = useState<AISettings | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [pinned, setPinned] = useState(false);

  // Editable / reorderable navigation state (persisted to localStorage).
  const [order, setOrder] = useState<NavId[]>(DEFAULT_ORDER);
  const [labels, setLabels] = useState<Partial<Record<NavId, string>>>({});
  const [editing, setEditing] = useState(false);
  const [dragId, setDragId] = useState<NavId | null>(null);

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api
      .getAISettings()
      .then(({ ai, usage }) => {
        setAi(ai);
        setUsage(usage);
      })
      .catch(() => {
        /* settings need auth; ignore in local/no-auth mode */
      });
    try {
      setPinned(localStorage.getItem(PIN_KEY) === "1");

      const rawOrder = localStorage.getItem(ORDER_KEY);
      if (rawOrder) {
        const parsed = JSON.parse(rawOrder) as NavId[];
        const known = parsed.filter((id) => id in NAV_REGISTRY);
        // Append any nav items added since the order was saved, so new features
        // never silently disappear from a returning user's menu.
        const merged = [...known, ...DEFAULT_ORDER.filter((id) => !known.includes(id))];
        setOrder(merged);
      }
      const rawLabels = localStorage.getItem(LABELS_KEY);
      if (rawLabels) setLabels(JSON.parse(rawLabels));
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

  function persistOrder(next: NavId[]) {
    setOrder(next);
    try {
      localStorage.setItem(ORDER_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  function persistLabels(next: Partial<Record<NavId, string>>) {
    setLabels(next);
    try {
      localStorage.setItem(LABELS_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  const labelOf = (id: NavId) => labels[id] ?? NAV_REGISTRY[id].label;

  function rename(id: NavId, value: string) {
    const next = { ...labels };
    if (value.trim() && value.trim() !== NAV_REGISTRY[id].label) next[id] = value.trim();
    else delete next[id];
    persistLabels(next);
  }

  function reorder(overId: NavId) {
    if (!dragId || dragId === overId) return;
    const from = order.indexOf(dragId);
    const to = order.indexOf(overId);
    if (from < 0 || to < 0) return;
    const next = [...order];
    next.splice(from, 1);
    next.splice(to, 0, dragId);
    setOrder(next); // live reorder while dragging; persisted on drop
  }

  function resetNav() {
    persistOrder(DEFAULT_ORDER);
    persistLabels({});
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

      <div className="nav-section">
        <div className="nav-section-head">
          <span className="label">Menu</span>
          <button
            className="nav-edit-btn label"
            onClick={() => setEditing((e) => !e)}
            title={editing ? "Done editing" : "Edit & reorder menu"}
          >
            {editing ? <Check size={14} strokeWidth={2.4} /> : <Pencil size={13} strokeWidth={2} />}
          </button>
        </div>

        {order.map((id) => {
          const n = NAV_REGISTRY[id];
          const label = labelOf(id);
          if (editing) {
            return (
              <div
                key={id}
                className={`nav-edit-row ${dragId === id ? "dragging" : ""}`}
                draggable
                onDragStart={() => setDragId(id)}
                onDragOver={(e) => {
                  e.preventDefault();
                  reorder(id);
                }}
                onDrop={() => {
                  persistOrder(order);
                  setDragId(null);
                }}
                onDragEnd={() => setDragId(null)}
              >
                <span className="nav-grip" title="Drag to reorder">
                  <GripVertical size={16} strokeWidth={1.9} />
                </span>
                <span className="ic">
                  <n.Icon size={18} strokeWidth={1.75} />
                </span>
                <input
                  className="nav-edit-input"
                  value={label}
                  onChange={(e) => rename(id, e.target.value)}
                  aria-label={`Rename ${NAV_REGISTRY[id].label}`}
                />
              </div>
            );
          }
          return (
            <Link
              key={id}
              href={n.href}
              className={`nav-link ${isActive(n.href, n.exact) ? "active" : ""}`}
              title={label}
            >
              <span className="ic">
                <n.Icon size={20} strokeWidth={1.75} />
              </span>
              <span className="label">{label}</span>
            </Link>
          );
        })}

        {editing && (
          <button className="nav-reset label" onClick={resetNav}>
            Reset to default
          </button>
        )}
      </div>

      <div className="sidebar-foot">
        {health ? (
          <>
            <Link href="/settings" style={{ color: "inherit", textDecoration: "none" }}>
              <AiStatus ai={ai} usage={usage} health={health} />
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
