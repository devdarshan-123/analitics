export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public hint: string | null = null) {
    super(message);
  }
}

/** Fetch from our own backend only (/api/*). Errors arrive as {"error": {code, message, hint}}. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the backend. Is the API server running on port 8000?");
  }
  if (!res.ok) {
    let body: any = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error */
    }
    const e = body?.error;
    if (res.status === 401 && !path.startsWith("/auth")) window.dispatchEvent(new Event("auth:expired"));
    throw new ApiError(
      res.status,
      e?.code ?? `http_${res.status}`,
      e?.message ?? (typeof body?.detail === "string" ? body.detail : `Request failed (HTTP ${res.status})`),
      e?.hint ?? null,
    );
  }
  return res.json() as Promise<T>;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
