"use client";

import { useEffect, useState } from "react";

/**
 * Portrait phones get a layout of their own (a top bar with a slide-out menu,
 * full-width content); everything wider keeps the desktop layout. The CSS for
 * it lives in one `@media (max-width: 640px)` block in globals.css; keep the
 * two in step.
 */
export const PHONE_QUERY = "(max-width: 640px)";

export function isPhone(): boolean {
  return typeof window !== "undefined" && window.matchMedia(PHONE_QUERY).matches;
}

/** Whether the phone layout is showing, kept current as the window changes. */
export function usePhone(): boolean {
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const update = () => setPhone(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return phone;
}
