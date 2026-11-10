import { useMutation, useQuery, useQueryClient, type Query } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { api, post } from "../lib/api";
import { useSelectedProperty, withProperty } from "../lib/property";
import { rangeQuery, type RangeState } from "../lib/range";
import type {
  AuthStatus,
  ClarityBreakdown,
  ClarityFrustration,
  ClarityOverview,
  ClarityProject,
  ClarityStatus,
  CombinedPages,
  ConnectionTest,
  GAChannels,
  GAEvents,
  GAGeo,
  GAOverview,
  GARealtime,
  GASources,
  GATech,
  GATimeseries,
  PropertyInfo,
  SyncResult,
} from "../types";

interface GAMap {
  overview: GAOverview;
  timeseries: GATimeseries;
  channels: GAChannels;
  sources: GASources;
  geo: GAGeo;
  tech: GATech;
  events: GAEvents;
}

// Only these endpoints change shape when compare is on; others ignore it (keeps the cache key tight).
const COMPARE_AWARE = new Set(["timeseries", "channels"]);

/**
 * Keep showing the previous range's data while a new range loads — but never another property's data.
 * Query keys are [source, propertyId, ...].
 */
function samePropertyPlaceholder(pid: string | null) {
  return <T,>(prev: T | undefined, prevQuery: Query<T, Error, T, readonly unknown[]> | undefined) =>
    prevQuery && prevQuery.queryKey[1] === pid ? prev : undefined;
}

/** Property-scoped query: waits for the property list, keys and URLs include the property. */
function usePropertyQuery<T>(source: string, keyParts: unknown[], path: string, extra: { refetchInterval?: number; enabled?: boolean } = {}) {
  const { propertyId, ready } = useSelectedProperty();
  return useQuery({
    queryKey: [source, propertyId, ...keyParts],
    queryFn: () => api<T>(withProperty(path, propertyId)),
    placeholderData: samePropertyPlaceholder(propertyId),
    enabled: ready && (extra.enabled ?? true),
    refetchInterval: extra.refetchInterval,
  });
}

export function useGA<K extends keyof GAMap>(name: K, r: RangeState) {
  const q = rangeQuery(r, COMPARE_AWARE.has(name));
  return usePropertyQuery<GAMap[K]>("ga", [name, q], `/ga/${name}${q}`);
}

export function useRealtime() {
  return usePropertyQuery<GARealtime>("ga", ["realtime"], "/ga/realtime", { refetchInterval: 60_000 });
}

export function useClarityOverview(r: RangeState, enabled = true) {
  const q = rangeQuery(r, false);
  return usePropertyQuery<ClarityOverview>("clarity", ["overview", q], `/clarity/overview${q}`, { enabled });
}

export function useClarityFrustration(r: RangeState, enabled = true) {
  const q = rangeQuery(r, false);
  return usePropertyQuery<ClarityFrustration>("clarity", ["frustration", q], `/clarity/frustration${q}`, { enabled });
}

export function useClarityBreakdown(dimension: "Device" | "Source" | "Country", enabled = true) {
  return usePropertyQuery<ClarityBreakdown>("clarity", ["breakdown", dimension], `/clarity/breakdown?dimension=${dimension}`, { enabled });
}

export function useClarityStatus() {
  return usePropertyQuery<ClarityStatus>("clarity", ["status"], "/clarity/status", { refetchInterval: 5 * 60_000 });
}

export function useCombinedPages(r: RangeState) {
  const q = rangeQuery(r, false);
  return usePropertyQuery<CombinedPages>("combined", ["pages", q], `/combined/pages${q}`);
}

export function useAuth() {
  return useQuery({ queryKey: ["auth"], queryFn: () => api<AuthStatus>("/auth/me"), staleTime: Infinity, retry: false });
}

/** Every GA4 property the service account can read. Cached server-side for 1h; `refresh` bypasses that. */
export function useProperties(enabled: boolean) {
  return useQuery({ queryKey: ["properties"], queryFn: () => api<PropertyInfo[]>("/properties"), staleTime: 60 * 60_000, enabled });
}

export function useRefreshProperties() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<PropertyInfo[]>("/properties?refresh=true"),
    onSuccess: (data) => qc.setQueryData(["properties"], data),
    onError: () => qc.invalidateQueries({ queryKey: ["properties"] }),
  });
}

const invalidateClarity = (qc: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    qc.invalidateQueries({ queryKey: ["clarity"] }),
    qc.invalidateQueries({ queryKey: ["combined"] }),
    qc.invalidateQueries({ queryKey: ["clarity-projects"] }),
    qc.invalidateQueries({ queryKey: ["properties"] }),
  ]);

/** Sync the selected property's Clarity project, or every enabled project with `all`. */
export function useSyncClarity() {
  const qc = useQueryClient();
  const { propertyId } = useSelectedProperty();
  return useMutation({
    mutationFn: (opts: { all?: boolean } = {}) => post<SyncResult>(opts.all ? "/admin/clarity/sync?all=true" : withProperty("/admin/clarity/sync", propertyId)),
    onSettled: () => invalidateClarity(qc),
  });
}

export function useConnectionTest(source: "ga" | "clarity") {
  const qc = useQueryClient();
  const { propertyId } = useSelectedProperty();
  return useMutation({
    mutationFn: (live: boolean = false) => post<ConnectionTest>(withProperty(`/admin/test/${source}${live ? "?live=true" : ""}`, propertyId)),
    onSettled: () => qc.invalidateQueries({ queryKey: ["clarity"] }),
  });
}

// ---------------------------------------------------------------- Clarity project mapping
export function useClarityProjects() {
  return useQuery({ queryKey: ["clarity-projects"], queryFn: () => api<ClarityProject[]>("/admin/clarity/projects") });
}

export interface ProjectInput {
  ga_property_id: string;
  label: string;
  api_token?: string;
  enabled: boolean;
}

export function useSaveProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectInput) => post<ClarityProject>("/admin/clarity/projects", body),
    onSuccess: () => invalidateClarity(qc),
  });
}

export function useToggleProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api<ClarityProject>(`/admin/clarity/projects/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => invalidateClarity(qc),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<ClarityProject>(`/admin/clarity/projects/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateClarity(qc),
  });
}

/** Most recent successful data fetch across all queries — drives "Last updated". */
export function useLastUpdated(): number {
  const qc = useQueryClient();
  const cache = qc.getQueryCache();
  return useSyncExternalStore(
    (cb) => cache.subscribe(cb),
    () =>
      cache
        .getAll()
        .filter((q) => !["auth", "properties", "clarity-projects"].includes(q.queryKey[0] as string))
        .reduce((max, q) => Math.max(max, q.state.dataUpdatedAt), 0),
  );
}
