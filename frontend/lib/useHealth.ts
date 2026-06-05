"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";

// Shared AI/connection status. Polls health once on mount.
export function useHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    let active = true;
    api
      .health()
      .then((h) => active && setHealth(h))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return health;
}
