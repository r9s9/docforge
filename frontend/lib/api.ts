// Thin fetch wrapper around the DocForge REST API.
//
// Same-origin by default (/api is proxied to the backend via next.config.mjs).
// For a split deployment set NEXT_PUBLIC_API_BASE_URL to the backend origin and
// the browser will call it directly.
import type {
  AISettings,
  AnalysisJob,
  ComplianceReport,
  GenerationResult,
  Health,
  PreviewResult,
  RouteDocumentResult,
  RoutingResult,
  Template,
  TemplateDetail,
  ValidationReport,
  VersionDetail,
} from "./types";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const BASE = `${API_ORIGIN}/api`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),

  analyze: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<AnalysisJob>("/templates/analyze", { method: "POST", body: form });
  },

  getAnalysis: (id: string) => request<AnalysisJob>(`/analyses/${id}`),

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
    const res = await fetch(`${BASE}/templates/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Delete failed (${res.status})`);
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

  routeDocument: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<RouteDocumentResult>(`/templates/${id}/route-document`, {
      method: "POST",
      body: form,
    });
  },

  compliance: (id: string, file: File, version?: number) => {
    const form = new FormData();
    form.append("file", file);
    const q = version ? `?version=${version}` : "";
    return request<ComplianceReport>(`/templates/${id}/compliance${q}`, {
      method: "POST",
      body: form,
    });
  },

  getAISettings: () => request<{ ai: AISettings }>("/settings"),

  updateAISettings: (patch: Record<string, unknown>) =>
    request<{ ai: AISettings }>("/settings", {
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

  templateDownloadUrl: (id: string, version: number) =>
    `${BASE}/templates/${id}/versions/${version}/template.docx`,
};
