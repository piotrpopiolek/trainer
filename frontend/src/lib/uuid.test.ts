import { describe, expect, it } from "vitest";

import { newClientMutationId } from "@/lib/uuid";

describe("uuid", () => {
  it("returns uuid string", () => {
    const id = newClientMutationId();
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });
});
