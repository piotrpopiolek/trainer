import { describe, expect, it } from "vitest";

import { indexPushResultsByMutationId } from "@/features/sync/flush";

describe("flush ACK by mutation ID (FR-072a)", () => {
  it("indexes results by client_mutation_id regardless of order", () => {
    const a = "018f0000-0000-7000-8000-0000000000a1";
    const b = "018f0000-0000-7000-8000-0000000000a2";
    const map = indexPushResultsByMutationId([
      {
        schema_version: 1,
        client_mutation_id: b,
        status: "rejected",
        error_code: "legal_required",
      },
      {
        schema_version: 1,
        client_mutation_id: a,
        status: "applied",
      },
    ]);
    expect(map.get(a)?.status).toBe("applied");
    expect(map.get(b)?.status).toBe("rejected");
    expect(map.get(b)?.error_code).toBe("legal_required");
  });

  it("returns undefined for missing mutation (truncated)", () => {
    const map = indexPushResultsByMutationId([
      {
        schema_version: 1,
        client_mutation_id: "018f0000-0000-7000-8000-0000000000a1",
        status: "applied",
      },
    ]);
    expect(map.get("018f0000-0000-7000-8000-0000000000ff")).toBeUndefined();
  });
});
