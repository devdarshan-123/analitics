export type Preset =
  | "today" | "yesterday" | "thisWeek" | "7d" | "lastWeek" | "28d" | "30d"
  | "thisMonth" | "lastMonth" | "90d" | "qtd" | "thisYear" | "lastYear" | "custom";

export interface RangeState {
  preset: Preset;
  start: string; // YYYY-MM-DD
  end: string;
  compare: boolean;
}

/** Same list, labels and rules as the Google Analytics date picker. */
export const PRESETS: { key: Exclude<Preset, "custom">; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "thisWeek", label: "This week (Sun – Today)" },
  { key: "7d", label: "Last 7 days" },
  { key: "lastWeek", label: "Last week (Sun – Sat)" },
  { key: "28d", label: "Last 28 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "thisMonth", label: "This month" },
  { key: "lastMonth", label: "Last month" },
  { key: "90d", label: "Last 90 days" },
  { key: "qtd", label: "Quarter to date" },
  { key: "thisYear", label: "This year (Jan – Today)" },
  { key: "lastYear", label: "Last calendar year" },
];

export function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

export function presetRange(preset: Exclude<Preset, "custom">, now: Date = new Date()): { start: string; end: string } {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = addDays(today, -1);
  const lastN = (n: number) => [addDays(yesterday, -(n - 1)), yesterday]; // GA: "Last N days" ends yesterday
  const y = today.getFullYear();
  const m = today.getMonth();
  const ranges: Record<Exclude<Preset, "custom">, Date[]> = {
    today: [today, today],
    yesterday: [yesterday, yesterday],
    thisWeek: [addDays(today, -today.getDay()), today],
    "7d": lastN(7),
    lastWeek: [addDays(today, -today.getDay() - 7), addDays(today, -today.getDay() - 1)],
    "28d": lastN(28),
    "30d": lastN(30),
    thisMonth: [new Date(y, m, 1), today],
    lastMonth: [new Date(y, m - 1, 1), new Date(y, m, 0)],
    "90d": lastN(90),
    qtd: [new Date(y, m - (m % 3), 1), today],
    thisYear: [new Date(y, 0, 1), today],
    lastYear: [new Date(y - 1, 0, 1), new Date(y - 1, 11, 31)],
  };
  const [start, end] = ranges[preset];
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

/** "3 Nov – 9 Nov 2026", shown under the preset name like GA does. */
export function rangeDates(r: RangeState): string {
  const f = (s: string, year: boolean) =>
    new Date(`${s}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}) });
  return r.start === r.end ? f(r.start, true) : `${f(r.start, false)} – ${f(r.end, true)}`;
}
