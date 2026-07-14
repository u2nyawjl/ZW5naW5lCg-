import { useEffect, useState } from "react";

const PREFIX = "cache:";

// Stale-while-revalidate: pinta al instante lo último cacheado y refresca en segundo
// plano. Elimina el "cargando…" en toda visita salvo la primera de todas.
export function useCached<T>(key: string, fetcher: () => Promise<T>, intervalMs?: number) {
  const [data, setData] = useState<T | null>(() => {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(data === null);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const fresh = await fetcher();
        if (!alive) return;
        setData(fresh);
        localStorage.setItem(PREFIX + key, JSON.stringify(fresh));
      } catch {
        /* red caída: se mantiene lo cacheado */
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    const id = intervalMs ? setInterval(run, intervalMs) : undefined;
    return () => {
      alive = false;
      if (id) clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

export function clearCache() {
  Object.keys(localStorage)
    .filter((k) => k.startsWith(PREFIX))
    .forEach((k) => localStorage.removeItem(k));
}
