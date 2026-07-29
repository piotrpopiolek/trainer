import { z } from "zod";

import { apiJson } from "@/lib/api";
import { schemaVersion } from "@/lib/schemas";

export const syncPushItemResultSchema = z.object({
  schema_version: schemaVersion.optional().default(1),
  client_mutation_id: z.string().uuid(),
  status: z.enum([
    "applied",
    "idempotent",
    "conflict_lost",
    "conflict_tie",
    "session_immutable_after_evaluate",
    "rejected",
  ]),
  error_code: z.string().nullable().optional(),
  conflict_id: z.string().uuid().nullable().optional(),
  progression_skipped: z.string().nullable().optional(),
  winning_revision: z.number().nullable().optional(),
  winning_updated_at: z.string().nullable().optional(),
});

export const syncPushResponseSchema = z.object({
  schema_version: schemaVersion.optional().default(1),
  truncated: z.boolean().optional().default(false),
  results: z.array(syncPushItemResultSchema),
  progression_events: z.array(z.record(z.unknown())).optional().default([]),
  progress: z.array(z.record(z.unknown())).optional().default([]),
});

export type SyncPushResponse = z.infer<typeof syncPushResponseSchema>;

export const syncPullResponseSchema = z.object({
  schema_version: schemaVersion.optional().default(1),
  server_time: z.string(),
  requested_locale: z.string(),
  resolved_locale: z.string(),
  catalog_version: z.number().nullable().optional(),
  resync_required: z.boolean().optional().default(false),
  sessions: z.array(z.record(z.unknown())).optional().default([]),
  measurements: z.array(z.record(z.unknown())).optional().default([]),
  satellites: z.array(z.record(z.unknown())).optional().default([]),
  progress: z.array(z.record(z.unknown())).optional().default([]),
  progression_events: z.array(z.record(z.unknown())).optional().default([]),
  conflicts: z.array(z.record(z.unknown())).optional().default([]),
  tombstones: z
    .array(
      z.object({
        schema_version: schemaVersion.optional().default(1),
        entity_type: z.string(),
        id: z.string().uuid(),
        deleted_at: z.string(),
        revision: z.number(),
      }),
    )
    .optional()
    .default([]),
});

export type SyncPullResponse = z.infer<typeof syncPullResponseSchema>;

export type SyncPushItem = {
  client_mutation_id: string;
  entity_type: string;
  entity_id: string;
  op: "upsert" | "delete";
  revision: number;
  client_updated_at: string | null;
  payload: Record<string, unknown> | null;
};

export async function syncPush(
  items: SyncPushItem[],
  deviceId: string | null,
): Promise<SyncPushResponse> {
  const raw = await apiJson<unknown>("/api/sync/push", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      device_id: deviceId,
      items,
    }),
  });
  return syncPushResponseSchema.parse(raw);
}

export async function syncPull(params?: {
  since?: string | null;
  locale?: string;
  deviceId?: string | null;
}): Promise<SyncPullResponse> {
  const q = new URLSearchParams();
  if (params?.since) q.set("since", params.since);
  if (params?.locale) q.set("locale", params.locale);
  if (params?.deviceId) q.set("device_id", params.deviceId);
  const qs = q.toString();
  const raw = await apiJson<unknown>(`/api/sync/pull${qs ? `?${qs}` : ""}`);
  return syncPullResponseSchema.parse(raw);
}
