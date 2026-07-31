import { describe, expect, it } from "vitest";

import { errorCodeToI18nKey } from "@/lib/errors";

describe("errorCodeToI18nKey Stage 1 satellite codes", () => {
  it.each([
    ["satellite_config_required", "errors.satelliteConfigRequired"],
    ["satellite_config_mismatch", "errors.satelliteConfigMismatch"],
    ["satellite_config_hash_invalid", "errors.satelliteConfigHashInvalid"],
    ["invalid_weight_kg", "errors.invalidWeightKg"],
    ["empty_set", "errors.emptySet"],
    ["stage1_goal_only_one_step", "errors.stage1GoalOnlyOneStep"],
    ["bilateral_not_allowed_when_require_both_sides", "errors.bilateralNotAllowed"],
    ["unknown_code_xyz", "errors.generic"],
  ] as const)("%s → %s", (code, key) => {
    expect(errorCodeToI18nKey(code)).toBe(key);
  });
});
