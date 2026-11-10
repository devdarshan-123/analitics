import { fmtValue } from "../lib/format";
import type { KpiMetric } from "../types";
import { ChangePill, Skeleton } from "./ui";

// Metrics where a decrease is an improvement.
const LOWER_IS_BETTER = new Set(["bounceRate"]);

export function KpiTile({ metric, showChange = true }: { metric: KpiMetric; showChange?: boolean }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <p className="truncate text-xs font-medium text-muted">{metric.label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{fmtValue(metric.value, metric.format)}</p>
      {showChange && (
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5">
          <ChangePill pct={metric.change_pct} invert={LOWER_IS_BETTER.has(metric.key)} />
          {metric.previous != null && <span className="truncate text-xs text-muted">vs {fmtValue(metric.previous, metric.format)}</span>}
        </div>
      )}
    </div>
  );
}

export function KpiSkeletons({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-xl border border-line bg-surface p-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-3 h-7 w-24" />
          <Skeleton className="mt-2 h-3 w-16" />
        </div>
      ))}
    </>
  );
}
