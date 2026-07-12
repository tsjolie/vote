import { vi } from "vitest";

export interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

interface FakeResult {
  status: number;
  data?: unknown;
}

function fakeResponse(status: number, data: unknown) {
  const text = data === undefined ? "" : JSON.stringify(data);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    async text() {
      return text;
    },
  } as unknown as Response;
}

/**
 * Install a fetch mock. `handler` maps (url, method) to a status + JSON body.
 * Returns the recorded calls array (mutated as calls arrive).
 */
export function installFetch(
  handler: (url: string, method: string, body: unknown) => FakeResult,
): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, opts: RequestInit = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const body = opts.body ? JSON.parse(opts.body as string) : undefined;
      calls.push({
        url,
        method,
        headers: (opts.headers as Record<string, string>) || {},
        body,
      });
      const { status, data } = handler(url, method, body);
      return fakeResponse(status, data);
    }),
  );
  return calls;
}

export function restoreFetch() {
  vi.unstubAllGlobals();
}
