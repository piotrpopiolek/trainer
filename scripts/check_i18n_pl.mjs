/**
 * Fail CI when source uses i18n keys missing from the matching pl-PL namespace.
 * Namespace = locale filename stem (common.json -> "common").
 * Usage: node scripts/check_i18n_pl.mjs
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "frontend", "src");
const LOCALE_DIR = path.join(SRC, "locales", "pl-PL");
const DEFAULT_NS = "common";

function walk(dir) {
  /** @type {string[]} */
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "locales" || entry.name === "test") continue;
      out.push(...walk(full));
    } else if (/\.(tsx?|jsx?)$/.test(entry.name) && !/\.(test|spec)\./.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function flatten(obj, prefix = "") {
  /** @type {Set<string>} */
  const keys = new Set();
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    if (prefix) keys.add(prefix);
    return keys;
  }
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      for (const child of flatten(v, next)) keys.add(child);
    } else {
      keys.add(next);
    }
  }
  return keys;
}

/** @returns {Map<string, Set<string>>} namespace -> keys */
function loadNamespaces() {
  /** @type {Map<string, Set<string>>} */
  const namespaces = new Map();
  if (!fs.existsSync(LOCALE_DIR)) {
    console.error(`Missing locale dir: ${LOCALE_DIR}`);
    process.exit(1);
  }
  for (const file of fs.readdirSync(LOCALE_DIR)) {
    if (!file.endsWith(".json")) continue;
    const ns = file.slice(0, -".json".length);
    const data = JSON.parse(fs.readFileSync(path.join(LOCALE_DIR, file), "utf8"));
    namespaces.set(ns, flatten(data));
  }
  if (!namespaces.has(DEFAULT_NS)) {
    console.error(`Missing required namespace file: ${DEFAULT_NS}.json`);
    process.exit(1);
  }
  return namespaces;
}

/**
 * @param {string} text
 * @returns {string}
 */
function detectDefaultNs(text) {
  const match = text.match(/useTranslation\(\s*(['"])([^'"]+)\1/);
  return match?.[2] ?? DEFAULT_NS;
}

/**
 * @param {string} raw
 * @param {string} defaultNs
 * @returns {{ ns: string, key: string }}
 */
function splitKey(raw, defaultNs) {
  const idx = raw.indexOf(":");
  if (idx > 0) {
    return { ns: raw.slice(0, idx), key: raw.slice(idx + 1) };
  }
  return { ns: defaultNs, key: raw };
}

const T_CALL_RE = /(?:\bi18n\.t\b|\.t|\bt)\(\s*(['"`])([^'"`]+)\1/g;
const I18N_KEY_RE = /\bi18nKey\s*=\s*(['"`])([^'"`]+)\1/g;

const namespaces = loadNamespaces();
/** @type {Map<string, string[]>} */
const missing = new Map();

/**
 * @param {string} ns
 * @param {string} key
 * @param {string} file
 */
function recordMissing(ns, key, file) {
  const id = `${ns}:${key}`;
  const list = missing.get(id) ?? [];
  list.push(file);
  missing.set(id, list);
}

for (const file of walk(SRC)) {
  const text = fs.readFileSync(file, "utf8");
  const defaultNs = detectDefaultNs(text);
  const rel = path.relative(ROOT, file);

  for (const re of [T_CALL_RE, I18N_KEY_RE]) {
    re.lastIndex = 0;
    for (const match of text.matchAll(re)) {
      const raw = match[2];
      if (!raw || raw.includes("${")) continue;
      const { ns, key } = splitKey(raw, defaultNs);
      const keys = namespaces.get(ns);
      if (!keys || !keys.has(key)) {
        recordMissing(ns, key, rel);
      }
    }
  }
}

if (missing.size > 0) {
  console.error("Missing pl-PL i18n keys (namespace:key):\n");
  for (const [id, files] of [...missing.entries()].sort()) {
    console.error(`  - ${id}`);
    for (const f of files) console.error(`      ${f}`);
  }
  process.exit(1);
}

const totalKeys = [...namespaces.values()].reduce((n, s) => n + s.size, 0);
console.log(
  `i18n gate OK — ${namespaces.size} namespace(s), ${totalKeys} pl-PL keys, no missing references`,
);
