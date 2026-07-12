// Thin typed client for /api/v1. State-changing requests carry the
// X-Requested-With header required by the backend CSRF guard (§11).

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  const opts: RequestInit = { method, credentials: "same-origin", headers };
  if (method !== "GET") {
    headers["X-Requested-With"] = "fetch";
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (res.status === 204) return undefined as T;
  let data: any = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    // FastAPI reports errors as {detail: "..."} for HTTPException, or
    // {detail: [{msg, loc, ...}]} for request-validation (422) failures.
    const raw = data?.detail;
    let detail: string;
    if (typeof raw === "string") detail = raw;
    else if (Array.isArray(raw)) detail = raw[0]?.msg || "Request failed";
    else if (raw && typeof raw.msg === "string") detail = raw.msg;
    else detail = res.statusText || "Request failed";
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  put: <T>(p: string, body?: unknown) => request<T>("PUT", p, body),
  del: <T>(p: string, body?: unknown) => request<T>("DELETE", p, body),
};

// ---- shared types ----
export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  created_at: string;
}

export interface OptionOut {
  id: string;
  label: string;
  position: number;
}

export interface QuestionView extends OptionOut {}

export interface PollMeta {
  id: string;
  slug: string;
  title: string;
  status: "open" | "closed";
  closes_at: string | null;
  closed_at: string | null;
  created_at: string;
  creator_username: string | null;
}

export interface Round {
  round: number;
  counts: Record<string, number>;
  eliminated: string | null;
  tiebreak_used: null | "borda" | "first_choice" | "random";
}

export interface Tally {
  question_id: string;
  total_ballots: number;
  winner_option_id: string | null;
  rounds: Round[];
}
