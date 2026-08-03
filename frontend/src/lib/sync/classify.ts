/** FR-072b ACK classification. */

export type PushItemStatus =
  | "applied"
  | "applied_detached"
  | "idempotent"
  | "conflict_lost"
  | "conflict_tie"
  | "session_immutable_after_evaluate"
  | "rejected";

export type AckAction =
  | { kind: "done" }
  | { kind: "conflict"; status: PushItemStatus }
  | { kind: "quarantine"; errorCode: string | null }
  | { kind: "retry"; errorCode: string | null };

const QUARANTINE_CODES = new Set([
  "revision_jump",
  "mutation_payload_mismatch",
  "legal_required",
  "duplicate_exercise_same_day",
  "satellite_limit_reached",
  "session_update_unsupported",
  "measurement_update_unsupported",
  "satellite_delete_unsupported",
  "session_date_immutable",
  "payload_required",
  "not_found",
  "unsupported_entity_type",
  "dependency_missing",
  "dependency_failed",
  "dependency_cycle",
  "recommendation_stale",
  "recommendation_not_pending",
]);

export function classifyAck(
  status: PushItemStatus,
  errorCode: string | null,
): AckAction {
  if (
    status === "applied" ||
    status === "applied_detached" ||
    status === "idempotent"
  ) {
    return { kind: "done" };
  }
  if (
    status === "conflict_lost" ||
    status === "conflict_tie" ||
    status === "session_immutable_after_evaluate"
  ) {
    return { kind: "conflict", status };
  }
  if (status === "rejected") {
    if (errorCode && QUARANTINE_CODES.has(errorCode)) {
      return { kind: "quarantine", errorCode };
    }
    // Unknown reject → quarantine (safer than silent retry loop)
    return { kind: "quarantine", errorCode };
  }
  return { kind: "retry", errorCode };
}

/** Cap 15 min with jitter (FR-072b). */
export function nextBackoffMs(attempts: number): number {
  const base = Math.min(15 * 60_000, 1000 * 2 ** Math.min(attempts, 8));
  const jitter = Math.floor(Math.random() * 500);
  return base + jitter;
}

export function nextAttemptAtIso(attempts: number, now = new Date()): string {
  return new Date(now.getTime() + nextBackoffMs(attempts)).toISOString();
}
