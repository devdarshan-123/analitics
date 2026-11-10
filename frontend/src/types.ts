export type Format = "number" | "percent" | "duration" | "decimal";

export interface RangeInfo { start: string; end: string }

export interface KpiMetric {
  key: string;
  label: string;
  value: number | null;
  previous: number | null;
  change_pct: number | null;
  format: Format;
}

export interface GAOverview { range: RangeInfo; previous_range: RangeInfo; metrics: KpiMetric[] }

export interface TimeseriesPoint {
  date: string;
  activeUsers: number;
  sessions: number;
  screenPageViews: number;
  prev_date: string | null;
  prev_activeUsers: number | null;
  prev_sessions: number | null;
  prev_screenPageViews: number | null;
}
export interface GATimeseries { range: RangeInfo; compare: boolean; points: TimeseriesPoint[] }

export interface ChannelRow {
  channel: string;
  sessions: number;
  activeUsers: number;
  engagementRate: number;
  keyEvents: number;
  prev_sessions: number | null;
  change_pct: number | null;
}
export interface GAChannels { range: RangeInfo; rows: ChannelRow[] }

export interface SourceRow { source: string; medium: string; sessions: number; activeUsers: number; engagementRate: number; keyEvents: number }
export interface GASources { range: RangeInfo; rows: SourceRow[] }

export interface NameCount { name: string; value: number }
export interface GAGeo {
  range: RangeInfo;
  countries: { country: string; activeUsers: number; sessions: number }[];
  cities: { city: string; country: string; activeUsers: number }[];
}
export interface GATech { range: RangeInfo; devices: NameCount[]; browsers: NameCount[]; operatingSystems: NameCount[] }
export interface GAEvents { range: RangeInfo; rows: { eventName: string; eventCount: number; totalUsers: number }[] }
export interface GARealtime { activeUsers: number; byCountry: NameCount[]; byDevice: NameCount[]; byPage: NameCount[]; fetched_at: string }

export interface ClarityDay {
  date: string;
  sessions: number | null;
  botSessions: number | null;
  users: number | null;
  pagesPerSession: number | null;
  scrollDepth: number | null;
  activeTime: number | null;
  totalTime: number | null;
}
export interface ClarityOverview {
  range: RangeInfo;
  history_start: string | null;
  latest_date: string | null;
  kpis: KpiMetric[];
  series: ClarityDay[];
  backfill: ClarityDay | null;
}

export type SignalKey = "dead" | "rage" | "quickback" | "excessive_scroll" | "error_click" | "script_error";
export type FrustrationPoint = { date: string; sessions: number | null } & {
  [K in `${SignalKey}_pct` | `${SignalKey}_count`]: number | null;
};
export interface ClarityPageRow {
  url: string;
  path: string;
  days: number;
  sessions: number | null;
  scrollDepth: number | null;
  activeTime: number | null;
  dead_pct: number | null;
  rage_pct: number | null;
  quickback_pct: number | null;
  excessive_scroll_pct: number | null;
  error_click_pct: number | null;
  script_error_pct: number | null;
  dead_count: number | null;
  rage_count: number | null;
}
export interface ClarityFrustration {
  range: RangeInfo;
  history_start: string | null;
  signals: { key: SignalKey; label: string; metric: string }[];
  series: FrustrationPoint[];
  by_page: ClarityPageRow[];
}
export interface ClarityBreakdown {
  dimension: string;
  snapshot_date: string | null;
  rows: { value: string; sessions: number | null; users: number | null; scrollDepth: number | null; activeTime: number | null; dead_pct: number | null; rage_pct: number | null }[];
}

export interface SyncRunInfo {
  started_at: string;
  finished_at: string | null;
  trigger: string;
  status: string;
  calls_made: number;
  snapshots_stored: number;
  message: string;
}
export interface ClarityStatus {
  property_id: string;
  linked: boolean;
  project: ClarityProject | null;
  mock_mode: boolean;
  token_configured: boolean;
  last_successful_sync: string | null;
  last_run: SyncRunInfo | null;
  calls_used_today: number;
  daily_limit: number;
  safety_limit: number;
  calls_remaining: number;
  sync_available: boolean;
  quota_exhausted: boolean;
  next_scheduled_run: string | null;
  scheduler_enabled: boolean;
  history_start: string | null;
  latest_snapshot: string | null;
  utc_day: string;
}
export interface ProjectSyncResult {
  property_id: string;
  project_id: number;
  label: string;
  status: string;
  calls_made: number;
  snapshots_stored: number;
  skipped: string[];
  errors: string[];
  message: string;
}
export interface SyncResult {
  status: string;
  calls_made: number;
  snapshots_stored: number;
  skipped: string[];
  errors: string[];
  message: string;
  projects: ProjectSyncResult[];
}

export interface CombinedPageRow {
  path: string;
  pageTitle: string;
  views: number;
  users: number;
  avgEngagementTime: number;
  has_clarity: boolean;
  clarity_sessions: number | null;
  scrollDepth: number | null;
  dead_pct: number | null;
  rage_pct: number | null;
  quickback_pct: number | null;
  error_click_pct: number | null;
  dead_count: number | null;
  rage_count: number | null;
  frustration_score: number | null;
  is_problem: boolean;
  problem_reasons: string[];
}
export interface CombinedPages {
  range: RangeInfo;
  clarity_linked: boolean;
  clarity_history_start: string | null;
  thresholds: { min_views: number; min_frustration_score: number };
  rows: CombinedPageRow[];
}

export interface AuthStatus { authenticated: boolean; mock_mode: boolean }
export interface ConnectionTest { source: "ga" | "clarity"; ok: boolean; message: string; details: Record<string, string | number | boolean | null> }

// ---------------------------------------------------------------- properties & Clarity projects
export interface PropertyInfo {
  accountId: string;
  accountName: string;
  propertyId: string;
  propertyName: string;
  hasClarity: boolean;
  isDefault: boolean;
}

export interface ClarityProject {
  id: number;
  ga_property_id: string;
  label: string;
  enabled: boolean;
  token_source: "db" | "env" | "mock";
  has_token: boolean;
  created_at: string;
  calls_used_today: number;
  quota_exhausted: boolean;
  last_run: SyncRunInfo | null;
}
