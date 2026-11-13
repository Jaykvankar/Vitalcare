import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "rpm-theme";

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage unavailable */
  }
  return "light";
}

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
}

applyTheme(read());

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return [theme, setTheme] as const;
}

/** Resolved light/dark for chart colours. */
export function useIsDark(theme: Theme) {
  const mq = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const [sys, setSys] = useState(mq?.matches ?? false);
  useEffect(() => {
    if (!mq) return;
    const h = () => setSys(mq.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, [mq]);
  return theme === "dark" || (theme === "system" && sys);
}
