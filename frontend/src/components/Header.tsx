import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useClarityStatus, useLastUpdated } from "../hooks/queries";
import { post } from "../lib/api";
import { timeAgo } from "../lib/format";
import { rangeLabel, type RangeState } from "../lib/range";
import { useSelectedProperty } from "../lib/property";
import { useTheme, type ThemePref } from "../lib/theme";
import type { PropertyInfo } from "../types";
import { DateRangePicker } from "./DateRangePicker";
import { PropertySwitcher } from "./PropertySwitcher";
import { Badge } from "./ui";

export const TABS = [
  { id: "overview", label: "Overview" },
  { id: "acquisition", label: "Acquisition" },
  { id: "content", label: "Content" },
  { id: "behaviour", label: "Behaviour" },
  { id: "events", label: "Events" },
  { id: "settings", label: "Settings" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

function useTicker(ms: number) {
  const [, set] = useState(0);
  useEffect(() => {
    const id = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}

function SyncBadge({ onClick }: { onClick: () => void }) {
  const { data, isLoading } = useClarityStatus();
  if (isLoading || !data) return <Badge>Clarity…</Badge>;
  if (!data.linked) {
    return (
      <button onClick={onClick} title="No Clarity project is linked to this property" className="rounded-full focus:outline-2 focus:outline-accent">
        <Badge>
          <span aria-hidden>○</span>Clarity not linked
        </Badge>
      </button>
    );
  }
  const last = data.last_successful_sync;
  const stale = !last || Date.now() - new Date(last).getTime() > 36 * 3600 * 1000;
  const failed = data.last_run?.status === "failed";
  const tone = failed ? "bad" : !last ? "neutral" : stale ? "warn" : "good";
  const label = failed ? "Clarity sync failed" : last ? `Clarity synced ${timeAgo(last)}` : data.history_start ? "Clarity: not synced yet" : "Clarity: no data";
  return (
    <button onClick={onClick} title={`${data.calls_used_today}/${data.daily_limit} Clarity API calls used today`} className="rounded-full focus:outline-2 focus:outline-accent">
      <Badge tone={tone}>
        <span aria-hidden>{failed ? "✕" : tone === "good" ? "●" : "○"}</span>
        {label}
      </Badge>
    </button>
  );
}

/** Opens the live site report (GA + Clarity) for the selected property and date range in a new tab. */
function GenerateReportButton({ range }: { range: RangeState }) {
  const { propertyId } = useSelectedProperty();
  const open = () => {
    const q = new URLSearchParams({ start: range.start, end: range.end, compare: "true", label: rangeLabel(range) });
    if (propertyId) q.set("propertyId", propertyId);
    window.open(`/api/report/html?${q}`, "_blank", "noopener");
  };
  return (
    <button
      onClick={open}
      title="Build a live report from Google Analytics and Microsoft Clarity for this date range"
      className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-ink hover:opacity-90"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
        <path d="M6 3h9l5 5v13H6z M14 3v6h6 M9 14h7 M9 18h5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Generate report
    </button>
  );
}

function ThemeToggle() {
  const { pref, setPref } = useTheme();
  const next: Record<ThemePref, ThemePref> = { system: "light", light: "dark", dark: "system" };
  const icon = { system: "◐", light: "☀", dark: "☾" }[pref];
  return (
    <button onClick={() => setPref(next[pref])} title={`Theme: ${pref} (click to change)`} aria-label={`Theme: ${pref}`} className="h-8 w-8 rounded-lg text-ink-2 hover:bg-surface-2">
      {icon}
    </button>
  );
}

export function Header({ tab, onTab, range, onRange, mockMode, properties }: {
  tab: TabId;
  onTab: (t: TabId) => void;
  range: RangeState;
  onRange: (r: RangeState) => void;
  mockMode: boolean;
  properties: { list: PropertyInfo[] | undefined; isLoading: boolean; error: unknown };
}) {
  const qc = useQueryClient();
  const updated = useLastUpdated();
  useTicker(30_000);

  const logout = async () => {
    await post("/auth/logout").catch(() => undefined);
    qc.clear();
    qc.setQueryData(["auth"], { authenticated: false, mock_mode: mockMode });
  };

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
              <rect width="32" height="32" rx="7" fill="var(--accent)" />
              <path d="M8 22l5-6 4 3 7-9" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <h1 className="hidden text-base font-semibold text-ink sm:block">Analytics</h1>
            <PropertySwitcher list={properties.list} isLoading={properties.isLoading} error={properties.error} />
            {mockMode && <Badge tone="warn">Mock data</Badge>}
          </div>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <SyncBadge onClick={() => onTab("settings")} />
            <span className="hidden text-xs text-muted md:inline">Updated {updated ? timeAgo(updated) : "—"}</span>
            <button
              onClick={() => qc.invalidateQueries()}
              title="Refresh data"
              aria-label="Refresh data"
              className="h-8 w-8 rounded-lg text-ink-2 hover:bg-surface-2"
            >
              ↻
            </button>
            <ThemeToggle />
            <button onClick={logout} className="rounded-lg px-2 py-1 text-xs font-medium text-ink-2 hover:bg-surface-2">
              Sign out
            </button>
          </div>
        </div>
        <div className="flex flex-col-reverse gap-2 pb-2 md:flex-row md:items-center md:justify-between">
          <nav aria-label="Sections" className="-mx-1 flex overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => onTab(t.id)}
                aria-current={tab === t.id ? "page" : undefined}
                className={`mx-1 shrink-0 border-b-2 px-1 py-2 text-sm font-medium transition ${tab === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          {tab !== "settings" && (
            <div className="flex items-center gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
                <input
                  type="checkbox"
                  role="switch"
                  checked={range.compare}
                  onChange={(e) => onRange({ ...range, compare: e.target.checked })}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
                Compare to previous period
              </label>
              <DateRangePicker value={range} onChange={onRange} />
              <GenerateReportButton range={range} />
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
