import { BarList } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { Card, ChangePill, QueryState, TableSkeleton } from "../components/ui";
import { useGA } from "../hooks/queries";
import { fmtNumber, fmtRatio } from "../lib/format";
import type { RangeState } from "../lib/range";
import type { ChannelRow, SourceRow } from "../types";

export function Acquisition({ range }: { range: RangeState }) {
  const channels = useGA("channels", range);
  const sources = useGA("sources", range);
  const geo = useGA("geo", range);

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Channels" subtitle="Sessions by default channel group" className="lg:col-span-2">
          <QueryState query={channels} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton />}>
            {(d) => <BarList items={d.rows.map((r) => ({ name: r.channel, value: r.sessions }))} showShare />}
          </QueryState>
        </Card>
        <Card title="Channel performance" className="lg:col-span-3">
          <QueryState query={channels} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton />}>
            {(d) => (
              <DataTable<ChannelRow>
                rows={d.rows}
                rowKey={(r) => r.channel}
                defaultSort={{ key: "sessions", dir: "desc" }}
                columns={[
                  { key: "channel", label: "Channel", render: (r) => <span className="font-medium text-ink">{r.channel}</span>, value: (r) => r.channel },
                  { key: "sessions", label: "Sessions", align: "right", render: (r) => fmtNumber(r.sessions), value: (r) => r.sessions },
                  ...(range.compare
                    ? [{ key: "change", label: "vs prev.", align: "right" as const, render: (r: ChannelRow) => <ChangePill pct={r.change_pct} />, value: (r: ChannelRow) => r.change_pct }]
                    : []),
                  { key: "users", label: "Users", align: "right", render: (r) => fmtNumber(r.activeUsers), value: (r) => r.activeUsers },
                  { key: "eng", label: "Engagement", align: "right", render: (r) => fmtRatio(r.engagementRate), value: (r) => r.engagementRate },
                  { key: "ke", label: "Key events", align: "right", render: (r) => fmtNumber(r.keyEvents), value: (r) => r.keyEvents },
                ]}
              />
            )}
          </QueryState>
        </Card>
      </div>

      <Card title="Source / medium" subtitle="Top 100 by sessions">
        <QueryState query={sources} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton rows={8} />}>
          {(d) => (
            <DataTable<SourceRow>
              rows={d.rows}
              searchable
              searchPlaceholder="Filter source or medium…"
              rowKey={(r) => `${r.source}/${r.medium}`}
              defaultSort={{ key: "sessions", dir: "desc" }}
              pageSize={15}
              columns={[
                { key: "source", label: "Source", render: (r) => <span className="font-medium text-ink">{r.source}</span>, value: (r) => r.source },
                { key: "medium", label: "Medium", render: (r) => <span className="text-ink-2">{r.medium}</span>, value: (r) => r.medium },
                { key: "sessions", label: "Sessions", align: "right", render: (r) => fmtNumber(r.sessions), value: (r) => r.sessions },
                { key: "users", label: "Users", align: "right", render: (r) => fmtNumber(r.activeUsers), value: (r) => r.activeUsers },
                { key: "eng", label: "Engagement", align: "right", render: (r) => fmtRatio(r.engagementRate), value: (r) => r.engagementRate },
                { key: "ke", label: "Key events", align: "right", render: (r) => fmtNumber(r.keyEvents), value: (r) => r.keyEvents },
              ]}
            />
          )}
        </QueryState>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Countries" subtitle="Active users">
          <QueryState query={geo} isEmpty={(d) => !d.countries.length} skeleton={<TableSkeleton />}>
            {(d) => <BarList items={d.countries.map((c) => ({ name: c.country, value: c.activeUsers }))} max={12} showShare />}
          </QueryState>
        </Card>
        <Card title="Cities" subtitle="Active users, top 50">
          <QueryState query={geo} isEmpty={(d) => !d.cities.length} skeleton={<TableSkeleton />}>
            {(d) => (
              <DataTable
                rows={d.cities}
                searchable
                searchPlaceholder="Filter cities…"
                pageSize={12}
                rowKey={(r) => `${r.city}-${r.country}`}
                defaultSort={{ key: "users", dir: "desc" }}
                columns={[
                  { key: "city", label: "City", render: (r) => <span className="text-ink">{r.city}</span>, value: (r) => r.city },
                  { key: "country", label: "Country", render: (r) => <span className="text-ink-2">{r.country}</span>, value: (r) => r.country },
                  { key: "users", label: "Users", align: "right", render: (r) => fmtNumber(r.activeUsers), value: (r) => r.activeUsers },
                ]}
              />
            )}
          </QueryState>
        </Card>
      </div>
    </div>
  );
}
