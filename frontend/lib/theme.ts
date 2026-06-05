// Light/dark theme persistence (applied via data-theme on <html>).
export type Theme = "light" | "dark";

const KEY = "docforge-theme";

export function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
}
