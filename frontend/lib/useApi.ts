"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api } from "./api";

/** Minimal fetch hook: data, error, loading, reload. Keeps the last data while reloading. */
export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    const run = () =>
      api<T>(path).then(
        (d) => { if (alive) { setData(d); setError(null); } },
        (e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); },
      );
    run();
    const timer = pollMs ? setInterval(run, pollMs) : undefined;
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
  }, [path, pollMs, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading: !!path && data === null && error === null, reload, setData };
}

// ---------- per-device memory (reviewed cards, last window); never needed for correctness ----------
const EVENT = "finn-storage";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(EVENT, cb);
  };
}

function parse<T>(raw: string | null, fallbackJson: string): T {
  try {
    return JSON.parse(raw ?? fallbackJson) as T;
  } catch {
    return JSON.parse(fallbackJson) as T;
  }
}

export function useStored<T>(key: string, initial: T) {
  const fallbackJson = JSON.stringify(initial);
  const raw = useSyncExternalStore(subscribe, () => read(key), () => null);
  const value = useMemo(() => parse<T>(raw, fallbackJson), [raw, fallbackJson]);

  const set = useCallback(
    (v: T | ((prev: T) => T)) => {
      const prev = parse<T>(read(key), fallbackJson);
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {}
      window.dispatchEvent(new Event(EVENT));
    },
    [key, fallbackJson],
  );
  return [value, set] as const;
}

// ---------- the clock: client-only, so prerendered HTML never bakes in a build-time date ----------
function subscribeMinute(cb: () => void) {
  const t = setInterval(cb, 30_000);
  return () => clearInterval(t);
}

export function useNow(): Date | null {
  const minute = useSyncExternalStore(subscribeMinute, () => Math.floor(Date.now() / 60_000), () => 0);
  return minute ? new Date(minute * 60_000) : null;
}
