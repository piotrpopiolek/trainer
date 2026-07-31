import { z } from "zod";

/** Every versioned API/JSONB document requires schema_version (FR-046). */
export const schemaVersion = z.number().int().gte(1);

export const meSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  email: z.string().nullable(),
  display_name: z.string().nullable(),
  locale: z.string(),
  timezone: z.string(),
  onboarding_completed: z.boolean(),
  health_disclaimer_accepted: z.boolean(),
  csrf_token: z.string(),
});

export type Me = z.infer<typeof meSchema>;

export const disclaimerSchema = z.object({
  schema_version: schemaVersion,
  document_id: z.string().uuid(),
  slug: z.string(),
  version: z.string(),
  locale: z.string(),
  title: z.string(),
  body: z.string(),
  content_hash: z.string().length(64),
});

export type Disclaimer = z.infer<typeof disclaimerSchema>;

export const todayCcExerciseSchema = z.object({
  schema_version: schemaVersion,
  exercise_id: z.string().uuid(),
  slug: z.string().nullable().optional(),
  name: z.string(),
  current_step_number: z.number(),
  advance: z.unknown().nullable().optional(),
  regress: z.unknown().nullable().optional(),
  standards: z
    .object({
      beginner: z.unknown(),
      intermediate: z.unknown(),
      progression: z.unknown(),
    })
    .nullable()
    .optional(),
  step_name: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  execution: z.string().nullable().optional(),
  rationale: z.string().nullable().optional(),
  technique: z.string().nullable().optional(),
});

export const todaySatelliteSchema = z.object({
  schema_version: schemaVersion,
  exercise_id: z.string().uuid(),
  name: z.string(),
  exercise_type: z.string(),
  schedule_kind: z.string().nullable().optional(),
  schedule_category: z.string().nullable().optional(),
  current_step_number: z.number().nullable().optional(),
  step_name: z.string().nullable().optional(),
  active_metrics: activeMetricsSchema.nullable().optional(),
  goal: satelliteGoalSchema.nullable().optional(),
  config_version_id: z.string().uuid().nullable().optional(),
  config_hash: z.string().nullable().optional(),
});

export const progressionEventSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  exercise_id: z.string().uuid(),
  session_id: z.string().uuid().nullable().optional(),
  event_type: z.string(),
  from_step: z.number(),
  to_step: z.number(),
  reason: z.string().nullable().optional(),
  created_at: z.string(),
});

export type ProgressionEvent = z.infer<typeof progressionEventSchema>;

export const progressItemSchema = z.object({
  schema_version: schemaVersion,
  exercise_id: z.string().uuid(),
  current_step_number: z.number(),
  fail_streak: z.number(),
  last_session_at: z.string().nullable().optional(),
  is_active: z.boolean(),
});

export type ProgressItem = z.infer<typeof progressItemSchema>;

export const sessionLogSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  exercise_id: z.string().uuid(),
  exercise_kind: z.string(),
  section: z.string(),
  step_number: z.number().nullable().optional(),
  exercise_name_snapshot: z.string(),
  step_label_snapshot: z.string().nullable().optional(),
  skipped: z.boolean(),
  sets: z.unknown().nullable().optional(),
  goal_met: z.boolean(),
  counts_for_progression: z.boolean(),
  progression_skipped: z.string().nullable().optional(),
  satellite_config_version_id: z.string().uuid().nullable().optional(),
  satellite_config_hash: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
});

export const sessionSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  performed_at: z.string(),
  local_date: z.string(),
  notes: z.string().nullable().optional(),
  revision: z.number(),
  deleted_at: z.string().nullable().optional(),
  logs: z.array(sessionLogSchema).default([]),
  progression_events: z.array(progressionEventSchema).default([]),
  progress: z.array(progressItemSchema).default([]),
});

export type Session = z.infer<typeof sessionSchema>;

export const todaySchema = z.object({
  schema_version: schemaVersion,
  local_date: z.string(),
  timezone: z.string(),
  split_day: z.number().nullable(),
  is_rest_day: z.boolean(),
  cc_day_override: z.number().nullable().optional(),
  requested_locale: z.string(),
  resolved_locale: z.string(),
  cc_exercises: z.array(todayCcExerciseSchema),
  satellites: z.array(todaySatelliteSchema),
  sessions: z.array(sessionSchema),
  progress: z.array(progressItemSchema),
});

export type Today = z.infer<typeof todaySchema>;

export const satelliteSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  name: z.string(),
  exercise_type: z.string(),
  active_metrics: z.unknown(),
  schedule_kind: z.string(),
  weekdays: z.array(z.number()).nullable().optional(),
  schedule_category: z.string().nullable().optional(),
  revision: z.number(),
  current_config_version_id: z.string().uuid().nullable().optional(),
  config_hash: z.string().nullable().optional(),
  steps: z.array(z.record(z.unknown())),
});

export type Satellite = z.infer<typeof satelliteSchema>;

export const measurementSchema = z.object({
  schema_version: schemaVersion,
  id: z.string().uuid(),
  measured_at: z.string(),
  local_date: z.string(),
  metrics: z.record(z.unknown()),
  notes: z.string().nullable().optional(),
  revision: z.number(),
});

export type Measurement = z.infer<typeof measurementSchema>;
