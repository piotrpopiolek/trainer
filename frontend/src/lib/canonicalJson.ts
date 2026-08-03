/** Minimal RFC 8785 JCS + SHA-256 (browser Web Crypto; FR-045 / Stage 1–2). */

function escapeString(value: string): string {
  let out = '"';
  for (const ch of value) {
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else {
      const code = ch.charCodeAt(0);
      if (code < 0x20) out += `\\u${code.toString(16).padStart(4, "0")}`;
      else out += ch;
    }
  }
  return `${out}"`;
}

export function canonicalize(value: unknown): string {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return escapeString(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("jcs_non_finite_number");
    if (!Number.isInteger(value)) throw new Error("jcs_float_forbidden");
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    const parts = keys.map(
      (key) => `${escapeString(key)}:${canonicalize(obj[key])}`,
    );
    return `{${parts.join(",")}}`;
  }
  throw new Error(`jcs_unsupported_type:${typeof value}`);
}

function bytesToHex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) {
    out += b.toString(16).padStart(2, "0");
  }
  return out;
}

/** SHA-256 over UTF-8 JCS (async — Web Crypto, works in PWA + Vitest/jsdom). */
export async function sha256JcsHex(
  document: Record<string, unknown>,
): Promise<string> {
  const text = canonicalize(document);
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return bytesToHex(new Uint8Array(digest));
}
