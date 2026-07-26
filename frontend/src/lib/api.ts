/** Same-origin fetch helper (FR-005a). Cookie session — credentials required. */
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
