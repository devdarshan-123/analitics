import { useEffect, useRef, useState } from "react";
import { isoLocal, PRESETS, presetRange, rangeDates, rangeLabel, type RangeState } from "../lib/range";

export function DateRangePicker({ value, onChange }: { value: RangeState; onChange: (r: RangeState) => void }) {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(value.start);
  const [end, setEnd] = useState(value.end);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setStart(value.start);
    setEnd(value.end);
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, value.start, value.end]);

  const today = isoLocal(new Date());
  const customValid = start && end && start <= end && end <= today;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden className="text-muted">
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 10h18M8 3v4M16 3v4" strokeLinecap="round" />
        </svg>
        <span className="flex flex-col items-start leading-tight">
          <span>{rangeLabel(value)}</span>
          <span className="text-[11px] font-normal text-muted">{rangeDates(value)}</span>
        </span>
        <span aria-hidden className="text-[10px] text-muted">▼</span>
      </button>
      {open && (
        <div role="dialog" aria-label="Choose date range" className="absolute right-0 z-30 mt-2 max-h-[75vh] w-72 overflow-y-auto rounded-xl border border-line bg-surface p-1.5 shadow-xl">
          <div className="mb-1 border-b border-line px-3 pt-2 pb-3">
            <p className="mb-2 text-sm font-medium text-ink">Custom</p>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-ink-2">
                From
                <input type="date" value={start} max={end || today} onChange={(e) => setStart(e.target.value)} className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink" />
              </label>
              <label className="text-xs text-ink-2">
                To
                <input type="date" value={end} min={start} max={today} onChange={(e) => setEnd(e.target.value)} className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink" />
              </label>
            </div>
            <button
              disabled={!customValid}
              onClick={() => {
                onChange({ ...value, preset: "custom", start, end });
                setOpen(false);
              }}
              className="mt-2.5 w-full rounded-lg bg-accent py-1.5 text-sm font-medium text-accent-ink disabled:opacity-40"
            >
              Apply
            </button>
          </div>
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => {
                onChange({ ...value, preset: p.key, ...presetRange(p.key) });
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-surface-2"
            >
              {p.label}
              {value.preset === p.key && <span className="font-bold text-accent" aria-label="selected">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
