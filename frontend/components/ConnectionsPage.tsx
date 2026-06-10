"use client";

import {
  Boxes,
  Cloud,
  HardDrive,
  type LucideIcon,
  MessageSquare,
  Share2,
  StickyNote,
  Users,
} from "@/components/icons";

interface Connection {
  id: string;
  name: string;
  desc: string;
  Icon: LucideIcon;
}

const GROUPS: { title: string; blurb: string; items: Connection[] }[] = [
  {
    title: "Microsoft 365",
    blurb: "Bring DocForge into the Microsoft tools your team already lives in.",
    items: [
      {
        id: "sharepoint",
        name: "SharePoint",
        desc: "Pull source files and publish generated documents to SharePoint sites and libraries.",
        Icon: Share2,
      },
      {
        id: "teams",
        name: "Microsoft Teams",
        desc: "Generate and share documents straight into your Teams channels and chats.",
        Icon: Users,
      },
      {
        id: "onedrive",
        name: "OneDrive",
        desc: "Read examples from and save finished documents back to OneDrive.",
        Icon: Cloud,
      },
    ],
  },
  {
    title: "Other services",
    blurb: "Connect the rest of your stack for import, export, and delivery.",
    items: [
      {
        id: "google-drive",
        name: "Google Drive",
        desc: "Import templates and export generated documents with Google Drive.",
        Icon: HardDrive,
      },
      {
        id: "dropbox",
        name: "Dropbox",
        desc: "Sync templates and generated files with your Dropbox folders.",
        Icon: Boxes,
      },
      {
        id: "slack",
        name: "Slack",
        desc: "Deliver finished documents to Slack channels and direct messages.",
        Icon: MessageSquare,
      },
      {
        id: "notion",
        name: "Notion",
        desc: "Send generated content to Notion pages and databases.",
        Icon: StickyNote,
      },
    ],
  },
];

export default function ConnectionsPage() {
  return (
    <div>
      <h1 className="page-title">Connections</h1>
      <p className="page-sub">
        Connect DocForge to the tools you already use. These integrations are on the way — check
        back soon.
      </p>

      {GROUPS.map((g) => (
        <div className="section" key={g.title}>
          <h2 className="section-h">{g.title}</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {g.blurb}
          </p>
          <div className="conn-grid">
            {g.items.map((c) => (
              <div className="card conn-card" key={c.id}>
                <div className="conn-card-head">
                  <span className="conn-ic">
                    <c.Icon size={22} strokeWidth={1.8} />
                  </span>
                  <span className="badge soon">Coming soon</span>
                </div>
                <div className="conn-name">{c.name}</div>
                <div className="conn-desc muted">{c.desc}</div>
                <button className="btn secondary" disabled style={{ marginTop: 14 }}>
                  Connect
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
