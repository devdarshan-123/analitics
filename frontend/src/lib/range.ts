export type Preset = "today" | "7d" | "30d" | "90d" | "custom";

export interface RangeState {
  preset: Preset;
  start: string; // YYYY-MM-DD
  end: string;
  compare: boolean;
}

export const PRESETS: { key: Exclude<Preset, "custom">; label: string; days: number }[] = [
  { key: "today", label: "Today", days: 1 },
  { key: "7d", label: "Last 7 days", days: 7 },
  { key: "30d", label: "Last 30 days", days: 30 },
  { key: "90d", label: "Last 90 days", days: 90 },
];

export function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function presetRange(preset: Exclude<Preset, "custom">): { start: string; end: string } {
  const days = PRESETS.find((p) => p.key === preset)!.days;
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (days - 1));
  return { start: isoLocal(start), end: isoLocal(end) };
}

export function rangeQuery(r: RangeState, withCompare = true): string {
  const q = new URLSearchParams({ start: r.start, end: r.end });
  if (withCompare && r.compare) q.set("compare", "true");
  return `?${q}`;
}

export function rangeLabel(r: RangeState): string {
  const p = PRESETS.find((x) => x.key === r.preset);
  return p ? p.label : `${r.start} → ${r.end}`;
}
