"use client";

// First-run tutorial: a tabbed tour of every section of the app. Auto-opened by
// AppShell on a user's first sign-in and reopenable from the ? button in the
// sidebar footer. All illustrations are CSS mini-mockups of the real UI so they
// follow the active theme and never go stale like screenshots would.
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderKanban,
  KeyRound,
  Lightbulb,
  type LucideIcon,
  PenLine,
  Plus,
  ShieldCheck,
  Sparkles,
  X,
} from "@/components/icons";

/* ---- CSS mini-mockups ---- */

function MockCoreLoop() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-loop">
        <div className="tut-loop-step">
          <b>1 · Upload</b>
          <span>Finished .docx examples</span>
        </div>
        <ArrowRight size={14} className="tut-loop-arrow" />
        <div className="tut-loop-step">
          <b>2 · Template</b>
          <span>AI finds the fillable parts</span>
        </div>
        <ArrowRight size={14} className="tut-loop-arrow" />
        <div className="tut-loop-step">
          <b>3 · Generate</b>
          <span>New documents in seconds</span>
        </div>
      </div>
      <figcaption>The core loop — everything in DocForge serves one of these steps.</figcaption>
    </figure>
  );
}

function MockModeCards() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-mock-cards">
        <div className="tut-mock-card active">
          <b>Full template</b>
          <span>Every text becomes a fillable tag — headings, paragraphs, tables. New documents get 100% new text.</span>
        </div>
        <div className="tut-mock-card">
          <b>Smart detect</b>
          <span>Keeps boilerplate fixed; only the parts that vary between documents become fields.</span>
        </div>
      </div>
      <figcaption>The analysis mode selector on the upload step.</figcaption>
    </figure>
  );
}

function MockProgress() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock">
        <div className="tut-mock-progress-head">
          <span>AI naming fields… batch 2/3</span>
          <b>64%</b>
        </div>
        <div className="tut-mock-track">
          <i style={{ width: "64%" }} />
        </div>
        <div className="tut-mock-steps">
          <span className="done">✓ Understand</span>
          <span className="done">✓ Classify</span>
          <span className="current">● Verify</span>
          <span>· Describe</span>
        </div>
      </div>
      <figcaption>Live analysis phases — you always see what the AI is doing.</figcaption>
    </figure>
  );
}

function MockFieldCard() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-mock-field">
        <div className="tut-mock-field-head">
          <code className="tut-mock-name">client_name</code>
          <span className="tut-badge">text</span>
          <span className="tut-conf" title="confidence">
            <i style={{ width: "82%" }} />
          </span>
        </div>
        <span className="tut-mock-desc">
          Full legal name of the client this agreement is prepared for.
        </span>
      </div>
      <figcaption>
        A field card — name, type, AI confidence, and a description of what belongs there.
      </figcaption>
    </figure>
  );
}

function MockInputModes() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-mock-seg">
        <span>Form</span>
        <span className="active">Raw text</span>
        <span>Document</span>
        <span>JSON</span>
      </div>
      <figcaption>Four ways to fill a template on the Generate page.</figcaption>
    </figure>
  );
}

function MockCompliance() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-mock-cols">
        <div className="tut-mock-doc">
          <i className="tut-mock-line w80" />
          <i className="tut-mock-line" />
          <i className="tut-mock-line hl" />
          <i className="tut-mock-line w60" />
        </div>
        <div className="tut-mock-doc tut-mock-score">
          <b>87%</b>
          <span>2 differences</span>
        </div>
        <div className="tut-mock-doc">
          <i className="tut-mock-line w80" />
          <i className="tut-mock-line" />
          <i className="tut-mock-line hl-sel" />
          <i className="tut-mock-line w60" />
        </div>
      </div>
      <figcaption>
        Template and document side by side — differences highlighted, selected one in red.
      </figcaption>
    </figure>
  );
}

function MockAISettings() {
  return (
    <figure className="tut-figure">
      <div className="tut-mock tut-mock-rows">
        <div className="tut-mock-row">
          <span>Provider</span>
          <b>Gemini</b>
        </div>
        <div className="tut-mock-row">
          <span>Model · everyday work</span>
          <b>gemini-2.5-flash-lite</b>
        </div>
        <div className="tut-mock-row">
          <span>Reasoning model · hard steps</span>
          <b>gemini-2.5-flash</b>
        </div>
        <div className="tut-mock-row">
          <span>API key</span>
          <b>••••••••</b>
          <span className="tut-chip-ok">✓ Connected</span>
        </div>
      </div>
      <figcaption>Settings → LLM Settings after a one-click “Use recommended” setup.</figcaption>
    </figure>
  );
}

/* ---- Tab content ---- */

interface TutTab {
  id: string;
  label: string;
  Icon: LucideIcon;
  render: () => React.ReactNode;
}

const TABS: TutTab[] = [
  {
    id: "welcome",
    label: "Welcome",
    Icon: Sparkles,
    render: () => (
      <>
        <h3>Turn finished documents into reusable templates</h3>
        <p>
          DocForge reverse-engineers your existing Word files. Upload a finished .docx, and the AI
          works out which parts are fixed structure and which parts are content that changes every
          time — giving you a reusable template with fillable fields. From then on, new documents
          take seconds instead of an afternoon of copy-paste-and-hope.
        </p>
        <MockCoreLoop />
        <p className="tut-lead">The sections in the sidebar, top to bottom:</p>
        <ul className="tut-list">
          <li><b>Dashboard</b> — your templates at a glance, plus quick actions.</li>
          <li><b>New Template</b> — build a template from example documents.</li>
          <li><b>Projects</b> — group templates and share metadata between them.</li>
          <li><b>Generate Document</b> — fill a template and download the result.</li>
          <li><b>Compliance Check</b> — verify a document against its template.</li>
          <li><b>Connections</b> — integrations (SharePoint, Drive…), coming soon.</li>
          <li><b>Settings</b> — AI configuration, server logs, and your profile.</li>
        </ul>
      </>
    ),
  },
  {
    id: "new-template",
    label: "New Template",
    Icon: Plus,
    render: () => (
      <>
        <h3>From example documents to a published template</h3>
        <ol className="tut-list">
          <li>
            <b>Upload 1–5 finished .docx files.</b> One is enough; more examples of the same
            document type help the AI see what varies between them.
          </li>
          <li>
            <b>Pick an analysis mode.</b>
          </li>
        </ol>
        <MockModeCards />
        <ol className="tut-list" start={3}>
          <li>
            <b>Watch the AI work.</b> Analysis runs in phases — it reads the whole document first,
            then names each field, then double-checks its own work.
          </li>
        </ol>
        <MockProgress />
        <ol className="tut-list" start={4}>
          <li>
            <b>Review the result.</b> A live preview of your document sits next to the detected
            field cards. Expand a card to edit its name, description, or type; exclude fields you
            don’t want. Switch the preview between <b>Filled</b> (example text) and <b>Tags</b>{" "}
            (raw placeholders). Spotted fixed text that should be fillable? Click it right in the
            preview to promote it into a field.
          </li>
        </ol>
        <MockFieldCard />
        <ol className="tut-list" start={5}>
          <li>
            <b>Name it and publish.</b> Optionally assign it to a project — then it’s ready on the
            Generate page.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: "generate",
    label: "Generate",
    Icon: PenLine,
    render: () => (
      <>
        <h3>Fill a template, download a document</h3>
        <p>Pick a template, then choose how you want to provide the content:</p>
        <MockInputModes />
        <ul className="tut-list">
          <li>
            <b>Form</b> — one input per field: text boxes, checkboxes, dropdowns, image uploads,
            and editable tables.
          </li>
          <li>
            <b>Raw text</b> — paste unstructured notes, meeting minutes, an email thread… The AI
            reads each field’s description and places the right piece of your text into the right
            field, drafting anything that’s missing.
          </li>
          <li>
            <b>Document</b> — upload a .docx and the AI extracts the content from it.
          </li>
          <li>
            <b>JSON</b> — paste exact values if you already have structured data.
          </li>
        </ul>
        <p>
          After AI routing, the form is pre-filled so you can review and adjust before generating.
          Hit <b>Generate</b> to download the finished .docx — a small line shows exactly how many
          tokens the AI used and the estimated cost. In Full-template documents, fields you leave
          empty are removed from the output entirely, so nothing ships half-filled.
        </p>
      </>
    ),
  },
  {
    id: "projects",
    label: "Projects",
    Icon: FolderKanban,
    render: () => (
      <>
        <h3>Projects group templates — and remember the boring parts</h3>
        <p>
          A project holds related templates and <b>shared metadata</b>: company name, address,
          registration numbers — anything that’s the same across all its documents. Set a value
          once on the project and every template in it inherits it automatically at generation
          time.
        </p>
        <h3>Each template keeps its full history</h3>
        <p>
          Open any template from the Dashboard to see its fields, validation rules, sections, and
          the original source documents it was built from. Editing fields publishes a{" "}
          <b>new version</b> — earlier versions stay intact, so documents already generated from
          them remain reproducible and nothing is ever silently changed underneath you.
        </p>
      </>
    ),
  },
  {
    id: "compliance",
    label: "Compliance",
    Icon: ShieldCheck,
    render: () => (
      <>
        <h3>Check documents that come back to you</h3>
        <p>
          Someone edited a generated contract and sent it back? Pick the template it came from,
          upload their document, and DocForge compares the two: you get a compliance score and a
          side-by-side view with every difference highlighted.
        </p>
        <MockCompliance />
        <p>
          Differences in <b>fillable fields</b> are expected — that’s content. Differences in the{" "}
          <b>fixed boilerplate</b> are the ones that matter, and <b>Auto-fix</b> repairs them in
          one click: it downloads a corrected .docx with the template’s boilerplate restored and
          the sender’s content left untouched.
        </p>
      </>
    ),
  },
  {
    id: "ai",
    label: "AI Settings",
    Icon: KeyRound,
    render: () => (
      <>
        <h3>Connect the AI (Settings → LLM Settings)</h3>
        <p>
          The AI does the heavy lifting — reading documents, naming fields, writing descriptions,
          routing your raw notes. It needs a provider and an API key:
        </p>
        <MockAISettings />
        <ul className="tut-list">
          <li>
            <b>Provider</b> — OpenAI, Anthropic, Gemini, DeepSeek, or a local model (e.g. Ollama).
            Your key is stored for your account only. No key yet? A small free allowance lets you
            try everything first.
          </li>
          <li>
            <b>Two models</b> — a fast <b>workhorse</b> for everyday extraction and a{" "}
            <b>reasoning</b> model for the hardest steps (verification, tricky placement). The{" "}
            <b>Use recommended</b> button configures a proven cheap-and-good pair in one click.
          </li>
          <li>
            <b>Test</b> — checks your key and model actually respond before you rely on them.
          </li>
          <li>
            <b>AI toggle</b> — with AI off, a built-in heuristic still analyzes documents; it
            works, but it’s far less accurate. The sidebar’s status line always shows which one is
            active.
          </li>
        </ul>
        <p>
          The other Settings tabs: <b>Logs</b> streams live server logs (handy when something looks
          stuck), and <b>Profile</b> handles password changes and account deletion.
        </p>
      </>
    ),
  },
  {
    id: "tips",
    label: "Tips",
    Icon: Lightbulb,
    render: () => (
      <>
        <h3>Small things that make it nicer</h3>
        <ul className="tut-list">
          <li>
            <b>Make the sidebar yours.</b> Pin it open with the pin button; hit the pencil next to
            “Menu” to rename entries or drag them into your preferred order.
          </li>
          <li>
            <b>Theme.</b> The light/dark switch lives at the bottom of the sidebar — and this
            tutorial is always one click away via the <b>?</b> button beside it.
          </li>
          <li>
            <b>Field cards.</b> “Expand all / Collapse all” on review and generate pages is
            remembered between visits.
          </li>
          <li>
            <b>Costs stay visible.</b> Every AI action reports its token usage and estimated cost,
            so there are no surprises on your provider bill.
          </li>
          <li>
            <b>Better templates come from better examples.</b> Upload documents that are fully
            filled in — the AI learns field names and descriptions from the real content.
          </li>
        </ul>
      </>
    ),
  },
];

/* ---- Modal ---- */

export default function TutorialModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Fresh start each time it opens; focus lands on the close button.
  useEffect(() => {
    if (!open) return;
    setTab(0);
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  function goTo(i: number) {
    setTab(i);
    bodyRef.current?.scrollTo({ top: 0 });
  }

  if (!open) return null;

  const last = tab === TABS.length - 1;
  const active = TABS[tab];

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal tut-modal" role="dialog" aria-modal="true" aria-label="DocForge tutorial">
        <div className="tut-head">
          <div>
            <h2>Welcome to DocForge</h2>
            <p className="sub">A two-minute tour — skip anytime, reopen from the ? in the sidebar.</p>
          </div>
          <button ref={closeRef} className="modal-close" onClick={onClose} aria-label="Close tutorial">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        <div className="tut-tabs" role="tablist">
          {TABS.map((t, i) => (
            <button
              key={t.id}
              className={`tut-tab ${i === tab ? "active" : ""}`}
              onClick={() => goTo(i)}
              role="tab"
              aria-selected={i === tab}
            >
              <t.Icon size={13} strokeWidth={2} />
              {t.label}
            </button>
          ))}
        </div>

        <div className="tut-body" ref={bodyRef}>
          {active.render()}
        </div>

        <div className="tut-foot">
          <button className="tut-skip" onClick={onClose}>
            Skip tour
          </button>
          <div className="tut-dots">
            {TABS.map((t, i) => (
              <button
                key={t.id}
                className={`tut-dot ${i === tab ? "active" : ""}`}
                onClick={() => goTo(i)}
                aria-label={`Go to ${t.label}`}
              />
            ))}
          </div>
          <div className="tut-nav">
            {tab > 0 && (
              <button className="btn secondary small" onClick={() => goTo(tab - 1)}>
                <ArrowLeft size={13} strokeWidth={2.2} /> Back
              </button>
            )}
            {last ? (
              <button className="btn small" onClick={onClose}>
                <Check size={13} strokeWidth={2.4} /> Get started
              </button>
            ) : (
              <button className="btn small" onClick={() => goTo(tab + 1)}>
                Next <ArrowRight size={13} strokeWidth={2.2} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
