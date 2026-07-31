/** Minimal RFC 8785 JCS + SHA-256 for shared satellite config golden vectors. */

import { createHash } from "node:crypto";

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

export function sha256JcsHex(document: Record<string, unknown>): string {
  const text = canonicalize(document);
  return createHash("sha256").update(text, "utf8").digest("hex");
}
