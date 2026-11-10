import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ApiError } from "../lib/api";
import { fmtChange } from "../lib/format";

export function Card({ title, subtitle, actions, children, className = "" }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div className="flex flex-col gap-3" style={{ height }} aria-busy="true" aria-label="Loading">
      <Skeleton className="h-full w-full" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2.5" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-7 w-full" />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  const message = e?.message ?? (error instanceof Error ? error.message : "Something went wrong.");
  return (
    <div role="alert" className="rounded-lg border border-line bg-bad-bg px-4 py-3 text-sm">
      <p className="font-medium text-ink">{message}</p>
      {e?.hint && <p className="mt-1 text-xs break-words text-ink-2">{e.hint}</p>}
      <div className="mt-2 flex items-center gap-3 text-xs text-muted">
        {e?.code && <code>{e.code}</code>}
        {onRetry && (
          <button onClick={onRetry} className="font-medium text-accent hover:underline">
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="mb-2 text-muted" aria-hidden>
        <path d="M3 3v18h18" strokeLinecap="round" />
        <path d="M7 15l4-4 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

/** Render loading / error / empty / content for a query in one place. */
export function QueryState<T>({ query, isEmpty, empty, skeleton, children }: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  isEmpty?: (d: T) => boolean;
  empty?: ReactNode;
  skeleton?: ReactNode;
  children: (d: T) => ReactNode;
}) {
  if (query.isLoading && !query.data) return <>{skeleton ?? <ChartSkeleton />}</>;
  if (query.error && !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return null;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="No data for this period" />}</>;
  return <>{children(query.data)}</>;
}

type Tone = "neutral" | "good" | "bad" | "warn" | "info";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2",
  good: "bg-good-bg text-good",
  bad: "bg-bad-bg text-bad",
  warn: "bg-warn-bg text-warn-ink",
  info: "bg-info-bg text-info-ink",
};

export function Badge({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]} ${className}`}>{children}</span>;
}

export function Button({ variant = "secondary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const styles = {
    primary: "bg-accent text-accent-ink hover:opacity-90",
    secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
    ghost: "text-ink-2 hover:bg-surface-2",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${value === o.value ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** % change with arrow + sign so direction is never colour-only. `invert` for metrics where down is good. */
export function ChangePill({ pct, invert = false }: { pct: number | null; invert?: boolean }) {
  if (pct == null) return <span className="text-xs text-muted">no comparison</span>;
  const up = pct > 0;
  const good = pct === 0 ? null : invert ? !up : up;
  const tone = good == null ? "text-muted" : good ? "text-good" : "text-bad";
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium tabular ${tone}`}>
      <span aria-hidden>{pct === 0 ? "→" : up ? "▲" : "▼"}</span>
      {fmtChange(pct)}
    </span>
  );
}

export function InfoNote({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${tone === "info" ? "bg-info-bg text-info-ink" : "bg-warn-bg text-warn-ink"}`}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mt-px shrink-0" aria-hidden>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v.01M12 11v5" strokeLinecap="round" />
      </svg>
      <div>{children}</div>
    </div>
  );
}
