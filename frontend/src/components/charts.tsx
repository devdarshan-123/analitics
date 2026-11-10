import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate, fmtNumber } from "../lib/format";
import { useTheme } from "../lib/theme";

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
  /** Previous-period / reference lines are thinner and lighter. */
  faint?: boolean;
}

function Legend({ series }: { series: SeriesDef[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: s.color, opacity: s.faint ? 0.55 : 1, height: s.faint ? 2 : 3 }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function TooltipBox({ title, rows }: { title: string; rows: { label: string; value: string; color: string; faint?: boolean }[] }) {
  return (
    <div className="min-w-40 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="mb-1.5 font-medium text-ink">{title}</p>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-ink-2">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: r.color, opacity: r.faint ? 0.55 : 1 }} />
            {r.label}
          </span>
          <span className="font-medium text-ink tabular">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export function LineTrend<T extends object>({ data, xKey, series, height = 260, yFormat = (v) => fmtNumber(v, { compact: true }), valueFormat, ariaLabel }: {
  data: T[];
  xKey: keyof T & string;
  series: SeriesDef[];
  height?: number;
  yFormat?: (v: number) => string;
  valueFormat?: (v: number) => string;
  ariaLabel: string;
}) {
  const { palette } = useTheme();
  const fmt = valueFormat ?? yFormat;
  return (
    <div role="img" aria-label={ariaLabel}>
      <Legend series={series} />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={palette.grid} />
            <XAxis
              dataKey={xKey}
              tickFormatter={(v) => fmtDate(String(v))}
              tick={{ fontSize: 11, fill: palette.muted }}
              tickLine={false}
              axisLine={{ stroke: palette.axis }}
              minTickGap={24}
            />
            <YAxis tickFormatter={yFormat} tick={{ fontSize: 11, fill: palette.muted }} tickLine={false} axisLine={false} width={44} />
            <Tooltip
              cursor={{ stroke: palette.axis, strokeWidth: 1 }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={fmtDate(String(label), { weekday: "short", day: "numeric", month: "short", year: "numeric" })}
                    rows={series
                      .filter((s) => payload.some((p) => p.dataKey === s.key && p.value != null))
                      .map((s) => ({ label: s.label, color: s.color, faint: s.faint, value: fmt(Number(payload.find((p) => p.dataKey === s.key)?.value)) }))}
                  />
                ) : null
              }
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeOpacity={s.faint ? 0.55 : 1}
                strokeWidth={s.faint ? 1.5 : 2}
                dot={false}
                activeDot={{ r: 4, stroke: palette.surface, strokeWidth: 2 }}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Part-to-whole donut, capped at 6 segments (the rest fold into "Other"). */
export function Donut({ data, valueLabel, format = (v) => fmtNumber(v) }: {
  data: { name: string; value: number }[];
  valueLabel: string;
  format?: (v: number) => string;
}) {
  const { palette } = useTheme();
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const top = sorted.slice(0, 5);
  const rest = sorted.slice(5).reduce((s, d) => s + d.value, 0);
  const slices = rest > 0 ? [...top, { name: "Other", value: rest }] : top;
  const total = slices.reduce((s, d) => s + d.value, 0) || 1;
  const color = (i: number, name: string) => (name === "Other" ? palette.other : palette.series[i]);

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="relative h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={slices} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="100%" paddingAngle={1.5} stroke={palette.surface} strokeWidth={2} isAnimationActive={false}>
              {slices.map((s, i) => (
                <Cell key={s.name} fill={color(i, s.name)} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={String(payload[0].name)}
                    rows={[{ label: valueLabel, value: `${format(Number(payload[0].value))} (${((Number(payload[0].value) / total) * 100).toFixed(1)}%)`, color: String(payload[0].payload?.fill ?? palette.other) }]}
                  />
                ) : null
              }
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-semibold text-ink">{fmtNumber(total, { compact: true })}</span>
          <span className="text-[11px] text-muted">{valueLabel}</span>
        </div>
      </div>
      <ul className="w-full min-w-0 space-y-1.5 text-sm">
        {slices.map((s, i) => (
          <li key={s.name} className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-ink-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color(i, s.name) }} />
              <span className="truncate">{s.name}</span>
            </span>
            <span className="shrink-0 text-ink tabular">
              {format(s.value)} <span className="text-xs text-muted">{((s.value / total) * 100).toFixed(0)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Ranked horizontal bars in plain HTML: one measure, one hue, value always printed. */
export function BarList({ items, format = (v) => fmtNumber(v), max = 10, showShare = false }: {
  items: { name: string; value: number; sub?: string }[];
  format?: (v: number) => string;
  max?: number;
  showShare?: boolean;
}) {
  const { palette } = useTheme();
  const shown = items.slice(0, max);
  const peak = Math.max(...shown.map((i) => i.value), 1);
  const total = items.reduce((s, i) => s + i.value, 0) || 1;
  return (
    <ul className="space-y-2.5">
      {shown.map((item) => (
        <li key={item.name + (item.sub ?? "")} title={`${item.name}: ${format(item.value)}`} className="group">
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-ink-2 group-hover:text-ink">
              {item.name}
              {item.sub && <span className="ml-1.5 text-xs text-muted">{item.sub}</span>}
            </span>
            <span className="shrink-0 font-medium text-ink tabular">
              {format(item.value)}
              {showShare && <span className="ml-1.5 text-xs font-normal text-muted">{((item.value / total) * 100).toFixed(1)}%</span>}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-2">
            <div className="h-1.5 rounded-full transition-[width]" style={{ width: `${(item.value / peak) * 100}%`, background: palette.series[0] }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
