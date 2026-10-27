import type { Change } from "./api";

const IST = "Asia/Kolkata";

export function crore(v: number | null | undefined): string {
  if (v == null) return "–";
  const abs = Math.abs(v);
  const s = abs >= 100 ? Math.round(abs).toLocaleString("en-IN") : abs.toLocaleString("en-IN", { maximumFractionDigits: 1 });
  return `${v < 0 ? "−" : ""}₹${s} cr`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "–";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

/** A Change carries a note ("loss narrowed") when a percentage would mislead. */
export function change(c: Change | null | undefined): string {
  if (!c) return "–";
  return c.value != null ? pct(c.value) : c.note ?? "–";
}

export function tone(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || Math.abs(v) < 0.05) return "flat";
  return v > 0 ? "up" : "down";
}

export function price(v: number): string {
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function timeIST(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: IST });
}

export function dayIST(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: IST });
}

export function ago(iso: string, now = Date.now()): string {
  const mins = Math.round((now - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  return dayIST(iso);
}

export function greeting(d: Date): string {
  const h = Number(d.toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: IST }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function todayLong(d: Date): string {
  return d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: IST });
}
