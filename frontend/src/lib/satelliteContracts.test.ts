import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { canonicalize, sha256JcsHex } from "@/lib/canonicalJson";
import {
  satelliteLogResultSchema,
  satelliteRulesSchema,
  satelliteSetSchema,
} from "@/lib/satelliteContracts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const vectorsPath = path.join(
  root,
  "backend",
  "tests",
  "fixtures",
  "satellite_jcs_vectors.json",
);

describe("satellite contracts Stage 1", () => {
  it("matches shared JCS golden vectors", () => {
    const payload = JSON.parse(readFileSync(vectorsPath, "utf8")) as {
      vectors: Array<{
        document: Record<string, unknown>;
        jcs: string;
        sha256_hex: string;
      }>;
    };
    for (const vector of payload.vectors) {
      expect(canonicalize(vector.document)).toBe(vector.jcs);
      expect(sha256JcsHex(vector.document)).toBe(vector.sha256_hex);
    }
  });

  it("rejects zero goal thresholds", () => {
    expect(() =>
      satelliteRulesSchema.parse({
        schema_version: 1,
        goal: { type: "reps", sets: 0, min_reps: 10 },
      }),
    ).toThrow();
    expect(() =>
      satelliteRulesSchema.parse({
        schema_version: 1,
        goal: { type: "reps", sets: 1, min_reps: 0 },
      }),
    ).toThrow();
  });

  it("rejects float weight and bad sides and empty sets", () => {
    expect(() =>
      satelliteSetSchema.parse({ reps: 10, weight_kg: 20 as unknown as string }),
    ).toThrow();
    expect(() => satelliteSetSchema.parse({ reps: 10, sides: "L" })).toThrow();
    expect(() => satelliteSetSchema.parse({})).toThrow();
  });

  it("rejects CC fields on satellite rules", () => {
    expect(() =>
      satelliteRulesSchema.parse({
        schema_version: 1,
        goal: { type: "reps", sets: 3, min_reps: 10 },
        advance: { sets: 3 },
      }),
    ).toThrow();
  });

  it("accepts type C completed log without sets", () => {
    const parsed = satelliteLogResultSchema.parse({
      schema_version: 1,
      completed: true,
      sets: [],
    });
    expect(parsed.completed).toBe(true);
    expect(parsed.sets).toEqual([]);
  });

  it("accepts Hip Thrust both-sides weight sets", () => {
    const parsed = satelliteLogResultSchema.parse({
      schema_version: 1,
      completed: null,
      sets: [
        { reps: 10, weight_kg: "20.000", sides: "left" },
        { reps: 10, weight_kg: "20.000", sides: "right" },
      ],
    });
    expect(parsed.sets).toHaveLength(2);
  });
});
