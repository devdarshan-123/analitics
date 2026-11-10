import type { Format } from "../types";

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const twoDp = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

export function fmtNumber(v: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (v == null || Number.isNaN(v)) return "—";
  return opts.compact && Math.abs(v) >= 10_000 ? compact.format(v) : whole.format(v);
}

/** GA ratios (0.58) -> "58.0%" */
export function fmtRatio(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

/** Values already in percent (Clarity: 47.3) -> "47.3%" */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : `${v.toFixed(digits)}%`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtValue(v: number | null, format: Format): string {
  switch (format) {
    case "percent":
      return fmtRatio(v);
    case "duration":
      return fmtDuration(v);
    case "decimal":
      return v == null ? "—" : twoDp.format(v);
    default:
      return fmtNumber(v, { compact: true });
  }
}

export function fmtChange(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(1)}%`;
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }): string {
  if (!iso) return "—";
  // Plain YYYY-MM-DD strings are calendar dates, not instants: parse as local.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return d.toLocaleDateString(undefined, opts);
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(iso: string | number | null | undefined): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 0) {
    const ahead = -diff;
    if (ahead < 3600) return `in ${Math.round(ahead / 60)} min`;
    if (ahead < 86400) return `in ${Math.round(ahead / 3600)} h`;
    return `in ${Math.round(ahead / 86400)} d`;
  }
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return `${Math.round(diff / 86400)} d ago`;
}
