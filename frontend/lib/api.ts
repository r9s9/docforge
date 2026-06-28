// Thin fetch wrapper around the DocForge REST API.
//
// Same-origin by default (/api is proxied to the backend via next.config.mjs).
// For a split deployment set NEXT_PUBLIC_API_BASE_URL to the backend origin and
// the browser will call it directly.
import type {
  AISettingsResponse,
  AnalysisJob,
  LogEntry,
  ComplianceReport,
  GenerationResult,
  Health,
  PreviewResult,
  Project,
  ProjectDetail,
  RouteDocumentResult,
  RoutingResult,
  Template,
  TemplateDetail,
  ValidationReport,
  VersionDetail,
} from "./types";

import { getAccessToken } from "./supabase";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const BASE = `${API_ORIGIN}/api`;

/** Merge the signed-in user's Bearer token into request headers. */
async function withAuth(headers?: HeadersInit): Promise<Headers> {
  const h = new Headers(headers);
  const token = await getAccessToken();
  if (token) h.set("Authorization", `Bearer ${token}`);
  return h;
}

/** Turn a non-OK response into a thrown Error, with a clear message on 401. */
async function raiseForStatus(res: Response): Promise<never> {
  if (res.status === 401) throw new Error("Your session expired — please sign in again.");
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail || JSON.stringify(body);
  } catch {
    /* ignore */
  }
  throw new Error(detail);
}

/** Authenticated fetch: attaches the Bearer token (used by raw-blob endpoints). */
export async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${BASE}${path}`, { ...init, headers: await withAuth(init?.headers) });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(path, init);
  if (!res.ok) await raiseForStatus(res);
  return (await res.json()) as T;
}

// --- Direct-to-storage uploads ---------------------------------------------
// On hosts where the API can issue signed storage URLs (Supabase backend, e.g.
// on Vercel), the browser PUTs each file straight to object storage and then
// hands the API just the storage key — so file bytes never hit the API request
// body (which Vercel caps at 4.5 MB). When signing isn't available (local dev),
// the helpers return null and callers fall back to a normal multipart upload.
type SourceRef = { key: string; filename: string };
type SignResult =
  | { direct: false }
  | { direct: true; key: string; url: string; method?: string; headers?: Record<string, string> };

async function uploadDirect(file: File): Promise<SourceRef | null> {
  const info = await request<SignResult>("/uploads/sign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, content_type: file.type || undefined }),
  });
  if (!info.direct) return null;
  // No Authorization header here: the signed URL's own token authorizes the PUT.
  const put = await fetch(info.url, { method: info.method || "PUT", headers: info.headers, body: file });
  if (!put.ok) throw new Error(`Upload failed (${put.status})`);
  return { key: info.key, filename: file.name };
}

/** Upload every file directly, or null if the backend wants multipart instead. */
async function uploadAllDirect(files: File[]): Promise<SourceRef[] | null> {
  if (!files.length) return null;
  const first = await uploadDirect(files[0]);
  if (!first) return null; // backend has no signed storage → caller uses multipart
  const refs = [first];
  for (const f of files.slice(1)) {
    const r = await uploadDirect(f);
    if (r) refs.push(r);
  }
  return refs;
}

export const api = {
  health: () => request<Health>("/health"),

  analyze: async (files: File[]) => {
    const refs = await uploadAllDirect(files);
    if (refs) {
      return request<AnalysisJob>("/templates/analyze-refs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources: refs }),
      });
    }
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<AnalysisJob>("/templates/analyze", { method: "POST", body: form });
  },

  getAnalysis: (id: string) => request<AnalysisJob>(`/analyses/${id}`),

  cancelAnalysis: (id: string) =>
    request<AnalysisJob>(`/analyses/${id}/cancel`, { method: "POST" }),

  // Build the proposed template as a real DOCX (review screen). mode: filled|tags.
  analysisPreviewDocx: async (
    id: string,
    mode: "filled" | "tags",
    fields?: unknown[],
  ): Promise<ArrayBuffer> => {
    const res = await authFetch(`/analyses/${id}/preview.docx?mode=${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: fields ?? null }),
    });
    if (!res.ok) await raiseForStatus(res);
    return res.arrayBuffer();
  },

  // Preview an existing template rebuilt with in-progress field edits (edit screen).
  templateEditPreviewDocx: async (
    id: string,
    mode: "filled" | "tags",
    fields?: unknown[],
  ): Promise<ArrayBuffer> => {
    const res = await authFetch(`/templates/${id}/edit-preview.docx?mode=${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: fields ?? null }),
    });
    if (!res.ok) await raiseForStatus(res);
    return res.arrayBuffer();
  },

  // Fire-and-forget cancel that survives page unload/navigation (keepalive).
  cancelAnalysisBeacon: (id: string) => {
    try {
      void authFetch(`/analyses/${id}/cancel`, { method: "POST", keepalive: true });
    } catch {
      /* best effort */
    }
  },

  publish: (payload: Record<string, unknown>) =>
    request<{ template: Template; version: { version: number } }>("/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listTemplates: () => request<Template[]>("/templates"),

  getTemplate: (id: string) => request<TemplateDetail>(`/templates/${id}`),

  renameTemplate: (id: string, name: string) =>
    request<Template>(`/templates/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  createVersion: (id: string, fields: unknown[]) =>
    request<{ template: Template; version: { version: number } }>(`/templates/${id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields }),
    }),

  deleteTemplate: async (id: string) => {
    const res = await authFetch(`/templates/${id}`, { method: "DELETE" });
    if (!res.ok) await raiseForStatus(res);
  },

  // --- Projects ---
  listProjects: () => request<Project[]>("/projects"),

  getProject: (id: string) => request<ProjectDetail>(`/projects/${id}`),

  createProject: (payload: { name: string; description?: string; metadata?: Record<string, string> }) =>
    request<Project>("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateProject: (id: string, patch: Record<string, unknown>) =>
    request<Project>(`/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),

  deleteProject: async (id: string) => {
    const res = await authFetch(`/projects/${id}`, { method: "DELETE" });
    if (!res.ok) await raiseForStatus(res);
  },

  assignTemplate: (projectId: string, templateId: string) =>
    request<Template>(`/projects/${projectId}/templates/${templateId}`, { method: "POST" }),

  unassignTemplate: async (projectId: string, templateId: string) => {
    const res = await authFetch(`/projects/${projectId}/templates/${templateId}`, {
      method: "DELETE",
    });
    if (!res.ok) await raiseForStatus(res);
  },

  getVersion: (id: string, version: number) =>
    request<VersionDetail>(`/templates/${id}/versions/${version}`),

  generate: (id: string, body: Record<string, unknown>) =>
    request<GenerationResult>(`/templates/${id}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  route: (id: string, body: Record<string, unknown>) =>
    request<RoutingResult>(`/templates/${id}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  validate: (id: string, context: Record<string, unknown>, version?: number) =>
    request<ValidationReport>(`/templates/${id}/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context, version }),
    }),

  preview: (id: string, body: Record<string, unknown>) =>
    request<PreviewResult>(`/templates/${id}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // Render the filled template as a real DOCX (for the live Word-page preview).
  generatePreviewDocx: async (id: string, body: Record<string, unknown>): Promise<ArrayBuffer> => {
    const res = await authFetch(`/templates/${id}/preview.docx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) await raiseForStatus(res);
    return res.arrayBuffer();
  },

  routeDocument: async (id: string, file: File) => {
    const ref = await uploadDirect(file);
    if (ref) {
      return request<RouteDocumentResult>(`/templates/${id}/route-document-refs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ref),
      });
    }
    const form = new FormData();
    form.append("file", file);
    return request<RouteDocumentResult>(`/templates/${id}/route-document`, {
      method: "POST",
      body: form,
    });
  },

  compliance: async (id: string, file: File, version?: number) => {
    const ref = await uploadDirect(file);
    if (ref) {
      return request<ComplianceReport>(`/templates/${id}/compliance-refs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...ref, version }),
      });
    }
    const form = new FormData();
    form.append("file", file);
    const q = version ? `?version=${version}` : "";
    return request<ComplianceReport>(`/templates/${id}/compliance${q}`, {
      method: "POST",
      body: form,
    });
  },

  // In-place fix: returns the corrected DOCX blob + how many fixes were applied.
  // Direct path: the fix is parked in storage and returned as JSON {fixed, url}
  // (large) or streamed inline (small); both yield the same shape here.
  complianceFix: async (
    id: string,
    file: File,
    version?: number,
  ): Promise<{ blob: Blob; fixed: number; filename: string }> => {
    const fallbackName = file.name.replace(/\.docx$/i, "") + "-fixed.docx";
    const ref = await uploadDirect(file);
    if (ref) {
      const res = await authFetch(`/templates/${id}/compliance/fix-refs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...ref, version }),
      });
      if (!res.ok) await raiseForStatus(res);
      if ((res.headers.get("Content-Type") || "").includes("application/json")) {
        const { fixed, filename, url } = await res.json();
        const fileRes = await fetch(url);
        if (!fileRes.ok) throw new Error(`Download failed (${fileRes.status})`);
        return { blob: await fileRes.blob(), fixed: Number(fixed) || 0, filename: filename || fallbackName };
      }
      return { blob: await res.blob(), fixed: Number(res.headers.get("X-Fixes-Applied") || "0"), filename: fallbackName };
    }
    const form = new FormData();
    form.append("file", file);
    const q = version ? `?version=${version}` : "";
    const res = await authFetch(`/templates/${id}/compliance/fix${q}`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) await raiseForStatus(res);
    const fixed = Number(res.headers.get("X-Fixes-Applied") || "0");
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const filename = m ? m[1] : fallbackName;
    return { blob: await res.blob(), fixed, filename };
  },

  getAISettings: () => request<AISettingsResponse>("/settings"),

  // Recent server-side log entries for the signed-in user (in-app Logs page).
  getLogs: (limit = 300) => request<{ entries: LogEntry[] }>(`/logs?limit=${limit}`),

  updateAISettings: (patch: Record<string, unknown>) =>
    request<AISettingsResponse>("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),

  testAI: (patch: Record<string, unknown>) =>
    request<{ ok: boolean; message: string }>("/settings/ai/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),

  // Permanently delete the account: all templates, projects, documents, files,
  // and the auth user. Irreversible.
  deleteAccount: () =>
    request<{ deleted: boolean; summary: Record<string, unknown> }>("/settings/account", {
      method: "DELETE",
    }),

  templateDownloadUrl: (id: string, version: number) =>
    `${BASE}/templates/${id}/versions/${version}/template.docx`,

  // Download a backend file with the Bearer token attached, then save it in the
  // browser. Needed because plain <a href> / window navigations can't send the
  // Authorization header. `url` may be absolute (already includes /api).
  download: async (url: string, filename?: string): Promise<void> => {
    const res = await fetch(url, { headers: await withAuth() });
    if (!res.ok) await raiseForStatus(res);
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const name = filename || (m ? m[1] : url.split("/").pop() || "download");
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  },

  // The template's stored example (left side of the compliance comparison).
  representativeDocx: async (id: string, version: number): Promise<ArrayBuffer> => {
    const res = await authFetch(`/templates/${id}/versions/${version}/representative.docx`);
    if (!res.ok) await raiseForStatus(res);
    return res.arrayBuffer();
  },
};
