import { useState } from "react";
import { LineTrend } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { KpiSkeletons, KpiTile } from "../components/KpiTile";
import { Button, Card, EmptyState, ErrorState, InfoNote, QueryState, Skeleton, TableSkeleton } from "../components/ui";
import { useClarityBreakdown, useClarityFrustration, useClarityOverview, useClarityStatus } from "../hooks/queries";
import { useSelectedProperty } from "../lib/property";
import { fmtDate, fmtDuration, fmtNumber, fmtPct } from "../lib/format";
import type { RangeState } from "../lib/range";
import { useTheme } from "../lib/theme";
import type { ClarityBreakdown, ClarityPageRow, SignalKey } from "../types";

const DEFAULT_SIGNALS: SignalKey[] = ["rage", "dead", "quickback", "error_click"];

function NoClarityData({ latest }: { latest: string | null }) {
  return (
    <EmptyState title="No Clarity data for this period">
      {latest
        ? `Clarity is synced once a day; the latest snapshot is ${fmtDate(latest)}. Pick a range that includes it.`
        : "Clarity data appears after the first sync. Run one from Settings."}
    </EmptyState>
  );
}

export function NotLinked() {
  const { property } = useSelectedProperty();
  return (
    <Card>
      <EmptyState title={`No Clarity project linked to ${property?.propertyName ?? "this property"}`}>
        <span className="block">
          Behaviour data (scroll depth, rage and dead clicks) comes from Microsoft Clarity. Each Clarity project has its own API
          token, so link this site's project to see its data here.
        </span>
        <span className="mt-3 block">
          <Button variant="primary" onClick={() => (window.location.hash = "settings")}>
            Link a Clarity project
          </Button>
        </span>
      </EmptyState>
    </Card>
  );
}

function BreakdownCard({ dimension, title }: { dimension: "Device" | "Source" | "Country"; title: string }) {
  const q = useClarityBreakdown(dimension);
  return (
    <Card title={title} subtitle={q.data?.snapshot_date ? `Latest snapshot · ${fmtDate(q.data.snapshot_date)}` : "Latest snapshot"}>
      <QueryState query={q} isEmpty={(d) => !d.rows.length} empty={<NoClarityData latest={null} />} skeleton={<TableSkeleton rows={4} />}>
        {(d) => (
          <DataTable<ClarityBreakdown["rows"][number]>
            rows={d.rows}
            rowKey={(r) => r.value}
            defaultSort={{ key: "sessions", dir: "desc" }}
            pageSize={8}
            columns={[
              { key: "value", label: dimension, render: (r) => <span className="font-medium text-ink">{r.value}</span>, value: (r) => r.value },
              { key: "sessions", label: "Sessions", align: "right", render: (r) => fmtNumber(r.sessions), value: (r) => r.sessions },
              { key: "scroll", label: "Scroll", align: "right", render: (r) => fmtPct(r.scrollDepth, 0), value: (r) => r.scrollDepth },
              { key: "active", label: "Active time", align: "right", render: (r) => fmtDuration(r.activeTime), value: (r) => r.activeTime },
              { key: "rage", label: "Rage", align: "right", render: (r) => fmtPct(r.rage_pct), value: (r) => r.rage_pct },
              { key: "dead", label: "Dead", align: "right", render: (r) => fmtPct(r.dead_pct), value: (r) => r.dead_pct },
            ]}
          />
        )}
      </QueryState>
    </Card>
  );
}

export function Behaviour({ range }: { range: RangeState }) {
  const status = useClarityStatus();
  if (status.isLoading || (!status.data && !status.error)) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-14 w-full" />
        <KpiSkeletons count={5} />
      </div>
    );
  }
  if (status.error && !status.data) return <ErrorState error={status.error} onRetry={() => status.refetch()} />;
  if (status.data && !status.data.linked) return <NotLinked />;
  return <BehaviourLinked range={range} />;
}

function BehaviourLinked({ range }: { range: RangeState }) {
  const { palette } = useTheme();
  const overview = useClarityOverview(range);
  const frustration = useClarityFrustration(range);
  const [shown, setShown] = useState<SignalKey[]>(DEFAULT_SIGNALS);

  const latest = overview.data?.latest_date ?? null;
  const historyStart = overview.data?.history_start;
  const signals = frustration.data?.signals ?? [];
  const colorOf = (key: SignalKey) => palette.series[signals.findIndex((s) => s.key === key)];

  return (
    <div className="space-y-5">
      <InfoNote>
        <strong>Clarity history starts from the first sync date</strong>
        {historyStart ? ` (${fmtDate(historyStart, { day: "numeric", month: "short", year: "numeric" })})` : ""}. Clarity's API only exposes the last 3 days, so this
        dashboard stores one snapshot per day (synced at 02:00) and builds history from there. Today's data appears after tomorrow's sync.
      </InfoNote>

      {overview.error && !overview.data ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {overview.data ? overview.data.kpis.map((k) => <KpiTile key={k.key} metric={k} showChange={range.compare} />) : <KpiSkeletons count={5} />}
        </div>
      )}

      <Card
        title="Frustration signals"
        subtitle="Share of sessions with each signal, per day"
        actions={
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Signals shown">
            {signals.map((s) => {
              const on = shown.includes(s.key);
              return (
                <button
                  key={s.key}
                  aria-pressed={on}
                  onClick={() => setShown((cur) => (on ? cur.filter((k) => k !== s.key) : [...cur, s.key]))}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition ${on ? "border-line bg-surface-2 text-ink" : "border-transparent text-muted hover:text-ink"}`}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: on ? colorOf(s.key) : "transparent", border: `1.5px solid ${colorOf(s.key)}` }} />
                  {s.label}
                </button>
              );
            })}
          </div>
        }
      >
        <QueryState query={frustration} isEmpty={(d) => !d.series.length} empty={<NoClarityData latest={latest} />}>
          {(d) => (
            <LineTrend
              data={d.series}
              xKey="date"
              ariaLabel="Frustration signals over time"
              yFormat={(v) => `${v}%`}
              valueFormat={(v) => fmtPct(v)}
              series={d.signals.filter((s) => shown.includes(s.key)).map((s) => ({ key: `${s.key}_pct`, label: s.label, color: colorOf(s.key) }))}
            />
          )}
        </QueryState>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Engagement time" subtitle="Average active time per session">
          <QueryState query={overview} isEmpty={(d) => !d.series.length} empty={<NoClarityData latest={latest} />}>
            {(d) => (
              <LineTrend
                data={d.series}
                xKey="date"
                height={220}
                ariaLabel="Average active time per session"
                yFormat={(v) => fmtDuration(v)}
                series={[{ key: "activeTime", label: "Active time", color: palette.series[0] }]}
              />
            )}
          </QueryState>
        </Card>
        <Card title="Scroll depth" subtitle="Average % of page scrolled">
          <QueryState query={overview} isEmpty={(d) => !d.series.length} empty={<NoClarityData latest={latest} />}>
            {(d) => (
              <LineTrend
                data={d.series}
                xKey="date"
                height={220}
                ariaLabel="Average scroll depth"
                yFormat={(v) => `${v}%`}
                valueFormat={(v) => fmtPct(v)}
                series={[{ key: "scrollDepth", label: "Scroll depth", color: palette.series[0] }]}
              />
            )}
          </QueryState>
        </Card>
        <BreakdownCard dimension="Device" title="By device" />
        <BreakdownCard dimension="Source" title="By source" />
      </div>

      <Card title="Pages with the most frustration" subtitle="Clarity per-URL metrics for the selected range">
        <QueryState query={frustration} isEmpty={(d) => !d.by_page.length} empty={<NoClarityData latest={latest} />} skeleton={<TableSkeleton rows={8} />}>
          {(d) => (
            <DataTable<ClarityPageRow>
              rows={d.by_page}
              searchable
              searchPlaceholder="Filter URLs…"
              rowKey={(r) => r.path}
              defaultSort={{ key: "rage_count", dir: "desc" }}
              pageSize={10}
              columns={[
                { key: "path", label: "Page", value: (r) => r.path, className: "max-w-[16rem]", render: (r) => <span className="block truncate font-medium text-ink" title={r.url}>{r.path}</span> },
                { key: "sessions", label: "Sessions", align: "right", render: (r) => fmtNumber(r.sessions), value: (r) => r.sessions },
                { key: "rage_count", label: "Rage clicks", align: "right", render: (r) => fmtNumber(r.rage_count), value: (r) => r.rage_count },
                { key: "dead_count", label: "Dead clicks", align: "right", render: (r) => fmtNumber(r.dead_count), value: (r) => r.dead_count },
                { key: "rage_pct", label: "Rage %", align: "right", render: (r) => fmtPct(r.rage_pct), value: (r) => r.rage_pct },
                { key: "qb", label: "Quick back %", align: "right", render: (r) => fmtPct(r.quickback_pct), value: (r) => r.quickback_pct },
                { key: "err", label: "Error click %", align: "right", render: (r) => fmtPct(r.error_click_pct), value: (r) => r.error_click_pct },
                { key: "scroll", label: "Scroll", align: "right", render: (r) => fmtPct(r.scrollDepth, 0), value: (r) => r.scrollDepth },
              ]}
            />
          )}
        </QueryState>
      </Card>
    </div>
  );
}
