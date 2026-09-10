"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { AISettings, AIUsage } from "./types";

export interface AiStatus {
  ai: AISettings | null;
  usage: AIUsage | null;
}

/** One shared snapshot of "which AI is serving this user".
 *
 * Four places display it — the sidebar's status line, the banner on New Template
 * and Generate, and the Settings form itself — and each used to fetch it once on
 * mount. Nothing remounts on a client-side route change, so saving a new model
 * left every one of them showing the old one until a full page reload.
 *
 * Subscribers share this cache, so they always agree with each other, and
 * ``publishAiStatus`` pushes the values a save just returned to all of them at
 * once (no extra round trip: the PUT response already carries them).
 */
let cached: AiStatus = { ai: null, usage: null };
let inFlight: Promise<void> | null = null;
const subscribers = new Set<(status: AiStatus) => void>();

function broadcast(): void {
  subscribers.forEach((notify) => notify(cached));
}

function load(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = api
    .getAISettings()
    .then(({ ai, usage }) => {
      cached = { ai, usage };
      broadcast();
    })
    .catch(() => {
      // Settings need auth; in local/no-auth mode the callers fall back to the
      // platform-wide health status instead.
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/** Push freshly-saved settings to every display. */
export function publishAiStatus(status: AiStatus): void {
  cached = status;
  broadcast();
}

/** Drop the snapshot — the next reader fetches again (used on sign out, so one
 * account's provider and model never linger in another's sidebar). */
export function clearAiStatus(): void {
  cached = { ai: null, usage: null };
  broadcast();
}

/** Re-read the server. Prefer ``publishAiStatus`` when you already have values. */
export function refreshAiStatus(): void {
  void load();
}

export function useAiStatus(): AiStatus {
  const [status, setStatus] = useState<AiStatus>(cached);
  useEffect(() => {
    subscribers.add(setStatus);
    setStatus(cached);
    void load();
    return () => {
      subscribers.delete(setStatus);
    };
  }, []);
  return status;
}
