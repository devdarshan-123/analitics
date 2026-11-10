import { BarList } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { Card, QueryState, TableSkeleton } from "../components/ui";
import { useGA } from "../hooks/queries";
import { fmtNumber } from "../lib/format";
import type { RangeState } from "../lib/range";

export function Events({ range }: { range: RangeState }) {
  const events = useGA("events", range);
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Top events" subtitle="Event count, top 12">
        <QueryState query={events} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton rows={10} />}>
          {(d) => <BarList items={d.rows.map((r) => ({ name: r.eventName, value: r.eventCount }))} max={12} />}
        </QueryState>
      </Card>
      <Card title="All events" subtitle="Top 50 by count">
        <QueryState query={events} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton rows={10} />}>
          {(d) => (
            <DataTable
              rows={d.rows}
              searchable
              searchPlaceholder="Filter events…"
              rowKey={(r) => r.eventName}
              defaultSort={{ key: "count", dir: "desc" }}
              pageSize={20}
              columns={[
                { key: "name", label: "Event", render: (r) => <code className="text-xs text-ink">{r.eventName}</code>, value: (r) => r.eventName },
                { key: "count", label: "Count", align: "right", render: (r) => fmtNumber(r.eventCount), value: (r) => r.eventCount },
                { key: "users", label: "Users", align: "right", render: (r) => fmtNumber(r.totalUsers), value: (r) => r.totalUsers },
                {
                  key: "per",
                  label: "Per user",
                  align: "right",
                  render: (r) => (r.totalUsers ? (r.eventCount / r.totalUsers).toFixed(1) : "—"),
                  value: (r) => (r.totalUsers ? r.eventCount / r.totalUsers : null),
                },
              ]}
            />
          )}
        </QueryState>
      </Card>
    </div>
  );
}
