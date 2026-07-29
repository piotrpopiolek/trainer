import { openUserDb } from "@/lib/db/open";
import type { CachedConflict } from "@/lib/db/types";

export async function putSessionCache(
  userId: string,
  session: Record<string, unknown>,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("sessions", session);
}

export async function deleteSessionCache(userId: string, id: string): Promise<void> {
  const db = await openUserDb(userId);
  await db.delete("sessions", id);
}

export async function putMeasurementCache(
  userId: string,
  row: Record<string, unknown>,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("measurements", row);
}

export async function putSatelliteCache(
  userId: string,
  row: Record<string, unknown>,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("satellites", row);
}

export async function putProgressCache(
  userId: string,
  rows: Record<string, unknown>[],
): Promise<void> {
  const db = await openUserDb(userId);
  const tx = db.transaction("progress", "readwrite");
  await Promise.all(rows.map((r) => tx.store.put(r)));
  await tx.done;
}

export async function replaceProgressCache(
  userId: string,
  rows: Record<string, unknown>[],
): Promise<void> {
  const db = await openUserDb(userId);
  const tx = db.transaction("progress", "readwrite");
  await tx.store.clear();
  await Promise.all(rows.map((r) => tx.store.put(r)));
  await tx.done;
}

export async function applyTombstone(
  userId: string,
  entityType: string,
  id: string,
): Promise<void> {
  const db = await openUserDb(userId);
  if (entityType === "workout_session") await db.delete("sessions", id);
  else if (entityType === "body_measurement") await db.delete("measurements", id);
  else if (entityType === "satellite") await db.delete("satellites", id);
}

export async function upsertConflict(
  userId: string,
  conflict: CachedConflict,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("conflicts", conflict);
}

export async function listConflicts(userId: string): Promise<CachedConflict[]> {
  const db = await openUserDb(userId);
  const all = await db.getAll("conflicts");
  return all.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function acknowledgeConflict(userId: string, id: string): Promise<void> {
  const db = await openUserDb(userId);
  const row = await db.get("conflicts", id);
  if (row) await db.put("conflicts", { ...row, acknowledged: true });
}

export async function listCachedSessions(userId: string): Promise<Record<string, unknown>[]> {
  const db = await openUserDb(userId);
  return db.getAll("sessions");
}

export async function listCachedProgress(userId: string): Promise<Record<string, unknown>[]> {
  const db = await openUserDb(userId);
  return db.getAll("progress");
}
