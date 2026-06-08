"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { ErrorBox, Spinner } from "@/components/ui";

export default function ProjectsList() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const p = await api.createProject({ name: name.trim(), description: description.trim() || undefined });
      router.push(`/projects/${p.id}`);
    } catch (e: any) {
      setError(String(e.message || e));
      setBusy(false);
    }
  }

  async function remove(p: Project) {
    if (!window.confirm(`Delete project "${p.name}"? Its templates are kept (just unassigned).`)) return;
    try {
      await api.deleteProject(p.id);
      setProjects((prev) => (prev ? prev.filter((x) => x.id !== p.id) : prev));
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  return (
    <div>
      <h1 className="page-title">Projects</h1>
      <p className="page-sub">
        Group templates and define shared metadata that their documents inherit — set a value
        once and every template in the project picks it up at generation.
      </p>

      {error && <ErrorBox message={error} />}

      <form className="card section" onSubmit={create}>
        <h2 className="section-h" style={{ margin: "0 0 12px" }}>
          New project
        </h2>
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ flex: "1 1 220px", margin: 0 }}>
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme Corp" />
          </label>
          <label className="field" style={{ flex: "2 1 320px", margin: 0 }}>
            <span>Description (optional)</span>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this project is for"
            />
          </label>
          <button className="btn" type="submit" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>

      <div className="section">
        <h2 className="section-h" style={{ marginBottom: 14 }}>
          Your projects
        </h2>
        {!projects ? (
          <Spinner label="Loading projects…" />
        ) : projects.length === 0 ? (
          <div className="card empty">No projects yet. Create one above to start grouping templates.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Metadata</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link href={`/projects/${p.id}`}>{p.name}</Link>
                  </td>
                  <td className="muted">{p.description || "—"}</td>
                  <td className="muted">{Object.keys(p.metadata || {}).length} field(s)</td>
                  <td className="muted">{new Date(p.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <button
                        className="btn secondary small"
                        onClick={() => remove(p)}
                        title="Delete project"
                        style={{ color: "var(--red)" }}
                      >
                        🗑
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
