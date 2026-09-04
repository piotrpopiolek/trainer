/** Offline-aware satellite progress snapshot (server state only; no local engine). */

import { ApiError } from "@/lib/api";
import { openUserDb } from "@/lib/db/open";
import {
  getSatelliteProgress,
  listSatelliteProgress,
} from "@/features/training/api";
import type { SatelliteProgressItem } from "@/lib/schemas";

const SNAPSHOT_KEY = "list";

export async function putSatelliteProgressSnapshot(
  userId: string,
  items: SatelliteProgressItem[],
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("satellite_progress", {
    id: SNAPSHOT_KEY,
    schema_version: 1,
    items,
    updated_at: new Date().toISOString(),
  });
  for (const item of items) {
    await db.put("satellite_progress", {
      id: item.id,
      schema_version: 1,
      item,
      updated_at: new Date().toISOString(),
    });
  }
}

export async function getCachedSatelliteProgressList(
  userId: string,
): Promise<SatelliteProgressItem[] | null> {
  const db = await openUserDb(userId);
  const row = await db.get("satellite_progress", SNAPSHOT_KEY);
  if (!row || !Array.isArray(row.items)) return null;
  return row.items as SatelliteProgressItem[];
}

export async function getCachedSatelliteProgressItem(
  userId: string,
  exerciseId: string,
): Promise<SatelliteProgressItem | null> {
  const db = await openUserDb(userId);
  const row = await db.get("satellite_progress", exerciseId);
  if (row?.item && typeof row.item === "object") {
    return row.item as SatelliteProgressItem;
  }
  const list = await getCachedSatelliteProgressList(userId);
  return list?.find((i) => i.id === exerciseId) ?? null;
}

export async function listSatelliteProgressCached(
  userId: string,
): Promise<SatelliteProgressItem[]> {
  try {
    const items = await listSatelliteProgress();
    await putSatelliteProgressSnapshot(userId, items);
    return items;
  } catch (err) {
    const cached = await getCachedSatelliteProgressList(userId);
    if (cached) return cached;
    if (err instanceof ApiError && !navigator.onLine) {
      return [];
    }
    throw err;
  }
}

export async function getSatelliteProgressCached(
  userId: string,
  exerciseId: string,
): Promise<SatelliteProgressItem> {
  try {
    const item = await getSatelliteProgress(exerciseId);
    const db = await openUserDb(userId);
    await db.put("satellite_progress", {
      id: item.id,
      schema_version: 1,
      item,
      updated_at: new Date().toISOString(),
    });
    return item;
  } catch (err) {
    const cached = await getCachedSatelliteProgressItem(userId, exerciseId);
    if (cached) return cached;
    throw err;
  }
}
