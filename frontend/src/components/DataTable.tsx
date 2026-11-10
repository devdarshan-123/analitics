import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  /** Value used for sorting and search; omit to make the column unsortable. */
  value?: (row: T) => number | string | null;
  align?: "left" | "right";
  className?: string;
}

export function DataTable<T>({ rows, columns, rowKey, defaultSort, searchable = false, searchPlaceholder = "Search…", rowClassName, pageSize = 25, emptyText = "No rows" }: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  defaultSort?: { key: string; dir: "asc" | "desc" };
  searchable?: boolean;
  searchPlaceholder?: string;
  rowClassName?: (row: T) => string;
  pageSize?: number;
  emptyText?: string;
}) {
  const [sort, setSort] = useState(defaultSort);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(pageSize);

  const visible = useMemo(() => {
    let out = rows;
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => columns.some((c) => String(c.value?.(r) ?? "").toLowerCase().includes(q)));
    }
    const col = sort && columns.find((c) => c.key === sort.key);
    if (col?.value) {
      const dir = sort!.dir === "asc" ? 1 : -1;
      out = [...out].sort((a, b) => {
        const av = col.value!(a);
        const bv = col.value!(b);
        if (av == null) return 1; // missing values always last
        if (bv == null) return -1;
        return (typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv))) * dir;
      });
    }
    return out;
  }, [rows, columns, sort, query]);

  const toggle = (c: Column<T>) => {
    if (!c.value) return;
    setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === "desc" ? "asc" : "desc" } : { key: c.key, dir: "desc" }));
  };

  return (
    <div>
      {searchable && (
        <div className="mb-3">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:w-72"
          />
        </div>
      )}
      <div className="-mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5">
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-muted">
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                  className={`py-2 pr-4 font-medium last:pr-0 ${c.align === "right" ? "text-right" : "text-left"} ${c.className ?? ""}`}
                >
                  {c.value ? (
                    <button onClick={() => toggle(c)} className={`inline-flex items-center gap-1 hover:text-ink ${sort?.key === c.key ? "text-ink" : ""}`}>
                      {c.label}
                      <span aria-hidden className="text-[10px]">{sort?.key === c.key ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}</span>
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.slice(0, limit).map((r) => (
              <tr key={rowKey(r)} className={`border-b border-line last:border-0 hover:bg-surface-2 ${rowClassName?.(r) ?? ""}`}>
                {columns.map((c) => (
                  <td key={c.key} className={`py-2 pr-4 align-top last:pr-0 ${c.align === "right" ? "text-right tabular" : ""} ${c.className ?? ""}`}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length === 0 && <p className="py-6 text-center text-sm text-muted">{query ? `No rows match “${query}”` : emptyText}</p>}
      {visible.length > limit && (
        <button onClick={() => setLimit((l) => l + pageSize)} className="mt-3 text-sm font-medium text-accent hover:underline">
          Show more ({visible.length - limit} remaining)
        </button>
      )}
    </div>
  );
}
