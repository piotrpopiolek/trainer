/** Same-origin API client (FR-005a). Cookie session — credentials required. */

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;

  constructor(status: number, errorCode: string) {
    super(errorCode);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
  }
}

export type ApiJsonOptions = RequestInit & {
  csrfToken?: string | null;
};

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  return fetch(path.startsWith("/") ? path : `/api/${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
}

function pathToUrl(path: string): string {
  return path.startsWith("/") ? path : `/api/${path}`;
}

export async function apiJson<T>(path: string, init: ApiJsonOptions = {}): Promise<T> {
  const { csrfToken, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (rest.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const res = await fetch(pathToUrl(path), {
    ...rest,
    credentials: "include",
    headers,
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const code =
      data &&
      typeof data === "object" &&
      "error_code" in data &&
      typeof (data as { error_code: unknown }).error_code === "string"
        ? (data as { error_code: string }).error_code
        : `http_${res.status}`;
    throw new ApiError(res.status, code);
  }

  return data as T;
}

export function googleStartUrl(): string {
  return "/api/auth/google/start";
}
