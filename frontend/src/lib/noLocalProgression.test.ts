import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      found.push(...sourceFiles(full));
      continue;
    }
    if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\./.test(name)) {
      found.push(full);
    }
  }
  return found;
}

describe("no second progression engine in the PWA", () => {
  it("keeps CC and satellite evaluation on the server", () => {
    const hits: string[] = [];
    for (const file of sourceFiles(srcRoot)) {
      const rel = path.relative(srcRoot, file).replaceAll("\\", "/");
      const text = readFileSync(file, "utf8");
      if (/fail_sessions/.test(text) && rel !== "lib/satelliteContracts.ts") {
        hits.push(`${rel}: fail_sessions`);
      }
      if (/satellite_goal_met|CcProgressionEvaluator|advance_threshold_met/.test(text)) {
        hits.push(`${rel}: evaluator`);
      }
    }
    expect(hits).toEqual([]);
  });
});
