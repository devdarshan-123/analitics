import { useEffect, useMemo, useRef, useState } from "react";
import { useRefreshProperties } from "../hooks/queries";
import { ApiError } from "../lib/api";
import { useSelectedProperty } from "../lib/property";
import type { PropertyInfo } from "../types";
import { Skeleton } from "./ui";

function groupByAccount(list: PropertyInfo[]) {
  const groups: { accountId: string; accountName: string; items: PropertyInfo[] }[] = [];
  for (const p of list) {
    const last = groups[groups.length - 1];
    if (last && last.accountId === p.accountId) last.items.push(p);
    else groups.push({ accountId: p.accountId, accountName: p.accountName, items: [p] });
  }
  return groups;
}

function ClarityDot({ on }: { on: boolean }) {
  return (
    <span
      title={on ? "Clarity project linked" : "No Clarity project"}
      aria-label={on ? "Clarity linked" : "No Clarity"}
      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${on ? "bg-good" : "border border-muted"}`}
    />
  );
}

export function PropertySwitcher({ list, isLoading, error }: { list: PropertyInfo[] | undefined; isLoading: boolean; error: unknown }) {
  const { property, setPropertyId } = useSelectedProperty();
  const refresh = useRefreshProperties();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setFilter("");
    setTimeout(() => searchRef.current?.focus(), 0);
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const items = (list ?? []).filter((p) => !f || `${p.propertyName} ${p.accountName} ${p.propertyId}`.toLowerCase().includes(f));
    return groupByAccount(items);
  }, [list, filter]);

  if (isLoading) return <Skeleton className="h-8 w-44" />;

  const err = error instanceof ApiError ? error : null;
  const label = property ? property.propertyName : error ? "Properties unavailable" : "Select property";
  const showSearch = (list?.length ?? 0) > 6;

  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={`inline-flex max-w-[16rem] min-w-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm hover:bg-surface-2 sm:max-w-xs ${error ? "border-bad text-bad" : "border-line text-ink"}`}
      >
        {property && <ClarityDot on={property.hasClarity} />}
        <span className="min-w-0 truncate text-left">
          <span className="font-medium">{label}</span>
          {property && <span className="ml-1.5 hidden text-xs text-muted sm:inline">{property.accountName}</span>}
        </span>
        <span aria-hidden className="text-[10px] text-muted">▼</span>
      </button>

      {open && (
        <div role="dialog" aria-label="Choose GA4 property" className="absolute left-0 z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface shadow-xl">
          {error ? (
            <div className="p-3 text-sm" role="alert">
              <p className="font-medium text-ink">{err?.message ?? "Couldn't load your GA4 properties."}</p>
              {err?.hint && <p className="mt-1.5 text-xs leading-relaxed break-words text-ink-2">{err.hint}</p>}
              {err?.code && <code className="mt-2 block text-xs text-muted">{err.code}</code>}
              <p className="mt-2 text-xs text-muted">Showing data for the default property (GA4_PROPERTY_ID) where possible.</p>
            </div>
          ) : (
            <>
              {showSearch && (
                <div className="border-b border-line p-2">
                  <input
                    ref={searchRef}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Search properties…"
                    aria-label="Search properties"
                    className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-muted"
                  />
                </div>
              )}
              <div className="max-h-[min(60vh,24rem)] overflow-y-auto p-1.5">
                {groups.length === 0 && <p className="px-3 py-2 text-sm text-muted">No matching properties</p>}
                {groups.map((g) => (
                  <div key={g.accountId} role="group" aria-label={g.accountName} className="mb-1 last:mb-0">
                    <p className="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted uppercase">{g.accountName}</p>
                    {g.items.map((p) => {
                      const selected = p.propertyId === property?.propertyId;
                      return (
                        <button
                          key={p.propertyId}
                          onClick={() => {
                            setPropertyId(p.propertyId);
                            setOpen(false);
                          }}
                          aria-current={selected ? "true" : undefined}
                          className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2 ${selected ? "bg-surface-2" : ""}`}
                        >
                          <ClarityDot on={p.hasClarity} />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-ink">{p.propertyName}</span>
                            <span className="block text-xs text-muted tabular">
                              {p.propertyId}
                              {p.isDefault && " · default"}
                            </span>
                          </span>
                          {selected && <span className="font-bold text-accent" aria-label="selected">✓</span>}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </>
          )}
          <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs text-muted">
              <ClarityDot on /> Clarity linked
            </span>
            <button
              // Always bypass the server's cache (it also remembers failures for a minute).
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
              className="text-xs font-medium text-accent hover:underline disabled:opacity-50"
            >
              {refresh.isPending ? "Refreshing…" : error ? "Retry" : "Refresh list"}
            </button>
          </div>
          {refresh.error && (
            <p className="border-t border-line px-3 py-2 text-xs text-bad" role="alert">
              {refresh.error instanceof ApiError ? refresh.error.message : "Refresh failed"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
