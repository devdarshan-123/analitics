import { useState } from "react";
import { DataTable } from "../components/DataTable";
import { Badge, Card, InfoNote, QueryState, TableSkeleton } from "../components/ui";
import { useCombinedPages } from "../hooks/queries";
import { fmtDate, fmtDuration, fmtNumber, fmtPct } from "../lib/format";
import type { RangeState } from "../lib/range";
import type { CombinedPageRow } from "../types";

export function Content({ range }: { range: RangeState }) {
  const pages = useCombinedPages(range);
  const [onlyProblems, setOnlyProblems] = useState(false);

  return (
    <div className="space-y-5">
      <QueryState query={pages} skeleton={<TableSkeleton rows={3} />}>
        {(d) => {
          const problems = d.rows.filter((r) => r.is_problem);
          return problems.length ? (
            <Card title={`${problems.length} problem page${problems.length > 1 ? "s" : ""}`} subtitle="High traffic combined with high frustration signals">
              <ul className="grid gap-3 md:grid-cols-2">
                {problems.map((p) => (
                  <li key={p.path} className="rounded-lg border border-line bg-bad-bg/60 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink">{p.pageTitle || p.path}</p>
                        <p className="truncate text-xs text-muted">{p.path}</p>
                      </div>
                      <span className="shrink-0 text-sm font-medium text-ink tabular">{fmtNumber(p.views)} views</span>
                    </div>
                    <ul className="mt-2 space-y-0.5 text-xs text-ink-2">
                      {p.problem_reasons.map((r) => (
                        <li key={r}>⚠ {r}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null;
        }}
      </QueryState>

      <Card
        title="Top pages"
        subtitle="Google Analytics traffic joined with Clarity behaviour by page path"
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-2">
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} className="accent-[var(--accent)]" />
            Problem pages only
          </label>
        }
      >
        <QueryState query={pages} isEmpty={(d) => !d.rows.length} skeleton={<TableSkeleton rows={10} />}>
          {(d) => (
            <>
              {!d.clarity_linked ? (
                <div className="mb-3">
                  <InfoNote>
                    No Clarity project is linked to this property, so only Google Analytics columns are shown and problem pages can't be
                    flagged.{" "}
                    <button onClick={() => (window.location.hash = "settings")} className="font-medium underline">
                      Link one in Settings
                    </button>
                    .
                  </InfoNote>
                </div>
              ) : (!d.clarity_history_start || d.clarity_history_start > range.start) && (
                <div className="mb-3">
                  <InfoNote>
                    {d.clarity_history_start
                      ? `Clarity columns cover ${fmtDate(d.clarity_history_start)} onwards (history starts at the first sync).`
                      : "No Clarity data yet — run a sync from Settings to fill the Clarity columns."}
                  </InfoNote>
                </div>
              )}
              <DataTable<CombinedPageRow>
                rows={onlyProblems ? d.rows.filter((r) => r.is_problem) : d.rows}
                searchable
                searchPlaceholder="Search page title or path…"
                rowKey={(r) => r.path}
                defaultSort={{ key: "views", dir: "desc" }}
                rowClassName={(r) => (r.is_problem ? "bg-bad-bg/50" : "")}
                emptyText="No problem pages in this period"
                columns={[
                  {
                    key: "page",
                    label: "Page",
                    value: (r) => `${r.pageTitle} ${r.path}`,
                    className: "max-w-[18rem]",
                    render: (r) => (
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-medium text-ink" title={r.pageTitle}>
                            {r.pageTitle || r.path}
                          </span>
                          {r.is_problem && (
                            <Badge tone="bad" className="shrink-0">
                              ⚠ Problem
                            </Badge>
                          )}
                        </div>
                        <span className="block truncate text-xs text-muted" title={r.path}>
                          {r.path}
                        </span>
                      </div>
                    ),
                  },
                  { key: "views", label: "Views", align: "right", render: (r) => fmtNumber(r.views), value: (r) => r.views },
                  { key: "users", label: "Users", align: "right", render: (r) => fmtNumber(r.users), value: (r) => r.users },
                  { key: "eng", label: "Avg. engagement", align: "right", render: (r) => fmtDuration(r.avgEngagementTime), value: (r) => r.avgEngagementTime },
                  { key: "scroll", label: "Scroll depth", align: "right", render: (r) => fmtPct(r.scrollDepth, 0), value: (r) => r.scrollDepth },
                  { key: "rage", label: "Rage clicks", align: "right", render: (r) => fmtPct(r.rage_pct), value: (r) => r.rage_pct },
                  { key: "dead", label: "Dead clicks", align: "right", render: (r) => fmtPct(r.dead_pct), value: (r) => r.dead_pct },
                  { key: "qb", label: "Quick backs", align: "right", render: (r) => fmtPct(r.quickback_pct), value: (r) => r.quickback_pct },
                  {
                    key: "score",
                    label: "Frustration",
                    align: "right",
                    value: (r) => r.frustration_score,
                    render: (r) =>
                      r.frustration_score == null ? (
                        <span className="text-muted" title="No Clarity data for this path">—</span>
                      ) : (
                        <span className={r.frustration_score >= d.thresholds.min_frustration_score ? "font-semibold text-bad" : ""}>{r.frustration_score.toFixed(1)}</span>
                      ),
                  },
                ]}
              />
              <p className="mt-3 text-xs text-muted">
                Click metrics are the share of Clarity sessions with that signal. Frustration score = 2×rage + dead + ½×quick-back + error-click %. A page is flagged when views ≥{" "}
                {fmtNumber(d.thresholds.min_views)} (top quartile) and score ≥ {d.thresholds.min_frustration_score.toFixed(1)}.
              </p>
            </>
          )}
        </QueryState>
      </Card>
    </div>
  );
}
