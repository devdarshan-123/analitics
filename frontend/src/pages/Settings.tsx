import { useState, type FormEvent, type ReactNode } from "react";
import { Badge, Button, Card, ErrorState, InfoNote, TableSkeleton } from "../components/ui";
import {
  useClarityProjects,
  useClarityStatus,
  useConnectionTest,
  useDeleteProject,
  useProperties,
  useSaveProject,
  useSyncClarity,
  useToggleProject,
} from "../hooks/queries";
import { fmtDate, fmtDateTime, timeAgo } from "../lib/format";
import { useSelectedProperty } from "../lib/property";
import type { ClarityProject, ConnectionTest, PropertyInfo, SyncResult } from "../types";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line py-2.5 last:border-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  );
}

function QuotaMeter({ used, limit, guard }: { used: number; limit: number; guard: number }) {
  return (
    <div>
      <div className="flex gap-1" role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used} aria-label="Clarity API calls used today">
        {Array.from({ length: limit }, (_, i) => (
          <div
            key={i}
            className={`h-2.5 flex-1 rounded-sm ${i < used ? (used >= guard ? "bg-bad" : "bg-accent") : i >= guard ? "border border-dashed border-line" : "bg-surface-2"}`}
          />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {used} of {limit} used today (UTC) by this project. The app stops at {guard} to keep one call in reserve.
      </p>
    </div>
  );
}

const statusTone = (s: string) => (s === "success" ? "good" : s === "failed" ? "bad" : s === "partial" ? "warn" : "neutral");

function TestResult({ result }: { result: ConnectionTest | undefined }) {
  if (!result) return null;
  const hint = result.details.hint;
  return (
    <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${result.ok ? "bg-good-bg" : "bg-bad-bg"}`} role="status">
      <p className="font-medium text-ink">
        <span aria-hidden>{result.ok ? "✓ " : "✕ "}</span>
        {result.message}
      </p>
      {typeof hint === "string" && <p className="mt-1 text-xs break-words text-ink-2">{hint}</p>}
    </div>
  );
}

function SyncOutcome({ result }: { result: SyncResult }) {
  return (
    <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${result.status === "failed" ? "bg-bad-bg" : result.status === "partial" ? "bg-warn-bg" : "bg-good-bg"}`} role="status">
      <p className="font-medium text-ink">{result.message}</p>
      {result.projects.length > 1 &&
        result.projects.map((p) => (
          <p key={p.property_id} className="mt-0.5 text-xs text-ink-2">
            <span className="tabular">{p.property_id}</span>
            {p.label ? ` (${p.label})` : ""}: {p.status} — {p.message}
          </p>
        ))}
      {result.projects.length <= 1 &&
        result.errors.map((e) => (
          <p key={e} className="mt-0.5 text-xs text-ink-2">
            {e}
          </p>
        ))}
    </div>
  );
}

// ---------------------------------------------------------------- selected property's Clarity sync
function ClaritySyncCard() {
  const { property } = useSelectedProperty();
  const status = useClarityStatus();
  const sync = useSyncClarity();
  const s = status.data;
  const name = property?.propertyName ?? "selected property";

  return (
    <Card title={`Clarity sync · ${name}`} subtitle="Scheduled daily for every linked project; reads are served from the database" className="lg:row-span-2">
      {status.isLoading ? (
        <TableSkeleton rows={7} />
      ) : status.error ? (
        <ErrorState error={status.error} onRetry={() => status.refetch()} />
      ) : s && !s.linked ? (
        <InfoNote>No Clarity project is linked to this property. Link one in “Clarity projects” below to start collecting behaviour data.</InfoNote>
      ) : s ? (
        <>
          {s.mock_mode && (
            <div className="mb-4">
              <InfoNote tone="warn">MOCK_MODE is on: syncs use generated data and don't call Clarity.</InfoNote>
            </div>
          )}
          {s.project && !s.project.enabled && (
            <div className="mb-4">
              <InfoNote tone="warn">This Clarity project is disabled: it's skipped by the daily sync. Stored history is still shown.</InfoNote>
            </div>
          )}
          <QuotaMeter used={s.calls_used_today} limit={s.daily_limit} guard={s.safety_limit} />
          <dl className="mt-4">
            <Row label="Last successful sync">{s.last_successful_sync ? `${fmtDateTime(s.last_successful_sync)} (${timeAgo(s.last_successful_sync)})` : "Never"}</Row>
            <Row label="Last run">
              {s.last_run ? (
                <span className="flex items-center gap-2">
                  <Badge tone={statusTone(s.last_run.status)}>{s.last_run.status}</Badge>
                  <span className="text-xs text-muted">
                    {s.last_run.trigger} · {timeAgo(s.last_run.started_at)}
                  </span>
                </span>
              ) : (
                "—"
              )}
            </Row>
            <Row label="Next scheduled run">{s.scheduler_enabled ? fmtDateTime(s.next_scheduled_run) : "Scheduler disabled (ENABLE_SCHEDULER=false)"}</Row>
            <Row label="History starts">{fmtDate(s.history_start, { day: "numeric", month: "short", year: "numeric" })}</Row>
            <Row label="Latest snapshot">{fmtDate(s.latest_snapshot, { day: "numeric", month: "short", year: "numeric" })}</Row>
            <Row label="API token">{s.token_configured ? <Badge tone="good">✓ configured</Badge> : <Badge tone="bad">✕ missing</Badge>}</Row>
          </dl>
          {s.last_run?.message && <pre className="mt-3 rounded-lg bg-surface-2 p-3 text-xs whitespace-pre-wrap text-ink-2">{s.last_run.message}</pre>}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={!s.sync_available || sync.isPending} onClick={() => sync.mutate({})}>
              {sync.isPending && !sync.variables?.all ? "Syncing…" : "Sync this project now"}
            </Button>
            <span className="text-xs text-muted">
              {s.quota_exhausted
                ? "Clarity reported this project's daily quota as used up."
                : !s.token_configured
                  ? "Add an API token first."
                  : s.project && !s.project.enabled
                    ? "Enable the project to sync it."
                    : !s.sync_available
                      ? "Disabled: today's quota is nearly used."
                      : "Uses up to 5 calls; snapshots already stored for yesterday are skipped."}
            </span>
          </div>
          {sync.data && !sync.variables?.all && <SyncOutcome result={sync.data} />}
          {sync.error && !sync.variables?.all && (
            <div className="mt-3">
              <ErrorState error={sync.error} />
            </div>
          )}
        </>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------- Clarity project mapping
function ProjectForm({ property, project, onDone }: { property: PropertyInfo | { propertyId: string; propertyName: string }; project?: ClarityProject; onDone: () => void }) {
  const save = useSaveProject();
  const [label, setLabel] = useState(project?.label ?? "");
  const [token, setToken] = useState("");
  const needsToken = !project || !project.has_token;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(
      { ga_property_id: property.propertyId, label, api_token: token.trim() || undefined, enabled: project?.enabled ?? true },
      { onSuccess: onDone },
    );
  };

  return (
    <form onSubmit={submit} className="mt-2 grid gap-3 rounded-lg border border-line bg-surface-2/60 p-3 sm:grid-cols-[1fr_1.4fr_auto] sm:items-end">
      <label className="text-xs text-ink-2">
        Label <span className="text-muted">(optional)</span>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          maxLength={200}
          placeholder={property.propertyName}
          className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-muted"
        />
      </label>
      <label className="text-xs text-ink-2">
        Clarity API token {project?.has_token && <span className="text-muted">(leave blank to keep the current one)</span>}
        <input
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          required={needsToken && project?.token_source !== "mock"}
          placeholder="Clarity → Settings → Data Export → Generate new API token"
          className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-muted"
        />
      </label>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : project ? "Save" : "Link"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {save.error && (
        <div className="sm:col-span-3">
          <ErrorState error={save.error} />
        </div>
      )}
      <p className="text-xs text-muted sm:col-span-3">
        Tokens are encrypted on the server (CLARITY_TOKEN_ENCRYPTION_KEY) and never sent back to the browser. Each Clarity project has its own 10 API
        calls per day.
      </p>
    </form>
  );
}

function TokenBadge({ p }: { p: ClarityProject }) {
  if (!p.has_token) return <Badge tone="bad">✕ no token</Badge>;
  const label = { db: "saved", env: ".env", mock: "mock" }[p.token_source];
  return <Badge tone="good">✓ {label}</Badge>;
}

function ProjectsCard() {
  const properties = useProperties(true);
  const projects = useClarityProjects();
  const toggle = useToggleProject();
  const remove = useDeleteProject();
  const syncAll = useSyncClarity();
  const [editing, setEditing] = useState<string | null>(null);

  const byProperty = new Map((projects.data ?? []).map((p) => [p.ga_property_id, p]));
  const known = new Set((properties.data ?? []).map((p) => p.propertyId));
  // Projects whose property is no longer visible (removed access, allowlist) are still listed so they can be cleaned up.
  const orphans = (projects.data ?? []).filter((p) => !known.has(p.ga_property_id));
  const rows: { property: PropertyInfo | { propertyId: string; propertyName: string; accountName: string }; project?: ClarityProject; orphan?: boolean }[] = [
    ...(properties.data ?? []).map((p) => ({ property: p, project: byProperty.get(p.propertyId) })),
    ...orphans.map((p) => ({ property: { propertyId: p.ga_property_id, propertyName: p.label || `Property ${p.ga_property_id}`, accountName: "Not in property list" }, project: p, orphan: true })),
  ];
  const enabledCount = (projects.data ?? []).filter((p) => p.enabled).length;
  const actionError = toggle.error ?? remove.error;

  return (
    <Card
      title="Clarity projects"
      subtitle="Link each site's Microsoft Clarity project to its GA4 property"
      className="lg:col-span-2"
      actions={
        <Button onClick={() => syncAll.mutate({ all: true })} disabled={syncAll.isPending || enabledCount === 0}>
          {syncAll.isPending && syncAll.variables?.all ? "Syncing…" : `Sync all ${enabledCount || ""} now`}
        </Button>
      }
    >
      {properties.isLoading || projects.isLoading ? (
        <TableSkeleton rows={4} />
      ) : projects.error ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : (
        <>
          {properties.error && (
            <div className="mb-3">
              <ErrorState error={properties.error} />
            </div>
          )}
          <ul className="divide-y divide-line">
            {rows.map(({ property, project, orphan }) => {
              const isEditing = editing === property.propertyId;
              return (
                <li key={property.propertyId} className="py-3">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <div className="min-w-0 flex-1 basis-56">
                      <p className="truncate text-sm font-medium text-ink">{property.propertyName}</p>
                      <p className="truncate text-xs text-muted">
                        {property.accountName} · <span className="tabular">{property.propertyId}</span>
                      </p>
                    </div>
                    {project ? (
                      <>
                        <div className="flex min-w-0 basis-64 flex-wrap items-center gap-2 text-xs text-ink-2">
                          {project.label && <span className="max-w-[10rem] truncate text-ink">{project.label}</span>}
                          <TokenBadge p={project} />
                          {!project.enabled && <Badge>disabled</Badge>}
                          {orphan && <Badge tone="warn">property not visible</Badge>}
                          <span className="tabular" title="Clarity API calls used today (UTC)">
                            {project.quota_exhausted ? "quota used up" : `${project.calls_used_today}/10 today`}
                          </span>
                          {project.last_run && (
                            <span className="flex items-center gap-1">
                              <Badge tone={statusTone(project.last_run.status)}>{project.last_run.status}</Badge>
                              <span className="text-muted">{timeAgo(project.last_run.started_at)}</span>
                            </span>
                          )}
                        </div>
                        <div className="flex gap-1">
                          <Button variant="ghost" onClick={() => setEditing(isEditing ? null : property.propertyId)}>
                            Edit
                          </Button>
                          <Button variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate({ id: project.id, enabled: !project.enabled })}>
                            {project.enabled ? "Disable" : "Enable"}
                          </Button>
                          {project.token_source !== "env" && (
                            <Button
                              variant="ghost"
                              disabled={remove.isPending}
                              onClick={() =>
                                window.confirm(`Unlink the Clarity project from ${property.propertyName}? Stored history is kept and comes back if you link it again.`) &&
                                remove.mutate(project.id)
                              }
                            >
                              Remove
                            </Button>
                          )}
                        </div>
                      </>
                    ) : (
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted">Not linked</span>
                        {!isEditing && <Button onClick={() => setEditing(property.propertyId)}>Link Clarity project</Button>}
                      </div>
                    )}
                  </div>
                  {isEditing && <ProjectForm property={property} project={project} onDone={() => setEditing(null)} />}
                </li>
              );
            })}
          </ul>
          {actionError && (
            <div className="mt-3">
              <ErrorState error={actionError} />
            </div>
          )}
          {syncAll.data && syncAll.variables?.all && <SyncOutcome result={syncAll.data} />}
          {syncAll.error && syncAll.variables?.all && (
            <div className="mt-3">
              <ErrorState error={syncAll.error} />
            </div>
          )}
          <p className="mt-3 text-xs text-muted">
            Projects from <code>CLARITY_TOKENS</code> / <code>CLARITY_API_TOKEN</code> in .env show as “.env” and can be disabled but not removed here.
            The daily sync runs each enabled project independently, so one failing or hitting its quota doesn't affect the others.
          </p>
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- page
export function Settings() {
  const { property } = useSelectedProperty();
  const status = useClarityStatus();
  const gaTest = useConnectionTest("ga");
  const clarityTest = useConnectionTest("clarity");
  const s = status.data;
  const name = property?.propertyName ?? "the default property";

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <ClaritySyncCard />

      <Card title="Google Analytics 4" subtitle={`Runs a small uncached report against ${name}`}>
        <Button onClick={() => gaTest.mutate(false)} disabled={gaTest.isPending}>
          {gaTest.isPending ? "Testing…" : "Test GA connection"}
        </Button>
        <TestResult result={gaTest.data} />
        {gaTest.error && <ErrorState error={gaTest.error} />}
      </Card>

      <Card title="Microsoft Clarity" subtitle="Checks this property's project; a live test spends 1 of its 10 daily API calls">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => clarityTest.mutate(false)} disabled={clarityTest.isPending || !s?.linked}>
            Check configuration
          </Button>
          <Button
            variant="ghost"
            disabled={clarityTest.isPending || !s?.sync_available}
            onClick={() => window.confirm("A live test uses 1 of this Clarity project's 10 daily API calls. Continue?") && clarityTest.mutate(true)}
          >
            Live test (uses 1 call)
          </Button>
        </div>
        {s && !s.linked && <p className="mt-2 text-xs text-muted">No Clarity project linked to {name}.</p>}
        <TestResult result={clarityTest.data} />
        {clarityTest.error && <ErrorState error={clarityTest.error} />}
      </Card>

      <ProjectsCard />
    </div>
  );
}

