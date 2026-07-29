import { openUserDb } from "@/lib/db/open";
import {
  META_DEVICE_ID,
  META_LAST_PULL,
  META_PERSISTED,
  META_USER_ID,
} from "@/lib/db/types";

export async function getMeta<T>(userId: string, key: string): Promise<T | null> {
  const db = await openUserDb(userId);
  const row = await db.get("meta", key);
  return (row?.value as T | undefined) ?? null;
}

export async function setMeta(userId: string, key: string, value: unknown): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("meta", { key, value });
}

export async function getOrCreateDeviceId(userId: string): Promise<string> {
  const existing = await getMeta<string>(userId, META_DEVICE_ID);
  if (existing) return existing;
  const id = crypto.randomUUID();
  await setMeta(userId, META_DEVICE_ID, id);
  await setMeta(userId, META_USER_ID, userId);
  return id;
}

export async function getLastPullServerTime(userId: string): Promise<string | null> {
  return getMeta<string>(userId, META_LAST_PULL);
}

export async function setLastPullServerTime(userId: string, iso: string): Promise<void> {
  await setMeta(userId, META_LAST_PULL, iso);
}

export async function getPersistedFlag(userId: string): Promise<boolean | null> {
  return getMeta<boolean>(userId, META_PERSISTED);
}

export async function setPersistedFlag(userId: string, value: boolean): Promise<void> {
  await setMeta(userId, META_PERSISTED, value);
}
