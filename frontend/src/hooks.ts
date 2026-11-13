import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

/** Fetch a JSON endpoint and re-fetch every `intervalMs` (pauses while the tab is hidden). */
export function usePolling<T>(path: string | null, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const pathRef = useRef(path);
  pathRef.current = path;

  const load = useCallback(async () => {
    const p = pathRef.current;
    if (!p) return;
    try {
      const d = await api<T>(p);
      if (pathRef.current === p) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (pathRef.current === p) setError(e as ApiError);
    }
  }, []);

  useEffect(() => {
    setData(null);
    load();
    const id = window.setInterval(() => {
      if (!document.hidden) load();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [path, intervalMs, load]);

  return { data, error, reload: load };
}
