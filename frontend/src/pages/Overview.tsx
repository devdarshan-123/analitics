import { BarList, Donut, LineTrend, type SeriesDef } from "../components/charts";
import { KpiSkeletons, KpiTile } from "../components/KpiTile";
import { Card, ErrorState, QueryState, Skeleton, TableSkeleton } from "../components/ui";
import { useGA, useRealtime } from "../hooks/queries";
import { fmtDate, fmtNumber, timeAgo } from "../lib/format";
import type { RangeState } from "../lib/range";
import { useTheme } from "../lib/theme";

function RealtimeCard() {
  const rt = useRealtime();
  return (
    <Card title="Active now" subtitle="Users in the last 30 minutes · refreshes every 60s" className="lg:row-span-2">
      {rt.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-24" />
          <TableSkeleton rows={4} />
        </div>
      ) : rt.error ? (
        <ErrorState error={rt.error} onRetry={() => rt.refetch()} />
      ) : rt.data ? (
        <>
          <div className="flex items-center gap-3">
            <span className="relative flex h-2.5 w-2.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60 motion-reduce:animate-none" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-good" />
            </span>
            <span className="text-4xl font-semibold tracking-tight text-ink">{fmtNumber(rt.data.activeUsers)}</span>
          </div>
          <p className="mt-1 text-xs text-muted">Updated {timeAgo(rt.data.fetched_at)}</p>
          {rt.data.byPage.length > 0 && (
            <>
              <h3 className="mt-5 mb-2 text-xs font-medium text-muted">Top pages right now</h3>
              <BarList items={rt.data.byPage} max={5} />
            </>
          )}
          {rt.data.byCountry.length > 0 && (
            <>
              <h3 className="mt-5 mb-2 text-xs font-medium text-muted">By country</h3>
              <BarList items={rt.data.byCountry} max={4} />
            </>
          )}
        </>
      ) : null}
    </Card>
  );
}

export function Overview({ range }: { range: RangeState }) {
  const { palette } = useTheme();
  const overview = useGA("overview", range);
  const ts = useGA("timeseries", range);
  const channels = useGA("channels", range);
  const tech = useGA("tech", range);

  const series: SeriesDef[] = [
    { key: "activeUsers", label: "Users", color: palette.series[0] },
    { key: "sessions", label: "Sessions", color: palette.series[1] },
  ];
  if (ts.data?.compare) {
    series.push(
      { key: "prev_activeUsers", label: "Users (previous period)", color: palette.series[0], faint: true },
      { key: "prev_sessions", label: "Sessions (previous period)", color: palette.series[1], faint: true },
    );
  }

  return (
    <div className="space-y-5">
      {overview.error && !overview.data ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {overview.data ? overview.data.metrics.map((m) => <KpiTile key={m.key} metric={m} />) : <KpiSkeletons count={8} />}
        </div>
      )}
      {overview.data && (
        <p className="-mt-2 text-xs text-muted">
          Change vs {fmtDate(overview.data.previous_range.start)} – {fmtDate(overview.data.previous_range.end)}
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Users & sessions" subtitle="Daily, Google Analytics" className="lg:col-span-2">
          <QueryState query={ts} isEmpty={(d) => d.points.every((p) => !p.sessions)}>
            {(d) => <LineTrend data={d.points} xKey="date" series={series} ariaLabel="Daily users and sessions" />}
          </QueryState>
        </Card>
        <RealtimeCard />
        <Card title="Channels" subtitle="Sessions by default channel group">
          <QueryState query={channels} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton rows={5} />}>
            {(d) => <Donut data={d.rows.map((r) => ({ name: r.channel, value: r.sessions }))} valueLabel="sessions" />}
          </QueryState>
        </Card>
        <Card title="Devices" subtitle="Active users by device category">
          <QueryState query={tech} isEmpty={(d) => !d.devices.length} skeleton={<TableSkeleton rows={3} />}>
            {(d) => <BarList items={d.devices.map((x) => ({ ...x, name: x.name[0].toUpperCase() + x.name.slice(1) }))} showShare />}
          </QueryState>
        </Card>
      </div>
    </div>
  );
}
