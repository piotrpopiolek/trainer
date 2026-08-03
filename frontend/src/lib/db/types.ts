/** IndexedDB types for F1.1 offline (FR-070 / FR-072). */

export type OutboxEntityType =
  | "legal_acceptance"
  | "workout_session"
  | "body_measurement"
  | "satellite"
  | "satellite_regression_decision";

export type OutboxOp = "upsert" | "delete";

export type OutboxStatus = "pending" | "in_flight" | "quarantine" | "synced";

export type OutboxItem = {
  schema_version: 1;
  client_mutation_id: string;
  entity_type: OutboxEntityType;
  entity_id: string;
  op: OutboxOp;
  revision: number;
  client_updated_at: string;
  payload: Record<string, unknown> | null;
  /** Prerequisite outbox mutation IDs (FR-072a). */
  depends_on: string[];
  /** Diagnostic only — which prereqs block flush (no fifth outbox status). */
  blocked_by: string[];
  status: OutboxStatus;
  attempts: number;
  transport_failures: number;
  next_attempt_at: string | null;
  last_error_code: string | null;
  conflict_id: string | null;
  created_at: string;
  updated_at: string;
};

export type SyncMeta = {
  key: string;
  value: unknown;
};

export type CachedConflict = {
  id: string;
  entity_type: string;
  entity_id: string;
  conflict_kind: string;
  created_at: string;
  acknowledged: boolean;
  winning_revision?: number | null;
  losing_summary?: string | null;
};

export const META_LAST_PULL = "last_pull_server_time";
export const META_DEVICE_ID = "device_id";
export const META_PERSISTED = "storage_persisted";
export const META_USER_ID = "user_id";
